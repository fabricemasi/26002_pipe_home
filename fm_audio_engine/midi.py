"""MIDI (sans Qt) : quantification, swing et groove RÉVERSIBLES, transposition, vélocités,
fichiers MIDI standard (SMF type 0 / 1) en lecture et en écriture, sans dépendance.

Réversibilité : la première quantification mémorise la position d'origine (`orig_tick`,
`orig_length`) ; `unquantize` la rétablit ; quantifier de nouveau part toujours de l'origine
(pas d'accumulation d'arrondis).
"""
from __future__ import annotations

import struct
from pathlib import Path

from .project import PPQ, Note


def _origin(n: Note) -> tuple[int, int]:
    return (n.orig_tick if n.orig_tick is not None else n.tick,
            n.orig_length if n.orig_length is not None else n.length)


def quantize(notes, grid: int = PPQ // 4, strength: float = 1.0, swing: float = 0.0, ends: bool = False) -> None:
    """Aligne les débuts (et les fins si `ends`) sur la grille ; `swing` 0..1 retarde les
    positions impaires de la grille de swing × grille / 2 ; `strength` 0..1 rapproche seulement."""
    for n in notes:
        t0, l0 = _origin(n)
        n.orig_tick, n.orig_length = t0, l0
        k = round(t0 / grid)
        target = k * grid + (int(round(swing * grid / 2)) if k % 2 else 0)
        n.tick = max(0, int(round(t0 + (target - t0) * strength)))
        if ends:
            e0 = t0 + l0
            ke = max(k + 1, round(e0 / grid))
            n.length = max(1, int(round(e0 + (ke * grid - e0) * strength)) - n.tick)
        else:
            n.length = l0


def apply_groove(notes, template: list, grid: int = PPQ // 4, velocity: list | None = None) -> None:
    """Groove : décalage (ticks) et facteur de vélocité par position de grille (motif répété)."""
    for n in notes:
        t0, l0 = _origin(n)
        n.orig_tick, n.orig_length = t0, l0
        k = round(t0 / grid)
        n.tick = max(0, k * grid + int(template[k % len(template)]))
        if velocity:
            n.vel = max(1, min(127, int(round(n.vel * velocity[k % len(velocity)]))))


def unquantize(notes) -> None:
    for n in notes:
        if n.orig_tick is not None:
            n.tick = n.orig_tick
        if n.orig_length is not None:
            n.length = n.orig_length
        n.orig_tick = n.orig_length = None


def transpose(notes, semitones: int) -> None:
    for n in notes:
        n.pitch = max(0, min(127, n.pitch + semitones))


def scale_velocity(notes, factor: float, offset: int = 0) -> None:
    for n in notes:
        n.vel = max(1, min(127, int(round(n.vel * factor + offset))))


# ---------------------------------------------------------------- SMF
def _vlq(v: int) -> bytes:
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append(0x80 | (v & 0x7F))
        v >>= 7
    return bytes(reversed(out))


def _read_vlq(b: bytes, i: int) -> tuple[int, int]:
    v = 0
    while True:
        c = b[i]
        i += 1
        v = (v << 7) | (c & 0x7F)
        if not c & 0x80:
            return v, i


def write_smf(path, tracks: list, tempo=None, signatures=None, ppq: int = PPQ) -> Path:
    """`tracks` : [{"name", "channel", "notes": [Note|dict], "controllers": {cc: [[tick, val]]}}] → SMF type 1."""
    chunks = []
    meta = []
    for p in (tempo or [{"tick": 0, "bpm": 120}]):
        us = int(round(60_000_000 / float(p["bpm"])))
        meta.append((int(p["tick"]), b"\xff\x51\x03" + us.to_bytes(3, "big")))
    for s in (signatures or [{"tick": 0, "num": 4, "den": 4}]):
        den = int(s["den"]).bit_length() - 1
        meta.append((int(s["tick"]), b"\xff\x58\x04" + bytes([int(s["num"]), den, 24, 8])))
    chunks.append(_track_bytes(meta))
    for tr in tracks:
        ch = int(tr.get("channel", 0)) & 0x0F
        evs = [(0, b"\xff\x03" + _vlq(len(tr.get("name", "").encode())) + tr.get("name", "").encode())]
        for n in tr.get("notes", []):
            n = n if isinstance(n, Note) else Note.from_dict(n)
            if n.mute:
                continue
            evs.append((n.tick + n.length, bytes([0x80 | ch, n.pitch, 0])))   # note-off d'abord à égalité de tick
            evs.append((n.tick, bytes([0x90 | ch, n.pitch, max(1, n.vel)])))
        for cc, pts in (tr.get("controllers") or {}).items():
            for t, v in pts:
                evs.append((int(t), bytes([0xB0 | ch, int(cc) & 0x7F, int(v) & 0x7F])))
        chunks.append(_track_bytes(evs))
    data = b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), ppq) + b"".join(chunks)
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def _track_bytes(events: list) -> bytes:
    # tri stable : à tick égal, l'ordre d'insertion (note-off avant note-on) est conservé
    events = sorted(enumerate(events), key=lambda e: (e[1][0], 0 if e[1][1][0] & 0xF0 == 0x80 else 1, e[0]))
    out, last = bytearray(), 0
    for _, (t, msg) in events:
        out += _vlq(max(0, t - last)) + msg
        last = t
    out += b"\x00\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(out)) + bytes(out)


def read_smf(path, ppq_out: int = PPQ) -> dict:
    """Lit un SMF (type 0 ou 1) → {"ppq", "tempo", "signatures", "tracks": [{"name", "channel", "notes", "controllers"}]}.
    Les positions sont ramenées à `ppq_out`. Une note sans note-off est fermée à la fin de sa piste (signalée)."""
    b = Path(path).read_bytes()
    if b[:4] != b"MThd":
        raise ValueError("pas un fichier MIDI standard")
    hlen, fmt, ntr, div = struct.unpack(">IHHH", b[4:14])
    if div & 0x8000:
        raise ValueError("division SMPTE non prise en charge")
    scale = ppq_out / div
    i = 8 + hlen
    tempo, sigs, tracks, warnings = [], [], [], []
    for _ in range(ntr):
        if b[i:i + 4] != b"MTrk":
            raise ValueError("piste MIDI invalide")
        ln = struct.unpack(">I", b[i + 4:i + 8])[0]
        j, end = i + 8, i + 8 + ln
        t, status = 0, 0
        name, notes, ccs, open_, chans = "", [], {}, {}, set()
        while j < end:
            dt, j = _read_vlq(b, j)
            t += dt
            c = b[j]
            if c == 0xFF:
                typ = b[j + 1]
                ml, j = _read_vlq(b, j + 2)
                data = b[j:j + ml]
                j += ml
                if typ == 0x51:
                    tempo.append({"tick": int(round(t * scale)), "bpm": round(60_000_000 / int.from_bytes(data, "big"), 6)})
                elif typ == 0x58:
                    sigs.append({"tick": int(round(t * scale)), "num": data[0], "den": 2 ** data[1]})
                elif typ == 0x03:
                    name = data.decode("utf-8", "replace")
                continue
            if c in (0xF0, 0xF7):
                ml, j = _read_vlq(b, j + 1)
                j += ml
                continue
            if c & 0x80:
                status = c
                j += 1
            kind, ch = status & 0xF0, status & 0x0F
            n_data = 1 if kind in (0xC0, 0xD0) else 2
            d = b[j:j + n_data]
            j += n_data
            chans.add(ch)
            if kind == 0x90 and d[1] > 0:
                open_.setdefault((ch, d[0]), []).append((t, d[1]))
            elif kind == 0x80 or (kind == 0x90 and d[1] == 0):
                st = open_.get((ch, d[0]))
                if st:
                    t0, v = st.pop(0)
                    notes.append(Note(int(round(t0 * scale)), max(1, int(round((t - t0) * scale))), d[0], v))
            elif kind == 0xB0:
                ccs.setdefault(d[0], []).append([int(round(t * scale)), d[1]])
        for (ch, p), lst in open_.items():
            for t0, v in lst:
                notes.append(Note(int(round(t0 * scale)), max(1, int(round((t - t0) * scale))), p, v))
                warnings.append(f"note {p} sans fin (piste « {name} ») : fermée en fin de piste")
        if notes or ccs:
            notes.sort(key=lambda n: (n.tick, n.pitch))
            tracks.append({"name": name, "channel": min(chans) if chans else 0, "notes": notes, "controllers": ccs})
        i = end
    tempo.sort(key=lambda x: x["tick"])
    sigs.sort(key=lambda x: x["tick"])
    return {"ppq": ppq_out, "tempo": tempo or [{"tick": 0, "bpm": 120.0}], "signatures": sigs or [{"tick": 0, "num": 4, "den": 4}],
            "tracks": tracks, "warnings": warnings, "format": fmt}

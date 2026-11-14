"""Modèle de projet commun à FM Audio et FM Music (sans Qt).

- positions audio en échantillons (int, 64 bits côté moteur), positions musicales en ticks (PPQ 960) ;
- carte tempo identique au moteur (`TempoMap`, testée contre le C++) ;
- schéma versionné (`SCHEMA_VERSION`), migrations testées, sauvegarde transactionnelle ;
- Undo / Redo par instantanés des seules pistes touchées ; `revision` change à chaque état ;
- extensions propres à chaque éditeur conservées telles quelles (`extensions`).
"""
from __future__ import annotations

import copy
import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

SCHEMA_VERSION = 1
PPQ = 960
FORMAT_ID = "pipe-fmz-audio-project"


class ProjectError(ValueError):
    pass


class IncompatibleProject(ProjectError):
    """Projet écrit par une version plus récente : refus prudent, rien n'est réécrit."""


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:10]


# ---------------------------------------------------------------- carte tempo
class TempoMap:
    """Même calcul que `TempoMap` de graph.h : position d'un segment calculée depuis son début."""

    def __init__(self, points=None, signatures=None, sample_rate: int = 48000, ppq: int = PPQ):
        self.sr = sample_rate
        self.ppq = ppq
        pts = sorted(((int(p["tick"]), max(1.0, float(p["bpm"]))) for p in (points or [])), key=lambda x: x[0])
        if not pts or pts[0][0] != 0:
            pts.insert(0, (0, pts[0][1] if pts else 120.0))
        self.segs = []  # (tick, bpm, sample)
        for i, (tk, bpm) in enumerate(pts):
            if i == 0:
                self.segs.append((tk, bpm, 0))
            else:
                ptk, pbpm, ps = self.segs[-1]
                self.segs.append((tk, bpm, ps + self._span(tk - ptk, pbpm)))
        sigs = sorted(((int(s["tick"]), int(s["num"]), int(s["den"])) for s in (signatures or [])), key=lambda x: x[0])
        if not sigs or sigs[0][0] != 0:
            sigs.insert(0, (0, 4, 4))
        self.sigs = sigs

    def _span(self, ticks: int, bpm: float) -> int:
        # llround du C++ : arrondi au plus proche, demi-valeurs loin de zéro
        x = ticks * 60.0 * self.sr / (bpm * self.ppq)
        return int(x + 0.5) if x >= 0 else -int(-x + 0.5)

    def tick_to_sample(self, tick: int) -> int:
        k = 0
        while k + 1 < len(self.segs) and self.segs[k + 1][0] <= tick:
            k += 1
        tk, bpm, s = self.segs[k]
        return s + self._span(tick - tk, bpm)

    def sample_to_tick(self, sample: int) -> float:
        k = 0
        while k + 1 < len(self.segs) and self.segs[k + 1][2] <= sample:
            k += 1
        tk, bpm, s = self.segs[k]
        return tk + (sample - s) * bpm * self.ppq / (60.0 * self.sr)

    def bpm_at(self, tick: int) -> float:
        bpm = self.segs[0][1]
        for tk, b, _ in self.segs:
            if tk <= tick:
                bpm = b
        return bpm

    def signature_at(self, tick: int) -> tuple[int, int, int]:
        """(tick de début, numérateur, dénominateur) de la signature active."""
        cur = self.sigs[0]
        for s in self.sigs:
            if s[0] <= tick:
                cur = s
        return cur

    def bar_ticks(self, tick: int) -> int:
        _, num, den = self.signature_at(tick)
        return num * self.ppq * 4 // den

    def bar_beat(self, tick: int) -> tuple[int, int, int]:
        """(mesure, temps, ticks) à partir de 1, en suivant les changements de signature."""
        bar = 0
        for i, (st, num, den) in enumerate(self.sigs):
            end = self.sigs[i + 1][0] if i + 1 < len(self.sigs) else None
            bt = num * self.ppq * 4 // den
            if end is not None and tick >= end:
                bar += (end - st) // bt
                continue
            rel = tick - st
            beat_t = self.ppq * 4 // den
            return bar + rel // bt + 1, (rel % bt) // beat_t + 1, (rel % bt) % beat_t
        return 1, 1, 0


# ---------------------------------------------------------------- éléments
def _from(cls, d: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (d or {}).items() if k in names})


@dataclass
class Clip:
    id: str = field(default_factory=lambda: new_id("c"))
    path: str = ""                 # localisateur du média (révision épinglée)
    resource: str = ""             # identité métier (bibliothèque), vide = média libre
    revision: int = 0
    name: str = ""
    start: int = 0                 # échantillons, position sur la timeline
    offset: int = 0                # échantillons dans le média
    length: int = 0
    gain_db: float = 0.0
    polarity: bool = False
    fade_in: int = 0
    fade_out: int = 0
    fade_in_shape: int = 0
    fade_out_shape: int = 0
    rate: float = 1.0
    reverse: bool = False
    mute: bool = False
    take: str = ""                 # identifiant de la prise (comping)

    @property
    def end(self) -> int:
        return self.start + self.length

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return _from(cls, d)


@dataclass
class Note:
    tick: int = 0
    length: int = PPQ
    pitch: int = 60
    vel: int = 100
    mute: bool = False
    orig_tick: int | None = None   # position d'avant quantification (quantification réversible)
    orig_length: int | None = None

    def to_dict(self):
        d = asdict(self)
        if d["orig_tick"] is None:
            del d["orig_tick"]
        if d["orig_length"] is None:
            del d["orig_length"]
        return d

    @classmethod
    def from_dict(cls, d):
        return _from(cls, d)


@dataclass
class MidiClip:
    id: str = field(default_factory=lambda: new_id("m"))
    name: str = ""
    start_tick: int = 0
    length_tick: int = 4 * PPQ
    notes: list = field(default_factory=list)      # list[Note]
    pattern: str = ""                               # instance d'un pattern (notes du pattern, répétées)
    transpose: int = 0
    mute: bool = False
    controllers: dict = field(default_factory=dict)  # cc -> [[tick, valeur]]

    @property
    def end_tick(self) -> int:
        return self.start_tick + self.length_tick

    def to_dict(self):
        d = asdict(self)
        d["notes"] = [n.to_dict() for n in self.notes]
        return d

    @classmethod
    def from_dict(cls, d):
        c = _from(cls, d)
        c.notes = [Note.from_dict(n) for n in (d or {}).get("notes", [])]
        return c


@dataclass
class Fx:
    type: str = "gain"
    params: dict = field(default_factory=dict)
    bypass: bool = False
    sidechain: str = ""
    automation: dict = field(default_factory=dict)   # clé -> {"unit": "sample"|"tick", "points": [[t, v]]}
    name: str = ""

    def to_dict(self):
        return copy.deepcopy(asdict(self))

    @classmethod
    def from_dict(cls, d):
        return _from(cls, copy.deepcopy(d))


@dataclass
class Track:
    id: str = field(default_factory=lambda: new_id("t"))
    name: str = "Piste"
    kind: str = "audio"            # audio | instrument
    gain_db: float = 0.0
    pan: float = 0.0
    mute: bool = False
    solo: bool = False
    polarity: bool = False
    channels: int = 2
    output: str = "master"
    group: str = ""
    color: str = ""
    sends: list = field(default_factory=list)       # [{"target", "gain_db", "pre"}]
    fx: list = field(default_factory=list)          # list[Fx]
    clips: list = field(default_factory=list)       # list[Clip]
    midi_clips: list = field(default_factory=list)  # list[MidiClip]
    instrument: dict | None = None
    input: int = -1
    input_channels: int = 1
    armed: bool = False
    monitor: bool = False
    automation: dict = field(default_factory=dict)  # "gain_db" | "pan" -> {"unit", "points"}
    takes: list = field(default_factory=list)       # [{"id", "name", "clips": [Clip]}]
    comp: list = field(default_factory=list)        # [{"start", "end", "take", "xfade"}] (échantillons)

    def to_dict(self):
        d = asdict(self)
        d["fx"] = [f.to_dict() for f in self.fx]
        d["clips"] = [c.to_dict() for c in self.clips]
        d["midi_clips"] = [m.to_dict() for m in self.midi_clips]
        d["takes"] = [{"id": t["id"], "name": t.get("name", ""), "clips": [c.to_dict() for c in t["clips"]]} for t in self.takes]
        return copy.deepcopy(d)

    @classmethod
    def from_dict(cls, d):
        d = copy.deepcopy(d or {})
        t = _from(cls, d)
        t.fx = [Fx.from_dict(f) for f in d.get("fx", [])]
        t.clips = [Clip.from_dict(c) for c in d.get("clips", [])]
        t.midi_clips = [MidiClip.from_dict(m) for m in d.get("midi_clips", [])]
        t.takes = [{"id": k.get("id") or new_id("k"), "name": k.get("name", ""),
                    "clips": [Clip.from_dict(c) for c in k.get("clips", [])]} for k in d.get("takes", [])]
        return t


@dataclass
class Bus:
    id: str = field(default_factory=lambda: new_id("b"))
    name: str = "Bus"
    gain_db: float = 0.0
    pan: float = 0.0
    mute: bool = False
    output: str = "master"
    fx: list = field(default_factory=list)
    sends: list = field(default_factory=list)
    automation: dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d["fx"] = [f.to_dict() for f in self.fx]
        return copy.deepcopy(d)

    @classmethod
    def from_dict(cls, d):
        d = copy.deepcopy(d or {})
        b = _from(cls, d)
        b.fx = [Fx.from_dict(f) for f in d.get("fx", [])]
        return b


@dataclass
class Group:
    """Groupe de type VCA : gain ajouté aux membres, mute / solo propagés."""
    id: str = field(default_factory=lambda: new_id("g"))
    name: str = "Groupe"
    gain_db: float = 0.0
    mute: bool = False
    solo: bool = False


# ---------------------------------------------------------------- projet
class Project:
    def __init__(self, kind: str = "audio", name: str = "Sans titre", sample_rate: int = 48000):
        self.schema = SCHEMA_VERSION
        self.kind = kind                   # audio (FM Audio) | music (FM Music)
        self.id = new_id("p")
        self.name = name
        self.sample_rate = int(sample_rate)
        self.tempo = [{"tick": 0, "bpm": 120.0}]
        self.signatures = [{"tick": 0, "num": 4, "den": 4}]
        self.tracks: list[Track] = []
        self.buses: list[Bus] = []
        self.groups: list[Group] = []
        self.master = Bus(id="master", name="Master")
        self.patterns: dict = {}           # id -> {"name", "length_tick", "notes": [Note]}
        self.sections: list = []           # [{"tick", "name"}]
        self.markers: list = []            # [{"pos", "name"}] (échantillons)
        self.loop = {"on": False, "start": 0, "end": 0}
        self.extensions: dict = {}         # données propres à un éditeur, conservées telles quelles
        self.revision = 0
        self.history = History(self)
        self.path: str = ""

    # ---- accès
    def tempo_map(self) -> TempoMap:
        return TempoMap(self.tempo, self.signatures, self.sample_rate, PPQ)

    def track(self, tid: str) -> Track | None:
        return next((t for t in self.tracks if t.id == tid), None)

    def bus(self, bid: str) -> Bus | None:
        return self.master if bid == "master" else next((b for b in self.buses if b.id == bid), None)

    def find_clip(self, cid: str) -> tuple[Track | None, Clip | None]:
        for t in self.tracks:
            for c in t.clips:
                if c.id == cid:
                    return t, c
        return None, None

    def length_samples(self) -> int:
        tm = self.tempo_map()
        end = 0
        for t in self.tracks:
            for c in t.clips:
                end = max(end, c.end)
            for m in t.midi_clips:
                end = max(end, tm.tick_to_sample(m.end_tick))
        return end

    # ---- édition (avec historique)
    @contextmanager
    def edit(self, label: str, *track_ids: str, structure: bool = False):
        """Toute modification passe par ici : instantané avant/après des pistes touchées
        (`structure=True` : liste des pistes, bus, tempo… = tout le projet)."""
        self.history.begin(label, None if structure else list(track_ids))
        try:
            yield self
        except BaseException:
            self.history.abort()
            raise
        self.history.commit()

    def add_track(self, track: Track | None = None, index: int | None = None, **kw) -> Track:
        t = track or Track(**kw)
        with self.edit("Ajouter une piste", structure=True):
            self.tracks.insert(len(self.tracks) if index is None else index, t)
        return t

    def remove_track(self, tid: str) -> None:
        with self.edit("Supprimer une piste", structure=True):
            self.tracks = [t for t in self.tracks if t.id != tid]

    # ---- sérialisation
    def to_dict(self) -> dict:
        return {
            "format": FORMAT_ID, "schema": SCHEMA_VERSION, "kind": self.kind, "id": self.id, "name": self.name,
            "sample_rate": self.sample_rate, "tempo": copy.deepcopy(self.tempo), "signatures": copy.deepcopy(self.signatures),
            "tracks": [t.to_dict() for t in self.tracks], "buses": [b.to_dict() for b in self.buses],
            "groups": [asdict(g) for g in self.groups], "master": self.master.to_dict(),
            "patterns": {k: {"name": p.get("name", ""), "length_tick": p.get("length_tick", 4 * PPQ),
                             "notes": [n.to_dict() for n in p.get("notes", [])]} for k, p in self.patterns.items()},
            "sections": copy.deepcopy(self.sections), "markers": copy.deepcopy(self.markers), "loop": dict(self.loop),
            "extensions": copy.deepcopy(self.extensions), "revision": self.revision,
        }

    def _load_dict(self, d: dict, keep_history: bool = False) -> None:
        self.kind = d.get("kind", "audio")
        self.id = d.get("id") or new_id("p")
        self.name = d.get("name", "Sans titre")
        self.sample_rate = int(d.get("sample_rate", 48000))
        self.tempo = d.get("tempo") or [{"tick": 0, "bpm": 120.0}]
        self.signatures = d.get("signatures") or [{"tick": 0, "num": 4, "den": 4}]
        self.tracks = [Track.from_dict(t) for t in d.get("tracks", [])]
        self.buses = [Bus.from_dict(b) for b in d.get("buses", [])]
        self.groups = [_from(Group, g) for g in d.get("groups", [])]
        self.master = Bus.from_dict(d.get("master") or {"id": "master", "name": "Master"})
        self.master.id = "master"
        self.patterns = {k: {"name": p.get("name", ""), "length_tick": int(p.get("length_tick", 4 * PPQ)),
                             "notes": [Note.from_dict(n) for n in p.get("notes", [])]} for k, p in (d.get("patterns") or {}).items()}
        self.sections = d.get("sections", [])
        self.markers = d.get("markers", [])
        self.loop = d.get("loop") or {"on": False, "start": 0, "end": 0}
        self.extensions = d.get("extensions", {})
        self.revision = int(d.get("revision", 0))
        if not keep_history:
            self.history = History(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        d = migrate(d)
        p = cls(d.get("kind", "audio"))
        p._load_dict(d)
        return p

    def save(self, path: str | os.PathLike | None = None) -> Path:
        path = Path(path or self.path)
        if not path.name:
            raise ProjectError("chemin de sauvegarde manquant")
        save_json_atomic(path, self.to_dict())
        self.path = str(path)
        self.history.mark_saved()
        return path

    @classmethod
    def load(cls, path: str | os.PathLike) -> "Project":
        try:
            raw = json.loads(Path(path).read_text("utf-8"))
        except (OSError, ValueError) as e:
            raise ProjectError(f"projet illisible : {path} ({e})")
        p = cls.from_dict(raw)
        p.path = str(path)
        return p


def save_json_atomic(path: Path, data: dict) -> None:
    """Écriture transactionnelle : .part + fsync + remplacement atomique ; l'ancien fichier reste en .bak."""
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    text = json.dumps(data, ensure_ascii=False, indent=1)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    json.loads(Path(tmp).read_text("utf-8"))  # relu avant de remplacer
    if path.exists():
        bak = path.with_name(path.name + ".bak")
        try:
            os.replace(path, bak)
        except OSError:
            pass
    os.replace(tmp, path)


# ---------------------------------------------------------------- migrations
def _migrate_0_to_1(d: dict) -> dict:
    """v0 (prototype) : `bpm` scalaire, positions de clips en secondes (`start_s`, `length_s`)."""
    d = copy.deepcopy(d)
    sr = int(d.get("sample_rate", 48000))
    if "tempo" not in d:
        d["tempo"] = [{"tick": 0, "bpm": float(d.pop("bpm", 120.0))}]
    for t in d.get("tracks", []):
        for c in t.get("clips", []):
            for k_s, k in (("start_s", "start"), ("length_s", "length"), ("offset_s", "offset")):
                if k_s in c:
                    c[k] = int(round(float(c.pop(k_s)) * sr))
    d["schema"] = 1
    return d


MIGRATIONS = {0: _migrate_0_to_1}


def migrate(d: dict) -> dict:
    if not isinstance(d, dict):
        raise ProjectError("projet invalide")
    if d.get("format") not in (None, FORMAT_ID):
        raise ProjectError(f"format inconnu : {d.get('format')}")
    v = int(d.get("schema", 0))
    if v > SCHEMA_VERSION:
        raise IncompatibleProject(f"projet au schéma {v}, plus récent que cette version ({SCHEMA_VERSION}) : ouverture refusée")
    while v < SCHEMA_VERSION:
        d = MIGRATIONS[v](d)
        v = int(d["schema"])
    return d


# ---------------------------------------------------------------- historique
class History:
    """Undo / Redo par instantanés des pistes touchées (ou de tout le projet pour la structure)."""

    def __init__(self, project: Project, limit: int = 200):
        self.p = project
        self.limit = limit
        self.undo_stack: list = []
        self.redo_stack: list = []
        self._pending = None
        self._depth = 0
        self._saved_rev = project.revision
        self.listeners: list = []

    def _snap(self, ids):
        if ids is None:
            d = self.p.to_dict()
            d.pop("revision", None)
            return ("all", d)
        return ("tracks", {tid: (self.p.track(tid).to_dict() if self.p.track(tid) else None) for tid in ids})

    def begin(self, label: str, ids) -> None:
        self._depth += 1
        if self._depth > 1:      # édition imbriquée : englobée dans la première
            if ids is None and self._pending and self._pending[1][0] != "all":
                self._pending = (self._pending[0], self._snap(None), None)
            return
        self._pending = (label, self._snap(ids), ids)

    def abort(self) -> None:
        self._depth -= 1
        if self._depth == 0 and self._pending:
            self._restore(self._pending[1])
            self._pending = None

    def commit(self) -> None:
        self._depth -= 1
        if self._depth > 0 or not self._pending:
            return
        label, before, ids = self._pending
        self._pending = None
        after = self._snap(None if before[0] == "all" else list(before[1].keys()))
        if after == before:
            return
        self.undo_stack.append((label, before, after))
        del self.undo_stack[:-self.limit]
        self.redo_stack.clear()
        self._bump()

    def _bump(self) -> None:
        self.p.revision += 1
        for cb in list(self.listeners):
            cb()

    def _restore(self, snap) -> None:
        kind, data = snap
        if kind == "all":
            rev = self.p.revision
            self.p._load_dict(dict(data, revision=rev), keep_history=True)
            return
        for tid, td in data.items():
            idx = next((i for i, t in enumerate(self.p.tracks) if t.id == tid), None)
            if td is None:
                if idx is not None:
                    del self.p.tracks[idx]
            elif idx is None:
                self.p.tracks.append(Track.from_dict(td))
            else:
                self.p.tracks[idx] = Track.from_dict(td)

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def undo(self) -> str | None:
        if not self.undo_stack:
            return None
        label, before, after = self.undo_stack.pop()
        self._restore(before)
        self.redo_stack.append((label, before, after))
        self._bump()
        return label

    def redo(self) -> str | None:
        if not self.redo_stack:
            return None
        label, before, after = self.redo_stack.pop()
        self._restore(after)
        self.undo_stack.append((label, before, after))
        self._bump()
        return label

    def mark_saved(self) -> None:
        self._saved_rev = self.p.revision

    @property
    def dirty(self) -> bool:
        return self.p.revision != self._saved_rev


# ---------------------------------------------------------------- compilation vers le moteur
def _auto_points(lane: dict | None, tm: TempoMap) -> list:
    if not lane:
        return []
    pts = lane.get("points", [])
    if lane.get("unit") == "tick":
        return [[tm.tick_to_sample(int(t)), float(v)] for t, v in pts]
    return [[int(t), float(v)] for t, v in pts]


def comp_clips(track: Track) -> list[Clip]:
    """Clips joués d'après le comping : segments choisis dans les prises, fondus croisés
    aux transitions. Les prises elles-mêmes restent intactes."""
    if not track.comp or not track.takes:
        return []
    takes = {k["id"]: k for k in track.takes}
    out = []
    for seg in sorted(track.comp, key=lambda s: s["start"]):
        take = takes.get(seg.get("take"))
        if not take:
            continue
        xf = int(seg.get("xfade", 0))
        s0, s1 = int(seg["start"]) - xf // 2, int(seg["end"]) + xf - xf // 2
        for c in take["clips"]:
            a, b = max(s0, c.start), min(s1, c.end)
            if b <= a:
                continue
            n = copy.deepcopy(c)
            n.id = new_id("c")
            n.offset = c.offset + int(round((a - c.start) * c.rate))
            n.start, n.length = a, b - a
            n.fade_in = xf if xf else (c.fade_in if a == c.start else 0)
            n.fade_out = xf if xf else (c.fade_out if b == c.end else 0)
            n.fade_in_shape = n.fade_out_shape = 1   # puissance constante aux transitions
            out.append(n)
    return out


def pattern_notes(project: Project, mc: MidiClip) -> list[Note]:
    """Notes jouées d'un clip MIDI : les siennes, ou celles de son pattern répété sur sa longueur."""
    if not mc.pattern:
        return mc.notes
    p = project.patterns.get(mc.pattern)
    if not p:
        return []
    plen = max(1, int(p["length_tick"]))
    out = []
    rep = 0
    while rep * plen < mc.length_tick:
        for n in p["notes"]:
            t = n.tick + rep * plen
            if t < mc.length_tick:
                out.append(Note(t, n.length, n.pitch, n.vel, n.mute))
        rep += 1
    return out


def compile_spec(project: Project, resolve=None, *, only_tracks=None) -> dict:
    """Description du graphe pour le moteur. `resolve(clip) -> chemin PCM | None` (cache des
    formats compressés) ; None = chemin du clip tel quel."""
    tm = project.tempo_map()
    groups = {g.id: g for g in project.groups}
    any_group_solo = any(g.solo for g in project.groups)
    tracks = []
    for t in project.tracks:
        if only_tracks is not None and t.id not in only_tracks:
            continue
        g = groups.get(t.group)
        gain = t.gain_db + (g.gain_db if g else 0.0)
        mute = t.mute or bool(g and g.mute)
        solo = t.solo or bool(g and g.solo)
        clips = []
        for c in list(t.clips) + comp_clips(t):
            if c.mute:
                continue
            path = resolve(c) if resolve else c.path
            clips.append({"media": path or c.path, "start": c.start, "offset": c.offset, "length": c.length,
                          "gain_db": c.gain_db, "polarity": c.polarity, "fade_in": c.fade_in, "fade_out": c.fade_out,
                          "fade_in_shape": c.fade_in_shape, "fade_out_shape": c.fade_out_shape, "rate": c.rate,
                          "reverse": c.reverse})
        midi = []
        for m in t.midi_clips:
            if m.mute:
                continue
            midi.append({"start_tick": m.start_tick, "length_tick": m.length_tick, "transpose": m.transpose,
                         "notes": [n.to_dict() for n in pattern_notes(project, m) if not n.mute]})
        tracks.append({
            "id": t.id, "name": t.name, "gain_db": gain, "pan": t.pan, "mute": mute, "solo": solo or (any_group_solo and bool(g and g.solo)),
            "polarity": t.polarity, "channels": t.channels, "output": t.output, "sends": copy.deepcopy(t.sends),
            "fx": [_fx_spec(f, tm) for f in t.fx], "clips": clips, "midi_clips": midi,
            "instrument": copy.deepcopy(t.instrument) if t.instrument else None,
            "input": t.input, "monitor": t.monitor,
            "midi_out": bool((t.instrument or {}).get("midi_out")), "midi_channel": int((t.instrument or {}).get("midi_channel", 0)),
            "automation": {k: _auto_points(v, tm) for k, v in t.automation.items()},
        })
    def bus_spec(b: Bus) -> dict:
        return {"id": b.id, "name": b.name, "gain_db": b.gain_db, "pan": b.pan, "mute": b.mute, "output": b.output,
                "sends": copy.deepcopy(b.sends), "fx": [_fx_spec(f, tm) for f in b.fx],
                "automation": {k: _auto_points(v, tm) for k, v in b.automation.items()}}
    spec = {"sample_rate": project.sample_rate, "revision": project.revision,
            "tempo": {"ppq": PPQ, "points": copy.deepcopy(project.tempo), "signatures": copy.deepcopy(project.signatures)},
            "tracks": tracks, "buses": [bus_spec(b) for b in project.buses], "master": bus_spec(project.master)}
    spec["master"].pop("output", None)
    return spec


def _fx_spec(f: Fx, tm: TempoMap) -> dict:
    return {"type": f.type, "params": copy.deepcopy(f.params), "bypass": f.bypass, "sidechain": f.sidechain,
            "automation": {k: _auto_points(v, tm) for k, v in f.automation.items()}}


def stack_loop_takes(project: Project, track_id: str) -> int:
    """Looper : les prises successives d'une boucle (une par passe) jouent ENSEMBLE, superposées au
    début de la boucle (overdub), au lieu d'être choisies une à une (comping). Annulable ; les prises
    restent des sources indépendantes. Retourne le nombre de couches."""
    t = project.track(track_id)
    loop = project.loop
    start = int(loop.get("start", 0)) if loop.get("end", 0) > loop.get("start", 0) else None
    with project.edit("Superposer les prises (looper)", track_id):
        layers = []
        for k in t.takes:
            for c in k["clips"]:
                n = Clip.from_dict(c.to_dict())
                n.id = new_id("c")
                if start is not None:
                    n.start = max(start, n.start)
                layers.append(n)
        t.clips = sorted(layers, key=lambda c: c.start)
        t.comp = []
    return len(layers)


def set_comp(project: Project, track_id: str, take_id: str, a: int, b: int, xfade: int = 480) -> None:
    """Comping : la prise `take_id` est choisie sur [a, b) ; les segments qui chevauchent sont
    rognés ou découpés ; les prises restent intactes ; les clips issus des prises (dernière prise
    posée sur la piste) laissent la place au comp. Une étape d'annulation."""
    a, b = int(min(a, b)), int(max(a, b))
    if b - a < 1:
        return
    t = project.track(track_id)
    with project.edit("Comping", track_id):
        t.clips = [c for c in t.clips if not c.take]
        out = []
        for s in sorted(t.comp, key=lambda s: s["start"]):
            if s["end"] <= a or s["start"] >= b:
                out.append(s)
                continue
            if s["start"] < a:
                out.append(dict(s, end=a))
            if s["end"] > b:
                out.append(dict(s, start=b))
        out.append({"start": a, "end": b, "take": take_id, "xfade": int(xfade)})
        t.comp = sorted(out, key=lambda s: s["start"])

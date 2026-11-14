"""Édition non destructive (sans Qt) : chaque opération modifie des RÉFÉRENCES (clips :
position, décalage, longueur, gain, fondus), jamais le fichier source. Toutes passent par
`project.edit(...)` : Undo / Redo et révision cohérents.

Positions en échantillons de la timeline. Les sélections sont des plages [a, b).
"""
from __future__ import annotations

import copy

import numpy as np

from . import wavio
from .project import Clip, Project, new_id

MIN_LEN = 1


def _clone(c: Clip) -> Clip:
    n = copy.deepcopy(c)
    n.id = new_id("c")
    return n


def _cut_piece(c: Clip, a: int, b: int) -> Clip | None:
    """Morceau [a, b) d'un clip (en coordonnées timeline), ou None si vide."""
    a, b = max(a, c.start), min(b, c.end)
    if b - a < MIN_LEN:
        return None
    n = _clone(c)
    n.offset = c.offset + int(round((a - c.start) * c.rate)) if not c.reverse else c.offset + int(round((c.end - b) * c.rate))
    n.start, n.length = a, b - a
    n.fade_in = min(c.fade_in, n.length) if a == c.start else 0
    n.fade_out = min(c.fade_out, n.length) if b == c.end else 0
    return n


def split(p: Project, track_id: str, clip_id: str, at: int) -> tuple[str, str] | None:
    t = p.track(track_id)
    c = next((x for x in t.clips if x.id == clip_id), None) if t else None
    if c is None or not (c.start < at < c.end):
        return None
    with p.edit("Scinder", track_id):
        left, right = _cut_piece(c, c.start, at), _cut_piece(c, at, c.end)
        i = t.clips.index(c)
        left.id = c.id
        t.clips[i:i + 1] = [left, right]
    return left.id, right.id


def delete_range(p: Project, track_ids, a: int, b: int, ripple: bool = False) -> None:
    """Supprime [a, b) sur les pistes ; `ripple` décale ensuite la suite vers la gauche."""
    if b <= a:
        return
    with p.edit("Supprimer", *track_ids):
        for tid in track_ids:
            t = p.track(tid)
            out = []
            for c in t.clips:
                if c.end <= a or c.start >= b:
                    if ripple and c.start >= b:
                        c.start -= b - a
                    out.append(c)
                    continue
                left, right = _cut_piece(c, c.start, a), _cut_piece(c, b, c.end)
                if left:
                    left.id = c.id
                    out.append(left)
                if right:
                    if ripple:
                        right.start -= b - a
                    out.append(right)
            t.clips = sorted(out, key=lambda x: x.start)


def crop(p: Project, track_ids, a: int, b: int, to_zero: bool = False) -> None:
    """Ne garde que [a, b) ; `to_zero` ramène la sélection au début de la timeline."""
    with p.edit("Rogner", *track_ids):
        for tid in track_ids:
            t = p.track(tid)
            out = []
            for c in t.clips:
                piece = _cut_piece(c, a, b)
                if piece:
                    piece.id = c.id
                    if to_zero:
                        piece.start -= a
                    out.append(piece)
            t.clips = out


def trim(p: Project, track_id: str, clip_id: str, new_start: int | None = None, new_end: int | None = None) -> None:
    """Déplace un bord sans déplacer le contenu (limité au média disponible si `media_frames` connu)."""
    t = p.track(track_id)
    c = next(x for x in t.clips if x.id == clip_id)
    with p.edit("Ajuster le bord", track_id):
        if new_start is not None:
            new_start = min(new_start, c.end - MIN_LEN)
            delta = new_start - c.start
            off = c.offset + int(round(delta * c.rate))
            if off < 0:                       # pas avant le début du média
                new_start -= int(np.ceil(off / c.rate))
                off = 0
                delta = new_start - c.start
            c.offset, c.start, c.length = off, new_start, c.length - delta
        if new_end is not None:
            c.length = max(MIN_LEN, new_end - c.start)
        c.fade_in = min(c.fade_in, c.length)
        c.fade_out = min(c.fade_out, c.length - c.fade_in)


def move_clips(p: Project, items, delta: int, target_track: str | None = None) -> None:
    """Déplace des clips ([(track_id, clip_id)]) de `delta` échantillons, éventuellement vers
    une autre piste. Jamais avant 0."""
    tids = {tid for tid, _ in items} | ({target_track} if target_track else set())
    with p.edit("Déplacer", *tids):
        lo = min(p.track(tid).clips[[c.id for c in p.track(tid).clips].index(cid)].start for tid, cid in items)
        delta = max(delta, -lo)
        for tid, cid in items:
            t = p.track(tid)
            c = next(x for x in t.clips if x.id == cid)
            c.start += delta
            if target_track and target_track != tid:
                t.clips.remove(c)
                p.track(target_track).clips.append(c)
        for tid in tids:
            p.track(tid).clips.sort(key=lambda x: x.start)


def copy_range(p: Project, track_ids, a: int, b: int) -> dict:
    """Presse-papiers : morceaux [a, b) par piste, positions relatives à a."""
    data = []
    for k, tid in enumerate(track_ids):
        pieces = []
        for c in p.track(tid).clips:
            piece = _cut_piece(c, a, b)
            if piece:
                piece.start -= a
                pieces.append(piece.to_dict())
        data.append(pieces)
    return {"length": b - a, "tracks": data}


def paste(p: Project, clip_board: dict, at: int, track_ids, replace: bool = True) -> list[str]:
    """Colle à `at` ; `replace` libère d'abord la place (pas de superposition involontaire)."""
    ids = []
    length = int(clip_board.get("length", 0))
    with p.edit("Coller", *track_ids):
        for tid, pieces in zip(track_ids, clip_board.get("tracks", [])):
            t = p.track(tid)
            if replace and length:
                out = []
                for c in t.clips:
                    if c.end <= at or c.start >= at + length:
                        out.append(c)
                        continue
                    for piece in (_cut_piece(c, c.start, at), _cut_piece(c, at + length, c.end)):
                        if piece:
                            out.append(piece)
                t.clips = out
            for d in pieces:
                c = Clip.from_dict(d)
                c.id = new_id("c")
                c.start += at
                t.clips.append(c)
                ids.append(c.id)
            t.clips.sort(key=lambda x: x.start)
    return ids


def set_fades(p: Project, track_id: str, clip_id: str, fade_in: int | None = None, fade_out: int | None = None,
              in_shape: int | None = None, out_shape: int | None = None) -> None:
    t = p.track(track_id)
    c = next(x for x in t.clips if x.id == clip_id)
    with p.edit("Fondus", track_id):
        if fade_in is not None:
            c.fade_in = int(max(0, min(fade_in, c.length)))
        if fade_out is not None:
            c.fade_out = int(max(0, min(fade_out, c.length - c.fade_in)))
        if in_shape is not None:
            c.fade_in_shape = in_shape
        if out_shape is not None:
            c.fade_out_shape = out_shape


def crossfade(p: Project, track_id: str, first_id: str, second_id: str, shape: int = 1) -> int:
    """Fondu enchaîné sur la zone de recouvrement de deux clips (puissance constante par défaut)."""
    t = p.track(track_id)
    a = next(x for x in t.clips if x.id == first_id)
    b = next(x for x in t.clips if x.id == second_id)
    if a.start > b.start:
        a, b = b, a
    ov = a.end - b.start
    if ov <= 0:
        return 0
    with p.edit("Fondu enchaîné", track_id):
        a.fade_out, a.fade_out_shape = ov, shape
        b.fade_in, b.fade_in_shape = ov, shape
    return ov


def set_gain(p: Project, track_id: str, clip_ids, gain_db: float) -> None:
    with p.edit("Gain", track_id):
        for c in p.track(track_id).clips:
            if c.id in clip_ids:
                c.gain_db = float(gain_db)


def invert_polarity(p: Project, track_id: str, clip_ids) -> None:
    with p.edit("Inverser la polarité", track_id):
        for c in p.track(track_id).clips:
            if c.id in clip_ids:
                c.polarity = not c.polarity


def set_rate(p: Project, track_id: str, clip_id: str, rate: float) -> None:
    """Vitesse (varispeed : durée et hauteur ensemble). Le contenu lu reste le même."""
    t = p.track(track_id)
    c = next(x for x in t.clips if x.id == clip_id)
    rate = float(min(8.0, max(0.05, rate)))
    with p.edit("Vitesse", track_id):
        content = c.length * c.rate
        c.rate = rate
        c.length = max(MIN_LEN, int(round(content / rate)))
        c.fade_in = min(c.fade_in, c.length)
        c.fade_out = min(c.fade_out, c.length - c.fade_in)


def peak_of(pcm_path: str, offset: int, length: int, chunk: int = 1 << 18) -> float:
    """Crête absolue réelle d'une plage du média (lecture par morceaux, action explicite)."""
    peak = 0.0
    pos, end = max(0, offset), offset + length
    while pos < end:
        data, _ = wavio.read(pcm_path, pos, min(chunk, end - pos))
        if data.shape[1] == 0:
            break
        peak = max(peak, float(np.max(np.abs(data))))
        pos += data.shape[1]
    return peak


def normalize(p: Project, track_id: str, clip_ids, target_db: float = -1.0, resolve=None) -> dict:
    """Normalisation de crête NON destructive : ajuste le gain du clip. Retourne {clip: gain_db}."""
    t = p.track(track_id)
    out = {}
    with p.edit("Normaliser", track_id):
        for c in t.clips:
            if c.id not in clip_ids:
                continue
            path = resolve(c) if resolve else c.path
            peak = peak_of(path, c.offset, int(np.ceil(c.length * c.rate)))
            if peak <= 0:
                continue
            c.gain_db = float(target_db - 20 * np.log10(peak))
            out[c.id] = c.gain_db
    return out

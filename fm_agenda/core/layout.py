"""Disposition des événements (sans Qt), reprise de la maquette Claude Design :
- `lay_timed` : événements horaires d'une colonne en VOIES quand ils se chevauchent (groupes de chevauchement,
  première voie libre, largeur = 1 / nombre de voies du groupe) ;
- `pack_spans` : barres « journée » d'une semaine en LIGNES (première ligne libre)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Placed:
    item: object
    a: float              # début (minutes depuis le début de la journée affichée)
    b: float              # fin
    lane: int = 0
    lanes: int = 1


def lay_timed(items: list[tuple[float, float, object]], min_len: float = 30.0) -> list[Placed]:
    """`items` : (début, fin, objet) en minutes. Un événement sans durée compte `min_len` minutes (tâche).
    Tri : début croissant, le plus long d'abord à début égal (maquette)."""
    placed = [Placed(obj, a, b if b > a else a + min_len) for a, b, obj in items]
    placed.sort(key=lambda p: (p.a, -p.b))
    groups: list[list[Placed]] = []
    group: list[Placed] | None = None
    end = -1.0
    for p in placed:
        if group is None or p.a >= end:
            group = []
            groups.append(group)
            end = p.b
        else:
            end = max(end, p.b)
        group.append(p)
    for grp in groups:
        lanes: list[float] = []
        for p in grp:
            lane = 0
            while lane < len(lanes) and lanes[lane] > p.a:
                lane += 1
            if lane == len(lanes):
                lanes.append(p.b)
            else:
                lanes[lane] = p.b
            p.lane = lane
        for p in grp:
            p.lanes = len(lanes)
    return placed


@dataclass(slots=True)
class Span:
    item: object
    first: int            # colonne de début (0 = premier jour affiché)
    last: int             # colonne de fin (incluse)
    row: int = 0
    cut_left: bool = False     # commence avant la période affichée
    cut_right: bool = False    # continue après


def pack_spans(spans: list[Span]) -> int:
    """Range les barres en lignes (ordre reçu : début croissant, la plus longue d'abord) ; rend le nombre de
    lignes."""
    rows_end: list[int] = []
    for s in spans:
        row = 0
        while row < len(rows_end) and rows_end[row] >= s.first:
            row += 1
        if row == len(rows_end):
            rows_end.append(s.last)
        else:
            rows_end[row] = s.last
        s.row = row
    return len(rows_end)

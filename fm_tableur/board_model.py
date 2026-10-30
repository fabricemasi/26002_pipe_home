"""Type « sheet » du `.mro` (SANS Qt) : un classeur posé sur le Board.

Élément = valeurs communes du Board (x, y, z, locked…) + `w`, `h` (taille dans le Board), `title`, `workbook`
(classeur au format natif, `io_native`). Une version plus ancienne de l'appli, qui ne connaît pas ce type, le garde
dans `foreign` et le réécrit tel quel (règle de la coque) ; les champs inconnus sont gardés."""
from __future__ import annotations

SHEET = "sheet"
TABLEUR_TYPES = (SHEET,)
DEFAULTS = {SHEET: {"w": 720.0, "h": 400.0, "title": "Classeur", "workbook": {}}}
MIN_W, MIN_H = 160.0, 90.0


def normalize_entity(item: dict):
    item["w"] = max(MIN_W, float(item.get("w") or DEFAULTS[SHEET]["w"]))
    item["h"] = max(MIN_H, float(item.get("h") or DEFAULTS[SHEET]["h"]))
    if not isinstance(item.get("workbook"), dict):
        item["workbook"] = {}
    if not isinstance(item.get("title"), str):
        item["title"] = "Classeur"

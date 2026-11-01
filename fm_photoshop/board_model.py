"""Type « ps_doc » du `.mro` (SANS Qt) : un document Photoshop posé sur le Board.

Élément = valeurs communes du Board (x, y, z, locked…) + `w`, `h` (taille de la présentation dans le Board), `title`,
`asset` (nom du conteneur `.fmps` dans le dossier `<board>_assets`, écrit à l'enregistrement : les pixels ne sont
JAMAIS dans le JSON), `init` (document NEUF à créer tant qu'aucun conteneur n'existe : largeur, hauteur, résolution,
fond) et `doc_w`, `doc_h` (taille en pixels du document, pour le cadre et le diagnostic si la ressource manque).
Une version plus ancienne de l'appli, qui ne connaît pas ce type, le garde dans `foreign` et le réécrit tel quel
(règle de la coque) ; les champs inconnus sont gardés."""
from __future__ import annotations

PS_DOC = "ps_doc"
PHOTOSHOP_TYPES = (PS_DOC,)
DEFAULTS = {PS_DOC: {"w": 480.0, "h": 360.0, "title": "Document", "asset": "", "init": {}, "doc_w": 0, "doc_h": 0}}
MIN_W, MIN_H = 120.0, 80.0


def normalize_entity(item: dict):
    base = DEFAULTS[PS_DOC]
    item["w"] = max(MIN_W, float(item.get("w") or base["w"]))
    item["h"] = max(MIN_H, float(item.get("h") or base["h"]))
    if not isinstance(item.get("title"), str):
        item["title"] = base["title"]
    if not isinstance(item.get("asset"), str):
        item["asset"] = ""
    if not isinstance(item.get("init"), dict):
        item["init"] = {}
    for key in ("doc_w", "doc_h"):
        try:
            item[key] = max(0, int(item.get(key) or 0))
        except (TypeError, ValueError):
            item[key] = 0


def fit_size(doc_w: int, doc_h: int, long_side: float = 480.0) -> tuple[float, float]:
    """Taille de présentation dans le Board pour un document de `doc_w` × `doc_h` pixels (même proportions)."""
    if doc_w <= 0 or doc_h <= 0:
        return 480.0, 360.0
    scale = long_side / max(doc_w, doc_h)
    return max(MIN_W, round(doc_w * scale, 1)), max(MIN_H, round(doc_h * scale, 1))

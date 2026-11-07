"""Type « pdf_doc » du `.brd` (SANS Qt) : un document PDF posé sur le Board (lien vers le fichier, jamais copié).

Élément = valeurs communes du Board + `w`, `h` (présentation), `title`, `path` (chemin absolu), `rel` (chemin
relatif au dossier du board : le lien suit un dossier de projet déplacé), `page` (page montrée), et l'AFFICHAGE du
document dans l'élément (toutes ses pages en défilement continu) : `fit` (« width » = pleine largeur, « page » =
pleine page, « » = zoom fixe `zoom`), `scroll` (défilement vertical, en points du document), `framed` (cadre déjà
calé sur la page : un élément d'avant les pages bord à bord est recalé UNE fois, `PdfItem.fit_frame_once`).
Une version de l'appli qui ne connaît pas ce type le garde dans `foreign` (règle de la coque)."""
from __future__ import annotations

import os
from pathlib import Path

PDF_DOC = "pdf_doc"
PDF_TYPES = (PDF_DOC,)
FITS = ("width", "page", "")
DEFAULTS = {PDF_DOC: {"w": 300.0, "h": 424.0, "title": "", "path": "", "rel": "", "page": 0, "fit": "width",
                      "zoom": 1.0, "scroll": 0.0, "framed": False}}
MIN_W, MIN_H = 80.0, 80.0


def normalize_entity(item: dict) -> None:
    base = DEFAULTS[PDF_DOC]
    item["w"] = max(MIN_W, float(item.get("w") or base["w"]))
    item["h"] = max(MIN_H, float(item.get("h") or base["h"]))
    for key in ("title", "path", "rel"):
        if not isinstance(item.get(key), str):
            item[key] = ""
    try:
        item["page"] = max(0, int(item.get("page") or 0))
    except (TypeError, ValueError):
        item["page"] = 0
    item["framed"] = bool(item.get("framed", False))
    if item.get("fit") not in FITS:
        item["fit"] = base["fit"]
    for key, low, high in (("zoom", 0.05, 64.0), ("scroll", 0.0, 1e7)):
        try:
            item[key] = min(high, max(low, float(item.get(key, base[key]))))
        except (TypeError, ValueError):
            item[key] = base[key]


def link_values(pdf_path, board_path=None) -> dict:
    """{path, rel, title} pour un fichier ; `rel` seulement si le board est enregistré sur le même volume."""
    pdf_path = Path(pdf_path).resolve()
    rel = ""
    if board_path:
        try:
            rel = os.path.relpath(pdf_path, Path(board_path).resolve().parent)
        except ValueError:                                   # autre lecteur
            rel = ""
    return {"path": str(pdf_path), "rel": rel, "title": pdf_path.stem}


def resolve(item: dict, board_path=None) -> Path | None:
    """Fichier lié : relatif au board d'abord (dossier déplacé), puis absolu ; None s'il est introuvable."""
    if item.get("rel") and board_path:
        candidate = (Path(board_path).resolve().parent / item["rel"]).resolve()
        if candidate.is_file():
            return candidate
    if item.get("path") and Path(item["path"]).is_file():
        return Path(item["path"])
    return None


def fit_size(page_w: float, page_h: float, long_side: float = 424.0) -> tuple[float, float]:
    if page_w <= 0 or page_h <= 0:
        return DEFAULTS[PDF_DOC]["w"], DEFAULTS[PDF_DOC]["h"]
    scale = long_side / max(page_w, page_h)
    return max(MIN_W, round(page_w * scale, 1)), max(MIN_H, round(page_h * scale, 1))

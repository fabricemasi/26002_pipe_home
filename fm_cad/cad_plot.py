"""PRESENTATIONS et IMPRESSION du CAD (mises en page / TRACEUP d'AutoCAD) : logique PURE (aucun Qt).

Une PRESENTATION (`page["cad"]["layouts"]` : liste, `page["cad"]["layout"]` = nom de la courante) =
- `name` ; `paper` (cle de PAPERS) ; `landscape` (paysage) ; `margin` (mm, chaque bord) ;
- `scale` : 0 = AJUSTER a la feuille, sinon N de l'echelle 1:N (longueurs REELLES : 1 mm de papier = N mm du
  dessin ; 1 unite du board = 25,4 / 96 mm, `cad_model.UNITS`) ;
- `area` : zone imprimee [x0, y0, x1, y1] (document), None = l'etendue du dessin ;
- `center` (centree sur la feuille).
L'impression (`plot_frame`) donne la feuille (mm), la zone du dessin (document) et sa place sur la feuille (mm) :
le rendu (cad_plot_ui) pose l'une sur l'autre, en vectoriel dans un PDF, ou sur une imprimante."""
from __future__ import annotations

import math

MM_PER_UNIT = 25.4 / 96.0           # longueur reelle d'une unite du board
PAPERS = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "A2": (420.0, 594.0), "A1": (594.0, 841.0),
          "A0": (841.0, 1189.0), "Letter": (215.9, 279.4), "Legal": (215.9, 355.6), "Tabloid": (279.4, 431.8)}
DEFAULT = {"name": "Présentation1", "paper": "A4", "landscape": True, "margin": 10.0, "scale": 0.0, "area": None,
           "center": True}


def _num(value, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def clean(raw) -> dict | None:
    """Presentation valide (None = illisible)."""
    if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
        return None
    out = dict(DEFAULT)
    out["name"] = str(raw["name"]).strip()[:255]
    out["paper"] = raw.get("paper") if raw.get("paper") in PAPERS else _custom_paper(raw.get("paper"))
    out["landscape"] = bool(raw.get("landscape", True))
    out["margin"] = max(0.0, min(100.0, _num(raw.get("margin"), DEFAULT["margin"])))
    out["scale"] = max(0.0, _num(raw.get("scale"), 0.0))
    area = raw.get("area")
    if isinstance(area, (list, tuple)) and len(area) == 4:
        try:
            x0, y0, x1, y1 = (float(v) for v in area)
            if x1 - x0 > 1e-9 and y1 - y0 > 1e-9:
                out["area"] = [x0, y0, x1, y1]
        except (TypeError, ValueError):
            pass
    out["center"] = bool(raw.get("center", True))
    return out


def _custom_paper(value) -> str:
    """Format libre « LxH » (mm) garde tel quel ; sinon A4."""
    if isinstance(value, str) and "x" in value:
        try:
            w, h = (float(v) for v in value.lower().split("x"))
            if w > 0 and h > 0:
                return f"{w:g}x{h:g}"
        except ValueError:
            pass
    return "A4"


def paper_size(layout: dict) -> tuple:
    """(largeur, hauteur) de la feuille en mm, orientation comprise."""
    found = PAPERS.get(layout["paper"])
    if found is None:
        w, h = (float(v) for v in layout["paper"].lower().split("x"))
    else:
        w, h = found
    w, h = min(w, h), max(w, h)
    return (h, w) if layout["landscape"] else (w, h)


def layouts(cad: dict) -> list:
    out, seen = [], set()
    for raw in (cad or {}).get("layouts") or []:
        found = clean(raw)
        if found is not None and found["name"].lower() not in seen:
            seen.add(found["name"].lower())
            out.append(found)
    return out


def current(cad: dict) -> dict | None:
    found = layouts(cad)
    name = str((cad or {}).get("layout") or "")
    for layout in found:
        if layout["name"] == name:
            return layout
    return found[0] if found else None


def by_name(cad: dict, name: str) -> dict | None:
    key = str(name or "").strip().lower()
    return next((l for l in layouts(cad) if l["name"].lower() == key), None)


def with_layout(cad: dict, layout: dict, make_current: bool = True) -> dict:
    """Page CAD NEUVE ou `layout` remplace celle du meme nom (ou s'ajoute)."""
    out = dict(cad)
    found = [l for l in layouts(cad) if l["name"].lower() != layout["name"].lower()]
    out["layouts"] = found + [clean(layout)]
    if make_current:
        out["layout"] = layout["name"]
    return out


def without_layout(cad: dict, name: str) -> dict:
    out = dict(cad)
    out["layouts"] = [l for l in layouts(cad) if l["name"].lower() != str(name).lower()]
    if str(out.get("layout") or "").lower() == str(name).lower():
        out["layout"] = out["layouts"][0]["name"] if out["layouts"] else ""
    return out


def unique_name(cad: dict, base: str = "Présentation") -> str:
    names = {l["name"].lower() for l in layouts(cad)}
    n = 1
    while f"{base}{n}".lower() in names:
        n += 1
    return f"{base}{n}"


def parse_scale(text) -> float | None:
    """« 1:100 », « 100 », « ajuster » (0) -> N ; None = illisible."""
    word = str(text or "").strip().lower().replace(" ", "")
    if word in ("", "a", "ajuster", "fit", "f"):
        return 0.0
    if ":" in word or "/" in word:
        left, right = word.replace("/", ":").split(":", 1)
        try:
            a, b = float(left.replace(",", ".")), float(right.replace(",", "."))
        except ValueError:
            return None
        return b / a if a > 0 and b > 0 else None
    try:
        value = float(word.replace(",", "."))
    except ValueError:
        return None
    return value if value > 0 else None


def describe_scale(scale: float) -> str:
    if scale <= 0:
        return "ajustée à la feuille"
    return f"1:{scale:g}" if scale >= 1 else f"{1.0 / scale:g}:1"


def plot_frame(layout: dict, extents) -> dict:
    """Mise en page d'une impression : `paper` (mm), `source` (zone du document [x0, y0, x1, y1]), `target` (sa place
    sur la feuille, mm, origine en HAUT a gauche, [x, y, l, h]), `scale` (N effectif de 1:N). `extents` = etendue du
    dessin (si la presentation n'a pas de zone)."""
    pw, ph = paper_size(layout)
    m = layout["margin"]
    usable_w, usable_h = max(1.0, pw - 2 * m), max(1.0, ph - 2 * m)
    x0, y0, x1, y1 = layout["area"] or extents
    w, h = max(1e-9, x1 - x0), max(1e-9, y1 - y0)
    if layout["scale"] > 0:
        k = MM_PER_UNIT / layout["scale"]                   # mm de papier par unite du board
        scale = layout["scale"]
    else:
        k = min(usable_w / w, usable_h / h)
        scale = MM_PER_UNIT / k
    tw, th = w * k, h * k
    if layout["center"]:
        tx, ty = (pw - tw) / 2.0, (ph - th) / 2.0
    else:
        tx, ty = m, ph - m - th                             # coin bas gauche de la zone utile (comme AutoCAD)
    return {"paper": (pw, ph), "source": [x0, y0, x1, y1], "target": [tx, ty, tw, th], "scale": scale,
            "fits": tw <= usable_w + 1e-6 and th <= usable_h + 1e-6}

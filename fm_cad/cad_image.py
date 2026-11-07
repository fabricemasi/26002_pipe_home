"""IMAGES du CAD (IMAGE / IMAGEATTACH d'AutoCAD : image REFERENCEE, le fichier reste ou il est) : geometrie PURE
(aucun Qt), coordonnees du DOCUMENT (Y vers le haut).

Champs de l'entite `cad_image` (en plus des proprietes communes) :
- `pos` : coin bas gauche de l'image ; `pu` : coin bas droit ; `pv` : coin haut gauche (le 4e coin = pu + pv - pos) —
  trois POINTS : deplacer, tourner, mettre a l'echelle, symetriser = transformer ces points (cisaillement compris) ;
- `path` : chemin du fichier (absolu, ou relatif au dessin d'origine : resolu a l'import) ;
- `fade` : estompage 0..100 (AutoCAD : 0 = image telle quelle).
L'image se peint SOUS les traits (passe des remplissages de la couche GPU) ; son cadre (IMAGEFRAME 1 d'AutoCAD) est un
trait de l'entite : il reste visible fichier absent (le nom du fichier s'affiche alors dedans)."""
from __future__ import annotations

import math

DEFAULTS = {"path": "", "pu": [1.0, 0.0], "pv": [0.0, 1.0], "fade": 0.0}
GEOMETRY_KEYS = ("pos", "pu", "pv")
EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp")


def _pt(value, default=(0.0, 0.0)):
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return default
    return (x, y) if math.isfinite(x) and math.isfinite(y) else default


def style_of(data: dict) -> dict:
    try:
        fade = float(data.get("fade", 0.0))
    except (TypeError, ValueError):
        fade = 0.0
    pos = _pt(data.get("pos"))
    pu = _pt(data.get("pu"), (pos[0] + 1.0, pos[1]))
    pv = _pt(data.get("pv"), (pos[0], pos[1] + 1.0))
    return {"path": str(data.get("path") or ""), "pos": list(pos), "pu": list(pu), "pv": list(pv),
            "fade": max(0.0, min(100.0, fade if math.isfinite(fade) else 0.0))}


def corners(data: dict, offset=(0.0, 0.0)) -> list:
    """Les 4 coins (bas gauche, bas droit, haut droit, haut gauche), document + `offset`."""
    s = style_of(data)
    ox, oy = offset
    p, u, v = s["pos"], s["pu"], s["pv"]
    q = (u[0] + v[0] - p[0], u[1] + v[1] - p[1])
    return [(p[0] + ox, p[1] + oy), (u[0] + ox, u[1] + oy), (q[0] + ox, q[1] + oy), (v[0] + ox, v[1] + oy)]


def prims(data: dict, offset=(0.0, 0.0)) -> list:
    """Cadre de l'image (4 segments)."""
    c = corners(data, offset)
    return [("segment", c[i], c[(i + 1) % 4]) for i in range(4)]


def size(data: dict) -> tuple:
    """(largeur, hauteur) dans le document."""
    s = style_of(data)
    p, u, v = s["pos"], s["pu"], s["pv"]
    return math.hypot(u[0] - p[0], u[1] - p[1]), math.hypot(v[0] - p[0], v[1] - p[1])


def inside(data: dict, x) -> bool:
    """Le point est dans l'image (parallelogramme) ?"""
    s = style_of(data)
    p, u, v = s["pos"], s["pu"], s["pv"]
    ax, ay = u[0] - p[0], u[1] - p[1]
    bx, by = v[0] - p[0], v[1] - p[1]
    det = ax * by - ay * bx
    if abs(det) <= 1e-18:
        return False
    dx, dy = x[0] - p[0], x[1] - p[1]
    s1 = (dx * by - dy * bx) / det
    s2 = (ax * dy - ay * dx) / det
    return 0.0 <= s1 <= 1.0 and 0.0 <= s2 <= 1.0


def translate(data: dict, delta) -> dict:
    return transform(data, lambda q: (q[0] + delta[0], q[1] + delta[1]))


def transform(data: dict, point_fn) -> dict:
    s = style_of(data)
    return {k: list(point_fn(tuple(s[k]))) for k in GEOMETRY_KEYS}


def placed(path: str, pos, width: float, height: float, rot: float) -> dict:
    """Champs d'une image posee en `pos` (coin bas gauche), de cette taille, tournee de `rot` degres."""
    r = math.radians(rot)
    c, s = math.cos(r), math.sin(r)
    x, y = float(pos[0]), float(pos[1])
    return {"path": str(path), "pos": [x, y], "pu": [x + width * c, y + width * s],
            "pv": [x - height * s, y + height * c]}

"""Module CAD du board : grammaire de SAISIE (aucun Qt), commune a la barre de commande et a la saisie
dynamique.

Formes reconnues (comme AutoCAD, coordonnees du document, angles en degres, 0 = est, sens trigonometrique) :
- `100,200`  absolue (barre de commande) — RELATIVE en saisie dynamique pour un point suivant, comme le
  reglage par defaut d'AutoCAD (DYNPICOORDS = 0) ;
- `@50,0`    relative au dernier point ; `@` seul = le dernier point ;
- `@100<45`  polaire relative ; `100<45` polaire absolue (depuis l'origine ; relative en saisie dynamique) ;
- `#100,200` / `*100,200` absolue, meme en saisie dynamique ;
- `150`      distance directe dans la direction du curseur (ou de l'angle impose) ;
- `<30`      impose l'angle du point suivant (le clic ou la distance donnent ensuite la longueur) ;
- `END`, `MID`, `INT`… accrochage a l'objet pour le point suivant seulement (`NON` = aucun) ;
- mots-cles des options de la commande (lettres en capitales du libelle : « annUler » -> U).
Separateur DECIMAL = le point, toujours (la virgule separe les coordonnees, comme dans AutoCAD, quels que
soient les parametres regionaux) : « 12,5 » est un POINT (12 ; 5), jamais 12,5. Nombres negatifs, decimaux et
notation scientifique acceptes ; toute autre saisie est refusee avec un message (jamais de geometrie devinee)."""
from __future__ import annotations

import math
import re

from . import cad_geometry as geo

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_NUM = re.compile(rf"^\s*({NUMBER})\s*$")
_XY = re.compile(rf"^\s*({NUMBER})\s*,\s*({NUMBER})\s*$")
_POLAR = re.compile(rf"^\s*({NUMBER})\s*<\s*({NUMBER})\s*$")
_ANGLE = re.compile(rf"^\s*<\s*({NUMBER})\s*$")

# Accrochages ponctuels (point suivant seulement) : mot tape -> mode du moteur (cad_snap.MODES).
OSNAP_WORDS = {
    "END": "end", "ENDP": "end", "ENDPOINT": "end", "EXTREMITE": "end",
    "MID": "mid", "MIDPOINT": "mid", "MIL": "mid", "MILIEU": "mid",
    "INT": "int", "INTERSECTION": "int", "APP": "appint", "APPINT": "appint",
    "EXTENSION": "ext", "PROLONGEMENT": "ext", "PRO": "ext",
    "PER": "per", "PERP": "per", "PERPENDICULAR": "per", "PERPENDICULAIRE": "per",
    "TAN": "tan", "TANGENT": "tan", "TANGENTE": "tan",
    "NEA": "nea", "NEAREST": "nea", "PROCHE": "nea", "PRES": "nea",
    "PAR": "par", "PARALLEL": "par", "PARALLELE": "par",
    "CEN": "cen", "CENTER": "cen", "CENTRE": "cen", "GCE": "gcen", "GCEN": "gcen",
    "QUA": "qua", "QUADRANT": "qua", "NOD": "node", "NODE": "node", "NODAL": "node",
    "INS": "ins", "INSERT": "ins", "INSERTION": "ins",
    "NON": "none", "NONE": "none", "AUCUN": "none",
    "EXT": "ext",                  # abreviation d'AutoCAD pour Extension (pas « extremite »)
}


def parse_number(text: str) -> float | None:
    match = _NUM.match(text or "")
    if not match:
        return None
    value = float(match.group(1))
    return value if math.isfinite(value) else None


def shortcut_of(label: str) -> str:
    """Raccourci d'une option = ses lettres en CAPITALES (« annUler » -> « U », « Clore » -> « C »)."""
    caps = "".join(c for c in label if c.isupper())
    return caps or label[:1].upper()


def match_keyword(text: str, options) -> str | None:
    """Option choisie par `text` : raccourci, libelle complet ou mot anglais. `options` : [(cle, libelle,
    (mots acceptes...))]."""
    word = (text or "").strip().lstrip("_").upper()
    if not word:
        return None
    for key, label, words in options:
        accepted = {shortcut_of(label), label.upper(), key.upper(), *(w.upper() for w in words)}
        if word in accepted:
            return key
    return None


def parse(text: str, last_point=None, dynamic: bool = False, options=()) -> tuple:
    """Interprete une saisie a l'invite d'un point. Rend un tuple dont le 1er element est la sorte :
    ("empty",) | ("point", (x, y)) | ("distance", d) | ("angle", a) | ("keyword", cle) | ("osnap", mode) |
    ("error", message)."""
    raw = (text or "").strip()
    if not raw:
        return ("empty",)
    keyword = match_keyword(raw, options)
    if keyword is not None:
        return ("keyword", keyword)
    word = raw.lstrip("_").upper()
    if word in OSNAP_WORDS:
        return ("osnap", OSNAP_WORDS[word])
    prefix = ""
    body = raw
    if body[0] in "@#*":
        prefix, body = body[0], body[1:].strip()
    relative = prefix == "@" or (dynamic and prefix == "" and last_point is not None)
    if prefix == "@" and not body:
        if last_point is None:
            return ("error", "Aucun point précédent pour « @ ».")
        return ("point", tuple(last_point))
    match = _ANGLE.match(body)
    if match and not prefix:
        return ("angle", float(match.group(1)) % 360.0)
    match = _XY.match(body)
    if match:
        x, y = float(match.group(1)), float(match.group(2))
        if not (math.isfinite(x) and math.isfinite(y)):
            return ("error", "Coordonnées invalides.")
        if relative:
            if last_point is None:
                return ("error", "Aucun point précédent : coordonnées relatives impossibles.")
            return ("point", (last_point[0] + x, last_point[1] + y))
        return ("point", (x, y))
    match = _POLAR.match(body)
    if match:
        dist, angle = float(match.group(1)), float(match.group(2))
        if not (math.isfinite(dist) and math.isfinite(angle)):
            return ("error", "Coordonnées polaires invalides.")
        base = (0.0, 0.0)
        if relative:
            if last_point is None:
                return ("error", "Aucun point précédent : coordonnées polaires relatives impossibles.")
            base = last_point
        return ("point", geo.polar(base, dist, angle))
    if not prefix:
        value = parse_number(body)
        if value is not None:
            return ("distance", value)
    if body.count(",") >= 2:
        return ("error", f"« {raw} » : coordonnées 3D non prises en charge (X,Y seulement).")
    if "," in body and re.search(r"\d,\d", body) and body.count(",") == 1:
        return ("error", f"« {raw} » : coordonnée invalide (séparateur décimal = le point, ex. 12.5,4).")
    return ("error", f"« {raw} » : saisie non reconnue (point, @x,y, @distance<angle, distance ou option).")


def format_number(value: float, decimals: int = 4) -> str:
    text = f"{geo.clean(value):.{max(0, int(decimals))}f}"
    return "0" + text[2:] if text.startswith("-0") and float(text) == 0 else text


def format_point(p, decimals: int = 4) -> str:
    return f"{format_number(p[0], decimals)},{format_number(p[1], decimals)}"


def format_angle(value: float, decimals: int = 2) -> str:
    return f"{format_number(value % 360.0, decimals)}°"

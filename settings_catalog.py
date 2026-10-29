"""Description des reglages comme des DONNEES (sans Qt) : `Spec` (une ligne), `Node` (arbre des sections),
`CATALOG` (groupe -> lignes) et les fabriques de lignes partagees. La fenetre de reglages (settings_window_v2.py)
construit ses champs a partir de ces donnees ; chaque module decrit ses propres reglages avec elles, dans SON
paquet (ex. `fm_video/settings.py`), sans importer la fenetre. Carte : docs/agents/reglages.md."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Spec:
    """Un reglage. `kind` choisit le controle (voir FIELD_FACTORIES) ;
    `extra_keys` : cles de stockage supplementaires gouvernees par le MEME
    champ/toggle (ex. une bordure = `*_border_enabled` + `*_border`)."""
    key: str
    label: str
    kind: str
    default: Any = None
    params: dict = field(default_factory=dict)
    extra_keys: tuple = ()
    general_toggle: str | None = None   # General : cle booleenne d'un interrupteur d'override devant la ligne


@dataclass(frozen=True)
class Node:
    """Un noeud replie/deplie : section (niveau 1), sous-section (2+). `group`
    = tableau de lignes du CATALOG ; `children` = noeuds imbriques."""
    title: str
    group: str | None = None
    children: tuple = ()
    toggle_key: str | None = None    # sous-section d'un style de toggle (clic droit : renommer / supprimer)


CATALOG: dict[str, list[Spec]] = {}

# Parametres d'une ligne « Bordure » (sides_thick) : cles de couleur et d'epaisseur, largeurs.
_BORD = lambda prefix, w=140, b=54: {"colors_key": prefix, "thickness_key": f"{prefix}_thickness", "width": w, "box": b}


def _shadow_spec(prefix: str, label: str = "Ombres", **kw) -> "Spec":
    """Ligne « Ombres » : lier les 4 | G | H | B | D (un toggle par cote) | Couleur (UNE pour les 4, opacite
    comprise) | Taille. Cles `<prefix>_enabled`, `<prefix>` (la couleur, gardee pour les 4 cotes),
    `<prefix>_size` (settings_widgets.shadow_look)."""
    return Spec(f"{prefix}_enabled", label, "shadow", False,
                {"colors_key": prefix, "thickness_key": f"{prefix}_size", "thickness_label": "Taille",
                 "range": (0, 40), "width": 90, "box": 54},
                extra_keys=(prefix, f"{prefix}_size"), **kw)


def _gabarit_extra(prefix: str, color_key: str | None = None, only: tuple | None = None) -> tuple:
    names = only or ("bold", "italic", "size", "smoothing_enabled", "smoothing", "color")
    keys = []
    for name in names:
        if name == "family":
            continue
        if name == "smoothing":
            keys += [f"{prefix}_font_smoothing_enabled", f"{prefix}_font_smoothing"]
        elif name == "color":
            keys.append(color_key or f"{prefix}_font_color")
        elif name != "smoothing_enabled":
            keys.append(f"{prefix}_font_{name}")
    return tuple(dict.fromkeys(keys))


def _ctx_font(prefix: str, label: str, size: int, color: str, bold: bool = False) -> Spec:
    return Spec(f"{prefix}_font_family", label, "font_gabarit", "",
                {"prefix": prefix, "size": (6, 32), "size_default": size, "color_default": color,
                 "color_title": "Couleur du texte", "bold_default": bold}, extra_keys=_gabarit_extra(prefix))

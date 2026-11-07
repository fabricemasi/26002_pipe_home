"""Module CAD du board : BARRES FLOTTANTES (demande de l'utilisateur, 2026-11-02 : « les palettes d'outils des différents
modules doivent être remplacées, toutes »). Le système est celui de fm_theme (`fm_theme/bar_manager.py` : barres à grille,
accrochage aux bords, éléments déplaçables d'une barre à l'autre ; aspect = réglages `palette_*`) et de `fm_board/bars.py`
(`BoardBars`, `BoardTool`, `ZoomText`) ; ce fichier n'apporte que ce qui est propre au CAD :

- `SECTIONS` / `PRECISION` : les outils et les bascules de précision (clés = noms des commandes de `cad_commands`) ;
- `CadTool` (case d'icône, grisée quand l'outil n'est pas disponible), `CadTextButton` (calque, épaisseur, type de ligne),
  `CadModeButton` (OSNAP, ORTHO… : case à texte allumée quand le mode est actif) ;
- `cad_default_state()` : la disposition par défaut (clés des éléments = celles de `CadChrome.buttons` / `mode_buttons`).

La barre de COMMANDE (saisie en bas, historique) et le panneau Propriétés (tableau d'édition) ne sont pas des palettes
d'outils : ils restent des panneaux de `cad_ui.CadChrome`."""
from __future__ import annotations

from PySide6.QtGui import QPainter

from fm_board.bars import BoardTool
from fm_theme.palette import PaletteTextButton

# Outils : (section, [(genre d'icone, commande, infobulle, disponible)]) ; une section = une barre.
SECTIONS = [
    ("Dessin", [("cad_line", "LINE", "Ligne (L)", True),
                ("cad_pline", "PLINE", "Polyligne (PL)", True),
                ("cad_circle", "CIRCLE", "Cercle (C)", True),
                ("cad_arc", "ARC", "Arc (A)", True),
                ("cad_rect", "RECTANGLE", "Rectangle (REC)", True),
                ("cad_polygon", "POLYGON", "Polygone (POL)", True),
                ("cad_ellipse", "ELLIPSE", "Ellipse (EL)", True),
                ("cad_point", "POINT", "Point (PO)", True),
                ("cad_hatch", "HATCH", "Hachures (H)", True)]),
    ("Modification", [("cad_move", "MOVE", "Déplacer (M)", True),
                      ("cad_copy", "COPY", "Copier (CO)", True),
                      ("cad_erase", "ERASE", "Effacer (E, Suppr)", True),
                      ("cad_match", "MATCHPROP", "Pipette : copier les propriétés d'un objet sur d'autres (MA)", True),
                      ("cad_rotate", "ROTATE", "Rotation (RO)", True),
                      ("cad_mirror", "MIRROR", "Miroir (MI)", True),
                      ("cad_scale", "SCALE", "Échelle (SC)", True),
                      ("cad_trim", "TRIM", "Ajuster (TR)", True),
                      ("cad_extend", "EXTEND", "Prolonger (EX) ; Maj + clic : ajuster", True),
                      ("cad_stretch", "STRETCH", "Étirer (S) : une capture choisit les points à déplacer", True),
                      ("cad_break", "BREAK", "Coupure (BR) : retire la partie entre deux points", True),
                      ("cad_join", "JOIN", "Joindre (J) : objets bout à bout en un seul", True),
                      ("cad_array", "ARRAY", "Réseau (AR) : rectangulaire, polaire ou le long d'un chemin", True),
                      ("cad_offset", "OFFSET", "Décaler (O)", True),
                      ("cad_chamfer", "CHAMFER", "Chanfrein (CHA)", True),
                      ("cad_fillet", "FILLET", "Raccord / arrondi (F)", True),
                      ("cad_explode", "EXPLODE", "Décomposer : polyligne en lignes et arcs, cotation en traits et "
                                                 "texte (X)", True)]),
    ("Annotations", [("cad_text", "TEXT", "Texte (DT) : une ligne par Entrée", True),
                     ("cad_mtext", "MTEXT", "Texte multiligne (MT) : cadre, Entrée = paragraphe, "
                                            "Ctrl+Entrée = fin", True),
                     ("cad_dim", "DIMLINEAR", "Cotation linéaire (DLI)", True),
                     ("cad_dim_aligned", "DIMALIGNED", "Cotation alignée (DAL)", True),
                     ("cad_dim_radius", "DIMRADIUS", "Cotation de rayon (DRA)", True),
                     ("cad_dim_diameter", "DIMDIAMETER", "Cotation de diamètre (DDI)", True),
                     ("cad_dim_angular", "DIMANGULAR", "Cotation angulaire (DAN)", True)]),
]
PRECISION = [("osnap", "OSNAP", "Accrochages aux objets (F3)"), ("ortho", "ORTHO", "Mode orthogonal (F8)"),
             ("polar", "POLAIRE", "Suivi polaire (F10)"), ("otrack", "OTRACK", "Suivi d'accrochage (F11)"),
             ("dyn", "DYN", "Saisie dynamique (F12)"), ("grid", "GRILLE", "Grille (F7)"),
             ("grid_snap", "RESOL", "Accrochage à la grille (F9)"),
             ("lineweight", "ÉPAIS.", "Afficher les épaisseurs de ligne (LWT) : éteint = simples lignes d'un pixel, comme AutoCAD")]
MODE_PREFIX = "mode_"           # clé d'une bascule de précision : « mode_osnap »


class CadTool(BoardTool):
    """Case d'outil CAD : grisée à 20 % quand l'outil n'est pas encore disponible (`setEnabled(False)`)."""

    def _paint_content(self, painter: QPainter) -> None:
        if not self.isEnabled():
            painter.setOpacity(0.2)
        super()._paint_content(painter)


class CadTextButton(PaletteTextButton):
    """Case à texte du CAD (calque, épaisseur, type de ligne) : mêmes noms que l'ancien `_TextButton` (`setText`, `text`)."""

    def setText(self, text: str) -> None:               # noqa: N802 - nom Qt de l'ancien bouton
        self.set_text(text)

    def text(self) -> str:
        return self.text_value()


class CadModeButton(CadTextButton):
    """Bascule de précision (OSNAP, ORTHO…) : case allumée quand le mode est actif."""

    def __init__(self, name: str, text: str, tip: str, parent=None):
        super().__init__(MODE_PREFIX + name, text, tip, parent, cells=2)
        self.name = name

    def set_on(self, on: bool) -> None:
        self.set_active(on)

    @property
    def _on(self) -> bool:
        return self.active


def _bar(bar_id: str, title: str, items: dict, cols: int, rows: int, **extra) -> dict:
    entry = {"id": bar_id, "title": title, "dock": None, "orient": "h", "along": 0, "x": 0, "y": 0, "cols": cols,
             "rows": rows, "items": {key: list(cell) for key, cell in items.items()}}
    entry.update(extra)
    return entry


def _reading_order(keys: list, cols: int) -> dict:
    return {key: (index % cols, index // cols, 1) for index, key in enumerate(keys)}


# Disposition par défaut : les trois barres d'outils clipsées à gauche l'une derrière l'autre (2 colonnes), « Propriétés »
# et « Gestion » en haut, « Précision » en bas à gauche, « Vue » en bas à droite (la barre de commande reste entre les deux).
def cad_default_state() -> dict:
    tools = {title: [command for _kind, command, _tip, _ok in rows] for title, rows in SECTIONS}
    drawing, modify, notes = tools["Dessin"], tools["Modification"], tools["Annotations"]
    modes = {f"{MODE_PREFIX}{name}": (index % 4 * 2, index // 4, 2) for index, (name, _text, _tip) in enumerate(PRECISION)}
    modes["cad_settings"] = (8, 0, 1)
    return {"next": 8, "bars": [
        _bar("b1", "Dessin", _reading_order(drawing, 2), 2, 5, dock="left", orient="v", along=16),
        _bar("b2", "Modification", _reading_order(modify, 2), 2, 9, dock="left", orient="v", after="b1", along=216),
        _bar("b3", "Annotations", _reading_order(notes, 2), 2, 4, dock="left", orient="v", after="b2", along=560),
        _bar("b4", "Propriétés", {"layer": (0, 0, 3), "color": (3, 0, 1), "weight": (4, 0, 2), "linetype": (6, 0, 3)},
             9, 1, dock="top", along=124),
        _bar("b5", "Gestion", {"cad_layers": (0, 0, 1), "cad_properties": (1, 0, 1), "cad_photoshop": (2, 0, 1),
                               "cad_drawing": (3, 0, 1), "BLOCK": (4, 0, 1), "INSERT": (5, 0, 1)}, 6, 1, dock="top",
             after="b4", along=492),
        _bar("b6", "Précision", modes, 9, 2, dock="bottom", along=0),
        _bar("b7", "Vue", {"zoom_out": (0, 0, 1), "zoom": (1, 0, 2), "zoom_in": (3, 0, 1), "fit": (4, 0, 1)}, 5, 1,
             dock="bottom", end=True)]}

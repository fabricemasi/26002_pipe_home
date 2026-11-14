"""Barres flottantes des modules du Board (demande de l'utilisateur, 2026-11-02 : « les palettes d'outils des différents
modules doivent être remplacées, toutes » ; la barre des modules, `modulebar.py`, n'est PAS touchée). Le système est celui de
fm_theme (`fm_theme/bar_manager.py` : barres à grille, accrochage aux bords, éléments déplaçables d'une barre à l'autre ;
aspect = réglages `palette_*`, section « Palette » de l'éditeur fm_theme) ; ce fichier n'apporte que ce qui est propre au
Board :

- `BoardTool` : une case d'icône qui peint les glyphes et les icônes personnalisées du Board (Réglages > Module MRO >
  Icônes) ;
- `BoardBars` : les barres d'UN module (un gestionnaire par module, disposition enregistrée dans les réglages, `board_bars`
  = {module: état}) ;
- `miro_default_state()` : la disposition par défaut de Miro (clés = celles des outils de `ui.TOOLS` / `DRAW_BAR`).

Les autres modules (CAD, Design, Tableur, Illustrator, Photoshop) gardent leurs barres jusqu'à leur conversion : chacun
crée son `BoardBars` et lui inscrit ses éléments (voir docs/agents/fm_board.md, « Barres flottantes »)."""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from fm_theme.bar_manager import BarManager
from fm_theme.palette import PaletteButton, PaletteTextButton

from . import model
from . import ui as _ui

_ICONES_OUTILS = {
    "sticky": "modules/miro/note_adhesive_03",
    "cad_fillet": "modules/cad/conge_03",
    "cad_erase": "modules/cad/gomme_01",                # « Effacer (E, Suppr) » de la barre Modification du CAD
    "ill_pen": "modules/illustrator/plume_03",
    "design_templates": "modules/design/grille_composition_03",
    "design_delete": "general/supprimer_02",            # « Supprimer (Suppr) » de la barre contextuelle Design
}


def library_icon_for(kind: str) -> str | None:
    """Icône du catalogue d'un genre de bouton du board (outil ou emblème de module) : UNE table, lue par les barres
    et par les aperçus de la liste ICÔNES des réglages (settings_v2_app._default_glyph)."""
    from .modulebar import MODULE_EMBLEMS
    return _ICONES_OUTILS.get(kind) or MODULE_EMBLEMS.get(kind)


def format_percent(zoom: float) -> str:
    return _ui.format_zoom(zoom)


class BoardTool(PaletteButton):
    """Case d'icône d'une barre du Board : glyphe peint (`ui.paint_glyph`) ou icône personnalisée, selon `kind` ; `set_on`
    = outil en cours ; `set_swatch(couleur, anneau)` = pastille de preset de dessin. Mêmes noms que `ui._GlyphButton` :
    le code du Board qui pilote ses boutons n'a rien à changer."""

    def __init__(self, kind: str, tip: str, parent=None, key: str | None = None):
        super().__init__(key or kind, tip, lambda p, r, c: self._paint_kind(p, r, c), parent)
        self.kind = kind
        self._swatch = None
        self._ring = None
        if kind in _ICONES_OUTILS:
            self.set_library_icon(_ICONES_OUTILS[kind])

    def _paint_library_icon(self, painter, rect, color):
        if _ui.custom_icon(self.kind, int(rect.width())) is not None:
            return False
        return super()._paint_library_icon(painter, rect, color)

    def set_on(self, on: bool) -> None:
        self.set_active(on)

    @property
    def _on(self) -> bool:
        """Compatibilité avec `ui._GlyphButton` (état « choisi »), lu par d'autres modules et leurs tests."""
        return self.active

    def set_swatch(self, color: str, ring: float | None = None) -> None:
        """Pastille de couleur ; `ring` = diamètre du point central (preset de dessin : épaisseur)."""
        if (color, ring) != (self._swatch, self._ring):
            self._swatch, self._ring = color, ring
            self.update()

    def extra_key(self) -> tuple:
        # Icônes personnalisées changées : `ui.refresh_glyph_buttons` incrémente la génération.
        return (self.kind, self._swatch, self._ring, _ui._GLYPH_GENERATION, _ui.ICON_PROVIDER, self.isEnabled())

    def _paint_content(self, painter: QPainter) -> None:
        if self._swatch is None:
            super()._paint_content(painter)
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        inner = QRectF(self.rect()).adjusted(7, 7, -7, -7)
        on = self.active
        if self._ring is not None:
            painter.setPen(QPen(QColor(model.MIRO_ACCENT) if on else QColor(0, 0, 0, 40), 2.0 if on else 1.0))
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(inner)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self._swatch))
            d = max(3.0, min(inner.width() - 6, self._ring))
            painter.drawEllipse(inner.center(), d / 2, d / 2)
        else:
            painter.setPen(QPen(QColor(model.MIRO_ACCENT) if on else QColor(0, 0, 0, 110 if self.underMouse() else 40),
                                2.0 if on else 1.2))
            painter.setBrush(QColor(self._swatch))
            painter.drawEllipse(inner)

    def _paint_kind(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        pixmap = _ui.custom_icon(self.kind, int(rect.width()))
        if pixmap is not None and not pixmap.isNull():
            if color.lightness() < 60:                       # barre claire : icône perso en négatif
                pixmap = _ui.negative_pixmap(pixmap)
            ratio = max(1.0, pixmap.devicePixelRatio())
            target = QRectF(0, 0, pixmap.width() / ratio, pixmap.height() / ratio)
            target.moveCenter(rect.center())
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        else:
            painter.setRenderHint(QPainter.Antialiasing, True)
            _ui.paint_glyph(painter, self.kind, rect, color)


class ZoomText(PaletteTextButton):
    """« 100 % » de la barre Vue : suit le zoom de la vue ; clic = revenir à 100 %."""

    def __init__(self, view, parent=None):
        super().__init__("zoom", format_percent(view.zoom()), "Zoom (clic : 100 %)", parent, cells=2)
        self.view = view

    def paintEvent(self, event):
        self.set_text(format_percent(self.view.zoom()))
        super().paintEvent(event)


# Disposition par défaut de Miro : « Outils » et « Créer » clipsées à gauche l'une derrière l'autre, « Page » ensuite, « Vue »
# en bas à droite, « Dessin » flottante (visible pendant un outil de dessin), « Sélection » en haut (boutons refaits à chaque
# sélection, `BoardPane._sync_context_bar`).
def miro_default_state() -> dict:
    def bar(bar_id, title, items, rows, **extra):
        entry = {"id": bar_id, "title": title, "dock": None, "orient": "h", "along": 0, "x": 0, "y": 0, "cols": 1,
                 "rows": rows, "items": {key: list(cell) for key, cell in items.items()}}
        entry.update(extra)
        return entry
    return {"next": 7, "bars": [
        bar("b1", "Outils", {"select": (0, 0, 1), "hand": (0, 1, 1)}, 2, dock="left", orient="v", along=16),
        bar("b2", "Créer", {key: (0, row, 1) for row, key in enumerate(
            ("sticky", "text", "shape", "connector", "draw", "comment", "frame", "image"))}, 8,
            dock="left", orient="v", after="b1", along=104),
        bar("b3", "Page", {"page": (0, 0, 1), "grid": (0, 1, 1)}, 2, dock="left", orient="v", after="b2", along=432),
        bar("b4", "Vue", {"zoom_out": (0, 0, 1), "zoom": (1, 0, 2), "zoom_in": (3, 0, 1), "fit": (4, 0, 1)}, 1,
            dock="bottom", end=True, cols=5),
        bar("b5", "Dessin", {"pen": (0, 0, 1), "highlighter": (1, 0, 1), "smart": (2, 0, 1), "eraser": (0, 1, 1),
                             "precision_eraser": (1, 1, 1), "lasso": (2, 1, 1), "preset0": (0, 2, 1),
                             "preset1": (1, 2, 1), "preset2": (2, 2, 1)}, 3, x=96, y=150, cols=3),
        bar("b6", "Sélection", {}, 1, dock="top", along=260, cols=8)]}


class BoardBars:
    """Les barres flottantes d'UN module du Board : un gestionnaire (`BarManager`) sur le board, sa disposition enregistrée
    dans les réglages de l'appli (`board_bars` = {module: état}, état temps réel : `save_live_state`). Le module inscrit ses
    éléments (`register`) puis appelle `restore()` ; la zone des barres est le board à droite de la barre des modules."""

    def __init__(self, pane, module: str, default_state: dict):
        self.pane = pane
        self.module = module
        self.manager = BarManager(pane)
        self.manager.default_state = default_state
        self.manager.layoutChanged.connect(self.save)
        self.visible = True

    def register(self, key: str, widget) -> None:
        self.manager.register(key, widget)

    def restore(self) -> None:
        saved = (self.pane._settings.get("board_bars") or {}).get(self.module)
        self.manager.restore(saved if isinstance(saved, dict) else None)

    def set_area(self, left: int) -> None:
        self.manager.set_area(QRect(left, 0, max(0, self.pane.width() - left), self.pane.height()))

    def set_visible(self, visible: bool) -> None:
        self.visible = bool(visible)
        self.manager.set_visible(self.visible)

    def sync(self) -> None:
        self.manager.sync_visibility()

    def raise_all(self) -> None:
        for bar in self.manager.bars:
            bar.raise_()

    def bar(self, bar_id: str):
        return self.manager.bar(bar_id)

    def reset(self) -> None:
        self.manager.reset()

    def save(self) -> None:
        """Fin d'un geste : la disposition de ce module est retenue (les autres modules gardent la leur)."""
        states = dict(self.pane._settings.get("board_bars") or {})
        states[self.module] = self.manager.state()
        self.pane._settings["board_bars"] = states
        try:
            from settings_store import save_live_state
            import ui_state
            save_live_state("board_bars", states)
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS["board_bars"] = states
        except Exception:                                  # noqa: BLE001 - la session garde la disposition
            pass

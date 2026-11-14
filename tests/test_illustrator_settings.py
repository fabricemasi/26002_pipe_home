"""Module Illustrator, tranche 18 : réglages (onglet « Illustrator » de Réglages : Board, clés `board_ill_*`) :
lignes déclarées avec le même défaut des deux côtés, champs construits et relus, application EN DIRECT (couleur de
sélection, poignées, points, aimantation, flèches, unité affichée, format des plans, police et corps des textes,
fidélité du crayon, DPI du PDF), valeur invalide = défaut, chemin rapide quand rien ne change."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import unittest

from PySide6.QtCore import QPointF, Qt

from test_illustrator import IllTestCase
from fm_illustrator import look, model as im


class SettingsTest(IllTestCase):
    def tearDown(self):
        look.apply_settings(None)                       # LOOK est global : défauts pour les tests suivants
        super().tearDown()

    def apply(self, **values):
        self.pane.apply_settings({**self.pane._settings, **values})

    def test_rows_declared_and_built(self):
        import settings_store
        import settings_window_v2 as v2
        from fm_illustrator.settings import ILL_TAB, ILL_TREE
        from settings_catalog import CATALOG
        self.assertIn(ILL_TAB, [label for label, _t in v2.MODULE_SCOPES["board"]])
        specs = [spec for node in ILL_TREE for spec in CATALOG[node.group] if spec.kind != "ui_icon"]  # lignes « Icônes » (ui_icon) : icônes perso, pas des réglages
        for spec in specs:
            self.assertEqual(spec.default, settings_store.DEFAULT_SETTINGS[spec.key], spec.key)
        self.assertEqual({s.key for s in specs}, {k for k in settings_store.DEFAULT_SETTINGS
                                                  if k.startswith("board_ill_")})
        settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
        for node in ILL_TREE:
            fields, record = {}, []
            v2.build_group(node.group, v2.ScopeValues(settings, None), settings["colors"], fields, {}, [], record,
                           lambda: None)
            if all(spec.kind == "ui_icon" for spec in CATALOG[node.group]):
                continue                          # section « Icônes » : icônes perso, rien d'enregistré
            self.assertTrue(record, node.group)

    def test_live_application(self):
        from fm_illustrator import controller, overlay, pdf, tools, tools_draw, tools_xform
        self.assertFalse(look.apply_settings(self.pane._settings))       # rien de changé : rien à faire
        self.apply(board_ill_accent="#ff0000", board_ill_handle_size=14, board_ill_anchor_size=8,
                   board_ill_snap_px=12, board_ill_nudge_big=25, board_ill_pencil_fidelity=50,
                   board_ill_pdf_dpi=150, board_ill_units="mm",
                   board_ill_artboard_format="Carré 1080", board_ill_text_size=24,
                   board_ill_handle_size_inconnu=3)
        self.assertEqual(im.ACCENT, "#ff0000")
        self.assertEqual((tools.HANDLE_PX, tools.ANCHOR_PX, overlay.ANCHOR_SIDE), (7.0, 8.0, 8.0))
        self.assertEqual((tools_xform.SNAP_PX, controller.NUDGE_BIG, pdf.DPI), (12.0, 25.0, 150))
        self.assertEqual(tools_draw.PencilTool.FIDELITY_PX, 5.0)
        a = self.rect(100, 100, 40, 40)
        self.ctl.select([a])
        self.key(Qt.Key_Right, Qt.ShiftModifier)
        self.assertEqual(a.geometry_rect().x(), 125)
        self.ctl.ui.sync()
        self.assertTrue(self.ctl.ui.width_button.text_value().endswith("mm"))
        board = self.ctl.add_artboard()
        self.assertEqual(board.size(), (1080.0, 1080.0))
        text = self.ctl.new_text(QPointF(0, 0), text="T")
        self.assertAlmostEqual(text.data["font_size"], 24 * im.PT, places=3)
        self.ctl.discard(text)

    def test_every_button_icon_is_settable(self):
        """Chaque bouton du module (barre d'outils, barre de contrôle) a sa ligne « Module MRO > Icônes » et lit
        l'icône choisie (`ui_board_<genre>`) ; sans icône choisie, le glyphe est peint."""
        from unittest import mock
        from PySide6.QtGui import QColor, QPixmap
        from fm_board import ui as board_ui
        from fm_board.model import ICON_ROWS
        from fm_board.bars import BoardTool
        ui = self.ctl.ui
        buttons = [w for w in ui.bars.manager.widgets.values() if isinstance(w, BoardTool)]
        kinds = {b.kind for b in buttons if b.kind.startswith("ill_")}
        self.assertTrue({"ill_pen", "ill_fx", "ill_export", "ill_shape_builder", "ill_swap"} <= kinds)
        self.assertEqual(kinds - {kind for kind, _label in ICON_ROWS}, set())
        asked = []

        def provider(kind, size):
            asked.append(kind)
            pixmap = QPixmap(size, size)
            pixmap.fill(QColor("#00ff00"))
            return pixmap
        with mock.patch.object(board_ui, "ICON_PROVIDER", provider):
            for button in buttons:
                button.grab()                                   # peint la case (image gardée : l'habillage a changé)
        self.assertIn("ill_pen", asked)

    def test_invalid_values_fall_back(self):
        self.apply(board_ill_handle_size="x", board_ill_units="lieues", board_ill_accent=12)
        self.assertEqual(look.LOOK["handle_size"], 9)
        self.assertEqual(look.LOOK["units"], "pt")
        self.assertEqual(look.LOOK["accent"], "#2f7cf6")


if __name__ == "__main__":
    unittest.main()

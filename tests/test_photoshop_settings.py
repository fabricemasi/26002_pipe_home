"""Module Photoshop : réglages (onglet « Photoshop » de Réglages : Board, clés `board_ps_*`) — lignes déclarées avec le
même défaut des deux côtés, champs construits et relus, application EN DIRECT au seul contenu concerné (damier, établi,
zoom, mémoire de l'historique), valeur invalide = défaut, chemin rapide quand rien ne change."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import unittest

from _photoshop_case import PsCase, settle
from fm_photoshop import history, look


class PhotoshopSettingsTest(PsCase):
    def tearDown(self):
        look.apply_settings(None)                       # LOOK est global : défauts pour les tests suivants
        super().tearDown()

    def apply(self, **values):
        self.pane.apply_settings({**self.pane._settings, **values})

    def test_rows_declared_and_built(self):
        import settings_store
        import settings_window_v2 as v2
        from fm_photoshop.settings import PS_TAB, PS_TREE
        from settings_catalog import CATALOG
        self.assertIn(PS_TAB, [label for label, _t in v2.MODULE_SCOPES["board"]])
        specs = [spec for node in PS_TREE for spec in CATALOG[node.group] if spec.kind != "ui_icon"]  # lignes « Icônes » (ui_icon) : icônes perso, pas des réglages
        for spec in specs:
            self.assertEqual(spec.default, settings_store.DEFAULT_SETTINGS[spec.key], spec.key)
        declared = {k for k in settings_store.DEFAULT_SETTINGS if k.startswith("board_ps_")}
        self.assertEqual({s.key for s in specs}, declared - {"board_ps_brush_presets"})     # (état, pas un réglage visible)
        settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
        for node in PS_TREE:
            fields, record = {}, []
            v2.build_group(node.group, v2.ScopeValues(settings, None), settings["colors"], fields, {}, [], record,
                           lambda: None)
            if all(spec.kind == "ui_icon" for spec in CATALOG[node.group]):
                continue                          # section « Icônes » : icônes perso, rien d'enregistré
            self.assertTrue(record, node.group)
            for spec, widget in record:
                if hasattr(spec, "kind"):
                    read = v2.FIELD_READERS.get(spec.kind, lambda sp, w: {sp.key: w.value()})(spec, widget)
                    self.assertEqual(read[spec.key], spec.default, spec.key)

    def test_live_application_repaints_only_the_content(self):
        _item, std = self.editor(64, 48)
        canvas = std.canvas
        self.assertFalse(look.apply_settings(self.pane._settings))               # rien de changé : rien à faire
        before_cache = std.session.tiles.version
        self.apply(board_ps_checker_a="#ff0000", board_ps_checker_size=20, board_ps_bench_color="#102030",
                   board_ps_zoom_pct=30, board_ps_max_zoom_pct=800, board_ps_history_mb=64,
                   board_ps_cursor_outline=False, board_ps_inconnu=3)
        self.assertEqual((look.LOOK["checker_a"], look.LOOK["checker_size"], look.LOOK["bench_color"]),
                         ("#ff0000", 20, "#102030"))
        self.assertAlmostEqual(look.LOOK["zoom_step"], 1.3)
        self.assertEqual((look.LOOK["max_zoom"], history.LIMIT_BYTES), (8.0, 64 << 20))
        self.assertEqual(std.session.tiles.version, before_cache)                  # aucune tuile recomposée
        canvas.set_zoom(100.0)
        self.assertEqual(canvas.zoom(), 8.0)                                       # zoom maximal appliqué
        canvas._hover = canvas.rect().center()
        canvas.grab()
        self.assertEqual(canvas._checker_key, ("#ff0000", "#cccccc", 20))          # damier refait avec les nouveaux réglages
        self.assertFalse(look.apply_settings({**self.pane._settings, "board_ps_checker_a": "#ff0000",
                                               "board_ps_checker_size": 20, "board_ps_bench_color": "#102030",
                                               "board_ps_zoom_pct": 30, "board_ps_max_zoom_pct": 800,
                                               "board_ps_history_mb": 64, "board_ps_cursor_outline": False}))

    def test_new_document_clipboard_paste_setting(self):
        self.assertIs(look.LOOK["new_paste_clipboard"], True)                       # défaut : l'image du presse-papiers est collée
        self.apply(board_ps_new_paste_clipboard=False)
        self.assertIs(look.LOOK["new_paste_clipboard"], False)
        self.apply(board_ps_new_paste_clipboard=True)
        self.assertIs(look.LOOK["new_paste_clipboard"], True)

    def test_invalid_values_fall_back_to_defaults(self):
        self.apply(board_ps_checker_a="rouge", board_ps_checker_size="x", board_ps_zoom_pct=-5,
                   board_ps_max_zoom_pct=10 ** 9, board_ps_history_mb=0)
        self.assertEqual(look.LOOK["checker_a"], "#ffffff")
        self.assertEqual(look.LOOK["checker_size"], 10)
        self.assertAlmostEqual(look.LOOK["zoom_step"], 1.02)                         # borné
        self.assertEqual(look.LOOK["max_zoom"], 64.0)
        self.assertEqual(history.LIMIT_BYTES, 16 << 20)


if __name__ == "__main__":
    unittest.main()

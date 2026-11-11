"""Barres flottantes du module CAD (fm_cad/cad_bars.py, fm_cad/cad_ui.py ; système de fm_theme : fm_theme/bar_manager.py,
fm_theme/palette.py ; demande de l'utilisateur, 2026-11-02 : « les palettes d'outils des différents modules doivent être
remplacées, toutes ») : chaque outil, bascule de précision et bouton de propriété du CAD est un élément d'une barre à grille
du gestionnaire du module, la disposition est retenue dans `board_bars["cad"]`. La barre de COMMANDE et le panneau Propriétés
(tableau) restent des panneaux."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from fm_board import ui as board_ui
from fm_board.ui import BoardPane
from fm_cad import cad_model
from fm_cad.cad_bars import MODE_PREFIX, PRECISION, SECTIONS
from test_cad import CadBoardCase, settle

TOP_BARS = ("b4", "b5")


class CadFloatingBarsTest(CadBoardCase):
    def setUp(self):
        super().setUp()
        self.pane.setGeometry(self.host.rect())              # (le panneau suit son hote : tailles de la fenetre de test)
        settle(0.05)

    def manager(self):
        return self.ctl.ui.bars.manager

    def drag_out(self, key, x=700, y=300):
        """Ctrl + glisser (methodes du gestionnaire) : l'element `key` lache dans le vide du board."""
        mgr = self.manager()
        bar = mgr.bar_of(key)
        item = bar._items[key]
        mgr.begin_item_drag(bar, item, bar.mapToGlobal(item.widget.geometry().center()))
        mgr.item_drag_to(self.pane.mapToGlobal(QPoint(x, y)))
        mgr.end_item_drag()

    def test_moving_a_bar_asks_the_gpu_layer_for_a_new_image(self):
        """Rendu GPU (couche peinte AU-DESSUS de tout, qui laisse la place des widgets du board) : deplacer, agrandir,
        montrer ou cacher une barre, ou un widget ajoute ensuite, redemande une image (sinon la barre « passait sous le
        viewport » pendant son deplacement, signale 2026-11-04)."""
        from PySide6.QtWidgets import QWidget
        from fm_board.view import _GpuObstacleWatch

        class Layer:
            requests = 0

            def request(self):
                Layer.requests += 1
        watch = _GpuObstacleWatch(self.pane.view, Layer())
        bar = self.manager().bars[0]
        bar.move(bar.pos() + QPoint(40, 30))
        self.assertGreater(Layer.requests, 0)
        before = Layer.requests

        class Later(QWidget):
            presses = 0

            def mousePressEvent(self, event):
                Later.presses += 1
        later = Later(self.pane)                                            # nouvelle barre, panneau ouvert ensuite
        settle(0.02)
        later.show()
        later.move(120, 80)
        self.assertGreater(Layer.requests, before)
        self.assertIs(type(self.pane.children()[-1]), Later)        # sa classe Python intacte (signale 2026-11-04 :
        QTest.mousePress(later, Qt.LeftButton)                      # barres plus deplacables ni peintes)
        self.assertEqual(Later.presses, 1)
        watch.stop()
        before = Layer.requests
        bar.move(bar.pos() + QPoint(10, 0))
        self.assertEqual(Layer.requests, before)
        later.deleteLater()

    def test_default_layout_puts_every_tool_in_a_named_bar(self):
        mgr = self.manager()
        self.assertEqual([b.title() for b in mgr.bars],
                         ["Dessin", "Modification", "Annotations", "Propriétés", "Gestion", "Précision", "Vue"])
        for title, tools in SECTIONS:                         # une barre par section d'outils, aucun outil perdu
            bar = mgr.bar_of(tools[0][1])
            self.assertEqual(bar.title(), title)
            self.assertEqual(sorted(bar.keys()), sorted(command for _kind, command, _tip, _ok in tools))
        self.assertEqual(sorted(mgr.bar("b4").keys()), ["color", "layer", "linetype", "weight"])
        self.assertEqual(sorted(mgr.bar("b6").keys()),
                         sorted([MODE_PREFIX + name for name, _text, _tip in PRECISION] + ["cad_settings"]))
        self.assertEqual(sorted(mgr.bar("b7").keys()), ["fit", "zoom", "zoom_in", "zoom_out"])
        self.assertTrue(all(mgr.bar_of(key) is not None for key in mgr.widgets))     # tout inscrit est pose dans une barre
        self.assertEqual(self.ctl.ui.buttons["LINE"], mgr.widgets["LINE"])

    def test_linetype_is_a_dropdown_controller_in_properties(self):
        """Type de ligne : contrôleur liste déroulante de la barre Propriétés (demande de l'utilisateur, 2026-11-10)."""
        from fm_cad import cad_model
        from fm_theme.palette import PaletteSelectBar
        mgr = self.manager()
        select = mgr.widgets["linetype"]
        self.assertIsInstance(select, PaletteSelectBar)
        self.assertEqual(mgr.bar_of("linetype").title(), "Propriétés")
        key, (label, _pattern) = next(iter(cad_model.LINETYPES.items()))
        self.assertIn(label, select.field._options)
        select.valueChanged.emit(label)                                  # choix dans le menu : type courant
        self.assertEqual(self.ctl.cad_page()["celtype"], key)
        self.ctl.ui.sync()
        self.assertEqual(select.value(), label)

    def test_bars_exist_only_with_the_cad_module(self):
        pane = self.pane
        mgr = self.manager()
        self.assertTrue(all(bar.isVisible() for bar in mgr.bars))
        self.assertFalse(pane._toolbar.isVisible())                                  # les barres de Miro sont cachees
        pane.set_module("miro")
        settle(0.05)
        self.assertFalse(any(bar.isVisible() for bar in mgr.bars))
        self.assertTrue(pane._toolbar.isVisible())
        pane.set_module("cad")
        settle(0.05)
        self.assertTrue(all(bar.isVisible() for bar in mgr.bars))
        self.assertFalse(pane._toolbar.isVisible())
        pane.set_module(None)
        settle(0.05)
        self.assertFalse(any(bar.isVisible() for bar in mgr.bars))

    def test_the_module_bar_is_not_touched_and_the_bars_start_to_its_right(self):
        pane, mgr = self.pane, self.manager()
        self.assertTrue(pane._modulebar.isVisible())
        self.assertEqual(pane._modulebar.geometry().left(), 0)
        for bar in mgr.bars:
            if bar.dock == "left":
                self.assertEqual(bar.x(), pane.left_edge())
        self.assertEqual(mgr.bar("b7").geometry().right() + 1, pane.width())        # « Vue » : en bas a droite
        self.assertEqual(mgr.bar("b6").x(), pane.left_edge())                       # « Precision » : en bas a gauche

    def test_a_tool_button_starts_its_command_and_lights_up_while_it_runs(self):
        ui = self.ctl.ui
        self.assertFalse(ui.buttons["LINE"].active)
        ui.buttons["LINE"].click()
        settle(0.05)
        self.assertEqual(self.ctl.command.NAME, "LINE")
        self.assertTrue(ui.buttons["LINE"].active)
        self.assertFalse(ui.buttons["MOVE"].active)
        QTest.keyClick(self.pane.view, "\x1b")
        settle(0.05)
        self.assertIsNone(self.ctl.command)
        self.assertFalse(ui.buttons["LINE"].active)

    def test_precision_buttons_toggle_their_mode_and_show_it(self):
        ui = self.ctl.ui
        before = self.ctl.mode_on("ortho")
        ui.mode_buttons["ortho"].click()
        settle(0.05)
        self.assertEqual(self.ctl.mode_on("ortho"), not before)
        self.assertEqual(ui.mode_buttons["ortho"].active, not before)
        for name, button in ui.mode_buttons.items():
            self.assertEqual(button.active, self.ctl.mode_on(name))
        self.assertEqual(ui.mode_buttons["osnap"].text(), "OSNAP")

    def test_property_buttons_show_the_current_values(self):
        ui = self.ctl.ui
        cad = self.ctl.cad_page()
        self.assertEqual(ui.layer_button.text(), cad_model.effective_layer(cad, cad["current"])["name"])
        ui.set_weight(0.5 * self.ctl.unit())
        settle(0.05)
        self.assertEqual(ui.weight_button.text(), cad_model.describe_weight(self.ctl.cad_page()["celweight"], self.ctl.unit()))
        self.assertNotEqual(ui.weight_button.text(), "ByLayer")
        ui.set_color("#ff0000")
        settle(0.05)
        self.assertEqual(ui.color_button._swatch, "#ff0000")

    def test_the_old_toolbar_attribute_answers_for_the_drawing_bar(self):
        ui = self.ctl.ui
        self.assertIs(ui.toolbar, self.manager().bar("b1"))
        self.pane.toggle_cad(False)
        self.assertFalse(ui.toolbar.isVisible())

    def test_a_tool_dropped_in_the_void_becomes_a_bar_that_is_saved_and_restored(self):
        self.drag_out("LINE")
        mgr = self.manager()
        new = mgr.bar_of("LINE")
        self.assertNotEqual(new.bar_id, "b1")
        self.assertEqual(new.keys(), ["LINE"])
        saved = self.pane._settings["board_bars"]["cad"]                              # la disposition de ce module seulement
        self.assertNotIn("miro", self.pane._settings["board_bars"])
        self.assertIn("LINE", next(b for b in saved["bars"] if b["id"] == new.bar_id)["items"])
        other = BoardPane(self.host, {"board_bars": self.pane._settings["board_bars"]})     # autre ouverture : meme disposition
        self.addCleanup(other.deleteLater)
        other.open(self.path)
        other.setGeometry(self.host.rect())
        other.show()
        other.toggle_cad(True)
        settle(0.05)
        self.assertEqual(other.cad.ui.bars.manager.bar_of("LINE").bar_id, new.bar_id)
        self.assertEqual(other.cad.ui.bars.manager.bar_of("LINE").keys(), ["LINE"])

    def test_reset_returns_to_the_default_layout(self):
        self.drag_out("LINE")
        self.ctl.ui.bars.reset()
        self.assertEqual(self.manager().bar_of("LINE").bar_id, "b1")
        self.assertEqual(len(self.manager().bars), 7)

    def test_the_command_bar_stays_between_the_bars_of_the_bottom(self):
        ui, mgr = self.ctl.ui, self.manager()
        command = ui.command_bar.geometry()
        for bar_id in ("b6", "b7"):
            self.assertFalse(command.intersects(mgr.bar(bar_id).geometry()), bar_id)
        self.assertGreater(command.left(), mgr.bar("b6").geometry().right())
        self.assertLess(command.right(), mgr.bar("b7").geometry().left())
        self.assertEqual(command.bottom() + 1 + 16, self.pane.height())
        mgr.bar("b6").hide()                                                        # barre retiree : la commande reprend la place
        ui.place()
        self.assertLess(ui.command_bar.geometry().left(), command.left())

    def test_the_properties_panel_opens_under_the_top_bars(self):
        ui, mgr = self.ctl.ui, self.manager()
        ui.show_properties()
        settle(0.1)
        panel = ui.properties.geometry()
        self.assertTrue(ui.properties.isVisible())
        for bar_id in TOP_BARS:
            self.assertFalse(panel.intersects(mgr.bar(bar_id).geometry()), bar_id)
        self.assertGreater(panel.top(), max(mgr.bar(b).geometry().bottom() for b in TOP_BARS))
        self.assertTrue(ui.buttons["cad_properties"].active)                         # reste allume apres une synchronisation
        ui.sync()
        self.assertTrue(ui.buttons["cad_properties"].active)

    def test_the_zoom_bar_of_the_cad_drives_the_view(self):
        view = self.pane.view
        view.set_zoom(1.0)
        settle(0.05)
        zoom = self.manager().widgets["zoom"]
        self.assertEqual(zoom.text_value(), board_ui.format_zoom(1.0))
        self.manager().widgets["zoom_in"].click()
        self.assertGreater(view.zoom(), 1.0)
        zoom.click()
        self.assertEqual(view.zoom(), 1.0)

    def test_the_look_is_the_palette_look_of_fm_theme(self):
        mgr = self.manager()
        bar = mgr.bar("b1")
        before = bar.width()
        self.pane.apply_settings(dict(self.pane._settings, palette_cell_size=48))
        settle(0.05)
        self.assertGreater(bar.width(), before)                                      # reglages `palette_*` : tout suit

    def test_every_tool_paints_its_icon(self):
        for command, button in self.ctl.ui.buttons.items():
            button.resize(36, 36)
            self.assertFalse(button.grab().isNull(), command)


if __name__ == "__main__":
    unittest.main()

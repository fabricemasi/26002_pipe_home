"""fm_font, ESPACE DE TRAVAIL (Qt offscreen) : grille (recherche, filtres, manquants, création), éditeur, panneaux
(saisie précise : chasse, approches, coordonnées, renommage, famille), aperçu (crénage interactif, HarfBuzz),
features (génération, erreurs, application), diagnostic, enregistrement / réouverture, import, export, fermeture
d'un projet modifié."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os as _os2, tempfile as _tempfile  # sauvegardes de secours : jamais dans le dossier de l'utilisateur
_os2.environ.setdefault("FM_FONT_AUTOSAVE_DIR", _tempfile.mkdtemp(prefix="fmfont_secours_"))
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from _window_cleanup import WindowTestCase, track  # noqa: E402
from fm_font import kerning, shapes  # noqa: E402
from fm_font import pane as pane_mod  # noqa: E402

app = QApplication.instance() or QApplication([])


class PaneTest(WindowTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fmfont_pane_"))
        self.host = track(QWidget())
        self.host.resize(1400, 900)
        self.host.show()
        self.pane = pane_mod.FontPane(self.host)
        self.pane.show()
        app.processEvents()

    def tearDown(self):
        self.pane.shutdown()
        super().tearDown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def flush(self, seconds: float = 0.04):
        """Attente qui LIBÈRE le verrou Python (QTest.qWait le garde avec PySide 6.11 : un fil de fond — la
        compilation de l'aperçu HarfBuzz — n'avançait pas pendant le test)."""
        end = time.time() + seconds
        while True:
            app.processEvents()
            if time.time() >= end:
                break
            time.sleep(0.01)

    def create(self, text):
        self.pane.new_field.setText(text)
        self.pane.create_from_field()

    def test_grid_create_search_filters_and_missing(self):
        p = self.pane
        self.create("A")
        self.create("U+00E9")
        self.create("f_i")
        self.assertIn("eacute", p.project.font)
        self.assertEqual(p.project.font["A"].unicodes, [0x41])
        p.search.setText("é")
        self.assertEqual([n for _k, n in p.grid.entries], ["eacute"])
        p.search.setText("")
        p._set_category("Sans Unicode")
        self.assertEqual({n for _k, n in p.grid.entries}, {".notdef", "f_i"})
        p._set_category("Tous")
        p._set_charset("Latin de base")
        missing = [v for k, v in p.grid.entries if k == "missing"]
        self.assertIn(0x42, missing)
        self.assertNotIn(0x41, missing)
        p.create_missing("Latin de base")
        self.assertIn("B", p.project.font)
        self.assertEqual(p.project.undo.undo_label(), "Créer 93 glyphes")

    def test_editor_draw_then_panel_precise_input(self):
        p = self.pane
        self.create("H")
        p.show_glyph("H")
        cv = p.canvas
        cv.set_tool("rect")
        a, b = cv.to_widget(100, 0), cv.to_widget(500, 700)
        QTest.mousePress(cv, Qt.LeftButton, Qt.NoModifier, a.toPoint())
        QTest.mouseMove(cv, b.toPoint())
        QTest.mouseRelease(cv, Qt.LeftButton, Qt.NoModifier, b.toPoint())
        glyph = p.project.font["H"]
        self.assertEqual(len(glyph.contours), 1)
        t = p.glyph_panel.table
        t.fields["width"].setText("650")
        t._commit("width")
        self.flush()
        self.assertEqual(glyph.width, 650)
        lsb = round(glyph.contours[0][0].x)
        t.fields["lsb"].setText(str(lsb + 20))
        t._commit("lsb")
        self.flush()
        self.assertEqual(round(min(pt.x for pt in glyph.contours[0])), lsb + 20)
        cv.set_selection({(0, 0)})
        t.fields["x"].setText("33")
        t._commit("x")
        self.flush()
        self.assertEqual(glyph.contours[0][0].x, 33)
        t.fields["name"].setText("H.alt")
        t._commit("name")
        self.flush()
        self.assertIn("H.alt", p.project.font)
        self.assertEqual(p.current_name, "H.alt")

    def test_font_panel_metrics_and_family(self):
        p = self.pane
        t = p.font_panel.table
        t.fields["familyName"].setText("Ma Famille")
        t._commit("familyName")
        t.fields["xHeight"].setText("520")
        t._commit("xHeight")
        t.fields["unitsPerEm"].setText("5")
        t._commit("unitsPerEm")
        self.flush()
        info = p.project.font.info
        self.assertEqual((info.familyName, info.xHeight, info.unitsPerEm), ("Ma Famille", 520, 1000))
        self.assertIn("Ma Famille", p.title.text())

    def test_preview_kerning_alt_arrows_and_ctrl_drag(self):
        p = self.pane
        for c in "AV":
            self.create(c)
        f = p.project.font
        for n in "AV":
            f[n].contours.append(shapes.rectangle(0, 0, 500, 700))
            f[n].width = 600
        p.show_page("Aperçu")
        p.preview_field.setText("AV")
        p.preview.resize(800, 300)
        p.preview.grab()
        x = p.preview._line_geometry[0] + 650 * p.preview._line_geometry[2]
        QTest.mouseClick(p.preview, Qt.LeftButton, Qt.NoModifier, QPoint(int(x), 60))
        self.assertEqual(p.preview.current_pair(), ("A", "V"))
        QTest.keyClick(p.preview, Qt.Key_Left, Qt.AltModifier)
        QTest.keyClick(p.preview, Qt.Key_Left, Qt.AltModifier | Qt.ShiftModifier)
        self.assertEqual(kerning.lookup(f, "A", "V")[0], -11)
        line = p.preview.layout_line()
        self.assertEqual(line[1][1], 589)
        p.project.undo.undo()
        self.assertEqual(kerning.lookup(f, "A", "V")[0], -10)
        s = p.preview._line_geometry[2]
        QTest.mousePress(p.preview, Qt.LeftButton, Qt.ControlModifier, QPoint(int(x), 60))
        QTest.mouseMove(p.preview, QPoint(int(x - 40 * s), 60))
        QTest.mouseRelease(p.preview, Qt.LeftButton, Qt.ControlModifier, QPoint(int(x - 40 * s), 60))
        self.assertAlmostEqual(kerning.lookup(f, "A", "V")[0], -50, delta=2)
        self.assertEqual(p.project.undo.undo_label(), "Crénage")

    def test_preview_harfbuzz_background_compile_and_features(self):
        p = self.pane
        for c in ("f", "i", "f_i"):
            self.create(c)
        f = p.project.font
        for n in ("f", "i", "f_i"):
            f[n].contours.append(shapes.rectangle(0, 0, 100, 600))
            f[n].width = 300
        p.show_page("Features")
        p.features_page.generate(["liga"])
        self.assertTrue(p.features_page.apply())
        p.show_page("Aperçu")
        p.preview_field.setText("fi")
        p.hb_button.setChecked(True)
        p.preview.set_hb(True)
        deadline = time.time() + 20
        while p.project.revision not in p.preview._hb and time.time() < deadline:
            self.flush(0.05)
        self.assertEqual([n for n, _x, _y in p.preview.layout_line()], ["f_i"])
        p.preview.set_feature("liga", False)
        self.assertEqual([n for n, _x, _y in p.preview.layout_line()], ["f", "i"])

    def test_features_errors_are_readable(self):
        p = self.pane
        p.show_page("Features")
        p.features_page.editor.setPlainText("feature liga {\n sub f i by f_i\n} liga;")
        errors = p.features_page.check()
        self.assertTrue(errors)
        self.assertIn("Ligne 3", p.features_page.errors.text())
        self.assertFalse(p.features_page.apply())

    def test_diagnostics_page_and_glyph_link(self):
        p = self.pane
        self.create("A")
        p.project.font["A"].contours.append(shapes.rectangle(0, 0, 100, 100))
        p.project.font["A"].contours[0][0].type = "move"
        found = p.diagnostics_page.run()
        self.assertTrue(any(d.level == "bloquant" and d.glyph == "A" for d in found))
        p.diagnostics_page.glyphRequested.emit("A")
        self.assertEqual(p.current_name, "A")
        # rapport FontBakery (JSON) -> niveaux du diagnostic, sans lancer FontBakery
        from fm_font import validation
        report = {"sections": [{"checks": [
            {"description": "Contrôle A", "logs": [{"status": "PASS", "message": {"message": "ok"}}]},
            {"description": "Contrôle B", "logs": [{"status": "WARN", "message": {"message": "un  détail\nlong"}}]},
            {"description": "Contrôle C", "logs": [{"status": "INFO"}, {"status": "FAIL", "message": "brut"}]}]}]}
        found = validation.parse_fontbakery(report)
        self.assertEqual([(d.level, d.message) for d in found],
                         [("avertissement", "FontBakery FAIL — Contrôle C : brut"),
                          ("suggestion", "FontBakery WARN — Contrôle B : un détail long")])
        p.diagnostics_page._show(found, "FontBakery : ")
        self.assertIn("FontBakery : 0 bloquant(s), 1 avertissement(s)", p.diagnostics_page.counts.text())

    @unittest.skipUnless(__import__("importlib.util").util.find_spec("fontbakery"), "FontBakery absent")
    def test_fontbakery_runs_in_background(self):
        from _lent import ACTIFS
        if not ACTIFS:
            self.skipTest("test lent (~5 s) : python tests/run.py fm_font --lent")
        p = self.pane
        self.create("A")
        p.project.font["A"].contours.append(shapes.rectangle(0, 0, 400, 700))
        t = time.perf_counter()
        thread = p.diagnostics_page.fontbakery()
        self.assertLess(time.perf_counter() - t, 0.5)                    # l'interface n'attend pas
        self.assertIn("en cours", p.diagnostics_page.counts.text())
        thread.join(120)
        self.flush(0.1)
        self.assertIn("FontBakery : ", p.diagnostics_page.counts.text())

    def test_save_reopen_import_export_and_close(self):
        p = self.pane
        self.create("A")
        p.project.font["A"].contours.append(shapes.rectangle(50, 0, 550, 700))
        path = self.tmp / "Essai.ufo"
        p.project.save(path)
        p.project.edit_glyph("A", "x", lambda g: setattr(g, "width", 640))
        self.assertTrue(p.save())
        self.assertFalse(p.project.is_dirty())
        ttf = self.tmp / "Essai.ttf"
        self.assertTrue(p.export_to(ttf, "ttf"))
        self.assertTrue(p.open_path(path))
        self.assertEqual(p.project.font["A"].width, 640)
        self.assertTrue(p.open_path(ttf))
        self.assertIsNone(p.project.path)
        self.assertEqual(p.project.source, ttf)
        self.assertFalse(p.export_to(ttf, "ttf"))                       # jamais l'original importé
        # export en fond : le projet affiché peut changer pendant la compilation, l'instantané fait foi
        out = self.tmp / "Fond.otf"
        thread = p.export_to(out, "otf", background=True)
        p.project.edit_glyph("A", "z", lambda g: setattr(g, "width", 999))
        thread.join(30)
        self.flush(0.1)
        self.assertIn("Exporté", p.status_label.text())
        from fontTools.ttLib import TTFont
        self.assertEqual(TTFont(out)["hmtx"]["A"][0], 640)
        p.project.undo.undo()
        p.project.edit_glyph("A", "y", lambda g: setattr(g, "width", 700))
        closed = []
        p.closeRequested.connect(lambda: closed.append(True))
        with mock.patch.object(pane_mod, "confirm", side_effect=[False, False]):
            p.request_close()
        self.assertEqual(closed, [])
        with mock.patch.object(pane_mod, "confirm", side_effect=[False, True]):
            p.request_close()
        self.assertEqual(closed, [True])

    def test_masters_panel_adds_compatible_master(self):
        p = self.pane
        self.create("o")
        p.project.font["o"].contours.append(shapes.ellipse(0, 0, 500, 500))
        p.masters_panel.add()
        self.assertEqual([m.name for m in p.project.masters], ["Regular", "Bold"])
        p.set_master(1)
        self.assertEqual(p.canvas.font.info.styleName, "Bold")
        from fm_font.interpolation import incompatibilities
        self.assertEqual(incompatibilities(p.project), [])
        t = p.masters_panel.table
        t.fields["instances"].setText("Regular 400, Semi Bold 600, Bold 700")
        t._commit("instances")
        self.flush()
        self.assertEqual([(i.styleName, i.location["Weight"]) for i in p.project.instances],
                         [("Regular", 400), ("Semi Bold", 600), ("Bold", 700)])
        self.assertIn(("Semi Bold", {"Weight": 600}), p.instance_locations())
        # axes, carte (avar) et position du master courant depuis le panneau
        t.fields["axes"].setText("Weight wght 100 400 900 carte 100>20 400>80 900>200 ; Width wdth 75 100 125")
        t._commit("axes")
        self.flush()
        self.assertEqual([a.tag for a in p.project.axes], ["wght", "wdth"])
        self.assertEqual(t.fields["position"].text(), "Weight=152 Width=100")      # master Bold (700 utilisateur)
        t.fields["position"].setText("Weight=200")
        t._commit("position")
        self.flush()
        self.assertEqual(p.project.masters[1].location, {"Weight": 200, "Width": 100})
        t.fields["position"].setText("Weight=999")                                  # refusé, message lisible
        t._commit("position")
        self.flush()
        self.assertIn("hors de l'axe", p.status_label.text())
        self.assertEqual(t.fields["position"].text(), "Weight=200 Width=100")

    def test_context_menus_build(self):
        p = self.pane
        self.create("A")
        p.show_glyph("A")
        p.project.font["A"].contours.append(shapes.rectangle(0, 0, 100, 100))
        p.project.font["A"].contours.append(shapes.ellipse(200, 0, 400, 200))
        from fm_font import actions
        menu = actions.canvas_menu(p, QPoint(10, 10), p.canvas.to_widget(50, 0))
        self.assertGreater(len(menu.actions()), 5)
        menu.close()
        menu = actions.grid_menu(p, QPoint(10, 10))
        menu.close()
        p.canvas.set_selection({(0, 0), (0, 1)})
        actions.glyph_op(p.canvas, "mirror_h")
        p.canvas.set_selection({(1, 0)})
        actions.contour_op(p.canvas, "quadratic")
        self.assertEqual(p.project.undo.undo_label(), "Convertir en quadratiques")


if __name__ == "__main__":
    unittest.main()

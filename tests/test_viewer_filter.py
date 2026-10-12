"""Filtres de la planche : criteres (attributs, extension, taille, dates), portee (colonne, dossier du set,
racine : parcours en fond), fenetre des filtres (briques des reglages), bouton rouge + elements du filtre
ecrits a cote. Dossiers temporaires ; reglages jamais ecrits."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

import app_style
import browser_core
import file_attributes as fa
import file_filters as ff
import focus
import pipeline_browser as pb
import settings_store
import ui_state
from browser_core import ROLE_PATH


def write(path: Path, size: int = 10, age_days: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if age_days:
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
    return path


class CriteriaTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.a = write(self.dir / "a.jpg", 3 * ff.MB)
        self.b = write(self.dir / "b.png", 10, age_days=40)
        self.c = write(self.dir / "c.blend", 10)
        fa.update(self.a, rating=4, color=2, like=True, keywords=["ciel bleu", "nuit"], status="keep")
        fa.update(self.b, rating=2, status="delete")

    def names(self, spec):
        return [p.name for p in ff.filter_paths([self.a, self.b, self.c], spec)]

    def test_nothing_set_keeps_everything(self):
        self.assertFalse(ff.is_active({}))
        self.assertEqual(self.names({}), ["a.jpg", "b.png", "c.blend"])

    def test_attributes(self):
        self.assertEqual(self.names({"rating": 2}), ["a.jpg", "b.png"])            # au moins 2 etoiles
        self.assertEqual(self.names({"rating": 2, "rating_mode": "eq"}), ["b.png"])  # exactement 2
        self.assertEqual(self.names({"rating": 4, "rating_mode": "eq"}), ["a.jpg"])
        self.assertEqual(self.names({"color": 2}), ["a.jpg"])                      # ancien format : un entier
        self.assertEqual(self.names({"color": [1, 2]}), ["a.jpg"])                 # une des couleurs
        self.assertEqual(self.names({"color": [1, 3]}), [])
        self.assertFalse(ff.is_active({"rating_mode": "eq"}))                      # mode seul : rien
        self.assertEqual(self.names({"like": True}), ["a.jpg"])
        self.assertEqual(self.names({"keywords": ["CIEL"]}), ["a.jpg"])           # partie d'un mot cle
        self.assertEqual(self.names({"keywords": ["ciel", "ville"]}), [])          # tous les mots
        self.assertEqual(self.names({"status": "delete"}), ["b.png"])
        self.assertEqual(self.names({"status": ff.STATUS_NONE}), ["c.blend"])

    def test_type_size_and_dates(self):
        self.assertEqual(self.names({"extensions": ff.parse_extensions(".JPG, blend")}), ["a.jpg", "c.blend"])
        self.assertEqual(self.names({"size_min": 1}), ["a.jpg"])
        self.assertEqual(self.names({"size_max": 1}), ["b.png", "c.blend"])
        self.assertEqual(self.names({"period": "30d"}), ["a.jpg", "c.blend"])
        old = time.strftime("%d/%m/%Y", time.localtime(time.time() - 40 * 86400))
        self.assertEqual(self.names({"date_from": old, "date_to": old}), ["b.png"])

    def test_scan_goes_into_sub_folders_but_not_hidden_ones(self):
        write(self.dir / "sous" / "d.jpg")
        write(self.dir / ".cache" / "e.jpg")
        write(self.dir / "notes.txt")
        found = [p.relative_to(self.dir).as_posix() for p in ff.scan(self.dir, {})]
        self.assertEqual(found, ["a.jpg", "b.png", "c.blend", "sous/d.jpg"])
        self.assertEqual([p.name for p in ff.scan(self.dir, {"rating": 3})], ["a.jpg"])

    def test_provenance_from_the_folders_above(self):
        root = self.dir
        files = {
            "set/in/screenshots/a.png": "io:screenshots",       # sous-dossier de in / over / out : son nom
            "set/over/Rendu/b.png": "io:rendu",
            "set/out/c.png": "io:out",                          # pose directement dans out
            "set/softs/blender/scenes/d.blend": "work",         # dossier d'un logiciel
            "BIB/textures/e.jpg": "bib",
            "ARCHIVES/set/in/ref/f.png": "archives",            # archives d'abord
            "set/divers/g.png": "other",
        }
        paths = [write(root / rel) for rel in files]
        for path, key in zip(paths, files.values()):
            self.assertEqual(ff.provenance(path, root)[0], key, path)
        self.assertEqual([p.name for p in ff.filter_entries(paths, {"provenance": "io:rendu"}, root)], ["b.png"])
        self.assertEqual([p.name for p in ff.filter_entries(paths, {"provenance": "work"}, root)], ["d.blend"])
        choices = ff.provenance_choices(paths, root)
        self.assertEqual(choices[:4], list(ff.PROVENANCE_FIXED))
        self.assertEqual([label for _k, label in choices[4:]], ["out", "Rendu", "screenshots"])
        self.assertEqual(ff.describe({"provenance": "io:rendu"}), ["rendu"])
        self.assertEqual(ff.describe({"provenance": "work"}), ["travail"])

    def test_images_of_a_pureref_board_are_part_of_the_results(self):
        # Planche deja extraite : ses images (cache) sont parcourues a sa place ; leurs attributs sont ceux
        # rangés avec la planche.
        from config import DATA_DIR
        cache = Path(tempfile.mkdtemp(prefix="_test_pur_cache_", dir=DATA_DIR))     # comme le vrai cache
        self.addCleanup(shutil.rmtree, cache, True)
        images = [write(cache / "0001.png"), write(cache / "0002.png")]
        board = write(self.dir / "refs" / "in" / "ref" / "main.pur")
        with mock.patch("preview_column.pur_image_files", return_value=images):
            entries = ff.scan_files(self.dir / "refs")
        self.addCleanup(lambda: [fa._ALIASES.pop(os.path.normcase(str(i)), None) for i in images])
        self.assertEqual([e[0] for e in entries], images)
        self.assertEqual(entries[0][3][0], board)
        fa.update(images[1], rating=4, keywords=["vaisseau"])
        self.assertTrue((board.parent / fa.FILENAME).is_file())               # range avec la planche
        found = ff.filter_entries(entries, {"rating": 3, "provenance": "io:ref"}, self.dir)
        self.assertEqual(found, [images[1]])

    def test_description_written_next_to_the_button(self):
        items = ff.describe({"scope": "level:1", "rating": 3, "color": 1, "like": True, "keywords": ["nuit"],
                             "status": "keep", "extensions": ["jpg"], "size_min": 2, "period": "7d"},
                            ["Rouge"], "Projets : projA")
        self.assertEqual(ff.describe({"rating": 3, "rating_mode": "eq", "color": [1, 2]}, ["Rouge", "Vert"]),
                         ["= ★★★", "Rouge / Vert"])
        self.assertEqual(items, ["Projets : projA", "★★★+", "Rouge", "♥ j'aime", "#nuit", "à retenir", ".jpg",
                                 "≥ 2 Mo", "7 derniers jours"])


class WindowTest(unittest.TestCase):
    def test_window_rows_give_the_filter(self):
        settings = settings_store.load_settings()
        scopes = [("local", "Local (colonne en cours)"), ("root", "Toute la racine")]
        with mock.patch("settings_quick_style.save_settings"):
            window = focus.filter_window({"rating": 2}, scopes, settings=settings)
            self.addCleanup(window.deleteLater)
            got = []
            window.styleChanged.connect(got.append)
            fields = window.filter_fields
            self.assertEqual(list(fields), ["Portée", "Provenance", "Note", "Couleurs", "J'aime", "Mots clés", "Statut",
                                            "Type de fichier", "Taille min (0 = aucune)", "Taille max (0 = aucune)",
                                            "Date", "Modifié depuis le", "Modifié jusqu'au"])
            self.assertEqual(fields["Note"].stars.value(), 2)
            self.assertEqual(fields["Note"].mode.value(), "au moins")
            fields["Note"].mode.setValue("égal à")
            # Couleurs : plusieurs, chaque clic allume / eteint la sienne.
            from PySide6.QtCore import QPoint, Qt
            from PySide6.QtTest import QTest
            labels = fields["Couleurs"]
            labels.resize(labels.size())
            step = labels._step
            for index in (3, 1, 2, 1):
                QTest.mouseClick(labels, Qt.LeftButton, pos=QPoint(int(step * (index - 0.5)), labels.height() // 2))
            self.assertEqual(labels.values(), [2, 3])
            # Lignes ou un filtre est applique : marquees (fond / bordures des reglages), les autres non.
            def mark(label):
                row = fields[label]
                while row is not None and type(row).__name__ != "_TableRow":
                    row = row.parentWidget()
                return getattr(row, "_mark_look", None)
            self.assertIsNotNone(mark("Note"))
            self.assertIsNone(mark("Portée"))
            self.assertEqual(mark("Note")["bg"].lower(), "#403d7fd9")
            fields["Portée"].setValue("Toute la racine")
            fields["Type de fichier"].setText("jpg png")
            # Mots cles : saisis a la volee, separes par des espaces (meme champ que les attributs).
            words = fields["Mots clés"]
            self.assertIsNotNone(words._suggestions)
            QTest.keyClicks(words, "nuit")
            self.assertIsNotNone(mark("Mots clés"))
            self.assertIsNotNone(mark("Couleurs"))
            self.assertIsNotNone(mark("Portée"))
            self.assertIsNone(mark("J'aime"))
            # Clic droit : « Style des filtres activés… » (seulement dans la fenetre des filtres).
            from settings_widgets import Menu, add_context_extras
            opened = []
            window.on_row_style = lambda: opened.append(True)
            menu = Menu(None)
            add_context_extras(fields["J'aime"], menu)
            action = next(a for a in menu.actions() if a.text() == "Style des filtres activés…")
            action.trigger()
            self.assertEqual(opened, [True])
            other = Menu(None)
            add_context_extras(other, other)
            self.assertFalse(any(a.text() == "Style des filtres activés…" for a in other.actions()))
        spec = got[-1]
        self.assertEqual((spec["scope"], spec["rating"], spec["rating_mode"], spec["color"], spec["extensions"],
                          spec["keywords"]), ("root", 2, "eq", [2, 3], ["jpg", "png"], ["nuit"]))


class RowMarkShapeTest(unittest.TestCase):
    def test_active_rows_have_border_radius_and_margin(self):
        # Style des filtres activés : lignes « Border radius » et « Margin » (retrait dans la ligne).
        import settings_window_v2 as v2
        import ui_state
        self.assertEqual([sp.label for sp in v2.FILTER_ROW_SPECS][-2:], ["Border radius", "Margin"])
        saved = ui_state.APPLIED_SETTINGS
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", saved)
        settings = settings_store.load_settings()
        settings.update({"viewer_filter_row_radius": 8, "viewer_filter_row_bg_color": "#ff00ff00",
                         "viewer_filter_row_margin": {"left": 6, "top": 3, "right": 6, "bottom": 3}})
        ui_state.APPLIED_SETTINGS = settings
        with mock.patch("settings_quick_style.save_settings"):
            window = focus.filter_window({"rating": 3}, [("local", "Local")], settings=settings)
            self.addCleanup(window.deleteLater)
            window.show()
            QApplication.processEvents()
            row = window.filter_fields["Note"]
            while type(row).__name__ != "_TableRow":
                row = row.parentWidget()
            image = row.grab().toImage()
        mid = image.height() // 2
        self.assertNotEqual(image.pixelColor(2, mid).name(), "#00ff00")       # margin gauche
        self.assertEqual(image.pixelColor(20, mid).name(), "#00ff00")
        self.assertNotEqual(image.pixelColor(7, 4).name(), "#00ff00")         # coin arrondi


class EmptyGalleryTest(unittest.TestCase):
    def test_a_filter_that_keeps_nothing_shows_an_empty_planche(self):
        gallery = focus.FocusGallery(None, [], None)
        self.addCleanup(gallery.deleteLater)
        gallery.resize(800, 600)
        gallery.show()
        gallery.reveal_current(None)
        gallery.warm_cells(False)
        gallery.start_ripple(wave=False)
        for _ in range(5):
            APP.processEvents()


def select(column, name):
    for i in range(column.list.count()):
        item = column.list.item(i)
        if Path(item.data(ROLE_PATH)).name == name:
            column.list.setCurrentItem(item)
            APP.processEvents()
            return
    raise AssertionError(f"{name} absent de {column.column_title}")


class PlancheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_style.apply_style(APP)

    def setUp(self):
        for module in (settings_store, pb, browser_core):
            for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
                if hasattr(module, name):
                    patcher = mock.patch.object(module, name, lambda *a, **k: None)
                    patcher.start()
                    self.addCleanup(patcher.stop)
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.here = [write(self.root / "3d/projA/sp1/in" / n) for n in ("a.png", "b.png", "c.jpg")]
        self.far = write(self.root / "3d/projA/sp2/in/d.png")
        write(self.root / "2d/autre/x/e.png")
        fa.update(self.here[0], rating=5)
        fa.update(self.far, rating=5)

    def test_active_filter_style_is_saved_in_real_time(self):
        win = pb.PipelineBrowser(self.root)
        win._idle_preview_scheduler.timer.stop()
        self.addCleanup(win.deleteLater)
        saved = ui_state.APPLIED_SETTINGS
        ui_state.APPLIED_SETTINGS = dict(saved or settings_store.load_settings())
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", saved)
        with mock.patch.object(pb, "save_settings") as save, \
                mock.patch.object(browser_core, "_sync_default_preset_override") as preset:
            win._on_filter_row_style({"viewer_filter_row_bg_color": "#80ff0000"})
            save.assert_called_once()                          # tout de suite, pas 300 ms apres
            self.assertEqual(save.call_args[0][0]["viewer_filter_row_bg_color"], "#80ff0000")
            preset.assert_called_once()                        # et dans le preset actif
            # Pendant un geste (curseur tire) : ecrit au relachement seulement.
            with mock.patch.object(pb.QApplication, "mouseButtons", return_value=pb.Qt.LeftButton):
                win._on_filter_row_style({"viewer_filter_row_border_thickness": 3})
            save.assert_called_once()

    def test_filter_button_window_and_scope(self):
        win = pb.PipelineBrowser(self.root)
        win._idle_preview_scheduler.timer.stop()
        win.resize(1400, 800)
        win.show()
        APP.processEvents()
        self.addCleanup(win.deleteLater)
        select(win.columns[0], "3d")
        select(win.columns[1], "projA")
        select(win.columns[2], "sp1")
        # Planche ouverte (colonnes masquees) sur le dossier sp1.
        win._project_columns_hidden = True
        win._viewer_paths = win._viewer_base = list(self.here)
        win._viewer_index = 0
        win._open_focus_gallery()
        APP.processEvents()
        self.assertIsNotNone(win._focus_gallery)
        button = win._filter_btn
        self.assertTrue(button.isVisible())
        self.assertIsNone(button._alert)
        self.assertFalse(win._filter_chips.isVisible())
        # Note >= 5, portee locale : seule a.png ; bouton rouge, elements ecrits a cote.
        win._set_viewer_filter({"rating": 5})
        self.assertEqual([p.name for p in win._gallery_list], ["a.png"])
        self.assertIsNotNone(button._alert)
        chips = win._filter_chips
        self.assertTrue(chips.isVisible())
        self.assertEqual(chips._items, ["★★★★★", "1 fichier"])
        self.assertGreater(chips.x(), button.geometry().right())
        # Portee = le projet : tout ce qui est sous projA (parcours en fond).
        scopes = dict(win._filter_scopes())
        self.assertEqual(scopes["level:1"].lower(), "projets : proja")
        win._set_viewer_filter({"rating": 5, "scope": "level:1"})
        deadline = time.monotonic() + 5
        while win._filter_task is not None and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.01)
        self.assertEqual([p.name for p in win._gallery_list], ["a.png", "d.png"])
        self.assertIn("2 fichiers", chips._items)
        # Un fichier d'un autre dossier choisi dans la planche : la visionneuse parcourt les fichiers filtres
        # et, au repos, les colonnes vont jusqu'a lui.
        win._on_gallery_chosen(self.far)
        self.assertEqual([p.name for p in win._viewer_paths], ["a.png", "d.png"])
        self.assertEqual(win._viewer_index, 1)
        win._flush_viewer_sync()
        APP.processEvents()
        self.assertTrue(any(c.current_path() == self.far for c in [*win.columns, *win.group_columns]))
        win._open_focus_gallery()                    # retour a la planche filtree
        APP.processEvents()
        # Toute la racine, sans critere : tous les fichiers a apercu.
        win._set_viewer_filter({"scope": "root"})
        deadline = time.monotonic() + 5
        while win._filter_task is not None and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.01)
        self.assertEqual(len(win._gallery_list), 5)
        # Clic droit > Retirer le filtre : la colonne, bouton normal, plus rien d'ecrit.
        win._clear_viewer_filter()
        self.assertEqual([p.name for p in win._gallery_list], ["a.png", "b.png", "c.jpg"])
        self.assertIsNone(button._alert)
        self.assertFalse(chips.isVisible())
        # La fenetre des filtres s'ouvre depuis le bouton, avec les portees du set.
        with mock.patch("settings_quick_style.save_settings"):
            button.click()
            window = win._filter_window
            self.assertIsNotNone(window)
            self.assertIn("Toute la racine", window.filter_fields["Portée"]._options)
            window.close()


if __name__ == "__main__":
    unittest.main()

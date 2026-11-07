"""Modules qui savent ouvrir un fichier (main_window/module_targets.py), partout dans le browser (demande de
l'utilisateur) : lignes « Ouvrir dans … » du menu d'une ligne de colonne, de la pellicule / planche et de l'image
du focus ; boutons de mode de la barre dégrisés sur le fichier choisi dans les colonnes OU montré par la
visionneuse, qui se referme avant d'ouvrir le module. Dossier temporaire ; aucun module réellement ouvert."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QPoint, QRectF
from PySide6.QtGui import QContextMenuEvent, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from _window_cleanup import WindowTestCase, track  # noqa: E402
import column as column_module  # noqa: E402
from browser_core import ROLE_PATH  # noqa: E402
from main_window.board_module import BoardModuleMixin  # noqa: E402
from main_window.chrome import ChromeMixin  # noqa: E402
from main_window.module_targets import ModuleTargetsMixin, module_targets  # noqa: E402
from main_window.side_module import SideModuleMixin, _SideViewer  # noqa: E402
from main_window.viewer_chrome import ViewerChromeMixin  # noqa: E402
from settings_widgets import Menu  # noqa: E402

app = QApplication.instance() or QApplication([])


class _Host(ModuleTargetsMixin, SideModuleMixin, BoardModuleMixin, ChromeMixin, ViewerChromeMixin, QWidget):
    """Fenêtre principale réduite : boutons de mode, sélection, visionneuse ; les ouvertures sont notées."""

    def __init__(self):
        super().__init__()
        from preview_column import IconButton
        self.selected = None
        self.opened = []
        self._md_open = False
        self._board = self._video = self._font = None
        self._project_columns_hidden = False
        self._viewer_paths, self._viewer_index = [], -1
        for name in ("btn_viewer", "btn_text_editor", "btn_board", "btn_video", "btn_font"):
            setattr(self, name, IconButton(name[4:], "#c4cacf", "#ffffff", parent=self))
        for key, method in (("md", "_open_md_editor"), ("board", "_open_board"), ("cad", "_open_cad_drawing"),
                            ("sheet", "_open_spreadsheet"), ("video", "_open_video"), ("font", "_open_font")):
            setattr(self, method, lambda path, k=key: self.opened.append((k, Path(path))))

    def _selected_path(self):
        return None, self.selected

    def _set_columns_hidden(self, hidden, animate=True):
        self.opened.append(("viewer closed", animate))
        self._project_columns_hidden = hidden

    def _view_in_viewer(self, path, column=None):
        self.opened.append(("viewer", Path(path)))

    def usable(self):
        return {name for name in ("text_editor", "board", "video", "font") if getattr(self, f"btn_{name}").isEnabled()}


def _menu_picking(label, seen):
    def fake_exec(menu, *args, **kwargs):
        seen[:] = [a.text() for a in menu.actions()]
        return next((a for a in menu.actions() if a.text() == label), None)
    return mock.patch.object(Menu, "exec", fake_exec)


def _settle():
    for _ in range(3):
        app.processEvents()


class ModuleTargetsTest(WindowTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="modules_"))
        for name in ("notes.csv", "clip.mp4", "plan.dxf", "scene.mro", "Essai.ttf"):
            (self.tmp / name).write_bytes(b"")
        (self.tmp / "Essai.ufo").mkdir()
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(0x336699)
        for name in ("a.png", "b.png"):
            image.save(str(self.tmp / name))

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_single_click_opens_images_texts_and_fonts(self):
        """Simple clic sur un fichier (demande de l'utilisateur, 2026-11-03) : image = visionneuse, texte / code =
        module Markdown, police = module typographique ; un autre fichier (ou un dossier) ne fait rien."""
        from main_window.module_targets import click_target
        self.assertEqual(click_target(self.tmp / "a.png"), "viewer")
        self.assertEqual(click_target(self.tmp / "notes.csv"), "md")
        self.assertEqual(click_target(self.tmp / "Essai.ttf"), "font")
        self.assertIsNone(click_target(self.tmp / "clip.mp4"))
        self.assertIsNone(click_target(self.tmp / "Essai.ufo"))
        host = self.track(_Host()) if hasattr(self, "track") else _Host()
        for name in ("a.png", "notes.csv", "Essai.ttf", "clip.mp4"):
            host.on_file_clicked(None, self.tmp / name)
            _settle()
        self.assertEqual(host.opened, [("viewer", self.tmp / "a.png"), ("md", self.tmp / "notes.csv"),
                                       ("font", self.tmp / "Essai.ttf")])

    def test_a_single_click_opens_the_image_beside_the_columns(self):
        """Simple clic sur une image : visionneuse À CÔTÉ de la colonne (les colonnes restent) ; double-clic sur
        l'image : la visionneuse pleine."""
        host = track(QWidget())
        host.resize(900, 500)
        host.show()
        image = QImage(400, 300, QImage.Format_RGB32)
        image.fill(0xff3366)
        full = []
        viewer = _SideViewer(host, 300, self.tmp / "a.png", QPixmap.fromImage(image), None, lambda: full.append(1))
        self.addCleanup(viewer.close_now)
        self.assertEqual(viewer.geometry().getRect(), (300, 0, 600, 500))     # colonnes à gauche : visibles
        viewer.overlay.finish_now()
        target = viewer.overlay.current_rect()
        self.assertTrue(QRectF(viewer.rect()).contains(target))
        host.resize(1000, 500)
        self.assertEqual(viewer.width(), 700)                                 # suit la fenêtre
        viewer.overlay._on_double_click()
        self.assertEqual(full, [1])

    def test_the_markdown_pane_can_sit_beside_the_columns(self):
        import fm_markdown.pane as md_pane
        host = track(QWidget())
        host.resize(900, 500)
        pane = md_pane.MarkdownPane.__new__(md_pane.MarkdownPane)
        QWidget.__init__(pane)
        self.addCleanup(pane.deleteLater)
        md_pane.MarkdownPane.attach(pane, host, 250)
        self.assertEqual(pane.geometry().getRect(), (250, 0, 650, 500))
        pane.set_side_left(0)                                                 # double-clic : plein
        self.assertEqual(pane.geometry().getRect(), (0, 0, 900, 500))

    def test_table(self):
        self.assertEqual(module_targets(self.tmp / "notes.csv", False), ["md", "sheet"])   # deux modules : les deux
        self.assertEqual(module_targets(self.tmp / "plan.dxf", False), ["cad"])
        self.assertEqual(module_targets(self.tmp / "scene.mro", False), ["board"])
        self.assertEqual(module_targets(self.tmp / "clip.mp4", False), ["video"])
        self.assertEqual(module_targets(self.tmp / "Essai.ttf", False), ["font"])
        self.assertEqual(module_targets(self.tmp / "Essai.ufo", True), ["font"])
        self.assertEqual(module_targets(self.tmp, True), [])
        self.assertEqual(module_targets(None, False), [])
        start = time.perf_counter()
        for _ in range(1000):
            module_targets(self.tmp / "a.png", False)
        self.assertLess((time.perf_counter() - start) / 1000, 0.0005)       # à chaque clic : aucun accès disque

    def test_buttons_follow_columns_and_viewer(self):
        host = track(_Host())
        host._sync_mode_buttons()
        self.assertEqual(host.usable(), set())
        self.assertFalse(host.btn_viewer.isEnabled())                       # rien de choisi : visionneuse grisée
        host.selected = self.tmp / "notes.csv"
        host._sync_mode_buttons()
        self.assertEqual(host.usable(), {"text_editor", "board"})
        self.assertFalse(host.btn_viewer.isEnabled())                       # pas un fichier qu'elle sait montrer
        for path, viewable in ((self.tmp, False), (self.tmp / "Essai.ufo", False), (self.tmp / "a.png", True)):
            host.selected = path
            host._sync_mode_buttons()
            self.assertEqual(host.btn_viewer.isEnabled(), viewable, path)
        host.selected = self.tmp / "notes.csv"
        host._toggle_board()                                                # bouton « Board » : le tableur
        self.assertEqual(host.opened, [("sheet", self.tmp / "notes.csv")])
        # Visionneuse ouverte (focus ou planche) : les boutons suivent l'image montrée, pas les colonnes.
        host.opened.clear()
        host._project_columns_hidden = True
        host._viewer_paths, host._viewer_index = [str(self.tmp / "a.png"), str(self.tmp / "clip.mp4")], 1
        host._sync_mode_buttons()
        self.assertEqual(host.usable(), {"video"})
        self.assertTrue(host.btn_viewer.isEnabled())                        # ouverte : pour en sortir
        host._open_selected_in(("video",))
        self.assertEqual(host.opened, [("viewer closed", False), ("video", self.tmp / "clip.mp4")])

    def test_column_menu_lists_every_module(self):
        host = track(_Host())
        column = column_module.Column(self.tmp, "Contenu")
        column.setParent(host)
        column.resize(300, 600)
        host.resize(300, 600)
        host.show()
        deadline = time.monotonic() + 5
        while column.loading or column._load_timer.isActive():
            app.processEvents()
            self.assertLess(time.monotonic(), deadline)
        rows = {Path(column.list.item(i).data(ROLE_PATH)).name: column.list.item(i) for i in range(column.list.count())}
        seen = []
        for name, label, expected in (
                ("notes.csv", "Ouvrir dans le tableur", ["Ouvrir dans l'éditeur de texte", "Ouvrir dans le tableur"]),
                ("plan.dxf", "Ouvrir dans le module CAD", ["Ouvrir dans le module CAD"]),
                ("Essai.ufo", "Ouvrir dans le module typographique", ["Ouvrir dans le module typographique"]),
                ("a.png", "Ouvrir dans la visionneuse", ["Ouvrir dans la visionneuse", "Ouvrir dans le module vidéo"])):
            host.opened.clear()
            with _menu_picking(label, seen):
                column._on_context_menu(column.list.visualItemRect(rows[name]).center())
            _settle()
            self.assertEqual([t for t in seen if t.startswith("Ouvrir dans")], expected, name)
            self.assertEqual(seen[seen.index("Ouvrir") + 1], expected[0])   # juste après « Ouvrir »
            self.assertEqual(host.opened[-1][1], self.tmp / name)
        self.assertEqual(host.opened[-1][0], "viewer")

    def test_filmstrip_gallery_and_focus_menus(self):
        host = track(_Host())
        seen = []
        with _menu_picking("Ouvrir dans l'éditeur de texte", seen):
            host._filmstrip_menu(QPoint(0, 0), self.tmp / "notes.csv")
        _settle()
        self.assertEqual(seen[:3], ["Ouvrir dans l'éditeur de texte", "Ouvrir dans le tableur", ""])
        self.assertIn("Changement de style à la volée", seen)
        self.assertEqual(host.opened, [("md", self.tmp / "notes.csv")])
        with _menu_picking("", seen):
            host._filmstrip_menu(QPoint(0, 0))                             # hors d'une case : le style seul
        self.assertEqual(seen[0], "Changement de style à la volée")
        # Planche : le clic droit donne le fichier de la case sous la souris.
        from fm_visionneuse.gallery import FocusGallery
        got = []
        paths = [self.tmp / "a.png", self.tmp / "b.png"]
        gallery = FocusGallery(host, paths, paths[0], on_menu=lambda pos, path: got.append(path))
        gallery.resize(600, 400)
        host.resize(600, 400)
        host.show()
        _settle()
        rect = gallery.visualItemRect(gallery.item(1))
        global_pos = gallery.viewport().mapToGlobal(rect.center())
        app.sendEvent(gallery.viewport(), QContextMenuEvent(QContextMenuEvent.Mouse, rect.center(), global_pos))
        self.assertEqual(got, [self.tmp / "b.png"])
        # Focus : clic droit sur l'image au repos -> modules de l'image en cours.
        from fm_visionneuse.overlay import FocusOverlay
        pixmap = QPixmap(40, 40)
        overlay = FocusOverlay(host, pixmap, QRectF(0, 0, 40, 40), QRectF(0, 0, 40, 40), 1.0, 1.0, 1)
        overlay.on_menu = host._focus_menu
        deadline = time.monotonic() + 2
        while not overlay._at_rest():
            app.processEvents()
            self.assertLess(time.monotonic(), deadline)
        host._project_columns_hidden = True
        host._viewer_paths, host._viewer_index = paths, 0
        host.opened.clear()
        with _menu_picking("Ouvrir dans le module vidéo", seen):
            overlay.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(5, 5), QPoint(5, 5)))
        _settle()
        self.assertEqual(seen, ["Ouvrir dans le module vidéo"])
        self.assertEqual(host.opened, [("viewer closed", False), ("video", self.tmp / "a.png")])


if __name__ == "__main__":
    unittest.main()

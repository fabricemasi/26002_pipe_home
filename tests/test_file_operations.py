"""Supprimer (menu d'une ligne) et glisser dans un autre dossier : toujours une fenetre de confirmation
(settings_dialogs.confirm) ; suppression = corbeille (sinon, 2e confirmation pour supprimer definitivement) ;
glisser = rien ne bouge tant que ce n'est pas confirme. La corbeille n'est jamais touchee ici
(QFile.moveToTrash simule)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

app = QApplication.instance() or QApplication([])

import column as column_module
import settings_dialogs
from browser_core import ROLE_PATH
from column import Column


class _FakeTrash:
    """QFile.moveToTrash simule : supprime (ok=True) ou refuse (ok=False)."""

    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def moveToTrash(self, path):
        self.calls.append(path)
        if self.ok:
            p = Path(path)
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        return self.ok


class _Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "dossier").mkdir()
        (self.root / "dossier" / "dedans.txt").write_text("x")
        (self.root / "fichier.txt").write_text("y")
        self.column = Column(self.root, "Contenu")
        self.column.resize(260, 400)
        self.column.show()
        self.column.refresh()
        self.addCleanup(self.column.deleteLater)
        app.processEvents()

    def answers(self, *values):
        replies = list(values)
        self.asked = []

        def fake(parent, tag, title, message, items=(), action="Valider"):
            self.asked.append((tag, title, message, list(items), action))
            return replies.pop(0)
        return mock.patch.object(settings_dialogs, "confirm", fake)


class DeleteTest(_Base):
    def test_cancel_keeps_the_file(self):
        trash = _FakeTrash()
        with self.answers(False), mock.patch.object(column_module, "QFile", trash):
            self.assertFalse(self.column.delete_path(self.root / "fichier.txt"))
        self.assertTrue((self.root / "fichier.txt").exists())
        self.assertEqual(trash.calls, [])
        self.assertEqual(self.asked[0][0], "Supprimer")

    def test_confirmed_goes_to_the_trash(self):
        trash = _FakeTrash()
        with self.answers(True), mock.patch.object(column_module, "QFile", trash):
            self.assertTrue(self.column.delete_path(self.root / "dossier"))
        self.assertFalse((self.root / "dossier").exists())
        self.assertEqual(trash.calls, [str(self.root / "dossier")])
        self.assertIn("tout son contenu", self.asked[0][2])
        names = [self.column.list.item(i).text() for i in range(self.column.list.count())]
        self.assertNotIn("dossier", names)

    def test_trash_refused_asks_again_before_deleting_for_good(self):
        trash = _FakeTrash(ok=False)
        with self.answers(True, False), mock.patch.object(column_module, "QFile", trash):
            self.assertFalse(self.column.delete_path(self.root / "fichier.txt"))
        self.assertTrue((self.root / "fichier.txt").exists())
        self.assertIn("DÉFINITIVEMENT", self.asked[1][2])
        with self.answers(True, True), mock.patch.object(column_module, "QFile", trash):
            self.assertTrue(self.column.delete_path(self.root / "fichier.txt"))
        self.assertFalse((self.root / "fichier.txt").exists())

    def test_menu_offers_delete_on_files_and_folders(self):
        seen = []

        class FakeMenu(column_module.Menu):
            def exec(self, *_a):
                seen.append([a.text() for a in self.actions()])
                return None

        lst = self.column.list
        with mock.patch.object(column_module, "Menu", FakeMenu):
            for i in range(lst.count()):
                self.column._on_context_menu(lst.visualItemRect(lst.item(i)).center())
        self.assertEqual(len(seen), 2)
        for texts in seen:
            self.assertIn("Supprimer", texts)


class DropTest(_Base):
    def setUp(self):
        super().setUp()
        self.target = self.root / "dossier"
        self.urls = [QUrl.fromLocalFile(str(self.root / "fichier.txt"))]

    def test_nothing_moves_until_confirmed(self):
        with self.answers(False):
            self.assertIsNone(self.column.list.confirm_drop(self.urls, Qt.MoveAction, self.target))
        self.assertTrue((self.root / "fichier.txt").exists())
        self.assertFalse((self.target / "fichier.txt").exists())
        tag, title, message, items, action = self.asked[0]
        self.assertEqual((tag, title, items, action), ("Déplacer", "dossier", ["fichier.txt"], "Déplacer"))

    def test_confirmed_move(self):
        with self.answers(True):
            self.column.list.confirm_drop(self.urls, Qt.MoveAction, self.target)
        self.assertFalse((self.root / "fichier.txt").exists())
        self.assertTrue((self.target / "fichier.txt").exists())

    def test_copy_is_confirmed_too(self):
        with self.answers(True):
            self.column.list.confirm_drop(self.urls, Qt.CopyAction, self.target)
        self.assertTrue((self.root / "fichier.txt").exists())
        self.assertTrue((self.target / "fichier.txt").exists())
        self.assertEqual(self.asked[0][0], "Copier")

    def test_no_window_when_there_is_nothing_to_do(self):
        same_folder = [QUrl.fromLocalFile(str(self.target / "dedans.txt"))]
        with self.answers():
            self.assertIsNone(self.column.list.confirm_drop(same_folder, Qt.MoveAction, self.target))
        self.assertEqual(self.asked, [])


class DialogTest(unittest.TestCase):
    def _run(self, key):
        dialog = settings_dialogs.ConfirmDialog(None, "Supprimer", "x.txt", "Mettre à la corbeille ?",
                                                [f"f{i}" for i in range(12)], "Supprimer")
        QTimer.singleShot(50, lambda: QTest.keyClick(dialog, key))
        result = dialog.exec()
        labels = [w.text() for w in dialog.findChildren(QLabel)]
        dialog.deleteLater()
        return result, labels

    def test_enter_confirms_escape_cancels(self):
        self.assertEqual(self._run(Qt.Key_Return)[0], QDialog.Accepted)
        self.assertEqual(self._run(Qt.Key_Escape)[0], QDialog.Rejected)

    def test_long_lists_are_shortened(self):
        _result, labels = self._run(Qt.Key_Escape)
        self.assertIn("f7", labels)
        self.assertNotIn("f8", labels)
        self.assertIn("… et 4 autre(s)", labels)


class DropPreviewTest(_Base):
    """Glisser d'une colonne a l'autre : la ligne en curseur, et un apercu en direct de l'emplacement."""

    def other(self):
        src = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, src, True)
        (src / "b_image.png").write_text("z")
        (src / "a_dir").mkdir()
        return src

    def test_predicted_place_follows_the_column_sort(self):
        src = self.other()
        view = self.column.list
        self.assertEqual(view.predicted_row(src / "a_dir"), 0)             # dossiers d'abord, par nom
        self.assertEqual(view.predicted_row(src / "b_image.png"), 1)       # apres « dossier », avant « fichier.txt »

    def test_preview_shows_one_slot_or_the_folder_aimed_at(self):
        src = self.other()
        view = self.column.list
        urls = [QUrl.fromLocalFile(str(src / "b_image.png"))]
        last = view.visualItemRect(view.item(view.count() - 1))
        view._drop_cache = {}
        view._update_drop_preview(last.center(), urls)                    # sur « fichier.txt »
        self.assertIsNone(view._drop_preview.folder_row)
        self.assertIsNotNone(view._drop_preview.slot_y)
        folder = view.visualItemRect(view.item(0))                        # « dossier »
        view._update_drop_preview(folder.center(), urls)
        self.assertEqual(view._drop_preview.folder_row, 0)
        # Deja dans ce dossier : rien a montrer.
        view._drop_cache = {}
        view._update_drop_preview(last.center(), [QUrl.fromLocalFile(str(self.root / "fichier.txt"))])
        self.assertIsNone(view._drop_preview)

    def test_drag_image_is_the_row_at_drag_opacity(self):
        view = self.column.list
        pixmap = view.drag_pixmap(view.item(0))
        rect = view.visualItemRect(view.item(0))
        self.assertEqual(pixmap.deviceIndependentSize().toSize(), rect.size())
        alpha = pixmap.toImage().pixelColor(rect.width() // 2, rect.height() // 2).alpha()
        self.assertTrue(180 <= alpha <= 200, alpha)                     # 75 %


if __name__ == "__main__":
    unittest.main()

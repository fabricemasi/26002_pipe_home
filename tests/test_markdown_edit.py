"""Edition des notes .md depuis l'inspecteur : lecture / ecriture fideles (encodage, BOM, fins de
ligne), bascule lecture / edition, enregistrement automatique, conflit avec une modification
exterieure, enregistrement au changement de fichier."""
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

from PySide6.QtWidgets import QApplication, QMessageBox

APP = QApplication.instance() or QApplication([])

import detail_panel as dp
import markdown_preview as mp


class NoteFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_round_trip_keeps_bom_and_crlf(self):
        path = self.dir / "a.md"
        path.write_bytes(b"\xef\xbb\xbf# \xc3\xa9t\xc3\xa9\r\nligne\r\n")
        text, info = mp.read_note(path)
        self.assertEqual(text, "# été\nligne\n")
        mp.write_note(path, text + "ajout\n", info)
        self.assertEqual(path.read_bytes(), b"\xef\xbb\xbf# \xc3\xa9t\xc3\xa9\r\nligne\r\najout\r\n")
        self.assertFalse(mp.changed_on_disk(path, info))
        self.assertFalse(any(p.name.endswith(".tmp") for p in self.dir.iterdir()))

    def test_legacy_windows_encoding_is_kept(self):
        path = self.dir / "b.md"
        path.write_bytes("caf\xe9\n".encode("cp1252"))
        text, info = mp.read_note(path)
        self.assertEqual((text, info["encoding"]), ("café\n", "cp1252"))
        mp.write_note(path, "thé\n", info)
        self.assertEqual(path.read_bytes(), "thé\n".encode("cp1252"))

    def test_external_change_is_detected(self):
        path = self.dir / "c.md"
        path.write_text("x", encoding="utf-8")
        _text, info = mp.read_note(path)
        time.sleep(0.02)
        path.write_text("y", encoding="utf-8")
        os.utime(path, ns=(info["mtime_ns"] + 10_000_000, info["mtime_ns"] + 10_000_000))
        self.assertTrue(mp.changed_on_disk(path, info))


class _FakeBox:
    """QMessageBox de remplacement : repond `choice` sans ouvrir de fenetre."""
    Warning, AcceptRole, DestructiveRole, RejectRole = (QMessageBox.Warning, QMessageBox.AcceptRole,
                                                        QMessageBox.DestructiveRole, QMessageBox.RejectRole)
    choice = None
    asked = 0

    def __init__(self, *_args, **_kwargs):
        self._buttons = {}

    def addButton(self, text, _role):
        self._buttons[text] = object()
        return self._buttons[text]

    def exec(self):
        _FakeBox.asked += 1

    def clickedButton(self):
        return self._buttons.get(_FakeBox.choice)

    @staticmethod
    def warning(*_args):
        pass


@unittest.skipUnless(mp.available(), "markdown-it-py absent")
class InspectorEditTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.note = self.dir / "note.md"
        self.note.write_text("# Titre\n", encoding="utf-8")
        self.panel = dp.DetailPanel()
        self.addCleanup(self.panel.deleteLater)
        _FakeBox.asked = 0
        patcher = mock.patch.object(dp, "QMessageBox", _FakeBox)
        patcher.start()
        self.addCleanup(patcher.stop)

    def edit(self, text):
        editor = self.panel.markdown_editor
        cursor = editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        editor.insertPlainText(text)

    def test_toggle_edit_and_autosave(self):
        panel = self.panel
        panel.show_path(self.note)
        self.assertFalse(panel._md_editing)
        self.assertEqual(panel.markdown_mode_button.text(), "Modifier")
        panel._toggle_markdown_mode()
        self.assertTrue(panel._md_editing)
        self.assertEqual(panel.markdown_editor.toPlainText(), "# Titre\n")
        self.edit("Ajout\n")
        self.assertTrue(panel._md_dirty)
        self.assertTrue(panel._md_save_timer.isActive())       # enregistrement automatique programme
        panel._md_save_timer.timeout.emit()
        self.assertEqual(self.note.read_text(encoding="utf-8"), "# Titre\nAjout\n")
        self.assertEqual(panel.markdown_status.text(), "Enregistré")
        self.edit("Encore\n")
        panel._toggle_markdown_mode()                          # retour en lecture : enregistre aussitot
        self.assertFalse(panel._md_editing)
        self.assertEqual(self.note.read_text(encoding="utf-8"), "# Titre\nAjout\nEncore\n")

    def test_conflict_keep_or_reload(self):
        panel = self.panel
        panel.show_path(self.note)
        panel._toggle_markdown_mode()
        info = panel._md_info
        self.note.write_text("# Version Obsidian\n", encoding="utf-8")
        os.utime(self.note, ns=(info["mtime_ns"] + 10_000_000, info["mtime_ns"] + 10_000_000))
        self.edit("Mien\n")
        _FakeBox.choice = "Recharger le fichier"
        self.assertTrue(panel._flush_markdown())
        self.assertEqual(_FakeBox.asked, 1)
        self.assertEqual(panel.markdown_editor.toPlainText(), "# Version Obsidian\n")
        self.assertEqual(self.note.read_text(encoding="utf-8"), "# Version Obsidian\n")
        # Meme situation, mais on garde sa version.
        info = panel._md_info
        self.note.write_text("# Encore change\n", encoding="utf-8")
        os.utime(self.note, ns=(info["mtime_ns"] + 20_000_000, info["mtime_ns"] + 20_000_000))
        self.edit("Mien\n")
        _FakeBox.choice = "Garder ma version"
        self.assertTrue(panel._flush_markdown())
        self.assertEqual(self.note.read_text(encoding="utf-8"), "# Version Obsidian\nMien\n")
        # Annuler : rien n'est ecrit, on reste en edition.
        info = panel._md_info
        self.note.write_text("# Autre\n", encoding="utf-8")
        os.utime(self.note, ns=(info["mtime_ns"] + 30_000_000, info["mtime_ns"] + 30_000_000))
        self.edit("x")
        _FakeBox.choice = "Annuler"
        panel._toggle_markdown_mode()
        self.assertTrue(panel._md_editing)
        self.assertEqual(self.note.read_text(encoding="utf-8"), "# Autre\n")

    def test_web_view_is_outside_graphics_effects(self):
        """Une vue web sous un QGraphicsEffect (coins arrondis de la carte) reste figee a l'ecran :
        elle doit n'avoir aucun ancetre a effet, et suivre sa place dans la mise en page."""
        panel = self.panel
        panel.resize(600, 800)
        panel.show()
        panel.show_path(self.note)
        APP.processEvents()
        view, slot = panel.markdown_view, panel.markdown_slot
        widget = view
        while widget is not None:
            self.assertIsNone(widget.graphicsEffect(), type(widget).__name__)
            widget = widget.parentWidget()
        self.assertTrue(view.isVisibleTo(panel))
        self.assertEqual(view.geometry().topLeft(), slot.mapTo(panel, slot.rect().topLeft()))
        self.assertEqual(view.size(), slot.size())
        panel._toggle_markdown_mode()                          # edition : la vue s'efface avec sa place
        self.assertFalse(view.isVisibleTo(panel))
        panel._toggle_markdown_mode()
        self.assertTrue(view.isVisibleTo(panel))

    def test_switching_file_saves_pending_edit(self):
        panel = self.panel
        other = self.dir / "autre.txt"
        other.write_text("autre", encoding="utf-8")
        panel.show_path(self.note)
        panel._toggle_markdown_mode()
        self.edit("Avant de partir\n")
        panel.show_path(other)
        self.assertEqual(self.note.read_text(encoding="utf-8"), "# Titre\nAvant de partir\n")
        self.assertFalse(panel.markdown_bar.isVisible())
        panel.show_path(self.note)                             # le mode edition est garde d'une note a l'autre
        self.assertTrue(panel._md_editing)
        self.assertEqual(panel.markdown_editor.toPlainText(), "# Titre\nAvant de partir\n")


if __name__ == "__main__":
    unittest.main()

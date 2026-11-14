"""Orthographe du module Markdown / texte (fm_markdown/spell.py) : fichiers vérifiés, menu des corrections, bouton ajouté
aux dispositions enregistrées, et chaîne entière dans la page (bouton -> soulignement de Chromium -> clic droit ->
correction remplacée dans CodeMirror)."""
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
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --log-level=3")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEventLoop, QPoint, QTimer, Qt
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
APP = QApplication.instance() or QApplication([])

import fm_markdown.bars as md_bars
import fm_markdown.pane as md_pane
import fm_markdown.spell as spell
import settings_store


def settle(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


def _js(pane, code, timeout=3000):
    loop, out = QEventLoop(), {}

    def got(value):
        out["v"] = value
        loop.quit()
    pane.view.page().runJavaScript(code, got)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    return out.get("v")


def _until(test, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if test():
            return True
        settle(0.03)
    return False


class SpellUnitTest(unittest.TestCase):
    def test_checks_prose_not_code(self):
        self.assertTrue(spell.checks(Path("a.md")))
        self.assertTrue(spell.checks(Path("a.TXT")))
        self.assertFalse(spell.checks(Path("a.py")))
        self.assertFalse(spell.checks(None))

    def test_menu_entries(self):
        entries, choices = spell.menu_entries("mondde", ["monde", "mondde", "monade"])
        self.assertEqual(choices, ["monde", "monade"])
        self.assertEqual(entries[0], {"section": "« mondde »"})
        self.assertEqual([e["title"] for e in entries[1:3]], choices)
        self.assertEqual(entries[3], "-")
        self.assertEqual(entries[-1], {"title": "Ajouter au dictionnaire"})
        entries, choices = spell.menu_entries("xqzw", [])
        self.assertEqual(choices, [])
        self.assertIn({"section": "Aucune suggestion"}, entries)

    def test_add_word(self):
        self.assertEqual(spell.add_word(["a"], "Zorg"), ["a", "Zorg"])
        self.assertEqual(spell.add_word(["Zorg"], " Zorg "), ["Zorg"])
        self.assertEqual(spell.add_word("abc", "Zorg"), ["Zorg"])          # valeur illisible : repart de zéro

    def test_new_buttons_join_their_neighbours_bar(self):
        saved = {"bars": [{"id": "b1", "items": {md_bars.NOTE_LINE_NUMBERS: [0, 0, 1]}},
                          {"id": "b2", "items": {md_bars.TEXT_WRAP: [0, 0, 1]}}]}
        state = md_bars.place_new_items(saved)
        self.assertIn(md_bars.NOTE_SPELL, state["bars"][0]["items"])
        self.assertIn(md_bars.TEXT_SPELL, state["bars"][1]["items"])
        self.assertNotIn(md_bars.NOTE_SPELL, saved["bars"][0]["items"])     # l'état enregistré n'est pas touché
        # Déjà posés ou mémorisés ailleurs par l'utilisateur : rien ne bouge.
        state["memory"] = {}
        self.assertIs(md_bars.place_new_items(state), state)


@unittest.skipUnless(md_pane.markdown_preview.available(), "markdown-it-py absent")
class SpellPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = {**settings_store.DEFAULT_SETTINGS, "md_css_path": "", "md_spellcheck": False}
        md_pane.HOOKS["settings"] = lambda: cls.settings
        md_pane.HOOKS["save_state"] = lambda k, v: cls.settings.__setitem__(k, v)
        cls.pane = md_pane.MarkdownPane()
        cls.pane.resize(1000, 700)
        cls.pane.show()
        if not _until(lambda: _js(cls.pane, "!!(window.MD && MD.bridge && MD.editor && MD.toolbar)"), 20):
            raise unittest.SkipTest("QtWebEngine indisponible ici")

    @classmethod
    def tearDownClass(cls):
        cls.pane.close()
        cls.pane.deleteLater()
        settle(0.1)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(self.pane.buffers.clear)

    def open(self, path):
        self.assertTrue(self.pane.open(path))
        self.assertTrue(_until(lambda: _js(self.pane, f"!!(MD.state.current && MD.state.current.path === {str(path)!r})")))

    def test_button_underlines_and_right_click_corrects(self):
        code = self.dir / "script.py"
        code.write_text("x = 1\n", encoding="utf-8")
        note = self.dir / "note.md"
        note.write_text("Bonjour le mondde entier\n", encoding="utf-8")
        self.open(note)
        bars = self.pane.bars
        self.assertTrue(bars.buttons[md_bars.NOTE_SPELL].isVisible())
        bars.toggle(md_bars.NOTE_SPELL)
        self.addCleanup(lambda: self.settings.__setitem__("md_spellcheck", False))
        self.assertTrue(_until(lambda: self.settings["md_spellcheck"], 3))          # aucune sélection : tout
        self.assertFalse(self.pane.spell_zone)
        self.assertTrue(_until(lambda: _js(self.pane, "MD.editor.cm.getOption('spellcheck') === true"), 3))
        # Clic droit sur le mot fautif : le menu (simulé) choisit la 1re suggestion, la page remplace le mot.
        xy = _js(self.pane, "(() => { const c = MD.editor.cm.charCoords({line: 0, ch: 13}, 'window');"
                            " return c.left + ',' + (c.top + c.bottom) / 2; })()")
        x, y = (float(v) * self.pane.view.zoomFactor() for v in xy.split(","))
        seen = {}

        def fake_menu(_parent, entries, _pos):
            seen["entries"] = entries
            return 0
        settle(1.5)                                     # le correcteur de Chromium parcourt le texte
        from PySide6.QtTest import QTest
        with mock.patch.object(md_bars, "run_menu", fake_menu):
            target = self.pane.view.focusProxy() or self.pane.view
            QTest.mouseClick(target, Qt.RightButton, Qt.NoModifier, QPoint(int(x), int(y)))
            self.assertTrue(_until(lambda: "entries" in seen, 5), "aucun mot fautif sous le clic")
        self.assertEqual(seen["entries"][0], {"section": "« mondde »"})
        self.assertEqual(seen["entries"][1], {"title": "monde"})
        self.assertTrue(_until(lambda: _js(self.pane, "MD.editor.cm.getLine(0)") == "Bonjour le monde entier", 3))
        # Fichier de code : jamais vérifié, bouton de la barre « Texte » caché.
        self.open(code)
        self.assertFalse(_js(self.pane, "MD.editor.cm.getOption('spellcheck')"))
        self.assertFalse(bars.buttons[md_bars.TEXT_SPELL].isVisible())

    def _right_click(self, ch, answer):
        """Clic droit sur le caractère `ch` de la 1re ligne ; le menu (simulé) répond `answer` ; lignes du menu ou None."""
        xy = _js(self.pane, f"(() => {{ const c = MD.editor.cm.charCoords({{line: 0, ch: {ch}}}, 'window');"
                            " return c.left + ',' + (c.top + c.bottom) / 2; })()")
        x, y = (float(v) * self.pane.view.zoomFactor() for v in xy.split(","))
        seen = {}

        def fake_menu(_parent, entries, _pos):
            seen["entries"] = entries
            return answer(entries)
        from PySide6.QtTest import QTest
        with mock.patch.object(md_bars, "run_menu", fake_menu):
            QTest.mouseClick(self.pane.view.focusProxy() or self.pane.view, Qt.RightButton, Qt.NoModifier,
                             QPoint(int(x), int(y)))
            _until(lambda: "entries" in seen, 3)
        return seen.get("entries")

    def test_button_with_a_selection_checks_only_the_selection(self):
        note = self.dir / "zone.md"
        note.write_text("Bonjour mondde. Ici une erreurr.\n", encoding="utf-8")
        self.addCleanup(lambda: self.settings.update(md_spellcheck=False))
        self.settings.update(md_spellcheck=False)
        self.open(note)
        self.pane._push_style(self.settings, force=True)
        # Sélection qui coupe « erreurr » en son milieu : la zone s'étend au mot entier.
        _js(self.pane, "MD.editor.cm.focus(); MD.editor.cm.setSelection({line: 0, ch: 16}, {line: 0, ch: 27})")
        bars = self.pane.bars
        bars.toggle(md_bars.NOTE_SPELL)
        self.assertTrue(_until(lambda: self.pane.spell_zone, 3))
        self.assertFalse(self.settings["md_spellcheck"])                         # temporaire : rien d'enregistré
        self.assertTrue(bars.buttons[md_bars.NOTE_SPELL].active)
        settle(1.5)
        none = lambda e: -1   # noqa: E731
        self.assertIsNone(self._right_click(10, none), "faute hors de la sélection soulignée")
        entries = self._right_click(28, none)
        self.assertIsNotNone(entries, "faute de la sélection non soulignée")
        self.assertEqual(entries[0], {"section": "« erreurr »"})
        # Re-clic : tout s'éteint (zone retirée, correcteur coupé).
        bars.toggle(md_bars.NOTE_SPELL)
        self.assertFalse(self.pane.spell_zone)
        self.assertFalse(bars.buttons[md_bars.NOTE_SPELL].active)
        self.assertTrue(_until(lambda: _js(self.pane, "MD.editor.cm.getOption('spellcheck') === false"
                                                      " && MD.editor.cm.getAllMarks().length === 0"), 3))

    def test_add_to_dictionary_stops_the_underline(self):
        note = self.dir / "perso.md"
        note.write_text("Le projet Zorglubix avance\n", encoding="utf-8")
        self.addCleanup(lambda: self.settings.update(md_spellcheck=False, md_spell_words=[]))
        self.settings.update(md_spellcheck=True, md_spell_words=[])
        self.open(note)
        self.pane._push_style(self.settings, force=True)
        _js(self.pane, "MD.editor.cm.focus()")
        settle(1.5)
        clickable = lambda entries: [e for e in entries if isinstance(e, dict) and "title" in e]   # noqa: E731
        entries = self._right_click(13, lambda e: len(clickable(e)) - 1)          # dernière ligne : Ajouter
        self.assertIsNotNone(entries, "aucun mot fautif sous le clic")
        self.assertEqual(entries[0], {"section": "« Zorglubix »"})
        self.assertEqual(clickable(entries)[-1], {"title": "Ajouter au dictionnaire"})
        self.assertEqual(self.settings["md_spell_words"], ["Zorglubix"])
        self.assertTrue(_until(lambda: _js(self.pane, "[...document.querySelectorAll('.cm-md-known-word')]"
                                                      ".some(e => e.textContent === 'Zorglubix'"
                                                      " && e.getAttribute('spellcheck') === 'false')"), 3))
        settle(1.0)
        self.assertIsNone(self._right_click(13, lambda e: -1), "mot ajouté encore souligné")
        self.assertEqual(_js(self.pane, "MD.editor.cm.getLine(0)"), "Le projet Zorglubix avance")


if __name__ == "__main__":
    unittest.main()

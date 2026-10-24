"""Module Markdown : tableaux EDITABLES de l'edition visuelle (mdeditor/web/table.js), comme Obsidian.

Le modele (analyse d'une ligne, une cellule modifiee sans toucher aux autres, lignes / colonnes, alignements,
echappements) puis le widget dans la vraie page : cellules rendues, cellule active = sa source, clavier, annulation,
enregistrement fidele, reouverture, syntaxe incomplete, modification exterieure, lecture et inspecteur, vitesse.
Toujours sur des notes temporaires."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
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

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
APP = QApplication.instance() or QApplication([])

import markdown_preview
import mdeditor.pane as md_pane
import settings_store

TABLE = ('Avant\n\n'
         '| <span class="entete">entete 1</span> | <span class="entete">entete 2</span> | entete 3 |\n'
         '| :--- | :---: | ---: |\n'
         '| <span class="test">item 3</span>    | item 4 \\| échappé | [lien hypertexte](https://exemple.org) |\n'
         '\nAprès\n')

W = "[...MD.editor.lp.state.tableMarks.values()][0].widget"


def settle(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


def _js(pane, code, timeout=4000):
    loop, out = QEventLoop(), {}

    def got(value):
        out["v"] = value
        loop.quit()
    pane.view.page().runJavaScript(code, got)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    return out.get("v")


def _json(pane, code):
    return json.loads(_js(pane, f"JSON.stringify({code})"))


def _until(pane, code, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _js(pane, code):
            return True
        settle(0.03)
    return False


@unittest.skipUnless(markdown_preview.available(), "markdown-it-py absent")
class TablesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = {**settings_store.DEFAULT_SETTINGS, "md_css_path": ""}
        md_pane.HOOKS["settings"] = lambda: cls.settings
        md_pane.HOOKS["save_state"] = lambda k, v: cls.settings.__setitem__(k, v)
        cls.pane = md_pane.MarkdownPane()
        cls.pane.resize(1000, 700)
        cls.pane.show()
        if not _until(cls.pane, "!!(window.MD && MD.bridge && MD.editor && MD.tableModel)", 20):
            raise unittest.SkipTest("QtWebEngine indisponible ici")

    @classmethod
    def tearDownClass(cls):
        cls.pane.close()
        cls.pane.deleteLater()
        settle(0.1)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name, value in (("exec", 0), ("clickedButton", None)):
            patcher = mock.patch.object(md_pane.QMessageBox, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.pane.buffers.clear)

    def open(self, text, name="tableau.md"):
        path = self.dir / name
        path.write_text(text, encoding="utf-8", newline="")
        self.assertTrue(self.pane.open(path))
        self.assertTrue(_until(self.pane, f"!!(MD.state.current && MD.state.current.path === {str(path)!r})"))
        _js(self.pane, "MD.setMode('edit'); true")
        return path

    def widget_ready(self):
        self.assertTrue(_until(self.pane, f"MD.editor.lp.state.tableMarks.size > 0 && "
                                          f"!!{W}.el.querySelector('th span.entete')"), "tableau non rendu")

    def key(self, name, shift=False):
        codes = {"Tab": 9, "Enter": 13, "Esc": 27, "Up": 38, "Down": 40, "Left": 37, "Right": 39}
        return _js(self.pane, f"""(() => {{ const cm = {W}.nested;
            cm.triggerOnKeyDown({{type: 'keydown', keyCode: {codes[name]}, shiftKey: {str(shift).lower()},
              preventDefault() {{}}, stopPropagation() {{}} }}); return true; }})()""")

    def active(self):
        return _json(self.pane, f"(() => {{ const w = {W}; return w.active ? [w.active.r, w.active.c, "
                                f"w.nested.getValue(), w.nested.getCursor().ch] : null; }})()")

    # -- Modele ---------------------------------------------------------------------------------------------------
    def test_model_keeps_everything_but_the_edited_cell(self):
        out = _json(self.pane, r"""(() => {
            const T = MD.tableModel;
            const text = "| a | b \\| c | `x` |\n|:--|--:|---|\n| 1 |  | [l](u) |\n| 2 |";
            const m = T.parseTable(text);
            const edit = (fn, ...a) => T.applyEdits(text, fn(m, ...a));
            return {
              valid: m.valid, cols: m.cols, aligns: m.aligns,
              cells: m.rows.map((r, i) => Array.from({length: m.cols}, (x, j) => T.cellSource(m, i, j))),
              set: edit(T.setCell, 0, 1, "B|C"), empty: edit(T.setCell, 1, 1, "neuf"),
              short: edit(T.setCell, 2, 2, "z"), row: edit(T.insertRow, 2), last: edit(T.insertRow, 3),
              delRow: edit(T.deleteRow, 2), col: edit(T.insertColumn, 1), delCol: edit(T.deleteColumn, 0),
              align: edit(T.setAlign, 2, "center"), br: T.sanitize("a\nb"), esc: T.sanitize("x \\| y | z"),
              bad: T.parseTable("| a | b |\n| --- |\n| 1 | 2 |").valid
            };
        })()""")
        self.assertTrue(out["valid"])
        self.assertEqual(out["cols"], 3)
        self.assertEqual(out["aligns"], ["left", "right", ""])
        self.assertEqual(out["cells"], [["a", "b \\| c", "`x`"], ["1", "", "[l](u)"], ["2", "", ""]])
        self.assertEqual(out["set"].split("\n")[0], "| a | B\\|C | `x` |")
        self.assertEqual(out["set"].split("\n")[1:], ["|:--|--:|---|", "| 1 |  | [l](u) |", "| 2 |"])
        self.assertEqual(out["empty"].split("\n")[2], "| 1 | neuf | [l](u) |")
        self.assertEqual(out["short"].split("\n")[3], "| 2 |   | z |")
        self.assertEqual(out["row"].split("\n")[3], "|  |  |  |")
        self.assertEqual(out["last"].split("\n")[-1], "|  |  |  |")
        self.assertEqual(out["delRow"], "| a | b \\| c | `x` |\n|:--|--:|---|\n| 1 |  | [l](u) |")
        self.assertEqual(out["col"].split("\n")[:2], ["| a |   | b \\| c | `x` |", "|:--| --- |--:|---|"])
        self.assertEqual(out["delCol"].split("\n")[:2], ["| b \\| c | `x` |", "|--:|---|"])
        self.assertEqual(out["align"].split("\n")[1], "|:--|--:|:---:|")
        self.assertEqual(out["br"], "a<br>b")
        self.assertEqual(out["esc"], "x \\| y \\| z")
        self.assertFalse(out["bad"])

    # -- Widget ---------------------------------------------------------------------------------------------------
    def test_table_is_shown_as_cells_with_html_and_links_rendered(self):
        self.open(TABLE)
        self.widget_ready()
        info = _json(self.pane, f"""(() => {{ const w = {W}; const t = w.el.querySelector('table');
            return {{rows: t.rows.length, cols: t.rows[0].cells.length, raw: w.el.textContent.includes('---'),
                     span: t.rows[1].cells[0].querySelector('span.test') !== null,
                     link: (t.rows[1].cells[2].querySelector('a') || {{}}).textContent,
                     esc: t.rows[1].cells[1].textContent.trim(), align: t.rows[0].cells[2].style.textAlign,
                     rawLines: [...document.querySelectorAll('.CodeMirror-line')].some(l => l.textContent.includes('| :---'))}}; }})()""")
        self.assertEqual((info["rows"], info["cols"]), (2, 3))
        self.assertFalse(info["raw"])
        self.assertFalse(info["rawLines"])
        self.assertTrue(info["span"])
        self.assertEqual(info["link"], "lien hypertexte")
        self.assertEqual(info["esc"], "item 4 | échappé")
        self.assertEqual(info["align"], "right")

    def test_active_cell_shows_its_source_and_typing_writes_only_that_cell(self):
        path = self.open(TABLE)
        self.widget_ready()
        _js(self.pane, f"{W}.activate(0, 1, 'end'); true")
        self.assertEqual(self.active()[:3], [0, 1, '<span class="entete">entete 2</span>'])
        others = _json(self.pane, f"[...{W}.el.querySelectorAll('th')].map(c => !!c.querySelector('.CodeMirror'))")
        self.assertEqual(others, [False, True, False])
        _js(self.pane, f"(() => {{ const cm = {W}.nested; for (const ch of ' ok|') cm.replaceSelection(ch, null, '+input'); return true; }})()")
        self.assertEqual(self.active()[2], '<span class="entete">entete 2</span> ok\\|')
        self.assertTrue(self.pane.flush())
        lines = path.read_text(encoding="utf-8").split("\n")
        self.assertEqual(lines[2], '| <span class="entete">entete 1</span> | <span class="entete">entete 2</span> ok\\| | entete 3 |')
        self.assertEqual(lines[3:5], TABLE.split("\n")[3:5])        # le reste du tableau est intact
        # La cellule quittee est de nouveau rendue (HTML compris).
        _js(self.pane, f"{W}.activate(1, 0, 0); true")
        self.assertTrue(_until(self.pane, f"{W}.el.querySelector('table').rows[0].cells[1].textContent.trim() === 'entete 2 ok|'"))

    def test_keyboard_moves_between_cells_and_adds_rows(self):
        path = self.open(TABLE)
        self.widget_ready()
        _js(self.pane, f"{W}.activate(0, 0, 0); true")
        self.key("Tab")
        self.assertEqual(self.active()[:2], [0, 1])
        self.key("Tab", shift=True)
        self.assertEqual(self.active()[:2], [0, 0])
        self.key("Enter")
        self.assertEqual(self.active()[:2], [1, 0])
        _js(self.pane, f"{W}.activate(1, 2, 'end'); true")
        self.key("Tab")                                              # derniere cellule : nouvelle ligne
        self.assertEqual(self.active()[:2], [2, 0])
        _js(self.pane, f"{W}.nested.replaceSelection('neuf', null, '+input'); true")
        self.key("Right")                                            # fin de cellule -> cellule suivante
        self.assertEqual(self.active()[:2], [2, 1])
        self.key("Left")
        self.assertEqual(self.active()[:2], [2, 0])
        self.key("Up")
        self.assertEqual(self.active()[:2], [1, 0])
        self.assertTrue(self.pane.flush())
        self.assertEqual(path.read_text(encoding="utf-8").split("\n")[5], "| neuf |  |  |")
        self.key("Esc")                                              # sortie : le curseur de la note sous le tableau
        self.assertTrue(_until(self.pane, f"!{W}.active && MD.editor.cm.hasFocus() && MD.editor.cm.getCursor().line === 6"))

    def test_undo_and_redo_follow_the_note_history(self):
        path = self.open(TABLE)
        self.widget_ready()
        _js(self.pane, f"{W}.activate(1, 1, 'end'); {W}.nested.replaceSelection(' X', null, '+input'); true")
        self.assertIn("item 4 \\| échappé X", _js(self.pane, "MD.editor.getText()"))
        _js(self.pane, f"{W}.history('undo'); true")
        self.assertEqual(_js(self.pane, "MD.editor.getText()"), TABLE)
        self.assertEqual(self.active()[2], "item 4 \\| échappé")
        _js(self.pane, f"{W}.history('redo'); true")
        self.assertIn("échappé X", self.active()[2])
        self.assertTrue(self.pane.flush())
        self.assertIn("item 4 \\| échappé X |", path.read_text(encoding="utf-8"))

    def test_rows_and_columns_added_removed_saved_and_reopened(self):
        path = self.open(TABLE)
        self.widget_ready()
        _js(self.pane, f"{W}.addColumn(3); {W}.addRow(2); true")
        self.assertTrue(_until(self.pane, f"{W}.el.querySelector('table').rows.length === 3 && "
                                          f"{W}.el.querySelector('table').rows[0].cells.length === 4"))
        _js(self.pane, f"{W}.activate(2, 3, 0); {W}.nested.replaceSelection('D', null, '+input'); true")
        _js(self.pane, f"{W}.edit(MD.tableModel.deleteColumn, 0); true")
        self.assertTrue(self.pane.flush())
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        self.assertEqual(lines[2], '| <span class="entete">entete 2</span> | entete 3 |   |')
        self.assertEqual(lines[3], "| :---: | ---: | --- |")
        self.assertEqual(lines[5], "|  |  | D |")
        self.assertEqual(markdown_preview.render_fragment(text, path).count("<tr>"), 3)
        # Reouverture : le meme tableau, en cellules.
        self.pane.buffers.clear()
        _js(self.pane, "MD.editor.docs.clear(); true")
        self.assertTrue(self.pane.open(path))
        self.assertTrue(_until(self.pane, f"MD.editor.lp.state.tableMarks.size > 0 && {W}.el.querySelector('table').rows.length === 3"))

    def test_incomplete_table_stays_text_and_becomes_cells_once_valid(self):
        self.open("| a | b |\n| --- |\n| 1 | 2 |\n")
        settle(0.3)
        self.assertEqual(_js(self.pane, "MD.editor.lp.state.tableMarks.size"), 0)
        _js(self.pane, "MD.editor.cm.replaceRange(' --- |', {line: 1, ch: 7}); true")
        self.assertTrue(_until(self.pane, "MD.editor.lp.state.tableMarks.size === 1"))

    def test_external_change_updates_the_cells(self):
        path = self.open(TABLE)
        self.widget_ready()
        path.write_text(TABLE.replace("item 4", "modifié ailleurs"), encoding="utf-8", newline="")
        self.pane._on_file_changed(str(path))
        self.assertTrue(_until(self.pane, f"{W}.el.querySelector('table').rows[1].cells[1].textContent.includes('modifié ailleurs')"))

    def test_source_button_shows_the_markdown_until_the_cursor_leaves(self):
        self.open(TABLE)
        self.widget_ready()
        _js(self.pane, f"{W}.showSource(); true")
        self.assertTrue(_until(self.pane, "MD.editor.lp.state.tableMarks.size === 0 && "
                                          "[...document.querySelectorAll('.CodeMirror-line')].some(l => l.textContent.includes(':---:'))"))
        _js(self.pane, "MD.editor.cm.focus(); MD.editor.cm.setCursor(0, 0); true")
        self.assertTrue(_until(self.pane, "MD.editor.lp.state.tableMarks.size === 1"))

    def test_arrow_down_from_the_text_enters_the_first_cell(self):
        self.open(TABLE)
        self.widget_ready()
        _js(self.pane, """(() => { const cm = MD.editor.cm; cm.focus(); cm.setCursor(1, 0);
            cm.triggerOnKeyDown({type: 'keydown', keyCode: 40, preventDefault() {}, stopPropagation() {}}); return true; })()""")
        self.assertTrue(_until(self.pane, f"!!{W}.active"))
        self.assertEqual(self.active()[:2], [0, 0])

    def test_reading_mode_and_inspector_show_the_same_table(self):
        path = self.open(TABLE)
        _js(self.pane, "MD.setMode('reading'); true")
        self.assertTrue(_until(self.pane, "document.querySelectorAll('#md-read-body table tr').length === 2"))
        page = markdown_preview.render_page(path, TABLE, {**self.settings})
        self.assertIn('<span class="entete">entete 1</span>', page)
        self.assertIn('style="text-align:right"', page)
        _js(self.pane, "MD.setMode('edit'); true")

    def test_typing_in_a_cell_stays_fast(self):
        rows = "\n".join(f"| ligne {i} | valeur {i} | [[note {i}]] |" for i in range(60))
        self.open("# Titre\n\n" + "Texte. " * 200 + "\n\n| a | b | c |\n| --- | --- | --- |\n" + rows + "\n\nFin\n")
        self.assertTrue(_until(self.pane, f"MD.editor.lp.state.tableMarks.size > 0"))
        _js(self.pane, f"{W}.activate(30, 1, 'end'); true")
        timing = _json(self.pane, f"""(() => {{ const cm = {W}.nested; const out = [];
            for (let i = 0; i < 40; i++) {{ const t0 = performance.now(); cm.replaceSelection('x', null, '+input');
              out.push(performance.now() - t0); }}
            out.sort((a, b) => a - b); return {{median: out[20], max: out[39]}}; }})()""")
        self.assertLess(timing["median"], 8, timing)
        settle(0.2)
        self.assertIn("valeur 29" + "x" * 40, _js(self.pane, "MD.editor.getText()"))


if __name__ == "__main__":
    unittest.main()

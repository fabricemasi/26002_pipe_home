"""Module Markdown / code (paquet mdeditor/) : apparence tiree des reglages (source unique), onglet « Markdown » des
reglages (restauration des valeurs d'origine), page de l'editeur (note, code, lecture, enregistrement fidele, barre
d'outils), bouton « Éditeur » de la barre de la fenetre principale ; et le test des compteurs IMG / VID deplaces
(auparavant dans test_text_editor.py)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# QtWebEngine hors ecran : sans GPU (son contexte se perdait et la page cessait de repondre).
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --log-level=3")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEventLoop, QPoint, QRect, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
APP = QApplication.instance() or QApplication([])

import app_style
import fm_markdown as mdeditor
import fm_markdown.pane as md_pane
import fm_markdown.style as md_style
import pipeline_browser as pb
import settings_store
import settings_window_v2 as v2
from browser_core import ROLE_PATH


def settle(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


class StyleTest(unittest.TestCase):
    def test_custom_css_is_included_in_inspector_page(self):
        with tempfile.TemporaryDirectory() as folder:
            css = Path(folder) / "theme & test.css"
            css.write_text("", encoding="utf-8")
            page = md_pane.markdown_preview.render_page(Path(folder) / "note.md", "Texte",
                                                         {"md_css_path": str(css)})
            self.assertIn(f'@import url("{css.as_uri()}?v=', page)
            self.assertIn("layer(md-user)", page)
            self.assertIn("base.css", page)                     # l'habillage des reglages reste dessous

    def test_module_margin_is_equal_on_both_sides(self):
        widget = QWidget()
        from PySide6.QtWidgets import QVBoxLayout
        QVBoxLayout(widget)
        md_pane.MarkdownPane._apply_module_padding(widget, {"md_module_padding": 75})
        margins = widget.layout().contentsMargins()
        self.assertEqual((margins.left(), margins.top(), margins.right(), margins.bottom()), (75, 0, 75, 0))

    def test_every_markdown_key_has_a_default_and_a_variable(self):
        values = dict(settings_store.MARKDOWN_DEFAULTS)
        css = md_style.css_variables(values)
        self.assertTrue(css.startswith(md_style.VARS_SELECTOR + " {"))
        for key in values:
            self.assertIn(key, settings_store.DEFAULT_SETTINGS)
        names = md_style.variables(values)
        for name in ("--md-h1-color", "--md-codeblock-bg", "--md-table-grid", "--md-toolbar-bg", "--md-syntax-keyword",
                     "--md-quote-border-left", "--md-image-max-width", "--md-bullet-1-char"):
            self.assertIn(name, names)
        # Valeurs d'origine = CSS de l'utilisateur (fabrice.css) : texte #ffffffbf, H1 rgb(75, 175, 255)...
        self.assertEqual(names["--md-text-color"], "#ffffffbf")
        self.assertEqual(names["--md-h1-color"], "#4bafffff")
        self.assertEqual(names["--md-quote-border-left"], "3px solid #b44747ff")
        self.assertEqual(names["--md-quote-border-top"], "0 solid transparent")

    def test_colors_and_fonts(self):
        self.assertEqual(md_style.css_color("#80ff0000"), "#ff000080")            # #aarrggbb -> #rrggbbaa
        self.assertEqual(md_style.css_color("#123456"), "#123456")
        names = md_style.variables({"md_text_font_family": "Systeme", "md_h2_font_family": "",
                                    "md_code_inline_font_family": "Consolas", "md_letter_spacing": -5})
        self.assertIn("sans-serif", names["--md-text-font"])
        self.assertEqual(names["--md-h2-font"], names["--md-text-font"])            # vide = police du texte
        self.assertEqual(names["--md-code-inline-font"], '"Consolas", monospace')
        self.assertEqual(names["--md-letter-spacing"], "-0.5px")

    def test_every_catalog_key_of_the_tab_is_declared(self):
        groups = v2.node_groups(v2.Node("x", children=v2.MARKDOWN_TREE))
        self.assertGreater(len(groups), 15)
        for group in groups:
            for spec in v2.CATALOG[group]:
                for key in (spec.key, *spec.extra_keys):
                    if spec.kind == "font_gabarit" and key.endswith("_font_family") and "family" not in spec.params["only"]:
                        continue
                    self.assertIn(key, settings_store.DEFAULT_SETTINGS, f"{group} : {key}")
                if spec.kind in ("padding", "corners", "sides_thick"):
                    self.assertIn(f"{spec.key}_linked", settings_store.DEFAULT_SETTINGS, spec.key)

    def test_restoring_defaults_covers_the_whole_part(self):
        node = next(n for n in v2.MARKDOWN_TREE if n.title == "Titres H1-H6")
        defaults = v2.group_default_values(v2.node_groups(node))
        self.assertEqual(defaults["md_h3_font_color"], "#ffcba54e")
        self.assertEqual(defaults["md_h6_space_after"], 8)
        self.assertNotIn("md_text_font_color", defaults)


class MarkdownTabTest(unittest.TestCase):
    """L'onglet « Markdown » de la fenetre de reglages : construit, lu, restaure."""

    def test_heading_tables_share_dimensions_and_restore_them(self):
        import copy
        settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
        settings["table_dims"] = {}
        with mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(settings)), \
                mock.patch.object(v2, "AUTOSAVE", False):
            window = v2.SettingsWindowV2(module="markdown")
        self.addCleanup(window.deleteLater)
        window._show_page(0)
        heads = next(n for n in window.findChildren(v2._LazyNode) if n.node.title == "Titres H1-H6")
        heads._build()
        children = list(heads._child_nodes)
        for child in children[:5]:
            child._build()
        frames = [c._group_widget for c in children[:5]]
        self.assertTrue(all(f._link_group == "markdown:headings" for f in frames))
        for frame in frames:
            frame._dims_applied = True
        source = frames[0]
        widths = source._v2_head.columnWidths()
        widths[0] += 45
        source._v2_head.setColumnWidths(widths)
        source.dimsChanged.emit()
        expected = source.collectDims()["cols"]
        self.assertTrue(all(f.collectDims()["cols"] == expected for f in frames))
        children[5]._build()
        last = children[5]._group_widget
        self.assertEqual(last.dimsKey(), source.dimsKey())
        last.applyDims(v2._TABLE_DIMS[last.dimsKey()])
        self.assertEqual(last.collectDims()["cols"], expected)

    def test_tab_values_and_reset(self):
        import copy
        settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
        settings["md_h2_font_color"] = "#ff00ff00"
        settings["md_h2_weight"] = 800
        with mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(settings)), \
                mock.patch.object(v2, "AUTOSAVE", False):
            window = v2.SettingsWindowV2(module="markdown")
        self.addCleanup(window.deleteLater)
        window._show_page(0)
        titles = [n for n in window.findChildren(v2._LazyNode) if n._values.name == v2.MARKDOWN_TAB]
        self.assertEqual([n.node.title for n in titles if n.level == 1], [n.title for n in v2.MARKDOWN_TREE])
        heads = next(n for n in titles if n.node.title == "Titres H1-H6")
        window.reset_to_defaults(heads)
        settle(0.1)
        values = window.wired_values()
        self.assertEqual(values["md_h2_font_color"], "#ff4bafff")
        self.assertEqual(values["md_h2_weight"], 300)


def _js(pane, code, timeout=3000):
    loop, out = QEventLoop(), {}

    def got(value):
        out["v"] = value
        loop.quit()
    pane.view.page().runJavaScript(code, got)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    return out.get("v")


def _until(pane, code, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _js(pane, code):
            return True
        settle(0.03)
    return False


@unittest.skipUnless(md_pane.markdown_preview.available(), "markdown-it-py absent")
class PaneTest(unittest.TestCase):
    """La page de l'editeur (une seule instance, chargee une fois)."""

    @classmethod
    def setUpClass(cls):
        # Sans la feuille du coffre de l'utilisateur (valeur d'origine de md_css_path) : jamais lue ici.
        cls.settings = {**settings_store.DEFAULT_SETTINGS, "md_css_path": ""}
        md_pane.HOOKS["settings"] = lambda: cls.settings
        md_pane.HOOKS["save_state"] = lambda k, v: cls.settings.__setitem__(k, v)
        cls.pane = md_pane.MarkdownPane()
        cls.pane.resize(1000, 700)
        cls.pane.show()
        if not _until(cls.pane, "!!(window.MD && MD.bridge && MD.editor && MD.toolbar)", 20):
            raise unittest.SkipTest("QtWebEngine indisponible ici")

    @classmethod
    def tearDownClass(cls):
        cls.pane.close()
        cls.pane.deleteLater()
        settle(0.1)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        # Jamais de vraie fenetre de question (elle bloquerait la suite) ; tampons oublies apres chaque test.
        for name, value in (("exec", 0), ("clickedButton", None)):
            patcher = mock.patch.object(md_pane.QMessageBox, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.pane.buffers.clear)

    def open(self, path):
        self.assertTrue(self.pane.open(path))
        self.assertTrue(_until(self.pane, f"!!(MD.state.current && MD.state.current.path === {str(path)!r})"))

    def test_page_frame_and_scrollbar_settings_apply_live(self):
        note = self.dir / "cadre.md"
        note.write_text("Texte\n" * 100, encoding="utf-8")
        self.open(note)
        values = {**self.settings, "md_page_margin": {"top": 7, "right": 11, "bottom": 13, "left": 17},
                  "md_page_padding": {"top": 19, "right": 23, "bottom": 29, "left": 23}, "md_scroll_width": 14, "md_scroll_offset": 6, "md_scroll_radius": 4}
        self.addCleanup(self.pane.apply_settings, self.settings, set(values))
        self.pane.apply_settings(values, {"md_page_margin", "md_page_padding", "md_scroll_width", "md_scroll_offset", "md_scroll_radius"})
        self.assertTrue(_until(self.pane, "getComputedStyle(document.querySelector('.md-view')).left === '17px'"))
        result = json.loads(_js(self.pane, """JSON.stringify((() => {
            let v = getComputedStyle(document.querySelector('.md-view'));
            let bar = getComputedStyle(document.querySelector('.md-read'), '::-webkit-scrollbar');
            let thumb = getComputedStyle(document.querySelector('.md-read'), '::-webkit-scrollbar-thumb');
            return [v.left, v.right, v.bottom, bar.width, thumb.borderRadius, getComputedStyle(document.querySelector('.md-sizer')).paddingTop, getComputedStyle(document.querySelector('.md-sizer')).paddingBottom];
        })())"""))
        self.assertEqual(result, ["17px", "11px", "13px", "20px", "4px", "19px", "29px"])

    def test_bullet_colors_override_obsidian_important_rules(self):
        note = self.dir / "puces.md"
        note.write_text("- premier\n  - deuxieme\n    - troisieme\n\nfin\n", encoding="utf-8")
        css = self.dir / "obsidian.css"
        css.write_text(".md-bullet::before, .md-rendered li::before { color: red !important; "
                       "-webkit-text-fill-color: red !important; }", encoding="utf-8")
        values = {**self.settings, "md_css_path": str(css), "md_bullet_1_font_color": "#ff123456",
                  "md_bullet_2_font_color": "#ff56789a", "md_bullet_3_font_color": "#ffabcdef"}
        self.addCleanup(self.pane.apply_settings, self.settings, set(values))
        self.open(note)
        self.pane.apply_settings(values, {"md_css_path", "md_bullet_1_font_color", "md_bullet_2_font_color", "md_bullet_3_font_color"})
        _js(self.pane, "MD.setMode('edit'); MD.editor.cm.setCursor(4, 0); true")
        self.assertTrue(_until(self.pane, "document.querySelectorAll('.md-bullet').length >= 3"))
        colors = json.loads(_js(self.pane, """JSON.stringify([1,2,3].map(n => {
            let e = document.querySelector('.md-bullet.level-' + n);
            return getComputedStyle(e, '::before').webkitTextFillColor;
        }))"""))
        self.assertEqual(colors, ["rgb(18, 52, 86)", "rgb(86, 120, 154)", "rgb(171, 205, 239)"])

    def test_note_edit_save_keeps_encoding_and_line_endings(self):
        note = self.dir / "note.md"
        note.write_bytes(b"\xef\xbb\xbf# Titre\r\n\r\nTexte\r\n")
        self.open(note)
        self.assertEqual(_js(self.pane, "MD.editor.kind"), "markdown")
        self.assertTrue(_js(self.pane, "document.querySelector('pre.md-h1') !== null"))      # mis en forme
        _js(self.pane, "MD.editor.cm.setCursor({line: 2, ch: 5}); MD.editor.cm.replaceSelection(' ajouté'); true")
        self.assertTrue(self.pane.flush())
        self.assertEqual(note.read_bytes(), b"\xef\xbb\xbf# Titre\r\n\r\nTexte ajout\xc3\xa9\r\n")

    def test_editing_text_has_equal_horizontal_margins(self):
        note = self.dir / "marges.md"
        note.write_text("Texte suffisamment long pour revenir à la ligne. " * 50, encoding="utf-8")
        self.open(note)
        _js(self.pane, "MD.setMode('edit'); true")
        margins = json.loads(_js(self.pane, """JSON.stringify((() => {
            const view = document.querySelector('.md-edit').getBoundingClientRect();
            const text = document.querySelector('.md-edit .CodeMirror-lines').getBoundingClientRect();
            return [text.left - view.left, view.right - text.right];
        })())"""))
        self.assertAlmostEqual(margins[0], margins[1], delta=1)

    def test_inline_code_at_start_does_not_style_the_whole_line_as_a_code_block(self):
        note = self.dir / "code_en_ligne.md"
        note.write_text("`CLAUDE.md` est créé : texte normal.\n\n```python\nprint(1)\n```\n", encoding="utf-8")
        self.open(note)
        _js(self.pane, "MD.setMode('edit'); true")
        result = json.loads(_js(self.pane, """JSON.stringify((() => {
            const lines = [...document.querySelectorAll('.CodeMirror-line')];
            const inline = lines.find(e => e.textContent.includes('est créé'));
            const block = lines.find(e => e.textContent.includes('print(1)'));
            return {line: inline.className, code: inline.querySelector('.cm-inline-code').textContent,
                    block: block.className};
        })())"""))
        self.assertNotIn("md-codeblock", result["line"])
        self.assertIn(result["code"], ("`", "CLAUDE.md"))
        self.assertIn("md-codeblock", result["block"])

    def test_code_fences_are_hidden_except_on_the_active_line(self):
        note = self.dir / "blocs.md"
        note.write_text("Avant\n```python\nprint(1)\n```\nAprès\n", encoding="utf-8")
        self.open(note)
        _js(self.pane, "MD.setMode('edit'); MD.editor.cm.focus(); MD.editor.cm.setCursor(0, 0); true")
        hidden = "MD.editor.cm.findMarksAt({line: %d, ch: 1}).some(m => m.collapsed)"
        self.assertTrue(_until(self.pane, hidden % 1))
        self.assertTrue(_until(self.pane, hidden % 3))
        _js(self.pane, "MD.editor.cm.setCursor(1, 1); true")
        self.assertTrue(_until(self.pane, "!(" + (hidden % 1) + ")"))
        self.assertTrue(_js(self.pane, hidden % 3))
        self.assertEqual(_js(self.pane, "MD.editor.getText()"), note.read_text(encoding="utf-8"))

    def test_custom_css_can_be_applied_and_removed_without_reloading(self):
        note = self.dir / "note.md"
        note.write_text("Un texte\n", encoding="utf-8")
        css = self.dir / "personnalise.css"
        css.write_text(".CodeMirror { background-color: rgb(12, 34, 56) !important; }", encoding="utf-8")
        self.open(note)
        _js(self.pane, "MD.setMode('edit'); true")
        original = _js(self.pane, "getComputedStyle(document.querySelector('.CodeMirror')).backgroundColor")
        self.pane.apply_settings({**self.settings, "md_css_path": str(css)}, {"md_css_path"})
        self.assertTrue(_until(self.pane, "getComputedStyle(document.querySelector('.CodeMirror')).backgroundColor === 'rgb(12, 34, 56)'"))
        self.assertTrue(_js(self.pane, "document.querySelector('#md-user-css').textContent.includes('personnalise.css')"))
        self.pane.apply_settings({**self.settings, "md_css_path": ""}, {"md_css_path"})
        self.assertTrue(_until(self.pane, f"getComputedStyle(document.querySelector('.CodeMirror')).backgroundColor === {original!r}"))
        self.assertEqual(_js(self.pane, "MD.editor.getText()"), "Un texte\n")

    def test_toolbar_acts_on_the_selection_with_undo(self):
        note = self.dir / "outils.md"
        note.write_text("mot\n", encoding="utf-8")
        self.open(note)
        _js(self.pane, "MD.setMode('edit'); MD.editor.cm.setSelection({line:0,ch:0},{line:0,ch:3}); "
                       "MD.toolbar.run('editing-toolbar:toggle-bold'); true")
        self.assertEqual(_js(self.pane, "MD.editor.getText()"), "**mot**\n")
        _js(self.pane, "MD.toolbar.run('editing-toolbar:header2-text'); true")
        self.assertEqual(_js(self.pane, "MD.editor.getText()"), "## **mot**\n")
        _js(self.pane, "MD.editor.cm.undo(); MD.editor.cm.undo(); true")
        self.assertEqual(_js(self.pane, "MD.editor.getText()"), "mot\n")
        self.assertGreater(_js(self.pane, "document.querySelectorAll('#md-toolbar .md-tool').length"), 10)

    def test_reading_mode_renders_images_and_highlighted_code(self):
        (self.dir / "img").mkdir()
        from PySide6.QtGui import QColor, QImage
        image = QImage(40, 20, QImage.Format_RGB32)
        image.fill(QColor("#336699"))
        image.save(str(self.dir / "img" / "a.png"))
        note = self.dir / "lecture.md"
        note.write_text("# T\n\n![[a.png|30]] ![b](img/a.png)\n\n```python\ndef f():\n    pass\n```\n", encoding="utf-8")
        self.open(note)
        _js(self.pane, "MD.setMode('reading'); true")
        self.assertTrue(_until(self.pane, "document.querySelectorAll('#md-read-body img').length === 2"))
        self.assertTrue(_until(self.pane, "document.querySelector('#md-read-body pre code .cm-keyword') !== null"))
        self.assertTrue(_until(self.pane, "[...document.querySelectorAll('#md-read-body img')]"
                                          ".every(i => i.complete && i.naturalWidth === 40)"))
        self.assertEqual(_js(self.pane, "document.querySelector('#md-read-body img').getAttribute('width')"), "30")
        _js(self.pane, "MD.setMode('edit'); true")
        self.assertEqual(self.settings.get("md_last_mode"), "edit")

    def test_code_file_is_source_code_with_its_language(self):
        code = self.dir / "outil.py"
        code.write_text("def f(x):\n\treturn x  # note\n", encoding="utf-8")
        self.open(code)
        self.assertEqual(_js(self.pane, "MD.editor.kind"), "code")
        self.assertEqual(_js(self.pane, "MD.editor.cm.getOption('mode')"), "text/x-python")
        self.assertTrue(_js(self.pane, "document.getElementById('md-edit').classList.contains('is-code')"))
        self.assertFalse(_js(self.pane, "document.getElementById('md-toolbar').classList.contains('is-shown')"))
        self.assertTrue(_until(self.pane, "document.querySelector('.md-edit .cm-keyword') !== null"))
        self.assertEqual(_js(self.pane, "MD.editor.getText()"), "def f(x):\n\treturn x  # note\n")   # tabulation gardee
        self.assertEqual(_js(self.pane, "MD.modeForExtension('vex')"), "text/x-csrc")
        self.assertEqual(_js(self.pane, "MD.modeForExtension('inconnu')"), "text/plain")

    def test_settings_apply_without_reload(self):
        note = self.dir / "style.md"
        note.write_text("# T\n", encoding="utf-8")
        self.open(note)
        _js(self.pane, "window.__marker = 42; true")
        self.pane.apply_settings({**self.settings, "md_h1_font_color": "#ff010203"}, {"md_h1_font_color"})
        self.assertTrue(_until(self.pane, "getComputedStyle(document.documentElement)"
                                          ".getPropertyValue('--md-h1-color').trim() === '#010203ff'"))
        self.assertEqual(_js(self.pane, "window.__marker"), 42)          # page jamais rechargee

    def test_binary_files_are_refused(self):
        blob = self.dir / "image.txt"
        blob.write_bytes(b"\x00\x01\x02binaire")
        self.assertIsNotNone(self.pane.can_open(blob))
        self.assertFalse(self.pane.open(blob))

    def test_file_changed_elsewhere_is_never_overwritten_silently(self):
        note = self.dir / "conflit.md"
        note.write_text("version A\n", encoding="utf-8")
        self.open(note)
        _js(self.pane, "MD.editor.cm.setValue('ma version\\n'); true")
        time.sleep(0.05)
        note.write_text("version B\n", encoding="utf-8")
        os.utime(note, None)
        self.assertFalse(self.pane.flush())                             # question : Annuler
        self.assertEqual(note.read_text(encoding="utf-8"), "version B\n")


class EditorButtonTest(unittest.TestCase):
    """Bouton « Éditeur » de la barre : grise tant que la selection n'est pas un fichier texte / code."""

    def setUp(self):
        app_style.apply_style(APP)
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "set").mkdir()
        (self.root / "set" / "notes.txt").write_text("bonjour\n", encoding="utf-8")
        (self.root / "set" / "image.bin").write_bytes(b"\0")
        self.win = pb.PipelineBrowser(self.root)
        self.win._idle_preview_scheduler.timer.stop()
        self.win.resize(1300, 800)
        self.win.show()
        self.addCleanup(self.win.deleteLater)
        settle()

    def _select(self, name):
        self.win._navigate_to(self.root / "set" / name)
        settle(0.3)
        for column in reversed(self.win.columns):
            for row in range(column.list.count()):
                item = column.list.item(row)
                if Path(str(item.data(ROLE_PATH) or "")).name == name:
                    if column.list.currentItem() is not item:
                        column.list.setCurrentItem(item)
                        settle(0.3)
                    return
        self.fail(f"{name} : {[c.directory for c in self.win.columns]}")

    def test_button_is_greyed_until_a_text_file_is_selected_then_opens_the_editor(self):
        win = self.win
        self.assertTrue(mdeditor.is_text_file(Path("a/script.VEX")))
        self.assertFalse(mdeditor.is_text_file(Path("a/photo.jpg")))
        self.assertTrue(win.titlebar.isAncestorOf(win.btn_text_editor))
        self.assertFalse(win.btn_text_editor.isEnabled())
        self._select("image.bin")
        self.assertFalse(win.btn_text_editor.isEnabled())
        self._select("notes.txt")
        self.assertTrue(win.btn_text_editor.isEnabled())
        win.btn_text_editor.click()
        settle(0.4)
        pane = md_pane.instance(create=False)
        self.assertTrue(win._md_open)
        self.assertEqual(pane.path, self.root / "set" / "notes.txt")
        self.assertEqual(pane.geometry(), win.scroll.viewport().rect())   # recouvre les colonnes
        group = win.titlebar.editor_group()
        self.assertTrue(group.isVisible())
        self.assertTrue(all(group.isAncestorOf(b) for b in win._editor_buttons))
        with mock.patch.object(md_pane.MarkdownPane, "confirm_leave", return_value=False):
            self.assertFalse(win._close_md_editor())                    # modifications non enregistrees : on reste
        self.assertTrue(win._md_open)
        self.assertTrue(win._close_md_editor())
        settle(0.4)
        self.assertFalse(win._md_open)
        self.assertFalse(group.isVisible())

    def test_double_click_opens_notes_in_the_editor_unless_obsidian_is_chosen(self):
        note = self.root / "set" / "n.md"
        note.write_text("x", encoding="utf-8")
        self.assertTrue(self.win._md_opens_on_double_click(note))
        self.assertFalse(self.win._md_opens_on_double_click(self.root / "set" / "notes.txt"))   # bouton seulement
        with mock.patch.object(pb.ui_state, "APPLIED_SETTINGS", {"md_open_md": "obsidian"}):
            self.assertFalse(self.win._md_opens_on_double_click(note))


class PaintedTargetRestoreTest(unittest.TestCase):
    """Bug signale : les compteurs IMG / VID deplaces au mode edition glissaient vers la gauche apres un
    redemarrage — leur decalage enregistre etait rajoute a CHAQUE tour de `_restore_visible_positions`."""

    def test_saved_offset_is_applied_once_from_the_painted_place(self):
        from PySide6.QtWidgets import QListWidget
        from settings_widgets import widget_path
        window = QWidget()
        window.setWindowTitle("Fenetre des compteurs")
        window.setGeometry(800, 50, 500, 200)
        view = QListWidget(window)
        view.setGeometry(0, 0, 500, 200)
        window.show()
        settle(0.05)
        self.addCleanup(window.deleteLater)
        painted = QRect(400, 10, 40, 12)
        view._edit_geometry = {"F:/photos": {"row": QRect(0, 0, 500, 40), "media-photo": QRect(painted)}}
        with mock.patch("main_window.interface_move.load_settings", return_value={"interface_move_positions": {}}):
            mode = pb._InterfaceMoveMode(QWidget())
        mode._edit_sync.stop()
        self.addCleanup(APP.removeEventFilter, mode)
        self.addCleanup(APP.aboutToQuit.disconnect, mode._flush_positions)
        key = f"{mode._window_key(window)}|{widget_path(view, window)}|F:/photos|media-photo"
        mode.position_overrides = {key: {"offset": [-6, 11]}}
        for _tick in range(6):                                            # rejoue toutes les 150 ms
            mode._restore_visible_positions()
        target = mode.painted_targets[(view, "F:/photos", "media-photo")]
        self.assertEqual(target.pos(), painted.topLeft() + QPoint(-6, 11))


def tearDownModule():
    """Pages web detruites AVANT l'application (sinon QtWebEngine plantait a la sortie du processus)."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWebEngineWidgets import QWebEngineView
    pane = md_pane.instance(create=False)
    if pane is not None:
        pane.setParent(None)
        pane.deleteLater()
    for view in APP.allWidgets():
        if isinstance(view, QWebEngineView):
            view.deleteLater()
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        settle(0.1)


if __name__ == "__main__":
    unittest.main()

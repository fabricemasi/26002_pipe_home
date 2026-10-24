"""Module Markdown : compatibilite des feuilles CSS avec Obsidian (Reglages > Markdown > CSS).

- une feuille ecrite pour Obsidian habille la lecture, l'edition et l'apercu de l'inspecteur (classes et variables
  d'Obsidian posees par la page) ;
- la feuille exportee pour Obsidian se recharge dans le module avec le meme rendu ;
- une feuille hostile ne casse ni la saisie, ni le defilement, ni la selection, ni les barres ;
- fichier absent / illisible : style integre ; aucun fichier de l'utilisateur n'est modifie ;
- reglages toujours appliques en direct, rien de recharge a la frappe.
Toutes les feuilles et notes sont des copies temporaires."""
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

from PySide6.QtCore import QEventLoop, QTimer, QUrl, Qt
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
APP = QApplication.instance() or QApplication([])

import markdown_preview
import mdeditor.pane as md_pane
import mdeditor.style as md_style
import settings_store
import settings_window_v2 as v2

# Reglages d'origine SANS la feuille du coffre de l'utilisateur (valeur d'origine de md_css_path) : jamais lue ici.
BASE = {**settings_store.DEFAULT_SETTINGS, "md_css_path": ""}

# Feuille « a la Obsidian » : selecteurs et variables d'Obsidian uniquement (comme fabrice.css).
OBSIDIAN_CSS = """
:root { --h1-color: rgb(1, 2, 3); --background-primary: rgb(20, 21, 22); }
body { --text-highlight-bg: rgb(30, 31, 32); }
.markdown-preview-view h2, .cm-line span.cm-header-2 { color: rgb(4, 5, 6); }
.markdown-reading-view strong, .cm-s-obsidian span.cm-strong { color: rgb(13, 14, 15); }
.markdown-preview-view p code,
.markdown-source-view.mod-cm6 .cm-inline-code:not(.cm-formatting) { background-color: rgb(7, 8, 9); }
.markdown-preview-view pre, .markdown-source-view.mod-cm6 .HyperMD-codeblock { background-color: rgb(10, 11, 12); }
.markdown-preview-view pre code .token.comment, .HyperMD-codeblock span.cm-comment { color: rgb(40, 41, 42); }
.markdown-preview-view blockquote, .markdown-source-view.mod-cm6 .cm-line.HyperMD-quote { background-color: rgb(50, 51, 52); }
.callout .callout-title { color: rgb(16, 17, 18); }
.markdown-preview-view table td, .cm-s-obsidian table td { color: rgb(60, 61, 62); }
.markdown-reading-view a, .markdown-source-view.mod-cm6 .cm-line:not(.cm-active) .cm-hmd-internal-link { color: rgb(70, 71, 72); }
.markdown-source-view.mod-cm6 .cm-list-1 .list-bullet::before { content: "@"; }
.inline-title { color: rgb(80, 81, 82); }
img { border-radius: 7px; }
"""

# Feuille hostile : tout ce qui casserait CodeMirror, la page ou les barres s'il passait.
HOSTILE_CSS = """
html, body { overflow: auto !important; height: auto !important; margin: 50px !important; }
.md-view, .markdown-source-view { display: none !important; position: static !important; }
.CodeMirror, .cm-editor { height: 20px !important; overflow: visible !important; position: static !important; }
.CodeMirror-scroll { overflow: hidden !important; height: 10px !important; }
.cm-line, .CodeMirror-line { white-space: normal !important; margin: 30px !important; display: flex !important;
  position: absolute !important; }
.cm-content { padding: 80px !important; position: absolute !important; }
.md-toolbar { display: none !important; position: static !important; }
.md-toolbar .md-tool { width: 1px !important; background: red !important; }
div.CodeMirror-cursors { position: absolute !important; z-index: -1 !important; }
* { box-sizing: border-box; }
"""

NOTE = ("# Titre un\n\n## Titre deux\n\nUn **gras** et du `code` et [[autre note]].\n\n"
        "- puce\n\n> citation\n\n> [!note] Mon callout\n> contenu\n\n```python\n# commentaire\nx = 1\n```\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n")
NOTE_LINES = {"h1": 0, "h2": 2, "bold": 4, "list": 6, "quote": 8, "fence": 13}


def settle(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


def _js(view, code, timeout=3000):
    loop, out = QEventLoop(), {}

    def got(value):
        out["v"] = value
        loop.quit()
    view.page().runJavaScript(code, got)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    return out.get("v")


def _until(view, code, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _js(view, code):
            return True
        settle(0.03)
    return False


def _style(selector, prop):
    return (f"(() => {{ const el = document.querySelector({selector!r}); "
            f"return el ? getComputedStyle(el).getPropertyValue({prop!r}).trim() : null; }})()")


class CssFilesTest(unittest.TestCase):
    """Choix de la feuille, variables reliees a Obsidian, export (sans page web)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_missing_or_unusable_css_falls_back_to_the_builtin_style(self):
        for raw in ("", str(self.dir / "absente.css"), str(self.dir), "relatif/feuille.css"):
            path, status = md_style.user_css({"md_css_path": raw})
            self.assertIsNone(path, raw)
            self.assertIn("tyle intégré", status)
            self.assertEqual(md_style.user_css_url({"md_css_path": raw}), "")
        css = self.dir / "ok.css"
        css.write_text("p { color: red; }", encoding="utf-8")
        path, status = md_style.user_css({"md_css_path": f'"{css}"'})              # guillemets d'un copier-coller
        self.assertEqual(path, css)
        self.assertIn("ok.css", status)
        self.assertTrue(md_style.user_css_url({"md_css_path": str(css)}).startswith(css.as_uri() + "?v="))

    def test_default_sheet_is_the_vault_snippet_and_is_only_read(self):
        # Valeur d'origine = l'extrait CSS du coffre de l'utilisateur ; ailleurs (fichier absent) : style integre.
        self.assertTrue(settings_store.DEFAULT_SETTINGS["md_css_path"].endswith("/.obsidian/snippets/fabrice.css".replace("/", os.sep)))
        with mock.patch.dict(settings_store.MARKDOWN_DEFAULTS, {"md_css_path": str(self.dir / "fabrice.css")}):
            self.assertIsNone(md_style.user_css({"md_css_path": settings_store.MARKDOWN_DEFAULTS["md_css_path"]})[0])

    def test_obsidian_variables_come_first_then_the_settings(self):
        values = dict(settings_store.MARKDOWN_DEFAULTS)
        linked = md_style.linked_variables(values)
        self.assertEqual(linked["--md-h1-color"], "var(--h1-color, #4bafffff)")
        self.assertEqual(linked["--md-text-font"], 'var(--font-text, var(--font-text-theme, "Inter", sans-serif))')
        self.assertEqual(linked["--md-codeblock-bg"], f"var(--code-background, {md_style.variables(values)['--md-codeblock-bg']})")
        self.assertTrue(linked["--md-quote-border-left"].startswith("var(--blockquote-border-thickness, 3px) solid"))
        values["md_h2_font_family"] = ""                                          # vide = police du texte
        self.assertEqual(md_style.linked_variables(values)["--md-h2-font"], "var(--h2-font, var(--md-text-font))")
        self.assertIn(md_style.VARS_SELECTOR, md_style.css_variables(values))

    def test_export_writes_obsidian_variables_and_never_replaces_a_user_file(self):
        values = {**settings_store.MARKDOWN_DEFAULTS, "md_h1_font_color": "#ff102030", "md_bullet_1_char": "▸"}
        target = self.dir / "pipeline-browser.css"
        md_style.export_obsidian_css(values, target)
        text = target.read_text(encoding="utf-8")
        self.assertIn(md_style.EXPORT_MARKER, text)
        self.assertIn("body.theme-dark, body.theme-light {", text)
        self.assertIn("--h1-color: #102030ff;", text)
        self.assertIn("--background-primary: #1b1c1d;", text)
        self.assertIn(".markdown-source-view.mod-cm6 .cm-line.HyperMD-header-1 {", text)
        self.assertIn('content: "▸";', text)
        self.assertNotIn("--md-", text)                                           # rien de propre au module
        self.assertNotIn("--h2-font", text) if not values.get("md_h2_font_family") else None
        self.assertEqual(text.count("{"), text.count("}"))
        # Remplacer sa propre feuille : oui ; une feuille de l'utilisateur : jamais (contenu intact).
        md_style.export_obsidian_css({**values, "md_h1_font_color": "#ff000000"}, target)
        self.assertIn("--h1-color: #000000ff;", target.read_text(encoding="utf-8"))
        mine = self.dir / "fabrice.css"
        mine.write_text("/* la feuille de l'utilisateur */\n.x { color: red; }\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            md_style.export_obsidian_css(values, mine)
        self.assertEqual(mine.read_text(encoding="utf-8"), "/* la feuille de l'utilisateur */\n.x { color: red; }\n")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["fabrice.css", "pipeline-browser.css"])

    def test_inspector_page_uses_the_same_layers_and_obsidian_classes(self):
        css = self.dir / "obsidian.css"
        css.write_text(OBSIDIAN_CSS, encoding="utf-8")
        page = markdown_preview.render_page(self.dir / "note.md", NOTE, {"md_css_path": str(css)})
        self.assertIn(md_style.LAYER_ORDER, page)
        self.assertIn("layer(md-theme)", page)
        self.assertIn(f'@import url("{css.as_uri()}?v=', page)
        for cls in ("markdown-reading-view", "markdown-preview-view", "markdown-rendered", "inline-title", "theme-dark",
                    "callout-title-inner", "internal-link"):
            self.assertIn(cls, page)
        missing = markdown_preview.render_page(self.dir / "note.md", NOTE, {"md_css_path": str(self.dir / "x.css")})
        self.assertNotIn("layer(md-user)", missing)
        self.assertIn("layer(md-theme)", missing)

    def test_settings_row_shows_the_state_and_exports_without_overwriting(self):
        field = v2._MarkdownCssPathField("")
        self.assertEqual(field.status.text(), "")
        field.edit.setText(str(self.dir / "absente.css"))
        self.assertIn("style intégré", field.status.text())
        css = self.dir / "fabrice.css"
        css.write_text(".x { color: red; }", encoding="utf-8")
        field.edit.setText(str(css))
        self.assertEqual(field.status.text(), "✓ fabrice.css")
        self.assertEqual(field.text(), str(css))
        target = self.dir / "export.css"
        with mock.patch.object(v2.QFileDialog, "getSaveFileName", return_value=(str(target), "")), \
                mock.patch.object(md_pane, "_settings", return_value=dict(BASE)):
            field._export()
        self.assertTrue(md_style.is_exported_file(target))
        self.assertIn("exporté", field.status.text())
        with mock.patch.object(v2.QFileDialog, "getSaveFileName", return_value=(str(css), "")), \
                mock.patch.object(md_pane, "_settings", return_value=dict(BASE)):
            field._export()
        self.assertIn("refusé", field.status.text())
        self.assertEqual(css.read_text(encoding="utf-8"), ".x { color: red; }")
        field.deleteLater()


@unittest.skipUnless(markdown_preview.available(), "markdown-it-py absent")
class PaneCssTest(unittest.TestCase):
    """La page du module avec une feuille chargee (une seule page, chargee une fois)."""

    @classmethod
    def setUpClass(cls):
        cls.settings = dict(BASE)
        md_pane.HOOKS["settings"] = lambda: cls.settings
        md_pane.HOOKS["save_state"] = lambda k, v: cls.settings.__setitem__(k, v)
        cls.pane = md_pane.MarkdownPane()
        cls.pane.resize(1000, 700)
        cls.pane.show()
        if not _until(cls.pane.view, "!!(window.MD && MD.bridge && MD.editor && MD.toolbar)", 20):
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
        self.addCleanup(self.use, dict(BASE))
        self.view = self.pane.view

    def use(self, settings, changed=None):
        type(self).settings.clear()
        type(self).settings.update(settings)
        self.pane.apply_settings(self.settings, changed)

    def open(self, text=NOTE, name="note.md"):
        note = self.dir / name
        note.write_text(text, encoding="utf-8")
        self.assertTrue(self.pane.open(note))
        self.assertTrue(_until(self.view, f"!!(MD.state.current && MD.state.current.path === {str(note)!r})"))
        return note

    def edit(self, line=None):
        """Mode edition, curseur hors des lignes verifiees (leur syntaxe reste masquee)."""
        _js(self.view, "MD.setMode('edit'); MD.editor.cm.setCursor(MD.editor.cm.lineCount() - 1, 0); "
                       "MD.editor.lp.refresh(); MD.editor.cm.refresh(); true")
        settle(0.15)

    def reading(self):
        _js(self.view, "MD.setMode('reading'); true")
        self.assertTrue(_until(self.view, "document.querySelector('#md-read-body h1') !== null"))

    def css_file(self, text, name="obsidian.css"):
        css = self.dir / name
        css.write_text(text, encoding="utf-8")
        return css

    def load_css(self, css):
        self.use({**self.settings, "md_css_path": str(css)}, {"md_css_path"})
        self.assertTrue(_until(self.view, f"document.querySelector('#md-user-css').textContent.includes({css.name!r})"))
        settle(0.2)

    def test_obsidian_css_styles_reading_and_editing(self):
        self.open()
        self.load_css(self.css_file(OBSIDIAN_CSS))
        self.edit()
        expect = {
            # variable d'Obsidian (--h1-color) -> titre ; regle d'Obsidian sur ses classes -> h2, gras, code…
            "pre.md-h1 .cm-header-1": ("color", "rgb(1, 2, 3)"),
            "pre.md-h2 .cm-header-2": ("color", "rgb(4, 5, 6)"),
            ".cm-strong": ("color", "rgb(13, 14, 15)"),
            ".cm-inline-code:not(.cm-formatting)": ("background-color", "rgb(7, 8, 9)"),
            "pre.HyperMD-codeblock:not(.HyperMD-codeblock-begin)": ("background-color", "rgb(10, 11, 12)"),
            "pre.HyperMD-codeblock .cm-comment": ("color", "rgb(40, 41, 42)"),
            "pre.cm-line.HyperMD-quote": ("background-color", "rgb(50, 51, 52)"),
            ".md-block .callout-title": ("color", "rgb(16, 17, 18)"),
            ".md-block td": ("color", "rgb(60, 61, 62)"),
            ".cm-hmd-internal-link": ("color", "rgb(70, 71, 72)"),
            ".md-edit .inline-title": ("color", "rgb(80, 81, 82)"),
            "body": ("background-color", "rgb(20, 21, 22)"),
        }
        for selector, (prop, value) in expect.items():
            self.assertTrue(_until(self.view, f"{_style(selector, prop)} === {value!r}", 3),
                            f"édition {selector} {prop} = {_js(self.view, _style(selector, prop))}")
        self.assertEqual(_js(self.view, "getComputedStyle(document.querySelector('.list-bullet'), '::before').content"),
                         '"@"')
        self.reading()
        expect = {
            "#md-read-body h1": ("color", "rgb(1, 2, 3)"),
            "#md-read-body h2": ("color", "rgb(4, 5, 6)"),
            "#md-read-body strong": ("color", "rgb(13, 14, 15)"),
            "#md-read-body p code": ("background-color", "rgb(7, 8, 9)"),
            "#md-read-body pre": ("background-color", "rgb(10, 11, 12)"),
            "#md-read-body blockquote": ("background-color", "rgb(50, 51, 52)"),
            "#md-read-body .callout-title": ("color", "rgb(16, 17, 18)"),
            "#md-read-body td": ("color", "rgb(60, 61, 62)"),
            "#md-read-body a.internal-link": ("color", "rgb(70, 71, 72)"),
            "#md-read-title": ("color", "rgb(80, 81, 82)"),
        }
        for selector, (prop, value) in expect.items():
            self.assertEqual(_js(self.view, _style(selector, prop)), value, f"lecture {selector} {prop}")
        self.assertTrue(_until(self.view, f"{_style('#md-read-body pre .token.comment', 'color')} === 'rgb(40, 41, 42)'"))
        self.assertEqual(_js(self.view, "MD.editor.getText()"), NOTE)            # le texte n'a pas bouge

    def test_hostile_css_cannot_break_typing_scrolling_selection_or_bars(self):
        long_note = NOTE + "".join(f"Ligne {i}\n\n" for i in range(200))
        note = self.open(long_note)
        self.load_css(self.css_file(HOSTILE_CSS, "hostile.css"))
        self.edit()
        self.assertTrue(_js(self.view, "getComputedStyle(document.getElementById('md-edit')).display === 'block'"))
        self.assertTrue(_js(self.view, "getComputedStyle(document.getElementById('md-toolbar')).display === 'flex'"))
        self.assertGreater(_js(self.view, "document.querySelector('#md-toolbar .md-tool').getBoundingClientRect().width"), 10)
        self.assertGreater(_js(self.view, "document.querySelector('.CodeMirror').getBoundingClientRect().height"), 400)
        self.assertEqual(_js(self.view, _style("pre.cm-line", "white-space")), "pre-wrap")
        self.assertEqual(_js(self.view, _style("pre.cm-line", "position")), "relative")
        self.assertEqual(_js(self.view, _style("html", "overflow")), "hidden")
        # Saisie : le texte tape arrive dans le document et le curseur est sur la ligne affichee.
        _js(self.view, "MD.editor.cm.focus(); MD.editor.cm.setCursor(4, 0); MD.editor.cm.replaceSelection('Écrit '); true")
        self.assertTrue(_js(self.view, "MD.editor.getText().split('\\n')[4].startsWith('Écrit Un')"))
        gap = _js(self.view, "(() => { const cm = MD.editor.cm; const c = cm.cursorCoords(null, 'window');"
                             " const line = cm.display.lineDiv.querySelectorAll('pre.CodeMirror-line')[4]"
                             ".getBoundingClientRect(); return Math.abs(c.top - line.top) + Math.abs(cm.coordsChar({left: c.left + 1,"
                             " top: c.top + 2}, 'window').line - 4); })()")
        self.assertLess(gap, 30)
        # Selection et defilement.
        _js(self.view, "MD.editor.cm.setSelection({line: 4, ch: 0}, {line: 4, ch: 5}); true")
        self.assertEqual(_js(self.view, "MD.editor.cm.getSelection()"), "Écrit")
        _js(self.view, "MD.editor.cm.scrollTo(null, 3000); true")
        settle(0.1)
        self.assertGreater(_js(self.view, "MD.editor.cm.getScrollInfo().top"), 1000)
        self.assertTrue(self.pane.flush())
        self.assertTrue(note.read_text(encoding="utf-8").startswith(NOTE.split("\n\n")[0]))
        self.assertIn("Écrit Un **gras**", note.read_text(encoding="utf-8"))

    def test_exported_css_gives_the_same_look_once_reloaded(self):
        custom = {**BASE, "md_h1_font_color": "#ff112233", "md_codeblock_bg": "#ff445566",
                  "md_bold_color": "#ff778899", "md_text_font_color": "#ffaabbcc", "md_bg_color": "#ff101112",
                  "md_h2_space_before": 40, "md_code_inline_bg": "#ff0a0b0c", "md_table_alt_bg": "#ff090807"}
        exported = self.dir / "pipeline-browser.css"
        md_style.export_obsidian_css(custom, exported)
        self.open()
        # Reglages d'origine + la feuille exportee : meme rendu que les reglages exportes.
        self.load_css(exported)
        self.edit()
        expect = {"pre.md-h1 .cm-header-1": ("color", "rgb(17, 34, 51)"), ".cm-strong": ("color", "rgb(119, 136, 153)"),
                  "pre.HyperMD-codeblock:not(.HyperMD-codeblock-begin)": ("background-color", "rgb(68, 85, 102)"),
                  ".cm-inline-code:not(.cm-formatting)": ("background-color", "rgb(10, 11, 12)"),
                  "pre.md-h2": ("padding-top", "40px"), "body": ("background-color", "rgb(16, 17, 18)"),
                  ".CodeMirror": ("color", "rgb(170, 187, 204)")}
        for selector, (prop, value) in expect.items():
            self.assertTrue(_until(self.view, f"{_style(selector, prop)} === {value!r}", 3),
                            f"édition {selector} {prop} = {_js(self.view, _style(selector, prop))}")
        self.reading()
        expect = {"#md-read-body h1": ("color", "rgb(17, 34, 51)"), "#md-read-body h2": ("margin-top", "40px"),
                  "#md-read-body pre": ("background-color", "rgb(68, 85, 102)"),
                  "#md-read-body p code": ("background-color", "rgb(10, 11, 12)"),
                  "#md-read-body tbody tr:nth-child(even) td, #md-read-body td": ("color", None)}
        for selector, (prop, value) in expect.items():
            if value is not None:
                self.assertEqual(_js(self.view, _style(selector, prop)), value, f"lecture {selector} {prop}")
        # Sans feuille, les memes reglages exportes donnent le meme rendu (aller-retour).
        self.use({**custom, "md_css_path": ""}, None)
        self.assertTrue(_until(self.view, f"{_style('#md-read-body h1', 'color')} === 'rgb(17, 34, 51)'"))

    def test_missing_css_keeps_the_builtin_style(self):
        self.open()
        css = self.css_file(OBSIDIAN_CSS)
        self.load_css(css)
        self.reading()
        self.assertEqual(_js(self.view, _style("#md-read-body h1", "color")), "rgb(1, 2, 3)")
        css.unlink()                                                           # fichier disparu
        self.use({**self.settings, "md_css_path": str(css)}, None)
        self.assertTrue(_until(self.view, "document.querySelector('#md-user-css').textContent === ''"))
        self.assertTrue(_until(self.view, f"{_style('#md-read-body h1', 'color')} === 'rgb(75, 175, 255)'"))
        self.assertIn("introuvable", self.pane.css_status)

    def test_settings_stay_live_and_typing_never_reloads_the_css(self):
        self.open()
        css = self.css_file(OBSIDIAN_CSS)
        self.load_css(css)
        self.edit()
        # Reglage que la feuille ne definit pas (H3) : applique ; reglage que la feuille definit (H1) : la feuille.
        t0 = time.perf_counter()
        self.use({**self.settings, "md_h2_space_before": 33, "md_h1_font_color": "#ff00ff00"},
                 {"md_h2_space_before", "md_h1_font_color"})
        self.assertLess(time.perf_counter() - t0, 0.1)
        self.assertTrue(_until(self.view, f"{_style('pre.md-h2', 'padding-top')} === '33px'"))
        self.assertEqual(_js(self.view, _style("pre.md-h1 .cm-header-1", "color")), "rgb(1, 2, 3)")
        pushed = []
        with mock.patch.object(self.pane, "_push", side_effect=lambda m: pushed.append(m.get("type"))):
            _js(self.view, "MD.editor.cm.setCursor(4, 0); for (let i = 0; i < 20; i++) MD.editor.cm.replaceSelection('x'); true")
            settle(0.6)
        self.assertNotIn("userCss", pushed)
        self.assertNotIn("style", pushed)

    def test_css_edited_on_disk_is_reloaded(self):
        self.open()
        css = self.css_file(".markdown-preview-view h1 { color: rgb(1, 1, 1); }")
        self.load_css(css)
        self.reading()
        self.assertTrue(_until(self.view, f"{_style('#md-read-body h1', 'color')} === 'rgb(1, 1, 1)'"))
        time.sleep(0.05)
        css.write_text(".markdown-preview-view h1 { color: rgb(2, 2, 2); }", encoding="utf-8")
        self.assertTrue(_until(self.view, f"{_style('#md-read-body h1', 'color')} === 'rgb(2, 2, 2)'", 8))

    def test_inspector_page_renders_the_obsidian_css(self):
        from PySide6.QtWebEngineWidgets import QWebEngineView
        css = self.css_file(OBSIDIAN_CSS)
        note = self.dir / "note.md"
        note.write_text(NOTE, encoding="utf-8")
        view = QWebEngineView()
        self.addCleanup(view.deleteLater)
        view.resize(600, 800)
        view.setHtml(markdown_preview.render_page(note, NOTE, {**BASE, "md_css_path": str(css)}),
                     QUrl.fromLocalFile(str(self.dir) + "/"))
        self.assertTrue(_until(view, f"{_style('.md-body h2', 'color')} === 'rgb(4, 5, 6)'"))
        self.assertEqual(_js(view, _style(".md-body h1", "color")), "rgb(1, 2, 3)")
        self.assertEqual(_js(view, _style(".md-body pre", "background-color")), "rgb(10, 11, 12)")
        self.assertEqual(_js(view, _style("html", "overflow-y")), "auto")            # defile par html


def tearDownModule():
    """Pages web detruites AVANT l'application (sinon QtWebEngine plantait a la sortie du processus)."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWebEngineWidgets import QWebEngineView
    for view in APP.allWidgets():
        if isinstance(view, QWebEngineView):
            view.deleteLater()
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        settle(0.1)


if __name__ == "__main__":
    unittest.main()

"""Feuille CSS partagee avec Obsidian (fm_markdown/css_sync.py) : le cycle complet, sur des COPIES temporaires.

1. un reglage change dans Pipeline Browser -> apercu immediat dans la page (avant toute ecriture) ;
2. le fichier recoit la declaration correspondante (une seule ecriture apres le geste, souris relachee) ;
3. la regle produite est du CSS valide sur les classes d'Obsidian (chargee seule, sans le module) ;
4. le fichier modifie de l'exterieur -> page et reglages (fenetre de reglages comprise) reprennent la valeur ;
5. regles, commentaires, valeurs et declarations inconnues gardes ; encodage, BOM, fins de ligne gardes.
Jamais le vrai fichier de l'utilisateur : tests/_isolate.py coupe la synchronisation, ce module l'allume sur ses
propres copies."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --log-level=3")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEventLoop, QTimer, QUrl, Qt
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
APP = QApplication.instance() or QApplication([])

from fm_markdown import preview as markdown_preview
import fm_markdown.css_sync as css_sync
import fm_markdown.pane as md_pane
import fm_markdown.style as md_style
import settings_store
import settings_window_v2 as v2

BASE = {**settings_store.DEFAULT_SETTINGS, "md_css_path": ""}

# Feuille « ecrite a la main » (comme fabrice.css) : tout ce qui n'est pas dans le bloc doit rester tel quel.
USER_CSS = """/* Ma feuille : commentaires, variables et regles a moi */
:root {
  --H1-couleur: rgb(75, 175, 255);   /* bleu */
}
.cm-line span.cm-header-1 { color: var(--H1-couleur); font-size: 1.1em !important; }
@media (max-width: 600px) { .markdown-rendered h1 { font-size: 1.4em; } }
.callout:not([data-callout="note"]) .callout-title { color: #ff6f00; }
"""


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


class _Case(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.css = self.dir / "fabrice.css"
        self.css.write_text(USER_CSS, encoding="utf-8")
        self.received = []
        patcher = mock.patch.dict(css_sync.HOOKS, {"external": self.received.append})
        patcher.start()
        self.addCleanup(patcher.stop)

    def engine(self, values=None):
        sync = css_sync.CssSync(enabled=True)
        self.addCleanup(sync.deleteLater)
        sync.update({**BASE, "md_css_path": str(self.css), **(values or {})})
        return sync


class BlockTest(unittest.TestCase):
    """Modification sur place du bloc gere."""

    def test_patch_changes_only_the_controlled_declaration(self):
        h1 = css_sync.BY_ID["h1.color"]
        text = css_sync.patch(USER_CSS, {"h1.color": "#112233ff"})
        self.assertTrue(text.startswith(USER_CSS))                              # rien d'avant n'a bouge
        self.assertIn(f"{h1.selector} {{\n  color: #112233ff !important;\n}}", text)
        # Le bloc recoit une declaration et un commentaire de l'utilisateur : gardes ; seule la valeur change.
        mine = text.replace("  color: #112233ff !important;\n", "  color: #112233ff !important;\n"
                            "  /* a moi */ text-shadow: 0 0 2px red;\n")
        again = css_sync.patch(mine, {"h1.color": "#445566ff", "h1.size": "30px"})
        self.assertIn("color: #445566ff !important;\n  /* a moi */ text-shadow: 0 0 2px red;\n  font-size: 30px !important;",
                      again)
        self.assertEqual(again.replace("#445566ff", "#112233ff").replace("  font-size: 30px !important;\n", ""), mine)
        # Retirer : la ligne seulement.
        self.assertEqual(css_sync.patch(again, {"h1.size": None}).replace("#445566ff", "#112233ff"), mine)

    def test_every_declaration_reads_back_to_the_same_settings(self):
        values = dict(settings_store.MARKDOWN_DEFAULTS)
        out = md_style.variables(values)
        text = css_sync.patch("", {d.id: d.fwd(out, values) for d in css_sync.DECLS})
        found = css_sync.read_block(text)
        self.assertGreater(len(found), 150)
        self.assertEqual(css_sync.interpret(found, values), ({}, []))
        # Valeurs ecrites autrement (comme dans Obsidian) : interpretees.
        found.update({"h1.color": "rgb(1, 2, 3)", "h1.size": "21px", "quote.padding": "4px 8px",
                      "codeblock.radius": "6px", "text.line_height": "1.7", "bullet1.char": '"▸"',
                      "codeblock.border_left": "none", "h2.weight": "bold", "h3.family": "'Georgia', serif"})
        updates, unparsed = css_sync.interpret(found, values)
        self.assertEqual(unparsed, [])
        self.assertEqual(updates["md_h1_font_color"], "#ff010203")
        self.assertEqual(updates["md_h1_font_size"], 21)
        self.assertEqual(updates["md_quote_padding"], {"left": 8, "top": 4, "right": 8, "bottom": 4})
        self.assertEqual(updates["md_codeblock_radius"], {"top_left": 6, "top_right": 6, "bottom_right": 6,
                                                          "bottom_left": 6})
        self.assertEqual(updates["md_line_height"], 170)
        self.assertEqual(updates["md_bullet_1_char"], "▸")
        self.assertFalse(updates["md_codeblock_border_enabled"]["left"])
        self.assertEqual(updates["md_h2_weight"], 700)
        self.assertEqual(updates["md_h3_font_family"], "Georgia")
        # Non interpretable (unite relative, variable) : garde tel quel, reglage intact.
        updates, unparsed = css_sync.interpret({"h1.size": "1.1em", "h2.color": "var(--H1-couleur)"}, values)
        self.assertEqual((updates, sorted(unparsed)), ({}, ["h1.size", "h2.color"]))


class EngineTest(_Case):
    def test_setting_change_is_shown_at_once_and_written_once_after_the_gesture(self):
        sync = self.engine()
        self.assertEqual(self.css.read_text(encoding="utf-8"), USER_CSS)        # lire n'ecrit rien
        self.assertEqual(sync.injection, "")
        values = dict(sync.values)
        for step in range(20):                                                 # un curseur tire : 20 crans
            values = {**values, "md_h1_font_size": 20 + step}
            sync.update(values, {"md_h1_font_size"})
            self.assertIn(f"font-size: {20 + step}px !important", sync.injection)   # apercu immediat
        self.assertEqual(self.css.read_text(encoding="utf-8"), USER_CSS)        # rien d'ecrit pendant le geste
        with mock.patch.object(css_sync.QApplication, "mouseButtons", return_value=Qt.LeftButton):
            settle(0.6)
            self.assertEqual(sync.writes, 0)                                   # bouton tenu : on attend
        settle(0.5)
        self.assertEqual(sync.writes, 1)
        text = self.css.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(USER_CSS))                              # le reste du fichier intact
        found = css_sync.read_block(text)
        self.assertEqual(found, {"h1.size": "39px"})                             # seule la declaration changee
        self.assertIn("Synchronisé", sync.status)

    def test_external_edit_updates_the_settings_and_keeps_unknown_values(self):
        sync = self.engine({"md_h1_font_color": "#ff102030"})
        sync.update({**sync.values, "md_h1_font_color": "#ff405060"}, {"md_h1_font_color"})
        self.assertTrue(sync.flush())
        text = self.css.read_text(encoding="utf-8")
        edited = (text.replace("color: #405060ff !important;", "color: rgb(9, 8, 7) !important;\n  font-size: 1.1em;")
                  + "\n.ajout { color: red; }\n")
        self.css.write_text(edited, encoding="utf-8")
        changed = []
        sync.fileChanged.connect(lambda: changed.append(True))
        sync.check_disk()
        self.assertEqual(self.received, [{"md_h1_font_color": "#ff090807"}])     # repris dans les reglages
        self.assertEqual(sync.values["md_h1_font_color"], "#ff090807")
        self.assertEqual(sync.unparsed, ["h1.size"])                             # 1.1em : garde tel quel
        self.assertTrue(changed)
        self.assertIn("font-size: 1.1em", sync.injection)
        # Un autre reglage change ensuite : l'ajout exterieur et la valeur non interpretable restent.
        sync.update({**sync.values, "md_bold_color": "#ff00ff00"}, {"md_bold_color"})
        self.assertTrue(sync.flush())
        final = self.css.read_text(encoding="utf-8")
        self.assertIn(".ajout { color: red; }", final)
        self.assertIn("font-size: 1.1em;", final)
        self.assertIn("color: rgb(9, 8, 7) !important;", final)
        self.assertIn("#00ff00ff !important", final)
        self.assertTrue(final.startswith(USER_CSS))

    def test_conflict_keeps_the_pending_pipeline_value_and_takes_the_others(self):
        sync = self.engine()
        sync.update({**sync.values, "md_h1_font_color": "#ff111111", "md_h2_font_color": "#ff222222"},
                    {"md_h1_font_color", "md_h2_font_color"})
        self.assertTrue(sync.flush())
        sync.update({**sync.values, "md_h1_font_color": "#ff333333"}, {"md_h1_font_color"})   # en attente
        text = self.css.read_text(encoding="utf-8")
        self.css.write_text(text.replace("#111111ff", "#444444ff").replace("#222222ff", "#555555ff"), encoding="utf-8")
        self.assertTrue(sync.flush(), sync.status)                              # relu avant d'ecrire
        found = css_sync.read_block(self.css.read_text(encoding="utf-8"))
        self.assertEqual(found["h1.color"], "#333333ff")                         # geste de Pipeline Browser
        self.assertEqual(found["h2.color"], "#555555ff")                         # modification exterieure gardee
        self.assertEqual(self.received[-1], {"md_h2_font_color": "#ff555555"})
        self.assertIn("conflit", sync.status)

    def test_encoding_bom_and_line_endings_are_kept(self):
        self.css.write_bytes(b"\xef\xbb\xbf/* \xc3\xa9t\xc3\xa9 */\r\n.x { color: red; }\r\n")
        sync = self.engine()
        sync.update({**sync.values, "md_hr_color": "#ff0000ff"}, {"md_hr_color"})
        self.assertTrue(sync.flush())
        raw = self.css.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf/* \xc3\xa9t\xc3\xa9 */\r\n.x { color: red; }\r\n"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertIn(b"--hr-color: #0000ffff;", raw)

    def test_missing_or_broken_file_is_never_created_nor_damaged(self):
        missing = self.dir / "absente.css"
        sync = css_sync.CssSync(enabled=True)
        self.addCleanup(sync.deleteLater)
        sync.update({**BASE, "md_css_path": str(missing)})
        sync.update({**sync.values, "md_h1_font_color": "#ff000000"}, {"md_h1_font_color"})
        self.assertTrue(sync.flush())
        self.assertFalse(missing.exists())
        broken = USER_CSS + css_sync.BEGIN + " */\n.markdown-rendered h1 { color: red; }\n"   # fin du bloc absente
        self.css.write_text(broken, encoding="utf-8")
        sync = self.engine()
        sync.update({**sync.values, "md_h1_font_color": "#ff000000"}, {"md_h1_font_color"})
        self.assertFalse(sync.flush())
        self.assertEqual(self.css.read_text(encoding="utf-8"), broken)
        self.assertIn("incomplet", sync.status)

    def test_disabled_sync_never_reads_the_user_file(self):
        self.assertTrue(os.environ.get("PIPELINE_NO_CSS_SYNC"))                 # pose par tests/_isolate.py
        sync = css_sync.CssSync()
        self.addCleanup(sync.deleteLater)
        sync.update({**BASE, "md_css_path": str(self.css)})
        self.assertIsNone(sync.path)


class ObsidianValidityTest(_Case):
    def test_written_rules_are_valid_css_on_obsidian_classes(self):
        """La feuille ecrite, chargee SEULE dans une page qui a la structure d'Obsidian (sans le module) : chaque
        declaration du bloc est comprise par le navigateur (Obsidian = Chromium) et s'applique."""
        from PySide6.QtWebEngineWidgets import QWebEngineView
        values = {**BASE, "md_h1_font_color": "#ff010203", "md_codeblock_bg": "#ff0a0b0c", "md_h2_space_before": 31}
        out = md_style.variables(values)
        self.css.write_text(css_sync.patch(USER_CSS, {d.id: d.fwd(out, values) for d in css_sync.DECLS}),
                            encoding="utf-8")
        page = f"""<!doctype html><html><head><link rel="stylesheet" href="{self.css.as_uri()}"></head>
<body class="theme-dark"><div class="markdown-reading-view"><div class="markdown-preview-view markdown-rendered">
<h1>T</h1><h2>D</h2><pre><code>x</code></pre></div></div>
<div class="markdown-source-view mod-cm6"><div class="cm-editor"><div class="cm-content">
<div class="cm-line HyperMD-header HyperMD-header-1"><span class="cm-header cm-header-1">T</span></div>
<div class="cm-line HyperMD-header HyperMD-header-2"><span class="cm-header cm-header-2">D</span></div>
<div class="cm-line HyperMD-codeblock HyperMD-codeblock-bg">x</div></div></div></div></body></html>"""
        view = QWebEngineView()
        self.addCleanup(view.deleteLater)
        view.setHtml(page, QUrl.fromLocalFile(str(self.dir) + "/"))
        self.assertTrue(_until(view, f"{_style('.markdown-rendered h1', 'color')} === 'rgb(1, 2, 3)'"))
        self.assertEqual(_js(view, _style(".cm-header-1", "color")), "rgb(1, 2, 3)")       # bat la regle a la main
        self.assertEqual(_js(view, _style(".HyperMD-header-2", "padding-top")), "31px")
        self.assertEqual(_js(view, _style(".markdown-rendered pre", "background-color")), "rgb(10, 11, 12)")
        self.assertEqual(_js(view, _style(".HyperMD-codeblock", "background-color")), "rgb(10, 11, 12)")
        # Aucune declaration rejetee par le navigateur : meme nombre que dans le fichier, regle par regle.
        expected = {}
        for decl in css_sync.DECLS:
            if decl.fwd(out, values) is not None:
                expected.setdefault(css_sync._norm(decl.selector), set()).add(decl.prop)
        wanted = {sel: sorted(props) for sel, props in expected.items()}
        parsed = json.loads(_js(view, "JSON.stringify((() => { const want = " + json.dumps(wanted) + r""";
            const norm = (t) => t.replace(/\s+/g, ' ').replace(/\s*,\s*/g, ', ').trim(); const out = {};
            for (const r of document.styleSheets[0].cssRules) {
              if (!r.selectorText) continue; const key = norm(r.selectorText); if (!want[key]) continue;
              out[key] = out[key] || {};
              for (const prop of want[key]) { const v = r.style.getPropertyValue(prop); if (v) out[key][prop] = v; }
            } return out; })())"""))
        for selector, props in wanted.items():
            self.assertIn(selector, parsed)
            for prop in props:
                self.assertIn(prop, parsed[selector], f"{selector} : {prop} rejete par le navigateur")


class SettingsWindowFollowsTest(_Case):
    def test_external_values_reach_the_open_settings_window_and_the_files(self):
        settings = copy.deepcopy(BASE)
        with mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(settings)), \
                mock.patch.object(v2, "AUTOSAVE", False):
            window = v2.SettingsWindowV2()
        self.addCleanup(window.deleteLater)
        index = [label for label, _t in v2.SCOPES].index(v2.MARKDOWN_TAB)
        window._show_page(index)
        heads = next(n for n in window.findChildren(v2._LazyNode)
                     if n._values.name == v2.MARKDOWN_TAB and n.node.title == "Titres H1-H6")
        window.reset_to_defaults(heads)                      # sections construites (champs a l'ancienne valeur)
        settle(0.1)
        self.assertEqual(window.wired_values()["md_h1_font_color"], settings_store.MARKDOWN_DEFAULTS["md_h1_font_color"])
        import pipeline_browser as pb
        detail = SimpleNamespace(refresh_markdown_style=mock.Mock())
        fake = SimpleNamespace(_settings_dialog_v2=window, detail=detail, _md_inspector_timer=None)
        pb.PipelineBrowser._apply_md_external(fake, {"md_h1_font_color": "#ff090807"})
        settle(0.1)
        self.assertEqual(window.wired_values()["md_h1_font_color"], "#ff090807")   # la fenetre montre la valeur
        self.assertEqual(settings_store.load_settings()["md_h1_font_color"], "#ff090807")   # enregistree
        detail.refresh_markdown_style.assert_called_once()


@unittest.skipUnless(markdown_preview.available(), "markdown-it-py absent")
class PaneSyncTest(_Case):
    """Le module : apercu immediat, fichier ecrit, reprise d'une modification exterieure."""

    @classmethod
    def setUpClass(cls):
        cls.saved_engine = css_sync._ENGINE
        css_sync._ENGINE = css_sync.CssSync(enabled=True)                 # moteur de ce test (copies)
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
        css_sync._ENGINE.update(BASE)
        css_sync._ENGINE.deleteLater()
        css_sync._ENGINE = cls.saved_engine
        settle(0.1)

    def apply(self, changes):
        type(self).settings.update(changes)
        self.pane.apply_settings(self.settings, set(changes))

    def test_full_cycle(self):
        view = self.pane.view
        note = self.dir / "note.md"
        note.write_text("# Titre\n\nTexte **gras**\n", encoding="utf-8")
        self.apply({"md_css_path": str(self.css)})
        self.addCleanup(self.apply, {"md_css_path": ""})
        self.assertTrue(self.pane.open(note))
        self.assertTrue(_until(view, f"!!(MD.state.current && MD.state.current.path === {str(note)!r})"))
        _js(view, "MD.setMode('edit'); MD.editor.cm.setCursor(2, 0); true")
        sync = css_sync.engine()
        # 1-2. Reglage change : la page change AVANT l'ecriture, puis le fichier recoit la declaration.
        t0 = time.perf_counter()
        self.apply({"md_h1_font_color": "#ff0a0b0c"})
        self.assertLess(time.perf_counter() - t0, 0.05)
        self.assertTrue(_until(view, f"{_style('pre.md-h1 .cm-header-1', 'color')} === 'rgb(10, 11, 12)'", 3))
        self.assertEqual(self.css.read_text(encoding="utf-8"), USER_CSS)
        self.assertTrue(_until(view, "true", 0.1))
        end = time.monotonic() + 3
        while time.monotonic() < end and "#0a0b0cff" not in self.css.read_text(encoding="utf-8"):
            settle(0.05)
        text = self.css.read_text(encoding="utf-8")
        self.assertIn("color: #0a0b0cff !important;", text)
        self.assertTrue(text.startswith(USER_CSS))
        # 4. Modifie dans « Obsidian » : la page et les reglages suivent.
        received = []
        css_sync.HOOKS["external"] = lambda values: (received.append(values), self.apply(values))
        self.css.write_text(text.replace("#0a0b0cff", "rgb(200, 100, 50)"), encoding="utf-8")
        self.assertTrue(_until(view, f"{_style('pre.md-h1 .cm-header-1', 'color')} === 'rgb(200, 100, 50)'", 5))
        self.assertEqual(received, [{"md_h1_font_color": "#ffc86432"}])
        self.assertEqual(self.settings["md_h1_font_color"], "#ffc86432")
        _js(view, "MD.setMode('reading'); true")
        self.assertTrue(_until(view, f"{_style('#md-read-body h1', 'color')} === 'rgb(200, 100, 50)'"))
        # La reprise n'ecrit rien de plus (aucune boucle) et le texte de la note n'a pas bouge.
        writes = sync.writes
        settle(0.7)
        self.assertEqual(sync.writes, writes)
        self.assertEqual(note.read_text(encoding="utf-8"), "# Titre\n\nTexte **gras**\n")


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

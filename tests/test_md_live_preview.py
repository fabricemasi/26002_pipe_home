"""Module Markdown : edition visuelle comparable a celle d'Obsidian (mdeditor/web/editor.js + base.css).

Cases a cocher (clic = Markdown modifie, etat garde a l'enregistrement), listes imbriquees (retrait par cran, puce
dans le retrait, lignes repliees alignees sur le texte), citations (« > » garde sa place, barre en ::before
qu'une feuille peut masquer comme dans Obsidian), repli des titres. Notes temporaires seulement."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_md_tables import APP, _js, _json, _until, settle  # noqa: F401  (meme page, memes outils)
import markdown_preview
import mdeditor.pane as md_pane
import settings_store

NOTE = ("> Sitation\n> Test seconde ligne\n\n"
        "- liste 1\n- liste 2\n\t- niveau 2\n\t\t- niveau 3\n"
        "- " + "élément assez long pour revenir à la ligne " * 6 + "\n\n"
        "Paragraphe.\n\n- [ ] Coche\n- [x] Faite\n\n# Titre 1\nsous le titre 1\n## Titre 2\nsous le titre 2\n# Autre\nfin\n")

LINE = "[...document.querySelectorAll('.md-edit .CodeMirror-code pre.CodeMirror-line')].find(l => l.textContent.includes(%r))"


def text_left(word):
    """Position (px) du 1er caractere de « word » dans sa ligne de l'editeur."""
    return f"""(() => {{ const l = {LINE % word}; const w = document.createTreeWalker(l, NodeFilter.SHOW_TEXT); let n;
        while ((n = w.nextNode())) {{ const i = n.data.indexOf({word!r}); if (i >= 0) {{ const g = document.createRange();
        g.setStart(n, i); g.setEnd(n, i + 1); return g.getBoundingClientRect().left; }} }} return null; }})()"""


@unittest.skipUnless(markdown_preview.available(), "markdown-it-py absent")
class LivePreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = {**settings_store.DEFAULT_SETTINGS, "md_css_path": "", "md_list_indent": 20}
        md_pane.HOOKS["settings"] = lambda: cls.settings
        md_pane.HOOKS["save_state"] = lambda k, v: cls.settings.__setitem__(k, v)
        cls.pane = md_pane.MarkdownPane()
        cls.pane.resize(700, 900)
        cls.pane.show()
        if not _until(cls.pane, "!!(window.MD && MD.bridge && MD.editor)", 20):
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
        self.path = self.dir / "note.md"
        self.path.write_text(NOTE, encoding="utf-8", newline="")
        self.assertTrue(self.pane.open(self.path))
        self.assertTrue(_until(self.pane, f"!!(MD.state.current && MD.state.current.path === {str(self.path)!r})"))
        _js(self.pane, f"MD.setMode('edit'); MD.editor.cm.focus(); MD.editor.cm.setCursor({NOTE.count(chr(10))}, 0); true")
        self.assertTrue(_until(self.pane, "document.querySelectorAll('.md-edit .md-checkbox').length === 2"))

    def test_checkbox_click_toggles_the_markdown_and_is_saved(self):
        info = _json(self.pane, """(() => { const b = [...document.querySelectorAll('.md-edit .md-checkbox')];
            const dash = document.querySelector('.md-edit .md-task-dash');
            return {classes: b[0].className, checked: b.map(x => x.checked), dash: getComputedStyle(dash).color,
                    dashText: dash.textContent}; })()""")
        self.assertIn("task-list-item-checkbox", info["classes"])
        self.assertEqual(info["checked"], [False, True])
        self.assertEqual(info["dash"], "rgba(0, 0, 0, 0)")              # le tiret garde sa place, invisible
        self.assertEqual(info["dashText"], "-")
        _js(self.pane, "document.querySelectorAll('.md-edit .md-checkbox')[0].dispatchEvent(new MouseEvent('mousedown', {bubbles: true})); true")
        self.assertTrue(_until(self.pane, "MD.editor.getText().includes('- [x] Coche')"))
        self.assertTrue(_until(self.pane, "document.querySelectorAll('.md-edit .md-checkbox')[0] && document.querySelectorAll('.md-edit .md-checkbox')[0].checked"))
        _js(self.pane, "document.querySelectorAll('.md-edit .md-checkbox')[1].dispatchEvent(new MouseEvent('mousedown', {bubbles: true})); true")
        self.assertTrue(_until(self.pane, "MD.editor.getText().includes('- [ ] Faite')"))
        self.assertTrue(self.pane.flush())
        saved = self.path.read_text(encoding="utf-8")
        self.assertIn("- [x] Coche\n- [ ] Faite\n", saved)
        self.assertEqual(saved.replace("- [x] Coche\n- [ ] Faite", "- [ ] Coche\n- [x] Faite"), NOTE)

    def test_nested_lists_indent_by_the_list_indent_with_the_bullet_inside(self):
        left = {w: _js(self.pane, text_left(w)) for w in ("Paragraphe", "liste 1", "niveau 2", "niveau 3")}
        bullet = _json(self.pane, f"(() => {{ const b = {LINE % 'liste 1'}.querySelector('.list-bullet'); "
                                  f"return b.getBoundingClientRect().left; }})()")
        self.assertGreater(bullet, left["Paragraphe"] + 5)              # la puce est dans le retrait (0,75 em)
        self.assertGreater(left["liste 1"], bullet)
        self.assertAlmostEqual(left["niveau 2"] - left["liste 1"], 20, delta=3)   # un cran = Retrait des listes
        self.assertAlmostEqual(left["niveau 3"] - left["niveau 2"], 20, delta=3)

    def test_wrapped_list_item_lines_align_on_the_item_text(self):
        rects = _json(self.pane, f"""(() => {{ const l = {LINE % 'assez long'}; const w = document.createTreeWalker(l, NodeFilter.SHOW_TEXT);
            let n, out = []; while ((n = w.nextNode())) {{ const g = document.createRange(); g.selectNodeContents(n);
            for (const r of g.getClientRects()) out.push([Math.round(r.left), Math.round(r.top)]); }}
            return out; }})()""")
        tops = sorted({top for _left, top in rects})
        self.assertGreater(len(tops), 1, "la ligne devrait revenir a la ligne")
        first = min(left for left, top in rects if top == tops[0] and left > 0)
        second = min(left for left, top in rects if top == tops[1])
        text = _js(self.pane, text_left("élément"))
        self.assertAlmostEqual(second, text, delta=2)
        self.assertLess(first, text)

    def test_quote_marker_keeps_its_place_and_its_bar_can_be_hidden_like_obsidian(self):
        hidden = "(() => { const m = %s.querySelector('.md-quote-mark-hidden'); return !!m && getComputedStyle(m).color; })()" % (LINE % 'Sitation')
        self.assertTrue(_until(self.pane, hidden + " === 'rgba(0, 0, 0, 0)'"))
        inactive = _js(self.pane, text_left("Sitation"))
        _js(self.pane, "MD.editor.cm.setCursor(0, 4); true")
        self.assertTrue(_until(self.pane, f"!{LINE % 'Sitation'}.querySelector('.md-quote-mark-hidden')"))
        self.assertAlmostEqual(_js(self.pane, text_left("Sitation")), inactive, delta=0.5)   # le texte ne saute pas
        bar = _json(self.pane, f"(() => {{ const s = getComputedStyle({LINE % 'Sitation'}, '::before'); "
                               f"return [s.display, s.borderLeftWidth]; }})()")
        self.assertNotEqual(bar[0], "none")
        _js(self.pane, "document.getElementById('md-user-css').textContent = '@layer md-user { .cm-editor .cm-line::before { display: none !important; } }'; true")
        self.assertTrue(_until(self.pane, f"getComputedStyle({LINE % 'Sitation'}, '::before').display === 'none'"))
        _js(self.pane, "document.getElementById('md-user-css').textContent = ''; true")

    def test_heading_fold_indicator_folds_the_section(self):
        self.assertTrue(_until(self.pane, f"!!{LINE % 'Titre 1'}.querySelector('.md-fold')"))
        line = NOTE.split("\n").index("# Titre 1")
        _js(self.pane, f"{LINE % 'Titre 1'}.querySelector('.md-fold').dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}})); true")
        self.assertTrue(_until(self.pane, f"MD.editor.cm.isFolded({{line: {line}, ch: 9}})"))
        self.assertTrue(_until(self.pane, "![...document.querySelectorAll('.md-edit pre.CodeMirror-line')].some(l => l.textContent.includes('sous le titre 2'))"))
        self.assertTrue(_until(self.pane, f"{LINE % 'Titre 1'}.querySelector('.md-fold.is-collapsed') !== null"))
        self.assertTrue(_until(self.pane, f"!!{LINE % 'Autre'}"))         # le titre suivant de meme niveau reste
        _js(self.pane, f"{LINE % 'Titre 1'}.querySelector('.md-fold').dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}})); true")
        self.assertTrue(_until(self.pane, f"!MD.editor.cm.isFolded({{line: {line}, ch: 9}})"))
        self.assertEqual(_js(self.pane, "MD.editor.getText()"), NOTE)       # replier ne change pas le texte

    def test_reading_checkbox_and_lists(self):
        _js(self.pane, "MD.setMode('reading'); true")
        self.assertTrue(_until(self.pane, "document.querySelectorAll('#md-read-body input.task-list-item-checkbox').length === 2"))
        _js(self.pane, "document.querySelectorAll('#md-read-body input.task-list-item-checkbox')[0].click(); true")
        self.assertTrue(_until(self.pane, "MD.editor.getText().includes('- [x] Coche')"))
        _js(self.pane, "MD.setMode('edit'); true")

    def test_settings_and_shared_sheet_change_lists_and_checkboxes_live(self):
        """Reglages (variables) puis feuille partagee (bloc gere, comme le pousse la synchronisation) : retrait des
        listes, puces et cases suivent sans recharger la page ; les lignes repliees restent alignees."""
        before = _js(self.pane, text_left("niveau 2")) - _js(self.pane, text_left("liste 1"))
        self.assertAlmostEqual(before, 20, delta=3)
        settings = {**self.settings, "md_list_indent": 34, "md_checkbox_color": "#ff00ff00"}
        self.pane.apply_settings(settings, {"md_list_indent", "md_checkbox_color"})
        self.assertTrue(_until(self.pane, f"Math.abs(({text_left('niveau 2')}) - ({text_left('liste 1')}) - 34) < 3"))
        self.assertTrue(_until(self.pane, "getComputedStyle(document.querySelectorAll('.md-edit .md-checkbox')[1]).backgroundColor === 'rgb(0, 255, 0)'"))
        # Bloc gere de la feuille partagee (couche md-user) : une puce plus grosse, remesuree.
        self.pane._on_managed_css("@layer md-user { .markdown-source-view.mod-cm6 .cm-list-1 .list-bullet::before "
                                  "{ content: '★' !important; font-size: 30px !important; } }")
        self.assertTrue(_until(self.pane, f"getComputedStyle({LINE % 'liste 1'}.querySelector('.list-bullet'), '::before').content.includes('★')"))
        # Lignes repliees de l'element : toujours alignees sur son texte (marque remesuree apres la feuille).
        aligned = f"""(() => {{ const l = {LINE % 'assez long'}; const rects = [];
            const w = document.createTreeWalker(l, NodeFilter.SHOW_TEXT); let n;
            while ((n = w.nextNode())) {{ const g = document.createRange(); g.selectNodeContents(n);
              for (const r of g.getClientRects()) rects.push(r); }}
            const tops = [...new Set(rects.map(r => Math.round(r.top)))].sort((a, b) => a - b);
            const second = Math.min(...rects.filter(r => Math.round(r.top) === tops[1]).map(r => r.left));
            return Math.abs(second - ({text_left('élément')})) < 2; }})()"""
        self.assertTrue(_until(self.pane, aligned))
        self.pane._on_managed_css("")
        self.pane.apply_settings(self.settings, {"md_list_indent", "md_checkbox_color"})

    def test_font_color_remains_applied_while_its_html_tags_are_revealed(self):
        source = 'Texte <font color="#3356bd">interne</font> fin'
        _js(self.pane, f"MD.editor.cm.replaceRange({source!r}, {{line: MD.editor.cm.lineCount() - 1, ch: 0}}); "
                       "MD.editor.cm.focus(); MD.editor.cm.setCursor(MD.editor.cm.lineCount() - 1, 20); true")
        line = LINE % "Texte"
        self.assertTrue(_until(self.pane, f"!!{line}.querySelector('.md-inline-font-color')"))
        visible = _json(self.pane, f"""(() => {{ const l = {line}, s = l.querySelector('.md-inline-font-color');
            return {{color: getComputedStyle(s).color, tags: l.textContent.includes('<font color=')}}; }})()""")
        self.assertEqual(visible["color"], "rgb(51, 86, 189)")
        self.assertTrue(visible["tags"], "le code source doit rester visible sous le curseur")
        _js(self.pane, "MD.editor.cm.setCursor(0, 0); true")
        hidden = _json(self.pane, f"""(() => {{ const l = {line}, s = l.querySelector('.md-inline-font-color');
            return {{color: getComputedStyle(s).color, tags: l.textContent.includes('<font color=')}}; }})()""")
        self.assertEqual(hidden["color"], "rgb(51, 86, 189)")
        self.assertFalse(hidden["tags"], "les balises doivent se masquer hors de la zone active")

    def test_typing_in_a_long_note_stays_fast(self):
        """Note representative (listes imbriquees, citations, taches, titres, tableaux) repetee : frappe dans une
        liste, edition visuelle refaite a chaque touche (comme a chaque image), temps mesures dans la page."""
        table = "| a | b | c |\n| --- | :-: | --: |\n" + "".join(f"| l{i} | [[n{i}]] | <b>{i}</b> |\n" for i in range(15))
        big = (NOTE + "\n" + table + "\n") * 25
        self.path.write_text(big, encoding="utf-8", newline="")
        self.pane.buffers.clear()
        _js(self.pane, "MD.editor.docs.clear(); true")
        self.assertTrue(self.pane.open(self.path))
        self.assertTrue(_until(self.pane, "MD.editor.cm.lineCount() > 900"))
        line = big.split("\n").index("\t- niveau 2", 500)
        timing = _json(self.pane, f"""(() => {{ const cm = MD.editor.cm, lp = MD.editor.lp; cm.focus();
            cm.setCursor({line}, 11); cm.scrollIntoView(null, 200); lp.refresh();
            const out = [];
            for (let i = 0; i < 40; i++) {{ const t0 = performance.now(); cm.replaceSelection('x', null, '+input');
              lp.refresh(); out.push(performance.now() - t0); }}
            out.sort((a, b) => a - b);
            const t1 = performance.now(); MD.editor.styleChanged(); const restyle = performance.now() - t1;
            return {{median: out[20], max: out[39], restyle}}; }})()""")
        self.assertLess(timing["median"], 12, timing)
        self.assertIn("niveau 2" + "x" * 40, _js(self.pane, "MD.editor.getText()"))


if __name__ == "__main__":
    unittest.main()

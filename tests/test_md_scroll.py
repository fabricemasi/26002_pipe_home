"""Defilement du module Markdown / code (mdeditor) : un seul scroller natif par mode, exactement de la taille de la zone
visible ; hauteur des lignes independante de la position du defilement (tout le document est decore, estimations
justes) ; rien ne bouge a l'ecran sans geste (travail de fond, images, redimensionnement) ; clavier, frappe en bas
d'une longue note, bascule lecture / edition, nouveau rendu de la lecture.

Mesures en conditions reelles (vraie fenetre, molette, pave tactile, glisser de la barre) : tests/_probe_md_scroll.py."""
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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --log-level=3")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
APP = QApplication.instance() or QApplication([])

import mdeditor.pane as md_pane
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


def _jsj(pane, code):
    value = _js(pane, code)
    return json.loads(value) if isinstance(value, str) else value


def _until(pane, code, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _js(pane, code):
            return True
        settle(0.03)
    return False


# Ligne a 40 % de la hauteur de la vue d'edition : son noeud et sa place a l'ecran (verite du DOM).
PICK = """(() => {
  const cm = MD.editor.cm, r = cm.getScrollerElement().getBoundingClientRect();
  const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height * 0.4);
  for (const v of cm.display.view) if (v.node && v.node.contains(el)) { window.__ref = v.line; break; }
  return true;
})()"""
REF_TOP = """(() => {
  for (const v of MD.editor.cm.display.view) if (v.line === window.__ref) return v.node.getBoundingClientRect().top;
  return null;
})()"""
SWEPT = "MD.editor.lp.state.sweepLeft === 0 && MD.editor.lp.state.estimateLeft === 0"


@unittest.skipUnless(md_pane.markdown_preview.available(), "markdown-it-py absent")
class ScrollTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
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
        self.addCleanup(self.pane.buffers.clear)
        self.pane.resize(1000, 700)

    def open(self, path, mode="edit"):
        self.assertTrue(self.pane.open(path))
        self.assertTrue(_until(self.pane, f"!!(MD.state.current && MD.state.current.path === {str(path)!r})"))
        _js(self.pane, f"MD.setMode({mode!r}); true")
        settle(0.1)

    def long_note(self, chunks=30, name="longue.md"):
        image = QImage(600, 300, QImage.Format_RGB32)
        image.fill(QColor("#3a7bd5"))
        image.save(str(self.dir / "image.png"))
        text = ("Un paragraphe assez long pour etre replie sur plusieurs lignes, avec du **gras** et un "
                "[lien](https://exemple.org/un/chemin/tres/long/qui/prend/de/la/place?x=1). ") * 2
        chunk = (f"# Partie\n\n{text}\n\n- un\n- deux\n  - trois\n\n> [!note] Callout\n> contenu\n\n"
                 "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n```python\nprint(1)\n```\n\n![[image.png]]\n\n")
        note = self.dir / name
        note.write_text(chunk * chunks, encoding="utf-8")
        return note

    def test_edit_scroller_is_exactly_the_visible_area(self):
        self.open(self.long_note())
        geo = _jsj(self.pane, """JSON.stringify((() => {
            const cm = MD.editor.cm, s = cm.getScrollerElement(), r = s.getBoundingClientRect();
            const host = document.getElementById('md-edit').getBoundingClientRect();
            const mirrors = [...document.querySelectorAll('.md-edit .CodeMirror-vscrollbar, .md-edit .CodeMirror-hscrollbar')]
                .filter((e) => getComputedStyle(e).display !== 'none').length;
            const scrollers = [...document.querySelectorAll('#md-edit *')].filter((e) => {
                const o = getComputedStyle(e).overflowY;
                return (o === 'auto' || o === 'scroll') && e.scrollHeight > e.clientHeight + 1;
            }).length;
            return { top: r.top - host.top, bottom: host.bottom - r.bottom, client: s.clientHeight, height: r.height,
                     bar: s.offsetWidth - s.clientWidth, mirrors, scrollers, scrollable: s.scrollHeight > s.clientHeight };
        })())""")
        self.assertAlmostEqual(geo["top"], 0, delta=1)
        self.assertAlmostEqual(geo["bottom"], 0, delta=1)              # rien du scroller (ni de sa barre) sous le cadre
        self.assertAlmostEqual(geo["client"], geo["height"], delta=1)  # pas de barre horizontale, pas de marge cachee
        self.assertGreater(geo["bar"], 0)                              # la barre native est la, visible
        self.assertEqual(geo["mirrors"], 0)                            # aucune barre miroir de CodeMirror
        self.assertEqual(geo["scrollers"], 1)                          # une seule zone defilante
        self.assertTrue(geo["scrollable"])

    def test_whole_note_is_decorated_and_estimated_without_scrolling(self):
        self.open(self.long_note(60))
        self.assertTrue(_until(self.pane, SWEPT, 20))
        far = _jsj(self.pane, """JSON.stringify((() => {
            const cm = MD.editor.cm;
            let image = -1;
            for (let i = cm.lineCount() - 1; i >= 0; i--) if (cm.getLine(i).startsWith('![[')) { image = i; break; }
            const marked = cm.findMarksAt({ line: image, ch: 1 }).some((m) => m.replacedWith);
            const rendered = image >= cm.display.viewFrom && image < cm.display.viewTo;
            return { marked, rendered, blocks: MD.editor.lp.state.blockMarks.size, tables: MD.editor.lp.state.tableMarks.size };
        })())""")
        self.assertFalse(far["rendered"])                  # jamais affichee...
        self.assertTrue(far["marked"])                     # ... et pourtant deja decoree (sa hauteur n'en dependra pas)
        self.assertEqual(far["blocks"], 60)
        self.assertEqual(far["tables"], 60)
        heights = _jsj(self.pane, """JSON.stringify((() => {
            const cm = MD.editor.cm, estimated = cm.getDoc().height;
            cm.setOption('viewportMargin', Infinity);
            cm.getScrollerElement().scrollHeight;
            const measured = cm.getDoc().height;
            cm.setOption('viewportMargin', 10);
            return [estimated, measured];
        })())""")
        self.assertLess(abs(heights[0] - heights[1]) / heights[1], 0.03)    # barre de defilement juste

    def test_background_work_never_moves_the_visible_text(self):
        note = self.long_note(60)
        self.open(note)
        # Au milieu, tout de suite (passage de fond pas fini) ; puis estimations jetees et reposees.
        _js(self.pane, "(() => { const s = MD.editor.cm.getScrollerElement(); s.scrollTop = (s.scrollHeight - s.clientHeight) / 2; return true; })()")
        settle(0.1)
        _js(self.pane, PICK)
        before = _js(self.pane, REF_TOP)
        self.assertIsNotNone(before)
        self.assertTrue(_until(self.pane, SWEPT, 20))
        settle(0.6)
        self.assertAlmostEqual(_js(self.pane, REF_TOP), before, delta=1.5)
        _js(self.pane, "MD.editor.forgetHeights(); MD.editor.lp.sweep(); true")
        settle(0.2)
        self.assertTrue(_until(self.pane, SWEPT, 20))
        settle(0.6)
        self.assertAlmostEqual(_js(self.pane, REF_TOP), before, delta=1.5)

    def test_resize_keeps_the_line_at_the_top_of_the_view(self):
        self.open(self.long_note(40))
        self.assertTrue(_until(self.pane, SWEPT, 20))
        _js(self.pane, "(() => { const s = MD.editor.cm.getScrollerElement(); s.scrollTop = (s.scrollHeight - s.clientHeight) * .4; return true; })()")
        settle(0.2)
        _js(self.pane, """(() => { const cm = MD.editor.cm, top = cm.getScrollerElement().scrollTop;
            window.__ref = cm.getLineHandle(cm.lineAtHeight(top + 2, 'local')); return true; })()""")
        before = _js(self.pane, REF_TOP)
        self.pane.resize(700, 600)
        settle(0.6)
        narrow = _js(self.pane, REF_TOP)
        self.pane.resize(1000, 700)
        settle(0.6)
        back = _js(self.pane, REF_TOP)
        self.assertIsNotNone(narrow)
        self.assertAlmostEqual(narrow, before, delta=40)        # meme ligne en haut (repliee autrement : a peu pres)
        self.assertAlmostEqual(back, before, delta=3)

    def test_page_keys_move_by_a_page_and_keep_the_cursor_visible(self):
        self.open(self.long_note(40))
        self.assertTrue(_until(self.pane, SWEPT, 20))
        result = _jsj(self.pane, """JSON.stringify((() => {
            const cm = MD.editor.cm, s = cm.getScrollerElement(), out = [];
            cm.focus(); cm.setCursor({ line: 0, ch: 0 }); cm.scrollTo(null, 0);
            const visible = () => { const c = cm.cursorCoords(null, 'local');
                return c.top >= s.scrollTop - 1 && c.bottom <= s.scrollTop + s.clientHeight + 1; };
            for (const cmd of ['goPageDown', 'goPageDown', 'goPageUp', 'goDocEnd', 'goDocStart']) {
                const before = s.scrollTop;
                cm.execCommand(cmd);
                out.push([cmd, s.scrollTop - before, visible()]);
            }
            return { steps: out, page: s.clientHeight };
        })())""")
        page = result["page"]
        for cmd, moved, visible in result["steps"]:
            self.assertTrue(visible, cmd)
        self.assertGreater(result["steps"][0][1], page * 0.6)
        self.assertLess(result["steps"][0][1], page * 1.1)

    def test_typing_at_the_end_of_a_long_note_keeps_the_cursor_visible(self):
        self.open(self.long_note(40))
        _js(self.pane, "(() => { const cm = MD.editor.cm; cm.focus(); cm.setCursor({ line: cm.lastLine(), ch: 0 }); return true; })()")
        settle(0.2)
        hidden = 0
        for i in range(24):
            _js(self.pane, "MD.editor.cm.replaceSelection('mot '); " + ("MD.editor.cm.execCommand('newlineAndIndent'); " if i % 6 == 5 else "") + "true")
            settle(0.03)
            ok = _js(self.pane, """(() => { const cm = MD.editor.cm, s = cm.getScrollerElement(), c = cm.cursorCoords(null, 'local');
                return c.top >= s.scrollTop - 1 && c.bottom <= s.scrollTop + s.clientHeight + 1; })()""")
            hidden += 0 if ok else 1
        self.assertEqual(hidden, 0)

    def test_image_height_is_reserved_before_it_is_decoded(self):
        self.open(self.long_note(3))
        self.assertTrue(_until(self.pane, "!!document.querySelector('.md-edit .md-image img[height]')"))
        size = _jsj(self.pane, """JSON.stringify((() => { const img = document.querySelector('.md-edit .md-image img[height]');
            return [img.getAttribute('width'), img.getAttribute('height')]; })())""")
        self.assertEqual(size, ["600", "300"])

    def test_mode_switch_keeps_the_reading_position(self):
        """Les deux modes ont chacun leur scroller natif ; la bascule garde la position (proportion)."""
        note = self.dir / "scroll.md"
        note.write_text("# Titre\n\n" + ("Une ligne suffisamment longue pour le défilement.\n" * 900), encoding="utf-8")
        self.open(note)
        self.assertTrue(_until(self.pane, "MD.editor.cm.getScrollInfo().height > MD.editor.cm.getScrollInfo().clientHeight"))
        edit = _jsj(self.pane, """JSON.stringify((() => {
            const cm = MD.editor.cm, info = cm.getScrollInfo();
            cm.scrollTo(null, (info.height - info.clientHeight) * .63);
            const now = cm.getScrollInfo();
            return [now.top, now.height - now.clientHeight];
        })())""")
        self.assertGreater(edit[0], 0)
        self.assertLessEqual(edit[0], edit[1])
        _js(self.pane, "MD.setMode('reading'); true")
        self.assertTrue(_until(self.pane, "document.querySelector('#md-read-body').textContent.includes('défilement')"))
        settle(0.1)
        reading = _jsj(self.pane, """JSON.stringify((() => {
            const read = document.getElementById('md-read');
            const max = read.scrollHeight - read.clientHeight;
            return [read.scrollTop, max, read.scrollTop / max];
        })())""")
        self.assertGreater(reading[1], 0)
        self.assertAlmostEqual(reading[2], .63, delta=.08)
        _js(self.pane, "MD.setMode('edit'); true")
        self.assertTrue(_until(self.pane, "MD.state.mode === 'edit' && MD.editor.cm.getScrollInfo().top > 0"))
        restored = _jsj(self.pane, """JSON.stringify((() => {
            const info = MD.editor.cm.getScrollInfo();
            return info.top / (info.height - info.clientHeight);
        })())""")
        self.assertAlmostEqual(restored, .63, delta=.08)

    def test_reading_rerender_does_not_return_to_the_top(self):
        note = self.dir / "rerender.md"
        note.write_text("# Titre\n\n" + ("Contenu long.\n" * 700), encoding="utf-8")
        self.open(note, "reading")
        self.assertTrue(_until(self.pane, "document.getElementById('md-read').scrollHeight > document.getElementById('md-read').clientHeight"))
        _js(self.pane, """(() => {
            const read = document.getElementById('md-read');
            read.scrollTop = (read.scrollHeight - read.clientHeight) * .55;
            window.__top = read.scrollTop;
            MD.state.rendered = null;
            MD.setMode('reading');
            return true;
        })()""")
        self.assertTrue(_until(self.pane, "MD.state.rendered === MD.editor.getText()"))
        self.assertAlmostEqual(_js(self.pane, "document.getElementById('md-read').scrollTop - window.__top"), 0, delta=1)

    def test_reading_has_one_native_scroller_with_centered_text(self):
        self.open(self.long_note(10), "reading")
        self.assertTrue(_until(self.pane, "document.querySelector('#md-read-body h1') !== null"))
        geo = _jsj(self.pane, """JSON.stringify((() => {
            const read = document.getElementById('md-read'), r = read.getBoundingClientRect();
            const body = document.querySelector('#md-read .md-sizer').getBoundingClientRect();
            const scrollers = [...document.querySelectorAll('#md-read, #md-read *')].filter((e) => {
                const o = getComputedStyle(e).overflowY;
                return (o === 'auto' || o === 'scroll') && e.scrollHeight > e.clientHeight + 1;
            }).length;
            return { scrollers, left: body.left - r.left, right: r.right - body.right };
        })())""")
        self.assertEqual(geo["scrollers"], 1)
        self.assertAlmostEqual(geo["left"], geo["right"], delta=1)

    def test_ctrl_wheel_still_zooms_code_files(self):
        code = self.dir / "script.py"
        code.write_text("print(1)\n" * 50, encoding="utf-8")
        before = int(self.settings.get("md_code_font_zoom") or 0)
        self.addCleanup(self.settings.__setitem__, "md_code_font_zoom", before)
        self.open(code)
        _js(self.pane, """(() => { const t = MD.editor.cm.getScrollerElement();
            t.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, bubbles: true, cancelable: true }));
            return true; })()""")
        settle(0.3)
        self.assertEqual(int(self.settings.get("md_code_font_zoom") or 0), before + 1)


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

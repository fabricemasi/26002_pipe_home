"""Sonde du module Markdown / code (mdeditor) : charge la page, ouvre une note et un fichier de code, mesure.

    python tests/_probe_md_editor.py [note.md] [code.py]

Sans argument : fichiers de demonstration dans un dossier temporaire. Affiche les erreurs JavaScript, les temps
(chargement de la page, ouverture, rendu de lecture, frappe) et l'etat de la page. Fenetre native hors ecran
(QtWebEngine ne dessine pas en offscreen) ; `SHOT=chemin.png` enregistre une capture de la vue ; `CSS=feuille.css`
la charge comme Reglages > Markdown > CSS (travailler sur des COPIES)."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QEventLoop, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
APP = QApplication.instance() or QApplication(sys.argv)

import settings_store  # noqa: E402
import mdeditor.pane as md_pane  # noqa: E402

SETTINGS = dict(settings_store.DEFAULT_SETTINGS)
SETTINGS["md_css_path"] = os.environ.get("CSS", "")          # `CSS=feuille.css` : feuille de Reglages > Markdown > CSS
md_pane.HOOKS["settings"] = lambda: SETTINGS
md_pane.HOOKS["save_state"] = lambda k, v: SETTINGS.__setitem__(k, v)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()


def js(pane, code, timeout=3000):
    loop, out = QEventLoop(), {}

    def got(value):
        out["v"] = value
        loop.quit()
    pane.view.page().runJavaScript(code, got)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    return out.get("v")


def until(pane, code, timeout=8000):
    end = time.monotonic() + timeout / 1000
    while time.monotonic() < end:
        if js(pane, code):
            return True
        wait(30)
    return False


def main():
    folder = Path(tempfile.mkdtemp())
    note = Path(sys.argv[1]) if len(sys.argv) > 1 else folder / "note.md"
    code = Path(sys.argv[2]) if len(sys.argv) > 2 else folder / "script.py"
    if len(sys.argv) <= 1:
        (folder / "img").mkdir()
        from PySide6.QtGui import QImage, QColor
        image = QImage(240, 120, QImage.Format_RGB32)
        image.fill(QColor("#3a7bd5"))
        image.save(str(folder / "img" / "bleu.png"))
        note.write_text("# Titre\n\nUn **gras**, un *italique*, ==fluo== et `code`.\n\n- un\n- deux\n  - trois\n"
                        "- [ ] tache\n- [x] faite\n\n> citation\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
                        "```python\ndef f(x):\n    return x  # commentaire\n```\n\n![[bleu.png|200]]\n"
                        "![alt](img/bleu.png)\n\n---\n\n[[Autre]] https://exemple.org\n" * 3, encoding="utf-8")
        code.write_text("import os\n\nclass A:\n    def f(self):\n        return 'x'  # c\n" * 50, encoding="utf-8")
    pane = md_pane.instance()
    pane.resize(1400, 900)
    pane.move(-3000, 0)
    pane.setWindowFlag(Qt.Tool, True)
    pane.show()
    t0 = time.perf_counter()
    if not until(pane, "!!(window.MD && MD.bridge && MD.editor)", 15000):
        print("page non prete", pane.view.page().console)
        return 1
    print(f"page prete : {(time.perf_counter() - t0) * 1000:.0f} ms")
    t0 = time.perf_counter()
    pane.open(note)
    ok = until(pane, f"!!(MD.state.current && MD.state.current.path === {str(note)!r})")
    print(f"note ouverte : {ok} {(time.perf_counter() - t0) * 1000:.0f} ms")
    wait(400)
    print("lignes :", js(pane, "MD.editor.cm.lineCount()"), "toolbar :",
          js(pane, "document.getElementById('md-toolbar').classList.contains('is-shown')"),
          "boutons :", js(pane, "document.querySelectorAll('#md-toolbar .md-tool').length"))
    print("classes h1 :", js(pane, "(document.querySelector('pre.md-h1')||{}).className"))
    print("images edition :", js(pane, "JSON.stringify([...document.querySelectorAll('.md-edit .md-image img')].map(i=>i.naturalWidth))"))
    t0 = time.perf_counter()
    js(pane, "MD.setMode('reading')")
    until(pane, "document.querySelector('#md-read-body h1') !== null")
    print(f"lecture : {(time.perf_counter() - t0) * 1000:.0f} ms ; code colore :",
          js(pane, "document.querySelectorAll('#md-read-body pre code span.cm-keyword').length"),
          "images :", js(pane, "JSON.stringify([...document.querySelectorAll('#md-read-body img')].map(i=>i.naturalWidth))"))
    js(pane, "MD.setMode('edit')")
    wait(200)
    # Frappe : 40 caracteres a la fin de la 1re ligne.
    js(pane, "MD.editor.cm.focus(); MD.editor.cm.setCursor({line: 2, ch: 0}); MD.metrics.take(); true")
    for _ in range(40):
        js(pane, "MD.editor.cm.replaceSelection('a')")
    wait(300)
    keys = js(pane, "(MD.metrics.data.lp||[]).slice(-40)") or []
    if keys:
        keys = sorted(keys)
        print(f"edition visuelle par frappe : mediane {keys[len(keys) // 2]:.2f} ms, max {keys[-1]:.2f} ms")
    pane.flush()
    print("enregistre :", "aaaa" in note.read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    pane.open(code)
    ok = until(pane, f"!!(MD.state.current && MD.state.current.path === {str(code)!r})")
    print(f"code ouvert : {ok} {(time.perf_counter() - t0) * 1000:.0f} ms ; mode :",
          js(pane, "MD.editor.cm.getOption('mode')"), "mots-cles :",
          js(pane, "document.querySelectorAll('.md-edit .cm-keyword').length"),
          "numeros :", js(pane, "MD.editor.cm.getOption('lineNumbers')"))
    t0 = time.perf_counter()
    pane.apply_settings({**SETTINGS, "md_h1_font_color": "#ffff0000"}, {"md_h1_font_color"})
    until(pane, "getComputedStyle(document.documentElement).getPropertyValue('--md-h1-color').includes('ff0000')")
    print(f"reglage applique : {(time.perf_counter() - t0) * 1000:.0f} ms")
    if os.environ.get("SHOT"):
        pane.open(note)
        wait(800)
        pane.view.grab().save(os.environ["SHOT"])
        js(pane, "MD.setMode('reading')")
        wait(600)
        pane.view.grab().save(os.environ["SHOT"].replace(".png", "_lecture.png"))
    errors = [c for c in pane.view.page().console if c[0] >= 2]
    print("erreurs JS :", errors or "aucune")
    return 0


if __name__ == "__main__":
    sys.exit(main())

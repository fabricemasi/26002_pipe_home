"""Sonde visuelle du module Markdown pour la comparaison avec Obsidian : captures de l'edition (curseur hors de tout,
dans la citation, dans une cellule de tableau) et de la lecture d'une note, avec une feuille CSS.

    CSS=<copie>.css python tests/_probe_md_compare.py <note.md> <dossier des captures>

Toujours sur des COPIES (la note est recopiee dans un dossier temporaire). Fenetre native hors ecran (QtWebEngine ne
dessine pas en offscreen). Affiche aussi les positions mesurees (puces, textes, cases, citations) pour comparer au
pixel avec des captures d'Obsidian."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
from _probe_md_editor import APP, SETTINGS, js, md_pane, until, wait  # noqa: E402,F401


def main():
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp())
    note = folder / source.name
    shutil.copyfile(source, note)
    pane = md_pane.instance()
    pane.resize(int(os.environ.get("W", 900)), int(os.environ.get("H", 1100)))
    pane.move(-3000, 0)
    from PySide6.QtCore import Qt
    pane.setWindowFlag(Qt.Tool, True)
    pane.show()
    if not until(pane, "!!(window.MD && MD.bridge && MD.editor)", 15000):
        print("page non prete")
        return 1
    pane.open(note)
    until(pane, f"!!(MD.state.current && MD.state.current.path === {str(note)!r})")
    js(pane, "MD.setMode('edit'); true")
    wait(600)
    last = js(pane, "MD.editor.cm.lastLine()")
    js(pane, f"MD.editor.cm.focus(); MD.editor.cm.setCursor({last}, 0); true")
    wait(500)
    pane.view.grab().save(str(out / "edition.png"))
    print("mesures :", json.dumps(json.loads(js(pane, """JSON.stringify((() => {
        const r = (el) => el ? Math.round(el.getBoundingClientRect().left) : null;
        const lines = [...document.querySelectorAll('.md-edit pre.CodeMirror-line')];
        const find = (t) => lines.find((l) => l.textContent.includes(t));
        const text = (t) => { const l = find(t); if (!l) return null; const w = document.createTreeWalker(l, NodeFilter.SHOW_TEXT);
          let n; while ((n = w.nextNode())) { const i = n.data.indexOf(t); if (i >= 0) { const g = document.createRange();
          g.setStart(n, i); g.setEnd(n, i + 1); return Math.round(g.getBoundingClientRect().left); } } return null; };
        const bullet = (t) => { const l = find(t); const b = l && l.querySelector('.list-bullet');
          if (!b) return null; const s = getComputedStyle(b, '::before'); return [r(b), s.content, s.fontSize, s.color]; };
        return { paragraphe: text('je veux'), citation: text('Sitation'), puce1: bullet('liste a puce 1'),
          texte1: text('liste a puce 1'), puce2: bullet('test interligne 1'), texte2: text('test interligne 1'),
          case: r(document.querySelector('.md-edit .md-checkbox')), coche: text('Coche'),
          titre1: text('Titre 1'), surligne: (() => { const e = document.querySelector('.md-edit .cm-highlight');
            if (!e) return null; const b = e.getBoundingClientRect(); const s = getComputedStyle(e);
            return [Math.round(b.height), s.backgroundColor, s.color]; })(),
          tableau: !!document.querySelector('.md-edit .cm-table-widget table') };
    })())""")), ensure_ascii=False))
    js(pane, "MD.editor.cm.setCursor(0, 3); true")
    wait(400)
    pane.view.grab().save(str(out / "edition_citation.png"))
    js(pane, "(() => { const w = [...MD.editor.lp.state.tableMarks.values()][0]; if (w) w.widget.activate(0, 1, 12); return true; })()")
    wait(500)
    pane.view.grab().save(str(out / "edition_tableau.png"))
    js(pane, "MD.setMode('reading'); true")
    wait(800)
    pane.view.grab().save(str(out / "lecture.png"))
    errors = [c for c in pane.view.page().console if c[0] >= 2]
    print("erreurs JS :", errors or "aucune")
    shutil.rmtree(folder, True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

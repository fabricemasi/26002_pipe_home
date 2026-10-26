"""Sonde du DEFILEMENT du module Markdown / code (mdeditor) : vraie fenetre QtWebEngine, vrais evenements Qt.

    python tests/_probe_md_scroll.py [note.md]

Sans argument : une longue note de demonstration (titres, paragraphes longs, listes, citations, callouts, tableaux,
blocs de code, images avec / sans taille, liens a longues adresses ; ~2 000 lignes) dans un dossier temporaire.
`LINES=n` change sa longueur, `MODE=edit|reading|both` (both par defaut), `NET=\\\\127.0.0.1\\C$\\...` copie la
note sur un partage avant de l'ouvrir, `DEBUG=1` detaille ce qui a fait bouger le contenu (operations de l'edition
visuelle, rendus de CodeMirror, hauteurs changees).

Mesures (« saut » = le contenu bouge a l'ecran d'autre chose que le defilement, ou le defilement bouge sans geste) :
  - geometrie : le scroller est-il exactement la zone visible (barre entiere, rien de rogne) ;
  - molette (crans de 120, rapides), pave tactile (pixelDelta + phases) : sauts, sens, images > 33 ms ;
  - positions posees (10 % … 90 %) puis 600 ms sans geste : derive ;
  - glisser du curseur de la barre (vrai clic sur la barre), clic dans la piste ;
  - clavier : Page suivante / precedente, Fin, Debut (curseur visible) ; frappe en bas d'une longue note ;
  - redimensionnement ; bascule lecture / edition (position gardee).
Fenetre native hors ecran (QtWebEngine ne dessine pas en offscreen)."""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, QSize, QTimer, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
APP = QApplication.instance() or QApplication(sys.argv)

import settings_store  # noqa: E402
import mdeditor.pane as md_pane  # noqa: E402

SETTINGS = dict(settings_store.DEFAULT_SETTINGS)
SETTINGS["md_css_path"] = os.environ.get("CSS", "")
md_pane.HOOKS["settings"] = lambda: SETTINGS
md_pane.HOOKS["save_state"] = lambda k, v: SETTINGS.__setitem__(k, v)

# Enregistreur dans la page : a chaque image, position du defilement et place a l'ecran de l'element sous un point
# fixe (verite du DOM, pas le modele de CodeMirror). Pour chaque image : « recul » = le contenu bouge a l'ecran a
# CONTRE-sens du geste (ou bouge sans geste) ; « recalage » = la position de la barre change sans que le contenu
# suive (CodeMirror compense une hauteur mesuree : le contenu reste en place, le curseur de la barre bouge).
RECORDER = r"""
(() => {
  const P = window.__probe = window.__probe || {};
  P.scroller = () => MD.state.mode === "reading" ? document.getElementById("md-read") : MD.editor.cm.getScrollerElement();
  P.pick = () => {
    const s = P.scroller(), r = s.getBoundingClientRect();
    const el = document.elementFromPoint(r.left + r.width * 0.45, r.top + r.height * 0.42);
    if (!el || !s.contains(el)) return null;
    if (MD.state.mode !== "reading") {
      for (const v of MD.editor.cm.display.view) if (v.node && v.node.contains(el)) return { line: v.line, node: v.node };
      return null;
    }
    return { node: el };
  };
  P.nodeOf = (ref) => {
    if (ref.node && ref.node.isConnected) return ref.node;
    if (ref.line) for (const v of MD.editor.cm.display.view) if (v.line === ref.line) return v.node;
    return null;
  };
  P.start = (dir) => {
    P.frames = []; P.jumps = []; P.reverse = []; P.events = []; P.dir = dir || 0; P.running = true;
    let prev = null, last = performance.now();
    const tick = () => {
      if (!P.running) return;
      const now = performance.now(), s = P.scroller(), st = s.scrollTop;
      if (prev) {
        const node = P.nodeOf(prev.ref);
        if (node) {
          const top = node.getBoundingClientRect().top;
          const moved = top - prev.top, jump = moved + (st - prev.st);
          if (Math.abs(jump) > 1.5) P.jumps.push(Math.round(jump));
          if (P.dir ? moved * P.dir > 1.5 : Math.abs(moved) > 1.5) {
            P.reverse.push(Math.round(moved));
            if (P.debug) P.events.push(["CONTENU", Math.round(now), Math.round(moved), prev.ref.line ? prev.ref.line.lineNo() : null]);
          }
        }
      }
      P.frames.push([Math.round(now - last), Math.round(st)]);
      last = now;
      const ref = P.pick();
      prev = ref ? { ref, top: P.nodeOf(ref).getBoundingClientRect().top, st } : null;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    return true;
  };
  P.stop = () => {
    P.running = false;
    const f = P.frames || [], d = f.slice(1).map((x) => x[0]);
    return JSON.stringify({ frames: f.length, slow: d.filter((x) => x > 33).length, worst: Math.max(0, ...d),
      jumps: P.jumps, reverse: P.reverse, first: f.length ? f[0][1] : 0, lastSt: f.length ? f[f.length - 1][1] : 0,
      backwards: (() => { let n = 0; for (let i = 1; i < f.length; i++) if (f[i][1] < f[i - 1][1] - 1) n++; return n; })(),
      forwards: (() => { let n = 0; for (let i = 1; i < f.length; i++) if (f[i][1] > f[i - 1][1] + 1) n++; return n; })() });
  };
  P.geometry = () => {
    const s = P.scroller(), host = MD.state.mode === "reading" ? s : document.getElementById("md-edit");
    const r = s.getBoundingClientRect(), h = host.getBoundingClientRect();
    // Ce qui est vraiment visible du scroller : coupe par ses parents (overflow hidden).
    let vis = { top: r.top, bottom: r.bottom, right: r.right };
    for (let p = s.parentElement; p; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (cs.overflow !== "visible" || cs.overflowY !== "visible") {
        const q = p.getBoundingClientRect();
        vis = { top: Math.max(vis.top, q.top), bottom: Math.min(vis.bottom, q.bottom), right: Math.min(vis.right, q.right) };
      }
    }
    return JSON.stringify({ scroller: [Math.round(r.top), Math.round(r.bottom), Math.round(r.right)],
      visible: [Math.round(vis.top), Math.round(vis.bottom), Math.round(vis.right)],
      host: [Math.round(h.top), Math.round(h.bottom), Math.round(h.right)],
      client: [s.clientWidth, s.clientHeight], scroll: [s.scrollTop, s.scrollHeight],
      bar: s.offsetWidth - s.clientWidth });
  };
  P.cursorVisible = () => {
    const cm = MD.editor.cm, c = cm.cursorCoords(null, "window"), s = cm.getScrollerElement().getBoundingClientRect();
    const host = document.getElementById("md-edit").getBoundingClientRect();
    const bottom = Math.min(s.bottom, host.bottom), top = Math.max(s.top, host.top);
    return JSON.stringify({ ok: c.top >= top - 1 && c.bottom <= bottom + 1, cursor: [Math.round(c.top), Math.round(c.bottom)],
      view: [Math.round(top), Math.round(bottom)] });
  };
  // Cout sur le fil de la page de l'edition visuelle (a l'ecran) et du passage de fond.
  if (!P.timed) {
    P.timed = true; P.costs = { lp: [], sweep: [] };
    const lp = MD.editor.lp;
    for (const [name, key] of [["refresh", "lp"], ["sweepSlice", "sweep"]]) {
      const f = lp[name].bind(lp);
      lp[name] = (...a) => { const t = performance.now(); f(...a); const d = performance.now() - t;
        if (d > 0.05) { P.costs[key].push(d); if (P.costs[key].length > 2000) P.costs[key].shift(); } };
    }
  }
  // DEBUG=1 : ce qui touche aux hauteurs pendant l'enregistrement (operations de l'edition visuelle, rendus).
  if (!P.hooked && P.debug) {
    P.hooked = true;
    const lp = MD.editor.lp, cm = MD.editor.cm, s = () => cm.getScrollerElement().scrollTop;
    const heights = () => { const out = new Map(); for (const v of cm.display.view) if (v.line) out.set(v.line, [v.line.height, v.node.getBoundingClientRect().top]); return out; };
    for (const name of ["refresh", "sweepSlice"]) {
      const f = lp[name].bind(lp);
      lp[name] = (...a) => {
        const t = s(), h0 = P.running && heights(); f(...a);
        if (!P.running) return;
        const diffs = [];
        for (const [line, [h, y]] of h0) { const no = line.lineNo(); if (no == null) continue; const n = MD.editor.lineNode(line, true);
          const y1 = n && n.getBoundingClientRect().top; if (Math.abs(line.height - h) > 0.5 || y1 != null && Math.abs(y1 - y) > 0.5) diffs.push([no, Math.round(h), Math.round(line.height), Math.round(y), y1 == null ? null : Math.round(y1)]); }
        P.events.push([name, Math.round(performance.now()), Math.round(t), Math.round(s()), cm.display.viewFrom, Math.round(cm.display.viewOffset), diffs.slice(0, 3), diffs.length]);
      };
    }
    cm.on("update", () => { if (P.running) P.events.push(["update", Math.round(performance.now()), Math.round(s()), cm.display.viewFrom, cm.display.viewTo]); });
    cm.on("scroll", () => { if (P.running) P.events.push(["scroll", Math.round(performance.now()), Math.round(s())]); });
  }
  return true;
})()
"""


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()


def js(pane, code, timeout=4000):
    loop, out = QEventLoop(), {}

    def got(value):
        out["v"] = value
        loop.quit()
    pane.view.page().runJavaScript(code, got)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    return out.get("v")


def jsj(pane, code):
    value = js(pane, code)
    return json.loads(value) if isinstance(value, str) else value


def until(pane, code, timeout=10000):
    end = time.monotonic() + timeout / 1000
    while time.monotonic() < end:
        if js(pane, code):
            return True
        wait(30)
    return False


def target(pane):
    return pane.view.focusProxy() or pane.view


def wheel(pane, pos, dy, pixel=None, phase=Qt.NoScrollPhase):
    w = target(pane)
    glob = w.mapToGlobal(pos)
    ev = QWheelEvent(QPointF(pos), QPointF(glob), QPoint(0, pixel or 0), QPoint(0, dy), Qt.NoButton, Qt.NoModifier,
                     phase, False)
    QApplication.sendEvent(w, ev)


def mouse(pane, kind, pos, buttons=Qt.LeftButton):
    w = target(pane)
    glob = w.mapToGlobal(pos)
    button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
    ev = QMouseEvent(kind, QPointF(pos), QPointF(glob), button, buttons, Qt.NoModifier)
    QApplication.sendEvent(w, ev)


def key(pane, k, text="", modifiers=Qt.NoModifier):
    w = target(pane)
    QApplication.sendEvent(w, QKeyEvent(QEvent.KeyPress, k, modifiers, text))
    QApplication.sendEvent(w, QKeyEvent(QEvent.KeyRelease, k, modifiers, text))


def demo_note(folder: Path, lines: int) -> Path:
    from PySide6.QtGui import QColor, QImage
    (folder / "img").mkdir()
    for name, (w, h, color) in {"grande.png": (900, 520, "#3a7bd5"), "petite.png": (240, 120, "#d53a7b")}.items():
        image = QImage(w, h, QImage.Format_RGB32)
        image.fill(QColor(color))
        image.save(str(folder / "img" / name))
    long = ("Un paragraphe assez long pour etre replie sur plusieurs lignes a l'ecran, avec du **gras**, de "
            "l'*italique*, du `code`, un [lien](https://exemple.org/un/chemin/tres/long/qui/prend/de/la/place/"
            "dans/la/ligne?parametre=valeur&autre=1) et [[Une autre note|un alias]]. ") * 2
    chunk = ["# Partie {n}", "", long, "", "## Sous-partie {n}", "", "- premier element", "- deuxieme element",
             "  - imbrique", "- [ ] tache a faire", "- [x] tache faite", "", "> Une citation qui continue "
             "longtemps pour se replier elle aussi sur plusieurs lignes, a la maniere d'Obsidian.", "",
             "> [!note] Un callout", "> avec du contenu", "> sur deux lignes", "", "| Col A | Col B | Col C |",
             "| --- | --- | --- |", "| 1 | deux | trois |", "| 4 | cinq | six |", "", "```python",
             "def f(x):", "    return x * 2  # commentaire", "```", "", "![[grande.png]]", "",
             "![[petite.png|200]]", "", long, "", "---", ""]
    out, n = [], 0
    while len(out) < lines:
        n += 1
        out += [c.replace("{n}", str(n)) for c in chunk]
    note = folder / "longue.md"
    note.write_text("\n".join(out[:lines]) + "\n", encoding="utf-8")
    return note


def scroller_rect(pane):
    g = jsj(pane, "__probe.geometry()")
    return g


def run_wheel(pane, label, notches, delay, dy=-120):
    rect = jsj(pane, "(() => { const r = __probe.scroller().getBoundingClientRect(); return JSON.stringify([r.left, r.top, r.width, r.height]); })()")
    pos = QPoint(int(rect[0] + rect[2] * 0.45), int(rect[1] + rect[3] * 0.5))
    js(pane, f"__probe.start({1 if dy < 0 else -1})")
    wait(50)
    for _ in range(notches):
        wheel(pane, pos, dy)
        wait(delay)
    wait(450)
    out = jsj(pane, "__probe.stop()")
    print(f"  {label:<34} images {out['frames']:>4}  >33 ms {out['slow']:>3}  pire {out['worst']:>4} ms  "
          f"defilement {out['first']:>6} -> {out['lastSt']:>6}  sens contraire {out['backwards'] if dy < 0 else out['forwards']:>3}  "
          f"RECULS {len(out['reverse'])} {out['reverse'][:6]}  recalages {len(out['jumps'])} {out['jumps'][:6]}")
    return out


def run_touchpad(pane, label, steps, px):
    rect = jsj(pane, "(() => { const r = __probe.scroller().getBoundingClientRect(); return JSON.stringify([r.left, r.top, r.width, r.height]); })()")
    pos = QPoint(int(rect[0] + rect[2] * 0.45), int(rect[1] + rect[3] * 0.5))
    js(pane, "__probe.start(1)")
    wait(50)
    wheel(pane, pos, 0, 0, Qt.ScrollBegin)
    for _ in range(steps):
        wheel(pane, pos, -px * 2, -px, Qt.ScrollUpdate)
        wait(12)
    wheel(pane, pos, 0, 0, Qt.ScrollEnd)
    wait(400)
    out = jsj(pane, "__probe.stop()")
    print(f"  {label:<34} images {out['frames']:>4}  >33 ms {out['slow']:>3}  pire {out['worst']:>4} ms  "
          f"defilement {out['first']:>6} -> {out['lastSt']:>6}  sens contraire {out['backwards']:>3}  "
          f"RECULS {len(out['reverse'])} {out['reverse'][:6]}  recalages {len(out['jumps'])} {out['jumps'][:6]}")


def run_drift(pane):
    worst = []
    for f in (0.1, 0.3, 0.5, 0.7, 0.9, 0.2):
        js(pane, f"(() => {{ const s = __probe.scroller(); s.scrollTop = (s.scrollHeight - s.clientHeight) * {f}; return true; }})()")
        wait(30)
        js(pane, "__probe.start()")
        wait(600)
        out = jsj(pane, "__probe.stop()")
        moved = out["lastSt"] - out["first"]
        worst.append((f, moved, len(out["reverse"]), out["reverse"][:4]))
        if out["reverse"] and os.environ.get("DEBUG"):
            print(f"    {f:.0%} :", jsj(pane, "JSON.stringify(__probe.events)"))
    print("  positions posees, 600 ms sans geste (fraction, derive de la barre px / contenu qui bouge) :",
          "  ".join(f"{f:.0%}:{m:+d}/{n}{j if j else ''}" for f, m, n, j in worst))


def run_drag(pane):
    g = jsj(pane, """(() => { const s = __probe.scroller(), r = s.getBoundingClientRect();
        return JSON.stringify([r.right, r.top, r.height, s.scrollTop, s.scrollHeight, s.clientHeight, s.offsetWidth - s.clientWidth]); })()""")
    right, top, height, st, sh, ch, bar = g
    if bar <= 0:
        # Barre miroir de CodeMirror (si elle existe)
        g2 = jsj(pane, """(() => { const b = document.querySelector('.md-edit .CodeMirror-vscrollbar');
            if (!b || getComputedStyle(b).display === 'none') return null; const r = b.getBoundingClientRect();
            return JSON.stringify([r.right, r.top, r.height, b.scrollTop, b.scrollHeight, b.clientHeight, r.width]); })()""")
        if not g2:
            print("  glisser de la barre : aucune barre trouvee")
            return
        right, top, height, st, sh, ch, bar = g2
    x = int(right - max(2, bar / 2))
    thumb = max(18, height * ch / sh)
    y0 = top + (st / max(1, sh - ch)) * (height - thumb) + thumb / 2
    js(pane, "__probe.start(1)")
    mouse(pane, QEvent.MouseButtonPress, QPoint(x, int(y0)))
    samples = []
    steps = 24
    span = height * 0.55
    for i in range(1, steps + 1):
        mouse(pane, QEvent.MouseMove, QPoint(x, int(y0 + span * i / steps)), Qt.LeftButton)
        wait(25)
        samples.append(js(pane, "__probe.scroller().scrollTop"))
    mouse(pane, QEvent.MouseButtonRelease, QPoint(x, int(y0 + span)), Qt.NoButton)
    after = js(pane, "__probe.scroller().scrollTop")
    out = jsj(pane, "__probe.stop()")
    if out["reverse"] and os.environ.get("DEBUG"):
        events = jsj(pane, "JSON.stringify(__probe.events)")
        for i, e in enumerate(events):
            if e[0] == "CONTENU":
                print("    glisser :", events[max(0, i - 4):i + 1])
    js(pane, "__probe.start(0)")
    wait(600)
    settled = js(pane, "__probe.scroller().scrollTop")
    still = jsj(pane, "__probe.stop()")
    expected = span * (sh - ch) / max(1, height - thumb)
    back = sum(1 for a, b in zip(samples, samples[1:]) if b < a - 1)
    print(f"  glisser du curseur (vers le bas, {span:.0f} px) : defilement {st:.0f} -> {after:.0f} (attendu ~{st + expected:.0f}), "
          f"barre a contre-sens {back}, RECULS {len(out['reverse'])} {out['reverse'][:6]}, recalages {len(out['jumps'])} ; "
          f"apres relache : barre {settled - after:+.0f} px, contenu qui bouge {still['reverse'][:6] or 'jamais'}")


def run_track_click(pane):
    g = jsj(pane, """(() => { const s = __probe.scroller(), r = s.getBoundingClientRect();
        s.scrollTop = 0; return JSON.stringify([r.right, r.top, r.height, s.offsetWidth - s.clientWidth, s.clientHeight]); })()""")
    right, top, height, bar, ch = g
    if bar <= 0:
        print("  clic dans la piste : pas de barre native sur le scroller")
        return
    wait(80)
    x, y = int(right - max(2, bar / 2)), int(top + min(height, 800) * 0.8)
    mouse(pane, QEvent.MouseButtonPress, QPoint(x, y))
    wait(30)
    mouse(pane, QEvent.MouseButtonRelease, QPoint(x, y), Qt.NoButton)
    wait(500)
    st = js(pane, "__probe.scroller().scrollTop")
    print(f"  clic dans la piste sous le curseur : defilement 0 -> {st} (une page ~{ch})")


def run_keys(pane):
    js(pane, "MD.editor.cm.focus(); MD.editor.cm.setCursor({line: 0, ch: 0}); MD.editor.cm.scrollTo(null, 0); true")
    wait(100)
    res = []
    for name, k in (("PageDown", Qt.Key_PageDown), ("PageDown", Qt.Key_PageDown), ("PageUp", Qt.Key_PageUp),
                    ("Ctrl+End", Qt.Key_End), ("Ctrl+Home", Qt.Key_Home)):
        before = js(pane, "__probe.scroller().scrollTop")
        key(pane, k, modifiers=Qt.ControlModifier if name.startswith("Ctrl") else Qt.NoModifier)
        wait(250)
        after = js(pane, "__probe.scroller().scrollTop")
        vis = jsj(pane, "__probe.cursorVisible()")
        res.append(f"{name} {before:.0f}->{after:.0f} curseur {'visible' if vis['ok'] else 'CACHE ' + str(vis)}")
    print("  clavier :", " | ".join(res))


def run_typing_bottom(pane):
    js(pane, "(() => { const cm = MD.editor.cm; cm.focus(); cm.setCursor({line: cm.lastLine(), ch: 0}); return true; })()")
    wait(250)
    js(pane, "__probe.start()")
    tops, hidden = [], 0
    for i in range(30):
        key(pane, Qt.Key_A, "a")
        if i % 10 == 9:
            key(pane, Qt.Key_Return, "\r")
        wait(30)
        vis = jsj(pane, "__probe.cursorVisible()")
        if not vis["ok"]:
            hidden += 1
        tops.append(js(pane, "__probe.scroller().scrollTop"))
    out = jsj(pane, "__probe.stop()")
    back = sum(1 for a, b in zip(tops, tops[1:]) if b < a - 1)
    print(f"  frappe en bas (30 car. + 3 retours) : curseur cache {hidden} fois, defilement {tops[0]:.0f} -> {tops[-1]:.0f}, "
          f"reculs de la barre {back}, images >33 ms {out['slow']}")
    js(pane, "MD.editor.cm.undo(); MD.editor.cm.undo(); MD.editor.cm.undo(); MD.editor.cm.undo(); true")


def run_resize(pane):
    js(pane, "(() => { const s = __probe.scroller(); s.scrollTop = (s.scrollHeight - s.clientHeight) * 0.5; return true; })()")
    wait(200)
    ref = jsj(pane, """(() => { const r = __probe.pick(); __probe._ref = r; if (!r) return null;
        const n = __probe.nodeOf(r); return JSON.stringify([r.line ? r.line.lineNo() : n.textContent.slice(0, 20), Math.round(n.getBoundingClientRect().top)]); })()""")
    size = QSize(pane.size())
    pane.resize(size.width() - 300, size.height() - 120)
    wait(500)
    now = jsj(pane, """(() => { const r = __probe._ref; if (!r) return null; const n = __probe.nodeOf(r);
        return n ? JSON.stringify([n.textContent.slice(0, 40), Math.round(n.getBoundingClientRect().top)]) : null; })()""")
    pane.resize(size)
    wait(500)
    back = jsj(pane, """(() => { const r = __probe._ref; if (!r) return null; const n = __probe.nodeOf(r);
        return n ? JSON.stringify([Math.round(n.getBoundingClientRect().top)]) : null; })()""")
    geo = jsj(pane, "__probe.geometry()")
    print(f"  redimensionnement : ligne de reference {ref and ref[0]} a {ref and ref[1]} px -> {now and now[1]} (plus etroit) -> {back and back[0]} ; "
          f"geometrie {geo}")


def main():
    folder = Path(tempfile.mkdtemp())
    lines = int(os.environ.get("LINES", "2000"))
    note = Path(sys.argv[1]) if len(sys.argv) > 1 else demo_note(folder, lines)
    if os.environ.get("NET"):
        dest = Path(os.environ["NET"]) / ("_probe_scroll_" + note.name)
        shutil.copytree(note.parent, dest.parent / ("_probe_scroll_" + str(os.getpid())), dirs_exist_ok=True)
        note = dest.parent / ("_probe_scroll_" + str(os.getpid())) / note.name
    pane = md_pane.instance()
    pane.resize(1300, 860)
    pane.move(-3000, 0)
    pane.setWindowFlag(Qt.Tool, True)
    pane.show()
    if not until(pane, "!!(window.MD && MD.bridge && MD.editor)", 20000):
        print("page non prete")
        return 1
    t0 = time.perf_counter()
    pane.open(note)
    until(pane, f"!!(MD.state.current && MD.state.current.path === {str(note)!r})")
    print(f"note ouverte ({js(pane, 'MD.editor.cm.lineCount()')} lignes) : {(time.perf_counter() - t0) * 1000:.0f} ms")
    if os.environ.get("DEBUG"):
        js(pane, "(window.__probe = window.__probe || {}).debug = true")
    js(pane, RECORDER)
    mode = os.environ.get("MODE", "both")
    if mode in ("edit", "both"):
        js(pane, "MD.setMode('edit'); true")
        wait(600)
        print("EDITION")
        print("  geometrie :", scroller_rect(pane))
        run_wheel(pane, "molette vers le bas, 40 crans/40 ms", 40, 40)
        run_wheel(pane, "molette vers le haut, 40 crans/40 ms", 40, 40, dy=120)
        run_wheel(pane, "molette rapide bas, 60 crans/8 ms", 60, 8)
        run_wheel(pane, "molette rapide haut, 60 crans/8 ms", 60, 8, dy=120)
        run_touchpad(pane, "pave tactile vers le bas", 80, 18)
        run_drift(pane)
        run_drag(pane)
        run_track_click(pane)
        run_keys(pane)
        run_typing_bottom(pane)
        run_resize(pane)
        for name, label in (("lp", "edition visuelle a l'ecran"), ("sweep", "passage de fond (tranches)")):
            values = sorted(jsj(pane, f"JSON.stringify(__probe.costs.{name})") or [])
            if values:
                print(f"  {label} : {len(values)} passages, mediane {values[len(values) // 2]:.2f} ms, "
                      f"95e centile {values[int(len(values) * .95)]:.1f} ms, max {values[-1]:.1f} ms")
    if mode in ("reading", "both"):
        js(pane, "MD.setMode('reading'); true")
        if not until(pane, "document.querySelector('#md-read-body h1') !== null", 15000):
            print("  lecture non rendue :", js(pane, "document.getElementById('md-notice').textContent"))
        wait(600)
        print("LECTURE")
        print("  geometrie :", scroller_rect(pane))
        run_wheel(pane, "molette vers le bas, 40 crans/40 ms", 40, 40)
        run_wheel(pane, "molette rapide haut, 60 crans/8 ms", 60, 8, dy=120)
        run_touchpad(pane, "pave tactile vers le bas", 80, 18)
        run_drift(pane)
        run_drag(pane)
        run_track_click(pane)
    if mode == "both":
        js(pane, "(() => { const s = __probe.scroller(); s.scrollTop = (s.scrollHeight - s.clientHeight) * 0.6; return true; })()")
        wait(200)
        r0 = js(pane, "(() => { const s = __probe.scroller(); return s.scrollTop / (s.scrollHeight - s.clientHeight); })()")
        js(pane, "MD.setMode('edit'); true")
        wait(500)
        r1 = js(pane, "(() => { const s = __probe.scroller(); return s.scrollTop / (s.scrollHeight - s.clientHeight); })()")
        js(pane, "MD.setMode('reading'); true")
        wait(700)
        r2 = js(pane, "(() => { const s = __probe.scroller(); return s.scrollTop / (s.scrollHeight - s.clientHeight); })()")
        print(f"BASCULE : lecture {r0:.3f} -> edition {r1:.3f} -> lecture {r2:.3f}")
    errors = [c for c in getattr(pane.view.page(), "console", []) if c[0] >= 2]
    print("erreurs JS :", errors or "aucune")
    pane.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Usage : python tests/_probe_v2_params.py [filtre] (racine root_path reelle, rien n'est enregistre).

Audit element par element de la fenetre de reglages v2 (onglet General, sections branchees) : chaque
CONTROLE elementaire (curseur, toggle, liste, couleur, texte) est modifie comme le ferait l'utilisateur,
puis on verifie :
  1. qu'au moins une cle lue par la fenetre change (sinon : controle mort) ;
  2. que l'effet se voit : fenetre principale (sections Colonnes) ou fenetre de reglages elle-meme hors
     du controle modifie (TITRE, Tableaux, Toggles, Sliders) ;
  3. qu'aucune exception n'est levee, et que le retour a la valeur d'origine restaure tout.
`filtre` : prefixes de cles separes par des virgules (ex. "table_,slider_") ; sans filtre, tout (long)."""
import os, sys, traceback
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Sans polices, la plateforme offscreen dessine des carres : police/gras/italique seraient invisibles.
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
sys.path.insert(0, os.getcwd())
from pathlib import Path
from unittest import mock

import numpy as np
from PySide6.QtCore import QElapsedTimer, QPoint, QRect
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QLineEdit

APP = QApplication.instance() or QApplication([])

errors = []
sys.excepthook = lambda t, v, tb: errors.append("".join(traceback.format_exception(t, v, tb)))

import settings_store, browser_core, pipeline_browser as p, app_style
import settings_window_v2 as v2
from settings_widgets import (_MiniSlider, _RatioSliderField, _SelectField, _SliderField, _Toggle,
                              _ToggleStylePicker)
from settings_sections import _CompactAppOrCustomColorField

# Rien ne touche le disque.
NOOP = lambda *a, **k: None
for mod in (settings_store, browser_core, p, v2):
    for name in ("save_settings", "_save_presets", "_save_window_geometry"):
        if hasattr(mod, name):
            setattr(mod, name, NOOP)
v2.AUTOSAVE = False


def pump(ms):
    t = QElapsedTimer(); t.start()
    while t.elapsed() < ms:
        APP.processEvents()


settings = p.load_settings(); p.apply_all_settings(settings)
app_style.apply_style(APP)
w = p.PipelineBrowser(Path(settings["root_path"]))
w._idle_preview_scheduler.timer.stop()
w.setGeometry(10, 10, 3200, 1000); w.show()      # large : aucune colonne hors champ
pump(600)
# Descend de quelques niveaux : colonnes remplies, une ligne selectionnee par colonne.
for _ in range(4):
    cols = [c for c in w.columns if c.isVisible() and c.list.count() > 0]
    if not cols:
        break
    cols[-1].list.setCurrentRow(min(1, cols[-1].list.count() - 1))
    pump(700)
cols = [c for c in w.columns if c.isVisible() and c.list.count() > 0]
if cols:
    cols[-1].list.setFocus()
pump(800)
print("colonnes :", [(c.title if hasattr(c, "title") else "?", c.list.count()) for c in cols])

w.open_settings_v2()
dlg = w._settings_dialog_v2
dlg.resize(1400, 900)
pump(300)
page = dlg.stack.widget(0)
# `filtre` : prefixes de cles separes par des virgules ; on ne deplie que les noeuds qui en contiennent
# (une fenetre moins chargee se restyle bien plus vite).
FILTERS = tuple(f for f in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if f)


def matches(key):
    return not FILTERS or key.startswith(FILTERS)


def node_matches(node):
    specs = v2.CATALOG.get(node.group, []) if node.group else []
    return any(matches(sp.key) for sp in specs) or any(node_matches(c) for c in node.children)


def wanted(lazy):
    return lazy.wired and node_matches(lazy.node)


for node in page.findChildren(v2._LazyNode):
    if wanted(node):
        node.set_collapsed(False)
while True:
    pending = [n for n in page.findChildren(v2._LazyNode) if wanted(n) and n.is_collapsed()]
    if not pending:
        break
    for n in pending:
        n.set_collapsed(False)
pump(500)
inner = page.findChild(v2._NoSqueezeScrollArea).widget()
records = [(s, wd) for s, wd in dlg.stores["General"]["specs"]]
print("lignes branchees :", len(records))


def leaves(widget):
    """Controles elementaires d'une ligne, dans l'ordre d'affichage."""
    roots = [widget, *getattr(widget, "_v2_parts", {}).values()]
    out = []
    for root in roots:
        cands = [root] + root.findChildren(object)
        for c in cands:
            if not hasattr(c, "isWidgetType") or not c.isWidgetType():
                continue
            if isinstance(c, (_MiniSlider, _Toggle, _SelectField, _CompactAppOrCustomColorField, _ToggleStylePicker)):
                pass
            elif isinstance(c, QLineEdit) and not isinstance(c.parent().parent(), (_SliderField, _RatioSliderField)):
                pass
            else:
                continue
            # Les toggles app/sys d'une couleur sont testes aussi (ce sont des controles a part entiere).
            if c not in out:
                out.append(c)
    return out


def describe(c):
    return type(c).__name__


def mutate(c):
    """Modifie `c` comme un utilisateur ; renvoie la fonction de retour arriere."""
    if isinstance(c, _MiniSlider):
        old, lo, hi = c.value(), c._min, c._max
        step = max(1, (hi - lo) // 4)
        new = old + step if old + step <= hi else old - step
        c.setValue(new)
        return lambda: c.setValue(old)
    if isinstance(c, _Toggle):
        old = c.isChecked()
        c.setChecked(not old)
        return lambda: c.setChecked(old)
    if isinstance(c, _SelectField):
        old = c.value()
        opts = [o for o in c._options if o != old]
        pref = [o for o in opts if o in ("Courier New", "Consolas", "Times New Roman")]
        c._select((pref or opts or [old])[0])
        return lambda: c._select(old)
    if isinstance(c, _CompactAppOrCustomColorField):
        old = c._value              # valeur INTERNE ("@slot" ou hex), pas value() (entetes : slot nu)
        c._apply_custom_live("#ff00ff" if old != "#ff00ff" else "#00ff00")
        return lambda: c._apply_custom_live(old)
    if isinstance(c, _ToggleStylePicker):
        old = c.value()
        other = [k for k in c._cards if k != old][0]
        c._select(other)
        return lambda: c._select(old)
    if isinstance(c, QLineEdit):
        old = c.text()
        c.setText(old + "Ab")
        c.editingFinished.emit()
        return lambda: (c.setText(old), c.editingFinished.emit())
    raise TypeError(type(c))


def settle():
    pump(40)
    dlg._flush_live()
    if getattr(w, "_pending_stylesheet_rebuild", False):
        w._flush_stylesheet_rebuild()
    pump(220)            # animations de toggle (~140 ms)


def img(widget):
    return widget.grab().toImage().convertToFormat(QImage.Format_RGB32)


def arr(image):
    ptr = image.constBits()
    return np.frombuffer(ptr, np.uint8, image.sizeInBytes()).reshape(image.height(), image.bytesPerLine()).copy()


def changed_pixels(a, b, mask: QRect | None = None):
    if a.shape != b.shape:
        return -1
    d = (a != b)
    if mask is not None:
        d[max(0, mask.top()):mask.bottom() + 1, max(0, mask.left() * 4):(mask.right() + 1) * 4] = False
    return int(d.any(axis=1).sum())


WINDOW_FAMILIES = ("title_level", "table_", "columns_resizable", "toggle", "slider_")
report = []
for spec, widget in records:
    key = spec if isinstance(spec, str) else spec.key
    if not matches(key):
        continue
    self_look = key.startswith(WINDOW_FAMILIES)
    controls = [widget] if isinstance(spec, str) else leaves(widget)
    for rank, c in enumerate(controls):
        n_err = len(errors)
        base_vals = dlg.wired_values()
        base_main = arr(img(w)) if not self_look else None
        base_dlg = arr(img(inner)) if self_look else None
        try:
            undo = mutate(c)
        except Exception as exc:
            report.append((key, rank, describe(c), "MUTATION IMPOSSIBLE", str(exc)))
            continue
        settle()
        vals = dlg.wired_values()
        diff = sorted(k for k in set(vals) | set(base_vals) if vals.get(k) != base_vals.get(k))
        if self_look:
            top_left = c.mapTo(inner, QPoint(0, 0))
            mask = QRect(top_left, c.size()).adjusted(-6, -6, 6, 6)
            seen = changed_pixels(base_dlg, arr(img(inner)), mask)
        else:
            seen = changed_pixels(base_main, arr(img(w)))
        undo()
        settle()
        back = dlg.wired_values()
        restored = all(back.get(k) == base_vals.get(k) for k in base_vals)
        errs = errors[n_err:]
        status = []
        if not diff:
            status.append("AUCUNE CLE")
        if seen == 0:
            status.append("RIEN A L'ECRAN")
        if not restored:
            status.append("PAS RESTAURE")
        if errs:
            status.append("EXCEPTION")
        report.append((key, rank, describe(c), " / ".join(status) or "ok",
                       ",".join(diff)[:90] + (f"  lignes px={seen}") + ("\n" + errs[0] if errs else "")))
        print(f"{key:<45} #{rank:<2} {describe(c):<30} {report[-1][3]:<30} {report[-1][4]}", flush=True)

print("\n==== PROBLEMES ====")
for key, rank, kind, status, info in report:
    if status != "ok":
        print(f"{key:<45} #{rank:<2} {kind:<30} {status:<30} {info}")
print("exceptions totales :", len(errors))

"""Compare le temps d'ouverture et le nombre de widgets :
  - SettingsWindow (reelle, mode "visuel") ;
  - SettingsWindowV2 (maquette pilotee par catalogue, construction differee) ;
  - SettingsWindowV2(eager=True) : meme catalogue, TOUT construit d'un coup
    (isole l'apport du "differe" de celui du "catalogue").
Puis, a perimetre EGAL (groupes Colonnes + Entetes seuls), la page Inspecteur
de l'ancienne fenetre contre celle de la v2.

Usage : python tests/_probe_settings_compare.py   (depuis la racine du depot)
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import settings_window as sw
import settings_window_v2 as v2
from app_style import INSPECTOR_TITLE


def count() -> int:
    return len(QApplication.allWidgets())


def measure(label, build, repeat=3):
    best = None
    for _ in range(repeat):
        n0 = count()
        t = time.perf_counter()
        win = build()
        dt = time.perf_counter() - t
        n = count() - n0
        best = (dt, n) if best is None or dt < best[0] else best
        win.deleteLater()
        app.processEvents()
    print(f"{label:58s} {best[0] * 1000:8.0f} ms {best[1]:6d} widgets")
    return best


print("== Ouverture de la fenetre ==")
old = measure("ANCIENNE  SettingsWindow (visuel)", lambda: sw.SettingsWindow(mode="visuel"), repeat=2)
new = measure("V2        catalogue + differe", lambda: v2.SettingsWindowV2())
eag = measure("V2 eager  catalogue, tout construit d'un coup", lambda: v2.SettingsWindowV2(eager=True))
print(f"\nOuverture : v2 est {old[0] / new[0]:.1f}x plus rapide, {old[1] / new[1]:.1f}x moins de widgets.")

host = sw.SettingsWindow(mode="general")        # fenetre legere, sert d'hote pour la methode


def v2_page_expanded(label_index):
    """Fenetre v2 + une page dont TOUS les groupes sont deplies (= construits)."""
    w = v2.SettingsWindowV2()
    t = time.perf_counter()
    w._ensure_page(label_index)
    page = w.stack.widget(label_index)
    v2.expand_all(page)
    w.page_seconds["__page__"] = time.perf_counter() - t
    return w


def run_equal(name, title, v2_index):
    print(f"\n== Perimetre egal : page '{name}' ==")
    measure(f"ANCIENNE  _build_column_override_page({name})",
            lambda: host._build_column_override_page(title, title))
    best = None
    keys_v2 = set()
    for _ in range(3):
        n0 = count()
        w = v2_page_expanded(v2_index)
        dt, n = w.page_seconds["__page__"], count() - n0
        best = (dt, n) if best is None or dt < best[0] else best
        keys_v2 = set(w.stores[name]["fields"])
        w.deleteLater()
        app.processEvents()
    print(f"{'V2        meme page, groupes deplies':58s} {best[0] * 1000:8.0f} ms {best[1]:6d} widgets (fenetre v2 incluse)")
    keys_old = set(host._type_fields[title])
    print(f"  cles de reglage : ancienne {len(keys_old)}, v2 {len(keys_v2)} ; "
          f"manquantes en v2 : {sorted(keys_old - keys_v2) or 'aucune'} ; "
          f"en plus en v2 : {sorted(keys_v2 - keys_old) or 'aucune'}")


labels = [label for label, _t in v2.SCOPES]
run_equal(INSPECTOR_TITLE, INSPECTOR_TITLE, labels.index(INSPECTOR_TITLE))
run_equal("Type", "Type", labels.index("Type"))

# Sections de General deja portees : chacune dans l'ancienne fenetre (methode _section_xxx) contre la v2.
print("\n== Sections de General : ancienne vs v2 (noeud deplie en entier) ==")
by_title = {n.title: n for n in v2.GENERAL_TREE}
for old_name, v2_title in (("_section_headers", "Colonnes"), ("_section_titre", "TITRE"),
                           ("_section_tables", "Tableaux"), ("_section_toggles", "Toggles"),
                           ("_section_slider", "Sliders")):
    o = measure(f"ANCIENNE  {old_name}()", lambda n=old_name: getattr(host, n)(), repeat=2)

    def build_v2(title=v2_title):
        w = v2.SettingsWindowV2()
        page = w.stack.currentWidget()
        node = next(n for n in page.findChildren(v2._LazyNode) if n.node.title == title and n.level == 1)
        t = time.perf_counter()
        node.set_collapsed(False)
        v2.expand_all(node)
        w.page_seconds["__n__"] = time.perf_counter() - t
        w._n_widgets = len(node.findChildren(__import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget))
        return w

    best = None
    for _ in range(2):
        w = build_v2()
        r = (w.page_seconds["__n__"], w._n_widgets)
        best = r if best is None or r[0] < best[0] else best
        w.deleteLater()
        app.processEvents()
    print(f"{'V2        ' + v2_title:58s} {best[0] * 1000:8.0f} ms {best[1]:6d} widgets")

from settings_store import DEFAULT_SETTINGS
covered = set()
for specs in v2.CATALOG.values():
    for sp in specs:
        covered |= {sp.key, *sp.extra_keys}
print(f"\nCouverture : {len(covered & set(DEFAULT_SETTINGS))} / {len(DEFAULT_SETTINGS)} cles de reglage")

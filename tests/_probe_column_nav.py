"""Sonde de NAVIGATION en colonnes dans la vraie fenêtre principale (affichage natif, hors écran) : arborescence
profonde générée (dossiers + fichiers + images), parcourue au clic niveau par niveau, en local puis par le réseau
(partage administratif `\\\\127.0.0.1\\X$`, vrai client SMB de Windows). Mesures par clic : temps BLOQUANT (le
clic rend la main) et temps jusqu'à la colonne suivante remplie ; médiane / 95e centile. Aussi : clics rapides sur
plusieurs dossiers frères, retour vers un dossier déjà vu, saut direct vers un dossier profond (raccourci).

    QT_QPA_PLATFORM=windows python tests/_probe_column_nav.py [local|net|both] [PROFILE=1]
"""
import copy, os, shutil, statistics, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import settings_store, browser_core
import pipeline_browser as pb
for module in (settings_store, pb, browser_core):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting",
                 "save_live_state"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
pb.open_path = lambda path: None

DEPTH = int(os.environ.get("DEPTH", "10"))
WIDE = int(os.environ.get("WIDE", "30"))          # dossiers frères par niveau
FILES = int(os.environ.get("FILES", "120"))       # fichiers par niveau (dont quelques images)


def build(root: Path) -> list[Path]:
    chain = []
    level = root
    img = QImage(64, 48, QImage.Format_RGB32)
    for d in range(DEPTH):
        for i in range(WIDE):
            (level / f"dir_{d:02d}_{i:03d}").mkdir()
        for i in range(FILES):
            if i % 10 == 0:
                img.fill(QColor(i * 2 % 255, 80, 120))
                img.save(str(level / f"img_{i:03d}.png"))
            else:
                (level / f"file_{i:03d}.txt").write_text("x" * i)
        level = level / f"dir_{d:02d}_{WIDE // 2:03d}"
        chain.append(level)
        if d == 2:
            # Niveau 3 = un « set » : l'appli y montre Logiciels / IN / OVER / OUT ; la descente continue dans IN.
            for name in ("in", "over", "out", "blender"):
                (level / name).mkdir()
            level = level / "in"
    return chain


QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv)


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.002)


def wait(cond, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.001)
    return False


def stats(label, values):
    v = sorted(x * 1000 for x in values)
    if not v:
        return
    p95 = v[min(len(v) - 1, int(round(len(v) * 0.95)) - 1)]
    print(f"  {label:<38} n={len(v):<3} médiane {statistics.median(v):7.1f} ms   P95 {p95:7.1f} ms   max {v[-1]:7.1f} ms")


def column_of(win, directory: Path):
    key = os.path.normcase(str(directory))
    for c in [*win.columns, *win.group_columns]:
        if c.directory is not None and os.path.normcase(str(c.directory)) == key:
            return c
    return None


def click(win, column, name):
    lst = column.list
    for i in range(lst.count()):
        item = lst.item(i)
        p = item.data(pb.ROLE_PATH)
        if p and Path(p).name == name:
            lst.scrollToItem(item)
            pos = lst.visualItemRect(item).center()
            t = time.perf_counter()
            QTest.mouseClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
            return time.perf_counter() - t
    raise RuntimeError(f"{name} absent de {column.directory}")


def run(root: Path, chain: list[Path], label: str, profile):
    settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
    settings["root_path"] = str(root)
    pb.apply_all_settings(settings)
    pb.apply_style(app)
    win = pb.PipelineBrowser(root)
    win._idle_preview_scheduler.timer.stop()
    win.move(-3000, 0); win.resize(1900, 1000); win.show()
    QTest.qWaitForWindowActive(win)
    pump(1.0)
    print(f"== {label} : {root}")
    blocks, fulls = [], []
    if profile is not None:
        profile.enable()
    # 1. Descente niveau par niveau.
    for level in chain:
        parent = level.parent
        col = column_of(win, parent)
        assert col is not None, parent
        t = time.perf_counter()
        blocks.append(click(win, col, level.name))
        ok = wait(lambda: column_of(win, level) is not None)
        fulls.append(time.perf_counter() - t)
        if not ok:
            print("   colonnes :", [(c.column_title, str(c.directory)[len(str(root)):], c.list.count())
                                    for c in [*win.columns, *win.group_columns]])
        assert ok, f"colonne {level} jamais remplie"
        pump(0.15)
    stats("descente : clic bloquant", blocks)
    stats("descente : colonne suivante remplie", fulls)
    # 2. Clics rapides sur des frères (sans attendre) puis le dernier doit gagner.
    mid = chain[DEPTH // 2 - 1]
    col = column_of(win, mid)
    rapid = []
    names = [f"dir_{DEPTH // 2:02d}_{i:03d}" for i in range(8)]
    t0 = time.perf_counter()
    for name in names:
        rapid.append(click(win, col, name))
        app.processEvents()
    target = mid / names[-1]
    wait(lambda: (c := column_of(win, target)) is not None and c.list.count() >= 0)
    stats("8 clics rapides : clic bloquant", rapid)
    print(f"  8 clics rapides : dernière colonne prête après {(time.perf_counter() - t0) * 1000:.0f} ms ;"
          f" colonnes ouvertes = {len(win.columns)}")
    pump(0.5)
    # 3. Retour vers un dossier déjà vu (niveau 2) puis redescente d'un niveau.
    back = []
    for _ in range(5):
        col = column_of(win, chain[0])
        click(win, col, "dir_01_000"); pump(0.2)
        t = time.perf_counter(); click(win, col, chain[1].name)
        wait(lambda: column_of(win, chain[1]) is not None); back.append(time.perf_counter() - t); pump(0.2)
        col = column_of(win, chain[1])
        click(win, col, chain[2].name); wait(lambda: column_of(win, chain[2]) is not None); pump(0.2)
    stats("retour vers un dossier déjà vu", back)
    # 4. Raccourci : saut direct vers le dossier le plus profond.
    jumps = []
    for _ in range(3):
        col = column_of(win, root)
        click(win, col, "dir_00_000"); pump(0.3)
        t = time.perf_counter()
        win._navigate_to(chain[-1])
        b = time.perf_counter() - t
        wait(lambda: column_of(win, chain[-1]) is not None)
        jumps.append(b); pump(0.4)
    stats("saut direct (_navigate_to) au niveau le plus profond", jumps)
    # 5. Ligne RACCOURCI (.pipeline_shortcuts.json) vers un dossier profond, éventuellement réseau : un clic.
    import json
    host = chain[4]
    for target_label, target in (("local", chain[-1]), ("réseau", SHORTCUT_REMOTE)):
        if target is None:
            continue
        (host / ".pipeline_shortcuts.json").write_text(json.dumps([{"target": str(target)}]), encoding="utf-8")
        col = column_of(win, chain[3]); click(win, col, "dir_04_000"); pump(0.3)
        click(win, col, chain[4].name); wait(lambda: column_of(win, chain[4]) is not None); pump(0.4)
        col = column_of(win, chain[4])
        t = time.perf_counter(); b = click(win, col, target.name)
        wait(lambda: column_of(win, target) is not None)
        print(f"  clic sur un raccourci {target_label} (dossier profond) : bloquant {b * 1000:.1f} ms, colonne "
              f"prête après {(time.perf_counter() - t) * 1000:.1f} ms")
        pump(0.4)
    (host / ".pipeline_shortcuts.json").unlink(missing_ok=True)
    if profile is not None:
        profile.disable()
    win.close(); pump(0.3)


TIMES = {}
SHORTCUT_REMOTE = None


def instrument():
    """TIMERS=1 : temps INCLUS des fonctions clés, fil de l'interface seulement (somme, nombre, max)."""
    import threading, functools
    import column as column_mod, preview_column, detail_panel
    main_thread = threading.main_thread()
    targets = [(pb.PipelineBrowser, n) for n in (
        "on_selected", "_on_selected_now", "prune_after", "add_column", "update_preview_stack", "_fade_before_select",
        "_animate_column_in", "_refresh_crumbs", "_grab_set_columns_at", "_apply_project_columns_collapsed",
        "_prewarm_snapshots", "add_group_column", "_navigate_to", "update_active_column", "_sync_collapse_state",
        "_sync_mode_buttons", "_sync_software_buttons", "_auto_collapse_now", "_grab_columns")]
    targets += [(column_mod.Column, n) for n in ("__init__", "refresh", "sync_bottom_gap", "sync_uniform_sizes")]
    targets += [(detail_panel.DetailPanel, n) for n in ("show_path", "clear")]
    targets += [(preview_column.PreviewColumn, n) for n in ("__init__", "set_preview_block")]
    for cls, name in targets:
        if not hasattr(cls, name):
            continue
        orig = getattr(cls, name)

        def wrap(orig=orig, key=f"{cls.__name__}.{name}"):
            @functools.wraps(orig)
            def inner(*a, **k):
                if threading.current_thread() is not main_thread:
                    return orig(*a, **k)
                t = time.perf_counter()
                try:
                    return orig(*a, **k)
                finally:
                    d = time.perf_counter() - t
                    s = TIMES.setdefault(key, [0.0, 0, 0.0])
                    s[0] += d; s[1] += 1; s[2] = max(s[2], d)
            return inner
        setattr(cls, name, wrap())


def profile_function():
    """PROFILE_FN=module.Classe.méthode : cProfile de cette seule fonction (fil de l'interface), cumulé."""
    import cProfile, importlib, threading
    mod_name, cls_name, fn_name = os.environ["PROFILE_FN"].split(".")
    cls = getattr(importlib.import_module(mod_name), cls_name)
    orig = getattr(cls, fn_name)
    prof = cProfile.Profile()

    def inner(*a, **k):
        if threading.current_thread() is not threading.main_thread():
            return orig(*a, **k)
        prof.enable()
        try:
            return orig(*a, **k)
        finally:
            prof.disable()
    setattr(cls, fn_name, inner)
    return prof


FS = {}


def count_fs():
    """FSCOUNT=1 : accès disque (stat, scandir, open, resolve) du fil de l'interface sur des chemins RÉSEAU,
    comptés par fonction de l'appli appelante."""
    import builtins, io, ntpath, threading, traceback
    main_thread = threading.main_thread()
    app_files = ("pipeline_browser", "column", "browser_core", "previews", "detail_panel", "row_delegates",
                 "capture_widgets", "preview_column", "lightroom_bridge", "focus", "file_attributes")

    def record(kind, path):
        if threading.current_thread() is not main_thread or not str(path).startswith("\\\\"):
            return
        for frame in reversed(traceback.extract_stack(limit=14)[:-2]):
            name = os.path.splitext(os.path.basename(frame.filename))[0]
            if name in app_files:
                key = f"{kind:<8} {name}.{frame.name}:{frame.lineno}"
                FS[key] = FS.get(key, 0) + 1
                return

    for mod, attr, kind in ((os, "stat", "stat"), (os, "scandir", "scandir"), (ntpath, "_getfinalpathname", "resolve"),
                            (os, "listdir", "listdir")):
        orig = getattr(mod, attr)

        def wrap(p, *a, _o=orig, _k=kind, **k):
            record(_k, p)
            return _o(p, *a, **k)
        setattr(mod, attr, wrap)
    orig_open = io.open

    def wrapped_open(file, *a, **k):
        record("open", file)
        return orig_open(file, *a, **k)
    builtins.open = wrapped_open
    io.open = wrapped_open


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    if os.environ.get("FSCOUNT"):
        count_fs()
    if os.environ.get("TIMERS"):
        instrument()
    fn_prof = profile_function() if os.environ.get("PROFILE_FN") else None
    import cProfile, pstats
    profile = cProfile.Profile() if os.environ.get("PROFILE") else None
    local = Path(tempfile.mkdtemp(prefix="colnav_"))
    try:
        chain = build(local)
        global SHORTCUT_REMOTE
        unc_root = "\\\\127.0.0.1\\" + local.drive.rstrip(":") + "$" + str(local)[2:]
        SHORTCUT_REMOTE = Path(unc_root + str(chain[-1])[len(str(local)):])
        if mode in ("local", "both"):
            run(local, chain, "LOCAL", profile)
        if mode in ("net", "both"):
            unc = Path(f"\\\\127.0.0.1\\{local.drive.rstrip(':')}$" + str(local)[2:])
            run(unc, [Path(str(unc) + str(c)[len(str(local)):]) for c in chain], "RÉSEAU (SMB local)", profile)
        if profile is not None:
            pstats.Stats(profile).sort_stats("cumulative").print_stats(
                r"(pipeline_browser|column|browser_core|previews|detail_panel|row_delegates|capture_widgets|"
                r"preview_column|focus)\.py", 40)
    finally:
        shutil.rmtree(local, ignore_errors=True)
    if FS:
        print(f"  accès réseau sur le fil de l'interface : {sum(FS.values())}")
        for key, n in sorted(FS.items(), key=lambda kv: -kv[1])[:30]:
            print(f"    {n:6d}  {key}")
    if fn_prof is not None:
        import pstats
        pstats.Stats(fn_prof).sort_stats("tottime").print_stats(30)
        if os.environ.get("CALLERS"):
            pstats.Stats(fn_prof).print_callers(os.environ["CALLERS"])
    for key, (total, n, worst) in sorted(TIMES.items(), key=lambda kv: -kv[1][0])[:28]:
        print(f"  {key:<48} total {total * 1000:8.0f} ms  n={n:<4} moy {total / n * 1000:6.1f}  max {worst * 1000:6.1f}")
    print("OK")


if __name__ == "__main__":
    main()

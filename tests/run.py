"""Tests rapides PAR MODULE : ne jamais lancer toute la suite pour une retouche.

    python tests/run.py                    liste des modules et de leurs fichiers de test
    python tests/run.py fm_video           tests rapides du module (les tests @lent sont sautés)
    python tests/run.py fm_cad fm_board    plusieurs modules
    python tests/run.py fm_video --lent    y compris les tests lents (avant un commit qui touche leur zone)
    python tests/run.py --tout             tous les modules (rapides seulement, sauf --lent)
    -v                                     détail test par test

Un nouveau fichier de test DOIT être rangé ci-dessous (sinon `run.py` le signale comme « non rangé »).
Marquer un test lent : `tests/_lent.py`. Plan : docs/agents/fm_theme.md, « Tests rapides par module »."""
import fnmatch
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent

# Module -> motifs de fichiers de test. Les noms fm_* sont ceux du plan d'isolation (paquets à venir) ;
# un fichier peut appartenir à plusieurs modules (fm_board regroupe fm_miro et fm_cad, à cause du cycle).
MODULES = {
    "fm_video": ["test_video_*.py", "test_moodboard_*.py"],
    "fm_markdown": ["test_markdown_*.py", "test_md_*.py"],
    "fm_visionneuse": ["test_focus_viewer.py", "test_filmstrip_cells.py", "test_gallery_attributes.py",
                       "test_file_attributes.py", "test_color_mark.py", "test_pureref_viewer.py",
                       "test_viewer_*.py", "test_folder_viewer_menu.py"],
    "fm_miro": ["test_board.py"],
    "fm_cad": ["test_cad*.py"],
    "fm_board": ["test_board.py", "test_cad*.py"],
    "apercus": ["test_abr_preview.py", "test_ai_preview.py", "test_alembic_conversion.py",
                "test_automatic_tasks.py", "test_cube_lut.py", "test_dwg_thumbnail.py", "test_hip_preview.py",
                "test_manual_file_preview.py", "test_previews_modules.py", "test_render_log.py", "test_turntable*.py", "test_lightroom_*.py"],
    "reglages": ["test_color_alpha.py", "test_color_drag.py", "test_color_picker.py", "test_context_menu.py",
                 "test_element_style.py", "test_extra_windows.py", "test_free_objects.py",
                 "test_input_tabs_settings.py", "test_interface_edit_scope.py", "test_menu_objects.py",
                 "test_presets.py", "test_settings_*.py", "test_shadows.py", "test_table_*.py",
                 "test_title_reorder.py", "test_navigation_bar.py", "test_space_below.py", "test_ext_color.py"],
    "colonnes": ["test_bottom_pin.py", "test_column_loading.py", "test_file_operations.py",
                 "test_navigation_loading.py", "test_pin_per_preset.py", "test_project_config_defaults.py",
                 "test_software_launch.py", "test_software_menu.py", "test_type_reorder.py",
                 "test_inspector_resize.py"],
}
# Noms des docs actuelles (docs/agents/<nom>.md) acceptés aussi.
ALIAS = {"video": "fm_video", "markdown": "fm_markdown", "visionneuse": "fm_visionneuse",
         "board": "fm_board", "miro": "fm_miro", "cad": "fm_cad"}


def _all_files():
    return sorted(p.name for p in TESTS.glob("test_*.py"))


def files_of(module):
    pats = MODULES[module]
    return [f for f in _all_files() if any(fnmatch.fnmatch(f, p) for p in pats)]


def unassigned():
    rangés = {f for m in MODULES for f in files_of(m)}
    return [f for f in _all_files() if f not in rangés]


def _print_list():
    for m in MODULES:
        print(f"{m:15} {' '.join(files_of(m))}")
    reste = unassigned()
    if reste:
        print(f"\nNON RANGÉS (à ajouter dans tests/run.py) : {' '.join(reste)}")
    print("\nUsage : python tests/run.py <module>... [--lent] [-v] | --tout")


def _run_one(name, verbose):
    """Processus enfant : un seul fichier de test. Sortie par os._exit : la fin normale de Python plante
    parfois (segfault de nanobind / Qt au démontage, après « OK ») et ne sert à rien ici."""
    os.chdir(ROOT)                                     # comme `python -m unittest` lancé depuis la racine
    for p in (str(TESTS), str(ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        suite = unittest.defaultTestLoader.loadTestsFromName(name[:-3])
        ok = unittest.TextTestRunner(verbosity=verbose).run(suite).wasSuccessful()
    except Exception:
        import traceback
        traceback.print_exc()
        ok = False
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if ok else 1)


def _summary(out):
    ran = next((l for l in out.splitlines() if l.startswith("Ran ")), "Ran ? tests").split(" in ")[0]
    last = [l for l in out.splitlines() if l.startswith(("OK", "FAILED"))]
    return f"{ran[4:]:>10} {last[-1] if last else 'PLANTÉ'}"


def main(argv):
    for s in (sys.stdout, sys.stderr):                 # console / fichier en cp1252 : jamais d'erreur d'affichage
        s.reconfigure(encoding="utf-8", errors="replace")
    lent = "--lent" in argv
    verbose = 2 if "-v" in argv else 1
    if "--un" in argv:                                 # appel interne (voir plus bas)
        _run_one(argv[argv.index("--un") + 1], verbose)
    names = [a for a in argv if not a.startswith("-")]
    if "--tout" in argv:
        names = list(MODULES)
    if not names:
        _print_list()
        return 0
    names = [ALIAS.get(n, n) for n in names]
    inconnus = [n for n in names if n not in MODULES]
    if inconnus:
        print(f"Module inconnu : {', '.join(inconnus)}\n")
        _print_list()
        return 2
    files = sorted({f for n in names for f in files_of(n)})

    # Un processus PAR FICHIER : dans un seul processus, les fenêtres et l'état laissés par un fichier
    # ralentissent les suivants (mesuré 2026-10-28 : fm_board 698 s d'un bloc contre ~140 s fichier par fichier).
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"),
               PIPELINE_TESTS_LENTS="1" if lent else "0", PYTHONIOENCODING="utf-8")
    t0 = time.perf_counter()
    failed = []
    for f in files:
        t1 = time.perf_counter()
        p = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--un", f] + (["-v"] if verbose > 1 else []),
                           cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = p.stdout + p.stderr
        crash = f" — PLANTÉ après les tests (code {p.returncode})" if p.returncode and "\nOK" in out else ""
        print(f"{f:40} {time.perf_counter() - t1:6.1f} s {_summary(out)}{crash}", flush=True)
        if p.returncode or verbose > 1:
            print(out)
        if p.returncode:
            failed.append(f)
    print(f"\n{', '.join(names)} : {len(files)} fichiers, {time.perf_counter() - t0:.1f} s"
          + ("" if lent else " (tests lents sautés : --lent pour les lancer)"))
    if failed:
        print(f"ÉCHECS : {' '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

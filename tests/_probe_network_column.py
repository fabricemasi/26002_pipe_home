"""Sonde : temps BLOQUANT de `Column.refresh` sur un dossier lu par le réseau (SMB), avec et sans la reprise des
infos de `os.scandir` (entry_is_dir / entry_size). Sans serveur, le partage administratif local
(`\\\\127.0.0.1\\C$\\…`) passe par le vrai client SMB de Windows.

    python tests/_probe_network_column.py [dossier UNC existant]"""
import _isolate  # noqa: F401

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)

import browser_core  # noqa: E402
from column_parts import loading as column_mod  # noqa: E402
from column import Column  # noqa: E402


def measure(directory: Path, label: str, runs: int = 3) -> float:
    col = Column(directory, "Test")
    best = None
    for _ in range(runs):
        browser_core._ENTRY_INFO.clear()
        t = time.perf_counter()
        col.refresh()
        took = time.perf_counter() - t
        best = took if best is None else min(best, took)
    print(f"{label:<44} {col.list.count():>4} lignes : {best * 1000:7.1f} ms")
    col.deleteLater()
    return best


def main():
    if len(sys.argv) > 1:
        unc = Path(sys.argv[1])
        local = None
    else:
        local = Path(tempfile.mkdtemp(prefix="netcol_"))
        for i in range(60):
            (local / f"dossier_{i:03d}").mkdir()
            (local / f"dossier_{i:03d}" / "a.txt").write_text("x")
        for i in range(300):
            (local / f"fichier_{i:03d}.txt").write_text("x" * i)
        drive = local.drive.rstrip(":")
        unc = Path(f"\\\\127.0.0.1\\{drive}$" + str(local)[2:])
    try:
        print("dossier :", unc)
        new = measure(unc, "après (infos de scandir)")
        # « Avant » : chaque ligne refait is_dir() / stat() comme l'ancien code.
        saved = column_mod.entry_is_dir, column_mod.entry_size
        column_mod.entry_is_dir = lambda p: Path(p).is_dir()
        column_mod.entry_size = lambda p: Path(p).stat().st_size
        try:
            old = measure(unc, "avant (is_dir / stat par ligne)")
        finally:
            column_mod.entry_is_dir, column_mod.entry_size = saved
        print(f"gain : x{old / max(new, 1e-6):.1f}")
    finally:
        if local is not None:
            shutil.rmtree(local, ignore_errors=True)


if __name__ == "__main__":
    main()

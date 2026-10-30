"""Sonde de fluidité du module Tableur (hors suite de tests) : `python tests/_probe_tableur.py [cellules]`.

Mesure, sur un classeur de N cellules (défaut 100 000, dont 10 % de formules dépendantes) : construction du
moteur, saisie d'une cellule dont dépendent des milliers de formules, insertion d'une ligne en haut, changement de
feuille, sérialisation native (enregistrement du Board), export / import .xlsx, peinture de la grille (pleine,
molette, flèche), ouverture du mode Standard. Hors écran (QT_QPA_PLATFORM=offscreen)."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import _isolate  # noqa: E402,F401
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from fm_tableur import io_xlsx, numfmt, ops  # noqa: E402
from fm_tableur.document import Cell, new_workbook  # noqa: E402
from fm_tableur.session import Session  # noqa: E402
from fm_tableur.widget import SpreadsheetWidget  # noqa: E402


def ms(start):
    return (time.perf_counter() - start) * 1000


def main(total=100_000):
    cols = 10
    rows = total // cols
    book = new_workbook(2)
    sheet = book.sheets[0]
    for r in range(rows):
        for c in range(cols - 1):
            sheet.cells[(r, c)] = Cell(float(r * cols + c))
        sheet.cells[(r, cols - 1)] = Cell(None, f"=SUM(A{r + 1}:I{r + 1})+$A$1")
    t = time.perf_counter()
    session = Session(book)
    print(f"moteur construit ({total} cellules, {rows} formules) : {ms(t):.0f} ms")
    t = time.perf_counter()
    ops.set_input(book, session.stack, sheet, 0, 0, "5", numfmt.DEFAULT_LOCALE)
    print(f"saisie de A1 ({rows} formules dépendantes recalculées) : {ms(t):.1f} ms")
    t = time.perf_counter()
    ops.set_input(book, session.stack, sheet, rows // 2, 3, "7", numfmt.DEFAULT_LOCALE)
    print(f"saisie d'une cellule (1 dépendante) : {ms(t):.2f} ms")
    t = time.perf_counter()
    ops.insert_lines(book, session.stack, sheet, "row", 0, 1)
    print(f"insertion d'une ligne en haut : {ms(t):.0f} ms")
    t = time.perf_counter()
    session.stack.undo()
    print(f"annulation de l'insertion : {ms(t):.0f} ms")
    t = time.perf_counter()
    raw = session.snapshot()
    print(f"sérialisation native : {ms(t):.0f} ms ; gardée ensuite : ", end="")
    t = time.perf_counter()
    session.snapshot()
    print(f"{ms(t):.3f} ms")
    t = time.perf_counter()
    Session.from_dict(raw)
    print(f"relecture native + moteur : {ms(t):.0f} ms")
    path = os.path.join(tempfile.mkdtemp(), "sonde.xlsx")
    t = time.perf_counter()
    io_xlsx.write(book, path)
    print(f"export .xlsx : {ms(t):.0f} ms ({os.path.getsize(path) / 1e6:.1f} Mo)")
    t = time.perf_counter()
    io_xlsx.read(path)
    print(f"import .xlsx : {ms(t):.0f} ms")
    w = SpreadsheetWidget(session)
    w.resize(2400, 1300)
    w.show()
    APP.processEvents()
    grid = w.grid
    times = []
    orig = grid.paint_to

    def timed(p, a):
        start = time.perf_counter()
        orig(p, a)
        times.append(ms(start))
    grid.paint_to = timed
    grid.viewport().repaint()
    times.clear()
    for _ in range(5):
        grid.viewport().repaint()
    print(f"peinture complète 2400 x 1300 : médiane {sorted(times)[2]:.1f} ms")
    times.clear()
    for _ in range(30):
        grid.verticalScrollBar().setValue(grid.verticalScrollBar().value() + 60)
        APP.processEvents()
    print(f"molette (3 lignes) : médiane {sorted(times)[len(times) // 2]:.1f} ms")
    times.clear()
    t = time.perf_counter()
    for i in range(20):
        grid.select(200 + i, 4)
        APP.processEvents()
    print(f"flèche : {ms(t) / 20:.1f} ms par pas (peinture comprise)")
    t = time.perf_counter()
    w.set_sheet(book.sheets[1])
    APP.processEvents()
    print(f"changement de feuille : {ms(t):.1f} ms")
    t = time.perf_counter()
    other = SpreadsheetWidget(session)
    other.resize(2400, 1300)
    other.show()
    APP.processEvents()
    print(f"seconde présentation de la même session (mode Standard) : {ms(t):.0f} ms")
    other.detach()
    w.detach()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100_000)

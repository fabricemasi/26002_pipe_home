"""CSV / TSV (SANS Qt). Import : encodage (UTF-8 avec ou sans BOM, sinon Windows-1252), séparateur deviné (« ; »,
« , », tabulation), valeurs reconnues comme une saisie (nombres à la française, dates…). Export : valeurs
AFFICHÉES de la feuille active (comme Excel), UTF-8 avec BOM (Excel le relit sans erreur d'accents), écriture
atomique."""
from __future__ import annotations

import csv
import io
import os
from pathlib import Path

from . import numfmt, ops
from .document import Workbook

MAX_BYTES = 512 * 1024 ** 2


def read_text(path) -> str:
    data = Path(path).read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError("fichier CSV trop volumineux (512 Mo au plus)")
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def sniff(text: str, suffix: str = "") -> str:
    if suffix == ".tsv":
        return "\t"
    sample = text[:20000]
    counts = {sep: sample.count(sep) for sep in (";", "\t", ",")}
    return max(counts, key=counts.get) if any(counts.values()) else ","


def read(path, loc=numfmt.DEFAULT_LOCALE, date_order="dmy") -> Workbook:
    path = Path(path)
    text = read_text(path)
    sep = sniff(text, path.suffix.lower())
    book = Workbook()
    sheet = book.add_sheet(path.stem[:31] or "Feuil1")
    book.source = {"path": str(path), "format": path.suffix.lower().lstrip("."), "lost": []}
    reader = csv.reader(io.StringIO(text), delimiter=sep)
    for r, row in enumerate(reader):
        for c, value in enumerate(row):
            if value == "":
                continue
            cell = ops.input_cell(book, sheet, r, c, value if not value.startswith("=") else "'" + value, loc,
                                  date_order)
            if cell is not None:
                sheet.cells[(r, c)] = cell
    return book


def write(book: Workbook, sheet, path, loc=numfmt.DEFAULT_LOCALE, sep: str | None = None):
    path = Path(path)
    if sep is None:
        sep = "\t" if path.suffix.lower() == ".tsv" else (";" if loc.decimal == "," else ",")
    used = sheet.used_range()
    out = io.StringIO()
    writer = csv.writer(out, delimiter=sep, lineterminator="\r\n")
    if used:
        r0, c0, r1, c1 = 0, 0, used[2], used[3]
        for r in range(r0, r1 + 1):
            writer.writerow([ops.display_text(book, sheet, r, c, loc)[0] for c in range(c0, c1 + 1)])
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(out.getvalue(), encoding="utf-8-sig", newline="")
    os.replace(tmp, path)

"""Import / export depuis l'interface (Qt) : fichiers Excel / CSV <-> classeur affiché.

Importer = AJOUTER les feuilles du fichier au classeur (une étape d'annulation ; styles et noms recopiés), jamais
remplacer en silence ni modifier le fichier lu. Les éléments perdus sont annoncés. Exporter = un NOUVEAU fichier."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from . import commands as C
from . import io_csv
from .document import Sheet

OPEN_FILTER = "Classeurs (*.xlsx *.xlsm *.csv *.tsv);;Excel (*.xlsx *.xlsm);;CSV (*.csv *.tsv)"
SAVE_FILTER = "Classeur Excel (*.xlsx);;CSV séparateur point-virgule (*.csv);;Texte tabulé (*.tsv)"


def load(path, loc, date_order="dmy"):
    """Classeur d'un fichier (sans l'afficher)."""
    suffix = Path(path).suffix.lower()
    if suffix in (".csv", ".tsv", ".txt"):
        return io_csv.read(path, loc, date_order)
    if suffix in (".xlsx", ".xlsm"):
        from . import io_xlsx
        return io_xlsx.read(path)
    if suffix == ".xls":
        raise ValueError("format .xls (Excel 97-2003) non pris en charge : l'enregistrer en .xlsx depuis Excel")
    if suffix == ".xlsb":
        raise ValueError("format .xlsb (binaire) non pris en charge : l'enregistrer en .xlsx depuis Excel")
    raise ValueError(f"format non pris en charge : {suffix}")


def merge_book(target_book, stack, source_book, index=None):
    """Feuilles de `source_book` ajoutées à `target_book` (styles réindexés, noms gardés s'ils sont libres)."""
    stack.begin("Importer")
    added = []
    position = len(target_book.sheets) if index is None else index
    for sheet in source_book.sheets:
        name = sheet.name if target_book.sheet(sheet.name) is None else target_book.unique_name(sheet.name)
        clone = Sheet(name)
        mapping = {}

        def remap(i):
            if not i:
                return 0
            found = mapping.get(i)
            if found is None:
                found = mapping[i] = target_book.styles.intern(dict(source_book.styles.get(i)))
            return found
        clone.cells = {k: c.with_(style=remap(c.style)) if c.style else c for k, c in sheet.cells.items()}
        clone.restore(sheet.state())
        clone.rows.styles = {k: remap(v) for k, v in sheet.rows.styles.items()}
        clone.cols.styles = {k: remap(v) for k, v in sheet.cols.styles.items()}
        for attr in ("show_grid", "zoom", "tab_color", "hidden", "protected"):
            setattr(clone, attr, getattr(sheet, attr))
        stack.push(C.SheetsCommand("add", "Importer", sheet=clone, index=position))
        position += 1
        added.append(clone)
    names = dict(target_book.names)
    for key, value in source_book.names.items():
        names.setdefault(key, value)
    if names != target_book.names:
        stack.push(C.Names(names))
    stack.end()
    return added


def import_into(sw, path):
    try:
        book = load(path, sw.grid.loc, sw.grid.date_order)
    except Exception as exc:                               # noqa: BLE001 - fichier refusé : message, rien de touché
        QMessageBox.warning(sw, "Import impossible", f"{Path(path).name} :\n{exc}")
        return None
    added = merge_book(sw.book, sw.stack, book, sw.book.index_of(sw.grid.sheet) + 1)
    lost = book.source.get("lost") or []
    if lost:
        QMessageBox.information(sw, "Import : éléments non repris",
                                "Le fichier d'origine n'est pas modifié. Non repris dans le tableur :\n- "
                                + "\n- ".join(lost))
    if added:
        sw.set_sheet(added[0])
    return added


def export_to(sw, path, chosen_filter=""):
    path = Path(path)
    suffix = path.suffix.lower()
    if not suffix:
        suffix = ".csv" if "csv" in (chosen_filter or "").lower() else (
            ".tsv" if "tsv" in (chosen_filter or "").lower() else ".xlsx")
        path = path.with_suffix(suffix)
    try:
        if suffix in (".csv", ".tsv"):
            io_csv.write(sw.book, sw.grid.sheet, path, sw.grid.loc)
            warnings = ["CSV : seule la feuille active, valeurs affichées (ni formules ni styles)"]
        else:
            from . import io_xlsx
            if suffix != ".xlsx":
                path = path.with_suffix(".xlsx")
            warnings = io_xlsx.write(sw.book, path)
    except Exception as exc:                               # noqa: BLE001
        QMessageBox.warning(sw, "Export impossible", f"{path.name} :\n{exc}")
        return False
    text = f"Exporté : {path.name}"
    if warnings:
        text += " — " + " ; ".join(warnings)
    sw._message(text)
    return True

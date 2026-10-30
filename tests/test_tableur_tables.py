"""fm_tableur, tableaux structurés : création (entêtes détectées / ajoutées), références structurées traduites pour le
moteur (T[Col], T[[Col1]:[Col2]], #All / #Data / #Headers / #Totals, [@Col], T[@Col], nom seul), recalcul quand le
tableau change, extension automatique, colonne calculée, ligne des totaux, renommer, convertir en plage, insertion de
lignes, annulation, format natif, aller-retour Excel (tableaux et forme longue [#This Row])."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_tableur import io_native, numfmt, ops, structured as T, tables_ops  # noqa: E402
from fm_tableur import values as V  # noqa: E402
from fm_tableur.document import new_workbook  # noqa: E402
from fm_tableur.engine import cell_value, fz  # noqa: E402
from fm_tableur.session import Session  # noqa: E402

EN = numfmt.Locale(".", ",", "en")


def make():
    s = Session(new_workbook(1))
    sheet = s.book.sheets[0]
    for r, row in enumerate([["Poste", "Montant", "Qte"], ["Transport", 10, 2], ["Repas", 20, 3],
                             ["Hôtel", 30, 4]]):
        for c, v in enumerate(row):
            ops.set_input(s.book, s.stack, sheet, r, c, str(v), EN)
    return s, sheet


def put(s, sheet, r, c, text):
    ops.set_input(s.book, s.stack, sheet, r, c, text, EN)


def val(s, sheet, r, c):
    return cell_value(s.book, sheet, r, c)


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.s, self.sheet = make()
        self.table = tables_ops.create(self.s.book, self.s.stack, self.sheet, (0, 0, 3, 2))

    def r(self, formula, row=10, col=6):
        return T.resolve(formula, self.s.book, self.sheet, row, col)

    def test_creation_detects_header(self):
        self.assertEqual((self.table["name"], self.table["ref"], self.table["header"]), ("Tableau1", (0, 0, 3, 2), True))
        self.assertEqual(T.columns(self.s.book, self.sheet, self.table), ["Poste", "Montant", "Qte"])

    def test_translation(self):
        n = "Feuil1!"
        self.assertEqual(self.r("=SUM(Tableau1[Montant])"), f"=SUM({n}$B$2:$B$4)")
        self.assertEqual(self.r("=SUM(Tableau1[[Montant]:[Qte]])"), f"=SUM({n}$B$2:$C$4)")
        self.assertEqual(self.r("=ROWS(Tableau1[#All])"), f"=ROWS({n}$A$1:$C$4)")
        self.assertEqual(self.r("=COUNTA(Tableau1[#Headers])"), f"=COUNTA({n}$A$1:$C$1)")
        self.assertEqual(self.r("=SUM(Tableau1[[#Headers],[#Data],[Qte]])"), f"=SUM({n}$C$1:$C$4)")
        self.assertEqual(self.r("=ROWS(Tableau1)+ROWS(Tableau1[])"), f"=ROWS({n}$A$2:$C$4)+ROWS({n}$A$2:$C$4)")
        self.assertEqual(self.r("=[@Montant]*[@Qte]", 2, 0), f"={n}$B$3*{n}$C$3")
        self.assertEqual(self.r("=Tableau1[@Montant]", 2, 9), f"={n}$B$3")
        self.assertEqual(self.r("=Tableau1[[#This Row],[Qte]]", 3, 9), f"={n}$C$4")
        self.assertEqual(self.r('=Tableau1[Inconnue]&"Tableau1[Montant]"'), '=#REF!&"Tableau1[Montant]"')
        self.assertEqual(self.r("=Absent[Montant]"), "=#REF!")
        self.assertEqual(self.r("=[@Montant]", 20, 1), "=#REF!")                 # hors de tout tableau
        self.assertEqual(self.r("=Tableau1[@Montant]", 20, 1), "=#VALUE!")       # ligne hors du tableau

    def test_french_keywords(self):
        self.assertEqual(self.r("=COUNTA(Tableau1[#En-têtes])"), "=COUNTA(Feuil1!$A$1:$C$1)")
        self.assertEqual(self.r("=Tableau1[[#Cette ligne],[Qte]]", 3, 9), "=Feuil1!$C$4")

    def test_escaped_column_names(self):
        put(self.s, self.sheet, 0, 2, "Prix [HT] #1")
        self.assertEqual(self.r("=SUM(Tableau1[Prix '[HT'] '#1])"), "=SUM(Feuil1!$C$2:$C$4)")


@unittest.skipIf(fz is None, "formualizer absent")
class EngineTablesTest(unittest.TestCase):
    def setUp(self):
        self.s, self.sheet = make()
        tables_ops.create(self.s.book, self.s.stack, self.sheet, (0, 0, 3, 2))

    def test_formulas_compute_and_follow_changes(self):
        s, sh = self.s, self.sheet
        put(s, sh, 6, 0, "=SUM(Tableau1[Montant])")
        put(s, sh, 7, 0, '=XLOOKUP("Repas",Tableau1[Poste],Tableau1[Montant])')
        put(s, sh, 8, 0, "=ROWS(Tableau1)")
        self.assertEqual((val(s, sh, 6, 0), val(s, sh, 7, 0), val(s, sh, 8, 0)), (60, 20, 3))
        put(s, sh, 2, 1, "25")                                   # donnée modifiée
        self.assertEqual(val(s, sh, 6, 0), 65)
        put(s, sh, 4, 0, "Divers")                               # ligne sous le tableau : extension auto
        self.assertEqual(T.find(s.book, "Tableau1")[1]["ref"], (0, 0, 4, 2))
        put(s, sh, 4, 1, "5")
        self.assertEqual((val(s, sh, 6, 0), val(s, sh, 8, 0)), (70, 4))
        put(s, sh, 0, 1, "Prix")                                 # entête renommée : les formules suivent (Excel)
        self.assertEqual(sh.cell(6, 0).formula, "=SUM(Tableau1[Prix])")
        self.assertEqual(sh.cell(7, 0).formula, '=XLOOKUP("Repas",Tableau1[Poste],Tableau1[Prix])')
        self.assertEqual(val(s, sh, 6, 0), 70)
        s.stack.undo()                                           # une seule étape : entête et formules
        self.assertEqual(sh.cell(6, 0).formula, "=SUM(Tableau1[Montant])")
        self.assertEqual(val(s, sh, 6, 0), 70)
        put(s, sh, 6, 1, "=SUM(Tableau1[Absente])")
        self.assertEqual(val(s, sh, 6, 1), V.XLError("#REF!"))

    def test_calculated_column_and_this_row(self):
        s, sh = self.s, self.sheet
        tables_ops.after_input  # (accroché à la saisie)
        put(s, sh, 0, 3, "Total")                                # colonne à droite : extension
        self.assertEqual(T.find(s.book, "Tableau1")[1]["ref"], (0, 0, 3, 3))
        put(s, sh, 1, 3, "=[@Montant]*[@Qte]")                    # colonne calculée : recopiée
        self.assertEqual([sh.cell(r, 3).formula for r in (1, 2, 3)], ["=[@Montant]*[@Qte]"] * 3)
        self.assertEqual([val(s, sh, r, 3) for r in (1, 2, 3)], [20, 60, 120])
        put(s, sh, 4, 0, "Divers")                               # nouvelle ligne : la colonne calculée la suit
        self.assertEqual(sh.cell(4, 3).formula, "=[@Montant]*[@Qte]")
        s.stack.undo()
        self.assertIsNone(sh.cell(4, 3))

    def test_totals_rename_insert_and_convert(self):
        s, sh = self.s, self.sheet
        table = T.find(s.book, "Tableau1")[1]
        tables_ops.toggle_totals(s.book, s.stack, sh, table)
        self.assertEqual((sh.cell(4, 0).value, sh.cell(4, 2).formula), ("Total", "=SUBTOTAL(109,Tableau1[Qte])"))
        self.assertEqual(val(s, sh, 4, 2), 9)
        put(s, sh, 7, 0, "=SUM(Tableau1[Montant])+Tableau1[[#Totals],[Qte]]")
        self.assertEqual(val(s, sh, 7, 0), 69)
        self.assertIsNone(tables_ops.rename(s.book, s.stack, sh, T.find(s.book, "Tableau1")[1], "Frais"))
        self.assertEqual(sh.cell(7, 0).formula, "=SUM(Frais[Montant])+Frais[[#Totals],[Qte]]")
        self.assertEqual(val(s, sh, 7, 0), 69)
        self.assertIsNotNone(tables_ops.rename(s.book, s.stack, sh, T.find(s.book, "Frais")[1], "A1"))
        ops.insert_lines(s.book, s.stack, sh, "row", 2, 1)       # ligne insérée DANS le tableau
        self.assertEqual(T.find(s.book, "Frais")[1]["ref"], (0, 0, 5, 2))
        put(s, sh, 2, 1, "100")
        self.assertEqual(val(s, sh, 8, 0), 169)
        tables_ops.convert_to_range(s.book, s.stack, sh, T.find(s.book, "Frais")[1])
        self.assertEqual(sh.tables, [])
        self.assertEqual(sh.cell(8, 0).formula, "=SUM($B$2:$B$5)+$C$6")
        self.assertEqual(val(s, sh, 8, 0), 169)
        s.stack.undo()
        self.assertEqual(sh.cell(8, 0).formula, "=SUM(Frais[Montant])+Frais[[#Totals],[Qte]]")
        self.assertEqual(val(s, sh, 8, 0), 169)

    def test_native_round_trip(self):
        put(self.s, self.sheet, 6, 0, "=SUM(Tableau1[Montant])")
        book, _a = io_native.from_dict(io_native.to_dict(self.s.book))
        other = Session(book)
        self.assertEqual(book.sheets[0].tables[0]["ref"], (0, 0, 3, 2))
        self.assertEqual(cell_value(other.book, book.sheets[0], 6, 0), 60)


class ExcelTablesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_import_and_export(self):
        import openpyxl
        from openpyxl.worksheet.table import Table, TableStyleInfo
        from fm_tableur import io_xlsx
        src = os.path.join(self.dir, "tableaux.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        for row in [["Poste", "Montant", "Qte", "Total"], ["A", 10, 2, None], ["B", 20, 3, None]]:
            ws.append(row)
        ws["D2"] = "=Ventes[[#This Row],[Montant]]*Ventes[[#This Row],[Qte]]"
        ws["D3"] = "=Ventes[[#This Row],[Montant]]*Ventes[[#This Row],[Qte]]"
        ws["F1"] = "=SUM(Ventes[Total])"
        table = Table(displayName="Ventes", ref="A1:D3")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium7", showRowStripes=True)
        ws.add_table(table)
        wb.save(src)
        book = io_xlsx.read(src)
        session = Session(book)
        sheet = book.sheets[0]
        self.assertEqual(sheet.tables[0]["name"], "Ventes")
        self.assertEqual((sheet.tables[0]["ref"], sheet.tables[0]["style"]), ((0, 0, 2, 3), "vert"))
        self.assertFalse(any("structurés" in x for x in book.source["lost"]))
        if fz is not None:
            self.assertEqual(cell_value(book, sheet, 0, 5), 80)
        ops.set_input(book, session.stack, sheet, 1, 3, "=[@Montant]+1", EN)   # forme courte d'Excel
        out = os.path.join(self.dir, "export.xlsx")
        io_xlsx.write(book, out)
        raw = openpyxl.load_workbook(out)
        ws2 = raw.active
        self.assertIn("Ventes", ws2.tables)
        self.assertEqual(ws2.tables["Ventes"].ref, "A1:D3")
        self.assertEqual(ws2["D2"].value, "=Ventes[[#This Row],[Montant]]+1")     # forme longue du fichier
        again = io_xlsx.read(out)
        self.assertEqual(again.sheets[0].tables[0]["ref"], (0, 0, 2, 3))


if __name__ == "__main__":
    unittest.main()


class CtrlTTest(unittest.TestCase):
    def test_ctrl_t_creates_table_from_current_region(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from fm_tableur.widget import SpreadsheetWidget
        s, sheet = make()
        w = SpreadsheetWidget(s)
        w.resize(900, 500)
        w.show()
        app.processEvents()
        try:
            w.grid.select(2, 1)
            QApplication.sendEvent(w.grid, QKeyEvent(QKeyEvent.KeyPress, Qt.Key_T, Qt.ControlModifier))
            self.assertEqual(sheet.tables[0]["ref"], (0, 0, 3, 2))
            self.assertEqual(w.grid.selection(), (0, 0, 3, 2))
            from PySide6.QtGui import QImage, QPainter
            image = QImage(900, 500, QImage.Format_ARGB32_Premultiplied)
            painter = QPainter(image)
            w.grid.paint_to(painter, w.grid.viewport().rect())         # style à bandes peint sans erreur
            painter.end()
            s.stack.undo()
            self.assertEqual(sheet.tables, [])
        finally:
            w.detach()
            w.deleteLater()

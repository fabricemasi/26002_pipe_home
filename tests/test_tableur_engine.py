"""fm_tableur, cœur SANS Qt : références A1 et leur réécriture, formats de nombres, saisie typée, moteur de calcul
(valeurs de RÉFÉRENCE indépendantes du code testé : exemples documentés de Microsoft Excel et calculs à la main),
dépendances et recalcul, erreurs, commandes et annulation, opérations (copier, recopier, trier, filtrer),
format natif."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_tableur import commands as C, io_native, numfmt, ops, refs as R, values as V  # noqa: E402
from fm_tableur.document import Cell, new_workbook  # noqa: E402
from fm_tableur.engine import cell_value, check_formula, expand_names, fz  # noqa: E402
from fm_tableur.session import Session  # noqa: E402

FR = numfmt.Locale(",", " ", "fr")
EN = numfmt.Locale(".", ",", "en")


def make(rows=None, sheets=1):
    """Session dont la 1re feuille reçoit `rows` (liste de listes de saisies, à partir de A1)."""
    s = Session(new_workbook(sheets))
    sheet = s.book.sheets[0]
    for r, row in enumerate(rows or []):
        for c, text in enumerate(row):
            if text is not None:
                ops.set_input(s.book, s.stack, sheet, r, c, str(text), EN)
    return s, sheet


def val(s, sheet, addr):
    r, c = R.parse_cell(addr)
    return cell_value(s.book, sheet, r, c)


def put(s, sheet, addr, text):
    r, c = R.parse_cell(addr)
    ops.set_input(s.book, s.stack, sheet, r, c, text, EN)


class RefsTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(R.col_name(0), "A")
        self.assertEqual(R.col_name(25), "Z")
        self.assertEqual(R.col_name(26), "AA")
        self.assertEqual(R.col_name(16383), "XFD")
        self.assertEqual(R.col_index("XFD"), 16383)
        self.assertEqual(R.col_index("XFE"), -1)
        self.assertEqual(R.parse_cell("$B$3"), (2, 1))
        self.assertEqual(R.parse_range("Feuil2!A1:C4"), ("Feuil2", (0, 0, 3, 2)))
        self.assertEqual(R.parse_range("B:B")[1], (0, 1, R.MAX_ROWS - 1, 1))

    def test_iter_refs_skips_strings_functions_and_names(self):
        f = '=SUM(A1:B2)+LOG10(C3)+"D4"&\'My Sheet\'!$E$5+Taux+Feuil2!F6+A1B+_X1'
        found = [(r.sheet, r.text()) for r in R.iter_refs(f)]
        self.assertEqual(found, [(None, "A1:B2"), (None, "C3"), ("My Sheet", "'My Sheet'!$E$5"),
                                 ("Feuil2", "Feuil2!F6")])

    def test_translate_relative_absolute_mixed(self):
        self.assertEqual(R.translate("=A1+$B$2+C$3+$D4", 1, 1), "=B2+$B$2+D$3+$D5")
        self.assertEqual(R.translate("=SUM(A1:A10)", 2, 0), "=SUM(A3:A12)")
        self.assertEqual(R.translate("=A1", -1, 0), "=#REF!")
        self.assertEqual(R.translate("=Feuil2!B2*2", 0, 1), "=Feuil2!C2*2")
        self.assertEqual(R.translate('="A1"&A1', 1, 0), '="A1"&A2')

    def test_insert_delete_rows(self):
        self.assertEqual(R.shift_insert("=SUM(A1:A10)+$B$5", "S", "S", "row", 4, 2), "=SUM(A1:A12)+$B$7")
        self.assertEqual(R.shift_insert("=A1", "S", "S", "row", 4, 2), "=A1")
        self.assertEqual(R.shift_insert("=T!A9", "S", "T", "row", 0, 1), "=T!A10")
        self.assertEqual(R.shift_insert("=A9", "S", "T", "row", 0, 1), "=A9")      # autre feuille
        self.assertEqual(R.shift_delete("=B5", "S", "S", "row", 4, 1), "=#REF!")
        self.assertEqual(R.shift_delete("=SUM(A1:A10)", "S", "S", "row", 2, 3), "=SUM(A1:A7)")
        self.assertEqual(R.shift_delete("=SUM(A3:A5)", "S", "S", "row", 2, 3), "=SUM(#REF!)")
        self.assertEqual(R.shift_delete("=SUM(A1:A3)", "S", "S", "row", 1, 5), "=SUM(A1:A1)")
        self.assertEqual(R.shift_delete("=C1", "S", "S", "col", 0, 1), "=B1")

    def test_sheet_rename_remove_and_move(self):
        self.assertEqual(R.rename_sheet("=Feuil1!A1+'Feuil1'!B2", "feuil1", "Mes données"),
                         "='Mes données'!A1+'Mes données'!B2")
        self.assertEqual(R.remove_sheet("=Feuil2!A1+A1", "Feuil2"), "=#REF!+A1")
        self.assertEqual(R.move_refs("=A1+B2+SUM(A1:A2)", "S", "S", (0, 0, 1, 0), 5, 2), "=C6+B2+SUM(C6:C7)")


class NumberFormatTest(unittest.TestCase):
    CASES = [
        (1234.5, "#,##0.00", EN, "1,234.50"), (1234.5, "#,##0.00", FR, "1 234,50"),
        (-1234.5, "#,##0.00;[Red](#,##0.00)", EN, "(1,234.50)"), (0.256, "0.0%", EN, "25.6%"),
        (0, '0.00;-0.00;"zero"', EN, "zero"), (123456789, "0.00E+00", EN, "1.23E+08"), (0.5, "#.##", EN, ".5"),
        (2.675, "0.00", EN, "2.68"), (1.005, "0.00", EN, "1.01"), (46000, "dd/mm/yyyy", EN, "09/12/2025"),
        (46000.75, "hh:mm", EN, "18:00"), (46000.75, "h:mm AM/PM", EN, "6:00 PM"), (1.5, "[h]:mm", EN, "36:00"),
        (46000, "dddd d mmmm yyyy", FR, "mardi 9 décembre 2025"), (1234567, "#,##0,", EN, "1,235"),
        (12, "0000", EN, "0012"), ("abc", '@" !"', EN, "abc !"), (0.1 + 0.2, "General", EN, "0.3"),
        (123456789012, "General", EN, "1.23457E+11"), (1 / 3, "General", FR, "0,333333333"),
        (5, '[>=10]"big";"small"', EN, "small"), (1.5, "# ?/?", EN, "1 1/2"), (0.75, "?/4", EN, "3/4"),
        (44927, "jj/mm/aaaa", FR, "01/01/2023"), (-0.001, "0.00", EN, "0.00"), (3, '0.0"€"', FR, "3,0€"),
        (60, "dd/mm/yyyy", EN, "########"), (61, "dd/mm/yyyy", EN, "01/03/1900"), (1, "dd/mm/yyyy", EN, "01/01/1900"),
    ]

    def test_cases(self):
        for value, code, loc, expected in self.CASES:
            with self.subTest(value=value, code=code):
                self.assertEqual(numfmt.format_value(value, code, loc)[0], expected)

    def test_color_and_decimals(self):
        self.assertEqual(numfmt.format_value(-3, "0;[Red]-0", EN), ("-3", "#ff0000"))
        self.assertEqual(numfmt.change_decimals("0.00", 1), "0.000")
        self.assertEqual(numfmt.change_decimals("0.00", -2), "0")
        self.assertEqual(numfmt.change_decimals("General", 1), "0.0")

    def test_serials(self):
        self.assertEqual(numfmt.datetime_to_serial(dt.date(2026, 10, 30)), 46325)
        self.assertEqual(numfmt.serial_to_datetime(46325), dt.datetime(2026, 10, 30))
        self.assertEqual(numfmt.datetime_to_serial(dt.date(1900, 1, 1)), 1)


class InputTest(unittest.TestCase):
    def test_typed_input(self):
        p = V.parse_input
        self.assertEqual(p("12,5").value, 12.5)
        self.assertEqual(p("1 234,5").value, 1234.5)
        self.assertEqual(p("1,234.5").value, 1234.5)
        self.assertEqual(p("1.5").value, 1.5)
        self.assertIsInstance(p("42").value, int)
        self.assertEqual((p("10%").value, p("10%").fmt), (0.1, "0%"))
        self.assertEqual((p("12,50 €").value, p("12,50 €").fmt), (12.5, '#,##0.00 "€"'))
        self.assertEqual((p("30/10/2026").value, p("30/10/2026").fmt), (46325, "dd/mm/yyyy"))
        self.assertEqual(p("2026-10-30").value, 46325)
        self.assertAlmostEqual(p("14:30").value, 14.5 / 24)
        self.assertIs(p("VRAI").value, True)
        self.assertEqual(p("#N/A").value, V.XLError("#N/A"))
        self.assertEqual(p("'0123").value, "0123")
        self.assertEqual(p("=A1").formula, "=A1")
        self.assertEqual(p("abc").value, "abc")
        self.assertEqual(p("(12)").value, -12)
        self.assertEqual(p("31/02/2026").value, "31/02/2026")       # date impossible : texte

    def test_edit_text(self):
        self.assertEqual(V.edit_text(46325, None, "dd/mm/yyyy", FR), "30/10/2026")
        self.assertEqual(V.edit_text(0.125, None, "0.0%", FR), "12,5%")
        self.assertEqual(V.edit_text(1 / 3, None, None, FR), "0,333333333333333")
        self.assertEqual(V.edit_text("0123", None, None, FR), "'0123")
        self.assertEqual(V.edit_text(None, "=A1+1", None, FR), "=A1+1")


@unittest.skipIf(fz is None, "formualizer absent")
class EngineReferenceTest(unittest.TestCase):
    """Résultats attendus = exemples des pages d'aide de Microsoft Excel (valeurs publiées) ou calculs à la main."""

    def check(self, formula, expected, places=6, setup=None):
        s, sheet = make(setup)
        put(s, sheet, "Z1", formula)
        got = val(s, sheet, "Z1")
        if isinstance(expected, float):
            self.assertIsInstance(got, (int, float), formula)
            self.assertAlmostEqual(got, expected, places=places, msg=formula)
        else:
            self.assertEqual(got, expected, formula)

    def test_math(self):
        for f, e in [("=ROUND(2.5,0)", 3), ("=ROUND(-2.5,0)", -3), ("=ROUNDDOWN(3.14159,3)", 3.141),
                     ("=ROUNDUP(-3.14159,1)", -3.2), ("=MOD(-3,2)", 1), ("=MOD(3,-2)", -1), ("=INT(-8.9)", -9),
                     ("=TRUNC(-8.9)", -8), ("=POWER(5,2)", 25), ("=SQRT(16)", 4), ("=ABS(-4)", 4),
                     ("=PRODUCT(5,15,30)", 2250), ("=SUMPRODUCT({3,4,8},{2,6,5})", 70), ("=2^10", 1024),
                     ("=-2^2", 4), ("=10/4", 2.5), ("=ROUND(1234.5678,-2)", 1200)]:
            with self.subTest(f):
                self.check(f, float(e))

    def test_statistics(self):
        data = [[1345], [1301], [1368], [1322], [1310], [1370], [1318], [1350], [1303], [1299]]
        self.check("=STDEV(A1:A10)", 27.46391572, places=6, setup=data)
        self.check("=VAR(A1:A10)", 754.2666667, places=5, setup=data)
        self.check("=AVERAGE(A1:A10)", 1328.6, setup=data)
        self.check("=MEDIAN(1,2,3,4,5,6)", 3.5)
        self.check("=COUNT(A1:A10,\"x\")", 10.0, setup=data)
        self.check("=COUNTA(A1:A3)", 2.0, setup=[[1], ["a"], [None]])
        self.check("=MAX(A1:A10)-MIN(A1:A10)", 71.0, setup=data)

    def test_logic(self):
        self.check('=IF(5>3,"OK","NON")', "OK")
        self.check('=IFS(1>2,"a",2>1,"b")', "b")
        self.check('=SWITCH(2,1,"un",2,"deux","autre")', "deux")
        self.check("=IFERROR(1/0,-1)", -1.0)
        self.check('=IFNA(NA(),"x")', "x")
        self.check("=AND(TRUE,1>0,NOT(FALSE))", True)
        self.check("=OR(FALSE,0)", False)

    def test_lookup(self):
        table = [["Transport", 10], ["Repas", 20], ["Transport", 5], ["Hôtel", 100]]
        self.check('=SUMIF(A1:A4,"Transport",B1:B4)', 15.0, setup=table)
        self.check('=COUNTIF(A1:A4,"Transport")', 2.0, setup=table)
        self.check('=COUNTIFS(A1:A4,"Transport",B1:B4,">6")', 1.0, setup=table)
        self.check('=AVERAGEIF(B1:B4,">8")', 130 / 3, setup=table)
        self.check('=VLOOKUP("Repas",A1:B4,2,FALSE)', 20.0, setup=table)
        self.check('=XLOOKUP("Hôtel",A:A,B:B)', 100.0, setup=table)
        self.check('=INDEX(B1:B4,MATCH("Hôtel",A1:A4,0))', 100.0, setup=table)
        self.check('=HLOOKUP(2,{1,2;10,20},2,FALSE)', 20.0)
        self.check('=VLOOKUP("Absent",A1:B4,2,FALSE)', V.XLError("#N/A"), setup=table)

    def test_text(self):
        for f, e in [('=LEFT("Sale Price",4)', "Sale"), ('=RIGHT("Stock Number",6)', "Number"),
                     ('=MID("Fluid Flow",7,20)', "Flow"), ('=LEN("Phoenix, AZ")', 11.0),
                     ('=TRIM(" First Quarter   Earnings ")', "First Quarter Earnings"),
                     ('=SUBSTITUTE("Sales Data","Sales","Cost")', "Cost Data"),
                     ('=FIND("M","Miriam McGovern")', 1.0), ('=SEARCH("e","Statements",6)', 7.0),
                     ('=CONCAT("a",1,TRUE)', "a1TRUE"), ('=VALUE("12.5")', 12.5), ('=UPPER("ab")', "AB"),
                     ('=TEXT(1234.567,"#,##0.00")', "1,234.57")]:
            with self.subTest(f):
                self.check(f, e)

    def test_dates(self):
        self.check("=DATE(2026,10,30)", 46325.0)
        self.check('=DATEDIF(DATE(2001,1,1),DATE(2003,1,1),"Y")', 2.0)
        self.check("=NETWORKDAYS(DATE(2012,10,1),DATE(2013,3,1))", 110.0)
        self.check("=WORKDAY(DATE(2008,10,1),151)", 39933.0)
        self.check("=YEAR(46325)+MONTH(46325)+DAY(46325)", 2026 + 10 + 30.0)
        self.check("=DATE(2026,1,31)+1", 46054.0)

    def test_finance(self):
        self.check("=PMT(0.08/12,10,10000)", -1037.032089, places=5)
        self.check("=PMT(0.05/12,360,-200000)", 1073.643246, places=5)
        self.check("=FV(0.06/12,10,-200,-500,1)", 2581.403374, places=5)
        self.check("=PV(0.08/12,12*20,500,,0)", -59777.14585, places=4)
        self.check("=NPV(0.1,-10000,3000,4200,6800)", 1188.443412, places=5)
        self.check("=IRR({-70000,12000,15000,18000,21000,26000})", 0.086630948, places=7)
        self.check("=RATE(4*12,-200,8000)", 0.007701472, places=8)
        self.check("=XNPV(0.09,{-10000,2750,4250,3250,2750},{39448,39508,39751,39859,39904})", 2086.647602,
                   places=4)
        self.check("=XIRR({-10000,2750,4250,3250,2750},{39448,39508,39751,39859,39904})", 0.373362535, places=6)

    def test_errors_never_hidden(self):
        self.check("=1/0", V.XLError("#DIV/0!"))
        self.check("=SQRT(-1)", V.XLError("#NUM!"))
        self.check('="a"+1', V.XLError("#VALUE!"))
        self.check("=PASUNEFONCTION(1)", V.XLError("#NAME?"))
        self.check("=A1+1", V.XLError("#DIV/0!"), setup=[["#DIV/0!"]])
        self.assertIsNotNone(check_formula("=SUM(A1:A3"))
        self.assertIsNone(check_formula("=SUM(A1:A3)"))

    def test_dynamic_arrays_spill(self):
        s, sheet = make()
        put(s, sheet, "A1", "=SEQUENCE(3)")
        self.assertEqual([val(s, sheet, a) for a in ("A1", "A2", "A3")], [1, 2, 3])
        put(s, sheet, "A2", "x")                      # obstacle : #SPILL!
        self.assertEqual(val(s, sheet, "A1"), V.XLError("#SPILL!"))
        self.check("=LET(x,2,x*3)", 6.0)
        self.check("=SUM(FILTER(A1:A4,A1:A4>2))", 7.0, setup=[[1], [2], [3], [4]])
        self.check("=SUM(UNIQUE({1;1;2}))", 3.0)


@unittest.skipIf(fz is None, "formualizer absent")
class ExtraFunctionsTest(EngineReferenceTest):
    """Fonctions ajoutées au moteur (`extra_functions.py`) : exemples de l'aide de Microsoft / calcul à la main."""

    def test_matrices(self):
        s, sheet = make([[1, 2], [3, 4]])
        put(s, sheet, "D1", "=MMULT(A1:B2,A1:B2)")
        self.assertEqual([val(s, sheet, a) for a in ("D1", "E1", "D2", "E2")], [7, 10, 15, 22])
        self.check("=MDETERM({1,3,8,5;1,3,6,1;1,1,1,0;7,3,10,2})", 88.0)
        self.check("=SUM(MINVERSE({4,-1;2,0}))", 1.5 + 0.5 - 1 + 0 + 0.5 - 0.5 + 0.5)
        self.check("=MINVERSE({1,2;2,4})", V.XLError("#NUM!"))
        self.check("=SUM(MUNIT(3))", 3.0)

    def test_finance_extras(self):
        self.check("=FVSCHEDULE(1,{0.09,0.11,0.1})", 1.33089, places=5)
        self.check("=DISC(DATE(2007,1,25),DATE(2007,6,15),97.975,100,1)", 0.052420213, places=8)
        self.check("=INTRATE(DATE(2008,2,15),DATE(2008,5,15),1000000,1014420,2)", 0.05768, places=5)


@unittest.skipIf(fz is None, "formualizer absent")
class RecalcTest(unittest.TestCase):
    def test_dependents_update_and_circular(self):
        s, sheet = make([[1, "=A1*2", "=B1+A1"]])
        self.assertEqual(val(s, sheet, "C1"), 3)
        put(s, sheet, "A1", "10")
        self.assertEqual((val(s, sheet, "B1"), val(s, sheet, "C1")), (20, 30))
        put(s, sheet, "A1", "=C1")
        self.assertEqual(val(s, sheet, "A1"), V.XLError("#CIRC!"))
        big, big_sheet = make()                    # moteur déjà rempli : il refuse l'auto-référence par exception
        big.stack.push(C.SetCells(big_sheet, {(r, c): Cell(r) for r in range(400) for c in range(2)}))
        put(big, big_sheet, "A1", "=A1*2")
        self.assertEqual(val(big, big_sheet, "A1"), V.XLError("#CIRC!"))

    def test_cross_sheet_rename_and_remove(self):
        s, sheet = make(sheets=2)
        other = s.book.sheets[1]
        ops.set_input(s.book, s.stack, other, 0, 0, "5", EN)
        put(s, sheet, "A1", f"={other.name}!A1*3")
        self.assertEqual(val(s, sheet, "A1"), 15)
        ops.rename_sheet(s.book, s.stack, other, "Données 2026")
        self.assertEqual(sheet.cell(0, 0).formula, "='Données 2026'!A1*3")
        self.assertEqual(val(s, sheet, "A1"), 15)
        ops.remove_sheet(s.book, s.stack, other)
        self.assertEqual(sheet.cell(0, 0).formula, "=#REF!*3")
        self.assertEqual(val(s, sheet, "A1"), V.XLError("#REF!"))
        s.stack.undo()
        self.assertEqual(val(s, sheet, "A1"), 15)
        s.stack.undo()
        self.assertEqual(sheet.cell(0, 0).formula, f"={other.name}!A1*3")

    def test_insert_delete_rows_keep_results(self):
        s, sheet = make([[1], [2], [3], ["=SUM(A1:A3)"]])
        self.assertEqual(val(s, sheet, "A4"), 6)
        ops.insert_lines(s.book, s.stack, sheet, "row", 1, 2)
        self.assertEqual(sheet.cell(5, 0).formula, "=SUM(A1:A5)")
        self.assertEqual(val(s, sheet, "A6"), 6)
        ops.delete_lines(s.book, s.stack, sheet, "row", 0, 1)
        self.assertEqual(sheet.cell(4, 0).formula, "=SUM(A1:A4)")
        self.assertEqual(val(s, sheet, "A5"), 5)
        s.stack.undo()
        s.stack.undo()
        self.assertEqual(sheet.cell(3, 0).formula, "=SUM(A1:A3)")
        self.assertEqual(val(s, sheet, "A4"), 6)

    def test_defined_names(self):
        s, sheet = make([[100], [0.2]])
        s.stack.push(C.Names({"Taux": "Feuil1!$A$2"}))
        put(s, sheet, "B1", "=A1*Taux")
        self.assertEqual(val(s, sheet, "B1"), 20)
        self.assertEqual(sheet.cell(0, 1).formula, "=A1*Taux")
        self.assertEqual(expand_names('=Taux+"Taux"', {"Taux": "S!A1"}), '=(S!A1)+"Taux"')

    def test_manual_mode(self):
        s, sheet = make([[1, "=A1+1"]])
        s.book.calc_mode = "manual"
        put(s, sheet, "A1", "5")
        self.assertEqual(val(s, sheet, "B1"), 2)               # pas encore recalculé
        s.engine.recalc()
        self.assertEqual(val(s, sheet, "B1"), 6)

    def test_incremental_chain_is_fast(self):
        import time
        s, sheet = make()
        changes = {(0, 0): Cell(1)}
        changes.update({(r, 0): Cell(None, f"=A{r}+1") for r in range(1, 5000)})
        s.stack.push(C.SetCells(sheet, changes))
        self.assertEqual(val(s, sheet, "A5000"), 5000)
        start = time.perf_counter()
        put(s, sheet, "A1", "10")
        elapsed = time.perf_counter() - start
        self.assertEqual(val(s, sheet, "A5000"), 5009)
        self.assertLess(elapsed, 0.5)


class UndoAndOpsTest(unittest.TestCase):
    def test_undo_redo_and_clean(self):
        s, sheet = make([[1]])
        s.stack.set_clean()
        put(s, sheet, "A1", "2")
        self.assertFalse(s.stack.is_clean())
        s.stack.undo()
        self.assertEqual(sheet.cell(0, 0).value, 1)
        self.assertTrue(s.stack.is_clean())
        s.stack.redo()
        self.assertEqual(sheet.cell(0, 0).value, 2)

    def test_copy_paste_translates_and_cut_moves_references(self):
        s, sheet = make([[1, 2, "=A1+B1"], [3, 4, None]])
        block = ops.copy_block(s.book, sheet, (0, 2, 0, 2))
        ops.paste_block(s.book, s.stack, sheet, 1, 2, block, source_sheet=sheet)
        self.assertEqual(sheet.cell(1, 2).formula, "=A2+B2")
        if fz is not None:
            self.assertEqual(val(s, sheet, "C2"), 7)
        cut = ops.copy_block(s.book, sheet, (0, 0, 0, 0), cut=True)
        ops.paste_block(s.book, s.stack, sheet, 5, 5, cut, source_sheet=sheet)
        self.assertIsNone(sheet.cell(0, 0))
        self.assertEqual(sheet.cell(0, 2).formula, "=F6+B1")
        self.assertEqual(sheet.cell(5, 5).value, 1)

    def test_paste_values(self):
        s, sheet = make([[2, "=A1*10"]])
        block = ops.copy_block(s.book, sheet, (0, 1, 0, 1))
        ops.paste_block(s.book, s.stack, sheet, 3, 3, block, mode="values", source_sheet=sheet)
        cell = sheet.cell(3, 3)
        self.assertIsNone(cell.formula)
        if fz is not None:
            self.assertEqual(cell.value, 20)

    def test_fill_series(self):
        s, sheet = make([[1, "Lundi", "Article 1", "=A1*2", "15/01/2026"], [3, None, None, None, None]])
        ops.fill(s.book, s.stack, sheet, (0, 0, 1, 0), (0, 0, 4, 0))
        self.assertEqual([sheet.cell(r, 0).value for r in range(5)], [1, 3, 5, 7, 9])
        ops.fill(s.book, s.stack, sheet, (0, 1, 0, 3), (0, 1, 2, 3))
        self.assertEqual([sheet.cell(r, 1).value for r in range(3)], ["Lundi", "Mardi", "Mercredi"])
        self.assertEqual(sheet.cell(2, 2).value, "Article 3")
        self.assertEqual(sheet.cell(2, 3).formula, "=A3*2")
        ops.fill(s.book, s.stack, sheet, (0, 4, 0, 4), (0, 4, 1, 4))
        self.assertEqual(sheet.cell(1, 4).value, sheet.cell(0, 4).value + 1)

    def test_sort_stable_excel_order(self):
        s, sheet = make([["Nom", "N"], ["b", 2], ["a", None], ["B", 1], ["c", "x"], ["a2", 2]])
        ops.sort_range(s.book, s.stack, sheet, (0, 0, 5, 1), [(1, True)], header=True)
        self.assertEqual([sheet.cell(r, 0).value for r in range(1, 6)], ["B", "b", "a2", "c", "a"])
        s.stack.undo()
        self.assertEqual(sheet.cell(1, 0).value, "b")

    def test_filter_hides_rows(self):
        s, sheet = make([["Cat"], ["x"], ["y"], ["x"]])
        ops.set_autofilter(s.book, s.stack, sheet, (0, 0, 3, 0))
        self.assertEqual(ops.filter_values(s.book, sheet, 0), ["x", "y"])
        ops.apply_filter(s.book, s.stack, sheet, 0, {"x"})
        self.assertEqual(sheet.rows.hidden, {2})
        ops.set_autofilter(s.book, s.stack, sheet, None)
        self.assertEqual(sheet.rows.hidden, set())

    def test_merge_and_styles_on_whole_column(self):
        s, sheet = make([["a", "b"]])
        ops.merge(s.book, s.stack, sheet, (0, 0, 0, 1), center=True)
        self.assertEqual(sheet.merges, [(0, 0, 0, 1)])
        self.assertIsNone(sheet.cell(0, 1))
        ops.apply_style(s.book, s.stack, sheet, (0, 3, R.MAX_ROWS - 1, 3), {"bold": True})
        self.assertTrue(s.book.style_of(sheet, 500000, 3).get("bold"))
        self.assertLess(len(sheet.cells), 5)

    def test_find_replace_and_duplicates(self):
        s, sheet = make([["pomme"], ["poire"], ["pomme"]])
        self.assertEqual(len(ops.find_all(s.book, [sheet], "POM")), 2)
        self.assertEqual(ops.replace_all(s.book, s.stack, [sheet], "pomme", "fraise"), 2)
        self.assertEqual(sheet.cell(0, 0).value, "fraise")
        self.assertEqual(ops.remove_duplicates(s.book, s.stack, sheet, (0, 0, 2, 0), [0], header=False), 1)
        self.assertEqual([sheet.cell(r, 0) and sheet.cell(r, 0).value for r in range(3)], ["fraise", "poire", None])

    def test_axis_positions(self):
        s, sheet = make()
        axis = sheet.rows
        axis.sizes[5] = 50
        axis.hidden.add(2)
        axis.changed()
        self.assertEqual(axis.pos(6), 5 * 20 - 20 + 50)
        self.assertEqual(axis.index_at(41), 3)                 # la ligne 2 masquée est sautée
        self.assertEqual(axis.index_at(axis.pos(5) + 49), 5)
        self.assertEqual(axis.index_at(axis.pos(1000) + 1), 1000)


class FormulaLangTest(unittest.TestCase):
    def test_french_round_trip(self):
        from fm_tableur.formula_lang import to_english, to_local
        cases = ['=SUM(A1:A3,2.5)+IF(B1>1,"a,b",TRUE)', "=VLOOKUP(\"x;y\",'Ma feuille'!A1:B2,2,FALSE)",
                 "=INDEX(A1:B2,1,2)", "=SUM(A1,5)", "=IFERROR(XLOOKUP(A1,B:B,C:C),0.25)"]
        for f in cases:
            with self.subTest(f):
                self.assertEqual(to_english(to_local(f)), f)
        self.assertEqual(to_local('=SUM(A1:A3,2.5)+IF(B1>1,"a,b",TRUE)'), '=SOMME(A1:A3;2,5)+SI(B1>1;"a,b";VRAI)')
        self.assertEqual(to_english("=somme(A1;B1)*1,5"), "=SUM(A1,B1)*1.5")
        self.assertEqual(to_english("=SUM(A1,B1)"), "=SUM(A1,B1)")              # noms anglais acceptés
        self.assertEqual(to_local("=SUM(A1,B1)", "en"), "=SUM(A1,B1)")


class NativeFormatTest(unittest.TestCase):
    def test_round_trip_keeps_types_and_unknown_keys(self):
        s, sheet = make([[1, 2.5, "t", "VRAI", "#N/A", "=A1+B1", "30/10/2026"]])
        sheet.merges = [(2, 2, 3, 3)]
        sheet.freeze = (1, 0)
        sheet.comments[(0, 0)] = "note"
        sheet.cols.sizes[1] = 120
        raw = io_native.to_dict(s.book)
        raw["futur"] = {"x": 1}
        raw["sheets"][0]["inconnu"] = [1, 2]
        text = json.dumps(raw)
        book, _active = io_native.from_dict(json.loads(text))
        other = book.sheets[0]
        for c in range(7):
            a, b = sheet.cell(0, c), other.cell(0, c)
            self.assertEqual(a.formula, b.formula)
            if a.formula is None:
                self.assertEqual((a.value, type(a.value)), (b.value, type(b.value)))
            elif fz is not None:
                self.assertEqual(b.value, 3.5)                  # valeur calculée rangée avec la formule
        self.assertEqual(book.style_of(other, 0, 6).get("fmt"), "dd/mm/yyyy")
        self.assertEqual((other.merges, other.freeze, other.comments, other.cols.sizes[1]),
                         ([(2, 2, 3, 3)], (1, 0), {(0, 0): "note"}, 120.0))
        again = io_native.to_dict(book)
        self.assertEqual(again["futur"], {"x": 1})
        self.assertEqual(again["sheets"][0]["inconnu"], [1, 2])

    def test_snapshot_cached_until_change(self):
        s, sheet = make([[1]])
        first = s.snapshot()
        self.assertIs(s.snapshot(), first)
        put(s, sheet, "A1", "2")
        self.assertIsNot(s.snapshot(), first)


if __name__ == "__main__":
    unittest.main()

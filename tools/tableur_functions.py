"""Matrice des fonctions d'Excel prises en charge par le moteur du module Tableur (formualizer).

    python tools/tableur_functions.py

Pour chaque fonction d'Excel (liste ci-dessous), une formule `=NOM()` est évaluée : #NAME? = inconnue du moteur,
#N/IMPL = reconnue mais non implémentée, autre résultat (y compris une erreur d'arguments) = présente. Écrit
`fm_tableur/fonctions_verifiees.txt` (lu par « Insérer une fonction ») et `docs/agents/fm_tableur_fonctions.md`.
« Présente » ne dit PAS que tous les cas sont justes : les tests de référence (`tests/test_tableur_engine.py`)
vérifient les résultats des fonctions courantes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAMILIES = {
    "Mathématiques et trigonométrie": "ABS ACOS ACOSH ACOT ACOTH AGGREGATE ARABIC ASIN ASINH ATAN ATAN2 ATANH BASE "
    "CEILING CEILING.MATH CEILING.PRECISE COMBIN COMBINA COS COSH COT COTH CSC CSCH DECIMAL DEGREES EVEN EXP FACT "
    "FACTDOUBLE FLOOR FLOOR.MATH FLOOR.PRECISE GCD INT ISO.CEILING LCM LN LOG LOG10 MDETERM MINVERSE MMULT MOD "
    "MROUND MULTINOMIAL MUNIT ODD PI POWER PRODUCT QUOTIENT RADIANS RAND RANDARRAY RANDBETWEEN ROMAN ROUND "
    "ROUNDDOWN ROUNDUP SEC SECH SEQUENCE SERIESSUM SIGN SIN SINH SQRT SQRTPI SUBTOTAL SUM SUMIF SUMIFS SUMPRODUCT "
    "SUMSQ SUMX2MY2 SUMX2PY2 SUMXMY2 TAN TANH TRUNC",
    "Statistiques": "AVEDEV AVERAGE AVERAGEA AVERAGEIF AVERAGEIFS BETA.DIST BETA.INV BINOM.DIST BINOM.INV CHISQ.DIST "
    "CHISQ.INV CHISQ.TEST CONFIDENCE.NORM CONFIDENCE.T CORREL COUNT COUNTA COUNTBLANK COUNTIF COUNTIFS COVARIANCE.P "
    "COVARIANCE.S DEVSQ EXPON.DIST F.DIST F.INV FISHER FISHERINV FORECAST FORECAST.LINEAR FREQUENCY GAMMA "
    "GAMMA.DIST GAMMA.INV GAMMALN GEOMEAN GROWTH HARMEAN HYPGEOM.DIST INTERCEPT KURT LARGE LINEST LOGEST "
    "LOGNORM.DIST LOGNORM.INV MAX MAXA MAXIFS MEDIAN MIN MINA MINIFS MODE MODE.MULT MODE.SNGL NEGBINOM.DIST "
    "NORM.DIST NORM.INV NORM.S.DIST NORM.S.INV PEARSON PERCENTILE PERCENTILE.EXC PERCENTILE.INC PERCENTRANK "
    "PERCENTRANK.EXC PERCENTRANK.INC PERMUT PERMUTATIONA PHI POISSON.DIST PROB QUARTILE QUARTILE.EXC QUARTILE.INC "
    "RANK RANK.AVG RANK.EQ RSQ SKEW SKEW.P SLOPE SMALL STANDARDIZE STDEV STDEV.P STDEV.S STDEVA STDEVP STDEVPA "
    "STEYX T.DIST T.DIST.2T T.DIST.RT T.INV T.INV.2T T.TEST TREND TRIMMEAN VAR VAR.P VAR.S VARA VARP VARPA "
    "WEIBULL.DIST Z.TEST",
    "Logique": "AND BYCOL BYROW FALSE IF IFERROR IFNA IFS LAMBDA LET MAKEARRAY MAP NOT OR REDUCE SCAN SWITCH TRUE XOR",
    "Recherche et référence": "ADDRESS AREAS CHOOSE CHOOSECOLS CHOOSEROWS COLUMN COLUMNS DROP EXPAND FILTER "
    "FORMULATEXT GETPIVOTDATA HLOOKUP HSTACK HYPERLINK INDEX INDIRECT LOOKUP MATCH OFFSET ROW ROWS SORT SORTBY TAKE "
    "TOCOL TOROW TRANSPOSE UNIQUE VLOOKUP VSTACK WRAPCOLS WRAPROWS XLOOKUP XMATCH",
    "Texte": "ARRAYTOTEXT CHAR CLEAN CODE CONCAT CONCATENATE DOLLAR EXACT FIND FIXED LEFT LEN LOWER MID NUMBERVALUE "
    "PROPER REGEXEXTRACT REGEXREPLACE REGEXTEST REPLACE REPT RIGHT SEARCH SUBSTITUTE T TEXT TEXTAFTER TEXTBEFORE "
    "TEXTJOIN TEXTSPLIT TRIM UNICHAR UNICODE UPPER VALUE VALUETOTEXT",
    "Date et heure": "DATE DATEDIF DATEVALUE DAY DAYS DAYS360 EDATE EOMONTH HOUR ISOWEEKNUM MINUTE MONTH NETWORKDAYS "
    "NETWORKDAYS.INTL NOW SECOND TIME TIMEVALUE TODAY WEEKDAY WEEKNUM WORKDAY WORKDAY.INTL YEAR YEARFRAC",
    "Finances": "ACCRINT ACCRINTM AMORDEGRC AMORLINC COUPDAYBS COUPDAYS COUPDAYSNC COUPNCD COUPNUM COUPPCD CUMIPMT "
    "CUMPRINC DB DDB DISC DOLLARDE DOLLARFR DURATION EFFECT FV FVSCHEDULE INTRATE IPMT IRR ISPMT MDURATION MIRR "
    "NOMINAL NPER NPV ODDFPRICE ODDFYIELD ODDLPRICE ODDLYIELD PDURATION PMT PPMT PRICE PRICEDISC PRICEMAT PV RATE "
    "RECEIVED RRI SLN SYD TBILLEQ TBILLPRICE TBILLYIELD VDB XIRR XNPV YIELD YIELDDISC YIELDMAT",
    "Information": "CELL ERROR.TYPE INFO ISBLANK ISERR ISERROR ISEVEN ISFORMULA ISLOGICAL ISNA ISNONTEXT ISNUMBER "
    "ISODD ISOMITTED ISREF ISTEXT N NA SHEET SHEETS TYPE",
    "Ingénierie": "BESSELI BESSELJ BESSELK BESSELY BIN2DEC BIN2HEX BIN2OCT BITAND BITLSHIFT BITOR BITRSHIFT BITXOR "
    "COMPLEX CONVERT DEC2BIN DEC2HEX DEC2OCT DELTA ERF ERFC GESTEP HEX2BIN HEX2DEC HEX2OCT IMABS IMAGINARY IMREAL "
    "IMSUM OCT2BIN OCT2DEC OCT2HEX",
    "Base de données": "DAVERAGE DCOUNT DCOUNTA DGET DMAX DMIN DPRODUCT DSTDEV DSTDEVP DSUM DVAR DVARP",
}


def probe():
    import formualizer as fz
    wb = fz.Workbook()
    from fm_tableur import extra_functions
    extra_functions.register(wb, fz)                       # fonctions ajoutées par le module
    sheet = wb.sheet("S")
    out = {}
    row = 1
    for family, names in FAMILIES.items():
        for name in names.split():
            sheet.set_formula(row, 1, f"={name}()")
            try:
                value = wb.evaluate_cell("S", row, 1)
            except Exception as exc:                       # noqa: BLE001
                value = {"type": "Error", "kind": "Exception", "message": str(exc)}
            kind = value.get("kind") if isinstance(value, dict) and value.get("type") == "Error" else None
            status = "absente" if kind == "Name" else ("non implémentée" if kind == "NImpl" else "présente")
            out.setdefault(family, []).append((name, status))
            row += 1
    return out


def main():
    from importlib.metadata import version
    results = probe()
    present = sorted(n for items in results.values() for n, s in items if s == "présente")
    (ROOT / "fm_tableur" / "fonctions_verifiees.txt").write_text("\n".join(present) + "\n", encoding="utf-8")
    lines = ["# Matrice des fonctions du module Tableur", "",
             f"Générée par `python tools/tableur_functions.py` (moteur formualizer {version('formualizer')}).",
             "« présente » = reconnue et évaluée par le moteur (y compris quand elle répond une erreur d'arguments) ;",
             "les RÉSULTATS des fonctions courantes sont vérifiés à part (`tests/test_tableur_engine.py`, valeurs",
             "publiées par Microsoft). « absente » = #NAME? ; « non implémentée » = #N/IMPL.", ""]
    total = sum(len(v) for v in results.values())
    lines.append(f"Bilan : {len(present)} présentes sur {total} fonctions sondées.")
    lines.append("")
    for family, items in results.items():
        ok = [n for n, s in items if s == "présente"]
        missing = [f"{n} ({s})" for n, s in items if s != "présente"]
        lines.append(f"## {family} — {len(ok)} / {len(items)}")
        lines.append("")
        lines.append("Présentes : " + ", ".join(ok))
        if missing:
            lines.append("")
            lines.append("Manquantes : " + ", ".join(missing))
        lines.append("")
    (ROOT / "docs" / "agents" / "fm_tableur_fonctions.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(present)} présentes sur {total}")


if __name__ == "__main__":
    main()

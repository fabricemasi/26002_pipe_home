"""Import / export Microsoft Excel .xlsx / .xlsm (SANS Qt) par openpyxl — openpyxl LIT et ÉCRIT, il ne calcule rien
(le calcul est fait par `engine.py`).

Conservé à l'import ET à l'export : feuilles (ordre, noms, masquées, couleur d'onglet), valeurs typées, formules,
valeurs en cache (affichage sans moteur), styles (police, couleurs, fond uni, alignements, retour à la ligne,
retrait, bordures, format de nombre, verrouillage), largeurs / hauteurs / masquage, fusions, volets figés,
quadrillage, zoom, noms définis globaux, commentaires, listes déroulantes, filtre automatique, mises en forme
conditionnelles courantes, protection de feuille, graphiques du module (export).

PERDU (signalé dans `book.source["lost"]`, jamais en silence) : macros VBA (jamais exécutées), images et formes,
graphiques d'un fichier importé, tableaux croisés, segments, liens externes, sparklines, contrôles, tableaux
structurés (leurs références), mises en forme conditionnelles non reconnues. Le fichier d'origine n'est jamais
réécrit par l'import ; l'export écrit un NOUVEAU fichier (atomique : `.part` puis remplacement).

Fonctions récentes : Excel les range sous un préfixe (`_xlfn.XLOOKUP`, `_xlfn._xlws.FILTER`) — retiré à l'import,
remis à l'export (sinon Excel affiche #NAME?). Sécurité : archive contrôlée avant lecture (taille décompressée,
taux de compression, nombre de fichiers)."""
from __future__ import annotations

import datetime as _dt
import os
import re
import zipfile
from pathlib import Path

from . import numfmt
from . import refs as R
from . import values as V
from .document import Cell, Workbook

MAX_UNCOMPRESSED = 2 * 1024 ** 3          # 2 Go décompressés au plus
MAX_RATIO = 200                           # taux de compression suspect (bombe de décompression)
MAX_MEMBERS = 50_000

# Fonctions écrites avec le préfixe _xlfn. dans les fichiers (liste de Microsoft, « Issue: an _xlfn. prefix… »)
XLFN = {"ACOT", "ACOTH", "AGGREGATE", "ARABIC", "BASE", "BETA.DIST", "BETA.INV", "BINOM.DIST", "BINOM.DIST.RANGE",
        "BINOM.INV", "BITAND", "BITLSHIFT", "BITOR", "BITRSHIFT", "BITXOR", "BYCOL", "BYROW", "CEILING.MATH",
        "CEILING.PRECISE", "CHISQ.DIST", "CHISQ.DIST.RT", "CHISQ.INV", "CHISQ.INV.RT", "CHISQ.TEST", "CHOOSECOLS",
        "CHOOSEROWS", "COMBINA", "CONCAT", "CONFIDENCE.NORM", "CONFIDENCE.T", "COT", "COTH", "COVARIANCE.P",
        "COVARIANCE.S", "CSC", "CSCH", "DAYS", "DECIMAL", "DROP", "ERF.PRECISE", "ERFC.PRECISE", "EXPAND",
        "EXPON.DIST", "F.DIST", "F.DIST.RT", "F.INV", "F.INV.RT", "F.TEST", "FLOOR.MATH", "FLOOR.PRECISE",
        "FORECAST.LINEAR", "FORMULATEXT", "GAMMA", "GAMMA.DIST", "GAMMA.INV", "GAMMALN.PRECISE", "GAUSS", "HSTACK",
        "HYPGEOM.DIST", "IFNA", "IFS", "IMCOSH", "IMCOT", "IMCSC", "IMCSCH", "IMSEC", "IMSECH", "IMSINH", "IMTAN",
        "ISFORMULA", "ISOMITTED", "ISOWEEKNUM", "LAMBDA", "LET", "LOGNORM.DIST", "LOGNORM.INV", "MAKEARRAY", "MAP",
        "MAXIFS", "MINIFS", "MODE.MULT", "MODE.SNGL", "MUNIT", "NEGBINOM.DIST", "NETWORKDAYS.INTL", "NORM.DIST",
        "NORM.INV", "NORM.S.DIST", "NORM.S.INV", "NUMBERVALUE", "PDURATION", "PERCENTILE.EXC", "PERCENTILE.INC",
        "PERCENTRANK.EXC", "PERCENTRANK.INC", "PERMUTATIONA", "PHI", "POISSON.DIST", "QUARTILE.EXC",
        "QUARTILE.INC", "RANDARRAY", "RANK.AVG", "RANK.EQ", "REDUCE", "RRI", "SCAN", "SEC", "SECH", "SEQUENCE",
        "SHEET", "SHEETS", "SKEW.P", "STDEV.P", "STDEV.S", "SWITCH", "T.DIST", "T.DIST.2T", "T.DIST.RT", "T.INV",
        "T.INV.2T", "T.TEST", "TAKE", "TEXTAFTER", "TEXTBEFORE", "TEXTJOIN", "TEXTSPLIT", "TOCOL", "TOROW",
        "UNICHAR", "UNICODE", "VALUETOTEXT", "ARRAYTOTEXT", "VAR.P", "VAR.S", "VSTACK", "WEIBULL.DIST",
        "WORKDAY.INTL", "WRAPCOLS", "WRAPROWS", "XLOOKUP", "XMATCH", "XOR", "Z.TEST", "FILTER", "SORT", "SORTBY",
        "UNIQUE"}
XLWS = {"FILTER", "SORT", "SORTBY"}        # _xlfn._xlws.
_PREFIXED = re.compile(r"_xlfn\.(?:_xlws\.)?|_xlpm\.", re.I)
_FUNC_CALL = re.compile(r"(?<![\w.])([A-Z][A-Z0-9]*(?:\.[A-Z0-9]+)*)\s*\(", re.I)
THEME = ["FFFFFF", "000000", "E7E6E6", "44546A", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47",
         "0563C1", "954F72"]


class UnsafeFile(Exception):
    pass


def check_archive(path) -> list[str]:
    """Contrôle d'une archive .xlsx avant lecture (bombe de décompression, archive malformée) ; rend la liste des
    parties pour l'inventaire des éléments non pris en charge."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise UnsafeFile(f"fichier Excel illisible (archive malformée) : {exc}") from exc
    if len(infos) > MAX_MEMBERS:
        raise UnsafeFile("archive anormale : trop de parties")
    total = sum(i.file_size for i in infos)
    packed = sum(i.compress_size for i in infos) or 1
    if total > MAX_UNCOMPRESSED:
        raise UnsafeFile(f"archive trop volumineuse une fois décompressée ({total / 1e9:.1f} Go)")
    if total > 50 * 1024 ** 2 and total / packed > MAX_RATIO:
        raise UnsafeFile("taux de compression anormal (bombe de décompression probable)")
    return [i.filename for i in infos]


def unsupported_parts(names: list[str]) -> list[str]:
    found = []
    checks = [("xl/vbaProject.bin", "macros VBA (jamais exécutées, non conservées)"),
              ("xl/charts/", "graphiques du fichier (non importés)"), ("xl/drawings/", "images / formes"),
              ("xl/pivotTables/", "tableaux croisés dynamiques"), ("xl/slicers/", "segments"),
              ("xl/externalLinks/", "liens vers d'autres classeurs (valeurs en cache seulement)"),
              ("xl/activeX/", "contrôles ActiveX"), ("xl/ctrlProps/", "contrôles de formulaire"),
              ("xl/tables/", "tableaux structurés (mise en forme et références de tableau)"),
              ("xl/timelines/", "chronologies"), ("xl/queryTables/", "requêtes de données"),
              ("xl/model/", "modèle de données Power Pivot")]
    for prefix, label in checks:
        if any(n.startswith(prefix) for n in names) and label not in found:
            found.append(label)
    return found


# ---------------------------------------------------------------- formules
def strip_prefixes(formula: str) -> str:
    return _PREFIXED.sub("", formula) if "_xl" in formula else formula


def add_prefixes(formula: str) -> str:
    def fix(m):
        name = m.group(1).upper()
        if name in XLWS:
            return "_xlfn._xlws." + m.group(1) + "("
        if name in XLFN:
            return "_xlfn." + m.group(1) + "("
        return m.group(0)
    out = []
    last = 0
    for start, end in _string_spans(formula):          # rien dans les chaînes
        out.append(_FUNC_CALL.sub(fix, formula[last:start]))
        out.append(formula[start:end])
        last = end
    out.append(_FUNC_CALL.sub(fix, formula[last:]))
    return "".join(out)


def _string_spans(text):
    i = 0
    while i < len(text):
        if text[i] == '"':
            j = i + 1
            while j < len(text):
                if text[j] == '"':
                    if j + 1 < len(text) and text[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            yield i, j + 1
            i = j + 1
        else:
            i += 1


# ---------------------------------------------------------------- couleurs
def _color(color) -> str | None:
    if color is None:
        return None
    try:
        kind = color.type
    except AttributeError:
        return None
    if kind == "rgb" and isinstance(color.rgb, str) and len(color.rgb) >= 6:
        if len(color.rgb) == 8 and color.rgb[:2] == "00" and color.rgb != "00000000":
            return "#" + color.rgb[2:].lower()
        return "#" + color.rgb[-6:].lower()
    if kind == "theme" and isinstance(color.theme, int) and 0 <= color.theme < len(THEME):
        base = THEME[color.theme]
        tint = float(color.tint or 0)
        r, g, b = (int(base[i:i + 2], 16) for i in (0, 2, 4))
        if tint > 0:
            r, g, b = (round(x + (255 - x) * tint) for x in (r, g, b))
        elif tint < 0:
            r, g, b = (round(x * (1 + tint)) for x in (r, g, b))
        return f"#{r:02x}{g:02x}{b:02x}"
    if kind == "indexed" and isinstance(color.indexed, int):
        from openpyxl.styles.colors import COLOR_INDEX
        if 0 <= color.indexed < len(COLOR_INDEX) and color.indexed not in (64, 65):
            return "#" + COLOR_INDEX[color.indexed][-6:].lower()
    return None


def _px_width(chars) -> float:
    return round(float(chars) * 7 + 5, 1)


def _chars_width(px) -> float:
    return max(0.0, round((float(px) - 5) / 7, 2))


# ---------------------------------------------------------------- import
def read(path, progress=None) -> Workbook:
    """Classeur Excel -> modèle. `progress(fraction)` facultatif. Lève `UnsafeFile` si l'archive est refusée."""
    import openpyxl
    path = Path(path)
    names = check_archive(path)
    lost = unsupported_parts(names)
    keep_vba = path.suffix.lower() == ".xlsm"
    wb = openpyxl.load_workbook(path, data_only=False, keep_vba=False, keep_links=False)
    cached = openpyxl.load_workbook(path, data_only=True, keep_vba=False, keep_links=False)
    book = Workbook()
    book.source = {"path": str(path), "format": path.suffix.lower().lstrip("."), "lost": lost,
                   "macros": keep_vba and "xl/vbaProject.bin" in names}
    style_cache: dict = {}
    for index, ws in enumerate(wb.worksheets):
        sheet = book.add_sheet(ws.title)
        sheet.hidden = ws.sheet_state != "visible"
        try:
            sheet.tab_color = _color(ws.sheet_properties.tabColor)
        except Exception:                                  # noqa: BLE001
            sheet.tab_color = None
        try:
            sheet.show_grid = bool(ws.sheet_view.showGridLines if ws.sheet_view.showGridLines is not None else True)
            if ws.sheet_view.zoomScale:
                sheet.zoom = max(0.1, min(4.0, ws.sheet_view.zoomScale / 100))
        except Exception:                                  # noqa: BLE001
            pass
        cws = cached.worksheets[index]
        for row in ws.iter_rows():
            for xc in row:
                value = xc.value
                if value is None and not xc.has_style:
                    continue
                r, c = xc.row - 1, xc.column - 1
                formula = None
                if xc.data_type == "f" or (isinstance(value, str) and value.startswith("=")):
                    text = getattr(value, "text", value)            # ArrayFormula : son texte
                    if not isinstance(text, str):
                        text = str(text)
                    formula = strip_prefixes(text if text.startswith("=") else "=" + text)
                    value = cws.cell(row=xc.row, column=xc.column).value
                if xc.data_type == "e" or (isinstance(value, str) and value in V.ERROR_CODES):
                    value = V.XLError(value) if isinstance(value, str) else value
                elif isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
                    value = numfmt.datetime_to_serial(value)
                elif isinstance(value, _dt.timedelta):
                    value = value.total_seconds() / 86400
                elif value is not None and not isinstance(value, (int, float, str, bool)):
                    value = str(value)
                style = _import_style(book, xc, style_cache) if xc.has_style else 0
                if value is None and formula is None and not style:
                    continue
                sheet.cells[(r, c)] = Cell(value, formula, style)
                if xc.comment is not None:
                    sheet.comments[(r, c)] = xc.comment.text
        for letter, dim in ws.column_dimensions.items():
            lo, hi = (dim.min or R.col_index(letter) + 1), (dim.max or R.col_index(letter) + 1)
            for col in range(lo - 1, min(hi, lo + 16384) if hi else lo):
                if col >= R.MAX_COLS:
                    break
                if dim.width and dim.customWidth is not False:
                    sheet.cols.sizes[col] = _px_width(dim.width)
                if dim.hidden:
                    sheet.cols.hidden.add(col)
        for number, dim in ws.row_dimensions.items():
            if dim.height:
                sheet.rows.sizes[number - 1] = round(dim.height * 96 / 72, 1)
            if dim.hidden:
                sheet.rows.hidden.add(number - 1)
        sheet.rows.changed()
        sheet.cols.changed()
        sheet.merges = [(m.min_row - 1, m.min_col - 1, m.max_row - 1, m.max_col - 1) for m in ws.merged_cells.ranges]
        if ws.freeze_panes:
            cell = R.parse_cell(str(ws.freeze_panes))
            if cell:
                sheet.freeze = cell
        if ws.auto_filter is not None and ws.auto_filter.ref:
            parsed = R.parse_range(ws.auto_filter.ref)
            if parsed:
                sheet.autofilter = parsed[1]
        sheet.protected = bool(ws.protection.sheet)
        _import_validations(ws, sheet)
        rest = _import_cond_formats(ws, sheet)
        if rest and "mises en forme conditionnelles non reconnues" not in lost:
            lost.append("mises en forme conditionnelles non reconnues")
        if progress:
            progress((index + 1) / len(wb.worksheets))
    try:
        for name, item in wb.defined_names.items():
            if item.attr_text and not name.startswith("_xlnm"):
                book.names[name] = strip_prefixes(item.attr_text)
    except Exception:                                      # noqa: BLE001 - noms illisibles : ignorés, signalés
        lost.append("noms définis illisibles")
    try:
        if wb.calculation is not None and wb.calculation.calcMode == "manual":
            book.calc_mode = "manual"
    except Exception:                                      # noqa: BLE001
        pass
    label = "graphiques du fichier (non importés)"
    if label in lost:
        if _restore_charts(wb, book):
            lost.remove(label)                             # graphiques écrits par le module : relus tels quels
        else:
            from .io_xlsx_charts import read_charts
            problems = read_charts(path, book)             # graphiques d'Excel : relus depuis le XML
            lost.remove(label)
            for problem in sorted(set(problems)):
                lost.append("graphique : " + problem)
        if "images / formes" in lost and not any(n.startswith("xl/media/") for n in names):
            lost.remove("images / formes")                 # parties « drawings » = graphiques seulement
    if not book.sheets:
        book.add_sheet()
    return book


CHART_PROP = "fm_tableur.charts"


def _store_charts(wb, book):
    """Graphiques du module gardés dans les propriétés personnalisées du classeur (morceaux de 250 caractères,
    limite d'Excel) : relus à l'import (openpyxl ne lit pas les graphiques d'un fichier)."""
    import json
    data = {s.name: s.charts for s in book.sheets if s.charts}
    if not data:
        return
    try:
        from openpyxl.packaging.custom import StringProperty
        text = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
        for i in range(0, len(text), 250):
            wb.custom_doc_props.append(StringProperty(name=f"{CHART_PROP}.{i // 250:04d}", value=text[i:i + 250]))
    except Exception:                                      # noqa: BLE001 - graphiques Excel écrits quand même
        pass


def _restore_charts(wb, book) -> bool:
    import json
    try:
        parts = sorted((p.name, p.value) for p in wb.custom_doc_props.props if p.name.startswith(CHART_PROP))
    except Exception:                                      # noqa: BLE001
        return False
    if not parts:
        return False
    try:
        data = json.loads("".join(v for _n, v in parts))
    except ValueError:
        return False
    for name, charts in data.items():
        sheet = book.sheet(name)
        if sheet is not None and isinstance(charts, list):
            sheet.charts = [dict(c) for c in charts if isinstance(c, dict)]
    return True


def _import_style(book, xc, cache) -> int:
    key = xc.style_id if hasattr(xc, "style_id") else None
    if key is not None and key in cache:
        return cache[key]
    style = {}
    f = xc.font
    if f is not None:
        if f.name and f.name != "Calibri":
            style["font"] = f.name
        if f.sz and float(f.sz) != 11:
            style["size"] = float(f.sz)
        if f.b:
            style["bold"] = True
        if f.i:
            style["italic"] = True
        if f.u and f.u != "none":
            style["underline"] = True
        if f.strike:
            style["strike"] = True
        color = _color(f.color)
        if color and color != "#000000":
            style["color"] = color
    fill = xc.fill
    if fill is not None and getattr(fill, "fill_type", None) == "solid":
        color = _color(fill.fgColor)
        if color:
            style["fill"] = color
    a = xc.alignment
    if a is not None:
        if a.horizontal and a.horizontal != "general":
            style["halign"] = a.horizontal
        if a.vertical and a.vertical != "bottom":
            style["valign"] = a.vertical
        if a.wrap_text:
            style["wrap"] = True
        if a.indent:
            style["indent"] = int(a.indent)
        if a.text_rotation:
            style["rotation"] = int(a.text_rotation)
    b = xc.border
    if b is not None:
        for key, side in (("border_l", b.left), ("border_r", b.right), ("border_t", b.top), ("border_b", b.bottom)):
            if side is not None and side.style:
                style[key] = (side.style, _color(side.color) or "#000000")
    if xc.number_format and xc.number_format != "General":
        style["fmt"] = xc.number_format
    p = xc.protection
    if p is not None:
        if p.locked is False:
            style["locked"] = False
        if p.hidden:
            style["hidden_formula"] = True
    index = book.styles.intern(style)
    if key is not None:
        cache[key] = index
    return index


def _ranges_of(sqref) -> list[tuple]:
    out = []
    for part in str(sqref).split():
        parsed = R.parse_range(part)
        if parsed:
            out.append(parsed[1])
    return out


def _import_validations(ws, sheet):
    try:
        items = ws.data_validations.dataValidation
    except AttributeError:
        return
    for dv in items:
        if dv.type == "list" and dv.formula1:
            text = dv.formula1
            if text.startswith('"') and text.endswith('"'):
                values = [v.strip() for v in text[1:-1].split(",")]
                sheet.validations.append({"type": "list", "values": values, "ranges": _ranges_of(dv.sqref)})
            else:
                sheet.validations.append({"type": "list_ref", "source": text, "ranges": _ranges_of(dv.sqref)})


_OPS = {"between": "between", "notBetween": "notBetween", "equal": "equal", "notEqual": "notEqual",
        "greaterThan": "greaterThan", "lessThan": "lessThan", "greaterThanOrEqual": "greaterThanOrEqual",
        "lessThanOrEqual": "lessThanOrEqual"}


def _dxf_style(rule) -> dict:
    style = {}
    dxf = getattr(rule, "dxf", None)
    if dxf is None:
        return style
    if dxf.fill is not None:
        color = _color(dxf.fill.bgColor) or _color(dxf.fill.fgColor)
        if color:
            style["fill"] = color
    if dxf.font is not None:
        color = _color(dxf.font.color)
        if color:
            style["color"] = color
        if dxf.font.b:
            style["bold"] = True
        if dxf.font.i:
            style["italic"] = True
    return style


def _import_cond_formats(ws, sheet) -> int:
    rest = 0
    try:
        items = list(ws.conditional_formatting)
    except Exception:                                      # noqa: BLE001
        return 0
    for cf in items:
        ranges = _ranges_of(cf.sqref)
        for rule in cf.rules:
            out = {"ranges": ranges, "style": _dxf_style(rule), "stop": bool(rule.stopIfTrue)}
            t = rule.type
            if t == "cellIs" and rule.operator in _OPS and rule.formula:
                out.update(type="cell", op=_OPS[rule.operator], value=strip_prefixes(rule.formula[0]).strip('"'))
                if len(rule.formula) > 1:
                    out["value2"] = rule.formula[1].strip('"')
            elif t == "expression" and rule.formula:
                out.update(type="formula", formula="=" + strip_prefixes(rule.formula[0]))
            elif t in ("duplicateValues", "uniqueValues"):
                out.update(type="duplicate" if t == "duplicateValues" else "unique")
            elif t == "top10":
                out.update(type="bottom" if rule.bottom else "top", rank=int(rule.rank or 10),
                           percent=bool(rule.percent))
            elif t == "aboveAverage":
                out.update(type="below_average" if rule.aboveAverage is False else "above_average")
            elif t == "containsText":
                out.update(type="text", op="contains", value=rule.text or "")
            elif t == "dataBar" and rule.dataBar is not None:
                out.update(type="bar", color=_color(rule.dataBar.color) or "#638ec6")
            elif t == "colorScale" and rule.colorScale is not None:
                out.update(type="scale", colors=[_color(c) or "#ffffff" for c in rule.colorScale.color])
            else:
                rest += 1
                continue
            sheet.cond_formats.append(out)
    return rest


# ---------------------------------------------------------------- export
def write(book: Workbook, path) -> list[str]:
    """Modèle -> classeur Excel (.xlsx). Écriture atomique. Rend les avertissements (éléments non exportés)."""
    import openpyxl
    from openpyxl.comments import Comment
    from openpyxl.workbook.defined_name import DefinedName
    path = Path(path)
    warnings = []
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    cache: dict = {}
    for sheet in book.sheets:
        ws = wb.create_sheet(sheet.name[:31])
        if sheet.hidden:
            ws.sheet_state = "hidden"
        if sheet.tab_color:
            ws.sheet_properties.tabColor = sheet.tab_color.lstrip("#").upper()
        ws.sheet_view.showGridLines = bool(sheet.show_grid)
        if sheet.zoom != 1.0:
            ws.sheet_view.zoomScale = int(round(sheet.zoom * 100))
        for (r, c), cell in sheet.cells.items():
            xc = ws.cell(row=r + 1, column=c + 1)
            if cell.formula:
                xc.value = add_prefixes(cell.formula)
            else:
                value = cell.value
                if isinstance(value, V.XLError):
                    xc.value = value.code
                    xc.data_type = "e"
                elif value is not None:
                    xc.value = value
            if cell.style:
                _export_style(book, xc, cell.style, cache)
            comment = sheet.comments.get((r, c))
            if comment:
                xc.comment = Comment(comment, "fm_tableur")
        for (r, c), text in sheet.comments.items():
            if (r, c) not in sheet.cells:
                ws.cell(row=r + 1, column=c + 1).comment = Comment(text, "fm_tableur")
        for col, size in sheet.cols.sizes.items():
            ws.column_dimensions[R.col_name(col)].width = _chars_width(size)
        for col in sheet.cols.hidden:
            ws.column_dimensions[R.col_name(col)].hidden = True
        for row, size in sheet.rows.sizes.items():
            ws.row_dimensions[row + 1].height = round(size * 72 / 96, 2)
        for row in sheet.rows.hidden:
            ws.row_dimensions[row + 1].hidden = True
        for axis_styles, is_col in ((sheet.cols.styles, True), (sheet.rows.styles, False)):
            if axis_styles:
                warnings.append("mise en forme de lignes / colonnes entières : seulement sur les cellules remplies")
        for m in sheet.merges:
            ws.merge_cells(start_row=m[0] + 1, start_column=m[1] + 1, end_row=m[2] + 1, end_column=m[3] + 1)
        if sheet.freeze != (0, 0):
            ws.freeze_panes = R.cell_name(sheet.freeze[0], sheet.freeze[1])
        if sheet.autofilter:
            ws.auto_filter.ref = R.range_name(*sheet.autofilter)
        if sheet.protected:
            ws.protection.sheet = True
        _export_validations(ws, sheet)
        _export_cond_formats(ws, sheet, warnings)
        if sheet.charts:
            from .charts import export_charts
            export_charts(ws, sheet, warnings)
    for name, text in book.names.items():
        try:
            wb.defined_names[name] = DefinedName(name, attr_text=add_prefixes(text.lstrip("=")))
        except Exception:                                  # noqa: BLE001
            warnings.append(f"nom défini non exporté : {name}")
    _store_charts(wb, book)
    try:
        wb.calculation.fullCalcOnLoad = True               # Excel recalcule tout à l'ouverture
        if book.calc_mode == "manual":
            wb.calculation.calcMode = "manual"
    except Exception:                                      # noqa: BLE001
        pass
    if any(_has_dynamic(c.formula) for _s, _k, c in book.formula_cells()):
        warnings.append("formules à débordement (FILTER, SORT, SEQUENCE…) : Excel peut les afficher avec « @ »")
    tmp = path.with_name(path.name + ".part")
    wb.save(tmp)
    os.replace(tmp, path)
    return sorted(set(warnings))


def _has_dynamic(formula):
    from .engine import _DYNAMIC
    return bool(formula and _DYNAMIC.search(formula))


def _export_style(book, xc, index, cache):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
    found = cache.get(index)
    if found is None:
        s = book.styles.get(index)
        font = Font(name=s.get("font") or book.default_font[0], sz=s.get("size") or book.default_font[1],
                    b=bool(s.get("bold")), i=bool(s.get("italic")), u="single" if s.get("underline") else None,
                    strike=bool(s.get("strike")), color=(s["color"].lstrip("#").upper() if s.get("color") else None))
        fill = PatternFill("solid", fgColor=s["fill"].lstrip("#").upper()) if s.get("fill") else None
        align = None
        if any(k in s for k in ("halign", "valign", "wrap", "indent", "rotation")):
            align = Alignment(horizontal=s.get("halign"), vertical=s.get("valign"), wrap_text=bool(s.get("wrap")),
                              indent=int(s.get("indent") or 0), text_rotation=int(s.get("rotation") or 0))
        border = None
        if any(k in s for k in ("border_l", "border_r", "border_t", "border_b")):
            def side(key):
                line = s.get(key)
                if not line:
                    return Side()
                return Side(style=line[0], color=str(line[1]).lstrip("#").upper())
            border = Border(left=side("border_l"), right=side("border_r"), top=side("border_t"),
                            bottom=side("border_b"))
        protection = None
        if s.get("locked") is False or s.get("hidden_formula"):
            protection = Protection(locked=s.get("locked") is not False, hidden=bool(s.get("hidden_formula")))
        found = cache[index] = (font, fill, align, border, s.get("fmt"), protection)
    font, fill, align, border, fmt, protection = found
    xc.font = font
    if fill is not None:
        xc.fill = fill
    if align is not None:
        xc.alignment = align
    if border is not None:
        xc.border = border
    if fmt:
        xc.number_format = fmt
    if protection is not None:
        xc.protection = protection


def _export_validations(ws, sheet):
    from openpyxl.worksheet.datavalidation import DataValidation
    for rule in sheet.validations:
        sqref = " ".join(R.range_name(*r) for r in rule.get("ranges", []))
        if not sqref:
            continue
        if rule.get("type") == "list":
            dv = DataValidation(type="list", formula1='"' + ",".join(str(v) for v in rule["values"]) + '"',
                                allow_blank=True)
        elif rule.get("type") == "list_ref":
            dv = DataValidation(type="list", formula1=rule.get("source", ""), allow_blank=True)
        else:
            continue
        dv.add(sqref)
        ws.add_data_validation(dv)


def _export_cond_formats(ws, sheet, warnings):
    from openpyxl.formatting.rule import (CellIsRule, ColorScaleRule, DataBarRule, FormulaRule, Rule)
    from openpyxl.styles import Font, PatternFill
    from openpyxl.styles.differential import DifferentialStyle
    for rule in sheet.cond_formats:
        sqref = " ".join(R.range_name(*r) for r in rule.get("ranges", []))
        if not sqref:
            continue
        st = rule.get("style") or {}
        font = Font(color=st["color"].lstrip("#").upper(), b=bool(st.get("bold"))) if st.get("color") or \
            st.get("bold") else None
        fill = PatternFill(bgColor=st["fill"].lstrip("#").upper()) if st.get("fill") else None
        kind = rule.get("type")
        try:
            if kind == "cell":
                values = [_cf_value(rule.get("value"))] + ([_cf_value(rule["value2"])] if rule.get("value2")
                                                           is not None else [])
                xrule = CellIsRule(operator=rule.get("op", "greaterThan"), formula=values, font=font, fill=fill)
            elif kind == "formula":
                xrule = FormulaRule(formula=[add_prefixes(rule["formula"].lstrip("="))], font=font, fill=fill)
            elif kind == "bar":
                xrule = DataBarRule(start_type="min", end_type="max", color=rule.get("color", "#638ec6")
                                    .lstrip("#").upper())
            elif kind == "scale":
                colors = [c.lstrip("#").upper() for c in rule.get("colors", [])]
                if len(colors) == 3:
                    xrule = ColorScaleRule(start_type="min", start_color=colors[0], mid_type="percentile",
                                           mid_value=50, mid_color=colors[1], end_type="max", end_color=colors[2])
                else:
                    xrule = ColorScaleRule(start_type="min", start_color=colors[0], end_type="max",
                                           end_color=colors[-1])
            elif kind in ("duplicate", "unique", "top", "bottom", "above_average", "below_average", "text"):
                dxf = DifferentialStyle(font=font, fill=fill)
                xtype = {"duplicate": "duplicateValues", "unique": "uniqueValues", "top": "top10",
                         "bottom": "top10", "above_average": "aboveAverage", "below_average": "aboveAverage",
                         "text": "containsText"}[kind]
                xrule = Rule(type=xtype, dxf=dxf)
                if kind in ("top", "bottom"):
                    xrule.rank = int(rule.get("rank", 10))
                    xrule.bottom = kind == "bottom"
                    xrule.percent = bool(rule.get("percent"))
                if kind == "below_average":
                    xrule.aboveAverage = False
                if kind == "text":
                    xrule.operator = "containsText"
                    xrule.text = rule.get("value", "")
                    first = R.cell_name(rule["ranges"][0][0], rule["ranges"][0][1])
                    xrule.formula = [f'NOT(ISERROR(SEARCH("{rule.get("value", "")}",{first})))']
            else:
                warnings.append(f"mise en forme conditionnelle non exportée : {kind}")
                continue
        except Exception as exc:                           # noqa: BLE001
            warnings.append(f"mise en forme conditionnelle non exportée ({kind}) : {exc}")
            continue
        ws.conditional_formatting.add(sqref, xrule)


def _cf_value(value):
    if value is None:
        return "0"
    try:
        float(str(value).replace(",", "."))
        return str(value).replace(",", ".")
    except ValueError:
        return '"' + str(value).replace('"', '""') + '"'

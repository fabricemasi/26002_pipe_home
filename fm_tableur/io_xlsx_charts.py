"""Graphiques d'un fichier Excel (SANS Qt) : openpyxl ne les lit pas ; ce module lit le XML de l'archive
(`xl/charts/chartN.xml` via les relations feuille -> dessin -> graphique) et les rend LIÉS aux données dans le
module (voir `charts.py`) : type, plage des séries et des catégories, titre, légende, ancrage, taille.

Pris en charge : histogrammes / barres (groupés), courbes, aires, secteurs (et anneaux, affichés en secteurs),
nuages de points, graphiques combinés barres + courbes. Une plage n'est reprise que si les séries sont des
colonnes (ou des lignes) CONTIGUËS d'une même feuille ; sinon le graphique est compté comme non repris (signalé).
Rien n'est exécuté ; une partie illisible est ignorée (signalée)."""
from __future__ import annotations

import posixpath
import uuid
import xml.etree.ElementTree as ET
import zipfile

from . import refs as R

NS = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
EMU_PER_PX = 9525
KINDS = {"barChart": "column", "bar3DChart": "column", "lineChart": "line", "line3DChart": "line",
         "areaChart": "area", "area3DChart": "area", "pieChart": "pie", "pie3DChart": "pie", "doughnutChart": "pie",
         "scatterChart": "scatter"}


def _rels(archive, part) -> dict:
    folder, name = posixpath.split(part)
    path = posixpath.join(folder, "_rels", name + ".rels")
    try:
        root = ET.fromstring(archive.read(path))
    except (KeyError, ET.ParseError):
        return {}
    out = {}
    for rel in root.findall("rel:Relationship", NS):
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            continue
        out[rel.get("Id")] = posixpath.normpath(posixpath.join(folder, target)) if not target.startswith("/") \
            else target.lstrip("/")
    return out


def _sheet_parts(archive) -> dict:
    """Nom de feuille -> partie XML de la feuille."""
    root = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = _rels(archive, "xl/workbook.xml")
    out = {}
    for sheet in root.findall("m:sheets/m:sheet", NS):
        rid = sheet.get(f"{{{NS['r']}}}id")
        if rid in rels:
            out[sheet.get("name")] = rels[rid]
    return out


def _text(node) -> str:
    return "".join(t.text or "" for t in node.iter(f"{{{NS['a']}}}t")) if node is not None else ""


def _ref(node, tag) -> str | None:
    target = node.find(f"c:{tag}", NS)
    if target is None:
        return None
    f = target.find(".//c:f", NS)
    return f.text if f is not None else None


def _bounds(ref_text):
    parsed = R.parse_range(ref_text.replace("$", "")) if ref_text else None
    return parsed


def _chart_from_xml(xml: bytes):
    root = ET.fromstring(xml)
    plot = root.find(".//c:plotArea", NS)
    if plot is None:
        return None, "graphique sans zone de tracé"
    groups = [child for child in plot if child.tag.split("}")[1] in KINDS]
    if not groups:
        return None, "type de graphique non pris en charge"
    kinds = [KINDS[g.tag.split("}")[1]] for g in groups]
    if kinds[0] == "column":
        direction = groups[0].find("c:barDir", NS)
        if direction is not None and direction.get("val") == "bar":
            kinds[0] = "bar"
    kind = "combo" if len(kinds) > 1 and kinds[0] in ("column", "bar") and "line" in kinds[1:] else kinds[0]
    sheet_name = None
    vals, cats, names = [], [], []
    for group in groups:
        for ser in group.findall("c:ser", NS):
            v = _ref(ser, "yVal" if kinds[0] == "scatter" else "val")
            c = _ref(ser, "xVal" if kinds[0] == "scatter" else "cat")
            t = ser.find("c:tx", NS)
            tx = t.find(".//c:f", NS).text if t is not None and t.find(".//c:f", NS) is not None else None
            for text, bucket in ((v, vals), (c, cats), (tx, names)):
                parsed = _bounds(text)
                if parsed is not None:
                    name, rect = parsed
                    if name:
                        sheet_name = sheet_name or name
                    bucket.append(rect)
    if not vals:
        return None, "graphique sans plage de valeurs lisible"
    r0 = min(r[0] for r in vals + cats + names)
    c0 = min(r[1] for r in vals + cats + names)
    r1 = max(r[2] for r in vals + cats + names)
    c1 = max(r[3] for r in vals + cats + names)
    columns = all(r[1] == r[3] for r in vals)
    count = sum((r[3] - r[1] + 1) if columns else (r[2] - r[0] + 1) for r in vals)
    span = (c1 - c0 + 1) if columns else (r1 - r0 + 1)
    if span > count + (1 if cats else 0):
        return None, "séries non contiguës (graphique non repris)"
    title = root.find(".//c:chart/c:title", NS)
    legend = root.find(".//c:chart/c:legend", NS)
    chart = {"id": uuid.uuid4().hex[:10], "type": kind, "data": R.range_name(r0, c0, r1, c1),
             "header": bool(names or cats), "series_in": "cols" if columns else "rows",
             "title": _text(title), "legend": legend is not None, "anchor": [0, 0], "size": [480, 288]}
    return (sheet_name, chart), None


def read_charts(path, book) -> list[str]:
    """Graphiques du fichier ajoutés aux feuilles de `book` ; rend les messages des graphiques non repris."""
    problems = []
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return problems
    with archive:
        try:
            sheets = _sheet_parts(archive)
        except (KeyError, ET.ParseError):
            return ["graphiques : classeur illisible"]
        for name, part in sheets.items():
            sheet = book.sheet(name)
            if sheet is None:
                continue
            for drawing in _rels(archive, part).values():
                if "/drawings/" not in drawing:
                    continue
                try:
                    root = ET.fromstring(archive.read(drawing))
                except (KeyError, ET.ParseError):
                    problems.append("dessin illisible")
                    continue
                chart_rels = _rels(archive, drawing)
                for anchor in list(root):
                    frame = anchor.find(".//c:chart", NS)
                    if frame is None:
                        continue
                    target = chart_rels.get(frame.get(f"{{{NS['r']}}}id"))
                    if target is None:
                        continue
                    try:
                        found, problem = _chart_from_xml(archive.read(target))
                    except (KeyError, ET.ParseError):
                        found, problem = None, "graphique illisible"
                    if found is None:
                        problems.append(problem)
                        continue
                    _ref_sheet, chart = found
                    start = anchor.find("xdr:from", NS)
                    if start is not None:
                        chart["anchor"] = [int(start.findtext("xdr:row", "0", NS)),
                                           int(start.findtext("xdr:col", "0", NS))]
                    end = anchor.find("xdr:to", NS)
                    ext = anchor.find("xdr:ext", NS)
                    if ext is not None:
                        chart["size"] = [round(int(ext.get("cx", "0")) / EMU_PER_PX) or 480,
                                         round(int(ext.get("cy", "0")) / EMU_PER_PX) or 288]
                    elif end is not None and start is not None:
                        r0, c0 = chart["anchor"]
                        r1 = int(end.findtext("xdr:row", "0", NS))
                        c1 = int(end.findtext("xdr:col", "0", NS))
                        chart["size"] = [max(120, round(sheet.cols.pos(c1) - sheet.cols.pos(c0))),
                                         max(80, round(sheet.rows.pos(r1) - sheet.rows.pos(r0)))]
                    if _ref_sheet and _ref_sheet.lower() != name.lower():
                        chart["data"] = R.quote_sheet(_ref_sheet) + "!" + chart["data"]
                    sheet.charts.append(chart)
    return problems

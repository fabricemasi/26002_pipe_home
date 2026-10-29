"""Journal quotidien des rendus et tableau de consultation.

Carte et pièges : docs/agents/apercus.md.
"""

import html
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHeaderView, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout

def _render_log_line(message: str) -> str:
    """Horodate une entree du journal avec l'heure locale de l'application."""
    return f"[{datetime.now():%H:%M:%S}] {message.rstrip(chr(13) + chr(10))}"

def _render_log_path(directory: Path) -> Path:
    return directory / f"pipeline_preview_render_{datetime.now():%Y-%m-%d}.html"

_RENDER_LOG_LOCK = threading.Lock()

def _update_render_log_rows(rows: list, message: str, source: str = "", media_type: str = "image",
                            render_mode: str = "", output_path: str = "", root: Path | None = None) -> int | None:
    message = message.strip()
    if not message or set(message) == {"-"}:
        return None
    stamp = datetime.now().strftime("%H:%M:%S")
    timestamp = re.match(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$", message, re.S)
    if timestamp:
        stamp, message = timestamp.groups()
    started = message.startswith("> Aperçu en cours : ")
    if started:
        source = message.split(": ", 1)[1]
    progress = re.match(r"^\[\s*(\d+%|---)\]\s*(.*?) — (.*)$", message, re.S)
    filename = Path(source).name if source else (progress.group(2) if progress else "—")
    detail = progress.group(3) if progress else message
    index = next((i for i in range(len(rows) - 1, -1, -1)
                  if (rows[i]["source"] == source if source else rows[i]["file"] == filename)), None)
    if started or index is None:
        rows.append({"start": stamp, "end": "", "source": source, "file": filename,
                     "type": "Turntable" if media_type == "turntable" else "Image",
                     "progress": "—", "state": "En cours", "details": []})
        index = len(rows) - 1
    row = rows[index]
    if source:
        location = Path(source)
        if root is not None:
            try:
                location = location.relative_to(root)
            except ValueError:
                pass
        row["location"] = location.as_posix()
    if render_mode:
        row["poly"] = "High poly" if render_mode == "high" else "Low poly"
    if output_path:
        row["output_directory"] = str(Path(output_path).parent)
        row["output_name"] = Path(output_path).name
    if media_type == "turntable" or "turntable" in detail.casefold():
        row["type"] = "Turntable"
    if progress:
        row["progress"] = progress.group(1)
    lowered = detail.casefold()
    if "interrompu" in lowered or "annul" in lowered:
        row["state"], row["end"] = "Interrompu", stamp
    elif any(word in lowered for word in ("erreur", "échec", "echec", "indisponible", "aucun rendu")):
        row["state"], row["end"] = "Échec", stamp
    elif progress and progress.group(1) == "100%":
        row["state"], row["end"] = "Terminé", stamp
    row["details"].append(f"[{stamp}] {detail}")
    return index

_RENDER_LOG_COLUMNS = ["Emplacement du fichier", "Heure de démarrage", "Heure de fin",
                       "Low / High poly", "Image / Turntable", "Emplacement du fichier généré",
                       "Nom du fichier généré", "Progression", "État"]

def _render_log_values(row: dict) -> list[str]:
    return [row.get("location") or row.get("source") or row.get("file", "—"),
            row["start"], row["end"] or "—", row.get("poly") or "—", row["type"],
            row.get("output_directory") or "—", row.get("output_name") or "—",
            row.get("progress") or "—", row["state"]]

def _render_log_html(rows: list, title: str) -> str:
    body = []
    for row in rows:
        details = "\n".join(row["details"])
        values = _render_log_values(row)
        cells = "".join(f"<td>{html.escape(value)}</td>" for value in values[:-1])
        body.append(f'<tr title="{html.escape(row["source"], quote=True)}">{cells}'
                    f'<td><details><summary>{html.escape(values[-1])}</summary><pre>{html.escape(details)}</pre></details></td></tr>')
    data = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    return ("<!doctype html><html lang='fr'><meta charset='utf-8'>"
            f"<title>{html.escape(title)}</title><style>"
            "body{background:#1a1c1e;color:#ddd;font:14px system-ui;padding:24px}"
            "table{border-collapse:collapse;width:100%}th,td{border:1px solid #45494d;padding:9px;text-align:left;vertical-align:top}"
            "th{background:#303438;position:sticky;top:0}tr:nth-child(even){background:#24272a}"
            "summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}"
            "</style><body>" + f"<h2>{html.escape(title)}</h2><table><thead><tr>"
            + "".join(f"<th>{html.escape(name)}</th>" for name in _RENDER_LOG_COLUMNS) +
            "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
            f'<script id="render-data" type="application/json">{data}</script></body></html>')

def _read_render_log_entries(path: Path) -> list:
    # Certains messages Blender contiennent des octets Windows-1252 au
    # milieu du journal UTF-8 : conserver les accents UTF-8 deja valides.
    content = path.read_bytes().decode("utf-8-sig", errors="surrogateescape")
    content = re.sub(r"[\udc80-\udcff]", lambda match:
                     bytes([ord(match.group()) - 0xdc00]).decode("cp1252", errors="replace"), content)
    match = re.search(r'<script id="render-data" type="application/json">(.*?)</script>', content, re.S)
    return json.loads(match.group(1)) if match else []

def _write_render_log(directory: Path, message: str = "", source: str = "", media_type: str = "image",
                     render_mode: str = "", output_path: str = "") -> Path:
    with _RENDER_LOG_LOCK:
        path = _render_log_path(directory)
        rows = []
        if path.is_file():
            rows = _read_render_log_entries(path)
        if message:
            _update_render_log_rows(rows, message, source, media_type, render_mode, output_path, directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(_render_log_html(rows, f"Rendus du {datetime.now():%Y-%m-%d}"), encoding="utf-8")
        temporary.replace(path)
        return path

class _RenderLogTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, len(_RENDER_LOG_COLUMNS), parent)
        self._entries = []
        self.setHorizontalHeaderLabels(_RENDER_LOG_COLUMNS)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate([280, 155, 125, 130, 140, 300, 230, 100, 130]):
            self.setColumnWidth(column, width)
        self.setWordWrap(False)
        self.cellDoubleClicked.connect(self._show_details)

    def clear(self):
        self._entries.clear()
        self.setRowCount(0)

    def appendPlainText(self, message, **metadata):
        index = _update_render_log_rows(self._entries, message, **metadata)
        if index is None:
            return
        self.setRowCount(len(self._entries))
        self._display_entry(index)

    def load_entries(self, entries):
        self.clear()
        self._entries = entries
        self.setRowCount(len(entries))
        for index in range(len(entries)):
            self._display_entry(index)

    def _display_entry(self, index):
        row = self._entries[index]
        values = _render_log_values(row)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(row["source"] + "\n" + "\n".join(row["details"]))
            self.setItem(index, column, item)
        self.setRowHeight(index, max(40, self.fontMetrics().height() * 2 + 8))

    def ensureCursorVisible(self):
        if self.rowCount():
            self.scrollToItem(self.item(self.rowCount() - 1, 0))

    def _show_details(self, row, column):
        dialog = QDialog(self)
        dialog.setWindowTitle("Détails du rendu — " + self._entries[row]["file"])
        dialog.resize(760, 460)
        layout = QVBoxLayout(dialog)
        details = QPlainTextEdit(dialog)
        details.setReadOnly(True)
        details.setPlainText(self._entries[row]["source"] + "\n\n" + "\n".join(self._entries[row]["details"]))
        layout.addWidget(details)
        dialog.exec()

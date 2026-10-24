"""État visible et journal des tâches de fond ; écritures hors du fil de l'interface."""
from datetime import datetime
from pathlib import Path
import queue
import threading
import html
import re
from urllib.parse import unquote
from PySide6.QtCore import QObject, Signal, QUrl, Qt, QProcess, QAbstractTableModel, QModelIndex, QByteArray
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QDialog,
                               QTableView, QHeaderView, QLineEdit, QComboBox)

LOG_PATH = Path(__file__).resolve().parent / 'data' / 'background_tasks.html'
_WINDOW_GEOMETRY_KEY = 'background_tasks_geometry'
_COLUMNS_STATE_KEY = 'background_tasks_columns'
_queue = queue.Queue()
_ORDER_STYLE = ('<style id="recent-first-aligned">table{width:100%}'
                'tbody{display:flex;flex-direction:column-reverse;width:100%}'
                'tr{display:grid;grid-template-columns:110px 28px 90px 28px 380px 28px minmax(300px,1fr);width:100%}'
                'td{display:block;min-width:0;box-sizing:border-box;overflow-wrap:anywhere}'
                'tbody td.task{white-space:normal}a{color:#80bfff}</style>\n')

_FILTERS = '''
<style>
#log-filters{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:16px 0}
#log-filters label{display:flex;align-items:center;gap:8px}
#log-filters input,#log-filters select,#log-filters button{background:#262626;color:#fff;
border:1px solid #555;border-radius:4px;padding:6px;color-scheme:dark}
tr[hidden]{display:none!important}#log-count{color:#bbb}
</style>
<form id="log-filters">
<label>Date <input id="filter-date" type="date"></label>
<label>De <input id="filter-from" type="time" step="1"></label>
<label>À <input id="filter-until" type="time" step="1"></label>
<label>Type <select id="filter-type"><option value="">Tous les types</option></select></label>
<button type="reset">Tout réafficher</button><span id="log-count" aria-live="polite"></span>
</form>
<script>
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('log-filters');
  const date = document.getElementById('filter-date');
  const from = document.getElementById('filter-from');
  const until = document.getElementById('filter-until');
  const type = document.getElementById('filter-type');
  const count = document.getElementById('log-count');
  const rows = Array.from(document.querySelectorAll('tbody tr')).map(row => ({
    row, date: row.cells[0]?.textContent.trim() || '',
    time: row.cells[2]?.textContent.trim() || '',
    type: (row.querySelector('.task')?.textContent || '').split(' · ')[0].trim()
  }));
  [...new Set(rows.map(r => r.type).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'fr')).forEach(name => {
    type.add(new Option(name,name));
  });
  function apply() {
    let visible = 0;
    const start = from.value.length === 5 ? from.value + ':00' : from.value;
    const end = until.value.length === 5 ? until.value + ':59' : until.value;
    for (const r of rows) {
      const hourOK = start && end && start > end ? (r.time >= start || r.time <= end)
        : ((!start || r.time >= start) && (!end || r.time <= end));
      const show = (!date.value || r.date === date.value) && (!type.value || r.type === type.value) && hourOK;
      r.row.hidden = !show;
      if(show) visible++;
    }
    count.textContent = visible + ' / ' + rows.length + ' entrées';
  }
  form.addEventListener('submit', e => e.preventDefault());
  form.addEventListener('input', apply);
  form.addEventListener('change', apply);
  form.addEventListener('reset', () => setTimeout(apply,0));
  apply();
});
</script>
'''


def _strip_html(value):
    return html.unescape(re.sub(r'<[^>]*>', '', value)).strip()


def _folder_of_file(file):
    """Dossier contenant le fichier traité, même pour les anciennes entrées HTML."""
    value = str(file or '').strip()
    if not value or value == '—':
        return ''
    try:
        return str(Path(value).absolute().parent)
    except (TypeError, ValueError):
        return ''


def _log_rows():
    """Lit le journal déjà écrit, sans démarrer Chromium.

    Le fichier est append-only et ses cellules sont produites par ``report`` :
    ce petit lecteur est donc volontairement beaucoup plus léger qu'une page
    WebEngine et reste immédiat même avec plusieurs milliers de tâches.
    """
    if not LOG_PATH.exists():
        return []
    try:
        content = LOG_PATH.read_text(encoding='utf-8')
    except OSError:
        return []
    rows = []
    for raw_row in re.findall(r'<tr>(.*?)</tr>', content, flags=re.S | re.I):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', raw_row, flags=re.S | re.I)
        if len(cells) < 7:
            continue
        task = _strip_html(cells[4])
        task_type, separator, message = task.partition(' · ')
        href = re.search(r'<a\s+[^>]*href=["\']([^"\']+)', cells[6], flags=re.I)
        file_name = _strip_html(cells[6]).replace(' · Ouvrir le dossier', '')
        # Le chemin du fichier est la source de vérité. L'ancien href reste
        # seulement un secours pour les rares lignes dont le fichier n'était
        # pas enregistré dans le journal.
        folder = _folder_of_file(file_name)
        if href:
            linked_folder = QUrl(html.unescape(href.group(1))).toLocalFile()
            if not folder:
                folder = linked_folder
            if not folder:
                folder = unquote(html.unescape(href.group(1)).removeprefix('file:///')).replace('/', '\\')
        rows.append((cells[0].strip(), cells[2].strip(), task_type, message if separator else '', file_name, folder))
    return rows


class _LogModel(QAbstractTableModel):
    headers = ('Date', 'Heure', 'Type', 'Tâche', 'Fichier concerné', 'Dossier')

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.visible = list(range(len(rows) - 1, -1, -1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.visible)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[self.visible[index.row()]]
        column = index.column()
        if role == Qt.DisplayRole:
            if column == 5:
                return 'Ouvrir le dossier' if row[5] else ''
            return row[column]
        if role == Qt.ForegroundRole:
            if column == 2:
                from PySide6.QtGui import QColor
                return QColor('#ff9800')
            if column == 5 and row[5]:
                from PySide6.QtGui import QColor
                return QColor('#80bfff')
        if role == Qt.UserRole:
            return row[5]
        if role == Qt.ToolTipRole and column in (4, 5):
            return row[5] or row[4]
        return None

    def apply_filter(self, date='', after='', before='', task_type=''):
        def matches(row):
            if date and row[0] != date:
                return False
            if task_type and row[2] != task_type:
                return False
            if after and before and after > before:
                return row[1] >= after or row[1] <= before
            return (not after or row[1] >= after) and (not before or row[1] <= before)
        self.layoutAboutToBeChanged.emit()
        self.visible = [i for i in range(len(self.rows) - 1, -1, -1) if matches(self.rows[i])]
        self.layoutChanged.emit()


class _BackgroundLogDialog(QDialog):
    """Journal natif : le tableau Qt évite le coût de layout de WebEngine."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle('Tâches en fond')
        self.resize(1280, 760)
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.date = QLineEdit(self)
        self.after = QLineEdit(self)
        self.before = QLineEdit(self)
        self.date.setPlaceholderText('Date (AAAA-MM-JJ)')
        self.after.setPlaceholderText('De (HH:MM:SS)')
        self.before.setPlaceholderText('À (HH:MM:SS)')
        self.kind = QComboBox(self)
        reset = QPushButton('Tout réafficher', self)
        self.count = QLabel(self)
        for widget in (self.date, self.after, self.before, self.kind, reset, self.count):
            filters.addWidget(widget)
        filters.addStretch(1)
        layout.addLayout(filters)
        self.table = QTableView(self)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setStyleSheet(
            'QTableView { background:#161616; color:#ffffff; gridline-color:#333333; }'
            'QTableView::item { background:#161616; }'
            'QTableView::item:selected { background:#303030; }'
            'QHeaderView::section { background:#202020; color:#ffffff; border:1px solid #333333; padding:5px; }'
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        for section, width in enumerate((110, 90, 145, 300, 430, 145)):
            header.resizeSection(section, width)
        layout.addWidget(self.table)
        self.reload()
        self._restore_window_state()
        self.date.textChanged.connect(self.apply_filter)
        self.after.textChanged.connect(self.apply_filter)
        self.before.textChanged.connect(self.apply_filter)
        self.kind.currentTextChanged.connect(self.apply_filter)
        reset.clicked.connect(self.reset_filter)
        self.table.clicked.connect(self._open_folder)

    def reload(self):
        self.model = _LogModel(_log_rows(), self)
        self.table.setModel(self.model)
        self.kind.blockSignals(True)
        selected = self.kind.currentText()
        self.kind.clear()
        self.kind.addItem('Tous les types')
        self.kind.addItems(sorted({row[2] for row in self.model.rows if row[2]}, key=lambda value: value.lower()))
        self.kind.setCurrentText(selected if selected else 'Tous les types')
        self.kind.blockSignals(False)
        self.apply_filter()

    def reset_filter(self):
        for field in (self.date, self.after, self.before):
            field.clear()
        self.kind.setCurrentIndex(0)
        self.apply_filter()

    def apply_filter(self):
        self.model.apply_filter(self.date.text().strip(), self.after.text().strip(), self.before.text().strip(),
                                '' if self.kind.currentIndex() <= 0 else self.kind.currentText())
        self.count.setText(f'{self.model.rowCount()} / {len(self.model.rows)} entrées')

    def _open_folder(self, index):
        if index.column() != 5:
            return
        folder = self.model.data(index, Qt.UserRole)
        if folder:
            QProcess.startDetached('explorer.exe', [folder])

    def _restore_window_state(self):
        """Position, taille et largeurs hors des presets visuels de l'application."""
        try:
            from settings_store import _load_window_geometry
            geometry = _load_window_geometry(_WINDOW_GEOMETRY_KEY)
            columns = _load_window_geometry(_COLUMNS_STATE_KEY)
            if geometry:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode('ascii')))
            if columns:
                self.table.horizontalHeader().restoreState(QByteArray.fromBase64(columns.encode('ascii')))
        except (ImportError, TypeError, ValueError):
            pass

    def closeEvent(self, event):
        """Conserve les ajustements seulement quand l'utilisateur a fini son geste."""
        try:
            from settings_store import _save_window_geometry
            _save_window_geometry(bytes(self.saveGeometry().toBase64()).decode('ascii'), _WINDOW_GEOMETRY_KEY)
            header = self.table.horizontalHeader()
            _save_window_geometry(bytes(header.saveState().toBase64()).decode('ascii'), _COLUMNS_STATE_KEY)
        except (ImportError, TypeError, ValueError):
            pass
        super().closeEvent(event)


def _upgrade_log():
    """Ajoute les contrôles aux anciens journaux, en gardant toutes leurs entrées."""
    if not LOG_PATH.exists() or not LOG_PATH.stat().st_size:
        return
    with LOG_PATH.open('r', encoding='utf-8') as stream:
        header = stream.read(16384)
    if 'id="recent-first-aligned"' in header and 'id="log-filters"' in header:
        return
    previous = LOG_PATH.read_text(encoding='utf-8')
    if 'id="recent-first-aligned"' not in header:
        previous = re.sub(r'<style id="recent-first">.*?</style>\s*', '', previous, flags=re.S)
        previous = previous.replace('<table>', _ORDER_STYLE + '<table>', 1)
    if 'id="log-filters"' not in header:
        previous = previous.replace('<table>', _FILTERS + '<table>', 1)
    LOG_PATH.write_text(previous, encoding='utf-8')


def _writer():
    while True:
        line = _queue.get()
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            fresh = not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0
            if not fresh:
                _upgrade_log()
            with LOG_PATH.open('a', encoding='utf-8') as stream:
                if fresh:
                    stream.write('<!doctype html><meta charset="utf-8"><title>Tâches en fond</title>' + _ORDER_STYLE +
                        '<style>body{background:#161616;color:white;font:14px sans-serif}'
                        'table{border-collapse:collapse}td{padding:6px 10px;border-bottom:1px solid #333}'
                        '.task{color:#ff9800;white-space:nowrap}</style><h1>Tâches en fond</h1>' + _FILTERS + '<table><tbody>\n')
                stream.write(line + '\n')
        except OSError:
            pass
        finally:
            _queue.task_done()


threading.Thread(target=_writer, name='background-log', daemon=True).start()


class BackgroundStatus(QObject):
    changed = Signal(str, str)

    def __init__(self, inspector):
        super().__init__(inspector)
        self.inspector = inspector
        self.active = {}
        box = QWidget(inspector)
        layout = QVBoxLayout(box)
        self.progress = QProgressBar(box)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat('Réglages en mémoire : %p %')
        self.progress.setStyleSheet('QProgressBar { color: #ffffff; }')
        self.label = QLabel('Aucune tâche en fond', box)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        self.label.setStyleSheet('color: #ffffff;')
        button = QPushButton('Tâches en fond', box)
        button.clicked.connect(self.open_log)
        layout.addWidget(self.progress)
        layout.addWidget(self.label)
        layout.addWidget(button)
        inspector._outer_layout.addWidget(box)
        self.changed.connect(self._show)

    def report(self, task, message, file=''):
        name = {'video': 'Aperçu vidéo', 'moodboard': 'Moodboard', 'settings': 'Réglages',
                'journal': 'Journal'}.get(task, task)
        now = datetime.now()
        detail = str(file) if file else '—'
        if file:
            folder = QUrl.fromLocalFile(_folder_of_file(file)).toString()
            detail_html = html.escape(detail) + ' · <a href="' + html.escape(folder, quote=True) + '">Ouvrir le dossier</a>'
        else:
            detail_html = html.escape(detail)
        _queue.put('<tr><td>' + now.strftime('%Y-%m-%d') + '</td><td> - </td><td>' +
                   now.strftime('%H:%M:%S') + '</td><td> - </td><td class="task">' +
                   html.escape(name + ' · ' + message) + '</td><td> - </td><td>' +
                   detail_html + '</td></tr>')
        self.changed.emit(task, '<span style="color:#ff9800">' + html.escape(name) + '</span> : ' +
                          html.escape(message) + (f' — {html.escape(str(file))}' if file else ''))

    def finish(self, task, message):
        self.report(task, message)
        self.changed.emit(task, '')

    def _show(self, task, message):
        if message:
            self.active[task] = message
        else:
            self.active.pop(task, None)
        self.label.setText('<br>'.join(self.active.values()) or 'Aucune tâche en fond')

    def settings_progress(self, percent):
        if percent is None:
            self.progress.setFormat('Réglages en mémoire : %p %')
        else:
            self.progress.setValue(int(percent))
            self.progress.setFormat('Chargement des réglages : %p %')

    def open_log(self):
        def open_ready():
            self._open_log_window()
        # Le fichier est créé par le même worker que les entrées du journal.
        self.report('journal', 'Ouverture du journal des tâches en fond')
        from PySide6.QtCore import QTimer
        timer = QTimer(self)
        timer.setInterval(25)
        def check():
            if not _queue.unfinished_tasks:
                timer.stop()
                timer.deleteLater()
                self.changed.emit('journal', '')
                open_ready()
        timer.timeout.connect(check)
        timer.start()

    def _open_log_window(self):
        """Ouvre le journal natif, sans le coût de démarrage/layout Chromium."""
        window = getattr(self, '_log_window', None)
        if window is not None and window.isVisible():
            window.raise_()
            window.activateWindow()
            return
        window = _BackgroundLogDialog(self.inspector)
        window.destroyed.connect(lambda: setattr(self, '_log_window', None))
        self._log_window = window
        window.show()

"""Travaux d'inactivité : contrôle léger sur Qt, parcours et génération sur un worker."""
import json
import os
import threading
import time
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication

TASKS = ('settings', 'moodboard', 'video')


class AutomaticTasks(QObject):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.away_at = None
        self.last_input = time.monotonic()
        self.cancel = {key: threading.Event() for key in TASKS}
        for event in self.cancel.values():
            event.set()
        self.jobs = {}
        self.migration_job = None
        self.migration_cancel = threading.Event()
        self.migration_cancel.set()
        self.migration_done = False
        self.closed = threading.Event()
        app = QApplication.instance()
        app.installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.wake = QTimer(self)
        self.wake.setSingleShot(True)
        self.wake.timeout.connect(self.tick)
        self._in_tick = False
        browser.destroyed.connect(lambda: self.stop())

    def stop(self):
        self.closed.set()
        self.migration_cancel.set()
        for event in self.cancel.values():
            event.set()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.Wheel):
            self.last_input = time.monotonic()
        if event.type() in (QEvent.ApplicationActivate, QEvent.ApplicationDeactivate,
                            QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.Wheel):
            # Ne pas modifier les widgets pendant la distribution d'un événement de focus.
            import ui_state
            settings = ui_state.APPLIED_SETTINGS or {}
            for task in TASKS:
                if (settings.get(f'auto_{task}_when', 'app') == 'computer' or
                        event.type() == QEvent.ApplicationActivate):
                    self.cancel[task].set()
            self.migration_cancel.set()
            self.wake.start(0)
        return False

    def eligible(self, task, settings):
        if not settings.get(f'auto_{task}_enabled', task == 'settings'):
            return False
        delay = int(settings.get(f'auto_{task}_delay', 60))
        if settings.get(f'auto_{task}_when', 'app') == 'computer':
            from settings_window_v2 import _system_idle_ms
            idle = _system_idle_ms()
            seconds = idle / 1000 if idle is not None else time.monotonic() - self.last_input
            # « Immédiatement » = dès la première seconde sans entrée, jamais pendant la frappe.
            return seconds >= max(1, delay)
        return self.away_at is not None and time.monotonic() - self.away_at >= delay

    def roots(self):
        from browser_core import ROLE_PATH, ROLE_ISDIR
        columns = self.browser.columns
        column = next((c for c in columns if str(c.column_title).casefold() == 'type'), None)
        if column is None:
            column = columns[0] if columns else None
        if column is None:
            return ()
        return tuple(dict.fromkeys(str(column.list.item(i).data(ROLE_PATH))
                     for i in range(column.list.count()) if column.list.item(i).data(ROLE_ISDIR)))

    def tick(self):
        if self._in_tick:
            return
        self._in_tick = True
        try:
            self._tick()
        finally:
            self._in_tick = False

    def _tick(self):
        if self.closed.is_set():
            return
        import ui_state
        active = QApplication.applicationState() == Qt.ApplicationActive
        if active:
            self.away_at = None
        elif self.away_at is None:
            self.away_at = time.monotonic()
        settings = dict(ui_state.APPLIED_SETTINGS or {})
        self._omit_dirs = {n.casefold() for n in __import__('config').GLOBAL_OMIT_DIR_NAMES} | {'moodboards'}
        # Une migration légère, au premier repos : seuls les dossiers qui ont
        # déjà un sous-dossier Moodboards sont ouverts, aucun proxy n'est créé.
        migrating = self.migration_job
        moodboard_job = self.jobs.get('moodboard')
        if (not active and not self.migration_done and (migrating is None or not migrating.is_alive())
                and (moodboard_job is None or not moodboard_job.is_alive())):
            roots = self.roots()
            if roots:
                self.migration_cancel = threading.Event()
                self.migration_job = threading.Thread(target=self._migrate_moodboard_directories,
                                                       args=(roots, self.migration_cancel), daemon=True,
                                                       name='moodboard-folder-migration')
                self.migration_job.start()
        for task in TASKS:
            allowed = self.eligible(task, settings)
            event = self.cancel[task]
            if not allowed:
                event.set()
                if self.jobs.get(task) is not None and self.jobs[task].is_alive():
                    setattr(self, f'next_{task}', 0)
                if task == 'settings':
                    self.browser._stop_settings_idle_load()
                continue
            if task == 'settings':
                dialog = self.browser._live_settings_dialog()
                if not self.browser._settings_idle_loading and (dialog is None or not dialog.prebuild_finished()):
                    self.browser._begin_settings_idle_load()
                continue
            job = self.jobs.get(task)
            if job is not None and job.is_alive():
                continue
            # Un nouveau balayage par minute, après la fin du précédent.
            if time.monotonic() < getattr(self, f'next_{task}', 0):
                continue
            roots = self.roots()
            if not roots:
                continue
            event = self.cancel[task] = threading.Event()
            setattr(self, f'next_{task}', time.monotonic() + 60)
            viewport = getattr(self.browser, '_video', None)
            if viewport is not None:
                settings['_mood_view'] = (viewport.moodboard.width(), viewport.moodboard.height(),
                                          viewport._mood_size, viewport.mood_gap_slider.value())
            else:
                settings['_mood_view'] = (self.browser.columns_host.width(),
                                          max(1, self.browser.columns_host.height() - 150), 180, 8)
            job = threading.Thread(target=self.run, args=(task, roots, settings, event), daemon=True,
                                   name=f'automatic-{task}')
            self.jobs[task] = job
            job.start()

    def _migrate_moodboard_directories(self, roots, cancel):
        """Renomme les anciens dossiers hashés dès qu'un MKV correspondant est trouvé.

        Ce parcours ne décode rien. Il s'interrompt au retour du focus, comme
        les autres travaux automatiques, et reprendra lors du prochain repos.
        """
        from browser_core import load_shortcuts
        from config import GLOBAL_OMIT_FILE_NAMES
        from fm_video.thumbs import MoodboardProxyCache
        status = getattr(self.browser, '_background_status', None)
        if status is not None:
            status.report('moodboard', 'Mise à jour des dossiers Moodboards existants')
        pending, seen = list(roots), set()
        omitted = {name.casefold() for name in GLOBAL_OMIT_FILE_NAMES}
        completed = True
        try:
            while pending and not cancel.is_set() and not self.closed.is_set():
                folder = Path(pending.pop())
                key = os.path.normcase(os.path.realpath(folder))
                if key in seen:
                    continue
                seen.add(key)
                try:
                    for shortcut in load_shortcuts(folder):
                        if shortcut.get('target'):
                            pending.append(shortcut['target'])
                    with os.scandir(folder) as entries:
                        for entry in entries:
                            if cancel.is_set() or self.closed.is_set():
                                completed = False
                                break
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name.casefold() not in self._omit_dirs:
                                    pending.append(entry.path)
                            elif (entry.name.casefold() not in omitted and entry.name.lower().endswith('.mkv')
                                  and (folder / 'Moodboards').is_dir()):
                                try:
                                    MoodboardProxyCache(entry.path)
                                except OSError:
                                    pass
                except OSError:
                    continue
        finally:
            self.migration_done = completed and not cancel.is_set() and not self.closed.is_set()
            if status is not None:
                status.finish('moodboard', 'Mise à jour des dossiers Moodboards ' +
                              ('terminée' if self.migration_done else 'suspendue'))

    def run(self, task, roots, settings, cancel):
        status = getattr(self.browser, '_background_status', None)
        name = 'Moodboards' if task == 'moodboard' else 'Aperçus vidéo'
        if status is not None:
            status.report(task, f'{name} : recherche récursive des fichiers')
        try:
            self._run(task, roots, settings, cancel, status, name)
        finally:
            if status is not None:
                status.finish(task, f'{name} : ' + ('suspendu' if cancel.is_set() else 'terminé'))

    def _run(self, task, roots, settings, cancel, status, name):
        from config import VIDEO_EXTENSIONS, GLOBAL_OMIT_FILE_NAMES, GLOBAL_OMIT_FILE_EXTENSIONS
        from browser_core import load_shortcuts
        pending = list(roots)
        seen = set()
        omitted_names = {n.casefold() for n in GLOBAL_OMIT_FILE_NAMES}
        extensions = VIDEO_EXTENSIONS - GLOBAL_OMIT_FILE_EXTENSIONS
        while pending and not cancel.is_set() and not self.closed.is_set():
            folder = Path(pending.pop())
            key = os.path.normcase(os.path.realpath(folder))
            if key in seen:
                continue
            seen.add(key)
            try:
                for shortcut in load_shortcuts(folder):
                    if shortcut.get('target'):
                        pending.append(shortcut['target'])
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if cancel.is_set() or self.closed.is_set():
                            return
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.casefold() not in self._omit_dirs:
                                pending.append(entry.path)
                        elif entry.name.casefold() not in omitted_names and Path(entry.name).suffix.lower() in extensions:
                            if task == 'moodboard' and Path(entry.name).suffix.lower() != '.mkv':
                                continue
                            try:
                                if status is not None:
                                    status.report(task, 'Vérification / génération', entry.path)
                                self.generate(task, Path(entry.path), settings, cancel)
                            except Exception as exc:
                                if status is not None:
                                    status.report(task, f'Erreur : {exc}', entry.path)
                                # Média illisible : poursuivre les autres fichiers au prochain repos.
                                pass
            except OSError:
                continue

    @staticmethod
    def generate(task, path, settings, cancel):
        """Décodeurs isolés : leur interruption ne détruit aucun objet multimédia de l'appli."""
        if cancel.is_set():
            return
        # Les réglages complets dépassent la limite Windows des lignes de commande.
        options = {key: settings[key] for key in ('video_moodboard_proxy_width', '_mood_view') if key in settings}
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), '--worker', task, str(path), json.dumps(options)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while process.poll() is None:
                if cancel.wait(.025):
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    return
            if process.returncode:
                raise RuntimeError(f'Le décodeur a quitté avec le code {process.returncode}')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    @staticmethod
    def video(path, cancel):
        import previews
        from PySide6.QtGui import QImage
        stamp = path.stat().st_mtime
        destination = previews._file_image_cache_path(path, stamp)
        if destination.is_file() and not QImage(str(destination)).isNull():
            return
        image = previews._decode_video_frame(path, previews.FILE_IMAGE_CACHE_MAX_DIM, cancel_event=cancel)
        if image is None or cancel.is_set():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix('.automatic.tmp.png')
        try:
            if image.save(str(temporary), 'PNG') and not cancel.is_set():
                os.replace(temporary, destination)
                previews._CACHE_INDEX.added(destination)
                previews._FILE_IMAGE_COLUMN_LOOKUP_MISSES.discard((str(path), int(stamp)))
                previews._PREVIEW_DECODE_MANAGER.ready.emit(str(path), stamp, image)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def moodboard(path, settings, cancel):
        from fm_video.media import open_media
        from fm_video.thumbs import MoodboardProxyCache
        source = open_media(path, settings)
        try:
            source._stream.codec_context.thread_count = 1
            cache = MoodboardProxyCache(path, settings.get('video_moodboard_proxy_width', 1200))
            manifest = cache.filename(0).parent / '.moodboard.json'
            try:
                previous = json.loads(manifest.read_text(encoding='utf-8'))
                if previous.get('version') != cache.version:
                    raise ValueError('La vidéo a changé')
                indices, layout = previous['indices'], previous['layout']
            except (OSError, ValueError, KeyError):
                vw, vh, size, gap = settings.get('_mood_view', (1200, 700, 180, 8))
                aspect = source.width / max(1, source.height)
                cols = max(1, int((vw + gap) // max(1, size + gap)))
                rows = max(1, int((vh + gap) // max(1, size / aspect + gap)))
                cell_w = max(1, (vw - gap * (cols + 1)) // cols)
                cell_h = max(1, (vh - gap * (rows + 1)) // rows)
                width = max(1, min(cell_w, round(cell_h * aspect)))
                layout = [cols, rows, width, max(1, round(width / aspect)), gap]
                count = min(500, rows * cols, source.frame_count)
                if count <= 0:
                    return
                indices = [0] if count == 1 else [round(i * (source.frame_count - 1) / (count - 1)) for i in range(count)]
            if cancel.is_set():
                return
            matches = cache.prepare(indices, layout, is_current=lambda: not cancel.is_set())
            if matches:
                cache.export(indices, layout, is_current=lambda: not cancel.is_set())
                return
            for index in indices:
                if cancel.is_set():
                    return
                cache.pixels(source, index, 48, is_current=lambda: not cancel.is_set())
            cache.export(indices, layout, is_current=lambda: not cancel.is_set())
        finally:
            source.close()


if __name__ == '__main__' and len(sys.argv) == 5 and sys.argv[1] == '--worker':
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication([])
    task, path, settings = sys.argv[2], Path(sys.argv[3]), json.loads(sys.argv[4])
    if task == 'video':
        AutomaticTasks.video(path, threading.Event())
    else:
        AutomaticTasks.moodboard(path, settings, threading.Event())

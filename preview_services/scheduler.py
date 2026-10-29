"""Balayage et ordonnanceur des rendus à l’inactivité.

Carte et pièges : docs/agents/apercus.md.
"""

import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path
from PySide6.QtCore import QEvent, QObject, QRunnable, QTimer, Signal
from PySide6.QtWidgets import QApplication
from config import GLOBAL_OMIT_DIR_NAMES, GLOBAL_OMIT_FILE_EXTENSIONS, GLOBAL_OMIT_FILE_NAMES, RENDERABLE_3D_EXTENSIONS, TWO_D_IMAGE_EXTENSIONS
from . import cache as _cache
from . import profiles as _profiles
from . import render_log as _render_log
from . import runtime as _runtime

class _IdleFileScanSignals(QObject):
    finished = Signal(str, object, object)

class _IdleFileScanTask(QRunnable):
    """Parcourt recursivement la racine sans bloquer la fenetre."""
    def __init__(self, root: Path, supported: set[str], cancel_event,
                 omit_file_names: set[str] | None = None, omit_extensions: set[str] | None = None,
                 omit_dir_names: set[str] | None = None):
        super().__init__()
        self.root = root
        self.supported = supported
        self.cancel_event = cancel_event
        self.omit_file_names = omit_file_names or set()
        self.omit_extensions = omit_extensions or set()
        self.omit_dir_names = omit_dir_names or set()
        self.signals = _IdleFileScanSignals()

    def run(self):
        found = []
        root_text = str(self.root)
        try:
            for current, dirs, files in os.walk(root_text, topdown=True, followlinks=False):
                if self.cancel_event.is_set():
                    break
                dirs.sort(key=str.casefold)
                dirs[:] = [name for name in dirs if name.casefold() not in self.omit_dir_names]
                files.sort(key=str.casefold)
                for filename in files:
                    if self.cancel_event.is_set():
                        break
                    name_lower = filename.casefold()
                    suffix = Path(filename).suffix.lower()
                    if (suffix not in self.supported
                            or name_lower in self.omit_file_names
                            or any(name_lower.endswith("." + extension) for extension in self.omit_extensions)):
                        continue
                    path = Path(current) / filename
                    try:
                        found.append((str(path), path.stat().st_mtime))
                    except OSError:
                        continue
        except (OSError, PermissionError):
            pass
        self.signals.finished.emit(root_text, found, self.cancel_event.is_set())

class _IdlePreviewScheduler(QObject):
    """Met a jour les apercus 2D/3D perimes apres 2 min d'inactivite."""
    # visible, termines, total, libelle : signal destine a la barre superieure
    # (le traitement reste entierement hors du fil d'interface).
    cache_progress = Signal(bool, int, int, str)
    IDLE_DELAY_MS = 120_000
    RESCAN_INTERVAL_SECONDS = 60.0
    LOG_SEPARATOR = "-----------------------------------------"
    SUPPORTED_SUFFIXES = RENDERABLE_3D_EXTENSIONS | TWO_D_IMAGE_EXTENSIONS

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._poll)
        self.last_activity = time.monotonic()
        self.is_idle = False
        self.queue: list[tuple[Path, float]] = []
        self.done: set[tuple[str, float]] = set()
        self.failed: set[tuple[str, float]] = set()
        self.failure_counts: dict[tuple[str, float, str], int] = {}
        self.retry_after: dict[tuple[str, float], float] = {}
        self._batch_profile_signature = None
        self.active_key: str | None = None
        self.active_media_type = "image"
        self.active_permanent_error = ""
        self.active_identity: tuple[str, float] | None = None
        self.cancel_event: threading.Event | None = None
        self.scan_cancel_event: threading.Event | None = None
        self.scan_task: _IdleFileScanTask | None = None
        self.scan_in_progress = False
        self.scan_root = ""
        self.last_scan = 0.0
        self.auto_render_count = 0
        self.active_log_path: Path | None = None
        self.batch_total = 0
        self.batch_completed = 0
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        _runtime._PREVIEW_DECODE_MANAGER.ready.connect(self._on_preview_ready)
        _runtime._PREVIEW_DECODE_MANAGER.turntable_ready.connect(self._on_preview_ready)
        _runtime._PREVIEW_DECODE_MANAGER.started.connect(self._on_preview_started)
        _runtime._PREVIEW_DECODE_MANAGER.progress.connect(self._on_preview_progress)
        if _cache.AUTO_RENDER_ENABLED:                   # rendus automatiques suspendus (voir AUTO_RENDER_ENABLED)
            self.timer.start()

    def eventFilter(self, watched, event):
        if sys.platform != "win32" and event.type() in {
            QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick, QEvent.Type.Wheel, QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease, QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate,
        }:
            self.last_activity = time.monotonic()
        return False

    @staticmethod
    def _system_idle_ms() -> int | None:
        if sys.platform != "win32":
            return None
        class LastInputInfo(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        info = LastInputInfo()
        info.cbSize = ctypes.sizeof(LastInputInfo)
        try:
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return None
            return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
        except (AttributeError, OSError):
            return None

    def _user_is_idle(self) -> bool:
        system_idle = self._system_idle_ms()
        if system_idle is not None:
            return system_idle >= self.IDLE_DELAY_MS
        return (time.monotonic() - self.last_activity) * 1000 >= self.IDLE_DELAY_MS

    def _poll(self):
        if not _cache.AUTO_RENDER_ENABLED:
            return
        idle_now = self._user_is_idle()
        if not idle_now:
            self.is_idle = False
            if self.cancel_event is not None:
                self.cancel_event.set()
            if self.scan_cancel_event is not None:
                self.scan_cancel_event.set()
            if self.batch_total or self.scan_in_progress:
                self.cache_progress.emit(False, 0, 0, "")
            return
        if not self.is_idle:
            self.is_idle = True
            self.last_scan = 0.0
        if self.active_key is not None:
            return
        if self.scan_in_progress:
            return
        if not self.queue and time.monotonic() - self.last_scan >= self.RESCAN_INTERVAL_SECONDS:
            self._start_file_scan()
        if self.queue:
            self._start_next()

    def _start_file_scan(self):
        self.last_scan = time.monotonic()
        root_text = self.browser.root_field.text().strip()
        root = Path(root_text)
        if not root.is_dir():
            return
        # Le profil automatique est actualise une fois avant le scan qui
        # decide si les caches sont encore valides, puis gele pour toute la file.
        _profiles._begin_automatic_render_batch()
        profile_signature = json.dumps(_profiles._AUTOMATIC_RENDER_PROFILES, sort_keys=True, default=str)
        for profile in (_profiles._AUTOMATIC_RENDER_PROFILES or {}).values():
            template = Path(__file__).resolve().parent.parent / "files" / str(profile.get("template", ""))
            try:
                profile_signature += str(template.stat().st_mtime_ns)
            except OSError:
                pass
        if profile_signature != self._batch_profile_signature:
            self.done.clear()
            self.failed.clear()
            self.failure_counts.clear()
            self.retry_after.clear()
            self._batch_profile_signature = profile_signature
        self.batch_total = 0
        self.batch_completed = 0
        self.cache_progress.emit(True, 0, 0, "Recherche des images à mettre en cache…")
        self.scan_in_progress = True
        self.scan_root = str(root)
        self.scan_cancel_event = threading.Event()
        task = _IdleFileScanTask(
            root, self.SUPPORTED_SUFFIXES, self.scan_cancel_event,
            GLOBAL_OMIT_FILE_NAMES.copy(), GLOBAL_OMIT_FILE_EXTENSIONS.copy(),
            GLOBAL_OMIT_DIR_NAMES.copy(),
        )
        task.signals.finished.connect(self._on_file_scan_finished)
        self.scan_task = task
        _runtime._IDLE_SCAN_POOL.start(task)

    def _on_file_scan_finished(self, root_text: str, entries, canceled: bool):
        self.scan_in_progress = False
        self.scan_task = None
        self.scan_cancel_event = None
        self.last_scan = time.monotonic()
        if canceled or not self.is_idle or not self._user_is_idle():
            self.cache_progress.emit(False, 0, 0, "")
            return
        if str(Path(self.browser.root_field.text().strip())) != root_text:
            self.cache_progress.emit(False, 0, 0, "")
            return
        found = []
        seen = set()
        for value, mtime in entries:
            path = Path(value)
            key = str(path)
            identity = (key, mtime)
            if identity in seen or identity in self.done or identity in self.failed or key in _runtime._PREVIEW_DECODE_MANAGER.active:
                continue
            if _cache._is_preview_protected(path):
                self.done.add(identity)
                continue
            seen.add(identity)
            if _cache._file_image_cache_path(
                path, mtime, profiles_snapshot=_profiles._AUTOMATIC_RENDER_PROFILES,
            ).is_file() and (path.suffix.lower() not in _cache.TURNTABLE_EXTENSIONS or _cache._turntable_frames(path, mtime, _profiles._AUTOMATIC_RENDER_PROFILES)):
                self.done.add(identity)
                continue
            found.append((path, mtime))
        self.queue.extend(found)
        self.batch_total = len(self.queue)
        self.batch_completed = 0
        if not self.batch_total:
            self.cache_progress.emit(False, 0, 0, "")
            return
        self.cache_progress.emit(True, 0, self.batch_total, "Mise en cache des images…")
        self._start_next()

    def _append_log(self, line: str):
        path = self.active_log_path
        if path is None:
            return
        if line == self.LOG_SEPARATOR:
            return
        try:
            task = _runtime._PREVIEW_DECODE_MANAGER.active.get(self.active_key)
            self.active_log_path = _render_log._write_render_log(path.parent, line, self.active_key or "", self.active_media_type,
                                                      getattr(task, "render_mode", "low"),
                                                      getattr(task, "output_path", ""))
        except (OSError, ValueError):
            pass

    def _on_preview_started(self, path_str: str):
        if path_str != self.active_key:
            return
        self.active_log_path = _render_log._render_log_path(Path(self.browser.root_field.text().strip()))
        try:
            has_previous_render = self.active_log_path.is_file() and self.active_log_path.stat().st_size > 0
        except OSError:
            has_previous_render = False
        if has_previous_render:
            self._append_log(self.LOG_SEPARATOR)
        self.auto_render_count += 1
        # La ligne courante et toutes les progressions sont egalement ecrites
        # dans le journal du root, sans inclure les apercus declenches a la main.
        self._append_log(f"> Aperçu en cours : {path_str}")

    def _on_preview_progress(self, path_str: str, percent: int, message: str):
        if path_str == self.active_key:
            if "HDF5" in message and ("obsol" in message or "réexport" in message):
                self.active_permanent_error = message
            self._append_log(f"[{percent:3d}%] {Path(path_str).name} — {message}")

    def _report_batch_item(self):
        """Compte un fichier qui n'a plus besoin d'etre traite (supprime ou deja cache)."""
        if not self.batch_total:
            return
        self.batch_completed = min(self.batch_completed + 1, self.batch_total)
        self.cache_progress.emit(
            True, self.batch_completed, self.batch_total,
            f"Mise en cache des images — {self.batch_completed}/{self.batch_total}",
        )

    def _start_next(self):
        # Un essai par element de la file : les reprises differees ne doivent
        # jamais bloquer le thread GUI dans une boucle de re-enfilement.
        for _ in range(len(self.queue)):
            path, previous_mtime = self.queue.pop(0)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                self._report_batch_item()
                continue
            key = str(path)
            identity = (key, mtime)
            if time.monotonic() < self.retry_after.get(identity, 0.0):
                self.queue.append((path, mtime))
                continue
            if identity in self.done or identity in self.failed or key in _runtime._PREVIEW_DECODE_MANAGER.active:
                self._report_batch_item()
                continue
            if _cache._is_preview_protected(path):
                self.done.add(identity)
                self._report_batch_item()
                continue
            if _cache._file_image_cache_path(
                path, mtime, profiles_snapshot=_profiles._AUTOMATIC_RENDER_PROFILES,
            ).is_file() and (path.suffix.lower() not in _cache.TURNTABLE_EXTENSIONS or _cache._turntable_frames(path, mtime, _profiles._AUTOMATIC_RENDER_PROFILES)):
                self.done.add(identity)
                self._report_batch_item()
                continue
            self.active_key = key
            self.active_permanent_error = ""
            self.active_identity = identity
            self.cancel_event = threading.Event()
            self.active_media_type = "turntable" if _cache._file_image_cache_path(
                path, mtime, profiles_snapshot=_profiles._AUTOMATIC_RENDER_PROFILES,
            ).is_file() and path.suffix.lower() in _cache.TURNTABLE_EXTENSIONS else "image"
            self.browser.detail.prepare_auto_preview_log(path)
            _runtime._PREVIEW_DECODE_MANAGER.request(
                path, mtime, cancel_event=self.cancel_event, force_render=True, automatic=True,
                media_type=self.active_media_type,
            )
            if key not in _runtime._PREVIEW_DECODE_MANAGER.active:
                self.active_key = None
                self.active_identity = None
                self.cancel_event = None
            return
        if self.batch_total and self.batch_completed >= self.batch_total:
            self.cache_progress.emit(False, self.batch_completed, self.batch_total, "")
            self.batch_total = 0
            self.batch_completed = 0

    def _on_preview_ready(self, path_str: str, mtime: float, image):
        if path_str != self.active_key:
            return
        canceled = self.cancel_event is not None and self.cancel_event.is_set()
        success = image is not None and not image.isNull()
        if canceled:
            self._append_log(f"[---] {Path(path_str).name} — interrompu par une activité utilisateur")
        else:
            message = "Aperçu terminé" if image is not None and not image.isNull() else "Aperçu indisponible"
            self._append_log(f"[100%] {Path(path_str).name} — {message}")
        identity = self.active_identity
        completed_media = self.active_media_type
        retry = False
        if identity is not None and not canceled and not success:
            failure_key = (*identity, completed_media)
            failures = self.failure_counts.get(failure_key, 0) + 1
            self.failure_counts[failure_key] = failures
            retry = failures < 2 and not self.active_permanent_error
            if retry:
                self._append_log(f"[---] {Path(path_str).name} — Nouvelle tentative differee (au moins 30 secondes), sans bloquer les autres fichiers")
            else:
                reason = self.active_permanent_error or "apres 2 tentatives : suspendu pour cette session"
                self._append_log(f"[---] {Path(path_str).name} — Échec : {reason}")
        self.active_key = None
        self.active_identity = None
        self.cancel_event = None
        self.active_log_path = None
        if canceled:
            if identity is not None:
                self.queue.insert(0, (Path(path_str), mtime))
            return
        if identity is not None:
            if retry:
                self.retry_after[identity] = time.monotonic() + 30.0
                self.queue.append((Path(path_str), mtime))
            elif completed_media == "image" and success and Path(path_str).suffix.lower() in _cache.TURNTABLE_EXTENSIONS:
                self.queue.insert(0, (Path(path_str), mtime))
            elif success:
                self.done.add((path_str, mtime))
            else:
                self.failed.add(identity)
            if success:
                self.failure_counts.pop((*identity, completed_media), None)
                self.retry_after.pop(identity, None)
            # Un turntable est d'abord converti, puis repasse dans la file pour
            # son aperçu final : ne compter qu'à la fin de cette seconde étape.
            final_step = not (completed_media == "image" and success and Path(path_str).suffix.lower() in _cache.TURNTABLE_EXTENSIONS)
            if final_step and (success or not retry):
                self.batch_completed = min(self.batch_completed + 1, self.batch_total)
                self.cache_progress.emit(
                    True, self.batch_completed, self.batch_total,
                    f"Mise en cache des images — {self.batch_completed}/{self.batch_total}",
                )
        if self.is_idle and self._user_is_idle():
            self._start_next()

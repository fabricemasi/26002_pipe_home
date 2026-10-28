"""Cache d'images du module vidéo et chargeurs en fond.

`FrameCache` : images décodées gardées par (source, calque, rang), plafond en octets (réglage « RAM maximale »),
les moins récemment vues partent d'abord.

`FrameLoader` : fils de fond qui lisent ce qui est DEMANDÉ, puis préchargent autour (devant dans le sens de la
lecture, un peu derrière). Une demande remplace la précédente : les lectures devenues inutiles (tête de lecture
déplacée vite) ne sont jamais commencées. Vidéo = UN fil (le décodeur avance image par image ; reculer décode
depuis l'image clé et garde les images traversées) ; séquence = plusieurs fils (un fichier par image).
Jamais de décodage sur le fil de l'interface : l'interface reçoit `frameReady(rang)` et lit le cache."""
from __future__ import annotations

import threading
from collections import OrderedDict

from PySide6.QtCore import QObject, Signal

from fm_video.media import Frame, MediaError, MediaSource


class FrameCache:
    def __init__(self, max_bytes: int = 2 << 30):
        self.max_bytes = int(max_bytes)
        self._items: OrderedDict = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def key(self, source: MediaSource, index: int):
        return (id(source), source.layer, int(index))

    def get(self, key) -> Frame | None:
        with self._lock:
            frame = self._items.get(key)
            if frame is not None:
                self._items.move_to_end(key)
            return frame

    def __contains__(self, key) -> bool:
        with self._lock:
            return key in self._items

    def put(self, key, frame: Frame, protect=()):
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self._bytes -= old.nbytes
            self._items[key] = frame
            self._bytes += frame.nbytes
            self._trim(protect)

    def _trim(self, protect=()):
        while self._bytes > self.max_bytes and len(self._items) > 1:
            for key in self._items:
                if key not in protect:
                    break
            else:
                return
            frame = self._items.pop(key)
            self._bytes -= frame.nbytes

    def set_limit(self, max_bytes: int):
        with self._lock:
            self.max_bytes = int(max_bytes)
            self._trim()

    def drop_source(self, source: MediaSource):
        sid = id(source)
        with self._lock:
            for key in [k for k in self._items if k[0] == sid]:
                self._bytes -= self._items.pop(key).nbytes

    def cached_indices(self, source: MediaSource) -> set[int]:
        sid, layer = id(source), source.layer
        with self._lock:
            return {k[2] for k in self._items if k[0] == sid and k[1] == layer}

    @property
    def used_bytes(self) -> int:
        return self._bytes

    def clear(self):
        with self._lock:
            self._items.clear()
            self._bytes = 0


class FrameLoader(QObject):
    """Chargement en fond d'une source. `request(rang, sens)` : l'image voulue d'abord, puis `ahead` images dans le
    sens de la marche et `behind` dans l'autre (séquences ; pour une vidéo, reculer garde les images traversées)."""

    frameReady = Signal(int)
    failed = Signal(int, str)

    def __init__(self, source: MediaSource, cache: FrameCache, workers: int = 4, ahead: int = 24,
                 behind: int = 8, parent=None):
        super().__init__(parent)
        self.source = source
        self.cache = cache
        self.ahead, self.behind = int(ahead), int(behind)
        self._video = source.kind == "video"
        count = 1 if self._video or source.frame_count == 1 else max(1, int(workers))
        self._cond = threading.Condition()
        self._target = None
        self._direction = 1
        self._wanted: list[int] = []
        self._busy: set[int] = set()
        self._failed: set[int] = set()
        self._stop = False
        self._threads = []
        for n in range(count):
            thread = threading.Thread(target=self._run, args=(source if n == 0 else source.clone(),),
                                      name=f"video-loader-{n}", daemon=True)
            self._threads.append(thread)
            thread.start()
        if self._video and hasattr(source, "build_index") and not source.index_ready:
            self._index_cancel = threading.Event()
            threading.Thread(target=self._build_index, name="video-index", daemon=True).start()

    indexReady = Signal()

    def _build_index(self):
        if self.source.build_index(self._index_cancel):
            try:
                self.indexReady.emit()
            except RuntimeError:                             # chargeur détruit entre-temps
                pass

    def set_window(self, ahead: int, behind: int):
        with self._cond:
            self.ahead, self.behind = int(ahead), int(behind)

    def request(self, index: int, direction: int = 1, prefetch: bool = True):
        """Nouvelle cible : la liste de travail est REFAITE (les rangs devenus inutiles sont oubliés)."""
        count = self.source.frame_count
        index = max(0, min(int(index), count - 1))
        direction = -1 if direction < 0 else 1
        wanted = [index]
        if prefetch:
            for step in range(1, self.ahead + 1):
                i = index + direction * step
                if 0 <= i < count:
                    wanted.append(i)
            if not self._video:
                for step in range(1, self.behind + 1):
                    i = index - direction * step
                    if 0 <= i < count:
                        wanted.append(i)
        with self._cond:
            self._target, self._direction = index, direction
            self._wanted = [i for i in wanted if i not in self._failed]
            self._cond.notify_all()

    def protect(self) -> set:
        """Clés à ne pas sortir du cache : la fenêtre de travail en cours."""
        with self._cond:
            return {self.cache.key(self.source, i) for i in self._wanted[:max(1, self.ahead // 2)]}

    def _next_job(self):
        for i in self._wanted:
            if i in self._busy:
                continue
            if self.cache.get(self.cache.key(self.source, i)) is not None:
                continue
            return i
        return None

    def _run(self, source: MediaSource):
        while True:
            with self._cond:
                while not self._stop:
                    job = self._next_job()
                    if job is not None:
                        break
                    self._cond.wait()
                if self._stop:
                    break
                self._busy.add(job)
                direction = self._direction
                layer = self.source.layer
            if source is not self.source and getattr(source, "layer", layer) != layer:
                source.set_layer(layer)
            try:
                extra = None
                if self._video and direction < 0:
                    keep_from = job - max(8, self.behind * 3)

                    def extra(frame: Frame, src=source):     # images traversées en reculant : les plus proches gardées
                        if frame.index >= keep_from:
                            self.cache.put(self.cache.key(self.source, frame.index), frame, self.protect())
                if self._video:
                    source.extra_window = max(8, self.behind * 3)
                frame = source.read(job, on_extra=extra, yuv=self._video)   # vidéo : planes YUV (shader)
                self.cache.put(self.cache.key(self.source, job), frame, self.protect())
                ok = True
            except MediaError as exc:
                ok, message = False, str(exc)
            except Exception as exc:                         # noqa: BLE001 - jamais de plantage du fil
                ok, message = False, f"{type(exc).__name__}: {exc}"
            with self._cond:
                self._busy.discard(job)
                if not ok:
                    self._failed.add(job)
                    if job in self._wanted:
                        self._wanted.remove(job)
            try:
                if ok:
                    self.frameReady.emit(job)
                else:
                    self.failed.emit(job, message)
            except RuntimeError:                             # objet Qt détruit : on s'arrête
                break
        if source is not self.source:
            source.close()

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        cancel = getattr(self, "_index_cancel", None)
        if cancel is not None:
            cancel.set()

    def join(self, timeout: float = 2.0):
        for thread in self._threads:
            thread.join(timeout)

"""Fil UNIQUE du moteur PDFium (sans Qt) : toute fonction de PDFium s'exécute ici, jamais sur le fil de l'interface.

- File à PRIORITÉS (plus petit = plus urgent) : saisie dans un formulaire > enregistrement > tuiles visibles >
  voisines > miniatures > fond (analyse, recherche, OCR préparatoire). Une tâche ANNULÉE (`Job.cancel`, ex. tuile
  sortie de l'écran) est sautée sans être exécutée.
- MINUTERIES de PDFium (FFI_SetTimer : clignotement du caret, `app.setTimeOut` des scripts) : RÉPÉTITIVES jusqu'à
  FFI_KillTimer, exécutées entre deux tâches.
- Après chaque tâche ou minuterie : les évènements des documents (zones à repeindre, focus, caret…) sont remis à
  leur `listener` (l'interface les transforme en signal Qt).
- ctypes rend le verrou global de Python pendant chaque appel natif : le rendu tourne VRAIMENT en parallèle de
  l'interface.
"""
from __future__ import annotations

import atexit
import heapq
import itertools
import threading
import time
import traceback

PRIO_INPUT = 0
PRIO_SAVE = 5
PRIO_VISIBLE = 10
PRIO_NEAR = 20
PRIO_THUMB = 30
PRIO_BACKGROUND = 40


class Job:
    __slots__ = ("fn", "priority", "seq", "on_done", "cancelled", "result", "error", "done", "tag", "on_cancel")

    def __init__(self, fn, priority, seq, on_done, tag):
        self.fn = fn
        self.priority = priority
        self.seq = seq
        self.on_done = on_done
        self.tag = tag
        self.cancelled = False
        self.on_cancel = None
        self.result = None
        self.error = None
        self.done = threading.Event()

    def cancel(self):
        self.cancelled = True
        if self.on_cancel is not None:
            hook, self.on_cancel = self.on_cancel, None
            hook()

    def __lt__(self, other):
        return (self.priority, self.seq) < (other.priority, other.seq)


class Engine:
    def __init__(self):
        self._heap: list[Job] = []
        self._cv = threading.Condition()
        self._seq = itertools.count()
        self._tid = itertools.count(1)
        self._timers: dict[int, list] = {}          # id -> [échéance, période s, fonction, document]
        self._stop = False
        self._current_doc = None
        self.docs: list = []
        self.init_error: str | None = None
        self.stats = {"jobs": 0, "busy_ms": 0.0, "max_ms": 0.0, "timers": 0}
        self._ready = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="fm_pdf-moteur", daemon=True)
        self.thread.start()
        self._ready.wait(30)

    # -- API (tout fil) --

    def on_engine_thread(self) -> bool:
        return threading.current_thread() is self.thread

    def submit(self, fn, priority: int = PRIO_BACKGROUND, on_done=None, tag=None) -> Job:
        """Exécute fn() sur le fil du moteur ; on_done(job) y est appelé ensuite (résultat ou erreur dans job)."""
        job = Job(fn, priority, next(self._seq), on_done, tag)
        with self._cv:
            heapq.heappush(self._heap, job)
            self._cv.notify()
        return job

    def call(self, fn, priority: int = PRIO_INPUT, timeout: float | None = 120.0):
        """Exécute fn() et ATTEND son résultat (tests, requêtes courtes hors interface). Sur le fil du moteur :
        appel direct."""
        if self.on_engine_thread():
            return fn()
        job = self.submit(fn, priority)
        if not job.done.wait(timeout):
            job.cancel()
            raise TimeoutError("le moteur PDF n'a pas répondu")
        if job.error is not None:
            raise job.error
        return job.result

    def pending(self) -> int:
        with self._cv:
            return sum(1 for j in self._heap if not j.cancelled)

    # -- documents (fil du moteur) --

    def open_document(self, data: bytes, path=None, password=None, **options):
        from .engine import Document
        self._current_doc = None
        doc = Document(self, data, path, password, **options)
        self.docs.append(doc)
        return doc

    def close_document(self, doc) -> None:
        if doc in self.docs:
            self.docs.remove(doc)
        doc.close()
        self.kill_timers_of(doc)

    # -- minuteries (fil du moteur, appelées par PDFium) --

    def add_timer(self, ms: int, fn, owner=None) -> int:
        tid = next(self._tid)
        period = max(0.001, ms / 1000.0)
        self._timers[tid] = [time.perf_counter() + period, period, fn, owner or self._current_doc]
        return tid

    def kill_timer(self, tid: int) -> None:
        self._timers.pop(tid, None)

    def kill_timers_of(self, doc) -> None:
        for tid in [t for t, v in self._timers.items() if v[3] is doc]:
            self._timers.pop(tid, None)

    # -- boucle --

    def _next_timer_due(self):
        return min((v[0] for v in self._timers.values()), default=None)

    def _fire_timers(self):
        now = time.perf_counter()
        for tid, timer in list(self._timers.items()):
            if timer[0] <= now and tid in self._timers:
                timer[0] = now + timer[1]
                doc = timer[3]
                if doc is not None and doc.closed:
                    self._timers.pop(tid, None)
                    continue
                self._current_doc = doc
                try:
                    timer[2](tid)
                except Exception:                        # noqa: BLE001
                    traceback.print_exc()
                self.stats["timers"] += 1
        self._current_doc = None

    def _dispatch(self):
        for doc in list(self.docs):
            if doc.closed or doc.listener is None:
                continue
            if doc.events or doc._raw_invalid or doc._caret is not None or doc._stale_pages:
                try:
                    events = doc.take_events()
                    if events:
                        doc.listener(events)
                except Exception:                        # noqa: BLE001
                    traceback.print_exc()

    def _loop(self):
        try:
            from .engine import init_library
            init_library()
        except Exception as exc:                         # noqa: BLE001 - DLL absente : chaque tâche le dira
            self.init_error = repr(exc)
        self._ready.set()
        while True:
            with self._cv:
                while not self._stop:
                    due = self._next_timer_due()
                    if self._heap or (due is not None and due <= time.perf_counter()):
                        break
                    self._cv.wait(None if due is None else max(0.0, due - time.perf_counter()))
                if self._stop:
                    return
                job = heapq.heappop(self._heap) if self._heap else None
            if self._timers:
                self._fire_timers()
                self._dispatch()
            if job is None:
                continue
            if job.cancelled:
                job.done.set()
                continue
            t0 = time.perf_counter()
            try:
                if self.init_error:
                    raise RuntimeError("moteur PDF indisponible : " + self.init_error)
                job.result = job.fn()
            except BaseException as exc:                 # noqa: BLE001
                job.error = exc
            ms = (time.perf_counter() - t0) * 1000
            self.stats["jobs"] += 1
            self.stats["busy_ms"] += ms
            self.stats["max_ms"] = max(self.stats["max_ms"], ms)
            if job.on_done is not None:
                try:
                    job.on_done(job)
                except Exception:                        # noqa: BLE001
                    traceback.print_exc()
            job.done.set()
            self._dispatch()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Ferme les documents sur le fil du moteur puis arrête la boucle (PDFium n'est PAS détruit : V8 lié au fil)."""
        if not self.thread.is_alive():
            return

        def close_all():
            for doc in list(self.docs):
                try:
                    self.close_document(doc)
                except Exception:                        # noqa: BLE001
                    pass
        try:
            self.call(close_all, timeout=timeout)
        except Exception:                                # noqa: BLE001
            pass
        with self._cv:
            self._stop = True
            self._cv.notify()
        self.thread.join(timeout)


_ENGINE: list = []


def get_engine() -> Engine:
    if not _ENGINE:
        _ENGINE.append(Engine())
        atexit.register(_ENGINE[0].shutdown)
    return _ENGINE[0]

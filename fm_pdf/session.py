"""Session d'un document ouvert dans l'interface (Qt) : pont entre les widgets et le FIL DU MOTEUR.

Le Document PDFium (engine.py) ne vit que sur le fil du moteur ; la session lui envoie des tâches (`run`) et
reçoit leurs résultats par signal (fil de l'interface). Rien de lourd ici : lecture du fichier, rendu, recherche,
enregistrement, éditions passent tous par le moteur.

Éditions STRUCTURELLES (champs créés, annotations, pages, caviardage…) : `edit(label, fonction(octets) -> octets)`
= instantané des octets courants (formulaire compris), fonction appliquée, document rouvert depuis le résultat ;
annuler / rétablir = rouvrir l'instantané (pile bornée en octets). La saisie dans un champ, elle, s'annule champ par
champ dans PDFium (FORM_Undo).
"""
from __future__ import annotations

import ctypes
import itertools
import pathlib
import threading
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from . import fileio
from .worker import PRIO_BACKGROUND, PRIO_INPUT, PRIO_SAVE, PRIO_VISIBLE, get_engine


_CANCELLED = object()


class _Relay(QObject):
    done = Signal(int, object, object)          # jeton, résultat, erreur (fil du moteur -> interface)
    events = Signal(list)
    ask = Signal(int, str, str, str, object)


def doc_info(doc) -> dict:
    """Instantané des propriétés du document (fil du moteur)."""
    sizes = doc.page_sizes()
    info = {"page_count": len(sizes), "sizes": list(sizes), "form_kind": doc.form_kind, "is_xfa": doc.is_xfa,
            "xfa_loaded": doc.xfa_loaded, "xfa_ms": doc.xfa_ms, "open_ms": doc.open_ms, "security": doc.security(),
            "active": doc.active_content(), "metadata": doc.metadata(), "path": doc.path, "size": len(doc.data)}
    try:
        info["fields"] = doc.fields() if doc.form_type == 1 else []
    except Exception:                                    # noqa: BLE001
        info["fields"] = []
    info["has_forms"] = doc.form_type != 0 or bool(info["fields"])
    labels = [doc.page_label(i) for i in range(min(len(sizes), 5000))]
    info["labels"] = labels if any(labels) else []
    return info


class PdfSession(QObject):
    opened = Signal(dict)
    failed = Signal(str, bool)                  # message, mot de passe demandé
    reloaded = Signal(dict)                     # après une édition structurelle, annuler, rétablir
    events = Signal(list)                       # évènements du formulaire (invalidate, cursor, focus…)
    stateChanged = Signal()                     # modifié / annuler / rétablir
    saved = Signal(str)
    saveFailed = Signal(str)
    conflict = Signal(str)                      # fichier modifié par un autre logiciel depuis l'ouverture
    blocked = Signal(str)                       # action d'un script refusée (réseau, fichier…)
    message = Signal(str)

    UNDO_BYTES = 400 * 1024 * 1024

    def __init__(self, parent=None, engine=None):
        super().__init__(parent)
        self.engine = engine or get_engine()
        self._relay = _Relay()
        self._relay.done.connect(self._on_done)
        self._relay.events.connect(self._on_events)
        self._relay.ask.connect(self._on_ask)
        self._tokens = itertools.count(1)
        self._callbacks: dict[int, object] = {}
        self.doc = None                         # objet du fil du moteur : n'y toucher que dans `run`
        self.info: dict = {}
        self.path: pathlib.Path | None = None
        self.password: str | None = None
        self.file_sig = None
        self.form_dirty = False
        self.struct_dirty = False
        self.undo_stack: list = []              # [(libellé, octets avant)]
        self.redo_stack: list = []
        self.generation = 0                     # +1 à chaque document (ré)ouvert : caches de la vue
        self.ask_handler = None                 # f(kind, titre, message, extra) -> réponse (fil de l'interface)
        self.options = {"javascript": True, "xfa": True}
        self.closed = False
        self._answers: dict[int, list] = {}

    # -- tâches --

    def run(self, fn, priority: int = PRIO_BACKGROUND, callback=None):
        """fn(doc) sur le fil du moteur ; callback(résultat, erreur) sur celui de l'interface."""
        token = next(self._tokens)
        if callback is not None:
            self._callbacks[token] = callback
        relay = self._relay

        def job():
            doc = self.doc
            if doc is None or doc.closed:
                raise RuntimeError("document fermé")
            return fn(doc)

        def done(j):
            if callback is not None:                  # annulée : le rappel est seulement LIBÉRÉ (aucune fuite)
                relay.done.emit(token, _CANCELLED if j.cancelled else j.result, None if j.cancelled else j.error)
        job_obj = self.engine.submit(job, priority, on_done=done)
        if callback is not None:                      # annulée avant de tourner : rappel libéré tout de suite
            job_obj.on_cancel = lambda: self._callbacks.pop(token, None)
        return job_obj

    def call(self, fn, priority: int = PRIO_INPUT, timeout: float = 120.0):
        """Exécute fn(doc) et attend (tests, outils)."""
        return self.engine.call(lambda: fn(self.doc), priority, timeout)

    def _on_done(self, token, result, error):
        callback = self._callbacks.pop(token, None)
        if callback is not None and result is not _CANCELLED:
            callback(result, error)

    # -- ouverture --

    def open_path(self, path, password: str | None = None) -> None:
        self.path = pathlib.Path(path)
        self.password = password
        target = self.path

        def job():
            data = fileio.read_file(target)             # réseau : lu en UNE fois, sur le fil du moteur
            sig = fileio.signature(target)
            return self._open_on_engine(data, str(target), password), sig
        self._submit_open(job)

    def open_bytes(self, data: bytes, path=None, password: str | None = None) -> None:
        self.path = pathlib.Path(path) if path else None
        self.password = password
        self._submit_open(lambda: (self._open_on_engine(data, str(path) if path else None, password), None))

    def _submit_open(self, job) -> None:
        token = next(self._tokens)

        def done(result, error):
            from .engine import PasswordError
            if error is not None:
                self.failed.emit(str(error), isinstance(error, PasswordError))
                return
            info, sig = result
            self.file_sig = sig
            self.info = info
            self.generation += 1
            self.form_dirty = self.struct_dirty = False
            self.opened.emit(info)
            self.stateChanged.emit()
        self._callbacks[token] = done
        relay = self._relay
        self.engine.submit(job, PRIO_SAVE, on_done=lambda j: relay.done.emit(token, j.result, j.error))

    def _open_on_engine(self, data: bytes, path, password) -> dict:
        old = self.doc
        doc = self.engine.open_document(data, path, password, javascript=self.options["javascript"],
                                        xfa=self.options["xfa"])
        doc.listener = self._relay.events.emit
        doc.asker = self._ask_from_engine
        self.doc = doc
        if old is not None:
            self.engine.close_document(old)
        return doc_info(doc)

    # -- évènements, questions des scripts --

    def _on_events(self, events: list) -> None:
        for event in events:
            if event[0] == "changed" and not self.form_dirty:
                self.form_dirty = True
                self.stateChanged.emit()
            elif event[0] == "blocked":
                self.blocked.emit(event[1])
            elif event[0] == "pages_changed":
                self._refresh_info()
        self.events.emit(events)

    def _refresh_info(self) -> None:
        self.run(doc_info, PRIO_VISIBLE, lambda info, err: self._set_info(info) if err is None else None)

    def _set_info(self, info) -> None:
        self.info = info
        self.reloaded.emit(info)

    def _ask_from_engine(self, kind, title, message, extra):
        """Fil du moteur : un script demande une réponse ; l'interface montre la question (non bloquante pour
        elle), le moteur attend au plus 5 min. Sans interface (tests) : réponse neutre."""
        if self.ask_handler is None:
            return 1 if kind == "alert" else None
        token = next(self._tokens)
        box = [None, threading.Event()]
        self._answers[token] = box
        self._relay.ask.emit(token, kind, title, message, extra)
        box[1].wait(300)
        self._answers.pop(token, None)
        return box[0] if box[0] is not None else (1 if kind == "alert" else None)

    def _on_ask(self, token, kind, title, message, extra):
        box = self._answers.get(token)
        if box is None:
            return
        try:
            box[0] = self.ask_handler(kind, title, message, extra) if self.ask_handler else None
        finally:
            box[1].set()

    # -- rendu --

    def render_tile(self, page: int, scale: float, rect, rotate: int, priority: int, callback, dpr: float = 1.0,
                    forms: bool = True):
        """Tuile `rect` = (x, y, l, h) en pixels de la page à `scale` ; callback(QImage, erreur)."""
        x, y, w, h = (int(v) for v in rect)
        generation = self.generation

        def job(doc):
            img = QImage(w, h, QImage.Format_RGB32)
            addr = ctypes.addressof(ctypes.c_char.from_buffer(img.bits()))
            doc.render(page, scale, (x, y, w, h), rotate=rotate, forms=forms, into=(addr, img.bytesPerLine()))
            img.setDevicePixelRatio(dpr)
            return generation, img
        return self.run(job, priority, callback)

    # -- état --

    @property
    def dirty(self) -> bool:
        return self.form_dirty or self.struct_dirty

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def undo_label(self) -> str:
        return self.undo_stack[-1][0] if self.undo_stack else ""

    def redo_label(self) -> str:
        return self.redo_stack[-1][0] if self.redo_stack else ""

    # -- éditions structurelles --

    def edit_doc(self, label: str, fn, callback=None) -> None:
        """fn(doc) modifie le document PDFium EN PLACE (objets de page : content.py) ; instantané avant / après,
        document rouvert depuis l'après (même chemin que `edit`)."""
        def job(doc):
            before, _ = doc.save_bytes()
            extra = fn(doc)
            after, _ = doc.save_bytes(kill_focus=False)
            return before, self._open_on_engine(after, doc.path, self.password), extra
        self.run(job, PRIO_SAVE, self._edit_done(label, callback))

    def edit(self, label: str, fn, callback=None) -> None:
        """fn(octets) -> octets (PyMuPDF, pikepdf…) sur le fil du moteur ; document rouvert depuis le résultat ;
        instantané pour annuler. callback(résultat de fn ou None, erreur)."""
        def job(doc):
            before, _ = doc.save_bytes()
            result = fn(before)
            data, extra = result if isinstance(result, tuple) else (result, None)
            info = self._open_on_engine(data, doc.path, self.password)
            return before, info, extra
        self.run(job, PRIO_SAVE, self._edit_done(label, callback))

    def _edit_done(self, label, callback):
        def done(result, error):
            if error is not None:
                self.message.emit("%s : %s" % (label, error))
                if callback:
                    callback(None, error)
                return
            before, info, extra = result
            self._push_undo(label, before)
            self.redo_stack.clear()
            self._after_reload(info)
            if callback:
                callback(extra, None)
        return done

    def _push_undo(self, label, data) -> None:
        self.undo_stack.append((label, data))
        while len(self.undo_stack) > 1 and sum(len(d) for _, d in self.undo_stack) > self.UNDO_BYTES:
            self.undo_stack.pop(0)

    def _after_reload(self, info) -> None:
        self.info = info
        self.generation += 1
        self.struct_dirty = True
        self.reloaded.emit(info)
        self.stateChanged.emit()

    def _swap(self, source, target, label_of) -> None:
        if not source:
            return
        label, data = source.pop()

        def job(doc):
            current, _ = doc.save_bytes()
            return current, self._open_on_engine(data, doc.path, self.password)

        def done(result, error):
            if error is not None:
                source.append((label, data))
                self.message.emit("%s impossible : %s" % (label_of, error))
                return
            current, info = result
            target.append((label, current))
            self._after_reload(info)
        self.run(job, PRIO_SAVE, done)

    def undo(self) -> None:
        self._swap(self.undo_stack, self.redo_stack, "Annuler")

    def redo(self) -> None:
        self._swap(self.redo_stack, self.undo_stack, "Rétablir")

    # -- enregistrement --

    def wants_incremental(self) -> bool:
        """Incrémental quand il PROTÈGE quelque chose : signatures, droits d'usage (XFA officiels), XFA."""
        active = self.info.get("active", {})
        return bool(active.get("signatures")) or bool(self.info.get("is_xfa"))

    def save(self, path=None, *, incremental: bool | None = None, force: bool = False, callback=None) -> None:
        """Enregistre (fil du moteur) : octets du document -> écriture transactionnelle vérifiée. Fichier modifié
        ailleurs depuis l'ouverture (et `force` faux) : signal `conflict`, rien n'est écrit."""
        target = pathlib.Path(path) if path else self.path
        if target is None:
            self.saveFailed.emit("aucun fichier : utilisez « Enregistrer sous »")
            return
        same_file = self.path is not None and target == self.path
        if same_file and not force and self.file_sig is not None and fileio.signature(target) != self.file_sig:
            self.conflict.emit(str(target))
            return
        inc = self.wants_incremental() if incremental is None else incremental
        pages = self.info.get("page_count")
        verify_pages = None if self.info.get("is_xfa") else pages

        def job(doc):
            t0 = time.perf_counter()
            data, repaired = doc.save_bytes(incremental=inc)
            fileio.write_atomic(target, data, verify=lambda d: fileio.verify_pdf(d, verify_pages))
            return fileio.signature(target), repaired, (time.perf_counter() - t0) * 1000

        def done(result, error):
            if error is not None:
                self.saveFailed.emit(str(error))
                if callback:
                    callback(False)
                return
            sig, repaired, ms = result
            self.path = target                          # « Enregistrer sous » : le document suit le nouveau fichier
            self.file_sig = sig
            self.form_dirty = self.struct_dirty = False
            if self.path is not None:
                fileio.drop_recovery(self.path)
            note = (" — paquets XFA réparés : %s" % ", ".join(repaired)) if repaired else ""
            self.saved.emit("Enregistré%s (%d ms)%s" % (" (incrémental)" if inc else "", ms, note))
            self.stateChanged.emit()
            if callback:
                callback(True)
        self.run(job, PRIO_SAVE, done)

    def snapshot(self, callback) -> None:
        """Octets courants du document (formulaire compris) -> callback(octets, erreur)."""
        self.run(lambda doc: doc.save_bytes()[0], PRIO_SAVE, callback)

    def write_recovery(self) -> None:
        """Copie de secours (data/pdf_recovery) d'un document modifié, en fond."""
        if self.path is None or not self.dirty:
            return
        original = self.path
        self.run(lambda doc: fileio.write_recovery(original, doc.save_bytes(kill_focus=False)[0]), PRIO_BACKGROUND)

    # -- fin --

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        doc, self.doc = self.doc, None
        if doc is not None:
            self.engine.submit(lambda: self.engine.close_document(doc), PRIO_SAVE)
        self._callbacks.clear()

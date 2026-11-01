"""Export en TÂCHE DE FOND (Qt) : encoder une grande composition (PNG, TIFF…) ne fige pas l'interface.

COHÉRENCE : le fil de fond ne lit JAMAIS le document vivant (l'utilisateur peut continuer à peindre) : il travaille sur un
INSTANTANÉ du document pris au lancement (copie des pixels, une seule fois par export). L'écriture est atomique
(`container.write_atomic`) ; le résultat est signalé par `finished(chemin, notes, erreur)` sur le fil de l'interface ;
jamais de widget touché depuis le fil de fond."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from . import io_images, ops
from .model import Document

_RUNNING: set = set()


def snapshot(doc: Document, layer=None):
    """(copie du document, copie du calque choisi ou None) — pixels recopiés, structure indépendante."""
    twin = Document(doc.width, doc.height, doc.name, doc.dpi, [], doc.icc_name, doc.icc_profile, doc.depth,
                    dict(doc.meta), dict(doc.extra), doc.uid)
    chosen = None
    for original in doc.layers:
        copy = ops._clone(original)
        twin.layers.append(copy)
    if layer is not None:
        for old, new in zip(doc.walk(), twin.walk()):
            if old is layer:
                chosen = new
    return twin, chosen


class _Job(QRunnable):
    def __init__(self, owner, doc, path, layer, options):
        super().__init__()
        self.owner, self.doc, self.path, self.layer, self.options = owner, doc, path, layer, options

    def run(self):
        notes, error = None, None
        try:
            notes = io_images.export_document(self.doc, self.path, layer=self.layer, **self.options)
        except Exception as exc:                                   # noqa: BLE001 - rapporté à l'interface, jamais avalé
            error = exc
        try:
            self.owner.finished.emit(str(self.path), notes, error)
        except RuntimeError:
            pass


class Exporter(QObject):
    finished = Signal(str, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.done = False
        self.notes = None
        self.error = None
        self.finished.connect(self._store)

    def _store(self, _path, notes, error):
        self.notes, self.error, self.done = notes, error, True
        _RUNNING.discard(self)

    def wait(self, timeout_ms: int = 60000):
        """Attend la fin (tests, fermeture) en laissant tourner les évènements."""
        import time
        from PySide6.QtWidgets import QApplication
        end = time.monotonic() + timeout_ms / 1000.0
        while not self.done and time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.002)
        return self.done


def start(doc: Document, path, layer=None, parent=None, **options) -> Exporter:
    """Lance l'export ; rend le suivi (`finished`, `wait`)."""
    copy, chosen = snapshot(doc, layer)
    exporter = Exporter(parent)
    _RUNNING.add(exporter)
    QThreadPool.globalInstance().start(_Job(exporter, copy, path, chosen, options))
    return exporter

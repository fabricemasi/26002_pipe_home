"""Sélection pour la visionneuse, compteurs médias et raccourcis accessibles."""

from pathlib import Path
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from config import IMAGE_EXTENSIONS
from browser_core import _STATUS_FOLDER_SET, count_entries, remember_entry
from previews import is_remote_path

# ==========================================================================
# Colonne
# ==========================================================================

def opens_in_viewer(path: Path) -> bool:
    """Double-clic sur ce fichier = visionneuse de l'appli : image, planche PureRef, ou tout fichier dont
    l'apercu existe deja (3D rendue, PSD, PDF, plans, videos...). Les autres gardent leur logiciel."""
    from config import PREVIEWABLE_EXTENSIONS, PUR_PREVIEW_EXTENSIONS
    from previews import file_image_pixmap
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS or suffix in PUR_PREVIEW_EXTENSIONS:
        return True
    return suffix in PREVIEWABLE_EXTENSIONS and file_image_pixmap(path, asynchronous=True) is not None


class _MediaCountSignals(QObject):
    finished = Signal(int, object)


class _MediaCountTask(QRunnable):
    """Parcours les médias sans bloquer le fil de l'interface."""

    def __init__(self, generation: int, folders: list[Path], entry_counts=False):
        super().__init__()
        self.generation = generation
        self.folders = folders
        self.signals = _MediaCountSignals()
        import threading
        self.cancelled = threading.Event()
        self.entry_counts = entry_counts

    def run(self):
        if self.cancelled.is_set():
            return
        try:
            import lightroom_bridge
            counts = lightroom_bridge.folder_media_counts(self.folders)
        except (ImportError, OSError, ValueError):
            counts = {}
        # Cles = chemins tels qu'affiches (la resolution, un acces disque par ligne, est faite ICI, en fond).
        shown = {}
        for folder in self.folders:
            if self.cancelled.is_set():
                return
            try:
                key = str(Path(folder).resolve())
            except (OSError, ValueError):
                continue
            if key in counts:
                shown[str(folder)] = counts[key]
        entries = {}
        if self.entry_counts:
            for folder in self.folders:
                if self.cancelled.is_set():
                    return
                if not is_remote_path(folder):
                    entries[str(folder)] = count_entries(folder, _STATUS_FOLDER_SET)
        if not self.cancelled.is_set():
            self.signals.finished.emit(self.generation, (shown, entries))


_MEDIA_COUNT_POOL = QThreadPool()
_MEDIA_COUNT_POOL.setMaxThreadCount(2)


def _shortcut_present(target: Path) -> bool:
    """Un raccourci fichier ou dossier s'affiche si sa cible existe.

    Les cibles réseau restent visibles sans test : un partage absent ne doit
    jamais bloquer le rendu d'une colonne.
    """
    from previews import is_remote_path
    if is_remote_path(target):
        remember_entry(target, True)
        return bool(str(target))
    if target.exists():
        remember_entry(target, target.is_dir())
        return True
    return False

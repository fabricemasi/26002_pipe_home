"""Décodage des images de la visionneuse en fond (FocusImageLoader), géométrie commune et noms affichés.

Découpé de focus.py (2026-10-28) ; carte : docs/agents/fm_visionneuse.md."""
import stat as _stat
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QRectF, QRunnable, QSize, QSizeF, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageIOHandler, QImageReader, QPixmap

from config import IMAGE_EXTENSIONS, RAW_EXTENSIONS
import previews


def fit_rect(size: QSizeF, area: QRect, margin: int = 40) -> QRectF:
    """Rectangle d'une image de taille `size` (pixels logiques) dans `area` : taille reelle si
    elle tient (moins une marge), sinon reduite ; centre sur `area`."""
    w, h = max(1.0, size.width()), max(1.0, size.height())
    scale = min(1.0, max(1, area.width() - 2 * margin) / w, max(1, area.height() - 2 * margin) / h)
    w, h = max(1.0, w * scale), max(1.0, h * scale)
    return QRectF(area.x() + (area.width() - w) / 2, area.y() + (area.height() - h) / 2, w, h)


def _pixmap_size(pixmap: QPixmap) -> QSizeF:
    dpr = pixmap.devicePixelRatio() or 1.0
    return QSizeF(pixmap.width() / dpr, pixmap.height() / dpr)


def _scaled_about(rect: QRectF, scale: float, dx: float = 0.0) -> QRectF:
    w, h = rect.width() * scale, rect.height() * scale
    c = rect.center()
    return QRectF(c.x() - w / 2 + dx, c.y() - h / 2, w, h)


# -- Images pleine definition, decodees en fond --------------------------------------------------

def _quarter_turn(reader: QImageReader) -> bool:
    """L'orientation EXIF fait tourner l'image d'un quart de tour (largeur et hauteur echangees)."""
    try:
        return bool(reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90)
    except (AttributeError, TypeError):
        return False


class _DecodeSignals(QObject):
    # cle, date, image pleine, image ajustee a l'ecran, taille reelle (QSizeF) ; None = echec
    done = Signal(str, float, object, object, object, str)


class _DecodeTask(QRunnable):
    def __init__(self, signals: _DecodeSignals, key: str, mtime: float, fit: QSize, max_side: int):
        super().__init__()
        self.setAutoDelete(True)
        self._signals, self._key, self._mtime, self._fit, self._max_side = signals, key, mtime, fit, max_side

    def run(self):
        full = fitted = natural = None
        origin = "Image originale"
        try:
            source_path = Path(self._key)
            from lightroom_bridge import (is_managed, large_file, orient_image, orientation,
                                          original_text, proxy_path)
            managed = is_managed(source_path)
            # Image en focus d'une photo Lightroom : son GRAND aperçu développé (pyramide standard /
            # 1:1, ou rendu du module SDK), jamais le petit proxy des colonnes ; sans lui, l'original.
            large = large_file(source_path) if managed else None
            reader_path = large[0] if large is not None else source_path
            use_original = large is None
            small = proxy_path(source_path) if managed and use_original else None
            reader = QImageReader(str(reader_path))
            reader.setAutoTransform(True)
            size = reader.size()
            # Taille du proxy Lightroom (déjà orienté) : dit si l'original est déjà tourné.
            oriented_proxy_size = QImageReader(str(small)).size() if small is not None else QSize()
            source_transform = reader.transformation() if use_original else 0
            if large is not None:
                origin = large[1]
            elif managed or source_path.suffix.lower() in RAW_EXTENSIONS:
                origin = original_text(source_path)
            if source_path.suffix.lower() in RAW_EXTENSIONS and use_original:
                image, source_transform = previews._decode_embedded_jpeg(
                    source_path, self._max_side, include_transform=True)
                if image is not None:
                    natural = QSizeF(image.size())
            else:
                image = None
            if image is None or image.isNull():
                turned = _quarter_turn(reader)
                if size.isValid() and max(size.width(), size.height()) > self._max_side:
                    reader.setScaledSize(size.scaled(self._max_side, self._max_side, Qt.KeepAspectRatio))
                image = reader.read()
                if size.isValid():
                    natural = QSizeF(size.height(), size.width()) if turned else QSizeF(size)
            if not image.isNull():
                if managed and use_original:
                    code = orientation(source_path)
                    same_axis = (oriented_proxy_size.isValid()
                                 and image.width() != image.height()
                                 and oriented_proxy_size.width() != oriented_proxy_size.height()
                                 and (image.width() > image.height()) ==
                                 (oriented_proxy_size.width() > oriented_proxy_size.height()))
                    # Le JPEG embarqué peut déjà être tourné physiquement ou par
                    # EXIF. Lightroom ne doit appliquer que la rotation manquante.
                    already_turned = code in ("BC", "DA", "CB", "AD") and same_axis
                    if code and getattr(source_transform, "value", source_transform) == 0 and not already_turned:
                        image = orient_image(image, code)
                    natural = QSizeF(image.size())
                fmt = QImage.Format_ARGB32_Premultiplied if image.hasAlphaChannel() else QImage.Format_RGB32
                if image.format() != fmt:
                    image = image.convertToFormat(fmt)
                if natural is None:
                    natural = QSizeF(image.size())
                full = image
                fit = self._fit
                if fit.isValid() and (image.width() > fit.width() or image.height() > fit.height()):
                    fitted = image.scaled(fit, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                else:
                    fitted = image
        except Exception:        # fichier illisible : rien, l'apercu du pipeline reste
            full = fitted = natural = None
        try:
            self._signals.done.emit(self._key, self._mtime, full, fitted, natural, origin)
        except RuntimeError:     # appli en train de se fermer
            pass


class FocusImageLoader(QObject):
    """Images du mode focus (formats d'image courants) decodees EN FOND, jamais sur le fil de
    l'interface : pleine definition (orientation EXIF appliquee, plafonnee a MAX_SIDE) + version
    deja ajustee a l'ecran (dessinee telle quelle, sans reduction a chaque image). Les voisines
    sont demandees a l'avance (voir PipelineBrowser._prefetch_viewer) ; memoire bornee (BUDGET,
    les moins recemment vues partent d'abord). `ready(cle)` a chaque image prete."""

    ready = Signal(str)

    MAX_SIDE = 8192
    BUDGET = 700 * 1024 * 1024

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._signals = _DecodeSignals(self)
        self._signals.done.connect(self._on_done)
        # cle -> (date, pixmap ajuste, image pleine, taille reelle, octets)
        self._entries: OrderedDict = OrderedDict()
        self._pending: dict[str, float] = {}
        self._refresh_after_pending: set[str] = set()
        self._tasks: dict[str, _DecodeTask] = {}      # decodages en file (annulables, voir retain)
        self._failed: dict[str, float] = {}
        self._naturals: dict[str, tuple[float, QSizeF]] = {}
        self._bytes = 0
        self._fit = QSize(1920, 1080)
        self._dpr = 1.0

    @staticmethod
    def supports(path: Path) -> bool:
        return path.suffix.lower() in IMAGE_EXTENSIONS | RAW_EXTENSIONS

    def set_fit(self, size: QSize, dpr: float = 1.0):
        """Zone (pixels PHYSIQUES) ou l'image est ajustee : taille des versions « ecran »."""
        if size.isValid() and not size.isEmpty():
            self._fit = QSize(size)
        self._dpr = dpr or 1.0

    @staticmethod
    def _mtime(path: Path) -> float | None:
        mtime = previews.cached_mtime(path)
        if mtime is not None:
            return mtime
        # L'image courante peut etre choisie alors que les apercus tournent dans
        # `memory_only()` : cached_mtime ne bloque alors pas sur le disque et renvoie
        # None. Pour cette demande explicite de decodage, lire la date du seul fichier
        # cible permet au chargeur plein format de demarrer.
        try:
            info = path.stat()
            return info.st_mtime if _stat.S_ISREG(info.st_mode) else None
        except OSError:
            return None

    def get(self, path: Path):
        """(pixmap ajuste, image pleine, taille reelle) si l'image est prete, sinon None."""
        key = str(path)
        entry = self._entries.get(key)
        if entry is None or entry[0] != self._mtime(path):
            return None
        self._entries.move_to_end(key)
        return entry[1], entry[2], entry[3]

    def request(self, path: Path, urgent: bool = False):
        if not self.supports(path):
            return
        key = str(path)
        mtime = self._mtime(path)
        if mtime is None or self._pending.get(key) == mtime or self._failed.get(key) == mtime:
            return
        entry = self._entries.get(key)
        if entry is not None and entry[0] == mtime:
            return
        self._pending[key] = mtime
        task = self._tasks[key] = _DecodeTask(self._signals, key, mtime, QSize(self._fit), self.MAX_SIDE)
        self._pool.start(task, 1 if urgent else 0)

    def retain(self, paths) -> None:
        """Annule les decodages pas encore commences des fichiers hors de `paths` (defilement
        rapide : l'image ou l'on s'arrete n'attend pas derriere toutes celles qu'on a passees)."""
        keep = {str(path) for path in paths}
        for key in [key for key in self._tasks if key not in keep]:
            if self._pool.tryTake(self._tasks[key]):
                del self._tasks[key]
                self._pending.pop(key, None)

    def natural_size(self, path: Path) -> QSizeF | None:
        """Taille reelle (lue dans l'entete du fichier, sans decoder : rapide) ; None si inconnue."""
        if not self.supports(path):
            return None
        key = str(path)
        mtime = self._mtime(path)
        known = self._naturals.get(key)
        if known is not None and known[0] == mtime:
            return known[1]
        try:
            from lightroom_bridge import is_managed
            managed = is_managed(path)
        except (ImportError, OSError, ValueError):
            managed = False
        if managed:
            # Photo Lightroom : l'image en focus est son grand apercu developpe (recadrage compris),
            # pas l'original ; sa taille arrive avec son decodage EN FOND (_DecodeTask -> _naturals).
            # Jamais de lecture du catalogue ni de Previews.lrdata ici : fil de l'interface.
            return None
        reader = QImageReader(str(path))
        size = reader.size()
        if not size.isValid():
            return None
        natural = QSizeF(size.height(), size.width()) if _quarter_turn(reader) else QSizeF(size)
        if len(self._naturals) > 4096:
            self._naturals.clear()
        self._naturals[key] = (mtime, natural)
        return natural

    def known_natural(self, path: Path) -> QSizeF | None:
        """Taille reelle deja connue (aucune lecture : utilisable en peignant)."""
        known = self._naturals.get(str(path))
        return known[1] if known is not None else None

    def _on_done(self, key: str, mtime: float, full, fitted, natural, origin: str):
        self._tasks.pop(key, None)
        if self._pending.get(key) == mtime:
            del self._pending[key]
        if key in self._refresh_after_pending:
            self._refresh_after_pending.discard(key)
            self.request(Path(key), urgent=True)
            return
        if full is None:
            self._failed[key] = mtime
            return
        pixmap = QPixmap.fromImage(fitted)
        size = full.sizeInBytes() + (fitted.sizeInBytes() if fitted is not full else 0)
        old = self._entries.pop(key, None)
        if old is not None:
            self._bytes -= old[4]
        self._entries[key] = (mtime, pixmap, full, natural, size, origin)
        self._naturals[key] = (mtime, natural)
        self._bytes += size
        while self._bytes > self.BUDGET and len(self._entries) > 1:
            _key, dropped = self._entries.popitem(last=False)
            self._bytes -= dropped[4]
        self.ready.emit(key)

    def clear(self):
        self._entries.clear()
        self._bytes = 0

    def origin(self, path: Path) -> str | None:
        entry = self._entries.get(str(path))
        return entry[5] if entry is not None else None

    def invalidate(self, path: Path):
        key = str(path)
        if key in self._pending:
            self._refresh_after_pending.add(key)
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes -= entry[4]
        self._naturals.pop(key, None)
        self._failed.pop(key, None)


# Nom affiche d'un fichier de la visionneuse (pellicule, planche) : son nom, sauf pour les images
# tirees d'une planche PureRef (fichiers du cache) : « planche.pur · 3/12 » (voir
# PipelineBrowser._expand_viewer_pureref).
DISPLAY_NAMES: dict[str, str] = {}


def display_name(path: Path) -> str:
    return DISPLAY_NAMES.get(str(path)) or path.name

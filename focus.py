"""Etat « focus » : se concentrer sur UN objet precis (aujourd'hui l'apercu image/
turntable de l'inspecteur ; plus tard texte, informations...). Ce module recevra
tout ce qui releve de cet etat ; il vient apres browser_core dans l'ordre de
dependance.

Visionneuse (colonnes masquees, image seule au centre) : l'image glisse d'un fichier a l'autre
sur un RUBAN (la suivante arrive du cote ou l'on va, la precedente s'efface en reculant), se
zoome autour du curseur, et une PELLICULE de vignettes la suit en bas ; les images sont decodees
en fond, voisines prechargees (FocusImageLoader) : rien de lourd sur le fil de l'interface."""
import hashlib
import math
import os
import stat as _stat
import time
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QElapsedTimer, QEvent, QObject, QPoint, QPointF, QRect, QRectF, QRunnable, QSize, QSizeF, Qt, QThreadPool,
    QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QFontMetrics, QImage, QImageIOHandler, QImageReader, QLinearGradient, QPainter, QPen,
    QPixmap, QRegion, QTextCursor, QTransform,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QGraphicsOpacityEffect, QHBoxLayout, QListView, QListWidget, QListWidgetItem, QStyle,
    QStyledItemDelegate, QWidget,
)

from app_style import C, scaled
from browser_core import _fine_timer, _snappy_gil, human_size
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


# Vignettes de la pellicule, a leur taille (cle = chemin + cote en pixels physiques).
_THUMBS: OrderedDict = OrderedDict()
_THUMBS_MAX = 800

# Source des vignettes des IMAGES 2D : une version de FILM_THUMB_MAX px au plus (plus grand cote),
# gardee sur disque (JPEG ; PNG si l'image a de la transparence) dans FILM_THUMB_DIR, cle = chemin
# + date. Au lancement suivant, la pellicule relit ces petits fichiers au lieu de redecoder les
# originaux. Cache PROPRE a la visionneuse, independant de previews.IMAGE_DISK_CACHE_ENABLED
# (suspendu). C'est aussi la taille maximale des vignettes de la pellicule (zoom borne, jamais
# d'agrandissement : FocusFilmstrip.max_thumb_height).
FILM_THUMB_MAX = 300
FILM_THUMB_DIR = previews.FILE_IMAGE_DISK_CACHE_DIR / "filmstrip"
_FILM: OrderedDict = OrderedDict()          # chemin -> (date, QPixmap)
_FILM_MAX = 400
_FILM_PENDING: set = set()
_FILM_FAILED: dict = {}                     # chemin -> date
_FILM_POOL = QThreadPool()
_FILM_POOL.setMaxThreadCount(2)
_film_order = 0


def _film_base(key: str, mtime: float) -> tuple[str, Path]:
    digest = hashlib.sha1(key.lower().encode("utf-8")).hexdigest()[:16]
    return digest, FILM_THUMB_DIR / f"{digest}_{int(mtime)}"


def _has_transparency(image: QImage) -> bool:
    if not image.hasAlphaChannel():
        return False
    alpha = image.convertToFormat(QImage.Format_Alpha8)
    data, line, width = bytes(alpha.constBits()), alpha.bytesPerLine(), alpha.width()
    return any(min(data[y * line:y * line + width]) < 255 for y in range(alpha.height()))


class _FilmSignals(QObject):
    done = Signal(str, float, object)       # chemin, date, image (None = echec)
    ready = Signal()                        # une vignette est arrivee (la pellicule se repeint)


class _FilmTask(QRunnable):
    """Vignette disque relue, sinon tiree de `source` (apercu 640 px deja en memoire) ou decodee
    depuis le fichier, puis enregistree (ecriture dans un temporaire puis remplacement)."""

    def __init__(self, key: str, mtime: float, source: QImage | None):
        super().__init__()
        self.setAutoDelete(True)
        self._key, self._mtime, self._source = key, mtime, source

    def run(self):
        image = None
        try:
            digest, base = _film_base(self._key, self._mtime)
            managed = False
            try:
                from lightroom_bridge import is_managed
                managed = is_managed(Path(self._key))
            except (ImportError, OSError, ValueError):
                pass
            if not managed:
                for ext in (".jpg", ".png"):
                    stored = base.with_name(base.name + ext)
                    if stored.is_file():
                        read = QImage(str(stored))
                        if not read.isNull():
                            image = read
                            break
            persist = not managed
            if managed and image is None:
                source_path = None
                try:
                    from lightroom_bridge import ensure_proxy_path
                    source_path = ensure_proxy_path(Path(self._key))
                except (ImportError, OSError, ValueError):
                    pass
                if source_path is not None and source_path.is_file():
                    image = previews._decode_2d_image(source_path, FILM_THUMB_MAX)
                else:
                    image = self._source
            elif image is None:
                image = self._source
                if image is None or image.isNull():
                    source_path = Path(self._key)
                    if source_path is not None and source_path.is_file():
                        image = previews._decode_2d_image(source_path, FILM_THUMB_MAX)
            if image is not None and not image.isNull():
                if max(image.width(), image.height()) > FILM_THUMB_MAX:
                    image = image.scaled(FILM_THUMB_MAX, FILM_THUMB_MAX, Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation)
                if persist:
                    self._store(image, digest, base)
            else:
                image = None
        except Exception:        # fichier illisible : la petite vignette des colonnes reste
            image = None
        try:
            _FILM_SIGNALS.done.emit(self._key, self._mtime, image)
        except RuntimeError:
            pass

    @staticmethod
    def _store(image: QImage, digest: str, base: Path):
        try:
            FILM_THUMB_DIR.mkdir(parents=True, exist_ok=True)
            fmt, ext = ("PNG", ".png") if _has_transparency(image) else ("JPG", ".jpg")
            target = base.with_name(base.name + ext)
            temp = base.with_name(base.name + ".tmp")
            out = image if fmt == "PNG" else image.convertToFormat(QImage.Format_RGB32)
            if not out.save(str(temp), fmt, 85):
                return
            os.replace(temp, target)
            for old in FILM_THUMB_DIR.glob(digest + "_*"):      # versions perimees du meme fichier
                if old != target:
                    try:
                        old.unlink()
                    except OSError:
                        pass
        except OSError:
            pass


def _on_film_done(key: str, mtime: float, image):
    _FILM_PENDING.discard(key)
    if image is None:
        _FILM_FAILED[key] = mtime
        return
    for stale in [k for k in _THUMBS if k[0] == key]:
        del _THUMBS[stale]
    _FILM.pop(key, None)
    _FILM[key] = (mtime, QPixmap.fromImage(image))
    while len(_FILM) > _FILM_MAX:
        _FILM.popitem(last=False)
    _FILM_SIGNALS.ready.emit()


_FILM_SIGNALS = _FilmSignals()
_FILM_SIGNALS.done.connect(_on_film_done)


def _film_source(path: Path, mtime) -> QPixmap | None:
    """Image dont on tire la vignette : la version disque (300 px) si elle est chargee, sinon
    l'apercu 640 px en memoire ; pour une image 2D, la version disque est demandee en fond (les
    dernieres demandees d'abord : ce sont les vignettes les plus proches du centre, peintes en
    dernier)."""
    key = str(path)
    film = _FILM.get(key)
    if film is not None and film[0] == mtime:
        return film[1]
    managed = False
    try:
        from lightroom_bridge import is_managed, preview_pixmap
        managed = is_managed(path)
    except (ImportError, OSError, ValueError):
        managed = False
    cached = previews._file_image_cache.get(key)
    preview = cached[1] if cached is not None and cached[0] == mtime and not cached[1].isNull() else None
    if managed and preview is None and mtime is not None and key not in _FILM_PENDING:
        preview = preview_pixmap(path, mtime)
    if ((managed or path.suffix.lower() in previews.TWO_D_IMAGE_EXTENSIONS)
            and key not in _FILM_PENDING
            and _FILM_FAILED.get(key) != mtime and not previews.requests_held()):
        global _film_order
        _film_order += 1
        _FILM_PENDING.add(key)
        _FILM_POOL.start(_FilmTask(key, mtime, preview.toImage() if preview is not None else None), _film_order)
    return preview


# Budget de reduction des vignettes pendant une image (pellicule) : au-dela de cette heure
# (time.perf_counter), une vignette pas encore reduite est dessinee depuis sa source, sans attendre.
_SCALE_DEADLINE: float | None = None
FILM_SCALE_BUDGET = 0.004


def thumbnail(path: Path, side: int) -> QPixmap | None:
    """Vignette de `path` dont le plus grand cote fait `side` pixels physiques (FILM_THUMB_MAX au
    plus), tiree de sa version disque ou de l'apercu du pipeline (voir _film_source) ; en
    attendant, la petite vignette des colonnes. Aucune lecture disque : utilisable en peignant."""
    side = min(side, FILM_THUMB_MAX)
    key = (str(path), side)
    mtime = previews.cached_mtime(path)
    hit = _THUMBS.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    source = _film_source(path, mtime) if mtime is not None else None
    if source is None:
        if mtime is None:
            return None
        if str(path) in _FILM_PENDING:
            # Sa vignette est deja en cours (_FilmTask, depuis le fichier) : l'apercu des colonnes
            # seulement s'il est en memoire — pas un 2e decodage du meme fichier en meme temps.
            with previews.memory_only(hold=True):
                return previews.file_image_pixmap(path, asynchronous=True)
        return previews.file_image_pixmap(path, asynchronous=True)
    if max(source.width(), source.height()) <= side:
        pix = source
    elif _SCALE_DEADLINE is not None and time.perf_counter() > _SCALE_DEADLINE:
        return source            # budget de l'image epuise : dessinee telle quelle, reduite a l'image suivante
    else:
        pix = source.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    _THUMBS[key] = (mtime, pix)         # oubliee quand la version disque arrive (_on_film_done)
    if len(_THUMBS) > _THUMBS_MAX:
        _THUMBS.popitem(last=False)
    return pix


# Proxys de la planche : chaque vignette est tiree d'une image un POIL PLUS GRANDE que sa case
# (PROXY_MARGIN), jamais d'une image agrandie. L'apercu du pipeline (640 px, en memoire) quand il
# suffit ; sinon (grandes cases, ecran haute densite) une version decodee EN FOND a cette taille
# (QImageReader.setScaledSize : sans passer par la pleine definition). Memoire bornee (LRU).
PROXY_MARGIN = 1.15
_PROXIES: OrderedDict = OrderedDict()      # chemin -> (date, cote demande, image, pleine definition)
_PROXIES_BUDGET = 300 * 1024 * 1024
_proxy_bytes = 0


# Images des cases de la planche (FocusGallery.cell_pixmap), gardees d'une ouverture a l'autre :
# chemin -> (signature, image, definitive, cle de la vignette). Bornees en nombre (~400 Ko par case).
_CELLS: OrderedDict = OrderedDict()
_CELLS_MAX = 400
_MARKED: OrderedDict = OrderedDict()   # (chemin, "focus" / "hover") -> (signature, vignette, image, coins)


def _film_look_signature() -> str:
    """Ce dont depend l'image d'une case : reglages de la visionneuse et padding des cellules."""
    import json
    import ui_state
    applied = ui_state.APPLIED_SETTINGS or {}
    subset = {k: v for k, v in applied.items()
              if k.startswith(("viewer_film_", "viewer_gallery_text", "viewer_filter_")) or k == "table_cell_padding"}
    subset["icons"] = [previews.cached_mtime(previews.custom_software_icon_path(k))
                       for k in previews.VIEWER_ICON_KEYS]        # icones perso des attributs
    return json.dumps(subset, sort_keys=True, default=str)


def _store_proxy(key: str, entry: tuple) -> None:
    global _proxy_bytes
    old = _PROXIES.pop(key, None)
    if old is not None:
        _proxy_bytes -= old[2].sizeInBytes()
    _PROXIES[key] = entry
    _proxy_bytes += entry[2].sizeInBytes()
    while _proxy_bytes > _PROXIES_BUDGET and len(_PROXIES) > 1:
        _k, gone = _PROXIES.popitem(last=False)
        _proxy_bytes -= gone[2].sizeInBytes()


def _drop_proxy(key: str) -> None:
    global _proxy_bytes
    old = _PROXIES.pop(key, None)
    if old is not None:
        _proxy_bytes -= old[2].sizeInBytes()


class _ProxySignals(QObject):
    done = Signal(str, float, int, object, bool)      # cle, date, cote demande, image (None = echec), pleine def.


class _ProxyTask(QRunnable):
    def __init__(self, signals: _ProxySignals, key: str, mtime: float, side: int):
        super().__init__()
        self.setAutoDelete(True)
        self._signals, self._key, self._mtime, self._side = signals, key, mtime, side

    def run(self):
        image, full = None, True
        try:
            source_path = Path(self._key)
            from lightroom_bridge import ensure_proxy_path, is_managed
            if is_managed(source_path):
                source_path = ensure_proxy_path(source_path)
                if source_path is None or not source_path.is_file():
                    raise FileNotFoundError("Proxy Lightroom indisponible")
            reader = QImageReader(str(source_path))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > self._side:
                reader.setScaledSize(size.scaled(self._side, self._side, Qt.KeepAspectRatio))
                full = False
            read = reader.read()
            image = None if read.isNull() else read
        except Exception:        # fichier illisible : l'apercu du pipeline reste
            image = None
        try:
            self._signals.done.emit(self._key, self._mtime, self._side, image, full)
        except RuntimeError:     # planche refermee
            pass


class FocusOverlay(QWidget):
    """Objet en FOCUS (image ou image de turntable) qui voyage entre sa place
    dans l'inspecteur (`source`) et le centre de la zone des colonnes
    (`target`), position ET echelle interpolees ensemble. Progression p : 0 =
    a la place de l'inspecteur, 1 = centre. Meme horloge/lissage que
    _FadeOverlay ; `retarget` repart de la valeur courante (clic pendant
    l'animation). Couvre toute la zone, transparent a la souris : seuls les
    pixels de l'objet sont peints. Premier maillon du concept « focus » : le
    contenu est un pixmap pour l'instant, d'autres types (texte...) viendront.

    Au repos au centre, c'est la VISIONNEUSE (set_viewer) : `show_image` fait glisser l'image
    suivante / precedente sur un ruban (decalage `_shift`, en images, qui revient a 0 ; les
    voisines viennent du rappel `neighbours(k)`), `bump` = petit rebond aux extremites, zoom
    anime autour d'un point (`zoom_by`, Ctrl+molette) et deplacement de l'image zoomee a la
    souris."""

    SLIDE_MS = 330
    BUMP_MS = 260

    def __init__(self, parent, pixmap: QPixmap, source: QRectF, target: QRectF, start: float, end: float,
                 duration_ms: int = 420, on_finished=None, on_done=None, on_double_click=None,
                 on_wheel=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(parent.rect())
        self._source = source
        self._target = target
        self._base = pixmap
        self._cache_key = None
        self._cache = None
        self._value = start
        self._from = start
        self._end = end
        self._duration = max(1, duration_ms)
        self._on_finished = on_finished
        self._on_done = on_done
        # Double-clic sur l'objet AU CENTRE (au repos) : `on_double_click`
        # (meme effet que le bouton « masquer », voir _update_hit_area).
        self._on_double_click = on_double_click
        # Molette sur l'objet au repos : `on_wheel(event)` (image suivante / precedente).
        self._on_wheel = on_wheel
        # Visionneuse (voir set_viewer) : taille reelle de l'image, image pleine definition pour
        # le zoom, voisines du ruban, rappel a chaque pas du ruban (la pellicule suit), zones
        # laissees a la souris (boutons).
        self._natural: QSizeF | None = None
        self._area: QRect | None = None   # zone ou l'image est ajustee (defaut : tout l'overlay)
        self._full: QImage | None = None
        self._neighbours = None
        self._on_moved = None
        self._holes: list = []
        self._shift = 0.0
        self._shift_from = 0.0
        self._slide_t0 = 0
        self._bump_dir = 0
        self._bump_t0 = 0
        self._zoom = 1.0
        self._zoom_goal = 1.0
        self._pan = QPointF()
        self._anchor = None           # (point fixe, position relative dans l'image) du zoom
        self._drag = None
        self._vclock = QElapsedTimer()
        self._vclock.start()
        self._vlast = 0
        self._vtimer = QTimer(self)
        self._vtimer.setTimerType(Qt.PreciseTimer)
        self._vtimer.setInterval(8)
        self._vtimer.timeout.connect(self._viewer_tick)
        # Cadre de l'image (Reglages > Visionneuse > Focus : bordures, border radius), `restyle`.
        look = _film_look()
        self._frame = look["focus_image"]
        self._shadow = look["focus_shadow"]      # Reglages > Visionneuse > Focus > Ombres de l'image
        self._textures: dict = {}     # cacheKey -> copie a ratio de pixels 1 (texture des coins arrondis)
        self.running = True
        self.hold = True    # le proprietaire le retire (voir PipelineBrowser._show_columns_now)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._tick)
        self._clock.start()
        _fine_timer(True)
        self._timer.start()

    @staticmethod
    def target_rect(pixmap: QPixmap, area: QRect, margin: int = 40) -> QRectF:
        """Taille reelle si elle tient dans `area` (moins une marge), sinon reduite ;
        centre sur `area`."""
        return fit_rect(_pixmap_size(pixmap), area, margin)

    def _layout_size(self) -> QSizeF:
        """Taille de reference de l'image : sa taille reelle si connue (l'apercu montre en
        attendant la pleine definition prend deja sa place definitive), sinon celle du pixmap."""
        return self._natural if self._natural is not None else _pixmap_size(self._base)

    def _fit_area(self) -> QRect:
        return self._area if self._area is not None else self.parentWidget().rect()

    def set_geometry_target(self, area: QRect | None, source: QRectF = None):
        """Redimensionnement de la fenetre : recentre dans `area` (None : la zone deja connue) et
        suit l'inspecteur si connu."""
        self.setGeometry(self.parentWidget().rect())
        if area is not None:
            self._area = QRect(area)
        self._target = fit_rect(self._layout_size(), self._fit_area())
        if source is not None:
            self._source = source
        self._clamp_pan()
        self._update_hit_area()
        self.update()

    def _update_hit_area(self):
        """Au repos au centre, seuls les pixels de l'objet captent la souris
        (double-clic, deplacement de l'image zoomee) ; partout ailleurs, et pendant
        l'animation, l'overlay reste transparent a la souris."""
        at_center = not self.running and self._value >= 1.0 and self._on_double_click is not None
        # Pendant un glissement / un zoom, pas de masque : il decouperait aussi le DESSIN (voisines
        # du ruban, image qui grandit) ; la souris traverse, la molette arrive par la zone.
        at_center = at_center and not (self._vtimer.isActive() and self._drag is None)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not at_center)
        if at_center:
            # Le masque decoupe aussi le DESSIN : il couvre l'ombre de l'image (un clic dessus = un clic a
            # cote de l'image, meme effet).
            grow = self._shadow["size"] if self._shadow is not None else 0
            region = QRegion(self._view_rect().toAlignedRect().adjusted(-grow, -grow, grow, grow)
                             .intersected(self.rect()))
            for hole in self._holes:
                region -= QRegion(hole)
            self.setMask(region)
            self.setCursor(Qt.OpenHandCursor if self.zoomed() else Qt.ArrowCursor)
        else:
            self.clearMask()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_click is not None:
            event.accept()                   # visionneuse : pas de double-clic sur l'image (le clic agit seul)
            return
        if event.button() == Qt.LeftButton and self._on_double_click is not None:
            self._drag = None
            self._on_double_click()
            return
        super().mouseDoubleClickEvent(event)

    # Clic SIMPLE sur l'image (visionneuse) : agit AUSSITOT au relachement (demande de l'utilisateur :
    # plus de double-clic sur l'image, qui obligeait a attendre son delai) ; un glisser (image zoomee
    # deplacee) n'en est pas un.
    _click_at = None
    _on_click = None

    def wheelEvent(self, event):
        if self._on_wheel is not None:
            self._on_wheel(event)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_click is not None and self._at_rest():
            self._click_at = event.globalPosition()
        if event.button() == Qt.LeftButton and self.zoomed() and self._at_rest():
            self._drag = (event.position(), QPointF(self._pan))
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if self._click_at is not None:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            start, pan = self._drag
            self._pan = pan + (event.position() - start)
            self._clamp_pan()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        press, self._click_at = self._click_at, None
        clicked = (press is not None and event.button() == Qt.LeftButton and self._on_click is not None
                   and (event.globalPosition() - press).manhattanLength() < QApplication.startDragDistance())
        dragged = self._drag is not None and event.button() == Qt.LeftButton
        if dragged:
            self._drag = None
            self._update_hit_area()
        if clicked and self._at_rest():
            self._on_click(QPointF(event.position()))
        if dragged or clicked or press is not None:
            event.accept()
            return
        if press is not None:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def retarget(self, end: float, on_finished=None):
        self.reset_view()
        self._from = self._value
        self._end = end
        self._on_finished = on_finished
        self.running = True
        self._update_hit_area()
        self._clock.restart()
        if not self._timer.isActive():
            _fine_timer(True)
            self._timer.start()

    def current_rect(self) -> QRectF:
        t = self._value
        s, e = self._source, self._target
        return QRectF(s.x() + (e.x() - s.x()) * t, s.y() + (e.y() - s.y()) * t,
                      s.width() + (e.width() - s.width()) * t, s.height() + (e.height() - s.height()) * t)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._at_rest():
            self._paint_viewer(painter)
            return
        rect = self.current_rect()
        # Pre-reduit a la plus grande des deux tailles extremes : dessiner une
        # grande image reduite a chaque image de l'animation serait trop lent.
        big_w = max(self._source.width(), self._target.width())
        pixmap = self._display_pixmap(big_w)
        # Cadre (bordures, border radius) : il s'installe avec le trajet vers le centre (0 a l'inspecteur
        # ou dans la case de la planche, entier au centre), sans saut a l'arrivee.
        self._paint_framed(painter, rect, pixmap, max(0.0, min(1.0, self._value)))

    def restyle(self):
        """Reglages > Visionneuse > Focus changes : nouveau cadre de l'image."""
        look = _film_look()
        self._frame = look["focus_image"]
        self._shadow = look["focus_shadow"]
        self._update_hit_area()                  # la zone cliquable couvre l'ombre (sinon son masque la coupe)
        self.update()

    def _texture(self, src):
        """`src` (QPixmap / QImage) a ratio de pixels 1 : la texture d'un pinceau Qt est mal mise a
        l'echelle sinon (mesure : 2 fois trop petite a 1,5, 4 fois a 2). Copie faite une fois, gardee."""
        if (src.devicePixelRatio() or 1.0) == 1.0:
            return src
        key = src.cacheKey()
        tex = self._textures.get(key)
        if tex is None:
            tex = src.copy()
            tex.setDevicePixelRatio(1.0)
            if len(self._textures) > 6:
                self._textures.clear()
            self._textures[key] = tex
        return tex

    def _paint_framed(self, painter: QPainter, rect: QRectF, src, strength: float = 1.0):
        """Image `src` (QPixmap ou QImage, entiere) dans `rect`, avec le cadre de Reglages > Visionneuse >
        Focus : coins arrondis LISSES (un setClipPath ne l'est pas : l'image est posee en pinceau sur le
        chemin arrondi) puis bordures par-dessus. `strength` (0-1) : part du cadre (vol vers le centre)."""
        frame = self._frame
        radius = {k: round(v * strength) for k, v in frame["radius"].items()}
        if self._shadow is not None:
            from settings_widgets import paint_shadow
            paint_shadow(painter, rect, radius, self._shadow, strength)
        if any(radius.values()) and rect.width() > 0 and rect.height() > 0:
            from settings_widgets import _rounded_rect_path
            tex = self._texture(src)
            brush = QBrush(tex)
            transform = QTransform()
            transform.translate(rect.x(), rect.y())
            transform.scale(rect.width() / max(1, tex.width()), rect.height() / max(1, tex.height()))
            brush.setTransform(transform)
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.drawPath(_rounded_rect_path(rect, radius))
            painter.restore()
        elif isinstance(src, QImage):
            painter.drawImage(rect, src, QRectF(src.rect()))
        else:
            painter.drawPixmap(rect, src, QRectF(src.rect()))
        if frame["thick"] and strength > 0.0:
            from settings_widgets import _paint_bordered_vector
            painter.save()
            painter.setOpacity(painter.opacity() * strength)
            _paint_bordered_vector(painter, rect.toRect(), radius, frame["on"], frame["thick"], frame["colors"], None)
            painter.restore()

    def _display_pixmap(self, width: float) -> QPixmap:
        """L'image a `width` pixels logiques de large au plus : reduite UNE fois (gardee) si le
        pixmap est nettement plus grand, sinon tel quel."""
        dpr = self._base.devicePixelRatio() or 1.0
        if self._base.width() / dpr <= width * 1.01:
            return self._base
        key = round(width)
        if self._cache_key != key:
            self._cache = self._base.scaledToWidth(max(1, round(width * dpr)), Qt.SmoothTransformation)
            self._cache_key = key
        return self._cache

    def _tick(self):
        distance = abs(self._end - self._from)
        t = min(1.0, self._clock.elapsed() / (self._duration * max(distance, 0.05)))
        eased = t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
        before = self.current_rect()
        self._value = self._from + (self._end - self._from) * eased
        # Seule la zone traversee (ancienne + nouvelle place) est repeinte : ce qui est dessous (planche,
        # colonnes) n'est pas redessine en entier a chaque image.
        grow = 2 + (self._shadow["size"] if self._shadow is not None else 0)    # ombre comprise
        self.update(before.united(self.current_rect()).toAlignedRect().adjusted(-grow, -grow, grow, grow))
        if t >= 1.0:
            self._finish()

    def finish_now(self):
        if self.running:
            self._finish()

    def jump(self, value: float):
        """Pose `value` sans animation ni rappel (une animation en cours est abandonnee)."""
        if self.running:
            self._timer.stop()
            _fine_timer(False)
            self.running = False
        self.reset_view()
        self._on_finished = None
        self._value = self._from = self._end = value
        self._update_hit_area()
        self.update()

    def _finish(self):
        self._timer.stop()
        _fine_timer(False)
        self.running = False
        self._value = self._end
        self._update_hit_area()
        self.update()
        if self._on_finished is not None:
            self._on_finished()
        if self._on_done is not None:
            self._on_done()

    def dispose(self):
        if self.running:
            self._timer.stop()
            _fine_timer(False)
            self.running = False
        self._stop_viewer_anim()
        self.hide()
        self.deleteLater()

    # -- Visionneuse --------------------------------------------------------------------------

    def set_viewer(self, neighbours=None, on_moved=None, holes=None, on_click=None):
        """`neighbours(k)` -> (QPixmap, QSizeF | None) | None : image k places plus loin sur le
        ruban (k negatif : avant) ; `on_moved(decalage)` a chaque pas du ruban ; `holes` :
        rectangles ou la souris passe a travers (boutons) ; `on_click()` : clic simple sur l'image
        (sans glisser ni double-clic, voir mouseReleaseEvent)."""
        self._neighbours = neighbours
        self._on_moved = on_moved
        self._on_click = on_click
        self._holes = list(holes or [])
        self._update_hit_area()

    def set_holes(self, holes):
        self._holes = list(holes or [])
        self._update_hit_area()

    def set_natural(self, natural: QSizeF | None, area: QRect | None = None):
        """Taille reelle de l'image : sa place au centre est calculee sur elle (dans `area`)."""
        self._natural = natural
        if area is not None:
            self._area = QRect(area)
        self._target = fit_rect(self._layout_size(), self._fit_area())
        self._clamp_pan()
        self._update_hit_area()
        self.update()

    def _at_rest(self) -> bool:
        return not self.running and self._value >= 1.0

    def show_image(self, pixmap: QPixmap, natural: QSizeF | None = None, full: QImage | None = None,
                   delta: int = 0):
        """Nouvelle image au centre. `delta` : son ecart avec la precedente (1 = suivante) ;
        elle arrive alors par le ruban du cote ou l'on va (decalage borne a 3 images)."""
        self._reset_zoom()
        self._base = pixmap
        self._cache_key = self._cache = None
        self._full = full
        self._natural = natural
        self._target = fit_rect(self._layout_size(), self._fit_area())
        if delta and self._at_rest() and self._neighbours is not None:
            self._shift_from = self._shift = max(-3.0, min(3.0, self._shift + delta))
            self._slide_t0 = self._vclock.elapsed()
            self._start_viewer_anim()
        self._update_hit_area()
        self.update()

    def upgrade(self, pixmap: QPixmap, natural: QSizeF | None = None, full: QImage | None = None):
        """Meme image, meilleure definition (pleine definition arrivee en fond) : rien ne bouge."""
        self._base = pixmap
        self._cache_key = self._cache = None
        if full is not None:
            self._full = full
        if natural is not None:
            self._natural = natural
        # Taille reelle connue : meme place. Sinon (apercu remplacant une carte) : celle du pixmap.
        self._target = fit_rect(self._layout_size(), self._fit_area())
        self._clamp_pan()
        self._update_hit_area()
        self.update()

    def bump(self, direction: int):
        """Plus d'image dans cette direction : l'image esquisse le mouvement et revient."""
        if not self._at_rest():
            return
        self._bump_dir = 1 if direction > 0 else -1
        self._bump_t0 = self._vclock.elapsed()
        self._start_viewer_anim()

    def ribbon_offset(self) -> float:
        """Decalage visuel du ruban, en images (0 = image en cours au centre)."""
        offset = self._shift
        if self._bump_dir:
            u = min(1.0, (self._vclock.elapsed() - self._bump_t0) / self.BUMP_MS)
            offset -= self._bump_dir * 0.06 * math.sin(math.pi * u) * (1.0 - u)
        return offset

    def animating(self) -> bool:
        return self.running or self._vtimer.isActive() or self._drag is not None

    def zoomed(self) -> bool:
        return self._zoom_goal > 1.001 or self._zoom > 1.001

    def zoom_level(self) -> float:
        return self._zoom_goal

    def _max_zoom(self) -> float:
        actual = self._actual_zoom()
        return max(4.0, min(40.0, actual * 4.0))

    def _actual_zoom(self) -> float:
        """Zoom ou l'image est a sa taille reelle (1 pixel image = 1 pixel logique)."""
        width = self._target.width()
        return max(1.0, self._layout_size().width() / width) if width > 0 else 1.0

    def zoom_by(self, factor: float, anchor: QPointF | None = None):
        """Zoom anime vers zoom courant * `factor`, en gardant fixe le point `anchor` (repere de
        l'overlay ; centre de l'image par defaut). 1 = image ajustee."""
        if not self._at_rest():
            return
        goal = max(1.0, min(self._max_zoom(), self._zoom_goal * factor))
        self._zoom_to(goal, anchor)

    def zoom_reset(self):
        self._zoom_to(1.0, None)

    def zoom_actual(self, anchor: QPointF | None = None):
        """Anime vers la taille reelle de l'image (1 pixel image = 1 pixel logique)."""
        self._zoom_to(self._actual_zoom(), anchor)

    def zoom_toggle_actual(self, anchor: QPointF | None = None):
        """Ajustee <-> taille reelle (sans effet si l'image tient deja a sa taille reelle)."""
        actual = self._actual_zoom()
        if actual <= 1.01 and not self.zoomed():
            return
        self._zoom_to(1.0 if self.zoomed() else actual, anchor)

    def _zoom_to(self, goal: float, anchor: QPointF | None):
        if not self._at_rest():
            return
        self._zoom_goal = goal
        # Point fixe : `anchor` (centre de la zone par defaut) et sa position RELATIVE dans
        # l'image, relevee une fois : chaque image du zoom en repart (le recentrage d'une image
        # encore plus petite que la zone ne s'accumule donc pas).
        anchor = QPointF(anchor) if anchor is not None else QPointF(self._fit_area().center())
        view = self._view_rect()
        self._anchor = (anchor, (anchor.x() - view.x()) / max(1e-6, view.width()),
                        (anchor.y() - view.y()) / max(1e-6, view.height()))
        self._start_viewer_anim()

    def _reset_zoom(self):
        self._zoom = self._zoom_goal = 1.0
        self._pan = QPointF()
        self._anchor = None
        self._drag = None

    def reset_view(self):
        """Sans animation : image ajustee, au centre du ruban (avant un vol, un changement d'etat)."""
        self._reset_zoom()
        self._shift = self._shift_from = 0.0
        self._bump_dir = 0
        self._stop_viewer_anim()
        if self._on_moved is not None:
            self._on_moved(0.0)
        self._update_hit_area()
        self.update()

    def _view_rect(self) -> QRectF:
        """Place de l'image en cours au repos : ajustee, zoomee autour de son centre + deplacement."""
        t = self._target
        z = self._zoom
        c = t.center() + self._pan
        return QRectF(c.x() - t.width() * z / 2, c.y() - t.height() * z / 2, t.width() * z, t.height() * z)

    def _clamp_pan(self):
        """Une image zoomee plus grande que la zone la couvre toujours (pas de bord vide) ; plus
        petite, elle reste centree."""
        t = self._target
        z = self._zoom
        area = QRectF(self.rect())
        base = t.center()
        x, y = self._pan.x(), self._pan.y()
        w, h = t.width() * z, t.height() * z
        if w <= area.width():
            x = 0.0
        else:
            x = max(area.right() - w / 2, min(area.left() + w / 2, base.x() + x)) - base.x()
        if h <= area.height():
            y = 0.0
        else:
            y = max(area.bottom() - h / 2, min(area.top() + h / 2, base.y() + y)) - base.y()
        self._pan = QPointF(x, y)

    def _start_viewer_anim(self):
        if not self._vtimer.isActive():
            self._vlast = self._vclock.elapsed()
            _fine_timer(True)
            self._vtimer.start()
            self._update_hit_area()          # masque retire le temps du mouvement

    def _stop_viewer_anim(self):
        if self._vtimer.isActive():
            self._vtimer.stop()
            _fine_timer(False)

    def _viewer_tick(self):
        now = self._vclock.elapsed()
        dt = max(0.001, (now - self._vlast) / 1000.0)
        self._vlast = now
        busy = False
        if self._shift_from:
            u = min(1.0, (now - self._slide_t0) / self.SLIDE_MS)
            self._shift = self._shift_from * (1.0 - u) ** 3     # depart vif, arrivee douce
            if u >= 1.0:
                self._shift = self._shift_from = 0.0
            else:
                busy = True
        if self._bump_dir:
            if now - self._bump_t0 >= self.BUMP_MS:
                self._bump_dir = 0
            else:
                busy = True
        if abs(self._zoom - self._zoom_goal) > 1e-6:
            z1 = self._zoom_goal + (self._zoom - self._zoom_goal) * math.exp(-dt / 0.06)
            if abs(z1 - self._zoom_goal) < self._zoom_goal * 0.002:
                z1 = self._zoom_goal
            self._zoom = z1
            if self._anchor is not None:
                # Le point de l'image sous le curseur reste sous le curseur.
                anchor, u, v = self._anchor
                t = self._target
                centre = QPointF(anchor.x() - (u - 0.5) * t.width() * z1, anchor.y() - (v - 0.5) * t.height() * z1)
                self._pan = centre - t.center()
            self._clamp_pan()
            busy = busy or z1 != self._zoom_goal
        if self._on_moved is not None:
            self._on_moved(self.ribbon_offset())
        self.update()
        if not busy:
            self._stop_viewer_anim()
            self._update_hit_area()

    def _paint_viewer(self, painter: QPainter):
        offset = self.ribbon_offset()
        if abs(offset) < 1e-4 or self._neighbours is None:
            self._draw_current(painter, self._view_rect())
            return
        # Ruban : chaque image a sa place k (0 = en cours), decalee de (k + offset) pas ; elle
        # recule, retrecit un peu et s'efface en s'eloignant du centre. La plus proche par-dessus.
        stride = max(1.0, self.width() * 0.72)
        area = self._fit_area()
        items = []
        for k in range(math.floor(-offset) - 1, math.ceil(-offset) + 2):
            d = k + offset
            if abs(d) >= 1.0:
                continue
            if k == 0:
                items.append((abs(d), d, None, self._view_rect()))
                continue
            got = self._neighbours(k)
            if not got:
                continue
            pixmap, natural = got
            size = natural if natural is not None else _pixmap_size(pixmap)
            items.append((abs(d), d, pixmap, fit_rect(size, area)))
        for distance, d, pixmap, rect in sorted(items, key=lambda item: -item[0]):
            painter.setOpacity(max(0.0, min(1.0, (1.0 - distance) / 0.65)))
            moved = _scaled_about(rect, 1.0 - 0.1 * distance, d * stride)
            if pixmap is None:
                self._draw_current(painter, moved)
            else:
                self._paint_framed(painter, moved, pixmap)
        painter.setOpacity(1.0)

    def _draw_current(self, painter: QPainter, rect: QRectF):
        dpr = self.devicePixelRatioF() or 1.0
        if self._full is not None and rect.width() * dpr > self._base.width() * 1.02:
            # Zoom au-dela de la version ajustee : l'image pleine definition (seule la partie
            # visible est echantillonnee).
            self._paint_framed(painter, rect, self._full)
            return
        self._paint_framed(painter, rect, self._display_pixmap(rect.width()))


def placeholder_pixmap(path: Path, note: str = "Aperçu pas encore rendu") -> QPixmap:
    """Carte montree au centre (etat focus) pour un fichier sans apercu disponible, typiquement un
    fichier 3D jamais rendu : son type en grand, son nom, `note`. Le diaporama ne le saute pas."""
    width, height = 960, 600
    pix = QPixmap(width, height)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setPen(QPen(QColor(C["border"]), 2))
    painter.setBrush(QColor(C["well"]))
    painter.drawRoundedRect(QRectF(1, 1, width - 2, height - 2), 18, 18)
    font = QFont(painter.font())
    font.setPixelSize(132)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(C["dim"]))
    painter.drawText(QRect(0, 70, width, 260), Qt.AlignCenter, path.suffix.lstrip(".").upper() or "?")
    font.setPixelSize(30)
    font.setBold(False)
    painter.setFont(font)
    painter.setPen(QColor(C["text"]))
    name = QFontMetrics(font).elidedText(path.name, Qt.ElideMiddle, width - 80)
    painter.drawText(QRect(40, 350, width - 80, 60), Qt.AlignCenter, name)
    font.setPixelSize(22)
    painter.setFont(font)
    painter.setPen(QColor(C["dim"]))
    painter.drawText(QRect(40, 420, width - 80, 50), Qt.AlignCenter, note)
    painter.end()
    return pix


_FILM_SIDES = ("top", "right", "bottom", "left")


def film_text_ratio() -> float:
    """Hauteur de la sous-cellule texte d'une diapositive / celle de sa sous-cellule image
    (`viewer_film_text_ratio`, Ctrl + tirer la bordure entre les deux)."""
    import ui_state
    try:
        ratio = float((ui_state.APPLIED_SETTINGS or {}).get("viewer_film_text_ratio", 0.32))
    except (TypeError, ValueError):
        ratio = 0.32
    return max(FocusFilmstrip.RATIO_MIN, min(FocusFilmstrip.RATIO_MAX, ratio))


def _film_look() -> dict:
    """Habillage des diapositives = Reglages > Visionneuse > Tableau / Sous cellule image / Sous cellule
    texte (cles `viewer_film_*`), lu dans les reglages appliques : par partie, bordures (cotes, couleurs,
    epaisseur), border radius, fond, police et couleur du texte."""
    import ui_state
    from app_style import font as app_font, resolve_color_ref
    from settings_store import DEFAULT_SETTINGS, _coerce_corner_radius, _coerce_side_enabled
    from settings_widgets import shadow_look
    values = dict(DEFAULT_SETTINGS)
    values.update(ui_state.APPLIED_SETTINGS or {})

    def box(pre: str, bg: bool = True) -> dict:
        raw = values.get(f"{pre}_border")
        colors = {s: resolve_color_ref(raw.get(s) if isinstance(raw, dict) else raw, "#2a2e32") for s in _FILM_SIDES}
        fill = QColor(resolve_color_ref(values.get(f"{pre}_bg"), "#00000000")) if bg else QColor(0, 0, 0, 0)
        try:
            thick = max(0, int(values.get(f"{pre}_border_thickness", 1)))
        except (TypeError, ValueError):
            thick = 1
        sides = _coerce_side_enabled(values.get(f"{pre}_border_enabled"), False)
        return {"on": sides, "colors": colors, "thick": thick if any(sides.values()) else 0,
                "radius": _coerce_corner_radius(values.get(f"{pre}_border_radius", 0)),
                "fill": fill.name(QColor.NameFormat.HexArgb) if fill.alpha() else None}

    def text(pre: str) -> tuple:
        smooth = values.get(f"{pre}_font_smoothing", "current") if values.get(f"{pre}_font_smoothing_enabled") \
            else "current"
        try:
            size = max(4, int(values.get(f"{pre}_font_size", 11)))
        except (TypeError, ValueError):
            size = 11
        weight = 700 if values.get(f"{pre}_font_bold") else 400
        # Choix « app » = un ROLE de Polices principales (« Police principale »...), a traduire en vraie
        # famille comme partout ailleurs (sinon Qt recevait ce libelle et prenait une police de repli :
        # bug signale) ; « Systeme » / vide = police par defaut.
        label = (values.get(f"{pre}_font_family") or "").strip()
        family = None
        if label and label != "Systeme":
            from browser_core import _resolve_font_family
            family = _resolve_font_family(label, size, weight)
        qfont = app_font(size, weight, family=family, smoothing=smooth,
                         italic=bool(values.get(f"{pre}_font_italic")))
        return qfont, QColor(resolve_color_ref(values.get(f"{pre}_font_color"), C["text"]))

    def mark(key: str, default: str) -> QColor:
        return QColor(resolve_color_ref(values.get(key), default))

    def inner(axis: str) -> tuple:
        # Planche : filets entre les cellules (actif, couleur, epaisseur), Visionneuse > Tableau.
        pre = f"viewer_film_table_inner_{axis}"
        try:
            thick = max(0, int(values.get(f"{pre}_thickness", 1) or 0))
        except (TypeError, ValueError):
            thick = 1
        return bool(values.get(f"{pre}_enabled")), mark(f"{pre}_color", "#2a2e32"), thick

    def pad(key: str) -> dict:
        raw = values.get(key)
        raw = raw if isinstance(raw, dict) else {}
        out = {}
        for side in _FILM_SIDES:
            try:
                out[side] = max(0, int(raw.get(side, 0) or 0))
            except (TypeError, ValueError):
                out[side] = 0
        return out

    return {"table": box("viewer_film_table"), "image_cell": box("viewer_film_image_cell"),
            "bg_padding": pad("viewer_film_bg_padding"),            # fond de la cellule dans la case
            "image_padding": pad("viewer_film_image_padding"),      # image dans le fond
            "attr_padding": pad("viewer_film_attr_padding"),        # icones d'attribut : calque a part

            "image": box("viewer_film_image", bg=False), "text_cell": box("viewer_film_text_cell"),
            "rank_font": text("viewer_film_table"), "ext_font": text("viewer_film_image_cell"),
            "name_font": text("viewer_film_text_cell"),
            "focus": mark("viewer_film_table_focus_color", "#465f9bd0"),
            "hover": mark("viewer_film_table_hover_color", "#165f9bd0"),
            "inner_h": inner("h"), "inner_v": inner("v"),
            "focus_image": box("viewer_focus_image", bg=False),
            # Ombres (lignes « Ombres » : settings_widgets.shadow_look ; None = aucune).
            "image_shadow": shadow_look(values, "viewer_film_image_shadow", resolve_color_ref),
            "table_shadow": shadow_look(values, "viewer_film_table_shadow", resolve_color_ref),
            "focus_shadow": shadow_look(values, "viewer_focus_image_shadow", resolve_color_ref),
            # Couleur attribuee a un fichier (Visionneuse > Filtres > « Opacite des couleurs attribuees »).
            "color_mark": {"opacity": max(0, min(100, int(values.get("viewer_filter_mark_opacity", 35) or 0))),
                           "border": bool(values.get("viewer_filter_mark_border")),
                           "thick": max(1, int(values.get("viewer_filter_mark_border_thickness", 2) or 1))}}


def _paint_film_box(painter: QPainter, rect: QRectF, look: dict):
    """Fond + bordures (par cote) + border radius d'une partie de diapositive (tableau, sous-cellule,
    image) : le trace des reglages (settings_widgets._paint_bordered_vector), jamais un style a part."""
    if look["fill"] is None and not look["thick"]:
        return
    from settings_widgets import _paint_bordered_vector
    _paint_bordered_vector(painter, rect.toRect(), look["radius"], look["on"], look["thick"], look["colors"],
                           look["fill"])


def _film_inner(rect: QRectF, look: dict) -> QRectF:
    """`rect` moins l'epaisseur des bordures actives de `look`."""
    t = look["thick"]
    on = look["on"]
    return rect.adjusted(t if on["left"] else 0, t if on["top"] else 0,
                         -(t if on["right"] else 0), -(t if on["bottom"] else 0))


def _gallery_mark_on_sub_cells(look: dict) -> bool:
    """Ou se pose le focus / survol d'une case de la planche : sur ses DEUX sous-cellules quand leurs
    deux fonds sont affiches, ou quand le tableau est sans fond (opacite 0) et sans border radius —
    un border radius que rien ne dessine (ni fond ni bordure) compte comme absent ; sinon (au moins
    un fond de sous-cellule absent) sur toute la cellule du tableau."""
    table = look["table"]
    if not look.get("split"):
        # Case non divisee (demande de l'utilisateur) : focus / survol / couleur suivent le FOND DE LA CELLULE
        # quand le fond du tableau est 100 % transparent, sinon la cellule du tableau (4 coins de la cellule
        # = seulement ceux du tableau, `corners`).
        return table["fill"] is None
    if look["image_cell"]["fill"] is not None and look["text_cell"]["fill"] is not None:
        return True
    return table["fill"] is None and (not table["thick"] or not any(table["radius"].values()))


def _paint_gallery_mark(painter: QPainter, look: dict, rect: QRect, which: str, corners: frozenset = frozenset()):
    """Case en cours (`which` = "focus") ou survolee ("hover") : couleur de Visionneuse > Tableau, sans
    bordure. Sur les sous-cellules (`rect` = les deux) : coins du haut = ceux de la sous-cellule image,
    du bas = ceux de la sous-cellule texte ; sur la cellule : border radius du tableau, mais seulement aux
    coins que la cellule partage avec le tableau (`corners`, FocusGallery.table_corners : la premiere
    case en haut a gauche n'arrondit que son coin haut gauche...)."""
    color = look[which]
    if color.alpha() == 0 or rect.width() <= 0 or rect.height() <= 0:
        return
    radius = _gallery_mark_radius(look, corners)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if any(radius.values()):
        from settings_widgets import _rounded_rect_path
        painter.fillPath(_rounded_rect_path(rect, radius), color)
    else:
        painter.fillRect(rect, color)
    painter.restore()


def _paint_color_mark(painter: QPainter, look: dict, rect: QRect, color: str, corners: frozenset = frozenset()):
    """Couleur ATTRIBUEE au fichier (file_attributes) : calque de cette couleur a la place des marques
    focus / survol (meme rectangle, memes coins), opacite et bordure de Visionneuse > Filtres."""
    mark = look["color_mark"]
    if rect.width() <= 0 or rect.height() <= 0:
        return
    radius = _gallery_mark_radius(look, corners)
    fill = QColor(color)
    fill.setAlphaF(fill.alphaF() * mark["opacity"] / 100.0)
    from settings_widgets import _rounded_rect_path
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if fill.alpha():
        if any(radius.values()):
            painter.fillPath(_rounded_rect_path(rect, radius), fill)
        else:
            painter.fillRect(rect, fill)
    if mark["border"]:
        t = mark["thick"]
        inner = QRectF(rect).adjusted(t / 2, t / 2, -t / 2, -t / 2)
        pen = QPen(QColor(color), t)
        pen.setJoinStyle(Qt.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if any(radius.values()):
            # Chemin sur le rectangle EXACT (demi-pixels compris) : arrondi par toRect(), une epaisseur
            # impaire decalait le cadre d'un demi-pixel — bords gauche / haut plus epais, droite / bas
            # rognes par la case (signale).
            painter.drawPath(_rounded_rect_path(inner, {k: max(0, v - t / 2) for k, v in radius.items()}))
        else:
            painter.drawRect(inner)
    painter.restore()


def _gallery_mark_radius(look: dict, corners: frozenset) -> dict:
    """Coins des marques d'une case (focus, survol, couleur attribuee) : voir _paint_gallery_mark."""
    if _gallery_mark_on_sub_cells(look):
        if not look.get("split"):
            return dict(look["image_cell"]["radius"])        # les 4 coins du fond de la cellule
        top, bottom = look["image_cell"]["radius"], look["text_cell"]["radius"]
        return {"top_left": top["top_left"], "top_right": top["top_right"],
                "bottom_right": bottom["bottom_right"], "bottom_left": bottom["bottom_left"]}
    return {k: (v if k in corners else 0) for k, v in look["table"]["radius"].items()}


# -- Encart « Source du proxy » (Maj + survol d'une diapositive) ------------------------------------

_PROXY_SOURCES: dict[str, str] = {}      # chemin -> source du proxy (lue en fond, voir ProxySourceTip)


class ProxySourceTip(QObject):
    """Encart « Source du proxy » sous le curseur quand on survole une diapositive (planche,
    pellicule) avec Maj enfonce (demande de l'utilisateur). Habillage = l'encart des reglages
    (`settings_widgets._WidthBadge`, role width_badge), jamais un style a part. Source lue EN FOND
    (`lightroom_bridge.request_sources`, catalogue et Previews.lrdata), gardee par fichier ; Maj
    enfoncee / relachee sans bouger la souris : filtre d'application (touches seulement)."""

    def __init__(self, host: QWidget, path_at):
        super().__init__(host)
        self._host, self._path_at = host, path_at
        self._badge = None
        self._path: str | None = None
        self._pos = QPoint()
        QApplication.instance().installEventFilter(self)
        try:
            import lightroom_bridge
            lightroom_bridge._signal_bus().sources_ready.connect(self._on_sources)
        except (ImportError, OSError, ValueError):
            pass

    def update_at(self, global_pos: QPoint | None = None, shift: bool | None = None):
        if shift is None:
            shift = bool(QApplication.queryKeyboardModifiers() & Qt.ShiftModifier)
        host = self._host
        pos = host.mapFromGlobal(global_pos if global_pos is not None else QCursor.pos())
        path = None
        if shift and host.isVisible() and host.rect().contains(pos):
            path = self._path_at(pos)
        if not path:
            self.hide()
            return
        self._path, self._pos = str(path), pos
        text = _PROXY_SOURCES.get(self._path)
        if text is None:
            text = self._ask(Path(path))
        self._show(text)

    def _ask(self, path: Path) -> str:
        try:
            import lightroom_bridge
            if lightroom_bridge.is_managed(path):
                lightroom_bridge.request_sources(path)
                return "lecture…"
        except (ImportError, OSError, ValueError):
            pass
        text = _PROXY_SOURCES[str(path)] = "Application · aperçu créé par l'application"
        return text

    def _on_sources(self, path: str, proxy: str, _full: str):
        _PROXY_SOURCES[path] = proxy
        if path == self._path and self._badge is not None and self._badge.isVisible():
            self._show(proxy)

    def _show(self, text: str):
        from settings_widgets import _WidthBadge
        if self._badge is None:
            self._badge = _WidthBadge(self._host)
        badge = self._badge
        badge.setText(f"Source du proxy : {text}")
        badge.adjustSize()
        gap = scaled(14)
        room = self._host.rect()
        x = min(self._pos.x() + gap, room.right() - badge.width())
        y = self._pos.y() + gap
        if y + badge.height() > room.bottom():
            y = self._pos.y() - gap - badge.height()
        badge.move(max(0, x), max(0, y))
        badge.raise_()
        badge.show()

    def hide(self):
        self._path = None
        if self._badge is not None:
            self._badge.hide()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in (QEvent.KeyPress, QEvent.KeyRelease) and event.key() == Qt.Key_Shift                 and not event.isAutoRepeat():
            self.update_at(shift=kind == QEvent.KeyPress)
        return False


class FocusFilmstrip(QWidget):
    """Pellicule de la visionneuse : vignettes de tous les fichiers du dossier, en bas de la zone.
    Un TABLEAU : une cellule par fichier, divisee en sous-cellule image (la vignette) et sous-cellule
    texte dessous (le nom ; rang « n / N » dans celle en cours) ; Ctrl + tirer la bordure entre les deux
    change leur hauteur (`viewer_film_text_ratio`, rappel `on_split(ratio, fini)`). Habillage :
    Reglages > Visionneuse > Tableau / Sous cellule image / Sous cellule texte (clic droit : `on_menu`).
    Elle suit le ruban en continu (`set_position`, rang fractionnaire), les cellules grossissent
    en approchant du centre (vague) ; celle de l'image en cours est entouree.
    Clic = aller a ce fichier (`chosen(rang)`), molette = suivant / precedent, double-clic hors
    vignette = comme sur l'image. S'efface quand la souris ne bouge plus (`reveal` la rappelle)."""

    chosen = Signal(int)

    GROW = 0.28
    HOLD_MS = 2400
    RATIO_MIN, RATIO_MAX = 0.12, 1.5
    SPLIT_GRAB = 4                         # demi-hauteur de saisie de la bordure image | texte
    # Hauteur des vignettes choisie par Ctrl+molette, retenue pour la session (None = defaut).
    session_thumb_height: int | None = None

    def __init__(self, parent, thumb, on_wheel=None, on_double_click=None, on_resized=None,
                 on_split=None, on_menu=None):
        super().__init__(parent)
        self._thumb = thumb                  # rappel (Path, cote en pixels physiques) -> QPixmap | None
        self._on_wheel = on_wheel
        self._on_double_click = on_double_click
        self._on_resized = on_resized        # la bande a change de hauteur (zoom des vignettes)
        self._on_split = on_split            # (ratio, fini) : bordure image | texte tiree (Ctrl)
        self._on_menu = on_menu              # (position globale) : clic droit
        self._split_drag = None              # (bas des cellules en y global, hauteur de l'image) pendant le geste
        _FILM_SIGNALS.ready.connect(self.update)
        previews.MTIME_SIGNALS.refreshed.connect(self.update)      # date relue en fond (memory_only)
        # Affichage LEGER quand c'est froid (demande de l'utilisateur : anticiper ce qui ferait ramer) :
        # une cellule dont la vignette n'est pas prete montre son type de fichier, et l'image y apparait
        # en fondu quand elle arrive (`_arrived`), au lieu de bloquer l'animation pour la charger.
        self._waiting: set = set()
        self._arrived: dict = {}
        self._ramp = QTimer(self)
        self._ramp.setInterval(15)
        self._ramp.timeout.connect(self.update)
        self._paths: list = []
        self._index = 0
        self._pos = 0.0
        self._hover = -1
        self.source_tip = ProxySourceTip(self, lambda pos: (
            str(self._paths[i]) if (i := self._index_at(QPointF(pos))) >= 0 else None))
        self._alpha = 0.0
        self._alpha_goal = 0.0
        self._th = scaled(60)
        self._tw = scaled(90)
        self._gap = scaled(8)
        self._pad = scaled(12)
        self.setMouseTracking(True)
        self._clock = QElapsedTimer()
        self._clock.start()
        self._last = 0
        self._fade = QTimer(self)
        self._fade.setInterval(15)
        self._fade.timeout.connect(self._fade_tick)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(self.HOLD_MS)
        self._hold.timeout.connect(self.conceal)
        # Defilement propre (glide_to) : quand l'image change sans ruban (effet slide coupe), la
        # pellicule glisse seule, meme courbe et meme duree que le ruban (FocusOverlay.SLIDE_MS).
        self._glide_from = 0.0
        self._glide_t0 = 0
        self._glide = QTimer(self)
        self._glide.setInterval(15)
        self._glide.timeout.connect(self._glide_tick)
        if FocusFilmstrip.session_thumb_height:
            self._set_thumb_height(FocusFilmstrip.session_thumb_height)

    def max_thumb_height(self) -> int:
        """Vignette la plus grande (celle du centre, grossie de GROW) : FILM_THUMB_MAX pixels
        physiques au plus sur son plus grand cote (largeur = 1,5 x hauteur), jamais agrandie."""
        dpr = self.devicePixelRatioF() or 1.0
        return max(scaled(30), int(FILM_THUMB_MAX / dpr / (1 + self.GROW) / 1.5))

    def _set_thumb_height(self, height: int) -> bool:
        height = max(scaled(30), min(self.max_thumb_height(), int(height)))
        if height == self._th:
            return False
        self._th, self._tw = height, round(height * 1.5)
        return True

    def zoom_thumbs(self, notches: float):
        """Ctrl+molette sur la pellicule : vignettes plus grandes / plus petites (x1,15 par cran),
        bornees a max_thumb_height ; la bande reservee sous l'image suit (`on_resized`)."""
        if self._set_thumb_height(round(self._th * 1.15 ** notches)):
            FocusFilmstrip.session_thumb_height = self._th
            self.update()
            if self._on_resized is not None:
                self._on_resized()

    def strip_height(self) -> int:
        """Bande reservee : la plus grande cellule (celle du centre, grossie de GROW), image + texte."""
        return round(self._pad * 2 + self._th * (1 + film_text_ratio()) * (1 + self.GROW))

    def set_paths(self, paths: list, index: int):
        self._paths = list(paths)
        self._index = index
        self._pos = float(index)
        self._hover = -1
        self.update()

    def set_current(self, index: int):
        self._index = index
        self.update()

    def set_position(self, pos: float):
        self._glide.stop()
        if abs(pos - self._pos) > 1e-4:
            self._pos = pos
            self.update()

    def glide_to(self, index: int):
        """Glisse jusqu'au rang `index` (crans rapides : l'ecart se cumule, borne a 3 rangs)."""
        offset = max(-3.0, min(3.0, self._pos - index))
        if abs(offset) < 1e-4:
            self.set_position(float(index))
            return
        self._glide_target = index
        self._glide_from = offset
        self._glide_t0 = self._clock.elapsed()
        self._pos = index + offset
        if not self._glide.isActive():
            self._glide.start()
        self.update()

    def gliding(self) -> bool:
        return self._glide.isActive()

    def _glide_tick(self):
        u = min(1.0, (self._clock.elapsed() - self._glide_t0) / FocusOverlay.SLIDE_MS)
        self._pos = self._glide_target + self._glide_from * (1.0 - u) ** 3   # depart vif, arrivee douce
        if u >= 1.0:
            self._pos = float(self._glide_target)
            self._glide.stop()
        self.update()

    def visible_amount(self) -> float:
        return self._alpha

    def reveal(self):
        self._hold.start()
        self._set_alpha_goal(1.0)

    keep_shown = None                    # rappel -> bool : rester affichee (son style se regle)

    def conceal(self):
        if self._hover >= 0 or (self.keep_shown is not None and self.keep_shown()):   # elle reste
            self._hold.start()
            return
        self._set_alpha_goal(0.0)

    def _set_alpha_goal(self, goal: float):
        self._alpha_goal = goal
        if abs(self._alpha - goal) > 1e-3 and not self._fade.isActive():
            self._last = self._clock.elapsed()
            self._fade.start()

    def _fade_tick(self):
        now = self._clock.elapsed()
        # Une image lente (disque froid...) RALENTIT le fondu au lieu de le faire sauter a sa fin :
        # au plus un pas de 30 images / s par image affichee.
        dt = min(1 / 30, max(0.001, (now - self._last) / 1000.0))
        self._last = now
        tau = 0.07 if self._alpha_goal > self._alpha else 0.18      # apparait vite, part en douceur
        self._alpha = self._alpha_goal + (self._alpha - self._alpha_goal) * math.exp(-dt / tau)
        if abs(self._alpha - self._alpha_goal) < 0.01:
            self._alpha = self._alpha_goal
            self._fade.stop()
        self.update()

    def _cells(self):
        """(rang, rectangle de la cellule) des cellules visibles, de la plus loin a la plus proche
        du centre (ordre de dessin ; l'ordre inverse sert au clic). Cellule = image + texte dessous."""
        if not self._paths:
            return []
        width = self.width()
        step = self._tw + self._gap
        bottom = self.height() - self._pad
        reach = int(width / step / 2) + 2
        first = max(0, math.floor(self._pos) - reach)
        last = min(len(self._paths) - 1, math.ceil(self._pos) + reach)
        tall = 1.0 + film_text_ratio()
        cells = []
        for i in range(first, last + 1):
            d = i - self._pos
            grow = 1.0 + self.GROW * max(0.0, 1.0 - abs(d) / 1.5)
            w, h = self._tw * grow, self._th * grow * tall
            x = width / 2 + d * step
            cells.append((abs(d), i, QRectF(x - w / 2, bottom - h, w, h)))
        cells.sort(key=lambda cell: -cell[0])
        return [(i, rect) for _distance, i, rect in cells]

    @staticmethod
    def _split(rect: QRectF) -> tuple:
        """(sous-cellule image, sous-cellule texte) d'une cellule : le texte dessous, hauteurs dans le
        rapport `viewer_film_text_ratio`."""
        ratio = film_text_ratio()
        image_h = rect.height() / (1.0 + ratio)
        return (QRectF(rect.left(), rect.top(), rect.width(), image_h),
                QRectF(rect.left(), rect.top() + image_h, rect.width(), rect.height() - image_h))

    def _index_at(self, pos: QPointF) -> int:
        for i, rect in reversed(self._cells()):
            if rect.contains(pos):
                return i
        return -1

    def _split_at(self, pos: QPointF):
        """Cellule dont la bordure image | texte est sous `pos` (a SPLIT_GRAB px pres), sinon None."""
        for _i, rect in reversed(self._cells()):
            if rect.left() <= pos.x() <= rect.right():
                line = self._split(rect)[1].top()
                if abs(pos.y() - line) <= self.SPLIT_GRAB:
                    return rect
        return None

    ARRIVE_MS = 180                       # fondu d'une vignette arrivee apres coup
    FILM_REQUEST_BUDGET = 0.004           # s de demandes de decodage par image (le reste : image suivante)

    def paintEvent(self, event):
        if self._alpha <= 0.01 or not self._paths:
            return
        # Jamais de disque pendant l'image (dates en memoire, relues en fond) et reduction des vignettes
        # bornee (FILM_SCALE_BUDGET) : la 1re image apres un long moment ne bloque plus l'animation.
        global _SCALE_DEADLINE
        _SCALE_DEADLINE = time.perf_counter() + FILM_SCALE_BUDGET
        # Pendant l'APPARITION, aucun decodage lance (ils gardent le GIL en fond et hachaient le fondu) :
        # ce qui manque est demande a l'image qui la termine (_fade_tick repeint a l'arret).
        appearing = self._fade.isActive() and self._alpha_goal > self._alpha
        try:
            with previews.memory_only(hold=appearing):
                self._paint(event)
        finally:
            _SCALE_DEADLINE = None

    def _thumb_fade(self, path, pix) -> float:
        """Opacite de l'image d'une cellule : 1, sauf pour une vignette arrivee apres que la cellule a ete
        montree sans elle (affichage leger) — fondu sur ARRIVE_MS."""
        key = str(path)
        if pix is None or pix.isNull():
            self._waiting.add(key)
            return 0.0
        now = self._clock.elapsed()
        if key in self._waiting:
            self._waiting.discard(key)
            self._arrived[key] = now
        start = self._arrived.get(key)
        if start is None:
            return 1.0
        amount = (now - start) / self.ARRIVE_MS
        if amount >= 1.0:
            del self._arrived[key]
            return 1.0
        if not self._ramp.isActive():
            self._ramp.start()
        return max(0.0, amount)

    def _paint(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setOpacity(self._alpha)
        if not self._arrived and self._ramp.isActive():
            self._ramp.stop()
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0.0, QColor(0, 0, 0, 0))
        shade.setColorAt(0.5, QColor(0, 0, 0, 120))
        shade.setColorAt(1.0, QColor(0, 0, 0, 190))
        painter.fillRect(self.rect(), shade)
        look = _film_look()
        from settings_widgets import paint_shadow
        width = self.width()
        dpr = self.devicePixelRatioF() or 1.0
        side = round(self._tw * (1 + self.GROW) * dpr)
        edge = (self._tw + self._gap) * 1.5
        ext_font, ext_color = look["ext_font"]
        name_font, name_color = look["name_font"]
        rank_font, rank_color = look["rank_font"]
        name_metrics, rank_metrics = QFontMetrics(name_font), QFontMetrics(rank_font)
        count = len(self._paths)
        cells = self._cells()
        # Vignettes, du CENTRE vers les bords ; demandes de decodage etalees : au-dela de
        # FILM_REQUEST_BUDGET dans cette image, les suivantes attendent l'image d'apres (sinon ~90 ms
        # d'un coup a la fin de l'apparition, quand toutes les demandes retenues partaient ensemble).
        thumbs, retry = {}, False
        request_deadline = time.perf_counter() + self.FILM_REQUEST_BUDGET
        for i, _rect in reversed(cells):
            over = time.perf_counter() > request_deadline
            with previews.memory_only(hold=over or previews.requests_held()):
                pix = self._thumb(self._paths[i], side)
            if over and (pix is None or pix.isNull()):
                retry = True
            thumbs[i] = pix
        if retry and not previews.requests_held():
            QTimer.singleShot(16, self.update)
        for i, rect in cells:
            centre = rect.center().x()
            near_edge = max(0.0, min(1.0, min(centre, width - centre) / edge))   # s'efface vers les bords
            emphasis = 1.0 if i in (self._index, self._hover) else 0.72
            painter.setOpacity(self._alpha * near_edge * emphasis)
            if look["table_shadow"] is not None:
                paint_shadow(painter, rect, look["table"]["radius"], look["table_shadow"])
            _paint_film_box(painter, rect, look["table"])
            image_cell, text_cell = self._split(_film_inner(rect, look["table"]))
            _paint_film_box(painter, image_cell, look["image_cell"])
            _paint_film_box(painter, text_cell, look["text_cell"])
            path = self._paths[i]
            room = _film_inner(image_cell, look["image_cell"]).adjusted(2, 2, -2, -2)
            pix = thumbs.get(i)
            fade = self._thumb_fade(path, pix)
            cell_opacity = painter.opacity()
            if fade < 1.0:                       # pas encore la (ou en fondu) : son type de fichier dessous
                painter.setOpacity(cell_opacity * (1.0 - fade))
                painter.setFont(ext_font)
                painter.setPen(ext_color)
                painter.drawText(room, Qt.AlignCenter, path.suffix.lstrip(".").upper())
                painter.setOpacity(cell_opacity * fade)
            if fade > 0.0 and room.width() > 0 and room.height() > 0:
                size = _pixmap_size(pix)
                size.scale(room.width(), room.height(), Qt.KeepAspectRatio)
                image_rect = QRectF(room.center().x() - size.width() / 2, room.center().y() - size.height() / 2,
                                    size.width(), size.height())
                image = look["image"]
                if look["image_shadow"] is not None:
                    paint_shadow(painter, image_rect, image["radius"], look["image_shadow"])
                painter.save()
                if any(image["radius"].values()):
                    from settings_widgets import _rounded_rect_path
                    painter.setClipPath(_rounded_rect_path(image_rect.toRect(), image["radius"]))
                painter.drawPixmap(image_rect, pix, QRectF(pix.rect()))
                painter.restore()
                _paint_film_box(painter, image_rect, image)
            painter.setOpacity(cell_opacity)
            # Sous-cellule texte : le nom ; dans la cellule en cours, suivi du rang (police du tableau).
            text_room = _film_inner(text_cell, look["text_cell"]).adjusted(4, 0, -4, 0)
            rank = f"  {i + 1} / {count}" if i == self._index else ""
            rank_w = rank_metrics.horizontalAdvance(rank) if rank else 0
            name = name_metrics.elidedText(display_name(path), Qt.ElideMiddle,
                                           max(0, int(text_room.width() - rank_w)))
            name_w = name_metrics.horizontalAdvance(name)
            x = text_room.center().x() - (name_w + rank_w) / 2
            painter.setFont(name_font)
            painter.setPen(name_color)
            painter.drawText(QRectF(x, text_room.top(), name_w + 1, text_room.height()),
                             Qt.AlignLeft | Qt.AlignVCenter, name)
            if rank:
                painter.setFont(rank_font)
                painter.setPen(rank_color)
                painter.drawText(QRectF(x + name_w, text_room.top(), rank_w + 1, text_room.height()),
                                 Qt.AlignLeft | Qt.AlignVCenter, rank)
            ring = rect.adjusted(-2, -2, 2, 2)
            radius = max(look["table"]["radius"].values()) + 2
            if i == self._index:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(C["accent"]), 2))
                painter.drawRoundedRect(ring, radius, radius)
            elif i == self._hover:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(255, 255, 255, 150), 1))
                painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), radius - 1, radius - 1)

    def mouseMoveEvent(self, event):
        self.reveal()
        if self._split_drag is not None:
            bottom, image_h = self._split_drag
            text_h = bottom - event.globalPosition().y()
            ratio = max(self.RATIO_MIN, min(self.RATIO_MAX, text_h / max(1.0, image_h)))
            if self._on_split is not None:
                self._on_split(ratio, False)
            self.update()
            return
        pos = event.position()
        if event.modifiers() & Qt.ControlModifier and self._split_at(pos) is not None:
            self.setCursor(Qt.SplitVCursor)
            return
        self.source_tip.update_at(event.globalPosition().toPoint(), bool(event.modifiers() & Qt.ShiftModifier))
        hover = self._index_at(pos)
        if hover != self._hover or self.cursor().shape() == Qt.SplitVCursor:
            self._hover = hover
            self.setCursor(Qt.PointingHandCursor if hover >= 0 else Qt.ArrowCursor)
            self.setToolTip(display_name(self._paths[hover]) if hover >= 0 else "")
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.source_tip.hide()
        if self._hover != -1:
            self._hover = -1
            self.update()
        self._hold.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            visible = self._alpha > 0.4
            self.reveal()
            cell = self._split_at(event.position()) if visible and event.modifiers() & Qt.ControlModifier else None
            if cell is not None:
                # Ctrl + bordure image | texte : le bas des cellules reste en place (y global), l'image
                # garde sa hauteur, le texte prend ce que la souris lui donne.
                bottom = self.mapToGlobal(QPointF(0, cell.bottom())).y()
                self._split_drag = (bottom, self._split(cell)[0].height())
                self.setCursor(Qt.SplitVCursor)
                event.accept()
                return
            index = self._index_at(event.position()) if visible else -1
            if index >= 0:
                self.chosen.emit(index)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._split_drag is not None and event.button() == Qt.LeftButton:
            self._split_drag = None
            self.setCursor(Qt.ArrowCursor)
            if self._on_split is not None:
                self._on_split(film_text_ratio(), True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        if self._on_menu is not None:
            self.reveal()
            self._on_menu(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._index_at(event.position()) < 0 and self._on_double_click:
            self._on_double_click()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.reveal()
            self.zoom_thumbs((event.angleDelta().y() or event.angleDelta().x()) / 120)
            event.accept()
            return
        if self._on_wheel is not None:
            self.reveal()
            self._on_wheel(event)
            event.accept()
            return
        super().wheelEvent(event)


def _gallery_look() -> dict:
    """Padding des cellules de la planche = celui des tableaux des reglages (Reglages > Tableaux), lu
    dans les reglages appliques (ui_state.APPLIED_SETTINGS)."""
    import ui_state
    from settings_store import DEFAULT_SETTINGS
    values = dict(DEFAULT_SETTINGS)
    values.update(ui_state.APPLIED_SETTINGS or {})

    def side_dict(key, fallback):
        raw = values.get(key)
        return {side: (raw.get(side, fallback) if isinstance(raw, dict) else raw if raw is not None else fallback)
                for side in ("left", "top", "right", "bottom")}

    # Fond, bordures et border radius du tableau sont ceux de Visionneuse > Tableau, et la planche n'a PLUS de
    # filets interieurs (ceux des tableaux des reglages restaient visibles tableau sans fond ni bordure :
    # demande de l'utilisateur). Elle n'a PLUS non plus le padding des cellules de Reglages > Tableaux (8 / 14 px
    # qui laissaient un espace autour de l'image, signale malgre des paddings a 0) : seuls comptent Visionneuse >
    # Cellules > « Padding de l'image » et « Padding des icônes d'attribut ».
    return {"padding": {side: 0 for side in ("left", "top", "right", "bottom")}}


class _GalleryDelegate(QStyledItemDelegate):
    """Cellule de la planche (un fichier par cellule du tableau) : image ajustee dans sa place,
    nom puis type et poids du fichier dessous ; la cellule de l'image en cours et la cellule survolee
    sont marquees (Couleur focus / survol, _paint_gallery_mark). A l'ouverture, les cellules
    apparaissent en vague depuis l'image en cours (FocusGallery.ripple_state)."""

    def __init__(self, gallery: "FocusGallery"):
        super().__init__(gallery)
        self.gallery = gallery

    def sizeHint(self, option, index) -> QSize:
        return self.gallery.gridSize()

    def paint(self, painter: QPainter, option, index):
        gallery = self.gallery
        key = index.data(Qt.UserRole)
        is_current = key == gallery.current
        opacity, scale = gallery.ripple_state(option.rect)
        if opacity <= 0.0:
            return
        hovered = bool(option.state & QStyle.State_MouseOver) and gallery.attr_editing_allowed()
        mark = "focus" if is_current else "hover" if option.state & QStyle.State_MouseOver else None
        painter.save()
        if opacity < 1.0 or scale != 1.0:
            painter.setOpacity(opacity)
            centre = QRectF(option.rect).center()
            painter.translate(centre)
            painter.scale(scale, scale)
            painter.translate(-centre)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # Toute la case (sous-cellules, image, textes) est une image gardee : une peinture ne fait que
        # la poser (la vague et le vol de l'image repeignent la planche a chaque image).
        painter.drawPixmap(option.rect.topLeft(), gallery.cell_pixmap(index, option.rect.size(), mark, hovered))
        if hovered and opacity >= 1.0:
            # Controles des attributs de la case survolee, directement sur la photo.
            room = gallery.photo_room(key, option.rect)
            hover = gallery._attr_hover[1:] if gallery._attr_hover and gallery._attr_hover[0] == key else None
            painter.translate(option.rect.topLeft())
            _paint_attr_controls(painter, room, gallery.attr_values(key), hover)
        painter.restore()

    @staticmethod
    def paint_content(painter: QPainter, gallery: "FocusGallery", rect: QRect, path: Path, info: str,
                      pix: QPixmap | None, hidden: bool, mark: str | None = None,
                      corners: frozenset = frozenset(), color: str | None = None, insets: tuple | None = None,
                      attrs: dict | None = None, hovered: bool = False):
        """Contenu d'une case dans `rect` : sous-cellule image puis sous-cellule texte dessous
        (Reglages > Visionneuse > Sous cellule image / Sous cellule texte, _film_look). `mark` = "focus" /
        "hover" : case en cours / survolee (_paint_gallery_mark) : sous les fonds des sous-cellules quand
        il couvre la cellule, par-dessus quand il couvre les sous-cellules (jamais sur l'image ni le texte)."""
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        look = gallery.film_look_for(str(path))
        cell_outer, cell, box = gallery.edited_cell_boxes(rect, look)
        cell_style = look.get("cell")
        if cell_style is not None:
            _paint_film_box(painter, QRectF(cell_outer), cell_style)
        text_box = QRect(cell.x(), box.bottom() + 1, cell.width(), max(0, cell.bottom() - box.bottom()))
        # Marques (couleur attribuee au fichier, puis focus / survol par-dessus) : sous les fonds des
        # sous-cellules quand elles couvrent la cellule, par-dessus quand elles couvrent les sous-cellules.
        on_cells = _gallery_mark_on_sub_cells(look)
        if not on_cells:
            if color:
                # Hors de ce que la planche peint par-dessus (filets, bordure du tableau : FocusGallery.mark_insets).
                left, top, right, bottom = insets or (0, 0, 0, 0)
                _paint_color_mark(painter, look, rect.adjusted(left, top, -right, -bottom), color, corners)
            if mark is not None:
                _paint_gallery_mark(painter, look, rect, mark, corners)
        bg_pad = look["bg_padding"]                  # fond de la cellule : retrait dans la case, images et icones suivent
        bg_box = QRect(box).adjusted(bg_pad["left"], bg_pad["top"], -bg_pad["right"], -bg_pad["bottom"])
        _paint_film_box(painter, QRectF(bg_box), look["image_cell"])
        if text_box.height() > 0:
            _paint_film_box(painter, QRectF(text_box), look["text_cell"])
        if on_cells:
            target = cell if look.get("split") else bg_box          # fond de la cellule (padding du fond compris)
            if color:
                _paint_color_mark(painter, look, target, color)
            if mark is not None:
                _paint_gallery_mark(painter, look, target, mark)
        attr_pad = look["attr_padding"]                                    # calque des icones d'attribut
        frame = QRect(bg_box).adjusted(attr_pad["left"], attr_pad["top"], -attr_pad["right"], -attr_pad["bottom"])
        room = _film_inner(QRectF(bg_box), look["image_cell"]).toRect()    # calque de l'image : son propre padding
        image_pad = look["image_padding"]
        room = room.adjusted(image_pad["left"], image_pad["top"], -image_pad["right"], -image_pad["bottom"])
        band = gallery.photo_band(look)
        if room.height() > 2 * band + 20:
            room = room.adjusted(0, band, 0, -band)      # place des attributs, au-dessus et au-dessous
        strip_room = room
        if pix is not None and not pix.isNull():
            target = gallery.fit_in_box(pix, room)
            strip_room = target              # attributs poses SUR la photo
            image = look["image"]
            if look["image_shadow"] is not None:
                from settings_widgets import paint_shadow
                paint_shadow(painter, QRectF(target), image["radius"], look["image_shadow"])
            painter.save()
            if any(image["radius"].values()):
                from settings_widgets import _rounded_rect_path
                painter.setClipPath(_rounded_rect_path(target, image["radius"]))
            painter.drawPixmap(target, pix)
            painter.restore()
            _paint_film_box(painter, QRectF(target), image)
        elif not hidden:
            # Pas (encore) d'apercu, ex. fichier 3D jamais rendu : son type au milieu de la case.
            ext_font, ext_color = look["ext_font"]
            painter.setFont(ext_font)
            painter.setPen(ext_color)
            painter.drawText(room, Qt.AlignCenter, path.suffix.lstrip(".").upper())
        if hasattr(gallery, "_photo_rects"):
            gallery._photo_rects[str(path)] = QRect(frame)           # coins de la diapo (controles du survol)
        if attrs:
            _paint_attrs(painter, frame, attrs, look, hovered, SHOW_KEYWORDS, strip_room)
        if text_box.height() <= 0:
            return                           # case non divisee : pas de sous-cellule texte
        # Nom (police de la sous-cellule texte) puis type et poids (police du tableau), centres ensemble.
        text_room = _film_inner(QRectF(text_box), look["text_cell"]).toRect()
        name_font, name_color = look["name_font"]
        info_font, info_color = look["rank_font"]
        name_m, info_m = QFontMetrics(name_font), QFontMetrics(info_font)
        block = name_m.height() + (info_m.height() if info else 0)
        top = text_room.y() + max(0, (text_room.height() - block) // 2)
        painter.save()
        painter.setClipRect(text_room)
        painter.setFont(name_font)
        painter.setPen(name_color)
        name = name_m.elidedText(display_name(path), Qt.ElideMiddle, text_room.width())
        offsets = getattr(gallery, "_edit_offsets", {}).get(str(path), {})
        name_width = min(text_room.width(), name_m.horizontalAdvance(name))
        name_rect = QRect(text_room.center().x() - name_width // 2, top, name_width, name_m.height())
        name_rect.translate(offsets.get("gallery-name", QPoint()))
        _paint_gallery_text_override(painter, name_rect, look.get("name_style"))
        painter.drawText(name_rect, Qt.AlignCenter, name)
        if info:
            painter.setFont(info_font)
            painter.setPen(info_color)
            shown_info = info_m.elidedText(info, Qt.ElideRight, text_room.width())
            info_width = min(text_room.width(), info_m.horizontalAdvance(shown_info))
            info_rect = QRect(text_room.center().x() - info_width // 2,
                              top + name_m.height(), info_width, info_m.height())
            info_rect.translate(offsets.get("gallery-info", QPoint()))
            _paint_gallery_text_override(painter, info_rect, look.get("info_style"))
            painter.drawText(info_rect, Qt.AlignCenter, shown_info)
        painter.restore()


_FLAG_PIXMAPS: dict = {}       # (statut, cote px) -> icone du drapeau (fichiers PNG lourds : lus une fois)


def _flag_pixmap(status: str, side: int) -> QPixmap | None:
    custom_key = {"keep": previews.UI_ICON_VIEWER_FLAG_KEEP, "delete": previews.UI_ICON_VIEWER_FLAG_DELETE}.get(status)
    if custom_key is not None:
        custom = previews.custom_ui_icon_pixmap(custom_key, side)       # Reglages > Visionneuse > Icones
        if custom is not None:
            return custom
    key = (status, side)
    if key not in _FLAG_PIXMAPS:
        icon_path = _StatusFlags.ICONS.get(status, ("", ""))[0]
        pix = QPixmap(icon_path) if icon_path else QPixmap()
        _FLAG_PIXMAPS[key] = None if pix.isNull() else pix.scaled(side, side, Qt.KeepAspectRatio,
                                                                   Qt.SmoothTransformation)
    return _FLAG_PIXMAPS[key]


def _star_polygon(cx: float, cy: float, radius: float):
    from PySide6.QtGui import QPolygonF
    return QPolygonF([QPointF(cx + (radius if k % 2 == 0 else radius * 0.45) * math.sin(k * math.pi / 5),
                              cy - (radius if k % 2 == 0 else radius * 0.45) * math.cos(k * math.pi / 5))
                      for k in range(10)])


SHOW_KEYWORDS = False          # touche I dans la planche : mots cles ecrits sur les photos (session)


def attr_unit() -> int:
    return scaled(14)


def attr_gap() -> int:
    """Espace entre la photo et ses attributs."""
    return scaled(5)


def attr_band() -> int:
    """Hauteur reservee au-dessus et au-dessous de la photo pour ses attributs."""
    return attr_unit() + attr_gap() + scaled(2)


def attr_inset() -> int:
    """Retrait des attributs par rapport au calque des icones (0 : leur padding, Reglages > Visionneuse >
    Cellules > « Padding des icônes d'attribut », fait le reste)."""
    return 0


def attr_layout(frame: QRect) -> dict:
    """Place des controles d'attributs, dans les COINS de la diapo `frame` (sa zone image, demande de
    l'utilisateur : plus collés à la photo), a `attr_gap` des bords : couleurs en haut a gauche, drapeaux en
    haut a droite, note en bas a gauche, « + » (mots cles) en bas a droite. Memes places pour ce qui est
    dessine (attributs appliques) et pour ce qui se manipule au survol. La bande au-dessus / au-dessous de la
    photo est reservee dans la case (`FocusGallery.photo_band`), la photo ne les recouvre jamais."""
    u = attr_unit()
    gap = scaled(2)
    inset = attr_inset()
    left, right = frame.left() + inset, frame.right() - inset
    above, below = frame.top() + inset, frame.bottom() + 1 - inset - u
    colors = [QRect(left + i * (u + gap), above, u, u) for i in range(COLOR_SLOTS)]
    flags = {"delete": QRect(right - u + 1, above, u, u), "keep": QRect(right - 2 * u - gap + 1, above, u, u)}
    stars = [QRect(left + i * u, below, u, u) for i in range(5)]
    plus = QRect(right - u + 1, below, u, u)
    return {"colors": colors, "flags": flags, "stars": stars, "plus": plus, "unit": u, "pad": scaled(5)}


COLOR_SLOTS = 5


def _backdrop(painter: QPainter, rect: QRectF, strength: int = 185):
    from settings_store import M
    back = QColor(M["panel_bg"])
    back.setAlpha(strength)
    painter.setPen(Qt.NoPen)
    painter.setBrush(back)
    painter.drawRoundedRect(rect, rect.height() / 2 if rect.width() <= rect.height() * 1.2 else scaled(5),
                            rect.height() / 2 if rect.width() <= rect.height() * 1.2 else scaled(5))


def _paint_star(painter: QPainter, rect: QRect, lit: bool, preview: bool = False):
    from settings_store import M
    from settings_widgets import _selection_color
    side = rect.height()
    on = previews.custom_ui_icon_pixmap(previews.UI_ICON_VIEWER_STAR_ON, side)
    off = previews.custom_ui_icon_pixmap(previews.UI_ICON_VIEWER_STAR_OFF, side)
    if on is not None or off is not None:               # icones perso (Reglages > Visionneuse > Icones)
        pix, opacity = (on or off) if lit else (off or on), 1.0
        if not lit and off is None:
            opacity = 0.3                               # pas d'etoile vide choisie : l'allumee, estompee
        if preview:
            opacity *= 0.6
        painter.save()
        painter.setOpacity(painter.opacity() * opacity)
        target = QRect(0, 0, pix.width(), pix.height())
        target.moveCenter(rect.center())
        painter.drawPixmap(target, pix)
        painter.restore()
        return
    color = QColor(_selection_color(255) if lit else M["value_fg"])
    if not lit:
        color.setAlpha(120)                 # etoile vide : contour discret mais visible sur la photo
    if preview:
        color.setAlpha(150)
    painter.setPen(QPen(color, 1.2))
    painter.setBrush(color if lit else Qt.NoBrush)
    painter.drawPolygon(_star_polygon(rect.center().x() + 0.5, rect.center().y() + 0.5, rect.height() * 0.4))


def _paint_flag(painter: QPainter, rect: QRect, status: str, dim: bool = False):
    from settings_store import M
    side = rect.width() - scaled(2)
    pix = _flag_pixmap(status, side)
    painter.save()
    if dim:
        painter.setOpacity(0.45)
    if pix is not None:
        painter.drawPixmap(rect.adjusted(scaled(1), scaled(1), -scaled(1), -scaled(1)), pix)
    else:
        painter.setPen(QColor(M["value_fg"]))
        painter.drawText(rect, Qt.AlignCenter, "✓" if status == "keep" else "✕")
    painter.restore()


def _paint_attrs(painter: QPainter, room: QRect, attrs: dict, look: dict, hovered: bool = False,
                 show_keywords: bool = False, photo: QRect | None = None):
    """Attributs APPLIQUES d'une case de la planche, directement sur la photo (demande de l'utilisateur :
    seulement ceux qui sont appliques ; manipulables au survol, `_paint_attr_controls`). Note en bas a
    gauche, couleur en haut a gauche, drapeau en haut a droite ; mots cles (un par ligne, a partir du haut
    a gauche, sous la rangee des couleurs) seulement quand la touche I les affiche. Au survol, note /
    couleur / drapeau sont repris par les controles (`hovered`) : les mots cles restent dessines ici."""
    layout = attr_layout(room)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if not hovered:
        rating = int(attrs.get("rating") or 0)
        if rating:
            lit = layout["stars"][:rating]
            group = lit[0].united(lit[-1])
            for rect in lit:
                _paint_star(painter, rect, True)
        color = int(attrs.get("color") or 0)
        palette = filter_colors()
        if 1 <= color <= min(len(palette), COLOR_SLOTS):
            slot = layout["colors"][0]          # coin haut gauche (au survol : sa pastille, parmi les 5)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(palette[color - 1][1]))
            painter.drawEllipse(QRectF(slot).adjusted(scaled(2), scaled(2), -scaled(2), -scaled(2)))
        status = attrs.get("status") or ""
        if status in layout["flags"]:
            slot = layout["flags"]["delete"]         # collé au coin de la photo, quel que soit le drapeau
            _paint_flag(painter, slot, status)
    words = attrs.get("keywords") or []
    if show_keywords and words:
        font, text_color = look["rank_font"]
        metrics = QFontMetrics(font)
        line = metrics.height() + scaled(3)
        photo = photo or room                 # mots cles DANS la photo, a partir de son coin haut gauche
        x = photo.left() + layout["pad"]
        y = photo.top() + layout["pad"]
        limit = photo.bottom() - layout["pad"]
        painter.setFont(font)
        for index, word in enumerate(words):
            if y + line > limit:
                more = f"+{len(words) - index}"
                painter.setPen(text_color)
                painter.drawText(QRect(x, y, photo.width(), line), Qt.AlignVCenter | Qt.AlignLeft, more)
                break
            text = metrics.elidedText(word, Qt.ElideRight, max(10, photo.width() - 2 * layout["pad"] - scaled(8)))
            box = QRectF(x, y, metrics.horizontalAdvance(text) + scaled(8), line - scaled(1))
            _backdrop(painter, box, 200)
            painter.setPen(text_color)
            painter.drawText(box, Qt.AlignCenter, text)
            y += line
    painter.restore()


def _paint_attr_controls(painter: QPainter, room: QRect, attrs: dict, hover: tuple | None):
    """Controles d'attributs de la case SURVOLEE, sur la photo : 5 etoiles (la note, apercu de la note
    visee), 5 pastilles de couleur, drapeaux « marquee » / « rejetee », « + » des mots cles. `hover` =
    (genre, valeur) de l'element sous le curseur."""
    from settings_store import M
    layout = attr_layout(room)
    rating = int(attrs.get("rating") or 0)
    color = int(attrs.get("color") or 0)
    status = attrs.get("status") or ""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    # Note
    shown = rating
    if hover and hover[0] == "star":
        shown = hover[1]
    group = layout["stars"][0].united(layout["stars"][-1])
    for i, rect in enumerate(layout["stars"]):
        _paint_star(painter, rect, i < shown, preview=bool(hover and hover[0] == "star" and i >= rating))
    # Couleurs
    palette = filter_colors()
    swatches = layout["colors"][:len(palette)]
    group = swatches[0].united(swatches[-1])
    for i, slot in enumerate(swatches):
        inner = QRectF(slot).adjusted(scaled(2.5), scaled(2.5), -scaled(2.5), -scaled(2.5))
        if hover and hover[0] == "color" and hover[1] == i + 1:
            inner = inner.adjusted(-scaled(1), -scaled(1), scaled(1), scaled(1))
        fill = QColor(palette[i][1])
        if color and color != i + 1:
            fill.setAlphaF(fill.alphaF() * 0.45)
        if color == i + 1:
            painter.setPen(QPen(QColor(M["value_fg"]), 1.6))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(inner.adjusted(-scaled(1.5), -scaled(1.5), scaled(1.5), scaled(1.5)))
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(inner)
    # Drapeaux
    for name, slot in layout["flags"].items():
        active = status == name
        if active or (hover and hover[0] == "flag" and hover[1] == name):
            painter.setPen(QPen(QColor("#55aaff"), 1.4))
            painter.setBrush(QColor(85, 170, 255, 45))
            painter.drawRoundedRect(QRectF(slot).adjusted(0.5, 0.5, -0.5, -0.5), scaled(3), scaled(3))
        _paint_flag(painter, slot, name, dim=bool(status) and not active)
    # « + » : mots cles
    plus = layout["plus"]
    hot = bool(hover and hover[0] == "plus")
    custom_plus = previews.custom_ui_icon_pixmap(previews.UI_ICON_VIEWER_PLUS, plus.height())
    if custom_plus is not None:
        target = QRect(0, 0, custom_plus.width(), custom_plus.height())
        target.moveCenter(plus.center())
        painter.setOpacity(1.0 if hot else 0.75)
        painter.drawPixmap(target, custom_plus)
        painter.restore()
        return
    painter.setPen(QPen(QColor(M["value_fg"] if hot else M["row_label"]), 1.6, Qt.SolidLine, Qt.RoundCap))
    cx, cy, arm = plus.center().x() + 0.5, plus.center().y() + 0.5, plus.width() * 0.3
    painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
    painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))
    painter.restore()


def attr_hit(room: QRect, pos: QPoint) -> tuple | None:
    """Element de `attr_layout` sous `pos` : ("star", n) / ("color", n) / ("flag", nom) / ("plus", 0)."""
    layout = attr_layout(room)
    for i, rect in enumerate(layout["stars"]):
        if rect.contains(pos):
            return ("star", i + 1)
    for i, rect in enumerate(layout["colors"][:len(filter_colors())]):
        if rect.contains(pos):
            return ("color", i + 1)
    for name, rect in layout["flags"].items():
        if rect.contains(pos):
            return ("flag", name)
    if layout["plus"].contains(pos):
        return ("plus", 0)
    return None


def _paint_gallery_text_override(painter, rect: QRect, values: dict | None):
    if not values:
        return
    from app_style import resolve_color_ref
    from settings_store import _coerce_corner_radius
    pad = values.get("text_padding") or {}
    box = rect.adjusted(-max(0, int(pad.get("left", 0))), -max(0, int(pad.get("top", 0))),
                        max(0, int(pad.get("right", 0))), max(0, int(pad.get("bottom", 0))))
    fill = QColor(resolve_color_ref(values.get("text_background_color"), "#00000000")) \
        if values.get("text_background_enabled") else QColor(0, 0, 0, 0)
    enabled = values.get("text_border_enabled") or {}
    if fill.alpha() or any(enabled.values()):
        colors = {side: QColor(resolve_color_ref((values.get("text_border") or {}).get(side), "#00000000"))
                  for side in _FILM_SIDES}
        corners = _coerce_corner_radius(values.get("text_border_radius") or 0)
        from settings_widgets import _paint_bordered_vector
        _paint_bordered_vector(painter, box, corners, enabled,
                               max(0, int(values.get("text_border_thickness", 1) or 0)), colors,
                               fill.name(QColor.NameFormat.HexArgb) if fill.alpha() else None)


class FocusGallery(QListWidget):
    """Planche de TOUS les fichiers a apercu (images, 3D, PSD, plans, videos...) du dossier de l'objet en focus (bouton voisin de « masquer
    les colonnes », voir PreviewColumn.gallery_btn) : grille qui remplit la zone des colonnes,
    image en cours entouree. Clic (ou Entree) sur une vignette : `chosen(Path)` ; Echap ou G :
    `closed`. Vignettes = apercus du pipeline (meme decodage asynchrone que les colonnes) :
    une case vide se remplit des que son apercu est pret (l'inspecteur repeint toutes les vues
    a chaque apercu termine). Chaque vignette est gardee ici a la taille de sa case, pour ne pas
    dependre des caches d'apercus, bornes.

    Ctrl+molette = taille des vignettes (retenue pour la session, `tile_size`) ; en continuant a
    zoomer une fois au maximum, la vignette sous le curseur s'ouvre (`zoomed_into(Path)`) : zoom
    « semantique », pendant de Ctrl+molette arriere sur l'image qui ouvre la planche. Ouverture :
    les cases apparaissent en vague depuis l'image en cours (`start_ripple`).

    TABLEAU : une cellule par fichier (image + nom + type et poids), habille comme les tableaux
    des reglages (`_gallery_look`), CALE SUR LES 4 BORDS de sa zone (`_plan`, `_layout_table`) :
    cellules agrandies pour que les colonnes remplissent la largeur et les lignes visibles la
    hauteur, en restant le plus carrees possible (contrainte n° 1). Les lignes suivantes sont sous
    la zone et defilent ligne par ligne. Trop peu de fichiers : cellules carrees, tableau centre."""

    chosen = Signal(object)
    closed = Signal()
    zoomed_into = Signal(object)
    outside_clicked = Signal()               # clic a cote du tableau (marges de la planche) : retour aux colonnes

    tile_size = 200          # taille des vignettes, gardee d'une ouverture a l'autre
    TILE_MIN = 110
    TILE_MAX = 420
    LABEL_GAP = 6            # px entre l'image et son nom
    RIPPLE_STEP_MS = 34      # retard par case d'eloignement
    RIPPLE_MS = 300          # apparition d'une case

    def __init__(self, parent, paths: list, current: str | None, on_split=None, on_menu=None):
        super().__init__(parent)
        self.current = current
        self._on_split = on_split            # (hauteur du texte en px, fini) : Ctrl + bordure image | texte
        self._on_menu = on_menu              # (position globale) : clic droit
        self._split_drag = None              # bas de la case (y global) pendant le geste
        self.film_look = _film_look()
        self._look_sig = _film_look_signature()
        self._ripple_fade = False            # True : simple fondu des cases (vague coupee dans les reglages)
        self._ripple_items: list = []        # (rect, index, en cours) des cases visibles pendant l'apparition
        self._late_proxies: set = set()      # vignettes arrivees pendant l'apparition : appliquees a sa fin
        # Decodages des vignettes demandes pendant l'ouverture animee (warm_cells -> fin de l'apparition) :
        # lances a la fin (ils prenaient du temps a l'animation). None = lances tout de suite.
        self._held_proxies: list | None = None
        self._ripple_prev: set = set()       # cases encore en mouvement a l'image precedente
        # Glissement de la molette (_scroll_to_row(animate=True)) : ligne visee, depart, horloge, image des
        # lignes qui defilent (_render_band).
        self._scroll_goal: int | None = None
        self._glide_band = None
        self._scroll_from = 0
        self._scroll_clock = QElapsedTimer()
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setTimerType(Qt.PreciseTimer)
        self._scroll_timer.setInterval(8)
        self._scroll_timer.timeout.connect(self._scroll_tick)
        self._warm_timer = QTimer(self)      # cases des lignes voisines, au repos (_warm_around)
        self._warm_timer.setSingleShot(True)
        self._warm_timer.setInterval(30)
        self._warm_timer.timeout.connect(self._warm_around)
        self.TILE = FocusGallery.tile_size
        self._tiles: dict[str, QPixmap] = {}
        self._proxy_pool = QThreadPool(self)
        self._proxy_pool.setMaxThreadCount(2)
        self._proxy_signals = _ProxySignals(self)
        self._proxy_signals.done.connect(self._on_proxy)
        self._proxy_pending: dict[str, int] = {}
        self._proxy_failed: set[str] = set()
        self._zoom_into = 0
        self._ripple_origin: QPointF | None = None
        self._ripple_end = 0.0
        self._ripple_clock = QElapsedTimer()
        self._ripple_timer = QTimer(self)
        self._ripple_timer.setInterval(15)
        self._ripple_timer.timeout.connect(self._ripple_tick)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setWrapping(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)     # molette seulement : largeur stable
        self.setSpacing(0)
        self.setFrameShape(QListWidget.NoFrame)
        self.setMouseTracking(True)
        self.setStyleSheet("QListWidget { background: transparent; border: none; outline: 0; }"
                           "QListWidget::item, QListWidget::item:selected, QListWidget::item:hover"
                           " { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        self._look = _gallery_look()
        self._filled = False                 # Ctrl+molette avant, peu de fichiers : ils remplissent l'ecran (_fit_plan)
        self._table = QSize(0, 0)
        self._cols = self._rows = self._visible_rows = 1
        self._wheel_rest = 0
        self._box_side = self.TILE
        self.setItemDelegate(_GalleryDelegate(self))
        # Visionneuse > Tableau > Ombres : le cadre du tableau = le viewport ; l'ombre deborde dans les marges
        # de la planche (sous-couche voisine, settings_widgets.ShadowUnderlay).
        from settings_widgets import attach_shadow
        self._table_shadow = attach_shadow(self.viewport(), lambda: self.film_look["table_shadow"],
                                           lambda: self.film_look["table"]["radius"])
        current_item = None
        for path in paths:
            try:
                info = os.stat(path)
            except OSError:
                continue
            if _stat.S_ISDIR(info.st_mode):
                continue
            item = QListWidgetItem(display_name(path))
            item.setData(Qt.UserRole, str(path))
            item.setData(Qt.UserRole + 1, info.st_mtime)
            item.setData(Qt.UserRole + 2, f"{Path(path).suffix.lstrip('.').upper()} · {human_size(info.st_size)}")
            item.setToolTip(display_name(path))
            self.addItem(item)
            if str(path) == current:
                current_item = item
        self.itemClicked.connect(lambda item: self.chosen.emit(Path(item.data(Qt.UserRole))))
        # Clic a cote du tableau : sur les marges de la planche (hors viewport) ou dans le viewport hors
        # du tableau (voir eventFilter).
        self._outside_press = None
        self.installEventFilter(self)
        self.viewport().installEventFilter(self)
        self.source_tip = ProxySourceTip(self.viewport(), lambda pos: self.indexAt(pos).data(Qt.UserRole))
        self._photo_rects: dict = {}         # chemin -> place de la photo dans sa case (peinte)
        self._attr_hover = None              # (chemin, genre, valeur) de l'element d'attribut sous le curseur
        self._attr_press = False
        self._keywords_window = None
        self.hidden_path: str | None = None    # image en vol (voir _GalleryDelegate.paint)
        self._fade_anim = None
        if current_item is not None:
            self.setCurrentItem(current_item)
        self._apply_grid()

    def _apply_grid(self):
        self._layout_table()

    def natural_cell(self) -> QSize:
        """Cellule sans aimantation : vignette + nom + padding des cellules des tableaux."""
        pad = self._look["padding"]
        return QSize(self.TILE + pad["left"] + pad["right"],
                     self.TILE + self.label_height() + pad["top"] + pad["bottom"])

    def _plan(self, tile: float) -> tuple:
        """Decoupage retenu. Les cases ont TOUJOURS la taille du decoupage qui remplit l'ecran
        (`_fill_plan` pour un dossier assez grand) : peu de fichiers ne les agrandit pas. Si tous les
        fichiers tiennent a l'ecran, le tableau est CARRE en nombre de cases (4 fichiers = 2 x 2, 5 = 3 x
        2, 9 = 3 x 3 : on ne remplit pas d'abord une ligne ; plus de colonnes que de lignes sur un ecran
        large, l'inverse en portrait) et centre. Sinon : `_fill_plan`, cale sur les bords et defilant."""
        if self._filled:
            return self._fit_plan()
        full = self._fill_plan(tile, crowded=True)
        count = max(1, self.count())
        if count > full[0] * full[1]:
            return self._fill_plan(tile)
        big = math.ceil(math.sqrt(count))
        small = math.ceil(count / big)
        wide = self.width() >= self.height()
        for cols, rows in (((big, small), (small, big)) if wide else ((small, big), (big, small))):
            if cols <= full[0] and rows <= full[1]:
                return cols, rows, full[2], full[3]
        cols = full[0]
        return cols, math.ceil(count / cols), full[2], full[3]

    def _fit_plan(self) -> tuple:
        """Tous les fichiers a l'ecran dans les plus grandes cases carrees possibles : tableau carre en
        nombre de cases (4 = 2 x 2...), oriente comme l'ecran, qui le remplit (Ctrl+molette avant au-dela
        de « tout tient a l'ecran », voir _zoom_fill)."""
        count = max(1, self.count())
        width, height = max(1, self.width() - 1), max(1, self.height())
        big = math.ceil(math.sqrt(count))
        small = math.ceil(count / big)
        cols, rows = max(((big, small), (small, big)), key=lambda cr: min(width // cr[0], height // cr[1]))
        side = max(1, min(width // cols, height // rows))
        return cols, rows, side, side

    def _shows_all(self, plan: tuple) -> bool:
        return math.ceil(max(1, self.count()) / max(1, plan[0])) <= plan[1]

    def _can_fill(self) -> bool:
        """Tous les fichiers sont a l'ecran et pourraient y etre plus grands (le remplir)."""
        if self._filled:
            return False
        current = self._plan(self.TILE)
        fit = self._fit_plan()
        # (au moins 3 % plus grandes : un cran qui ne changerait rien a l'ecran serait un cran perdu)
        return self._shows_all(current) and min(fit[2], fit[3]) > max(current[2], current[3]) * 1.03

    def _set_filled(self, filled: bool, anchor=None):
        """Ecran rempli par tous les fichiers (Ctrl+molette avant, peu de fichiers) ou retour a la taille
        des vignettes (Ctrl+molette arriere)."""
        if filled == self._filled:
            return
        self._filled = filled
        self._tiles.clear()
        self._apply_grid()
        self.doItemsLayout()
        if not filled and self.currentItem() is not None:
            self._scroll_to_row(self._row_of(self.currentItem()) - (self._visible_rows - 1) // 2)
        self.viewport().update()

    def _fill_plan(self, tile: float, crowded: bool = False) -> tuple:
        """(colonnes, lignes visibles, largeur, hauteur de cellule) pour une vignette de `tile` px.

        Le tableau REMPLIT la zone : colonnes = toute la largeur, lignes visibles = toute la
        hauteur (les suivantes sont plus bas, hors de la vue, et defilent ligne par ligne). Les
        cellules visibles sont donc agrandies / reduites pour s'y caler ; CONTRAINTE N° 1 : elles
        restent le plus CARREES possible — parmi les colonnes voisines de celles que demande la
        taille de vignette, on garde le decoupage le plus carre (la taille demandee departage).
        Trop peu de fichiers pour remplir la hauteur (ou la largeur) : les cellules restent
        carrees et le tableau est centre sur cet axe. `crowded` : comme si le dossier remplissait
        l'ecran (taille de reference des cases, voir _plan)."""
        pad = self._look["padding"]
        width = max(1, self.width() - 1)      # Qt passe a la ligne quand une rangee remplit EXACTEMENT le viewport
        height = max(1, self.height())
        count = 1_000_000 if crowded else max(1, self.count())
        ideal = width / max(1.0, tile + pad["left"] + pad["right"])
        best = None
        candidates = {min(count, c) for c in range(max(1, math.floor(ideal) - 2), math.ceil(ideal) + 3)}

        def consider(cols, visible, cell_w, cell_h):
            # Carre d'abord ; puis remplir la zone (part laissee vide) ; puis la taille demandee.
            nonlocal best
            if cell_w < 1 or cell_h < 1:
                return
            empty = (1.0 - cols * cell_w / width) + (1.0 - visible * cell_h / height)
            # (a 3 % pres, une cellule compte pour carree : remplir la zone l'emporte alors)
            score = (10.0 * max(0.0, abs(math.log(cell_w / cell_h)) - 0.03) + 3.0 * empty
                     + abs(math.log(cols / max(0.01, ideal))))
            if best is None or score < best[0]:
                best = (score, cols, visible, cell_w, cell_h)

        for cols in sorted(candidates):
            cell_w = width // cols
            needed = math.ceil(count / cols)
            for visible in {max(1, math.floor(height / cell_w)), max(1, math.ceil(height / cell_w))}:
                # Pas assez de lignes pour remplir : autant de lignes que de fichiers.
                visible = min(visible, needed)
                consider(cols, visible, cell_w, height // visible)            # cale sur les 4 bords
                side = min(cell_w, height // visible)
                consider(cols, visible, side, side)                           # carrees, centrees
        if best is None:
            return 1, 1, width, height
        return best[1:]

    def _layout_table(self):
        """Pose le decoupage de `_plan` : grille, marges du viewport (tableau cale sur les bords,
        ou centre s'il ne les atteint pas), defilement ramene sur une ligne entiere."""
        pad = self._look["padding"]
        cols, visible, cell_w, cell_h = self._plan(self.TILE)
        width, height = max(1, self.width()), max(1, self.height())
        rows = math.ceil(max(1, self.count()) / cols)
        table_w, table_h = cols * cell_w, rows * cell_h
        view_h = visible * cell_h
        left = max(0, (width - 1 - table_w) // 2)
        top = max(0, (height - view_h) // 2)
        self._cols, self._rows, self._visible_rows = cols, rows, visible
        self._table = QSize(table_w, table_h)
        box_side = max(1, max(cell_w - pad["left"] - pad["right"],
                              cell_h - pad["top"] - pad["bottom"] - self.label_height()))
        if box_side != self._box_side:
            self._box_side = box_side
            self._tiles.clear()
        self.setViewportMargins(left, top, max(0, width - 1 - table_w - left), max(0, height - view_h - top))
        if self.gridSize() != QSize(cell_w, cell_h):
            self.setGridSize(QSize(cell_w, cell_h))
            self.doItemsLayout()
        self._scroll_to_row(self.first_visible_row())

    def path_keys(self) -> tuple:
        """Les fichiers de la planche, dans l'ordre (reconnaitre le meme dossier d'une ouverture a l'autre)."""
        return tuple(self.item(row).data(Qt.UserRole) for row in range(self.count()))

    SCROLL_MS = 240          # glissement d'un cran de molette (Visionneuse > Scrolling anime)

    def first_visible_row(self) -> int:
        if self._scroll_goal is not None:
            return self._scroll_goal         # en plein glissement : la ligne ou il s'arretera
        return round(self.verticalScrollBar().value() / max(1, self.gridSize().height()))

    def _scroll_to_row(self, row: int, animate: bool = False):
        """Defilement par LIGNES entieres : les lignes visibles restent calees sur la zone. `animate`
        (molette, reglage « Scrolling anime ») : les lignes GLISSENT jusque-la (depart de la position
        courante : des crans rapides se cumulent sans a-coup) ; sinon saut sec."""
        row = max(0, min(int(row), self._rows - self._visible_rows))
        goal = row * self.gridSize().height()
        bar = self.verticalScrollBar()
        if not animate or bar.value() == goal:
            self._stop_scroll()
            bar.setValue(goal)
            self._schedule_warm()            # au repos : lignes voisines preparees
            return
        if self._held_proxies is None:
            self._held_proxies = []          # decodages de vignettes retenus jusqu'a l'arrivee
        # Toutes les lignes qui vont passer a l'ecran, en UNE image faite avant le depart (`_glide_band`) :
        # chaque image du glissement ne fait que la poser, decalee. Repeindre les cases a chaque pas (la
        # planche est transparente : Qt ne peut pas decaler l'ancien affichage, tout est repeint) et les
        # fabriquer au passage hachait le glissement (mesure a l'ecran : _probe_gallery_scroll.py).
        grid_h = max(1, self.gridSize().height())
        start_row = bar.value() // grid_h
        lo, hi = min(start_row, row), max(start_row, row) + self._visible_rows + 1
        band = self._glide_band
        if band is None or lo < band[0] or hi > band[1] or self._ripple_timer.isActive():
            self._glide_band = None if self._ripple_timer.isActive() else self._render_band(lo, hi)
        self._scroll_goal = row
        self._scroll_from = bar.value()
        self._scroll_clock.restart()
        if not self._scroll_timer.isActive():
            _fine_timer(True)
            _snappy_gil(True)                # chaque image ne fait que poser la bande : GIL rendu vite
            self._scroll_timer.start()

    def _scroll_tick(self):
        t = min(1.0, self._scroll_clock.elapsed() / self.SCROLL_MS)
        eased = 1.0 - (1.0 - t) ** 3 if t < 1.0 else 1.0
        goal = self._scroll_goal * self.gridSize().height()
        self.verticalScrollBar().setValue(round(self._scroll_from + (goal - self._scroll_from) * eased))
        if t >= 1.0:
            self._stop_scroll()

    def _stop_scroll(self):
        if self._glide_band is not None:
            self._glide_band = None
            self.viewport().update()         # retour aux cases vivantes (survol...)
        if self._scroll_timer.isActive():
            self._scroll_timer.stop()
            _fine_timer(False)
            _snappy_gil(False)
            self._scroll_goal = None
            if not self._ripple_timer.isActive():
                self._apply_late_proxies()   # vignettes arrivees pendant le glissement + decodages retenus
                self._schedule_warm()
        self._scroll_goal = None

    def attr_editing_allowed(self) -> bool:
        """Attributs manipulables au survol : pas pendant une animation, ni le vol d'une image."""
        return not self._busy() and self._ripple_origin is None and self._split_drag is None

    def photo_band(self, look: dict | None = None) -> int:
        """Bande reservee a la photo pour les attributs : AUCUNE (demande de l'utilisateur : le calque de l'image
        et celui des icones d'attribut sont PARALLELES, chacun avec son padding, sans influence de l'un sur
        l'autre ; les icones sont peintes par-dessus la photo)."""
        return 0

    def photo_room(self, key: str, cell: QRect) -> QRect:
        """Zone image (coins de la diapo, ou se posent les attributs) de la case `key` (cellule de grille
        `cell`, repere de la case)."""
        rel = self._photo_rects.get(key)
        if rel is None:
            look = self.film_look_for(key)
            _outer, _cell, box = self.edited_cell_boxes(QRect(QPoint(0, 0), cell.size()), look)
            bg, pad = look["bg_padding"], look["attr_padding"]
            rel = box.adjusted(bg["left"] + pad["left"], bg["top"] + pad["top"],
                               -bg["right"] - pad["right"], -bg["bottom"] - pad["bottom"])
        return QRect(rel)

    def _attr_at(self, pos: QPoint):
        """(chemin, genre, valeur, case) de l'element d'attribut sous `pos` (repere du viewport) ; None."""
        if not self.attr_editing_allowed() or not self.viewport().rect().contains(pos):
            return None
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        import file_attributes
        key = index.data(Qt.UserRole)
        if key == self.hidden_path or not file_attributes.eligible(Path(key)):
            return None
        cell = self.visualRect(index)
        hit = attr_hit(self.photo_room(key, cell), pos - cell.topLeft())
        return (key, hit[0], hit[1], cell) if hit else None

    def _set_attr_hover(self, hit, cell_pos: QPoint | None = None):
        new = (hit[0], hit[1], hit[2]) if hit else None
        if new == self._attr_hover:
            return
        old, self._attr_hover = self._attr_hover, new
        for key in {old[0] if old else None, new[0] if new else None} - {None}:
            self.viewport().update()
        self.viewport().setCursor(Qt.PointingHandCursor if new else Qt.ArrowCursor)
        if not new:
            self.viewport().unsetCursor()

    def _apply_attr(self, key: str, kind: str, value):
        """Clic sur un element d'attribut : note, couleur, drapeau (re-clic = aucun) ou fenetre des mots cles."""
        import file_attributes
        path = Path(key)
        current = self.attr_values(key)
        if kind == "star":
            changes = {"rating": 0 if int(current.get("rating") or 0) == value else value}
        elif kind == "color":
            changes = {"color": 0 if int(current.get("color") or 0) == value else value}
        elif kind == "flag":
            changes = {"status": "" if current.get("status") == value else value}
        else:
            self.open_keywords_window(key)
            return
        file_attributes.update(path, **changes)
        merged = dict(current)
        merged.update(changes)
        self.hold_attrs(key, merged)

    def open_keywords_window(self, key: str):
        """Fenetre des mots cles de `key` ; une deja ouverte est fermee (enregistree). La reference est
        lachee a la fermeture (`closed`) : la fenetre se detruit d'elle-meme et une reference restee sur un
        objet detruit faisait echouer toute reouverture (signale : « il ne se passe rien »)."""
        previous, self._keywords_window = self._keywords_window, None
        if previous is not None:
            try:
                previous._accept()
            except RuntimeError:                      # deja detruite
                pass
        window = KeywordsWindow(self, key, self.attr_values(key).get("keywords") or [])
        self._keywords_window = window
        window.saved.connect(lambda words, k=key: self._keywords_saved(k, words))
        window.closed.connect(self._keywords_window_closed)
        window.popup_near(QCursor.pos())

    def _keywords_window_closed(self, window):
        if self._keywords_window is window:
            self._keywords_window = None

    def _keywords_saved(self, key: str, words: list):
        import file_attributes
        file_attributes.update(Path(key), keywords=words)
        merged = dict(self.attr_values(key))
        if words:
            merged["keywords"] = words
        else:
            merged.pop("keywords", None)
        self.hold_attrs(key, merged)

    def _busy(self) -> bool:
        """Une animation de la planche tourne (apparition, glissement de la molette) : rien ne doit lui
        prendre de temps (cases refaites, decodages)."""
        return self._ripple_timer.isActive() or self._scroll_timer.isActive()

    def _cell_ready(self, index, size: QSize) -> bool:
        cached = _CELLS.get(index.data(Qt.UserRole))
        return cached is not None and cached[0] == (size.width(), size.height(),
                                                    index.data(Qt.UserRole) == self.hidden_path, self._look_sig,
                                                    self.devicePixelRatioF() or 1.0)

    def _warm_rows(self, lo: int, hi: int, budget: float | None = None) -> bool:
        """Fabrique les cases des lignes [lo, hi) qui ne sont pas pretes ; `budget` (s) : s'arrete au-dela
        (False = il en reste)."""
        size = self.gridSize()
        cols = max(1, self._cols)
        deadline = time.perf_counter() + budget if budget is not None else None
        for i in range(max(0, lo) * cols, min(self.count(), max(0, hi) * cols)):
            index = self.model().index(i, 0)
            if self._cell_ready(index, size):
                continue
            self.cell_pixmap(index, size)
            if deadline is not None and time.perf_counter() > deadline:
                return False
        return True

    def _render_band(self, lo: int, hi: int):
        """(premiere ligne, derniere + 1, image) : les lignes [lo, hi) du tableau comme a l'ecran (fond et
        cadre de Visionneuse > Tableau, cases gardees, case en cours et survolee marquees, bordures
        interieures), pour le glissement de la molette."""
        lo, hi = max(0, lo), min(self._rows, hi)
        size = self.gridSize()
        gw, gh = size.width(), size.height()
        width = max(1, self.viewport().width())
        dpr = self.devicePixelRatioF() or 1.0
        pix = QPixmap(max(1, round(width * dpr)), max(1, round(max(1, hi - lo) * gh * dpr)))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        table = QRect(0, -lo * gh, self._table.width(), self._table.height())
        self._paint_table_back(painter, table)
        hover = None
        if self.viewport().underMouse():
            hover = self.indexAt(self.viewport().mapFromGlobal(QCursor.pos()))
        cols = max(1, self._cols)
        for i in range(lo * cols, min(self.count(), hi * cols)):
            index = self.model().index(i, 0)
            row, col = divmod(i, cols)
            mark = ("focus" if index.data(Qt.UserRole) == self.current
                    else "hover" if hover is not None and hover.isValid() and hover.row() == i else None)
            painter.drawPixmap(QPoint(col * gw, (row - lo) * gh), self.cell_pixmap(index, size, mark))
        self._paint_table_front(painter, table)
        painter.end()
        return lo, hi, pix

    def _schedule_warm(self):
        timer = getattr(self, "_warm_timer", None)
        if timer is not None:
            timer.start()

    def _warm_around(self):
        """Au repos : les cases des lignes voisines (un ecran au-dessus et au-dessous) sont faites par
        petites tranches, pour que le prochain glissement les trouve pretes."""
        if not self.isVisible():
            return
        if self._busy():
            return                           # relance a la fin de l'animation
        first = self.first_visible_row()
        rows = max(1, self._visible_rows)
        if not self._warm_rows(first - rows, first + 2 * rows + 1, budget=0.004):
            self._warm_timer.start()

    @staticmethod
    def scroll_animated() -> bool:
        import ui_state
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_scroll_animated", True))

    def table_corners(self, i: int) -> frozenset:
        """Coins du TABLEAU que partage la case n° `i` ("top_left"...) : premiere / derniere colonne de la
        premiere / derniere ligne (derniere ligne incomplete : son coin bas droit est une place vide)."""
        cols, rows = max(1, self._cols), max(1, self._rows)
        row, col = divmod(i, cols)
        out = set()
        if row == 0 and col == 0:
            out.add("top_left")
        if row == 0 and col == cols - 1:
            out.add("top_right")
        if row == rows - 1 and col == 0:
            out.add("bottom_left")
        if row == rows - 1 and col == cols - 1:
            out.add("bottom_right")
        return frozenset(out)

    def mark_insets(self, i: int) -> tuple:
        """(gauche, haut, droite, bas) de la case n° `i` couverts par ce que la planche peint PAR-DESSUS les
        cases (_paint_table_front) : filets interieurs (centres sur la limite : `ep - ep // 2` px du cote de la
        case qui suit, `ep // 2` de celle qui precede) et bordure du tableau sur les bords exterieurs. Le cadre
        d'une couleur attribuee s'y loge, sinon ses bords gauche et haut etaient caches (signale)."""
        cols, rows = max(1, self._cols), max(1, self._rows)
        row, col = divmod(i, cols)
        look = self.film_look
        v_on, _c, v_t = look["inner_v"]
        h_on, _c, h_t = look["inner_h"]
        v_t, h_t = (v_t if v_on else 0), (h_t if h_on else 0)
        table = look["table"]
        edge = {side: (table["thick"] if table["on"].get(side) else 0) for side in ("left", "top", "right", "bottom")}
        left = edge["left"] if col == 0 else v_t - v_t // 2
        right = edge["right"] if col == cols - 1 else v_t // 2
        top = edge["top"] if row == 0 else h_t - h_t // 2
        bottom = edge["bottom"] if row == rows - 1 else h_t // 2
        return (left, top, right, bottom)

    def _row_of(self, item) -> int:
        return self.row(item) // max(1, self._cols)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_table()

    def _table_rect(self) -> QRect:
        """Le tableau entier dans le repere du viewport (suit le defilement)."""
        return QRect(0, -self.verticalScrollBar().value(), self._table.width(), self._table.height())

    def paintEvent(self, event):
        band = self._glide_band
        if band is not None:
            # Glissement de la molette : l'image des lignes qui defilent, posee a la position courante.
            painter = QPainter(self.viewport())
            painter.drawPixmap(0, band[0] * self.gridSize().height() - self.verticalScrollBar().value(), band[2])
            painter.end()
            return
        table = self._table_rect()
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._paint_table_back(painter, table)
        if self._ripple_origin is not None and self._ripple_items:
            # Pendant l'apparition (vague ou fondu) : les cases sont posees ici, directement depuis leurs
            # images gardees, sans la mecanique des delegues de la liste (trop lente a chaque image).
            self._paint_ripple(painter, event.rect())
        else:
            painter.end()
            super().paintEvent(event)
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.Antialiasing, True)
        self._paint_table_front(painter, table)
        painter.end()

    def _paint_table_back(self, painter: QPainter, table: QRect):
        """Fond du tableau (Reglages > Visionneuse > Tableau), sous les cases."""
        _paint_film_box(painter, QRectF(table), {**self.film_look["table"], "thick": 0})

    def _paint_table_front(self, painter: QPainter, table: QRect):
        """Par-dessus les cases : bordures interieures (Visionneuse > Tableau > Bordure interieure H / V)
        puis bordures du tableau."""
        grid = self.gridSize()
        on, color, thick = self.film_look["inner_h"]
        if on and thick:
            for row in range(1, self._rows):
                painter.fillRect(QRect(table.x(), table.y() + row * grid.height() - thick // 2, table.width(), thick), color)
        on, color, thick = self.film_look["inner_v"]
        if on and thick:
            for col in range(1, self._cols):
                painter.fillRect(QRect(table.x() + col * grid.width() - thick // 2, table.y(), thick, table.height()), color)
        _paint_film_box(painter, QRectF(table), {**self.film_look["table"], "fill": None})

    # -- Habillage (Reglages > Visionneuse), bordure image | texte, clic droit --

    def restyle(self):
        """Reglages de la visionneuse changes : nouvel habillage, hauteur du texte, mise en page."""
        self.film_look = _film_look()
        self._look = _gallery_look()
        self._table_shadow.sync()
        self._look_sig = _film_look_signature()
        self._filter_palette = None                # couleurs attribuees : reglages relus
        self._attr_colors = {}
        self._layout_table()
        self.viewport().update()

    def film_look_for(self, path: str) -> dict:
        """Habillage general complete par les overrides propres a cette cellule / image / texte."""
        import ui_state
        if not hasattr(ui_state, "GALLERY_STYLE_OVERRIDES"):
            from settings_element_style import ensure_row_text_overrides
            ensure_row_text_overrides()
        from settings_store import _coerce_corner_radius, _coerce_side_enabled
        from settings_element_style import _editable_font_size
        # Ne pas deepcopy les QFont / QColor Qt du look de base : leur copie Python peut
        # invalider des ressources C++ encore utilisees par les peintures de la planche.
        look = dict(self.film_look)
        look["split"] = bool(self.SPLIT_CELLS)       # case divisee (ancien mode) : marques sur les sous-cellules
        for key in ("image_cell", "text_cell", "image"):
            box = dict(self.film_look[key])
            box["on"] = dict(box.get("on") or {})
            box["colors"] = dict(box.get("colors") or {})
            box["radius"] = dict(box.get("radius") or {})
            look[key] = box
        overrides = getattr(ui_state, "GALLERY_STYLE_OVERRIDES", {}) or {}
        cell_values = {}
        for part in ("cell", "name", "info"):
            cell_values.update({key: value for key, value in
                                (overrides.get(f"gallery-{part}:{path}") or {}).items()
                                if key.startswith("gallery_cell_")})
        if cell_values:
            from app_style import resolve_color_ref
            enabled = _coerce_side_enabled(cell_values.get("gallery_cell_border_enabled"), False)
            raw_colors = cell_values.get("gallery_cell_border") or {}
            colors = {side: resolve_color_ref(raw_colors.get(side) if isinstance(raw_colors, dict)
                                               else raw_colors, "#2a2e32") for side in _FILM_SIDES}
            thickness = max(0, int(cell_values.get("gallery_cell_border_thickness", 1) or 0))
            fill = QColor(resolve_color_ref(cell_values.get("gallery_cell_bg"), "#00000000"))
            look["cell"] = {"on": enabled, "colors": colors,
                            "thick": thickness if any(enabled.values()) else 0,
                            "radius": _coerce_corner_radius(cell_values.get("gallery_cell_border_radius", 0)),
                            "fill": fill.name(QColor.NameFormat.HexArgb) if fill.alpha() else None}
            look["cell_padding"] = cell_values.get("gallery_cell_padding") or {}
        for part in ("cell", "image", "name", "info"):
            saved = overrides.get(f"gallery-{part}:{path}") or {}
            if not saved:
                continue
            values = dict(ui_state.APPLIED_SETTINGS or {})
            values.update(saved)
            if part in {"cell", "image"}:
                boxes = (("image", "viewer_film_image"),) if part == "image" else (
                    ("image_cell", "viewer_film_image_cell"),
                    ("text_cell", "viewer_film_text_cell"),
                    ("image", "viewer_film_image"),
                )
                for key, prefix in boxes:
                    box = look[key]
                    enabled = values.get(f"{prefix}_border_enabled")
                    if enabled is not None:
                        box["on"] = _coerce_side_enabled(enabled, False)
                    colors = values.get(f"{prefix}_border")
                    if colors is not None:
                        from app_style import resolve_color_ref
                        box["colors"] = {side: resolve_color_ref(colors.get(side) if isinstance(colors, dict)
                                                                  else colors, "#2a2e32")
                                          for side in _FILM_SIDES}
                    thickness = values.get(f"{prefix}_border_thickness")
                    if thickness is not None:
                        box["thick"] = max(0, int(thickness)) if any(box["on"].values()) else 0
                    radius = values.get(f"{prefix}_border_radius")
                    if radius is not None:
                        box["radius"] = _coerce_corner_radius(radius)
                    bg = values.get(f"{prefix}_bg")
                    if bg is not None and key != "image":
                        from app_style import resolve_color_ref
                        color = QColor(resolve_color_ref(bg, "#00000000"))
                        box["fill"] = color.name(QColor.NameFormat.HexArgb) if color.alpha() else None
                    if part == "cell" and key in {"image_cell", "text_cell"}:
                        from app_style import font as app_font, resolve_color_ref
                        family_key = f"{prefix}_font_family"
                        if family_key in values:
                            size = max(4, int(values.get(f"{prefix}_font_size", 11) or 11))
                            weight = 700 if values.get(f"{prefix}_font_bold") else 400
                            label = (values.get(family_key) or "").strip()
                            family = None
                            if label and label != "Systeme":
                                from browser_core import _resolve_font_family
                                family = _resolve_font_family(label, size, weight)
                            qfont = app_font(size, weight, family=family,
                                             italic=bool(values.get(f"{prefix}_font_italic")),
                                             smoothing=values.get(f"{prefix}_font_smoothing", "current")
                                             if values.get(f"{prefix}_font_smoothing_enabled") else "current")
                            color = QColor(resolve_color_ref(values.get(f"{prefix}_font_color"), "#d6d9dc"))
                            look["ext_font" if key == "image_cell" else "name_font"] = (qfont, color)
                if part in {"cell", "image"} and any(k.startswith("viewer_film_image_shadow") for k in values):
                    from app_style import resolve_color_ref
                    from settings_widgets import shadow_look
                    look["image_shadow"] = shadow_look(values, "viewer_film_image_shadow", resolve_color_ref)
            else:
                from app_style import font as app_font, resolve_color_ref
                qfont, qcolor = look["name_font" if part == "name" else "rank_font"]
                defaults = {"text_font_family": qfont.family(),
                            "text_font_bold": qfont.weight() >= QFont.DemiBold,
                            "text_font_italic": qfont.italic(),
                            "text_font_size": _editable_font_size(qfont),
                            "text_font_color": qcolor.name(QColor.NameFormat.HexArgb),
                            "text_font_smoothing_enabled": False, "text_font_smoothing": "current",
                            "text_padding": {s: 0 for s in ("left", "top", "right", "bottom")},
                            "text_border_enabled": {s: False for s in _FILM_SIDES},
                            "text_border": {s: "#00000000" for s in _FILM_SIDES},
                            "text_border_thickness": 1, "text_border_radius": 0,
                            "text_background_enabled": False, "text_background_color": "#00000000"}
                defaults.update(saved)
                values = defaults
                size = max(1, int(values.get("text_font_size", qfont.pointSize() or 11) or 11))
                weight = 600 if values.get("text_font_bold", qfont.weight() >= QFont.DemiBold) else 400
                family = (values.get("text_font_family") or "").strip() or qfont.family()
                smoothing = values.get("text_font_smoothing", "current") if values.get("text_font_smoothing_enabled") else "current"
                look["name_font" if part == "name" else "rank_font"] = (app_font(size, weight, family=family,
                                                   italic=bool(values.get("text_font_italic")), smoothing=smoothing),
                                         QColor(resolve_color_ref(values.get("text_font_color"), qcolor.name())))
                look[f"{part}_style"] = values
        return look

    def edit_target_at(self, point: QPoint):
        """Retourne la partie peinte cliquée et les rectangles de sa cellule (repère viewport)."""
        index = self.indexAt(point)
        if not index.isValid():
            return None
        path = str(index.data(Qt.UserRole) or "")
        rect = self.visualRect(index)
        look = self.film_look_for(path)
        cell_outer, cell, box = self.edited_cell_boxes(rect, look)
        text_box = QRect(cell.x(), box.bottom() + 1, cell.width(), max(0, cell.bottom() - box.bottom()))
        text_room = _film_inner(QRectF(text_box), look["text_cell"]).toRect()
        info = str(index.data(Qt.UserRole + 2) or "")
        name_font, info_font = look["name_font"][0], look["rank_font"][0]
        name_metrics, info_metrics = QFontMetrics(name_font), QFontMetrics(info_font)
        total = name_metrics.height() + (info_metrics.height() if info else 0)
        top = text_room.y() + max(0, (text_room.height() - total) // 2)
        name = name_metrics.elidedText(display_name(Path(path)), Qt.ElideMiddle, text_room.width())
        name_width = min(text_room.width(), name_metrics.horizontalAdvance(name))
        info_width = min(text_room.width(), info_metrics.horizontalAdvance(
            info_metrics.elidedText(info, Qt.ElideRight, text_room.width())))
        name_rect = QRect(text_room.center().x() - name_width // 2, top, name_width, name_metrics.height())
        info_rect = QRect(text_room.center().x() - info_width // 2, top + name_metrics.height(),
                          info_width, info_metrics.height())
        offsets = getattr(self, "_edit_offsets", {}).get(path, {})
        if name_rect.translated(offsets.get("gallery-name", QPoint())).contains(point):
            part, leaf_rect = "gallery-name", name_rect
        elif info and info_rect.translated(offsets.get("gallery-info", QPoint())).contains(point):
            part, leaf_rect = "gallery-info", info_rect
        elif box.contains(point):
            part, leaf_rect = "gallery-image", box
        else:
            part, leaf_rect = "gallery-cell", cell
        geometry = self.__dict__.setdefault("_edit_geometry", {}).setdefault(path, {})
        geometry.update({part: QRect(leaf_rect), "gallery-cell": QRect(cell_outer),
                         "gallery-text-bounds": QRect(text_room)})
        return path, part, leaf_rect, cell_outer

    def edited_cell_boxes(self, rect: QRect, look: dict):
        """Geometrie commune a la peinture et a la selection du mode edition."""
        outer, base_box = self.tile_boxes(rect)
        cell = QRect(outer)
        style = look.get("cell")
        if style is not None:
            pad = look.get("cell_padding") or {}
            thick = style["thick"]
            sides = style["on"]
            inset = {side: max(0, int(pad.get(side, 0))) + (thick if sides.get(side) else 0)
                     for side in _FILM_SIDES}
            inner = outer.adjusted(inset["left"], inset["top"], -inset["right"], -inset["bottom"])
            if inner.width() > 0 and inner.height() > 0:
                cell = inner
        box_height = max(1, min(cell.height(), base_box.height() - (cell.top() - outer.top())))
        return outer, cell, QRect(cell.x(), cell.y(), cell.width(), box_height)

    def invalidate_edited_cell(self, path: str, repaint: bool = True):
        _CELLS.pop(str(path), None)
        for key in [key for key in _MARKED if key[0] == str(path)]:
            _MARKED.pop(key, None)
        if repaint:
            self.viewport().update()

    def _paint_ripple(self, painter: QPainter, clip: QRect):
        size = self.gridSize()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for rect, index, is_current in self._ripple_items:
            if not rect.intersects(clip):
                continue
            opacity, scale = self.ripple_state(rect)
            if opacity <= 0.0:
                continue
            pixmap = self.cell_pixmap(index, size, "focus" if is_current else None)
            painter.setOpacity(opacity)
            if scale != 1.0:
                centre = QRectF(rect).center()
                painter.save()
                painter.translate(centre)
                painter.scale(scale, scale)
                painter.translate(-centre)
                painter.drawPixmap(rect.topLeft(), pixmap)
                painter.restore()
            else:
                painter.drawPixmap(rect.topLeft(), pixmap)
        painter.setOpacity(1.0)

    def warm_cells(self, wave: bool = True):
        """Images des cases visibles faites AVANT l'animation d'ouverture (vague ou fondu) : fabriquees
        au vol, plusieurs a la fois quand la vague les atteint, elles faisaient sauter des images (et
        fabriquees par tranches pendant l'animation, elles lui volaient du temps). Gardees d'une ouverture
        a l'autre (_CELLS) : seule la premiere ouverture d'un dossier les fabrique."""
        self._held_proxies = []              # relaches a la fin de l'apparition (release_proxies)
        view = self.viewport().rect()
        size = self.gridSize()
        for row in range(self.count()):
            index = self.model().index(row, 0)
            if self.visualRect(index).intersects(view):
                self.cell_pixmap(index, size, "focus" if index.data(Qt.UserRole) == self.current else None)

    def cell_pixmap(self, index, size: QSize, mark: str | None = None, hovered: bool = False) -> QPixmap:
        """Image de toute la case, refaite seulement si sa taille, sa vignette, l'habillage ou l'etat
        « en vol » changent : la peinture de la planche ne fait que poser ces images. Chemin rapide (une
        image par case et par peinture) : une case dont la vignette est definitive n'interroge plus rien.
        `mark` ("focus" / "hover") : variante marquee de la case, gardee a part (`_MARKED`)."""
        if mark is not None or hovered:
            return self._marked_pixmap(index, size, mark, hovered)
        key = index.data(Qt.UserRole)
        hidden = key == self.hidden_path
        color = self.attr_color(key)
        attrs = self.attr_values(key)
        import ui_state
        if not hasattr(ui_state, "GALLERY_STYLE_OVERRIDES"):
            from settings_element_style import ensure_row_text_overrides
            ensure_row_text_overrides()
        styles = getattr(ui_state, "GALLERY_STYLE_OVERRIDES", {}) or {}
        local_style = tuple(repr(styles.get(f"gallery-{part}:{key}")) for part in ("cell", "image", "name", "info"))
        base = (size.width(), size.height(), hidden, self._look_sig, self.devicePixelRatioF() or 1.0, color,
                (self.table_corners(index.row()), self.mark_insets(index.row())) if color else None, local_style,
                repr(sorted(attrs.items())) + str(SHOW_KEYWORDS))
        cached = _CELLS.get(key)
        if cached is not None and cached[0] == base and (cached[2] or self._ripple_origin is not None):
            return cached[1]                 # (pendant l'apparition, meme une vignette provisoire reste)
        pix = None if hidden else self.tile_pixmap(Path(key), index.data(Qt.UserRole + 1))
        tile_key = pix.cacheKey() if pix is not None else 0
        final = hidden or key in self._tiles
        if cached is not None and cached[0] == base and cached[3] == tile_key:
            if final:
                _CELLS[key] = (base, cached[1], True, tile_key)
            return cached[1]
        dpr = base[4]
        out = QPixmap(max(1, round(size.width() * dpr)), max(1, round(size.height() * dpr)))
        out.setDevicePixelRatio(dpr)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        _GalleryDelegate.paint_content(painter, self, QRect(QPoint(0, 0), size), Path(key),
                                       index.data(Qt.UserRole + 2) or "", pix, hidden,
                                       corners=base[6][0] if color else frozenset(), color=color,
                                       insets=base[6][1] if color else None, attrs=attrs)
        painter.end()
        _CELLS[key] = (base, out, final, tile_key)
        _CELLS.move_to_end(key)
        while len(_CELLS) > _CELLS_MAX:
            _CELLS.popitem(last=False)
        return out

    def attr_values(self, key: str) -> dict:
        """Attributs APPLIQUES au fichier (note, couleur, mots cles, statut ; valeurs par defaut omises),
        lus une fois par dossier, relus au plus toutes les 2 s, jamais pendant une animation. Juste apres
        un changement fait ici, la valeur choisie est gardee (`hold_attrs`) : Lightroom ecrit en differe."""
        now = time.monotonic()
        held = self.__dict__.setdefault("_attr_hold", {}).get(key)
        if held is not None and now < held[0]:
            return held[1]
        memo = self.__dict__.setdefault("_attr_values", {})
        hit = memo.get(key)
        if hit is not None and (now - hit[0] < 2.0 or self._busy()):
            return hit[1]
        import file_attributes
        path = Path(key)
        try:
            from lightroom_bridge import is_managed, attributes
            managed = is_managed(path)
            values = attributes(path) if managed else None
        except (ImportError, OSError, ValueError):
            managed, values = False, None
        if not managed:
            folder, name = file_attributes.location(path)
            values = file_attributes._load_dir(folder, max_age=2.0).get(name)
        applied = file_attributes._clean(values if isinstance(values, dict) else {})
        memo[key] = (now, applied)
        return applied

    def hold_attrs(self, key: str, values: dict, seconds: float = 30.0):
        """Valeurs que l'on vient de choisir (barre de survol) : montrees aussitot, case refaite."""
        import file_attributes
        self.__dict__.setdefault("_attr_hold", {})[key] = (time.monotonic() + seconds,
                                                           file_attributes._clean(values))
        self.__dict__.setdefault("_attr_values", {}).pop(key, None)
        self.invalidate_edited_cell(key)

    def attr_color(self, key: str) -> str | None:
        """Couleur attribuee au fichier (une des 5 de Visionneuse > Filtres) ou None (voir attr_values)."""
        index = int(self.attr_values(key).get("color") or 0)
        palette = self.__dict__.get("_filter_palette")
        if palette is None:
            palette = self._filter_palette = [c for _n, c in filter_colors()]
        return palette[index - 1] if 1 <= index <= len(palette) else None

    def _marked_pixmap(self, index, size: QSize, mark: str | None, hovered: bool = False) -> QPixmap:
        """Case en cours / survolee : meme image que `cell_pixmap`, marquage compris, refaite seulement
        quand la case simple l'est (meme signature, meme vignette)."""
        plain = self.cell_pixmap(index, size)
        key = index.data(Qt.UserRole)
        base, _out, _final, tile_key = _CELLS[key]
        corners = self.table_corners(index.row())
        cached = _MARKED.get((key, mark, hovered))
        if cached is not None and cached[0] == base and cached[1] == tile_key and cached[3] == corners:
            return cached[2]
        hidden = base[2]
        pix = None if hidden else self.tile_pixmap(Path(key), index.data(Qt.UserRole + 1))
        out = QPixmap(plain.size())
        out.setDevicePixelRatio(plain.devicePixelRatio())
        out.fill(Qt.transparent)
        painter = QPainter(out)
        _GalleryDelegate.paint_content(painter, self, QRect(QPoint(0, 0), size), Path(key),
                                       index.data(Qt.UserRole + 2) or "", pix, hidden, mark, corners,
                                       color=base[5], insets=base[6][1] if base[5] else None,
                                       attrs=self.attr_values(key), hovered=hovered)
        painter.end()
        _MARKED[(key, mark, hovered)] = (base, tile_key, out, corners)
        _MARKED.move_to_end((key, mark, hovered))
        while len(_MARKED) > 8:
            _MARKED.popitem(last=False)
        return out

    def _outside_table(self, obj, pos) -> bool:
        if obj is self:
            return not self.viewport().geometry().contains(pos)      # marges autour du viewport
        return not self._table_rect().contains(pos)

    def eventFilter(self, obj, event):
        if obj in (self, self.viewport()):
            kind = event.type()
            if kind == QEvent.Leave and obj is self.viewport():
                self.source_tip.hide()
                self._set_attr_hover(None)
            if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                pos = event.position().toPoint()
                self._outside_press = event.globalPosition() if self._outside_table(obj, pos) else None
                if self._outside_press is not None:
                    return True
            elif kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self._outside_press is not None:
                press, self._outside_press = self._outside_press, None
                pos = event.position().toPoint()
                if ((event.globalPosition() - press).manhattanLength() < QApplication.startDragDistance()
                        and self._outside_table(obj, pos)):
                    self.outside_clicked.emit()
                return True
        return super().eventFilter(obj, event)

    def _split_cell_at(self, pos: QPoint):
        """Case dont la bordure image | texte est sous `pos` (repere du viewport, a 4 px pres)."""
        if not self.SPLIT_CELLS:
            return None
        for probe in (pos, pos - QPoint(0, 5), pos + QPoint(0, 5)):
            index = self.indexAt(probe)
            if not index.isValid():
                continue
            cell, box = self.tile_boxes(self.visualRect(index))
            if cell.left() <= pos.x() <= cell.right() and abs(pos.y() - (box.bottom() + 1)) <= 4:
                return cell
        return None

    def mousePressEvent(self, event):
        # Clic pendant un glissement de la molette : les lignes s'arretent la ou elles sont (on choisit
        # la case qu'on voit sous le curseur).
        self._stop_scroll()
        hit = self._attr_at(event.position().toPoint()) if event.button() == Qt.LeftButton else None
        if hit is not None:
            # Element d'attribut (note, couleur, drapeau, « + ») : agit, ne choisit pas l'image.
            self._attr_press = True
            self._apply_attr(hit[0], hit[1], hit[2])
            event.accept()
            return
        if event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier:
            cell = self._split_cell_at(event.position().toPoint())
            if cell is not None:
                # Le bas de la case reste en place : le texte prend ce que la souris lui laisse.
                self._split_drag = self.viewport().mapToGlobal(QPoint(0, cell.bottom() + 1)).y()
                self.viewport().setCursor(Qt.SplitVCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._split_drag is not None:
            height = self._split_drag - event.globalPosition().y()
            limit = max(self.TEXT_MIN, self.gridSize().height() - 24)
            height = int(round(max(self.TEXT_MIN, min(limit, height))))
            if self._on_split is not None:
                self._on_split(height, False)
            event.accept()
            return
        self.source_tip.update_at(event.globalPosition().toPoint(), bool(event.modifiers() & Qt.ShiftModifier))
        self._set_attr_hover(self._attr_at(event.position().toPoint()))
        if event.modifiers() & Qt.ControlModifier and self._split_cell_at(event.position().toPoint()) is not None:
            self.viewport().setCursor(Qt.SplitVCursor)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._attr_press and event.button() == Qt.LeftButton:
            self._attr_press = False
            event.accept()
            return
        if self._split_drag is not None and event.button() == Qt.LeftButton:
            self._split_drag = None
            self.viewport().unsetCursor()
            if self._on_split is not None:
                self._on_split(self.label_height(), True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        if self._on_menu is not None:
            self._on_menu(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def reveal_current(self, first_row: int | None = None):
        """Met en page puis fait defiler jusqu'a l'image en cours : sa case doit etre a sa place
        AVANT que l'image ne s'y pose (voir image_rect_in). `first_row` : premiere ligne visible a la
        derniere fermeture de la planche sur ce dossier — elle revient A LA MEME POSITION (demande de
        l'utilisateur : jamais recentree) ; l'image en cours hors de cette vue : defilement minimal
        (sa ligne en haut ou en bas). Sans memoire : sa ligne au milieu."""
        self._layout_table()
        self.doItemsLayout()
        item = self.currentItem()
        if first_row is None:
            if item is not None:
                self._scroll_to_row(self._row_of(item) - (self._visible_rows - 1) // 2)
            return
        row = first_row
        if item is not None:
            current = self._row_of(item)
            if current < row:
                row = current
            elif current > row + self._visible_rows - 1:
                row = current - self._visible_rows + 1
        self._scroll_to_row(row)

    def tile_boxes(self, rect: QRect) -> tuple:
        """(case, cadre de l'image) d'une vignette dont la cellule de grille est `rect`."""
        pad = self._look["padding"]
        cell = rect.adjusted(pad["left"], pad["top"], -pad["right"], -pad["bottom"])
        return cell, QRect(cell.x(), cell.y(), cell.width(), max(1, cell.height() - self.label_height()))

    @staticmethod
    def fit_in_box(pix: QPixmap, box: QRect) -> QRect:
        dpr = pix.devicePixelRatio() or 1.0
        size = QSize(round(pix.width() / dpr), round(pix.height() / dpr))
        size.scale(box.size(), Qt.KeepAspectRatio)
        target = QRect(0, 0, size.width(), size.height())
        target.moveCenter(box.center())
        return target

    def image_rect_in(self, widget: QWidget, path: str | None, pix: QPixmap) -> QRect | None:
        """Ou `pix` (l'image de `path`) se pose dans sa vignette, dans le repere de `widget` ;
        None si elle n'est pas dans la planche ou hors de la partie visible."""
        if not path or pix is None or pix.isNull():
            return None
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.UserRole) == path:
                rect = self.visualItemRect(item)
                if not rect.intersects(self.viewport().rect()):
                    return None
                box = self.tile_boxes(rect)[1]
                look = self.film_look_for(path)
                bg, pad = look["bg_padding"], look["image_padding"]
                box = box.adjusted(bg["left"] + pad["left"], bg["top"] + pad["top"],
                                   -bg["right"] - pad["right"], -bg["bottom"] - pad["bottom"])
                band = self.photo_band(look)
                if box.height() > 2 * band + 20:
                    box = box.adjusted(0, band, 0, -band)       # meme place que la case peinte
                target = self.fit_in_box(pix, box)
                return QRect(self.viewport().mapTo(widget, target.topLeft()), target.size())
        return None

    def set_hidden_path(self, path: str | None):
        self.hidden_path = path
        self.viewport().update()

    def fade(self, end: float, duration_ms: int, on_done=None):
        """Fondu de toute la planche vers l'opacite `end` (depuis l'opacite courante). A 1 :
        l'effet est retire (rendu direct, net et rapide)."""
        effect = self.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(1.0 if end <= 0.0 else 0.0)
            self.setGraphicsEffect(effect)
        if self._fade_anim is not None:
            self._fade_anim.stop()
        anim = self._fade_anim = QVariantAnimation(self)
        anim.setStartValue(float(effect.opacity()))
        anim.setEndValue(float(end))
        anim.setDuration(max(1, duration_ms))
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.valueChanged.connect(lambda value: effect.setOpacity(float(value)))

        def finished():
            if end >= 1.0:
                self.setGraphicsEffect(None)
            if on_done is not None:
                on_done()
        anim.finished.connect(finished)
        anim.start()

    # -- Apparition en vague ------------------------------------------------------------------

    FADE_MS = 260            # apparition en simple fondu (vague coupee)

    def start_ripple(self, wave: bool = True):
        """Les cases apparaissent (fondu + leger grossissement) en vague qui part de l'image en
        cours : plus une case en est loin, plus elle arrive tard. `wave` False (Reglages >
        Visionneuse, animation des diapositives coupee) : toutes ensemble, en simple fondu.
        Seules les cases encore en mouvement sont repeintes a chaque image (voir _ripple_tick)."""
        self._ripple_fade = not wave
        self._ripple_prev = set()
        # Cases visibles, figees pour toute l'apparition (posees par _paint_ripple).
        view = self.viewport().rect()
        self._ripple_items = []
        for row in range(self.count()):
            index = self.model().index(row, 0)
            rect = self.visualRect(index)
            if rect.intersects(view):
                self._ripple_items.append((rect, index, index.data(Qt.UserRole) == self.current))
        if not wave:
            self._ripple_origin = QPointF(0, 0)
            self._ripple_end = float(self.FADE_MS)
            self._ripple_clock.start()
            if not self._ripple_timer.isActive():
                _fine_timer(True)
            self._ripple_timer.start()
            self.viewport().update()
            return
        item = self.currentItem()
        origin = self.visualItemRect(item).center() if item is not None else self.viewport().rect().center()
        self._ripple_origin = QPointF(origin)
        grid = self.gridSize()
        view = self.viewport().rect()
        far = max(math.hypot((corner.x() - origin.x()) / max(1, grid.width()),
                             (corner.y() - origin.y()) / max(1, grid.height()))
                  for corner in (view.topLeft(), view.topRight(), view.bottomLeft(), view.bottomRight()))
        self._ripple_end = (far + 1) * self.RIPPLE_STEP_MS + self.RIPPLE_MS
        self._ripple_clock.start()
        if not self._ripple_timer.isActive():
            _fine_timer(True)                # une image toutes les ~16 ms, pas tous les 15,6 / 31 ms
        self._ripple_timer.start()
        self.viewport().update()

    def ripple_state(self, rect: QRect) -> tuple:
        """(opacite, echelle) d'une case pendant la vague ; (1, 1) en dehors."""
        if self._ripple_origin is None:
            return 1.0, 1.0
        if self._ripple_fade:
            t = max(0.0, min(1.0, self._ripple_clock.elapsed() / self.FADE_MS))
            return t * t * (3.0 - 2.0 * t), 1.0
        grid = self.gridSize()
        centre = rect.center()
        distance = math.hypot((centre.x() - self._ripple_origin.x()) / max(1, grid.width()),
                              (centre.y() - self._ripple_origin.y()) / max(1, grid.height()))
        t = (self._ripple_clock.elapsed() - distance * self.RIPPLE_STEP_MS) / self.RIPPLE_MS
        t = max(0.0, min(1.0, t))
        eased = 1.0 - (1.0 - t) ** 3
        return eased, 0.84 + 0.16 * eased

    def preview_ready(self, key: str):
        """Un apercu du pipeline vient d'etre decode (detail_panel) : seule sa case est repeinte, et pas
        pendant l'apparition (elle le sera a la fin)."""
        if self._busy():
            self._proxy_failed.discard(key)
            _drop_proxy(key)
            self._late_proxies.add(key)
            return
        self._tiles.pop(key, None)
        self._proxy_failed.discard(key)
        _drop_proxy(key)
        _CELLS.pop(key, None)
        for mark in ("focus", "hover"):
            _MARKED.pop((key, mark), None)
        for row in range(self.count()):
            item = self.item(row)
            if item.data(Qt.UserRole) == key:
                self.viewport().update(self.visualItemRect(item))
                break

    def _apply_late_proxies(self):
        for key in self._late_proxies:
            self._tiles.pop(key, None)
            _CELLS.pop(key, None)
        self._late_proxies = set()
        self.release_proxies()

    def release_proxies(self):
        """Fin de l'apparition : les decodages de vignettes retenus partent (les plus recents d'abord)."""
        held, self._held_proxies = self._held_proxies, None
        for key, need in held or ():
            self._request_proxy(key, need)

    def _ripple_tick(self):
        if self._ripple_clock.elapsed() >= self._ripple_end:
            self._ripple_timer.stop()
            _fine_timer(False)
            self._ripple_origin = None
            self._ripple_prev = set()
            self._apply_late_proxies()
            self.viewport().update()
            self._schedule_warm()
            return
        if self._ripple_fade:
            self.viewport().update()         # toutes les cases changent ensemble
            return
        # Vague : seules les cases en mouvement (et celles qui viennent de finir) sont repeintes.
        moving, region = set(), QRegion()
        for row, (rect, _index, _current) in enumerate(self._ripple_items):
            opacity, _scale = self.ripple_state(rect)
            if 0.0 < opacity < 1.0:
                moving.add(row)
            if row in moving or row in self._ripple_prev:
                region += QRegion(rect)
        self._ripple_prev = moving
        if not region.isEmpty():
            self.viewport().update(region)

    # -- Taille des vignettes -----------------------------------------------------------------

    def set_tile_size(self, size: float, anchor=None) -> bool:
        """Change la taille des vignettes en gardant sous `anchor` (repere du viewport) la meme
        vignette, au meme endroit. False si deja a la borne."""
        size = int(round(max(self.TILE_MIN, min(self.TILE_MAX, size))))
        if size == self.TILE:
            return False
        # Le tableau change par colonnes entieres : on avance jusqu'au decoupage suivant (sinon un
        # cran de molette ne changerait rien a l'ecran).
        step = 1 if size > self.TILE else -1
        current = self._plan(self.TILE)
        while self._plan(size) == current and self.TILE_MIN < size < self.TILE_MAX:
            size = max(self.TILE_MIN, min(self.TILE_MAX, size + step * max(1, size // 25)))
        if step > 0 and self._can_fill() and not self._shows_all(self._plan(size)):
            # Peu de fichiers : avant de les faire defiler (puis d'entrer dans une image), ils
            # remplissent l'ecran, tous ensemble.
            self._set_filled(True)
            return True
        item = self.itemAt(anchor) if anchor is not None else None
        if item is None:
            item = self.currentItem()
        # La vignette sous le curseur reste sur la meme ligne visible.
        slot = (self._row_of(item) - self.first_visible_row()) if item is not None else 0
        self.TILE = FocusGallery.tile_size = size
        self._tiles.clear()
        self._apply_grid()
        self.doItemsLayout()
        if item is not None:
            self._scroll_to_row(self._row_of(item) - min(slot, self._visible_rows - 1))
        self.viewport().update()
        return True

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            anchor = event.position().toPoint()
            if delta > 0 and self.TILE >= self.TILE_MAX and self._can_fill():
                self._zoom_into = 0
                self._set_filled(True)           # tous les fichiers remplissent l'ecran d'abord
            elif delta < 0 and self._filled:
                self._zoom_into = 0
                self._set_filled(False)          # retour a la taille des vignettes
            elif delta > 0 and (self.TILE >= self.TILE_MAX or self._filled):
                # Deja au plus grand (ou l'ecran est rempli) : on « entre » dans la vignette sous le curseur.
                self._zoom_into += delta
                if self._zoom_into >= 240:
                    self._zoom_into = 0
                    item = self.itemAt(anchor) or self.currentItem()
                    if item is not None:
                        self.zoomed_into.emit(Path(item.data(Qt.UserRole)))
            else:
                self._zoom_into = 0
                self.set_tile_size(self.TILE * 1.15 ** (delta / 120), anchor)
            event.accept()
            return
        # Molette : une ligne par cran (lignes visibles toujours calees sur la zone).
        self._wheel_rest += event.angleDelta().y()
        steps = int(self._wheel_rest / 120)
        if steps:
            self._wheel_rest -= steps * 120
            self._set_attr_hover(None)
            self._scroll_to_row(self.first_visible_row() - steps, animate=self.scroll_animated())
        event.accept()

    TEXT_MIN = 10            # hauteur mini de la sous-cellule texte (Ctrl + bordure)
    # Case NON divisee (demande de l'utilisateur) : plus de sous-cellule texte sous l'image, l'image est
    # centree sur toute la case (nom en info-bulle, attributs dessines sur l'image : _paint_attrs).
    SPLIT_CELLS = False

    def label_height(self) -> int:
        """Sous-cellule texte (nom + type et poids, sous l'image) : la hauteur choisie par Ctrl + bordure
        (`viewer_gallery_text_height`, px), sinon de quoi loger les deux lignes dans leurs polices ;
        0 quand la case n'est pas divisee (SPLIT_CELLS)."""
        if not self.SPLIT_CELLS:
            return 0
        import ui_state
        try:
            chosen = int((ui_state.APPLIED_SETTINGS or {}).get("viewer_gallery_text_height") or 0)
        except (TypeError, ValueError):
            chosen = 0
        if chosen > 0:
            return max(self.TEXT_MIN, chosen)
        look = self.film_look
        return (self.LABEL_GAP + QFontMetrics(look["name_font"][0]).height()
                + QFontMetrics(look["rank_font"][0]).height())

    def tile_pixmap(self, path: Path, mtime) -> QPixmap | None:
        """Vignette de `path` a la taille d'une case, tiree d'un PROXY un poil plus grand que la case
        (PROXY_MARGIN) : l'apercu du pipeline (cache de l'inspecteur, 640 px) s'il suffit, sinon une
        version decodee en fond a cette taille (en attendant : l'apercu, agrandi). Sans apercu :
        demande le decodage et rend la petite vignette des colonnes s'il y en a une."""
        key = str(path)
        tile = self._tiles.get(key)
        if tile is not None:
            return tile
        managed = False
        try:
            from lightroom_bridge import is_managed, preview_pixmap
            managed = is_managed(path)
            if managed and mtime is not None:
                preview_pixmap(path, mtime)
        except (ImportError, OSError, ValueError):
            pass
        dpr = self.devicePixelRatioF() or 1.0
        side = round(self._box_side * dpr)
        need = math.ceil(side * PROXY_MARGIN)
        source, enough = None, False
        proxy = _PROXIES.get(key)
        if proxy is not None and (mtime is None or proxy[0] == mtime):
            _PROXIES.move_to_end(key)
            source, enough = proxy[2], proxy[3] or proxy[1] >= need
        cached = previews._file_image_cache.get(key)
        if not enough and cached is not None and (mtime is None or cached[0] == mtime) and not cached[1].isNull():
            preview = cached[1]
            big = max(preview.width(), preview.height()) >= need
            if source is None or (not managed and (big or max(preview.width(), preview.height()) > max(source.width(), source.height()))):
                source, enough = preview, big and not managed
        if not enough and (managed or path.suffix.lower() in IMAGE_EXTENSIONS) and key not in self._proxy_failed:
            self._request_proxy(key, need)
        elif source is not None:
            enough = True                    # rien de mieux a attendre (fichier 3D, image illisible...)
        if source is None:
            return previews.file_image_pixmap(path, asynchronous=True)
        tile = source.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if isinstance(tile, QImage):
            tile = QPixmap.fromImage(tile)
        tile.setDevicePixelRatio(dpr)
        self._tiles[key] = tile
        return tile

    def _request_proxy(self, key: str, need: int) -> None:
        if self._held_proxies is not None:
            self._held_proxies.append((key, need))
            return
        if self._proxy_pending.get(key, 0) >= need:
            return
        mtime = previews.cached_mtime(Path(key))
        if mtime is None:
            return
        try:
            from lightroom_bridge import is_managed, preview_pixmap
            if is_managed(Path(key)):
                preview_pixmap(Path(key), mtime)
        except (ImportError, OSError, ValueError):
            pass
        self._proxy_pending[key] = need
        self._proxy_pool.start(_ProxyTask(self._proxy_signals, key, mtime, need))

    def hideEvent(self, event):
        if self._ripple_timer.isActive():
            self._ripple_timer.stop()
            _fine_timer(False)
            self._ripple_origin = None
        if self._scroll_goal is not None:
            self._scroll_to_row(self._scroll_goal)   # glissement en cours : pose sa fin (lignes calees)
        self._proxy_pool.clear()             # planche refermee : plus de decodage en file
        self._proxy_pending.clear()
        super().hideEvent(event)

    def _on_proxy(self, key: str, mtime: float, side: int, image, full: bool):
        if self._proxy_pending.get(key) == side:
            self._proxy_pending.pop(key, None)
        if image is None:
            self._proxy_failed.add(key)
            return
        fmt = QImage.Format_ARGB32_Premultiplied if image.hasAlphaChannel() else QImage.Format_RGB32
        _store_proxy(key, (mtime, side, image.convertToFormat(fmt), full))
        if self._busy():
            # Pendant l'apparition ou un glissement, une case refaite volerait une image a l'animation :
            # la meilleure vignette remplace la provisoire a la fin (_apply_late_proxies).
            self._late_proxies.add(key)
            return
        self._tiles.pop(key, None)           # la vignette provisoire est refaite depuis le proxy
        _CELLS.pop(key, None)
        for row in range(self.count()):     # seule sa case est repeinte
            item = self.item(row)
            if item.data(Qt.UserRole) == key:
                self.viewport().update(self.visualItemRect(item))
                break

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_G):
            self.closed.emit()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentItem() is not None:
            self.chosen.emit(Path(self.currentItem().data(Qt.UserRole)))
            return
        if event.key() == Qt.Key_I and not event.modifiers():
            self.toggle_keywords()
            return
        super().keyPressEvent(event)

    def toggle_keywords(self):
        """Touche I : mots cles ecrits (ou non) sur les photos de la planche."""
        global SHOW_KEYWORDS
        SHOW_KEYWORDS = not SHOW_KEYWORDS
        _CELLS.clear()
        _MARKED.clear()
        self.viewport().update()


# -- Parametres de l'image (panneau a droite de l'image, Reglages > Visionneuse) -----------------

_PIL_MODES = {
    "1": "1 bit (noir et blanc)", "L": "8 bits, niveaux de gris", "LA": "8 bits, gris + alpha",
    "P": "8 bits, palette", "PA": "8 bits, palette + alpha", "RGB": "8 bits par canal, RGB",
    "RGBA": "8 bits par canal, RGBA", "RGBX": "8 bits par canal, RGB", "CMYK": "8 bits par canal, CMJN",
    "YCbCr": "8 bits par canal, YCbCr", "LAB": "8 bits par canal, Lab", "HSV": "8 bits par canal, TSV",
    "I": "32 bits entiers, gris", "F": "32 bits flottants, gris", "I;16": "16 bits, niveaux de gris",
    "I;16B": "16 bits, niveaux de gris", "I;16L": "16 bits, niveaux de gris",
}
_PNG_COLOR = {0: "gris", 2: "RGB", 3: "palette", 4: "gris + alpha", 6: "RGBA"}
_EXIF_ORIENTATION = {1: "normale", 2: "miroir horizontal", 3: "180°", 4: "miroir vertical",
                     5: "miroir + 90° anti-horaire", 6: "90° horaire", 7: "miroir + 90° horaire",
                     8: "90° anti-horaire"}


def _size_text(size: int) -> str:
    for unit, step in (("Go", 1 << 30), ("Mo", 1 << 20), ("Ko", 1 << 10)):
        if size >= step:
            return f"{size / step:.1f} {unit}".replace(".", ",")
    return f"{size} octets"


def _num(value) -> float | None:
    try:
        if isinstance(value, tuple) and len(value) == 2:
            return float(value[0]) / float(value[1]) if value[1] else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _clean(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return " ".join(str(value).replace("\x00", " ").split())


def _gps_degrees(values, ref) -> float | None:
    try:
        d, m, s = (_num(v) for v in values)
        deg = d + m / 60 + s / 3600
        return -deg if str(ref).upper() in ("S", "W") else deg
    except (TypeError, ValueError):
        return None


def _png_header(path: Path) -> str | None:
    """Profondeur et couleurs d'un PNG lues dans son entete IHDR (Pillow ouvre un PNG 16 bits en 8)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(29)
        if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
            return None
        return f"{head[24]} bits par canal, {_PNG_COLOR.get(head[25], '?')}"
    except OSError:
        return None


def _exif_rows(exif, ExifTags, image_rows: list, camera_rows: list):
    """Lignes « Prise de vue » (et l'orientation, cote Image) tirees de l'EXIF lu par Pillow."""
    import datetime
    base = dict(exif)
    sub = dict(exif.get_ifd(ExifTags.IFD.Exif) or {})
    gps = dict(exif.get_ifd(ExifTags.IFD.GPSInfo) or {})
    if base.get(0x0112) in _EXIF_ORIENTATION:
        image_rows.append(("Orientation", _EXIF_ORIENTATION[base[0x0112]]))
    make, model = _clean(base.get(0x010F, "")), _clean(base.get(0x0110, ""))
    if make or model:
        camera_rows.append(("Appareil", model if make and model.startswith(make) else f"{make} {model}".strip()))
    if sub.get(0xA434):
        camera_rows.append(("Objectif", _clean(sub[0xA434])))
    taken = sub.get(0x9003) or base.get(0x0132)
    if taken:
        text = _clean(taken)
        try:
            text = datetime.datetime.strptime(text, "%Y:%m:%d %H:%M:%S").strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            pass
        camera_rows.append(("Date", text))
    exposure = _num(sub.get(0x829A))
    if exposure:
        camera_rows.append(("Exposition", f"1/{round(1 / exposure)} s" if exposure < 1
                            else f"{exposure:g} s".replace(".", ",")))
    aperture = _num(sub.get(0x829D))
    if aperture:
        camera_rows.append(("Ouverture", f"f/{aperture:g}".replace(".", ",")))
    iso = sub.get(0x8827)
    if iso:
        camera_rows.append(("ISO", str(iso[0] if isinstance(iso, tuple) else iso)))
    focal = _num(sub.get(0x920A))
    if focal:
        eq = sub.get(0xA405)
        camera_rows.append(("Focale", f"{focal:g} mm".replace(".", ",") + (f" ({eq} mm éq. 24×36)" if eq else "")))
    bias = _num(sub.get(0x9204))
    if bias:
        camera_rows.append(("Correction", f"{bias:+.1f} IL".replace(".", ",")))
    if 0x9209 in sub:
        camera_rows.append(("Flash", "déclenché" if int(sub[0x9209]) & 1 else "non"))
    if 0xA403 in sub:
        camera_rows.append(("Balance des blancs", "manuelle" if sub[0xA403] else "auto"))
    lat = _gps_degrees(gps.get(2), gps.get(1)) if gps.get(2) else None
    lon = _gps_degrees(gps.get(4), gps.get(3)) if gps.get(4) else None
    if lat is not None and lon is not None:
        camera_rows.append(("GPS", f"{lat:.5f}, {lon:.5f}"))
    for tag, label in ((0x0131, "Logiciel"), (0x013B, "Auteur"), (0x8298, "Copyright"), (0x010E, "Description")):
        value = _clean(base.get(tag, ""))
        if value:
            camera_rows.append((label, value))


def image_sources(path: Path, mtime: float) -> list:
    """Lignes « Source du proxy » (colonnes, inspecteur, diapositives), « Path du proxy » et
    « Source de l'aperçu plein écran » (image en focus). Lit le catalogue / le disque : EN FOND."""
    try:
        import lightroom_bridge as lb
        managed = lb.is_managed(path)
    except (ImportError, OSError, ValueError):
        managed = False
    if managed:
        try:
            found = lb.proxy_file(path)
        except Exception:
            found = None
        return [("Source du proxy", lb.proxy_source(path)),
                ("Path du proxy", str(found[0]) if found is not None else "—"),
                ("Source de l'aperçu plein écran", lb.fullscreen_source(path))]
    from previews import _file_image_cache_path
    cache = _file_image_cache_path(path, mtime)
    proxy = "Application · cache d'aperçus" if cache.is_file() else "Application · pas encore créé"
    full = "Image originale (JPEG intégré au RAW)" if path.suffix.lower() in RAW_EXTENSIONS else "Image originale"
    return [("Source du proxy", proxy), ("Path du proxy", str(cache)),
            ("Source de l'aperçu plein écran", full)]


def image_info(path: Path) -> list:
    """Tous les parametres connus d'un fichier de la visionneuse : [(section, [(libelle, valeur)])].
    Lu sans decoder l'image (entete ; EXIF, profil couleur, ppp via Pillow s'il est installe).
    Appele EN FOND (_InfoTask), jamais sur le fil de l'interface."""
    import datetime
    sections = []
    file_rows = [("Nom", display_name(path)), ("Dossier", str(path.parent)),
                 ("Path de l'image", str(path.resolve())),
                 ("Type", path.suffix.lstrip(".").upper() or "?")]
    try:
        stat = path.stat()
        file_rows += image_sources(path, stat.st_mtime)

        def stamp(t):
            return datetime.datetime.fromtimestamp(t).strftime("%d/%m/%Y %H:%M:%S")

        file_rows += [("Taille", _size_text(stat.st_size)), ("Modifié", stamp(stat.st_mtime)),
                      ("Créé", stamp(stat.st_ctime))]
    except OSError:
        pass
    sections.append(("Fichier", file_rows))
    image_rows, camera_rows, text_rows = [], [], []
    reader = QImageReader(str(path))
    size = reader.size()
    dims = (size.width(), size.height()) if size.isValid() else None
    fmt = bytes(reader.format()).decode("ascii", "ignore").upper()
    for key in reader.textKeys():
        value = _clean(reader.text(key))
        if value and len(value) < 400:
            text_rows.append((key, value))
    depth = _png_header(path) if path.suffix.lower() == ".png" else None
    colors = None
    extra_rows: list = []
    try:
        from PIL import ExifTags, Image
    except ImportError:
        Image = None
    if Image is not None:
        try:
            with Image.open(path) as im:
                dims = dims or im.size
                fmt = fmt or (im.format or "")
                bits = None
                if im.format == "TIFF":
                    sample = getattr(im, "tag_v2", {}).get(258)
                    if sample:
                        first = sample[0] if isinstance(sample, tuple) else sample
                        bits = f"{first} bits par canal, {im.mode}"
                colors = depth or bits or _PIL_MODES.get(im.mode, im.mode)
                if "transparency" in im.info or im.mode in ("RGBA", "LA", "PA"):
                    extra_rows.append(("Transparence", "oui"))
                dpi = im.info.get("dpi")
                if dpi and _num(dpi[0]):
                    extra_rows.append(("Résolution", f"{round(_num(dpi[0]))} × {round(_num(dpi[1]))} ppp"))
                icc = im.info.get("icc_profile")
                if icc:
                    name = "intégré"
                    try:
                        import io
                        from PIL import ImageCms
                        name = ImageCms.getProfileDescription(
                            ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip() or name
                    except Exception:
                        pass
                    extra_rows.append(("Profil couleur", name))
                frames = getattr(im, "n_frames", 1) or 1
                if frames > 1:
                    extra_rows.append(("Images", str(frames)))
                exif = im.getexif()
                if exif:
                    _exif_rows(exif, ExifTags, extra_rows, camera_rows)
        except Exception:
            pass
    if dims:
        w, h = dims
        g = math.gcd(w, h) or 1
        ratio = f"{w // g}:{h // g}" if w // g <= 32 and h // g <= 32 else f"{w / max(1, h):.3f}".replace(".", ",")
        image_rows += [("Dimensions", f"{w} × {h} px"), ("Mégapixels", f"{w * h / 1e6:.1f}".replace(".", ",")),
                       ("Ratio", ratio)]
    if fmt:
        image_rows.append(("Format", fmt.upper()))
    if colors or depth:
        image_rows.append(("Couleurs", colors or depth))
    image_rows += extra_rows
    for title, rows in (("Image", image_rows), ("Prise de vue", camera_rows), ("Textes intégrés", text_rows)):
        if rows:
            sections.append((title, rows))
    return sections


class _InfoSignals(QObject):
    done = Signal(str, float, object)


class _InfoTask(QRunnable):
    def __init__(self, path: Path, mtime: float, signals: _InfoSignals):
        super().__init__()
        self._path, self._mtime, self._signals = path, mtime, signals

    def run(self):
        try:
            info = image_info(self._path)
        except Exception:
            info = [("Fichier", [("Nom", display_name(self._path))])]
        try:
            self._signals.done.emit(str(self._path), self._mtime, info)
        except RuntimeError:                      # panneau detruit entre-temps
            pass


def filter_colors() -> list[tuple[str, str]]:
    """(nom, couleur) des 5 couleurs de Reglages > Visionneuse > Filtres (couleurs de l'appli resolues)."""
    import ui_state
    from app_style import resolve_color_ref
    from settings_store import DEFAULT_SETTINGS
    settings = ui_state.APPLIED_SETTINGS or DEFAULT_SETTINGS
    out = []
    for n in range(1, 6):
        name = str(settings.get(f"viewer_filter_color_{n}_name") or DEFAULT_SETTINGS[f"viewer_filter_color_{n}_name"])
        color = settings.get(f"viewer_filter_color_{n}") or DEFAULT_SETTINGS[f"viewer_filter_color_{n}"]
        out.append((name, resolve_color_ref(color)))
    return out


class _StarRating(QWidget):
    """Note de 0 a 5 : clic sur une etoile = cette note, re-clic sur la note en cours = aucune ; survol =
    apercu de la note visee. Couleur de selection des tableaux pour les etoiles allumees."""

    changed = Signal(int)
    COUNT = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value, self._hover = 0, 0
        self._step = scaled(20)
        self.setFixedSize(self._step * self.COUNT, scaled(20))
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int):
        self._value = max(0, min(self.COUNT, int(value)))
        self.update()

    def _star_at(self, x: float) -> int:
        return max(1, min(self.COUNT, int(x // self._step) + 1))

    def mouseMoveEvent(self, event):
        star = self._star_at(event.position().x())
        if star != self._hover:
            self._hover = star
            self.update()

    def leaveEvent(self, event):
        self._hover = 0
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            star = self._star_at(event.position().x())
            self.setValue(0 if star == self._value else star)
            self.changed.emit(self._value)

    def paintEvent(self, event):
        import math
        from PySide6.QtGui import QPolygonF
        from settings_store import M
        from settings_widgets import _selection_color
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        lit = _selection_color(255)
        off = QColor(M["field_border"])
        shown = self._hover or self._value
        radius = self.height() * 0.42
        for i in range(self.COUNT):
            cx, cy = self._step * i + self._step / 2, self.height() / 2
            points = [QPointF(cx + (radius if k % 2 == 0 else radius * 0.45) * math.sin(k * math.pi / 5),
                              cy - (radius if k % 2 == 0 else radius * 0.45) * math.cos(k * math.pi / 5))
                      for k in range(10)]
            on = i < shown
            color = QColor(lit if on else off)
            if on and self._hover and i >= self._value:
                color.setAlpha(150)                     # apercu de survol
            p.setPen(QPen(color, 1.2))
            p.setBrush(color if on else Qt.NoBrush)
            p.drawPolygon(QPolygonF(points))
        p.end()


class _ColorLabels(QWidget):
    """Les 5 couleurs de Reglages > Visionneuse > Filtres en pastilles : clic = cette couleur, re-clic sur
    la couleur en cours = aucune ; nom en info-bulle. `multi` (fenetre des filtres) : chaque clic allume /
    eteint sa couleur, plusieurs a la fois (`values`)."""

    changed = Signal(int)

    def __init__(self, parent=None, multi: bool = False):
        super().__init__(parent)
        self._value, self._colors = 0, filter_colors()
        self._multi, self._chosen = multi, set()
        self._step = scaled(22)
        self.setFixedSize(self._step * len(self._colors), scaled(20))
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int):
        self._value = max(0, min(len(self._colors), int(value)))
        self.update()

    def values(self) -> list[int]:
        return sorted(self._chosen)

    def setValues(self, values):
        self._chosen = {int(v) for v in values or [] if 1 <= int(v) <= len(self._colors)}
        self.update()

    def refresh_colors(self):
        self._colors = filter_colors()
        self.update()

    def _index_at(self, x: float) -> int:
        return max(1, min(len(self._colors), int(x // self._step) + 1))

    def mouseMoveEvent(self, event):
        index = self._index_at(event.position().x())
        self.setToolTip(self._colors[index - 1][0])

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self._index_at(event.position().x())
            if self._multi:
                self._chosen ^= {index}
                self.update()
                self.changed.emit(index)
                return
            self.setValue(0 if index == self._value else index)
            self.changed.emit(self._value)

    def paintEvent(self, event):
        from settings_store import M
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        size = self.height() * 0.62
        chosen_set = self._chosen if self._multi else ({self._value} if self._value else set())
        for i, (_name, color) in enumerate(self._colors):
            center = QPointF(self._step * i + self._step / 2, self.height() / 2)
            chosen = i + 1 in chosen_set
            if chosen:                                    # anneau autour de la couleur choisie
                p.setPen(QPen(QColor(M["value_fg"]), 1.6))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(center, size / 2 + 3, size / 2 + 3)
            fill = QColor(color)
            if not chosen and chosen_set:
                fill.setAlphaF(fill.alphaF() * 0.45)      # les autres s'effacent
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawEllipse(center, size / 2, size / 2)
        p.end()


class _StatusFlags(QWidget):
    """Trois actions directes pour le statut Lightroom : neutre, garder, rejeter."""

    changed = Signal(str)
    ICONS = {
        "keep": (r"F:\SYNC\Sync\IMAGES\ico\PNG\coche_01.png", "Marquée"),
        "delete": (r"F:\SYNC\Sync\IMAGES\ico\PNG\croix_01.png", "Rejetée"),
        "": (r"F:\SYNC\Sync\IMAGES\ico\PNG\moins_01.png", "Neutre"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QToolButton

        self._buttons = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scaled(5))
        for value, (path, label) in self.ICONS.items():
            button = QToolButton(self)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolTip(label)
            custom = {"keep": previews.UI_ICON_VIEWER_FLAG_KEEP,
                      "delete": previews.UI_ICON_VIEWER_FLAG_DELETE}.get(value)
            custom_pix = previews.custom_ui_icon_pixmap(custom, scaled(48)) if custom else None
            button.setIcon(QIcon(custom_pix) if custom_pix is not None else QIcon(path))
            button.setIconSize(QSize(scaled(24), scaled(24)))
            button.setFixedSize(scaled(32), scaled(30))
            button.setStyleSheet(
                "QToolButton { border: 1px solid transparent; border-radius: 3px; padding: 2px; }"
                "QToolButton:checked { border-color: #55aaff; background: rgba(85,170,255,45); }"
            )
            button.clicked.connect(lambda _checked=False, status=value: self.changed.emit(status))
            self._group.addButton(button)
            self._buttons[value] = button
            layout.addWidget(button)
        self.setValue("")

    def setValue(self, value: str):
        self._buttons.get(value, self._buttons[""]).setChecked(True)


class FileAttributesEditor(QObject):
    """Lignes « Attributs » du tableau de la visionneuse (demande de l'utilisateur) : note, couleur,
    j'aime, mots cles, statut du fichier EN FOCUS ; chaque changement est enregistre aussitot
    (file_attributes). Champs = briques des reglages (toggle, zone de saisie, liste) + etoiles / pastilles."""

    STATUS_LABELS = (("", "Neutre"), ("keep", "Marquée"), ("delete", "Rejetée"))
    TITLE = "Attributs"

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._path: Path | None = None
        self._loading = False
        self.rows: list = []
        self.on_saved = None                       # rappel (chemin, changements) apres chaque enregistrement

    def build_rows(self) -> list:
        """(libelle, champ, None) pour _flat_cells_table — champs neufs (le tableau est reconstruit)."""
        from settings_cells import _WordsField
        from settings_widgets import _Toggle
        self.stars = _StarRating()
        self.colors = _ColorLabels()
        # Mots cles : saisis a la volee, separes par des espaces, autocompletion des mots deja employes.
        import file_attributes
        self.keywords = _WordsField(suggestions=file_attributes.known_keywords, width=scaled(150))
        self.keywords.setPlaceholderText("ciel nuit ville…")
        self.status = _StatusFlags()
        self.stars.changed.connect(lambda v: self._save(rating=v))
        self.colors.changed.connect(lambda v: self._save(color=v))
        self.keywords.editingFinished.connect(self._save_keywords)      # Entree / sortie du champ
        self.status.changed.connect(lambda value: self._save(status=value))
        self.rows = [("Note (0–5)", self.stars, None), ("Libellé de couleur", self.colors, None),
                     ("Drapeau", self.status, None), ("Mots clés", self.keywords, None)]
        self._load()
        return self.rows

    def set_path(self, path: Path | None, values: dict | None = None):
        """`values` : attributs deja connus (memoire de la planche) ; sinon lus (file_attributes.get)."""
        if self.rows and self._path is not None and path != self._path:
            self._save_keywords()                  # mots en cours de saisie : pas perdus
        self._path = path
        self._load(values)

    def _load(self, known: dict | None = None):
        import file_attributes
        if not self.rows:
            return
        if not file_attributes.eligible(self._path):
            values = dict(file_attributes.DEFAULTS)
        elif known is not None:
            values = file_attributes.values_of(known)
        else:
            values = file_attributes.get(self._path)
        self._loading = True
        try:
            for control in (self.stars, self.colors, self.keywords, self.status):
                control.setEnabled(True)
            self.stars.setValue(values["rating"])
            self.colors.setValue(values["color"])
            self.keywords.set_words(values["keywords"])
            self._loaded_keywords = list(values["keywords"])
            self.status.setValue(values["status"])
        except RuntimeError:                       # champs detruits (tableau reconstruit)
            pass
        finally:
            self._loading = False

    def _save(self, **changes):
        import file_attributes
        if self._loading or not file_attributes.eligible(self._path):
            return
        file_attributes.update(self._path, **changes)
        if "keywords" in changes:
            self._loaded_keywords = list(changes["keywords"])
        if self.on_saved is not None:
            self.on_saved(self._path, changes)

    def _save_keywords(self):
        import file_attributes
        try:
            words = self.keywords.words()
        except RuntimeError:
            return
        if self._path is not None and file_attributes.eligible(self._path) \
                and words != self._shown_keywords():
            self._save(keywords=words)

    def _shown_keywords(self) -> list:
        """Mots cles du fichier avant la saisie (ceux charges dans le champ, ou les derniers enregistres)."""
        return list(getattr(self, "_loaded_keywords", None) or [])


class KeywordsWindow(QWidget):
    """Fenetre des mots cles d'une photo (bouton « + » de sa case) : UN MOT CLE PAR LIGNE (demande de
    l'utilisateur ; un mot cle peut contenir des espaces), zone de saisie des reglages
    (`settings_cells._LinesField`) avec autocompletion des mots deja employes ; elle contient les mots
    cles actuels — en ajouter une ligne, en effacer. Clic ailleurs ou Ctrl + Entree = enregistrer et fermer,
    Echap = fermer sans rien changer. Cadre de panneau des reglages (`_PanelFrame`). Le bouton « + » la
    rouvre a chaque fois (la reference est lachee a la fermeture)."""

    saved = Signal(list)
    closed = Signal(object)

    def __init__(self, gallery: "FocusGallery", key: str, words: list):
        super().__init__(gallery.window(), Qt.Tool | Qt.FramelessWindowHint)
        from PySide6.QtWidgets import QVBoxLayout
        from settings_cells import _LinesField
        from settings_store import M
        from settings_theme import _text_label
        from settings_window import _PanelFrame
        import file_attributes
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.key = key
        self._done = False
        self._filtered = False
        frame = _PanelFrame(self)
        frame.setColors(M["panel_bg"], M["panel_border"])
        frame.setRadius(scaled(5))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        box = QVBoxLayout(frame)
        m = scaled(10)
        box.setContentsMargins(m, m, m, m)
        box.setSpacing(scaled(6))
        title = _text_label(f"Mots clés — {display_name(Path(key))}", "row_label")
        title.setWordWrap(False)
        box.addWidget(title)
        self.field = _LinesField(words, suggestions=file_attributes.known_keywords, width=scaled(300))
        self.field.setPlaceholderText("un mot clé par ligne")
        self.field.submitted.connect(self._accept)
        self.field.textChanged.connect(self._fit)
        box.addWidget(self.field)
        hint = _text_label("Ctrl+Entrée ou clic ailleurs : enregistrer · Échap : annuler", "row_label")
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.setFixedWidth(scaled(340))
        self.adjustSize()

    def _fit(self):
        self.field.fit_rows()
        self.adjustSize()

    def popup_near(self, global_pos: QPoint):
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left(), global_pos.x() - self.width()), area.right() - self.width())
        y = min(max(area.top(), global_pos.y() - self.height() - scaled(8)), area.bottom() - self.height())
        self.move(x, y)
        self.show()
        self.raise_()
        self.field.setFocus()
        self.field.moveCursor(QTextCursor.End)
        QApplication.instance().installEventFilter(self)

    def _accept(self):
        if self._done:
            return
        self._done = True
        self.saved.emit(self.field.lines())
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._done = True
            self.close()
            return
        super().keyPressEvent(event)

    def _is_inside(self, global_pos: QPoint) -> bool:
        """Le point (global) est dans cette fenetre ou dans la liste de propositions du champ."""
        widget = QApplication.widgetAt(global_pos)
        if widget is None:
            return False
        popup = self.field.completer_.popup()
        return (widget is self or self.isAncestorOf(widget)
                or (popup is not None and (widget is popup or popup.isAncestorOf(widget))))

    def eventFilter(self, obj, event):
        # « Clic ailleurs » = enregistrer et fermer. Jugé sur le widget SOUS LE CURSEUR, jamais sur `obj` : pour
        # une fenetre, le filtre d'application recoit aussi le clic au niveau de la fenetre native (pas un
        # QWidget), pris a tort pour un clic exterieur — la fenetre se fermait des qu'on cliquait dedans
        # (signale : impossible d'entrer un nouveau mot cle).
        if event.type() == QEvent.MouseButtonPress and not self._done:
            if not self._is_inside(event.globalPosition().toPoint()):
                self._accept()
        return False

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self.closed.emit(self)
        super().closeEvent(event)


class FocusInfoPanel(QWidget):
    """Tableau de TOUS les parametres de l'image en cours, a droite de l'image (Reglages >
    Visionneuse > « Parametres de l'image », touche I). Lu en fond (_InfoTask, cache par fichier).
    Habillage = celui des REGLAGES, jamais un style a part : cadre de panneau (`_PanelFrame`,
    M["panel_bg"] / M["panel_border"]), titres de section (police / couleur des titres de niveau 1),
    tableaux Parametre | Valeur de la v2 (`_flat_cells_table`, roles de texte row_label / value),
    style commun pose par `seed_window_look` (comme settings_quick_style.QuickStyleWindow). Les
    dimensions des tableaux (largeurs, hauteurs, justifications) s'enregistrent comme dans les
    reglages (`table_dims`, cle `Paramètres de l'image/<section>#0`). La visionneuse lui RESERVE sa
    bande (PipelineBrowser._viewer_area) : l'image n'est jamais couverte."""

    WIDTH = 380
    DIMS = "Paramètres de l'image"
    _VALUE_WIDTH = 190          # valeurs plus longues : abregees (texte entier en info-bulle)

    def __init__(self, parent):
        super().__init__(parent)
        from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout
        from settings_window import _PanelFrame
        self._signals = _InfoSignals(self)
        self._signals.done.connect(self._on_done)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._cache: OrderedDict = OrderedDict()
        self._path: Path | None = None
        self._sections: list = []
        self._shape = None                    # (titre, libelles) des tableaux affiches
        self._values: list = []               # etiquettes des valeurs, dans l'ordre des lignes
        self._tables: list = []
        # Attributs du fichier en focus (note, couleur, j'aime, mots cles, statut), en tete du tableau.
        self._attributes = FileAttributesEditor(self)
        self._frame = _PanelFrame(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._frame)
        box = QVBoxLayout(self._frame)
        box.setContentsMargins(1, 1, 1, 1)
        self._scroller = QScrollArea()
        self._scroller.setFrameShape(QFrame.NoFrame)
        self._scroller.setWidgetResizable(True)
        self._scroller.setStyleSheet("QScrollArea { background: transparent; }")
        self._scroller.viewport().setStyleSheet("background: transparent;")
        box.addWidget(self._scroller)
        self._dims_timer = QTimer(self)
        self._dims_timer.setSingleShot(True)
        self._dims_timer.setInterval(400)
        self._dims_timer.timeout.connect(self._save_dims)
        self.restyle()

    @staticmethod
    def panel_width() -> int:
        return scaled(FocusInfoPanel.WIDTH)

    def restyle(self):
        """(Re)pose le style commun des reglages et reconstruit les tableaux (reglages changes)."""
        import ui_state
        from settings_store import M
        from settings_widgets import _TABLE_DIMS
        import settings_window_v2 as v2
        settings = dict(ui_state.APPLIED_SETTINGS or {})
        if "colors" in settings:
            v2.seed_window_look(settings)
        for key, dims in (settings.get("table_dims") or {}).items():
            if key.startswith(self.DIMS + "/"):
                _TABLE_DIMS.setdefault(key, dims)
        self._frame.setColors(M["panel_bg"], M["panel_border"])
        self._shape = None
        self._show(self._sections)

    def set_path(self, path: Path | None):
        if path == self._path and self._sections:
            return
        self._attributes.set_path(path)
        self._path = path
        if path is None:
            self._show([])
            return
        mtime = previews.cached_mtime(path)
        hit = self._cache.get(str(path))
        if hit is not None and hit[0] == mtime:
            self._show(hit[1])
        else:
            # En attendant la lecture : le tableau reste en place, valeurs en attente.
            self._show([(title, [(label, "…") for label, _v in rows]) for title, rows in self._sections]
                       or [("Fichier", [("Nom", display_name(path))])])
            self._pool.clear()
            self._pool.start(_InfoTask(path, mtime, self._signals))

    def refresh(self, path: Path):
        """Relit les parametres de `path` (sources des apercus changees : apercu Lightroom ou proxy
        arrive apres coup) ; le tableau garde sa forme, seules les valeurs changent."""
        self._cache.pop(str(path), None)
        if self._path is not None and str(self._path) == str(path):
            self._pool.start(_InfoTask(path, previews.cached_mtime(path), self._signals))

    def sections(self) -> list:
        return self._sections

    def wait_done(self, msecs: int = 5000) -> bool:
        return self._pool.waitForDone(msecs)

    def _on_done(self, key: str, mtime: float, info):
        self._cache[key] = (mtime, info)
        self._cache.move_to_end(key)
        while len(self._cache) > 512:
            self._cache.popitem(last=False)
        if self._path is not None and str(self._path) == key:
            self._show(info)

    def _value_text(self, label: QWidget, value) -> None:
        text = str(value)
        metrics = QFontMetrics(label.font())
        width = scaled(self._VALUE_WIDTH)
        label.setText(metrics.elidedText(text, Qt.ElideMiddle, width))
        label.setToolTip(text if metrics.horizontalAdvance(text) > width else "")

    def _show(self, sections: list):
        """Meme forme qu'avant (memes sections, memes libelles : cas courant d'un dossier) : seules
        les valeurs changent, aucun widget n'est reconstruit. Sinon : tableaux reconstruits."""
        import file_attributes
        self._sections = sections
        shape = (file_attributes.eligible(self._path),
                 tuple((title, tuple(label for label, _v in rows)) for title, rows in sections))
        if shape == self._shape:
            values = [value for _t, rows in sections for _l, value in rows]
            for label, value in zip(self._values, values):
                self._value_text(label, value)
            return
        from PySide6.QtWidgets import QLabel, QVBoxLayout
        import settings_window_v2 as v2
        from settings_store import _title_color, _title_font
        from settings_theme import _text_label
        self._shape = shape
        self._values, self._tables = [], []
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(scaled(14), scaled(10), scaled(14), scaled(14))
        layout.setSpacing(scaled(6))
        if shape[0] and sections:                      # fichier a apercu : ses attributs, modifiables
            head = QLabel(FileAttributesEditor.TITLE)
            head.setFont(_title_font(1))
            head.setStyleSheet(f"color: {_title_color(1)}; background: transparent;")
            layout.addWidget(head)
            table = v2._flat_cells_table(self._attributes.build_rows())
            table._dims_key = f"{self.DIMS}/{FileAttributesEditor.TITLE}#0"
            table.dimsChanged.connect(self._dims_timer.start)
            self._tables.append(table)
            layout.addWidget(table, 0, Qt.AlignLeft)
            layout.addSpacing(scaled(8))
        for title, rows in sections:
            head = QLabel(title)
            head.setFont(_title_font(1))
            head.setStyleSheet(f"color: {_title_color(1)}; background: transparent;")
            layout.addWidget(head)
            table_rows = []
            for label, value in rows:
                cell = _text_label("", "value")
                self._value_text(cell, value)
                self._values.append(cell)
                table_rows.append((label, cell, None))
            table = v2._flat_cells_table(table_rows)
            table._dims_key = f"{self.DIMS}/{title}#0"
            table.dimsChanged.connect(self._dims_timer.start)
            self._tables.append(table)
            layout.addWidget(table, 0, Qt.AlignLeft)       # tableaux justifies a gauche
            layout.addSpacing(scaled(8))
        layout.addStretch(1)
        old = self._scroller.takeWidget()
        self._scroller.setWidget(inner)
        if old is not None:
            old.deleteLater()

    def _save_dims(self):
        """Dimensions des tableaux tirees a la main : sur le disque aussitot (comme les reglages)."""
        from settings_store import load_settings, save_settings
        from settings_widgets import _TABLE_DIMS
        import ui_state
        changed = {}
        for table in self._tables:
            try:
                changed[table._dims_key] = table.collectDims()
            except RuntimeError:
                continue
        if not changed:
            return
        _TABLE_DIMS.update(changed)
        settings = load_settings()
        all_dims = dict(settings.get("table_dims") or {})
        all_dims.update(changed)
        settings["table_dims"] = all_dims
        save_settings(settings)
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS["table_dims"] = dict(all_dims)


# -- Filtres de la planche (demande de l'utilisateur) : bouton filtre, fenetre, elements ecrits a cote --

class FilterChips(QWidget):
    """Elements du filtre applique, ecrits a cote du bouton filtre de la planche en « style code » : police
    et couleur du role « Police code » (Reglages > Polices principales), chacun dans une pastille teintee
    de cette couleur, arrondie comme les zones de saisie. Transparent a la souris (la planche reste
    cliquable dessous) ; `set_items` retaille le widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._items: list[str] = []
        self.restyle()

    def restyle(self):
        from app_style import role_color, role_font
        self._font = role_font("code", 10)
        self._color = role_color("code", C["text"])
        self._layout()

    def set_items(self, items: list[str]):
        self._items = list(items)
        self._layout()

    def _layout(self):
        metrics = QFontMetrics(self._font)
        pad, gap = scaled(6), scaled(4)
        self._boxes = []
        x = 0
        height = metrics.height() + scaled(6)
        for text in self._items:
            width = metrics.horizontalAdvance(text) + 2 * pad
            self._boxes.append((QRectF(x, 0, width, height), text))
            x += width + gap
        self.setFixedSize(max(1, int(x - gap if self._items else 1)), height)
        self.update()

    def paintEvent(self, event):
        from settings_widgets import _input_radius
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setFont(self._font)
        radius = min(_input_radius(), self.height() / 2)
        tint = QColor(self._color)
        tint.setAlphaF(0.16)
        for rect, text in self._boxes:
            p.setPen(Qt.NoPen)
            p.setBrush(tint)
            p.drawRoundedRect(rect, radius, radius)
            p.setPen(QColor(self._color))
            p.drawText(rect, Qt.AlignCenter, text)
        p.end()


def filter_window(spec: dict, scopes: list[tuple[str, str]], settings: dict | None = None, parent=None,
                  provenances: list[tuple[str, str]] | None = None):
    """Fenetre des filtres de la planche : la fenetre « Changement de style a la volee » (briques des
    reglages, mise en forme retenue sous « Filtres »), une ligne par critere. `scopes` : (cle, libelle) des
    portees proposees ; `provenances` : (cle, libelle) des provenances (file_filters.provenance_choices).
    Valeurs en direct par `styleChanged` -> dict du filtre (file_filters)."""
    import file_filters as ff
    from settings_cells import _TextField
    from settings_quick_style import QuickStyleWindow
    from settings_widgets import _SelectField, _SliderField, _Toggle
    spec = ff.normalized(spec)
    width = scaled(190)
    scope_labels = [label for _k, label in scopes]
    scope = _SelectField(scope_labels, dict(scopes).get(spec["scope"], scope_labels[0]), width=width)
    origins = [("", "Toutes")] + list(provenances if provenances is not None else ff.PROVENANCE_FIXED)
    if spec["provenance"] and spec["provenance"] not in dict(origins):
        origins.append((spec["provenance"], spec["provenance"][len(ff.PROV_IO):]))
    origin = _SelectField([label for _k, label in origins], dict(origins)[spec["provenance"]], width=width)
    # Note : « au moins » / « egal a » puis les etoiles, cote a cote dans la cellule (sans entete ni
    # bordures de sous-cellules : demande de l'utilisateur).
    rating = QWidget()
    rating.setStyleSheet("background: transparent;")
    row_layout = QHBoxLayout(rating)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(scaled(10))
    rating.mode = _SelectField([l for _k, l in ff.RATING_MODES], dict(ff.RATING_MODES)[spec["rating_mode"]],
                               width=scaled(90))
    rating.stars = _StarRating()
    rating.stars.setValue(spec["rating"])
    rating._v2_parts = {"mode": rating.mode, "stars": rating.stars}
    row_layout.addWidget(rating.mode, 0, Qt.AlignVCenter)
    row_layout.addWidget(rating.stars, 0, Qt.AlignVCenter)
    colors = _ColorLabels(multi=True)
    colors.setValues(spec["color"])
    # Mots cles : comme dans les attributs, separes par des espaces, autocompletion des mots deja employes.
    import file_attributes
    from settings_cells import _WordsField
    keywords = _WordsField(spec["keywords"], suggestions=file_attributes.known_keywords, width=width)
    keywords.setPlaceholderText("ciel nuit…")
    statuses = (("", "Tous"), ("keep", "Marquées"), ("delete", "Rejetées"), (ff.STATUS_NONE, "Neutres"))
    status = _SelectField([l for _k, l in statuses], dict(statuses)[spec["status"]], width=width)
    extensions = _TextField(" ".join(spec["extensions"]), width=width)
    extensions.setPlaceholderText("jpg png blend…")
    size_min = _SliderField(0, 2000, spec["size_min"], "Mo", slider_width=scaled(120), box_width=68)
    size_max = _SliderField(0, 2000, spec["size_max"], "Mo", slider_width=scaled(120), box_width=68)
    period = _SelectField([l for _k, l in ff.DATE_PERIODS], dict(ff.DATE_PERIODS)[spec["period"]], width=width)
    date_from = _TextField(spec["date_from"], width=width)
    date_to = _TextField(spec["date_to"], width=width)
    for field in (date_from, date_to):
        field.setPlaceholderText("JJ/MM/AAAA")

    def key_of(pairs, label):
        return next((k for k, l in pairs if l == label), pairs[0][0])

    rows = [
        ("Portée", scope, lambda w: {"scope": key_of(scopes, w.value())}),
        ("Provenance", origin, lambda w: {"provenance": key_of(origins, w.value())}),
        ("Note", rating, lambda w: {"rating": w.stars.value(),
                                     "rating_mode": key_of(ff.RATING_MODES, w.mode.value())}),
        ("Couleurs", colors, lambda w: {"color": w.values()}),
        ("Mots clés", keywords, lambda w: {"keywords": w.words()}),
        ("Drapeau", status, lambda w: {"status": key_of(statuses, w.value())}),
        ("Type de fichier", extensions, lambda w: {"extensions": ff.parse_extensions(w.text())}),
        ("Taille min (0 = aucune)", size_min, lambda w: {"size_min": w.value()}),
        ("Taille max (0 = aucune)", size_max, lambda w: {"size_max": w.value()}),
        ("Date", period, lambda w: {"period": key_of(ff.DATE_PERIODS, w.value())}),
        ("Modifié depuis le", date_from, lambda w: {"date_from": w.text().strip()}),
        ("Modifié jusqu'au", date_to, lambda w: {"date_to": w.text().strip()}),
    ]
    window = QuickStyleWindow("Filtres", rows, {}, title="Filtres", settings=settings, parent=parent)
    window.filter_fields = {label: widget for label, widget, _r in rows}

    def refresh_marks(*_a):
        """Lignes ou un filtre est applique (valeur differente de « aucun filtre ») : fond / bordures de
        Reglages > Visionneuse > Filtres (clic droit > « Style des filtres actives »)."""
        from settings_widgets import set_row_mark
        look = filter_row_look()
        for _label, widget, reader in rows:
            values = reader(widget)
            current = ff.normalized(values)
            active = any(current[k] != ff.DEFAULT_FILTER[k] for k in values if k not in ff.MODIFIERS)
            try:
                set_row_mark(widget, look if active else None)
            except RuntimeError:                  # fenetre fermee
                return
    window.refresh_marks = refresh_marks
    window.styleChanged.connect(refresh_marks)
    refresh_marks()
    return window


def filter_row_look() -> dict:
    """Marque des lignes actives de la fenetre des filtres (settings_widgets.set_row_mark), d'apres les
    reglages appliques."""
    import ui_state
    from app_style import resolve_color_ref
    from settings_store import DEFAULT_SETTINGS
    from settings_store import _coerce_corner_radius
    from settings_widgets import _coerce_side_enabled
    s = {**DEFAULT_SETTINGS, **(ui_state.APPLIED_SETTINGS or {})}
    bg = resolve_color_ref(s["viewer_filter_row_bg_color"]) if s["viewer_filter_row_bg_enabled"] else None
    return {"bg": bg, "sides": _coerce_side_enabled(s["viewer_filter_row_border_enabled"]),
            "colors": {k: resolve_color_ref(v) for k, v in (s["viewer_filter_row_border"] or {}).items()},
            "thickness": int(s["viewer_filter_row_border_thickness"] or 0),
            "radius": _coerce_corner_radius(s["viewer_filter_row_radius"]),
            "margin": {k: int((s["viewer_filter_row_margin"] or {}).get(k, 0) or 0)
                       for k in ("left", "top", "right", "bottom")}}


def _filter_window_menu_extra(widget, menu):
    """Clic droit dans la fenetre des filtres : « Style des filtres actives… » (fond, bordures)."""
    window = widget.window() if widget is not None else None
    handler = getattr(window, "on_row_style", None)
    if handler is None:
        return
    menu.addSeparator()
    menu.addAction("Style des filtres activés…", handler)


def _install_filter_menu():
    from settings_widgets import CONTEXT_MENU_EXTRAS
    if _filter_window_menu_extra not in CONTEXT_MENU_EXTRAS:
        CONTEXT_MENU_EXTRAS.append(_filter_window_menu_extra)


_install_filter_menu()

"""Caches des vignettes de la pellicule et des proxies de la planche (mémoire + disque), tâches de fond.

Découpé de focus.py (2026-10-28) ; carte : docs/agents/fm_visionneuse.md."""
import hashlib
import os
import time
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap

import previews


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

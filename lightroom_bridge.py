"""Pont discret entre les dossiers associés et le module SDK Lightroom Classic.

Le catalogue n'est ouvert qu'en lecture seule. Les fichiers JPEG de prévisualisation
sont demandés au SDK Lightroom et conservés dans le cache de Pipeline Browser.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
import unicodedata
import winreg

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QImage, QImageReader, QPixmap

from config import DATA_DIR, IMAGE_EXTENSIONS, PSD_EXTENSIONS, RAW_EXTENSIONS, VIDEO_EXTENSIONS

MARKER = ".pipeline_lightroom.json"
PLUGIN = Path(__file__).parent / "plugins" / "PipelineLightroom.lrplugin"
_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="LightroomProxy")
_signals = None
_pending: set[tuple[str, str]] = set()
_force_after_pending: set[tuple[str, str]] = set()
_retry_after: dict[tuple[str, str], float] = {}
_automatic_requests: dict[tuple[str, str], tuple[Path, float, Path, Path, str, float]] = {}
_AUTO_MAX_IN_FLIGHT = 6
_AUTO_TIMEOUT = 120
_lock = threading.Lock()
_metadata_cache: dict[tuple[str, str], tuple[tuple, dict | None, float]] = {}
_preview_path_cache: dict[tuple[str, int, int | None], tuple[tuple, tuple[Path, str, str, str] | None]] = {}
_displayed_from: set[str] = set()
_preview_origins: dict[str, str] = {}
_preview_errors: dict[str, str] = {}
_large_preview_pending: set[str] = set()
_large_preview_retry_after: dict[tuple[str, str], float] = {}
_develop_profiles: dict[str, tuple[str, str, str]] = {}
_profile_pending: set[str] = set()
_preview_monitor_started = False
_preview_monitor_lock = threading.Lock()
_PREFETCH_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".psd", ".psb", ".dng",
    ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".heic", ".heif",
    ".avif", ".mov", ".mp4", ".m4v",
}
_PHOTO_EXTENSIONS = IMAGE_EXTENSIONS | PSD_EXTENSIONS | RAW_EXTENSIONS | {".heic", ".heif", ".avif"}
_VIDEO_EXTENSIONS = VIDEO_EXTENSIONS


class _Signals(QObject):
    ready = Signal(str, float, object)
    failed = Signal(str, str)
    updated = Signal(str, str)
    profile_ready = Signal(str, str, str, str)

    @Slot(str, float, object)
    def deliver(self, path, mtime, image):
        _deliver(path, mtime, image)


def _signal_bus():
    global _signals
    if _signals is None:
        _signals = _Signals()
        _signals.ready.connect(_signals.deliver)
    return _signals


@lru_cache(maxsize=4096)
def _managed_directory(directory: str, epoch: int) -> tuple[Path, Path] | None:
    """Mémorise l'association par dossier, jamais par photo ni par peinture."""
    try:
        current = Path(directory).resolve()
        while True:
            marker = current / MARKER
            if marker.is_file():
                data = json.loads(marker.read_text(encoding="utf-8"))
                catalog = Path(data["catalog"]).resolve()
                return current, catalog
            parent = current.parent
            if parent == current:
                return None
            current = parent
    except (OSError, ValueError, KeyError, TypeError):
        return None


def managed_folder(path: Path) -> tuple[Path, Path] | None:
    """Retourne (dossier Lightroom, catalogue) pour un fichier sous un dossier associé."""
    directory = os.path.dirname(os.path.abspath(str(path)))
    return _managed_directory(directory, int(time.monotonic() // 30))


def is_managed(path: Path) -> bool:
    return managed_folder(path) is not None


def _cache_root(catalog: Path) -> Path:
    key = hashlib.sha256(os.path.normcase(str(catalog)).encode("utf-8")).hexdigest()[:20]
    root = DATA_DIR / "lightroom" / key
    for name in ("requests", "replies", "images", "errors"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _write_connection(root: Path, catalog: Path):
    PLUGIN.mkdir(parents=True, exist_ok=True)
    content = "\n".join(str(p).encode("utf-8").hex() for p in (root, catalog)) + "\n"
    temp = PLUGIN / "connection.tmp"
    temp.write_text(content, encoding="ascii")
    os.replace(temp, PLUGIN / "connection.txt")


def _catalog_photo(catalog: Path, path: Path) -> dict | None:
    stamp = []
    for part in (catalog, Path(str(catalog) + "-wal")):
        try:
            stat = part.stat()
            stamp.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            stamp.append(None)
    cache_key = (os.path.normcase(str(catalog)), os.path.normcase(os.path.abspath(str(path))))
    cached = _metadata_cache.get(cache_key)
    if cached is not None and (cached[0] == tuple(stamp) or time.monotonic() - cached[2] < 1.5):
        return cached[1]
    def read_photo(db):
        db.execute("PRAGMA query_only=ON")
        rows = db.execute("""SELECT i.id_global,i.id_local,r.absolutePath,d.pathFromRoot,
            f.idx_filename,i.rating,i.colorLabels,i.pick,i.fileFormat,i.developSettingsIDCache,f.modTime,i.orientation
            FROM Adobe_images i JOIN AgLibraryFile f ON f.id_local=i.rootFile
            JOIN AgLibraryFolder d ON d.id_local=f.folder
            JOIN AgLibraryRootFolder r ON r.id_local=d.rootFolder
            WHERE f.idx_filename=? COLLATE NOCASE""", (Path(path).name,))
        wanted = os.path.normcase(os.path.abspath(str(path)))
        photo = None
        for row in rows:
            full = Path(row[2]) / row[3] / row[4]
            if os.path.normcase(os.path.abspath(str(full))) == wanted:
                photo = {"uuid": str(row[0]), "local_id": int(row[1]), "path": str(full),
                         "rating": int(row[5] or 0), "label": str(row[6] or ""),
                         "pick": int(row[7] or 0), "format": str(row[8] or ""),
                         "revision": f"{row[9]}:{row[10]}", "orientation": str(row[11] or "AB")}
                break
        if photo is not None:
            photo["keywords"] = [str(row[0]) for row in db.execute("""SELECT k.name
                FROM AgLibraryKeywordImage ki JOIN AgLibraryKeyword k ON k.id_local=ki.tag
                WHERE ki.image=?""", (photo["local_id"],)) if row[0]]
        return photo

    try:
        with closing(sqlite3.connect(catalog.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
            photo = read_photo(db)
    except sqlite3.OperationalError:
        # Un catalogue fermé peut rester en mode WAL sans fichier -shm. Sur un
        # emplacement en lecture seule, SQLite ne peut alors pas créer ce fichier.
        # Le mode immutable lit le catalogue principal sans modifier son dossier.
        if Path(str(catalog) + "-wal").exists():
            raise
        with closing(sqlite3.connect(catalog.resolve().as_uri() + "?mode=ro&immutable=1", uri=True,
                                     timeout=3)) as db:
            photo = read_photo(db)
    _metadata_cache[cache_key] = (tuple(stamp), photo, time.monotonic())
    return photo


def folder_media_counts(folders) -> dict[str, tuple[int, int]]:
    """Compte les médias référencés dans Lightroom, récursivement par dossier.

    Le catalogue reste la seule source du compteur ; aucun parcours du disque
    des photos n'est lancé à l'ouverture d'une colonne.
    """
    grouped: dict[str, tuple[Path, list[Path]]] = {}
    for folder in folders:
        folder = Path(folder)
        try:
            target = folder.resolve()
            association = managed_folder(target / "__pipeline_count_target__")
            if association is None:
                continue
            key = os.path.normcase(str(association[1]))
            grouped.setdefault(key, (association[1], []))[1].append(target)
        except (OSError, ValueError):
            continue

    result: dict[str, tuple[int, int]] = {}
    for catalog, targets in grouped.values():
        counts = {str(target): [0, 0] for target in targets}
        try:
            with closing(sqlite3.connect(catalog.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
                db.execute("PRAGMA query_only=ON")
                roots = db.execute("SELECT id_local,absolutePath FROM AgLibraryRootFolder")
                for root_id, root_text in roots:
                    root = Path(root_text).resolve()
                    # Un dossier demandé peut être sous la racine cataloguée,
                    # ou le raccourci peut contenir cette racine.
                    relatives: dict[str, list[Path]] = {}
                    query_relatives: dict[str, str] = {}
                    for target in targets:
                        try:
                            relative = "" if target == root else target.relative_to(root).as_posix().strip("/")
                        except ValueError:
                            try:
                                root.relative_to(target)
                            except ValueError:
                                continue
                            relative = ""
                        folded = relative.casefold()
                        relatives.setdefault(folded, []).append(target)
                        query_relatives.setdefault(folded, relative)
                    if not relatives:
                        continue
                    conditions = []
                    params: list = [root_id]
                    for relative in query_relatives.values():
                        if not relative:
                            conditions = ["1=1"]
                            params = [root_id]
                            break
                        conditions.append("(trim(d.pathFromRoot,'/')=? OR "
                                          "substr(trim(d.pathFromRoot,'/'),1,length(?)+1)=? || '/')")
                        params.extend((relative, relative, relative))
                    # SQLite limite le nombre de paramètres : une racine qui
                    # possède beaucoup de dossiers est lue en lots.
                    if len(params) > 900:
                        conditions, params = ["1=1"], [root_id]
                    rows = db.execute(
                        "SELECT d.pathFromRoot,f.idx_filename FROM AgLibraryFolder d "
                        "JOIN AgLibraryFile f ON f.folder=d.id_local "
                        "WHERE d.rootFolder=? AND (" + " OR ".join(conditions) + ")",
                        tuple(params),
                    )
                    for relative_folder, filename in rows:
                        extension = Path(str(filename)).suffix.casefold()
                        media = 0 if extension in _PHOTO_EXTENSIONS else 1 if extension in _VIDEO_EXTENSIONS else -1
                        if media < 0:
                            continue
                        parts = str(relative_folder or "").strip("/").split("/") if relative_folder else []
                        for count in range(len(parts) + 1):
                            relative = "/".join(parts[:count]).casefold()
                            for target in relatives.get(relative, ()):
                                counts[str(target)][media] += 1
        except (OSError, sqlite3.Error, ValueError):
            continue  # catalogue inaccessible : ne pas afficher un faux zéro
        result.update({key: (value[0], value[1]) for key, value in counts.items()})
    return result


def attributes(path: Path) -> dict | None:
    """Attributs Lightroom sous les clés du système de planche de l'application."""
    association = managed_folder(path)
    if association is None:
        return None
    photo = _catalog_photo(association[1], path)
    if photo is None:
        return {"rating": 0, "color": 0, "keywords": [], "status": ""}
    color_names = {
        "red": 1, "rouge": 1,
        "yellow": 2, "jaune": 2,
        "green": 3, "vert": 3,
        "blue": 4, "bleu": 4,
        "purple": 5, "pourpre": 5, "violet": 5,
    }
    def normalized_label(value):
        text = unicodedata.normalize("NFKD", str(value or "").casefold())
        return "".join(char for char in text if not unicodedata.combining(char)).strip()

    label = normalized_label(photo["label"])
    color = color_names.get(label, 0)
    try:
        status = json.loads((_cache_root(association[1]) / "status.json").read_text(encoding="utf-8"))
        if os.path.normcase(status.get("catalog", "")) == os.path.normcase(str(association[1])):
            # Le SDK retourne une table {couleur standard: libellé utilisateur}, pas l'inverse.
            for color_name, label_name in status.get("labels", {}).items():
                if normalized_label(label_name) == label:
                    color = color_names.get(normalized_label(color_name), 0)
                    break
    except (OSError, ValueError, TypeError):
        pass
    return {"rating": photo["rating"], "color": color, "keywords": photo.get("keywords", []),
            "status": {1: "keep", -1: "delete"}.get(photo["pick"], "")}


def orientation(path: Path) -> str | None:
    """Orientation choisie dans le catalogue Lightroom, même sans proxy disponible."""
    association = managed_folder(path)
    if association is None:
        return None
    try:
        photo = _catalog_photo(association[1], path)
    except (OSError, sqlite3.Error, ValueError):
        return None
    return photo.get("orientation") if photo is not None else None


def orient_image(image: QImage, code: str | None) -> QImage:
    """Applique les mêmes rotations/miroirs Lightroom à une image originale."""
    from PySide6.QtGui import QTransform
    turns = {"AB": 0, "BC": 90, "CD": 180, "DA": 270}
    mirrors = {"BA": (True, False), "DC": (False, True)}
    if code in turns:
        return image if turns[code] == 0 else image.transformed(QTransform().rotate(turns[code]))
    if code in mirrors:
        return image.mirrored(*mirrors[code])
    if code == "CB":
        return image.transformed(QTransform().rotate(90)).mirrored(True, False)
    if code == "AD":
        return image.transformed(QTransform().rotate(270)).mirrored(True, False)
    return image


def _lightroom_preview_path(catalog: Path, image_id: int, max_dimension: int | None = None
                            ) -> tuple[Path, str, str, str] | None:
    """Retrouve le niveau d'aperçu Lightroom demandé et son orientation."""
    store = catalog.parent / f"{catalog.stem} Previews.lrdata"
    database = store / "previews.db"
    stamp = []
    for part in (database, Path(str(database) + "-wal")):
        try:
            info = part.stat()
            stamp.append((info.st_mtime_ns, info.st_size))
        except OSError:
            stamp.append(None)
    if stamp[0] is None:
        return None
    key = (os.path.normcase(str(catalog)), image_id, max_dimension)
    cached = _preview_path_cache.get(key)
    if cached is not None and cached[0] == tuple(stamp):
        entry = cached[1]
        return entry if entry is not None and entry[0].is_file() else None
    result = None
    try:
        db = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            db.execute("PRAGMA query_only=ON")
            entry = db.execute("SELECT uuid,digest,orientation FROM ImageCacheEntry WHERE imageId=?",
                               (image_id,)).fetchone()
            if entry is not None:
                uuid, digest, orientation = entry
                if (re.fullmatch(r"[0-9a-fA-F-]{36}", uuid or "")
                        and re.fullmatch(r"[0-9a-fA-F]{32}", digest or "")):
                    dimensions = [int(row[0]) for row in db.execute(
                        """SELECT longDimension FROM PyramidLevel
                        WHERE uuid=? AND digest=? ORDER BY longDimension DESC""", (uuid, digest))]
                    if max_dimension is not None:
                        suitable = [size for size in dimensions if size <= max_dimension]
                        dimensions = sorted(suitable, reverse=True) if suitable else sorted(dimensions)
                    folder = store / uuid[0] / uuid[:4]
                    for dimension in dimensions:
                        candidate = folder / f"{uuid}-{digest}_{dimension}"
                        if candidate.is_file():
                            result = (candidate, str(orientation or "AB"), uuid, digest)
                            break
        finally:
            db.close()
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return None
    _preview_path_cache[key] = (tuple(stamp), result)
    return result


def _oriented_preview_path(source: Path, orientation: str, uuid: str, digest: str,
                           catalog: Path) -> Path:
    turns = {"AB": 0, "BC": 90, "CD": 180, "DA": 270}
    mirrors = {"BA": (True, False), "DC": (False, True)}
    if orientation in turns and turns[orientation] == 0:
        return source
    # Chaque niveau de la pyramide doit avoir son propre fichier : sinon le
    # 320 px orienté est réutilisé à la place du grand aperçu en focus.
    dimension = source.name.rsplit("_", 1)[-1]
    target = _cache_root(catalog) / "images" / f"{uuid}-{digest}-{orientation}-{dimension}.jpg"
    if target.is_file():
        return target
    from PySide6.QtGui import QImageReader
    reader = QImageReader(str(source))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        return source
    if orientation not in turns and orientation not in mirrors and orientation not in ("CB", "AD"):
        return source
    image = orient_image(image, orientation)
    temp = target.with_name(target.stem + ".tmp.jpg")
    if image.save(str(temp), "JPEG", 95):
        try:
            os.replace(temp, target)
            return target
        except OSError:
            temp.unlink(missing_ok=True)
    return source


def proxy_path(path: Path, max_dimension: int | None = None) -> Path | None:
    association = managed_folder(path)
    if association is None:
        return None
    photo = _catalog_photo(association[1], path)
    if photo is None:
        return None
    lightroom_preview = _lightroom_preview_path(association[1], photo["local_id"], max_dimension)
    # Le SDK peut avoir produit un JPEG retouche bien plus grand que le seul
    # niveau present dans Previews.lrdata (parfois 242 px). La visionneuse doit
    # retrouver ce rendu, meme si la base de pyramide contient encore sa vignette.
    rendered = _lightroom_request_path(path, photo, association[1])
    rendered_size = QImageReader(str(rendered)).size() if rendered.is_file() else None
    if rendered_size is not None and rendered_size.isValid():
        # Ce nom contient la révision de développement actuelle. Une pyramide
        # plus grande peut dater d'avant la retouche ; la couleur prime.
        with _lock:
            _preview_origins[str(path)] = "lightroom"
        return rendered
    if lightroom_preview is not None:
        source, orientation, uuid, digest = lightroom_preview
        proxy = _oriented_preview_path(source, orientation, uuid, digest, association[1])
        # Le proxy peut être consulté directement par l'inspecteur ou la
        # visionneuse, sans passer par _fetch. Enregistrer aussi cette origine
        # pour que l'interface puisse identifier l'image réellement affichée.
        with _lock:
            _preview_origins[str(path)] = "lightroom"
        return proxy
    revision = hashlib.sha256(photo["revision"].encode("utf-8")).hexdigest()[:10]
    identity = os.path.normcase(os.path.abspath(str(path))) + ":" + revision
    name = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:28] + ".jpg"
    proxy = _cache_root(association[1]) / "images" / name
    try:
        if proxy.is_file():
            with _lock:
                _preview_origins[str(path)] = "application"
    except OSError:
        pass
    return proxy


def ensure_large_preview(path: Path, width: int, height: int) -> None:
    """Demande au SDK un rendu retouche assez grand pour l'image en focus."""
    path = Path(path)
    if path.suffix.casefold() not in _PHOTO_EXTENSIONS:
        return
    key = os.path.normcase(os.path.abspath(str(path)))
    with _lock:
        if key in _large_preview_pending:
            return
        _large_preview_pending.add(key)
    _pool.submit(_check_large_preview, path, max(1, width), max(1, height), key)


def _check_large_preview(path: Path, width: int, height: int, key: str) -> None:
    try:
        association = managed_folder(path)
        if association is None or not _plugin_is_live(association[1]):
            return
        photo = _catalog_photo(association[1], path)
        if photo is None:
            return
        revision_key = (key, str(photo["revision"]))
        with _lock:
            if time.monotonic() < _large_preview_retry_after.get(revision_key, 0):
                return
        # Le SDK ne peut pas fournir davantage que le JPEG qu'il a deja rendu
        # pour cette revision : ne pas lui redemander la meme photo toutes les 10 s.
        rendered = _lightroom_request_path(path, photo, association[1])
        if rendered.is_file() and QImageReader(str(rendered)).size().isValid():
            return
        proxy = proxy_path(path)
        size = QImageReader(str(proxy)).size() if proxy is not None else None
        if size is not None and size.isValid() and min(
            width / max(1, size.width()), height / max(1, size.height())
        ) <= 1.0:
            return
        request_key = (os.path.normcase(str(path.resolve())), os.path.normcase(str(association[1])))
        with _lock:
            if request_key in _pending:
                return  # la demande automatique en cours peut déjà produire le grand JPEG
            _large_preview_retry_after[revision_key] = time.monotonic() + 30
        create_preview(path)
    except (OSError, ValueError, sqlite3.Error):
        return
    finally:
        with _lock:
            _large_preview_pending.discard(key)


def preview_pixmap(path: Path, mtime: float) -> QPixmap | None:
    association = managed_folder(path)
    if association is None:
        return None
    import previews
    cached = previews._file_image_cache.get(str(path))
    if cached is not None and cached[0] == mtime and str(path) in _displayed_from:
        if _preview_origins.get(str(path)) == "application":
            _request(path, mtime, association[1])
        return cached[1]
    # La recherche SQLite et le décodage JPEG restent sur le fil de fond.
    _request(path, mtime, association[1])
    return None


def preview_origin(path: Path) -> str | None:
    """Origine de l'aperçu actuellement affiché : Lightroom ou application."""
    return _preview_origins.get(str(path))


def develop_profile(path: Path) -> tuple[str, str] | None:
    """Dernier profil de développement reçu pour cette photo, s'il existe."""
    cached = _develop_profiles.get(os.path.normcase(os.path.abspath(str(path))))
    return (cached[1], cached[2]) if cached else None


def request_develop_profile(path: Path) -> None:
    """Lit le profil de développement de cette photo via le module SDK Lightroom."""
    path = Path(path)
    association = managed_folder(path)
    if association is None:
        return
    key = os.path.normcase(os.path.abspath(str(path)))
    with _lock:
        if key in _profile_pending:
            return
        _profile_pending.add(key)
    _pool.submit(_read_develop_profile, path, association[1], key)


def _read_develop_profile(path: Path, catalog: Path, key: str) -> None:
    request_dir = reply_dir = None
    ident = None
    try:
        photo = _catalog_photo(catalog, path)
        if photo is None:
            raise ValueError("Photo absente du catalogue Lightroom associé.")
        revision = str(photo["revision"])
        cached = _develop_profiles.get(key)
        if cached and cached[0] == revision:
            _signal_bus().profile_ready.emit(str(path), cached[1], cached[2], "")
            return
        root = _cache_root(catalog)
        if not _plugin_is_live(catalog):
            raise RuntimeError("Lightroom ou son module Pipeline Browser n’est pas actif.")
        _write_connection(root, catalog)
        request_dir = root / "requests"
        reply_dir = root / "replies"
        ident = f"{time.time_ns():020d}_{hashlib.sha1(str(path).encode()).hexdigest()[:8]}"
        command = {"id": ident, "op": "profile", "uuid": photo["uuid"], "catalog": str(catalog)}
        fields = ("id", "op", "uuid", "field", "before", "value", "target", "collection", "catalog")
        line = "\t".join(str(command.get(name, "")).encode("utf-8").hex() for name in fields)
        temp = request_dir / f"{ident}.tmp"
        temp.write_text(line + "\n", encoding="ascii")
        os.replace(temp, request_dir / f"{ident}.req")
        reply = reply_dir / f"{ident}.json"
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and not reply.is_file():
            time.sleep(.2)
        if not reply.is_file():
            raise TimeoutError("Lightroom n’a pas répondu à la lecture du profil.")
        response = json.loads(reply.read_text(encoding="utf-8"))
        if response.get("error"):
            raise RuntimeError(response["error"])
        profile = str(response.get("profile") or "").strip()
        base_profile = str(response.get("baseProfile") or "").strip()
        _develop_profiles[key] = (revision, profile, base_profile)
        _signal_bus().profile_ready.emit(str(path), profile, base_profile, "")
    except Exception as exc:
        _signal_bus().profile_ready.emit(str(path), "", "", str(exc))
    finally:
        if reply_dir is not None and ident is not None:
            (reply_dir / f"{ident}.json").unlink(missing_ok=True)
        if request_dir is not None and ident is not None:
            (request_dir / f"{ident}.req").unlink(missing_ok=True)
        with _lock:
            _profile_pending.discard(key)


def _application_preview_path(path: Path, mtime: float, catalog: Path) -> Path:
    identity = f"application:{os.path.normcase(os.path.abspath(str(path)))}:{mtime}"
    name = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32] + ".jpg"
    return _cache_root(catalog) / "images" / name


def _lightroom_request_path(path: Path, photo: dict, catalog: Path) -> Path:
    revision = hashlib.sha256(photo["revision"].encode("utf-8")).hexdigest()[:10]
    identity = os.path.normcase(os.path.abspath(str(path))) + ":" + revision
    name = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:28] + ".jpg"
    return _cache_root(catalog) / "images" / name


def _plugin_is_live(catalog: Path) -> bool:
    """N'attend pas 20 s un retour SDK si le module Lightroom ne surveille pas."""
    try:
        status = json.loads((_cache_root(catalog) / "status.json").read_text(encoding="utf-8"))
        return (os.path.normcase(status.get("catalog", "")) == os.path.normcase(str(catalog))
                and abs(time.time() - float(status.get("time", 0))) <= 5)
    except (OSError, ValueError, TypeError):
        return False


def _load_or_create_application_preview(path: Path, mtime: float, catalog: Path) -> QImage:
    """Produit le repli local, même si la photo n'est pas encore dans le catalogue."""
    app_proxy = _application_preview_path(path, mtime, catalog)
    image = QImage(str(app_proxy)) if app_proxy.is_file() else QImage()
    if image.isNull():
        import previews
        if path.suffix.casefold() in VIDEO_EXTENSIONS:
            image = previews._decode_video_frame(path, previews.FILE_IMAGE_CACHE_MAX_DIM)
        else:
            image = previews._decode_2d_image(path, previews.FILE_IMAGE_CACHE_MAX_DIM)
        if image is not None and not image.isNull():
            app_proxy.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(app_proxy), "JPEG", 92)
    return image if image is not None else QImage()


def _emit_preview(path: str, mtime: float, image: QImage) -> None:
    """Garde les aperçus des colonnes petits ; le focus lit le grand proxy séparément."""
    if image is None or image.isNull():
        return
    import previews
    side = previews.FILE_IMAGE_CACHE_MAX_DIM
    if max(image.width(), image.height()) > side:
        image = image.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    _signal_bus().ready.emit(path, mtime, image)


def _monitor_application_previews() -> None:
    """Remplace les replis locaux dès qu'un aperçu apparaît dans le cache Lightroom."""
    while True:
        time.sleep(6)
        _poll_automatic_requests()
        with _lock:
            candidates = [key for key, origin in list(_preview_origins.items())[-64:]
                          if origin == "application"]
        for path_text in candidates:
            try:
                path = Path(path_text)
                association = managed_folder(path)
                if association is None:
                    continue
                photo = _catalog_photo(association[1], path)
                if photo is None:
                    continue
                entry = _lightroom_preview_path(association[1], photo["local_id"])
                rendered = _lightroom_request_path(path, photo, association[1])
                if entry is None and not rendered.is_file():
                    continue
                proxy = proxy_path(path)
                if proxy is None:
                    continue
                image = QImage(str(proxy))
                if image.isNull():
                    continue
                _application_preview_path(path, path.stat().st_mtime, association[1]).unlink(missing_ok=True)
                with _lock:
                    _preview_origins[path_text] = "lightroom"
                    _displayed_from.add(path_text)
                _emit_preview(path_text, path.stat().st_mtime, image)
            except (OSError, ValueError, sqlite3.Error):
                continue


def _poll_automatic_requests() -> None:
    """Récolte les réponses SDK sans immobiliser les workers de préchargement."""
    with _lock:
        waiting = list(_automatic_requests.items())
    for key, (path, mtime, catalog, rendered, ident, started) in waiting:
        try:
            root = _cache_root(catalog)
            reply = root / "replies" / f"{ident}.json"
            response = json.loads(reply.read_text(encoding="utf-8")) if reply.is_file() else None
            image = QImage(str(rendered)) if rendered.is_file() else QImage()
            if response is None and time.monotonic() - started < _AUTO_TIMEOUT:
                continue
            if response is not None and response.get("error"):
                error = str(response["error"])
            elif image.isNull():
                error = ("Le module Lightroom n'a pas produit d'image."
                         if response is not None else "Délai de rendu Lightroom dépassé.")
            else:
                error = None
            with _lock:
                current = _automatic_requests.get(key)
                if current is None or current[4] != ident:
                    continue
                del _automatic_requests[key]
                if error:
                    _preview_errors[str(path)] = error
                    _retry_after[key] = time.monotonic() + 60
                else:
                    _preview_errors.pop(str(path), None)
                    _preview_origins[str(path)] = "lightroom"
                    _displayed_from.add(str(path))
            if not error:
                _application_preview_path(path, mtime, catalog).unlink(missing_ok=True)
                _emit_preview(str(path), mtime, image)
            for file in (root / "requests" / f"{ident}.req",
                         root / "requests" / f"{ident}.json", reply):
                file.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            continue


def _ensure_preview_monitor() -> None:
    global _preview_monitor_started
    with _preview_monitor_lock:
        if _preview_monitor_started:
            return
        _preview_monitor_started = True
    threading.Thread(target=_monitor_application_previews, name="LightroomPreviewMonitor",
                     daemon=True).start()


def _request(path: Path, mtime: float, catalog: Path):
    key = (os.path.normcase(str(path.resolve())), os.path.normcase(str(catalog)))
    with _lock:
        if (key in _pending or key in _automatic_requests
                or len(_automatic_requests) >= _AUTO_MAX_IN_FLIGHT
                or time.monotonic() < _retry_after.get(key, 0)):
            return
        _pending.add(key)
    _pool.submit(_fetch, path, mtime, catalog, key)


def request_previews(paths, limit: int = 36) -> None:
    """Amorce les premières lignes visibles, sans parcourir tout le dossier."""
    candidates = tuple(dict.fromkeys(Path(path) for path in paths
                                     if Path(path).suffix.casefold() in _PREFETCH_EXTENSIONS))[:limit]
    if candidates:
        _pool.submit(_prefetch_batch, candidates)


def _prefetch_batch(paths: tuple[Path, ...]):
    for path in paths:
        try:
            association = managed_folder(path)
            if association is not None and path.is_file():
                _request(path, path.stat().st_mtime, association[1])
        except (OSError, ValueError, sqlite3.Error):
            continue


def create_preview(path: Path) -> None:
    """Force Lightroom à recalculer puis renvoyer l'aperçu de cette photo."""
    path = Path(path)
    association = managed_folder(path)
    if association is None:
        return
    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        _signal_bus().failed.emit(str(path), f"Lecture de la photo impossible : {exc}")
        return
    key = (os.path.normcase(str(path.resolve())), os.path.normcase(str(association[1])))
    with _lock:
        if key in _pending:
            # Une prélecture automatique peut déjà occuper la photo. Ne pas
            # perdre le clic : le recalcul explicite partira juste après.
            _force_after_pending.add(key)
            return
        _pending.add(key)
    _pool.submit(_fetch, path, mtime, association[1], key, True)


def write_attributes(path: Path, changes: dict) -> None:
    """Demande au module SDK d'écrire les attributs dans le catalogue actif, sans bloquer l'interface."""
    association = managed_folder(path)
    if association is None:
        return
    photo = _catalog_photo(association[1], path)
    if photo is None:
        _signal_bus().failed.emit(str(path), "Cette photo n’est pas référencée dans le catalogue Lightroom choisi.")
        return
    color_names = ("", "red", "yellow", "green", "blue", "purple")
    status_values = {"": "0", "keep": "1", "delete": "-1"}
    commands = []
    if "rating" in changes:
        rating = int(changes["rating"] or 0)
        commands.append(("rating", str(rating) if rating else ""))
    if "color" in changes:
        index = int(changes["color"] or 0)
        commands.append(("color", color_names[index] if 0 <= index < len(color_names) else ""))
    if "status" in changes:
        commands.append(("status", status_values.get(str(changes["status"]), "0")))
    if "keywords" in changes:
        words = changes["keywords"] or []
        commands.append(("keywords", "\n".join(str(word).strip() for word in words
                                                if str(word).strip() and "\n" not in str(word))))
    if commands:
        _write_connection(_cache_root(association[1]), association[1])
        for field, value in commands:
            ident = f"{time.time_ns():020d}_{hashlib.sha1((str(path) + field).encode()).hexdigest()[:8]}"
            _pool.submit(_write_attribute, path, association[1], photo["uuid"], field, value, ident)


def open_in_lightroom(path: Path) -> None:
    """Demande au module Lightroom de sélectionner la photo et d'ouvrir Développement."""
    try:
        association = managed_folder(path)
        if association is None:
            raise RuntimeError("Cette photo n’est pas associée à un catalogue Lightroom.")
        photo = _catalog_photo(association[1], path)
        if photo is None:
            raise RuntimeError("Cette photo n’est pas référencée dans le catalogue Lightroom associé.")
        root = _cache_root(association[1])
        _write_connection(root, association[1])
        ident = f"{time.time_ns():020d}_{hashlib.sha1(str(path).encode()).hexdigest()[:8]}"
        _pool.submit(_open_in_lightroom, path, association[1], photo["uuid"], root, ident)
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        _signal_bus().failed.emit(str(path), f"Ouverture dans Lightroom : {exc}")


def _open_in_lightroom(path: Path, catalog: Path, uuid: str, root: Path, ident: str):
    request_dir = root / "requests"
    reply = root / "replies" / f"{ident}.json"
    try:
        command = {"id": ident, "op": "open", "uuid": uuid,
                   "target": str(path), "catalog": str(catalog)}
        fields = ("id", "op", "uuid", "field", "before", "value", "target", "collection", "catalog")
        line = "\t".join(str(command.get(name, "")).encode("utf-8").hex() for name in fields)
        temp = request_dir / f"{ident}.tmp"
        temp.write_text(line + "\n", encoding="ascii")
        os.replace(temp, request_dir / f"{ident}.req")
        # Si Lightroom est fermé, ouvrir directement le catalogue associé : le module
        # externe récupérera la demande dès son démarrage.
        launched_at = time.time()
        running = False
        try:
            tasklist = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Lightroom.exe", "/NH"],
                capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            running = "lightroom.exe" in tasklist.stdout.casefold()
        except (OSError, subprocess.SubprocessError):
            pass
        if not running:
            executable = _lightroom_executable()
            if executable is None:
                raise RuntimeError("Lightroom Classic est introuvable sur cet ordinateur.")
            try:
                subprocess.Popen([str(executable), str(catalog)], cwd=str(executable.parent),
                                 close_fds=True)
            except OSError as exc:
                raise RuntimeError(f"Impossible de lancer Lightroom : {exc}") from exc
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not reply.is_file():
            status_path = root / "status.json"
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
                if (float(status.get("time", 0) or 0) >= launched_at
                        and os.path.normcase(status.get("expectedCatalog", "")) == os.path.normcase(str(catalog))
                        and os.path.normcase(status.get("catalog", "")) != os.path.normcase(str(catalog))):
                    raise RuntimeError("Lightroom est ouvert sur un autre catalogue. Ouvre le catalogue associé puis réessaie.")
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError):
                pass
            time.sleep(.2)
        if not reply.is_file():
            try:
                last_status = json.loads((root / "status.json").read_text(encoding="utf-8"))
                plugin_active = float(last_status.get("time", 0) or 0) >= launched_at - 2
            except (OSError, ValueError, TypeError):
                plugin_active = False
            if not plugin_active:
                raise TimeoutError("Le module externe Lightroom ne répond pas. Dans Lightroom Classic, "
                                   "vérifie Bibliothèque > Modules externes supplémentaires > "
                                   "État de la connexion Pipeline Browser.")
            raise TimeoutError("Lightroom a reçu la connexion mais n’a pas traité cette photo. "
                               "Vérifie le catalogue ouvert et réessaie.")
        response = json.loads(reply.read_text(encoding="utf-8"))
        if response.get("error"):
            raise RuntimeError(response["error"])
        if response.get("uuid") != uuid:
            raise RuntimeError("Lightroom a répondu pour une autre photo que celle demandée.")
        if response.get("module") != "develop":
            raise RuntimeError("Lightroom n’a pas confirmé le mode Développement.")
        opened_path = response.get("path")
        if opened_path and os.path.normcase(os.path.abspath(opened_path)) != os.path.normcase(os.path.abspath(str(path))):
            raise RuntimeError(f"Lightroom a ouvert une autre photo : {opened_path}")
        opened_folder = response.get("folder")
        if not opened_folder or os.path.normcase(os.path.abspath(opened_folder)) != os.path.normcase(os.path.abspath(str(path.parent))):
            raise RuntimeError("Lightroom n’a pas confirmé le dossier de la photo.")
        _signal_bus().updated.emit(str(path), "open")
    except Exception as exc:
        _signal_bus().failed.emit(str(path), f"Ouverture dans Lightroom : {exc}")
    finally:
        reply.unlink(missing_ok=True)
        (request_dir / f"{ident}.req").unlink(missing_ok=True)


def _lightroom_executable() -> Path | None:
    """Trouve Lightroom Classic via l'association .lrcat, puis ses emplacements usuels."""
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ".lrcat") as key:
            progid, _ = winreg.QueryValueEx(key, None)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{progid}\\shell\\open\\command") as key:
            command, _ = winreg.QueryValueEx(key, None)
        match = re.match(r'\s*"([^\"]+\.exe)"', command, re.IGNORECASE)
        if match:
            candidate = Path(match.group(1))
            if candidate.is_file():
                return candidate
    except (OSError, ValueError, TypeError):
        pass
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidate = Path(base) / "Adobe" / "Adobe Lightroom Classic" / "Lightroom.exe"
            if candidate.is_file():
                return candidate
    return None


def _write_attribute(path: Path, catalog: Path, uuid: str, field: str, value: str, ident: str):
    root = _cache_root(catalog)
    request_dir = root / "requests"
    reply = root / "replies" / f"{ident}.json"
    try:
        command = {"id": ident, "op": "set", "uuid": uuid, "field": field,
                   "value": value, "catalog": str(catalog)}
        fields = ("id", "op", "uuid", "field", "before", "value", "target", "collection", "catalog")
        line = "\t".join(str(command.get(name, "")).encode("utf-8").hex() for name in fields)
        temp = request_dir / f"{ident}.tmp"
        temp.write_text(line + "\n", encoding="ascii")
        os.replace(temp, request_dir / f"{ident}.req")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not reply.is_file():
            time.sleep(.2)
        if not reply.is_file():
            raise TimeoutError("Lightroom n’a pas confirmé l’écriture. Vérifiez qu’il est ouvert sur le catalogue associé.")
        response = json.loads(reply.read_text(encoding="utf-8"))
        if response.get("error"):
            raise RuntimeError(response["error"])
        cache_key = (os.path.normcase(str(catalog)), os.path.normcase(os.path.abspath(str(path))))
        _metadata_cache.pop(cache_key, None)
        _signal_bus().updated.emit(str(path), field)
    except Exception as exc:
        _signal_bus().failed.emit(str(path), f"Écriture Lightroom ({field}) : {exc}")
    finally:
        reply.unlink(missing_ok=True)
        (request_dir / f"{ident}.req").unlink(missing_ok=True)


def _fetch(path: Path, mtime: float, catalog: Path, key: tuple[str, str], force: bool = False):
    request_dir = None
    ident = None
    try:
        photo = _catalog_photo(catalog, path)
        if photo is None:
            image = _load_or_create_application_preview(path, mtime, catalog)
            if image.isNull():
                raise ValueError("Cette photo n’est pas dans le catalogue Lightroom et l’application n’a pas pu la décoder.")
            with _lock:
                _preview_origins[str(path)] = "application"
                _displayed_from.add(str(path))
                _retry_after[key] = time.monotonic() + 8
            _ensure_preview_monitor()
            _emit_preview(str(path), mtime, image)
            return
        preview_entry = None if force else _lightroom_preview_path(catalog, photo["local_id"])
        rendered = _lightroom_request_path(path, photo, catalog)
        proxy = None
        if preview_entry is not None:
            source, orientation, uuid, digest = preview_entry
            proxy = _oriented_preview_path(source, orientation, uuid, digest, catalog)
        if not force and rendered.is_file() and QImageReader(str(rendered)).size().isValid():
            proxy = rendered
        if proxy is not None:
            image = QImage(str(proxy))
            if not image.isNull():
                origin = "lightroom"
                _application_preview_path(path, mtime, catalog).unlink(missing_ok=True)
            else:
                proxy = None
        if proxy is None:
            app_proxy = _application_preview_path(path, mtime, catalog)
            image = _load_or_create_application_preview(path, mtime, catalog)
            origin = "application"
            if image is None or image.isNull():
                image = QImage()
            if not image.isNull():
                _preview_origins[str(path)] = "application"
                _displayed_from.add(str(path))
                _emit_preview(str(path), mtime, image)
                _ensure_preview_monitor()
        if (force or proxy is None) and not _plugin_is_live(catalog):
            _preview_errors[str(path)] = "Module Lightroom inactif pendant la demande d'aperçu."
            if image.isNull():
                raise TimeoutError("Aucun aperçu Lightroom en cache et le module Lightroom est arrêté.")
            with _lock:
                _retry_after[key] = time.monotonic() + 8
            return
        if force or proxy is None:
            root = _cache_root(catalog)
            _write_connection(root, catalog)
            request_dir = root / "requests"
            ident = f"{time.time_ns():020d}_{hashlib.sha1(str(path).encode()).hexdigest()[:8]}"
            command = {"id": ident, "op": "preview", "uuid": photo["uuid"],
                       "catalog": str(catalog), "target": rendered.name}
            (request_dir / f"{ident}.json").write_text(json.dumps(command), encoding="utf-8")
            fields = ("id", "op", "uuid", "field", "before", "value", "target", "collection", "catalog")
            line = "\t".join(str(command.get(field, "")).encode("utf-8").hex() for field in fields)
            temp = request_dir / f"{ident}.tmp"
            temp.write_text(line + "\n", encoding="ascii")
            os.replace(temp, request_dir / f"{ident}.req")
            if not force:
                with _lock:
                    _automatic_requests[key] = (path, mtime, catalog, rendered, ident, time.monotonic())
                # La réponse arrivera par le moniteur ; garder la requête active
                # pendant que les autres photos peuvent être amorcées.
                _ensure_preview_monitor()
                request_dir = None
                ident = None
                return
            reply = root / "replies" / f"{ident}.json"
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not reply.is_file():
                time.sleep(.2)
            if reply.is_file():
                response = json.loads(reply.read_text(encoding="utf-8"))
                reply.unlink(missing_ok=True)
                if response.get("error"):
                    raise RuntimeError(response["error"])
                if response.get("ok") and rendered.is_file():
                    result = QImage(str(rendered))
                    if not result.isNull():
                        image = result
                        origin = "lightroom"
                        _application_preview_path(path, mtime, catalog).unlink(missing_ok=True)
                        _preview_origins[str(path)] = "lightroom"
            elif image.isNull():
                raise TimeoutError("Aucune réponse du module Lightroom. Vérifiez qu’il est chargé et que Lightroom est ouvert sur ce catalogue.")
            else:
                # L'aperçu local est un repli valide lorsque Lightroom est fermé.
                _preview_errors[str(path)] = "Aucune réponse du module Lightroom dans les 20 secondes."
                with _lock:
                    _retry_after[key] = time.monotonic() + 8
        if image.isNull():
            image = QImage(str(rendered))
        if image.isNull():
            raise ValueError("Impossible de lire l’aperçu Lightroom ou de décoder la photo originale.")
        with _lock:
            if origin == "application" and _preview_origins.get(str(path)) == "lightroom":
                return  # le contrôleur a déjà remplacé le secours par le proxy Lightroom
            _displayed_from.add(str(path))
            _preview_origins[str(path)] = origin
            if origin == "lightroom":
                _preview_errors.pop(str(path), None)
        _emit_preview(str(path), mtime, image)
    except Exception as exc:
        _preview_errors[str(path)] = str(exc)
        with _lock:
            _retry_after[key] = time.monotonic() + (8 if _preview_origins.get(str(path)) == "application" else 30)
        if _preview_origins.get(str(path)) != "application":
            _signal_bus().failed.emit(str(path), str(exc))
    finally:
        if request_dir is not None and ident is not None:
            try:
                (request_dir / f"{ident}.req").unlink(missing_ok=True)
                (request_dir / f"{ident}.json").unlink(missing_ok=True)
            except OSError:
                pass
        with _lock:
            _pending.discard(key)
            rerun_force = key in _force_after_pending
            _force_after_pending.discard(key)
        if rerun_force:
            create_preview(path)


def _deliver(path: str, mtime: float, image):
    if image is None or image.isNull():
        return
    import previews
    pixmap = QPixmap.fromImage(image)
    previews._cache_file_preview(path, mtime, pixmap)
    _displayed_from.add(path)
    previews._PREVIEW_DECODE_MANAGER.ready.emit(path, mtime, image)


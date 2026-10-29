"""Cache disque indexé, signatures, protection et nettoyage.

Carte et pièges : docs/agents/apercus.md.
"""

import config as _config
import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from config import ABC_EXTENSIONS, BLEND_EXTENSIONS, DATA_DIR, FBX_EXTENSIONS, CUBE_EXTENSIONS, HOUDINI_SCENE_EXTENSIONS, MAYA_SCENE_EXTENSIONS, OBJ_EXTENSIONS, RENDERABLE_3D_EXTENSIONS, TWO_D_IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, _STALE_PREVIEW_PATHS
from . import images as _images
from . import memory as _memory
from . import profiles as _profiles

# Ces lignes n'affichent jamais le fichier plus grand que ~200px (voir
# file_preview_size dans settings_window.py) : decoder et garder en cache
# l'image a sa resolution d'origine (une photo/rendu peut faire plusieurs
# dizaines de Mo une fois decompressee) pour une vignette de quelques
# dizaines de px serait pur gaspillage de memoire. Marge x3 par rapport au
# reglage max pour rester net sur les ecrans HiDPI et les images non carrees.
FILE_IMAGE_CACHE_MAX_DIM = 640

# _file_image_cache ci-dessus ne vit qu'en memoire : tout redemarrage de
# l'appli (ou dossier pas encore visite dans cette session) oblige a
# redecoder et reduire chaque image depuis son fichier d'origine, potentiellement
# lourd sur un partage reseau. On garde donc en plus, sur disque, une copie
# deja reduite (voir FILE_IMAGE_CACHE_MAX_DIM) de chaque image deja vue : les
# ouvertures suivantes du meme dossier n'ont plus qu'a relire ce petit fichier
# local. Nommee par hash du chemin (independant du mtime, pour retrouver et
# purger les anciennes versions perimees d'une meme image, voir
# _prune_stale_disk_cache) suivi du mtime (pour invalider automatiquement des
# qu'un fichier source change).
FILE_IMAGE_DISK_CACHE_DIR = DATA_DIR / ".pipeline_preview_cache"

# SUSPENDU a la demande de l'utilisateur (systeme a repenser) : rendus AUTOMATIQUES — le balayage
# d'inactivite (_IdlePreviewScheduler) ne rend plus rien en arriere-plan (fichiers 3D, apercus
# perimes) ; les rendus lances a la main (menu) restent.
AUTO_RENDER_ENABLED = False

# Mise en cache disque des apercus d'IMAGES (2D et videos) : REMISE a la demande de l'utilisateur
# (les originaux ne doivent pas etre relus a chaque demarrage).
IMAGE_DISK_CACHE_ENABLED = True

_IMAGE_CACHE_SUFFIXES = TWO_D_IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# La cle de cache disque ne depend que du chemin source et de son mtime :
# un changement du CODE de rendu (ex. _decode_obj_image) ne les fait pas
# bouger, donc un vieux rendu perime resterait sinon servi indefiniment tant
# que le fichier source lui-meme n'est pas retouche. A incrementer chaque
# fois que la logique de decodage/rendu change reellement (ex. le passage a
# un flat shading sans contour) pour forcer une regeneration.
_PREVIEW_CACHE_VERSION = 57

_TURNTABLE_CACHE_VERSION = 1

TURNTABLE_FRAME_COUNT = 72

TURNTABLE_EXTENSIONS = (OBJ_EXTENSIONS | ABC_EXTENSIONS | BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS
                        | HOUDINI_SCENE_EXTENSIONS)

def _cache_slug(text: str, limit: int) -> str:
    text = re.sub(r"[^0-9a-zà-ÿ._-]+", "_", text.casefold())
    text = re.sub(r"_{2,}", "_", text).strip("._ ")
    return text[:limit].rstrip("._ ") or "x"

def _cache_label(path: Path) -> str:
    """Prefixe EXPLICITE des fichiers de cache : « set » (jusqu'a 3 dossiers
    sous la racine : Type-Projet-Sous-projet) puis nom du fichier source, en
    minuscules — ex. "3d-_assets-hotrod__hotrod.abc". Permet de retrouver a
    quoi correspond un fichier du cache sans passer par les fiches JSON."""
    p = Path(str(path))
    parts = [x.casefold() for x in p.parts]
    root_parts = [x.casefold() for x in Path(str(_config.ROOT)).parts]
    if len(parts) > len(root_parts) and parts[:len(root_parts)] == root_parts:
        folders = parts[len(root_parts):-1][:3]
    else:
        anchor = p.anchor.casefold()
        folders = [x for x in parts[:-1] if x != anchor][-3:]
    set_name = "-".join(_cache_slug(x, 24) for x in folders) or "racine"
    return f"{_cache_slug(set_name, 60)}__{_cache_slug(parts[-1] if parts else '', 50)}"

def _cache_digest_of(cache_path: Path) -> str:
    """Code court (16 car.) d'un fichier de cache, ancien (40 car., sans
    prefixe) ou nouveau format (<set>__<fichier>__<code>_<mtime>)."""
    return cache_path.stem.rsplit("__", 1)[-1].split("_", 1)[0][:16]

def _cache_glob(digest: str) -> str:
    return f"*{digest[:16]}*_*.png"

class _CacheDirIndex:
    """Noms du dossier du cache disque, lus UNE fois et tenus à jour. Le dossier compte des dizaines de milliers
    d'entrées : chaque `glob` / `iterdir` y coûtait ~100 ms de Python (GIL tenu par tranches de ~16 ms), et un
    aperçu absent en déclenchait jusqu'à une dizaine (aperçus périmés, nettoyage) — de quoi faire saccader la
    lecture vidéo et ralentir les colonnes pendant que les aperçus d'un dossier se calculent. Fraîcheur : date de
    modification du dossier (changée par toute création / suppression d'entrée), relue à chaque demande ; nos
    propres écritures mettent l'index à jour (`added` / `removed`) sans tout relire."""

    MAX_AGE = 300.0
    MIN_REBUILD_GAP = 30.0

    def __init__(self):
        self._lock = threading.RLock()
        self._dir = None
        self._stamp = None
        self._built = 0.0
        self._names: list[str] = []          # triés (recherche par préfixe)
        self._by_digest: dict[str, list[str]] = {}

    @staticmethod
    def _digest(name: str) -> str | None:
        if not name.endswith(".png"):
            return None
        return name[:-4].rsplit("__", 1)[-1].split("_", 1)[0][:16]

    def _dir_stamp(self, directory: Path):
        try:
            return os.stat(directory).st_mtime_ns
        except OSError:
            return None

    def _ensure(self) -> Path:
        directory = FILE_IMAGE_DISK_CACHE_DIR
        stamp = self._dir_stamp(directory)
        age = time.monotonic() - self._built
        if directory == self._dir and stamp is not None and (
                (stamp == self._stamp and age < self.MAX_AGE) or age < self.MIN_REBUILD_GAP):
            # Dossier changé depuis la lecture (fiches JSON, images temporaires… écrites par les aperçus) : les
            # images et dossiers qui comptent sont tenus à jour par `added` / `removed` ; une relecture complète
            # pour le reste (autre programme) au plus toutes les MIN_REBUILD_GAP secondes.
            return directory
        names = []
        if stamp is not None:
            try:
                with os.scandir(directory) as entries:
                    names = [entry.name for entry in entries]
            except OSError:
                names = []
        names.sort()
        by_digest = {}
        for name in names:
            digest = self._digest(name)
            if digest:
                by_digest.setdefault(digest, []).append(name)
        self._dir, self._stamp, self._built = directory, stamp, time.monotonic()
        self._names, self._by_digest = names, by_digest
        return directory

    def warm(self):
        with self._lock:
            self._ensure()

    def has_png(self) -> bool:
        with self._lock:
            self._ensure()
            return bool(self._by_digest)

    def with_prefix(self, prefix: str) -> list[Path]:
        import bisect
        with self._lock:
            directory = self._ensure()
            i = bisect.bisect_left(self._names, prefix)
            out = []
            while i < len(self._names) and self._names[i].startswith(prefix):
                out.append(directory / self._names[i])
                i += 1
            return out

    def with_digest(self, digest: str) -> list[Path]:
        """Équivalent de `glob(_cache_glob(digest))` (images PNG de ce code de rendu)."""
        with self._lock:
            directory = self._ensure()
            return [directory / name for name in self._by_digest.get(digest[:16], ())]

    def _touched(self, path: Path, add: bool):
        import bisect
        with self._lock:
            if self._dir is None or Path(path).parent != self._dir:
                return
            name = Path(path).name
            i = bisect.bisect_left(self._names, name)
            present = i < len(self._names) and self._names[i] == name
            digest = self._digest(name)
            if add and not present:
                self._names.insert(i, name)
                if digest:
                    self._by_digest.setdefault(digest, []).append(name)
            elif not add and present:
                del self._names[i]
                if digest and name in self._by_digest.get(digest, ()):
                    self._by_digest[digest].remove(name)
            self._stamp = self._dir_stamp(self._dir)

    def added(self, path: Path):
        self._touched(path, True)

    def removed(self, path: Path):
        self._touched(path, False)

_CACHE_INDEX = _CacheDirIndex()

def _turntable_cache_path(path: Path, mtime: float, profiles_snapshot=None, render_mode: str = "low") -> Path:
    signature = _file_image_cache_signature(path, render_mode=render_mode, profiles_snapshot=profiles_snapshot)
    digest = hashlib.sha1(f"turntable:{_TURNTABLE_CACHE_VERSION}:{_PREVIEW_CACHE_VERSION}:{path.resolve()}:{mtime}:{signature}".encode()).hexdigest()
    return FILE_IMAGE_DISK_CACHE_DIR / f"{_cache_label(path)}__turntable_{digest[:16]}"

def _turntable_metadata_path(path: Path, render_mode: str = "low") -> Path:
    identity = os.path.normcase(str(path.resolve()))
    digest = hashlib.sha1((identity if render_mode == "low" else f"{identity}:high").encode()).hexdigest()
    return FILE_IMAGE_DISK_CACHE_DIR / f"{_cache_label(path)}__turntable_latest_{digest[:16]}.json"

def _turntable_work_path(destination: Path, profile: dict, render_mode: str) -> Path:
    references = {}
    for key in ("template", "lighting_hdri", "lighting"):
        if not profile.get(key):
            continue
        path = Path(__file__).resolve().parent.parent / str(profile[key])
        try:
            stat = path.stat()
            references[key] = (str(path), stat.st_mtime_ns, stat.st_size)
        except OSError:
            pass
    signature = json.dumps({"version": 2, "profile": profile, "mode": render_mode, "references": references},
                           sort_keys=True, default=str)
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
    return destination.with_name(destination.name + "_partial_" + digest)

def _turntable_frames(path: Path, mtime: float, profiles_snapshot=None, allow_stale=False,
                      render_mode: str = "low") -> list[Path]:
    directory = _turntable_cache_path(path, mtime, profiles_snapshot, render_mode)
    try:
        if not (directory / "complete.json").is_file() and allow_stale:
            directory = Path(json.loads(_turntable_metadata_path(path, render_mode).read_text(encoding="utf-8"))["cache"])
            if directory.parent.resolve() != FILE_IMAGE_DISK_CACHE_DIR.resolve():
                return []
        manifest = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
        if manifest.get("frames") != TURNTABLE_FRAME_COUNT:
            return []
        frames = [directory / f"frame_{i:03d}.png" for i in range(TURNTABLE_FRAME_COUNT)]
        return frames if all(frame.is_file() for frame in frames) else []
    except (OSError, ValueError, KeyError, TypeError):
        return []

_PREVIEW_PROTECTION_FILE = DATA_DIR / ".pipeline_protected_previews.json"

_PROTECTED_PREVIEW_PATHS: set[str] | None = None

def _protected_preview_paths() -> set[str]:
    global _PROTECTED_PREVIEW_PATHS
    if _PROTECTED_PREVIEW_PATHS is None:
        try:
            payload = json.loads(_PREVIEW_PROTECTION_FILE.read_text(encoding="utf-8"))
            _PROTECTED_PREVIEW_PATHS = {
                os.path.normcase(str(Path(value).resolve()))
                for value in payload
                if isinstance(value, str)
            }
        except (OSError, ValueError, TypeError):
            _PROTECTED_PREVIEW_PATHS = set()
    return _PROTECTED_PREVIEW_PATHS

def _is_preview_protected(path: Path) -> bool:
    return os.path.normcase(str(path.resolve())) in _protected_preview_paths()

def _set_preview_protected(path: Path, protected: bool) -> None:
    paths = _protected_preview_paths()
    key = os.path.normcase(str(path.resolve()))
    if protected:
        paths.add(key)
    else:
        paths.discard(key)
    try:
        temp_path = _PREVIEW_PROTECTION_FILE.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(sorted(paths), indent=2), encoding="utf-8")
        temp_path.replace(_PREVIEW_PROTECTION_FILE)
    except OSError:
        pass

def _file_image_cache_signature(
    path: Path, render_mode: str = "low", profiles_snapshot: dict | None = None,
) -> str:
    template_signature = ""
    suffix = path.suffix.lower()
    renderable_3d = RENDERABLE_3D_EXTENSIONS
    if suffix in renderable_3d:
        profiles = profiles_snapshot if profiles_snapshot is not None else _profiles._RENDER_PROFILES
        profile_name = "HIGH POLY" if render_mode == "high" else "LOW POLY"
        profile = profiles.get(profile_name, {})
        template_name = str(profile.get("template", "scene pour appercu.blend"))
        template_path = Path(__file__).resolve().parent.parent / "files" / template_name
        try:
            template_stat = template_path.stat()
            template_signature = f":{template_stat.st_mtime_ns}:{template_stat.st_size}"
        except OSError:
            pass
        profile_digest = hashlib.sha1(
            json.dumps(profile, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:12]
        # v3 pour les .blend : l'apercu respecte desormais la visibilite de rendu du fichier.
        render_tag = "v3" if suffix in BLEND_EXTENSIONS else "v2"
        template_signature += f":profile_render_{render_tag}:{render_mode}:{profile_digest}"
    if suffix in CUBE_EXTENSIONS:
        template_signature = ":lut:" + _images._lut_test_image_signature()
    return template_signature

def _file_image_cache_path(
    path: Path, mtime: float, version: int | None = None, signature: str | None = None,
    render_mode: str = "low", profiles_snapshot: dict | None = None,
) -> Path:
    if version is None:
        version = _PREVIEW_CACHE_VERSION
    if signature is None:
        signature = _file_image_cache_signature(path, render_mode, profiles_snapshot)
    digest = hashlib.sha1(f"{version}:{path}{signature}".encode("utf-8")).hexdigest()
    return FILE_IMAGE_DISK_CACHE_DIR / f"{_cache_label(path)}__{digest[:16]}_{int(mtime)}.png"

def _preview_cache_metadata_path(path: Path) -> Path:
    identity = hashlib.sha1(os.path.normcase(str(path.resolve())).encode("utf-8")).hexdigest()
    return FILE_IMAGE_DISK_CACHE_DIR / f"{_cache_label(path)}__preview_{identity[:16]}.json"

def delete_preview_cache(path: Path) -> int:
    """Supprime tous les apercus en cache du fichier `path` (image low/high,
    turntables, fiches, rendus partiels) sur le disque ET en memoire ; le
    fichier source n'est jamais touche. Retourne le nombre d'elements supprimes."""
    removed = 0
    key = str(path)
    for memory_cache in (_memory._file_image_cache, _memory._file_image_column_cache, _memory._file_image_high_cache):
        memory_cache.pop(key, None)
    _STALE_PREVIEW_PATHS.discard(key)
    _memory._PREVIEW_STALE_LOOKUP_MISSES.difference_update({item for item in _memory._PREVIEW_STALE_LOOKUP_MISSES if item[0] == key})
    prefix = _cache_label(path) + "__"
    try:
        entries = _CACHE_INDEX.with_prefix(prefix)
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            _CACHE_INDEX.removed(entry)
            removed += 1
        except OSError:
            pass
    return removed

def _keep_cache_digests(path: Path, mtime: float) -> tuple[set, set]:
    """(codes d'images, codes de turntables) encore valables pour `path` : LOW et HIGH,
    avec les profils manuels et automatiques courants."""
    image_codes, turntable_codes = set(), set()
    for profiles in (None, _profiles._AUTOMATIC_RENDER_PROFILES):
        for mode in ("low", "high"):
            try:
                image_codes.add(_cache_digest_of(_file_image_cache_path(path, mtime, render_mode=mode, profiles_snapshot=profiles)))
                turntable_codes.add(_turntable_cache_path(path, mtime, profiles, mode).name.split("__turntable_", 1)[1][:16])
            except (OSError, ValueError, IndexError):
                pass
    return image_codes, turntable_codes

def prune_unused_previews(path: Path, mtime: float | None = None, entries: list | None = None) -> int:
    """Supprime les images et turntables de cache de `path` devenus inutiles : ceux
    d'anciens reglages de rendu (profil, modele Blender) qui ne servent plus ni a
    l'affichage courant ni de repli « perime ». Garde LOW et HIGH actuels et la
    derniere image enregistree. Retourne le nombre d'elements supprimes."""
    prefix = _cache_label(path) + "__"
    try:
        mtime = path.stat().st_mtime if mtime is None else mtime
        names = entries if entries is not None else _CACHE_INDEX.with_prefix(prefix)
    except OSError:
        return 0
    image_codes, turntable_codes = _keep_cache_digests(path, mtime)
    keep_names = set()
    for sidecar in (_preview_cache_metadata_path(path), _turntable_metadata_path(path, "low"),
                    _turntable_metadata_path(path, "high")):
        try:
            keep_names.add(Path(json.loads(sidecar.read_text(encoding="utf-8")).get("cache", "")).name)
        except (OSError, ValueError, TypeError):
            pass
    own = [entry for entry in names if entry.name.startswith(prefix)]
    # Confirmation POSITIVE : on ne supprime que si un element courant de ce type est
    # bien present (sinon on ne sait pas distinguer l'inutile de l'unique repli).
    has_current_image = any(e.suffix == ".png" and _cache_digest_of(e) in image_codes for e in own)
    has_current_turntable = any(
        e.is_dir() and e.name[len(prefix):].startswith("turntable_") and
        e.name[len(prefix) + len("turntable_"):][:16] in turntable_codes for e in own)
    removed = 0
    for entry in own:
        if entry.name in keep_names:
            continue
        rest = entry.name[len(prefix):]
        try:
            if entry.is_dir() and rest.startswith("turntable_") and not rest.startswith("turntable_latest_"):
                code = rest[len("turntable_"):][:16]
                if has_current_turntable and code not in turntable_codes:
                    shutil.rmtree(entry)
                    _CACHE_INDEX.removed(entry)
                    removed += 1
            elif entry.suffix == ".png" and not entry.name.endswith(".tmp.png"):
                if has_current_image and _cache_digest_of(entry) not in image_codes:
                    entry.unlink()
                    _CACHE_INDEX.removed(entry)
                    removed += 1
                elif has_current_image and not entry.stem.endswith(f"_{int(mtime)}") and any(
                        other is not entry and other.suffix == ".png" and other.stem.endswith(f"_{int(mtime)}")
                        and _cache_digest_of(other) == _cache_digest_of(entry) for other in own):
                    entry.unlink()   # meme reglage, ancienne date : le rendu a jour existe deja
                    _CACHE_INDEX.removed(entry)
                    removed += 1
        except OSError:
            pass
    return removed

def sweep_preview_cache(dry_run: bool = False) -> dict:
    """Balayage complet du cache : pour chaque fichier source connu (fiches), retire ce
    qui est inutile (voir prune_unused_previews) ; si le fichier source n'existe plus
    alors que son dossier existe, retire aussi tous ses apercus. Les sources dont le
    dossier est introuvable (disque debranche) ne sont jamais touchees."""
    result = {"inutiles": 0, "orphelins": 0}
    listing = _CACHE_INDEX.with_prefix("")
    if not listing:
        return result
    by_label = {}
    for entry in listing:
        by_label.setdefault(entry.name.rsplit("__", 1)[0], []).append(entry)
    sidecars = [e for e in listing if "__preview_" in e.name and e.suffix == ".json"]
    for sidecar in sidecars:
        # Travail de fond PUR PYTHON (des dizaines de milliers de fiches) : on rend la main à chaque fiche,
        # sinon il garde le GIL par tranches et fait saccader l'interface (lecture vidéo, colonnes).
        time.sleep(_SWEEP_YIELD_S)
        try:
            source = Path(json.loads(sidecar.read_text(encoding="utf-8"))["source"])
            if source.exists():
                if dry_run:
                    continue
                # La fiche garde le chemin en MINUSCULES (normcase) : les codes de cache sont
                # calcules sur le chemin tel que l'appli le manipule, donc on retablit la casse.
                real = source.resolve()
                result["inutiles"] += prune_unused_previews(real, entries=by_label.get(_cache_label(real), []))
            elif source.parent.exists():
                for entry in by_label.get(_cache_label(source), []):
                    result["orphelins"] += 1
                    if not dry_run:
                        try:
                            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
                            _CACHE_INDEX.removed(entry)
                        except OSError:
                            pass
        except (OSError, ValueError, KeyError, TypeError):
            continue                      # fiche illisible, source inaccessible (accès refusé…) : on passe
    return result

_SWEEP_YIELD_S = 0.002

SWEEP_INTERVAL_S = 24 * 3600

def sweep_preview_cache_if_due() -> dict | None:
    """Ménage du cache au plus une fois par jour (il relit chaque fiche et chaque source : ~35 s de calcul
    pour ~10 000 fiches) ; date du dernier passage dans `<cache>/.last_sweep`."""
    stamp = FILE_IMAGE_DISK_CACHE_DIR / ".last_sweep"
    try:
        if time.time() - stamp.stat().st_mtime < SWEEP_INTERVAL_S:
            return None
    except OSError:
        pass
    result = sweep_preview_cache()
    try:
        stamp.write_text(json.dumps(result), encoding="utf-8")
        _CACHE_INDEX.added(stamp)
    except OSError:
        pass
    return result

def migrate_cache_names() -> int:
    """Renomme les anciens fichiers du cache (codes opaques) au format explicite
    <set>__<fichier>__<code>_<mtime> et rattache leurs fiches JSON au dossier
    actuel (voir _cache_label). Idempotent ; retourne le nombre de renommages."""
    cache = FILE_IMAGE_DISK_CACHE_DIR
    if not cache.is_dir():
        return 0
    renamed = 0
    for meta in [m for m in _CACHE_INDEX.with_prefix("preview_") if m.suffix == ".json"]:
        try:
            payload = json.loads(meta.read_text(encoding="utf-8"))
            source = Path(payload["source"])
            old_png = cache / Path(payload.get("cache", "")).name
            label = _cache_label(source)
            new_png = old_png
            if old_png.is_file() and "__" not in old_png.name:
                digest, _, tail = old_png.stem.partition("_")
                new_png = cache / f"{label}__{digest[:16]}_{tail}.png"
                old_png.replace(new_png)
                renamed += 1
            payload["cache"] = str(new_png)
            new_meta = cache / f"{label}__preview_{meta.stem.removeprefix('preview_')[:16]}.json"
            new_meta.write_text(json.dumps(payload), encoding="utf-8")
            meta.unlink()
        except (OSError, ValueError, KeyError, TypeError):
            continue
    for directory in [p for p in _CACHE_INDEX.with_prefix("turntable_") if "__" not in p.name and p.is_dir()]:
        try:
            manifest = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
            label = _cache_label(Path(manifest["source"]))
            new_dir = cache / f"{label}__turntable_{directory.name.split('_')[1][:16]}{directory.name[directory.name.find('_partial_'):] if '_partial_' in directory.name else ''}"
            directory.replace(new_dir)
            renamed += 1
            for latest in [m for m in _CACHE_INDEX.with_prefix("turntable_latest_") if m.suffix == ".json"]:
                data = json.loads(latest.read_text(encoding="utf-8"))
                if Path(data.get("cache", "")).name == directory.name:
                    data["cache"] = str(new_dir)
                    (cache / f"{label}__turntable_latest_{latest.stem.rsplit('_', 1)[1][:16]}.json").write_text(
                        json.dumps(data), encoding="utf-8")
                    latest.unlink()
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return renamed

def _record_preview_cache(path: Path, source_mtime: float, cache_path: Path) -> None:
    """Remember the last usable image even after its render key goes stale."""
    try:
        _memory._PREVIEW_STALE_LOOKUP_MISSES.discard((str(path), int(source_mtime)))
        FILE_IMAGE_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        metadata_path = _preview_cache_metadata_path(path)
        payload = {
            "source": os.path.normcase(str(path.resolve())),
            "source_mtime": float(source_mtime),
            "cache": str(cache_path.resolve()),
        }
        temp_path = metadata_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        temp_path.replace(metadata_path)
    except (OSError, ValueError):
        pass

def _preview_cache_metadata_matches(path: Path, cache_path: Path) -> bool:
    try:
        metadata_path = _preview_cache_metadata_path(path)
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return (
            payload.get("source") == os.path.normcase(str(path.resolve()))
            and Path(payload.get("cache", "")).resolve() == cache_path.resolve()
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False

def _find_stale_preview_cache(path: Path, mtime: float, current_path: Path) -> Path | None:
    """Find the last cached image for this source when its render key changed."""
    try:
        metadata_path = _preview_cache_metadata_path(path)
        if metadata_path.is_file():
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            stale_path = Path(payload.get("cache", ""))
            same_source = payload.get("source") == os.path.normcase(str(path.resolve()))
            if (same_source and stale_path != current_path and stale_path.parent == FILE_IMAGE_DISK_CACHE_DIR
                    and stale_path.is_file()):
                return stale_path
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    # Le cache peut ne contenir que des sidecars JSON (par exemple si les
    # anciens apercus ont ete purges). Detecter ce cas une seule fois evite
    # alors toute la recherche de migration pour chaque fichier affiche.
    if _memory._PREVIEW_CACHE_HAS_PNG is None:
        try:
            _memory._PREVIEW_CACHE_HAS_PNG = _CACHE_INDEX.has_png()
        except OSError:
            _memory._PREVIEW_CACHE_HAS_PNG = False
    if not _memory._PREVIEW_CACHE_HAS_PNG:
        return None

    # Migrate legacy cache files created before the metadata sidecar existed.
    # These candidates cover earlier preview revisions without guessing from
    # unrelated PNG files in the shared cache directory.
    suffix = path.suffix.lower()
    signatures = [_file_image_cache_signature(path)]
    if suffix in MAYA_SCENE_EXTENSIONS:
        template_base = signatures[0].split(":maya_", 1)[0]
        signatures.extend(template_base + ":" + value for value in (
            "maya_ascii_join_apply_all_transforms_before_bbox_scale_v8",
            "maya_ascii_join_weld_before_bbox_transform_v7",
            "maya_ascii_join_weld_before_bbox_transform_v6",
            "maya_ascii_join_before_bbox_transform_v5",
            "maya_ascii_binary_join_before_bbox_transform_v4",
            "maya_ascii_binary_collective_bbox_transform_v3",
            "maya_ascii_binary_manual_idle_escaped_paths_v2",
        ))
    digests = set()
    # Les anciennes revisions n'ont pas de sidecar et doivent etre migrees
    # occasionnellement. Ne pas parcourir toute l'histoire du cache a chaque
    # ligne visible : cela faisait des centaines de glob() synchrones, surtout
    # couteux sur les dossiers Maya sans rendu existant. Les revisions recentes
    # couvrent les formats de cache encore susceptibles d'etre presents.
    first_version = max(1, _PREVIEW_CACHE_VERSION - 8)
    for old_version in range(first_version, _PREVIEW_CACHE_VERSION):
        for signature in signatures:
            digests.add(hashlib.sha1(f"{old_version}:{path}{signature}".encode("utf-8")).hexdigest())
    for digest in digests:
        candidates = [c for c in _CACHE_INDEX.with_digest(digest) if c.is_file()]
        if candidates:
            candidates.sort(key=lambda candidate: candidate.stat().st_mtime, reverse=True)
            return candidates[0]

    # Source-only changes keep the same render digest; the old source-mtime
    # suffix remains available until a replacement is written.
    digest = _cache_digest_of(current_path)
    try:
        candidates = [candidate for candidate in _CACHE_INDEX.with_digest(digest)
                      if candidate != current_path and candidate.is_file()]
        if candidates:
            candidates.sort(key=lambda candidate: candidate.stat().st_mtime, reverse=True)
            return candidates[0]
    except OSError:
        pass
    return None

def _prune_stale_disk_cache(cache_path: Path) -> None:
    """Supprime les autres fichiers de cache disque de la meme image (memes
    premiers caracteres de nom, mtime different) que `cache_path`, devenus
    perimes suite a une modification du fichier source."""
    digest = _cache_digest_of(cache_path)
    try:
        for stale in _CACHE_INDEX.with_digest(digest):
            if stale != cache_path:
                try:
                    stale.unlink()
                    _CACHE_INDEX.removed(stale)
                except OSError:
                    pass
    except OSError:
        pass

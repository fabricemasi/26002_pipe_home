"""Lecture des aperçus et files de décodage asynchrones.

Carte et pièges : docs/agents/apercus.md.
"""

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap
from config import ABC_EXTENSIONS, BLEND_EXTENSIONS, DWG_EXTENSIONS, DXF_EXTENSIONS, FBX_EXTENSIONS, HOUDINI_SCENE_EXTENSIONS, MAYA_SCENE_EXTENSIONS, OBJ_EXTENSIONS, RENDERABLE_3D_EXTENSIONS, TWO_D_IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, _STALE_PREVIEW_PATHS
from . import alembic as _alembic
from . import blender as _blender
from . import cache as _cache
from . import dwg as _dwg
from . import executables as _executables
from . import filesystem as _filesystem
from . import houdini as _houdini
from . import images as _images
from . import maya as _maya
from . import memory as _memory
from . import mtime as _mtime
from . import obj as _obj
from . import profiles as _profiles
from . import render_log as _render_log
from . import video as _video

def _read_preview_pixmap(path: Path, mtime: float) -> tuple[QPixmap | None, bool]:
    """Load a current cached preview, or keep the last render as stale fallback."""
    key = str(path)
    cached = _memory._file_image_cache.get(key)
    if cached and cached[0] == mtime:
        column_cached = _memory._file_image_column_cache.get(key)
        if column_cached is None or column_cached[0] != mtime:
            _memory._cache_file_preview(key, mtime, cached[1], key in _STALE_PREVIEW_PATHS)
        return cached[1], key in _STALE_PREVIEW_PATHS
    current_path = _cache._file_image_cache_path(path, mtime)
    if current_path.is_file():
        pix = QPixmap(str(current_path))
        if not pix.isNull():
            is_stale = key in _STALE_PREVIEW_PATHS
            if not is_stale:
                _STALE_PREVIEW_PATHS.discard(key)
            _memory._cache_file_preview(key, mtime, pix, is_stale)
            if not _cache._preview_cache_metadata_matches(path, current_path):
                _cache._record_preview_cache(path, mtime, current_path)
            return pix, is_stale
    miss_key = (key, int(mtime))
    if miss_key in _memory._PREVIEW_STALE_LOOKUP_MISSES:
        return None, False
    # Evite meme la lecture des sidecars individuels dans un dossier qui ne
    # contient aucun apercu image. Cas courant pour une serie de scenes Maya
    # en attente du balayage d'inactivite : seul le premier fichier provoque
    # le scan du dossier de cache.
    if _memory._PREVIEW_CACHE_HAS_PNG is None:
        try:
            _memory._PREVIEW_CACHE_HAS_PNG = _cache._CACHE_INDEX.has_png()
        except OSError:
            _memory._PREVIEW_CACHE_HAS_PNG = False
    if not _memory._PREVIEW_CACHE_HAS_PNG:
        if len(_memory._PREVIEW_STALE_LOOKUP_MISSES) >= 4096:
            _memory._PREVIEW_STALE_LOOKUP_MISSES.clear()
        _memory._PREVIEW_STALE_LOOKUP_MISSES.add(miss_key)
        return None, False
    stale_path = _cache._find_stale_preview_cache(path, mtime, current_path)
    if stale_path is not None:
        pix = QPixmap(str(stale_path))
        if not pix.isNull():
            _STALE_PREVIEW_PATHS.add(key)
            _memory._cache_file_preview(key, mtime, pix, True)
            if not _cache._preview_cache_metadata_matches(path, stale_path):
                try:
                    old_mtime = float(stale_path.stem.rsplit("_", 1)[1])
                except (ValueError, IndexError):
                    old_mtime = 0.0
                _cache._record_preview_cache(path, old_mtime, stale_path)
            return pix, True
    _STALE_PREVIEW_PATHS.discard(key)
    if len(_memory._PREVIEW_STALE_LOOKUP_MISSES) >= 4096:
        _memory._PREVIEW_STALE_LOOKUP_MISSES.clear()
    _memory._PREVIEW_STALE_LOOKUP_MISSES.add(miss_key)
    return None, False

def file_image_pixmap(path: Path, asynchronous: bool = False) -> QPixmap | None:
    """Image du fichier `path` lui-meme (pas une vignette perso a choisir :
    c'est le fichier) — ou, pour un .obj (voir OBJ_EXTENSIONS), un rendu
    genere (voir _decode_obj_image), ou pour un .psd/.psb (voir
    PSD_EXTENSIONS), sa vignette JPEG embarquee (voir
    _decode_psd_thumbnail) — reduite au chargement si besoin (voir
    FILE_IMAGE_CACHE_MAX_DIM) puis mise en cache par date de
    modification, en memoire (cache borne, voir _bounded_cache_set) ET sur
    disque (voir FILE_IMAGE_DISK_CACHE_DIR) : la generation/reduction depuis
    le fichier source, plus couteuse, ne se refait qu'une fois par fichier
    (jusqu'a sa prochaine modification), meme apres redemarrage de l'appli.
    Le recadrage carre final se fait au dessin (voir _paint_row_image), a
    la taille reelle de la ligne. None si le fichier n'est plus lisible ou
    n'a pas de contenu exploitable."""
    # Les lignes des colonnes l'appellent a CHAQUE repeinture (asynchronous) : date memorisee un
    # instant (cached_mtime) ; l'inspecteur (synchrone) relit le disque.
    if asynchronous:
        mtime = _mtime.cached_mtime(path)
    else:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
    if mtime is None:
        return None
    # Un dossier associé à Lightroom ne décode jamais la photo originale : seul le JPEG demandé au SDK
    # Lightroom peut alimenter son aperçu.
    try:
        import lightroom_bridge
        managed = lightroom_bridge.is_managed(path)
    except (ImportError, OSError, ValueError):
        managed = False
    if managed:
        try:
            return lightroom_bridge.preview_pixmap(path, mtime)
        except (OSError, ValueError):
            return None
    key = str(path)
    cache_path = _cache._file_image_cache_path(path, mtime)
    if asynchronous:
        cached = _memory._file_image_column_cache.get(key)
        if cached and (cached[0] == mtime or key in _STALE_PREVIEW_PATHS):
            if key in _STALE_PREVIEW_PATHS and path.suffix.lower() in TWO_D_IMAGE_EXTENSIONS:
                _PREVIEW_DECODE_MANAGER.request(path, mtime, quiet=True, force_render=True)
            return cached[1]
        cached_full = _memory._file_image_cache.get(key)
        if cached_full and (cached_full[0] == mtime or key in _STALE_PREVIEW_PATHS):
            _memory._cache_file_preview(key, mtime, cached_full[1], key in _STALE_PREVIEW_PATHS)
            return _memory._file_image_column_cache[key][1]
        miss_key = (key, int(mtime))
        if miss_key in _memory._FILE_IMAGE_COLUMN_LOOKUP_MISSES:
            return None
        if _mtime.requests_held():                     # animation en cours : rien a decoder maintenant
            return None
        suffix = path.suffix.lower()
        # Les vignettes sont chargées/décodées en worker pour que l'ouverture
        # d'une colonne ne fasse jamais de lecture image sur le thread UI.
        if suffix in TWO_D_IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            _PREVIEW_DECODE_MANAGER.request(
                path, mtime, quiet=True, cache_only=False, force_render=key in _STALE_PREVIEW_PATHS
            )
        elif suffix in RENDERABLE_3D_EXTENSIONS:
            _PREVIEW_DECODE_MANAGER.request(path, mtime, quiet=True, cache_only=True)
        elif suffix in DWG_EXTENSIONS | DXF_EXTENSIONS:
            _PREVIEW_DECODE_MANAGER.request(path, mtime, quiet=True, cache_only=False)
        return None
    cached_pix, is_stale = _read_preview_pixmap(path, mtime)
    if cached_pix is not None:
        if is_stale and path.suffix.lower() in TWO_D_IMAGE_EXTENSIONS:
            _PREVIEW_DECODE_MANAGER.request(path, mtime, quiet=True)
        return cached_pix

    suffix = path.suffix.lower()
    if suffix in OBJ_EXTENSIONS | ABC_EXTENSIONS:
        # Les rendus OBJ/ABC sont explicites (menu contextuel) ou lances par
        # le balayage d'inactivite ; ne pas les demarrer a la simple selection.
        return None
    elif suffix in DWG_EXTENSIONS | DXF_EXTENSIONS:
        # Conversion / dessin DWG-DXF couteux : genere en arriere-plan.
        _PREVIEW_DECODE_MANAGER.request(path, mtime)
        return None
    elif suffix in BLEND_EXTENSIONS:
        # Un .blend ne se rend qu'a la demande via son menu contextuel;
        # une fois genere, son cache est affiche comme les autres apercus.
        return None
    elif suffix in MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS | HOUDINI_SCENE_EXTENSIONS:
        # Les scenes Maya se rendent a la demande ou pendant le balayage d'inactivite.
        return None
    elif suffix in TWO_D_IMAGE_EXTENSIONS:
        image = _images._decode_2d_image(path, _cache.FILE_IMAGE_CACHE_MAX_DIM)
        if image is None or image.isNull():
            return None
    elif suffix in VIDEO_EXTENSIONS:
        if suffix == ".mkv":
            # Les MKV ne sont décodés que sur demande explicite ; le cache reste lisible.
            return None
        image = _video._decode_video_frame(path, _cache.FILE_IMAGE_CACHE_MAX_DIM)
        if image is None or image.isNull():
            return None
    else:
        return None
    pix = QPixmap.fromImage(image)
    _STALE_PREVIEW_PATHS.discard(key)
    _memory._cache_file_preview(key, mtime, pix)
    if not _cache.IMAGE_DISK_CACHE_ENABLED:
        return pix                              # mise en cache disque des images suspendue
    try:
        was_new = not _cache.FILE_IMAGE_DISK_CACHE_DIR.is_dir()
        _cache.FILE_IMAGE_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if was_new:
            _filesystem._set_hidden(_cache.FILE_IMAGE_DISK_CACHE_DIR)
        if pix.save(str(cache_path), "PNG"):
            _memory._PREVIEW_CACHE_HAS_PNG = True
            _filesystem._set_hidden(cache_path)
            _cache._prune_stale_disk_cache(cache_path)
            _cache._record_preview_cache(path, mtime, cache_path)
    except OSError:
        pass
    return pix

def _cached_file_image_pixmap(path: Path, render_mode: str = "low") -> QPixmap | None:
    """Lit seulement le cache d'un apercu, sans lancer sa generation."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    try:
        import lightroom_bridge
        managed = lightroom_bridge.is_managed(path)
    except (ImportError, OSError, ValueError):
        managed = False
    if managed:
        try:
            return lightroom_bridge.preview_pixmap(path, mtime)
        except (OSError, ValueError):
            return None
    if render_mode == "high":
        cached = _memory._file_image_high_cache.get(str(path))
        if cached and cached[0] == mtime:
            return cached[1]
        image_path = _cache._file_image_cache_path(path, mtime, render_mode="high")
        pix = QPixmap(str(image_path)) if image_path.is_file() else QPixmap()
        if not pix.isNull():
            _memory._bounded_cache_set(_memory._file_image_high_cache, str(path), (mtime, pix))
        return pix if not pix.isNull() else None
    pix, _is_stale = _read_preview_pixmap(path, mtime)
    return pix

class _PreviewDecodeSignals(QObject):
    finished = Signal(object, str, float, object)
    progress = Signal(str, int, str)

def _set_render_execution_state(flags: int) -> int | None:
    """Requete Windows propre au thread de rendu ; ne modifie pas le plan d'energie."""
    if sys.platform != "win32":
        return None
    try:
        setter = ctypes.windll.kernel32.SetThreadExecutionState
        setter.argtypes = [ctypes.c_uint32]
        setter.restype = ctypes.c_uint32
        previous = setter(flags)
        return int(previous) if previous else None
    except (AttributeError, OSError):
        return None

def _rename_render_directory(source: Path, destination: Path) -> None:
    """Absorbe les verrous Windows brefs sans recalculer les 72 images."""
    for attempt in range(5):
        try:
            source.rename(destination)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1 * (2 ** attempt))

def _render_turntable_frame(prepared: Path, target: Path, index: int, cancel_event=None,
                            progress_callback=None) -> bool:
    """Un processus par image : sa RAM et ses buffers GPU sont liberes a la sortie."""
    blender = _executables._blender_executable()
    if not blender or (cancel_event is not None and cancel_event.is_set()):
        return False
    temporary = target.with_name(target.stem + ".tmp.png")
    expression = (
        "import bpy, os; bpy.context.preferences.edit.use_global_undo=False; "
        f"s=bpy.context.scene; s.frame_set({index + 1}); "
        f"s.render.filepath={str(temporary)!r}; s.render.use_overwrite=True; "
        "s.render.use_placeholder=False; bpy.ops.render.render(write_still=True); "
        f"os.replace({str(temporary)!r}, {str(target)!r})")
    error_path = prepared.parent / "render.log"
    process = None
    try:
        with error_path.open("w", encoding="utf-8") as stream:
            process = subprocess.Popen([blender, "-b", str(prepared), "--python-expr", expression],
                                       stdout=stream, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + 600
            while process.poll() is None:
                canceled = cancel_event is not None and cancel_event.is_set()
                if canceled or time.monotonic() > deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    if not canceled and progress_callback:
                        progress_callback(99, f"Erreur du turntable : delai de 10 minutes depasse a l'image {index + 1}/72")
                    return False
                time.sleep(0.1)
        if process.returncode == 0 and not QImage(str(target)).isNull():
            return True
        if progress_callback:
            details = error_path.read_text(encoding="utf-8", errors="replace").splitlines()
            progress_callback(99, f"Erreur du turntable a l'image {index + 1}/72 :\n" + "\n".join(details[-12:]))
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        if progress_callback:
            progress_callback(99, f"Erreur du turntable a l'image {index + 1}/72 : {exc}")
        return False
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()

class _PreviewDecodeTask(QRunnable):
    """Genere un apercu 3D sans bloquer l'interface; ne manipule que QImage."""
    def __init__(self, path: Path, mtime: float, quiet: bool = False, cancel_event=None, cache_only: bool = False, force_render: bool = False, render_mode: str = "low", profile_override=None, profiles_snapshot=None, automatic: bool = False, media_type: str = "image"):
        super().__init__()
        self.path = path
        self.mtime = mtime
        self.quiet = quiet
        self.cancel_event = cancel_event
        self.cache_only = cache_only
        self.force_render = force_render
        self.render_mode = render_mode
        self.profile_override = profile_override
        self.profiles_snapshot = profiles_snapshot
        self.automatic = automatic
        self.media_type = media_type
        self.output_path = ""
        self.loaded_stale = False
        self.log_directory = None
        self.signals = _PreviewDecodeSignals()

    def run(self):
        # Windows suit ces demandes par thread. Acquisition et liberation
        # restent donc dans ce meme worker, meme en cas d'erreur/annulation.
        rendering = not self.cache_only and self.path.suffix.lower() in RENDERABLE_3D_EXTENSIONS
        previous = _set_render_execution_state(0x80000001) if rendering else None
        if rendering and sys.platform == "win32" and previous is None and not self.quiet:
            self.signals.progress.emit(str(self.path), 0, "Windows n'a pas autorise le blocage de la veille automatique")
        try:
            self._run_preview()
        finally:
            if previous is not None:
                _set_render_execution_state(previous | 0x80000000)

    def _run_preview(self):
        def report(percent, message):
            if not self.quiet:
                self.signals.progress.emit(str(self.path), int(percent), str(message))
        if self.media_type == "turntable":
            try:
                image = self._decode_turntable()
            except Exception as exc:
                report(99, f"Erreur de turntable : {exc}")
                image = None
            report(100, "Turntable prêt" if image is not None else "Turntable indisponible")
            try:
                self.signals.finished.emit(self, str(self.path), self.mtime, image)
            except RuntimeError:
                pass  # l'application s'est fermee pendant le decodage
            return
        try:
            cache_path = _cache._file_image_cache_path(
                self.path, self.mtime, render_mode=self.render_mode,
                profiles_snapshot=self.profiles_snapshot,
            )
            if cache_path.is_file() and not self.force_render:
                image = QImage(str(cache_path))
                if image.isNull():
                    image = None
                else:
                    self.output_path = str(cache_path.resolve())
            elif self.cache_only:
                stale_path = _cache._find_stale_preview_cache(self.path, self.mtime, cache_path)
                image = QImage(str(stale_path)) if stale_path is not None else None
                if image is not None and not image.isNull():
                    self.loaded_stale = True
                    self.output_path = str(stale_path.resolve())
                else:
                    image = None
            else:
                image = self._decode()
            keep_on_disk = _cache.IMAGE_DISK_CACHE_ENABLED or self.path.suffix.lower() not in _cache._IMAGE_CACHE_SUFFIXES
            if (image is not None and not image.isNull() and not self.loaded_stale and keep_on_disk
                    and (self.force_render or not cache_path.is_file())):
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temp_path = cache_path.with_name(cache_path.stem + ".tmp.png")
                    if image.save(str(temp_path), "PNG"):
                        os.replace(temp_path, cache_path)
                        _cache._CACHE_INDEX.added(cache_path)
                        _memory._PREVIEW_CACHE_HAS_PNG = True
                        _filesystem._set_hidden(cache_path)
                        _cache._prune_stale_disk_cache(cache_path)
                        _cache._record_preview_cache(self.path, self.mtime, cache_path)
                        _cache.prune_unused_previews(self.path, self.mtime)
                        self.output_path = str(cache_path.resolve())
                except OSError:
                    pass
        except Exception as exc:
            if not self.quiet:
                self.signals.progress.emit(str(self.path), 99, f"Erreur de rendu : {exc}")
            image = None
        if image is not None and not image.isNull():
            report(100, "Image prête")
        else:
            report(100, "Aucun rendu exploitable")
        try:
            self.signals.finished.emit(self, str(self.path), self.mtime, image)
        except RuntimeError:
            pass  # l'application s'est fermee pendant le decodage

    def _decode_turntable(self):
        if self.path.suffix.lower() not in _cache.TURNTABLE_EXTENSIONS:
            return None
        if self.cancel_event is not None and self.cancel_event.is_set():
            return None
        destination = _cache._turntable_cache_path(self.path, self.mtime, self.profiles_snapshot, self.render_mode)
        _cache.FILE_IMAGE_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        profile = {key: value for key, value in _profiles._render_profile(self.render_mode, self.profile_override).items()
                   if not key.startswith("_turntable_")}
        staging = _cache._turntable_work_path(destination, profile, self.render_mode)
        staging.mkdir(exist_ok=True)
        prepared = staging / "prepared.blend"
        missing = [index for index in range(_cache.TURNTABLE_FRAME_COUNT)
                   if QImage(str(staging / f"frame_{index:03d}.png")).isNull()]
        def report(percent, message):
            if not self.quiet:
                self.signals.progress.emit(str(self.path), int(percent), message)
        report(1, f"Turntable : {_cache.TURNTABLE_FRAME_COUNT - len(missing)}/72 images deja sauvegardees")
        if missing:
            if not prepared.is_file():
                self.profile_override = dict(profile, _turntable_output=str(staging.resolve()),
                                             _turntable_prepared_scene=str(prepared.resolve()))
                result = self._decode()
                if result is None or result.isNull() or not prepared.is_file():
                    return None
            for index in missing:
                if self.path.stat().st_mtime != self.mtime:
                    return None
                report(70 + int(28 * index / 72), f"Turntable : image {index + 1}/72 (processus independant)")
                if not _render_turntable_frame(prepared, staging / f"frame_{index:03d}.png", index,
                                               self.cancel_event, report):
                    return None
        # Les fichiers partiels restent en place en cas d'erreur ou de pause.
        # Ce dossier temporaire ne contient que l'ancienne sequence publiee.
        with tempfile.TemporaryDirectory(prefix="turntable_work_", dir=str(_cache.FILE_IMAGE_DISK_CACHE_DIR),
                                         ignore_cleanup_errors=True) as work:
            first_image = None
            for index in range(_cache.TURNTABLE_FRAME_COUNT):
                if self.cancel_event is not None and self.cancel_event.is_set():
                    return None
                frame = staging / f"frame_{index:03d}.png"
                decoded = QImage(str(frame))
                if decoded.isNull():
                    return None
                composed = _profiles._apply_render_background(decoded, profile)
                temporary_frame = frame.with_name(frame.stem + ".compose.tmp.png")
                if not composed.save(str(temporary_frame), "PNG"):
                    return None
                temporary_frame.replace(frame)
                if index == 0:
                    first_image = composed
            if self.path.stat().st_mtime != self.mtime:
                return None
            if self.cancel_event is not None and self.cancel_event.is_set():
                return None
            (staging / "complete.json").write_text(json.dumps({"frames": _cache.TURNTABLE_FRAME_COUNT, "source": str(self.path), "mtime": self.mtime}), encoding="utf-8")
            # Ne publier que les 72 images completes ; une interruption
            # conserve le turntable precedent et ses metadonnees.
            previous = Path(work) / "previous"
            if destination.exists():
                _rename_render_directory(destination, previous)
            try:
                _rename_render_directory(staging, destination)
                _cache._CACHE_INDEX.added(destination)
            except OSError:
                if previous.exists():
                    _rename_render_directory(previous, destination)
                raise
            metadata = _cache._turntable_metadata_path(self.path, self.render_mode)
            temporary = metadata.with_suffix(".tmp")
            temporary.write_text(json.dumps({"cache": str(destination.resolve())}), encoding="utf-8")
            temporary.replace(metadata)
            try:
                _cache.prune_unused_previews(self.path, self.mtime)
            except OSError:
                pass
            self.output_path = str((destination / "frame_000.png").resolve())
            # Le snapshot lourd n'est utile que tant que la sequence est
            # incomplete. Ne pas le conserver pour chaque turntable publie.
            try:
                (destination / "prepared.blend").unlink(missing_ok=True)
            except OSError:
                pass
            return first_image

    def _decode(self):
        def report(percent, message):
            if not self.quiet:
                self.signals.progress.emit(str(self.path), int(percent), str(message))
        suffix = self.path.suffix.lower()
        if suffix in OBJ_EXTENSIONS: return _obj._decode_obj_image(self.path, _profiles.OBJ_PREVIEW_DIM, report, self.cancel_event, render_mode=self.render_mode, profile_override=self.profile_override)
        if suffix in ABC_EXTENSIONS: return _alembic._decode_abc_image(self.path, _profiles.OBJ_PREVIEW_DIM, report, self.cancel_event, render_mode=self.render_mode, profile_override=self.profile_override)
        if suffix in BLEND_EXTENSIONS:
            # Le rendu manuel "high resolution" doit rester strictement
            # identique au rendu automatique : la resolution 1105x1105 est
            # conservee et Blender detecte/applique la subdivision comme
            # dans le chemin automatique.
            return _blender._render_wireframe_eevee(self.path, _profiles.OBJ_PREVIEW_DIM, report, self.cancel_event, render_mode=self.render_mode, profile_override=self.profile_override)
        if suffix in HOUDINI_SCENE_EXTENSIONS: return _houdini._render_hip_wireframe(self.path, _profiles.OBJ_PREVIEW_DIM, report, self.cancel_event, render_mode=self.render_mode, profile_override=self.profile_override)
        if suffix in MAYA_SCENE_EXTENSIONS: return _maya._render_ma_wireframe(self.path, _profiles.OBJ_PREVIEW_DIM, report, self.cancel_event, render_mode=self.render_mode, profile_override=self.profile_override)
        if suffix in FBX_EXTENSIONS: return _blender._render_wireframe_eevee(self.path, _profiles.OBJ_PREVIEW_DIM, report, self.cancel_event, render_mode=self.render_mode, profile_override=self.profile_override)
        if suffix in DWG_EXTENSIONS: return _dwg._decode_dwg_image(self.path, _profiles.OBJ_PREVIEW_DIM, report, self.cancel_event)
        if suffix in DXF_EXTENSIONS: return _dwg._render_dxf_file(self.path, _profiles.OBJ_PREVIEW_DIM, report)
        if suffix in TWO_D_IMAGE_EXTENSIONS: return _images._decode_2d_image(self.path, _cache.FILE_IMAGE_CACHE_MAX_DIM, report, self.cancel_event)
        if suffix in VIDEO_EXTENSIONS: return _video._decode_video_frame(self.path, _cache.FILE_IMAGE_CACHE_MAX_DIM)
        return None

_PREVIEW_DECODE_POOL = QThreadPool()

_PREVIEW_DECODE_POOL.setMaxThreadCount(2)

_IDLE_SCAN_POOL = QThreadPool()

_IDLE_SCAN_POOL.setMaxThreadCount(1)

_IMAGE_DECODE_POOL = QThreadPool()

_IMAGE_DECODE_POOL.setMaxThreadCount(max(2, min(4, (os.cpu_count() or 4) - 2)))

_image_decode_order = 0

class _PreviewDecodeManager(QObject):
    started = Signal(str)
    progress = Signal(str, int, str)
    ready = Signal(str, float, object)
    turntable_ready = Signal(str, float, object)

    def __init__(self):
        super().__init__()
        self.active: dict[str, _PreviewDecodeTask] = {}
        self._pending_manual_requests: dict[str, tuple] = {}
        self.last_completed_mode: dict[str, str] = {}

    def request(self, path: Path, mtime: float, quiet: bool = False, cancel_event=None, cache_only: bool = False, force_render: bool = False, render_mode: str = "low", automatic: bool = False, media_type: str = "image", log_directory: Path | None = None):
        if path.suffix.lower() == ".mkv" and (not force_render or automatic):
            cache_only = True
            force_render = False
        key = str(path)
        if key in self.active:
            if force_render and not automatic and self.active[key].cache_only:
                # Un clic pendant la lecture du cache doit quand même produire son aperçu.
                self._pending_manual_requests[key] = (path, mtime, dict(
                    quiet=quiet, cancel_event=cancel_event, force_render=True,
                    render_mode=render_mode, media_type=media_type, log_directory=log_directory))
            return
        try:
            import lightroom_bridge
            managed = lightroom_bridge.is_managed(path)
        except (ImportError, OSError, ValueError):
            managed = False
        if managed:
            try:
                lightroom_bridge.preview_pixmap(path, mtime)
            except (OSError, ValueError):
                pass
            return
        profile_override = None
        profiles_snapshot = None
        if force_render and path.suffix.lower() in RENDERABLE_3D_EXTENSIONS:
            if automatic:
                if _profiles._AUTOMATIC_RENDER_PROFILE is None:
                    _profiles._begin_automatic_render_batch()
                profile_override = _profiles._AUTOMATIC_RENDER_PROFILE
                profiles_snapshot = _profiles._AUTOMATIC_RENDER_PROFILES
            else:
                _profiles._reload_render_profiles()
                profile_override = _profiles._render_profile(render_mode)
                profiles_snapshot = json.loads(json.dumps(_profiles._RENDER_PROFILES))
        task = _PreviewDecodeTask(path, mtime, quiet=quiet, cancel_event=cancel_event,
                                  cache_only=cache_only, force_render=force_render,
                                  render_mode=render_mode, profile_override=profile_override,
                                  profiles_snapshot=profiles_snapshot,
                                  automatic=automatic, media_type=media_type)
        task.signals.finished.connect(self._on_finished)
        task.signals.progress.connect(self._on_task_progress)
        self.active[key] = task
        task.log_directory = log_directory
        if force_render and not automatic and log_directory is not None:
            self._write_task_log(task, f"> Aperçu en cours : {path}")
        if not quiet:
            self.started.emit(key)
        if path.suffix.lower() in _cache._IMAGE_CACHE_SUFFIXES:
            # Images 2D / videos : file a part, plusieurs decodages a la fois, les DERNIERES
            # demandees d'abord (les lignes / vignettes visibles, peintes en dernier) ; jamais
            # derriere un rendu Blender / Maya.
            global _image_decode_order
            _image_decode_order += 1
            _IMAGE_DECODE_POOL.start(task, _image_decode_order)
        else:
            _PREVIEW_DECODE_POOL.start(task)

    def _on_finished(self, task, path_str: str, mtime: float, image):
        self.active.pop(path_str, None)
        self.last_completed_mode[path_str] = task.render_mode
        if task.media_type == "turntable":
            self.turntable_ready.emit(path_str, mtime, image)
        else:
            miss_key = (path_str, int(mtime))
            if image is not None and not image.isNull():
                _memory._FILE_IMAGE_COLUMN_LOOKUP_MISSES.discard(miss_key)
                if task.loaded_stale:
                    _STALE_PREVIEW_PATHS.add(path_str)
                else:
                    _STALE_PREVIEW_PATHS.discard(path_str)
            elif task.cache_only:
                if len(_memory._FILE_IMAGE_COLUMN_LOOKUP_MISSES) >= 4096:
                    _memory._FILE_IMAGE_COLUMN_LOOKUP_MISSES.clear()
                _memory._FILE_IMAGE_COLUMN_LOOKUP_MISSES.add(miss_key)
            self.ready.emit(path_str, mtime, image)
        pending = self._pending_manual_requests.pop(path_str, None)
        if pending is not None:
            path, stamp, options = pending
            self.request(path, stamp, **options)

    def _on_task_progress(self, path_str: str, percent: int, message: str):
        task = self.active.get(path_str)
        if task is not None and task.force_render and not task.automatic and task.log_directory is not None:
            self._write_task_log(task, f"[{percent:3d}%] {Path(path_str).name} — {message}")
        if task is None or not task.quiet:
            self.progress.emit(path_str, percent, message)

    def _write_task_log(self, task, message):
        try:
            _render_log._write_render_log(task.log_directory, message, str(task.path), task.media_type,
                              task.render_mode, task.output_path)
        except (OSError, ValueError):
            pass

_PREVIEW_DECODE_MANAGER = _PreviewDecodeManager()

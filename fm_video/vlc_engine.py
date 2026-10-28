"""Lecture des vidéos par LibVLC (le moteur de VLC) : décodage matériel (D3D11VA), audio, synchronisation
audio / vidéo, mise en cache réseau — exactement ceux de VLC installé sur la machine (python-vlc + libvlc.dll).

Les images ne vont PAS dans une fenêtre native : elles arrivent en mémoire (callbacks « vmem », planes I420 posés
directement dans nos tampons, aucune copie Python) et sont affichées par notre `GLViewer` (conversion YUV -> RVB
dans le shader, avec la matrice et la plage du fichier). Surimpression d'infos, bordures / coins / ombres, LUT,
corrections et OCIO restent donc disponibles pendant la lecture.

LibVLC ne sert qu'à la LECTURE. La navigation image par image (avant / arrière, exacte) reste à PyAV (`media`) :
à la pause, l'image exacte du rang atteint est décodée par PyAV ; pendant la lecture, PyAV ne décode rien.

Tampons : un état par tampon (libre / pris par VLC / dernière image montrée / en cours d'envoi au GPU) ; VLC ne
reçoit jamais un tampon que l'interface lit encore. Les appels à LibVLC se font sur le fil de l'interface (jamais
depuis un callback de VLC : interblocage)."""
from __future__ import annotations

import ctypes
import os
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

_LOCK = threading.Lock()
_INSTANCE = None
_ERROR = ""

# Options de l'instance : celles de VLC par défaut (sortie audio WASAPI, décodage matériel « any ») ; rien qui
# modifie l'image ou le son (ni normalisation, ni égaliseur, ni compresseur).
_ARGS = ["--quiet", "--no-video-title-show", "--no-osd", "--no-snapshot-preview", "--no-stats",
         "--no-media-library", "--avcodec-hw=any", "--no-sub-autodetect-file"]

_FormatCb = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                             ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
                             ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint))
_CleanupCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
_LockCb = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_UnlockCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_DisplayCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)

FREE, VLC, LATEST, UI = 0, 1, 2, 3


def instance():
    """Instance LibVLC partagée (créée une fois, en fond au démarrage : ~0,1-0,3 s). None si VLC est absent."""
    global _INSTANCE, _ERROR
    with _LOCK:
        if _INSTANCE is None and not _ERROR:
            try:
                import vlc
                inst = vlc.Instance(_ARGS)
                if inst is None:
                    raise RuntimeError("libvlc_new a échoué")
                _INSTANCE = inst
            except Exception as exc:                         # noqa: BLE001 - VLC absent : moteur PyAV
                _ERROR = f"{type(exc).__name__}: {exc}"
        return _INSTANCE


def available() -> bool:
    return instance() is not None


def error() -> str:
    return _ERROR


def version() -> str:
    try:
        import vlc
        return vlc.libvlc_get_version().decode("utf-8", "replace")
    except Exception:                                        # noqa: BLE001
        return ""


def is_remote(path) -> bool:
    """Chemin réseau (UNC ou lecteur réseau) : VLC y applique « network-caching » (au lieu de « file-caching »)."""
    text = str(path)
    if text.startswith(("\\\\", "//")):
        return True
    if os.name == "nt" and len(text) >= 2 and text[1] == ":":
        try:
            return ctypes.windll.kernel32.GetDriveTypeW(text[:2] + "\\") == 4      # DRIVE_REMOTE
        except Exception:                                    # noqa: BLE001
            return False
    return False


class _Buffer:
    __slots__ = ("planes", "pointers", "state", "seq")

    def __init__(self, sizes):
        self.planes = [np.empty(n, np.uint8) for n in sizes]
        self.pointers = [p.ctypes.data for p in self.planes]
        self.state = FREE
        self.seq = 0


class VlcPlayer(QObject):
    """Un lecteur LibVLC dont les images sont rendues en mémoire. Signaux (fil de l'interface) : `frameReady`
    (une nouvelle image est prête : `take()`), `ended` (fin du média), `playing` (la lecture a démarré :
    volume / muet réappliqués — LibVLC ignore le volume posé avant la création de la sortie audio)."""

    frameReady = Signal()
    ended = Signal()
    playing = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        import vlc
        self._vlc = vlc
        inst = instance()
        if inst is None:
            raise RuntimeError(_ERROR or "LibVLC indisponible")
        self.player = inst.media_player_new()
        self._lock = threading.Lock()
        self._buffers: list[_Buffer] = []
        self._format = None                       # (largeur, hauteur, pitches, lignes)
        self._latest = None
        self._seq = 0
        self._emit_pending = False
        self._closed = False
        self.path = None
        self.volume = 80
        self.muted = False
        self.displayed = 0                        # images montrées par VLC depuis l'ouverture (diagnostic)
        self.first_display = None                 # perf_counter de la 1re image après play / seek
        # Callbacks gardés en vie (ctypes) ; posés par les fonctions BRUTES de libvlc (types à nous).
        self._cb = (_FormatCb(self._on_format), _CleanupCb(self._on_cleanup), _LockCb(self._on_lock),
                    _UnlockCb(self._on_unlock), _DisplayCb(self._on_display))
        dll = vlc.dll
        set_fmt = dll.libvlc_video_set_format_callbacks
        set_fmt.argtypes = (ctypes.c_void_p, _FormatCb, _CleanupCb)
        set_fmt.restype = None
        set_cb = dll.libvlc_video_set_callbacks
        set_cb.argtypes = (ctypes.c_void_p, _LockCb, _UnlockCb, _DisplayCb, ctypes.c_void_p)
        set_cb.restype = None
        ptr = ctypes.c_void_p(self.player._as_parameter_.value)
        set_fmt(ptr, self._cb[0], self._cb[1])
        set_cb(ptr, self._cb[2], self._cb[3], self._cb[4], None)
        events = self.player.event_manager()
        events.event_attach(vlc.EventType.MediaPlayerEndReached, lambda _e: self._emit(self.ended))
        events.event_attach(vlc.EventType.MediaPlayerPlaying, lambda _e: self._emit(self.playing))
        events.event_attach(vlc.EventType.MediaPlayerEncounteredError,
                            lambda _e: self._emit(self.failed, "Erreur de lecture (VLC)"))

    def _emit(self, signal, *args):
        """Signal émis depuis un fil de VLC : livré au fil de l'interface (connexion en file)."""
        if self._closed:
            return
        try:
            signal.emit(*args)
        except RuntimeError:                                 # objet détruit
            pass

    # -- callbacks vmem (fil de sortie vidéo de VLC) --

    def _on_format(self, _opaque, chroma, width, height, pitches, lines):
        w, h = int(width[0]), int(height[0])
        ctypes.memmove(chroma, b"I420", 4)
        cw, ch = (w + 1) // 2, (h + 1) // 2
        p = [(w + 31) & ~31, (cw + 31) & ~31, (cw + 31) & ~31]
        ln = [(h + 15) & ~15, ((ch + 15) & ~15), ((ch + 15) & ~15)]
        for i in range(3):
            pitches[i] = p[i]
            lines[i] = ln[i]
        with self._lock:
            self._format = (w, h, p, ln)
            sizes = [p[i] * ln[i] for i in range(3)]
            self._buffers = [_Buffer(sizes) for _ in range(8)]
            self._latest = None
        return 6

    def _on_cleanup(self, _opaque):
        pass

    def _on_lock(self, _opaque, planes):
        with self._lock:
            buf = next((b for b in self._buffers if b.state == FREE), None)
            if buf is None:                                  # tous pris : un tampon de plus
                w, h, p, ln = self._format
                buf = _Buffer([p[i] * ln[i] for i in range(3)])
                self._buffers.append(buf)
            buf.state = VLC
            index = self._buffers.index(buf)
        for i in range(3):
            planes[i] = buf.pointers[i]
        return index + 1                                     # identifiant (jamais 0 : NULL)

    def _on_unlock(self, _opaque, picture, _planes):
        with self._lock:
            i = (picture or 0) - 1
            if 0 <= i < len(self._buffers) and self._buffers[i].state == VLC:
                self._buffers[i].state = FREE                # jamais montrée (image sautée)

    def _on_display(self, _opaque, picture):
        emit = False
        with self._lock:
            i = (picture or 0) - 1
            if not 0 <= i < len(self._buffers):
                return
            if self._latest is not None and self._latest.state == LATEST:
                self._latest.state = FREE                    # pas encore lue : remplacée
            buf = self._buffers[i]
            buf.state = LATEST
            self._seq += 1
            buf.seq = self._seq
            self._latest = buf
            self.displayed += 1
            if self.first_display is None:
                self.first_display = time.perf_counter()
            if not self._emit_pending:
                self._emit_pending = emit = True
        if emit:
            self._emit(self.frameReady)

    # -- lecture des images (fil de l'interface) --

    def take(self):
        """Dernière image montrée par VLC : (tampon, largeur, hauteur, pitches, lignes) ; le tampon reste à
        l'interface jusqu'au `take` suivant (ou `release`)."""
        with self._lock:
            self._emit_pending = False
            buf = self._latest
            if buf is None or buf.state != LATEST or self._format is None:
                return None
            for other in self._buffers:
                if other.state == UI:
                    other.state = FREE
            buf.state = UI
            w, h, p, ln = self._format
            return buf, w, h, p, ln

    def release_ui(self):
        with self._lock:
            for b in self._buffers:
                if b.state == UI:
                    b.state = FREE

    # -- commandes (fil de l'interface) --

    def open(self, path, cache_local_ms: int = 1000, cache_network_ms: int = 1500, repeat: bool = False,
             start: float = 0.0):
        """Média posé (lecture au prochain `play`). Cache : VLC applique « network-caching » aux fichiers d'un
        partage réseau (UNC, lecteur réseau) et « file-caching » aux autres ; `start` : départ en secondes."""
        inst = instance()
        media = inst.media_new_path(str(path))
        media.add_option(f":file-caching={int(cache_local_ms)}")
        media.add_option(f":network-caching={int(cache_network_ms)}")
        if start > 0:
            media.add_option(f":start-time={float(start):.6f}")
        if repeat:
            media.add_option(":input-repeat=65535")
        self.path = Path(path)
        self.player.set_media(media)
        media.release()
        self.first_display = None

    def play(self):
        self.first_display = None
        state = self.player.get_state()
        if state in (self._vlc.State.Ended, self._vlc.State.Error):
            # Après la fin du média, LibVLC refuse play() / set_time() : on repart d'un lecteur arrêté (cause du
            # « plus de son après plusieurs lectures » : la sortie audio n'était plus recréée).
            self.player.stop()
        self.player.play()

    def pause(self):
        if self.player.is_playing():
            self.player.set_pause(1)

    def stop(self):
        self.player.stop()
        self.release_ui()

    def is_playing(self) -> bool:
        return bool(self.player.is_playing())

    def state(self):
        return self.player.get_state()

    def set_time(self, ms: int):
        self.first_display = None
        self.player.set_time(int(max(0, ms)))

    def time_ms(self) -> int:
        return int(self.player.get_time())

    def set_volume(self, value: int):
        self.volume = int(max(0, min(100, value)))
        self.player.audio_set_volume(self.volume)

    def set_mute(self, muted: bool):
        self.muted = bool(muted)
        self.player.audio_set_mute(self.muted)

    def apply_audio(self):
        """Volume / muet réappliqués (événement Playing : la sortie audio vient d'être créée)."""
        self.player.audio_set_volume(self.volume)
        self.player.audio_set_mute(self.muted)

    def close(self):
        self._closed = True
        try:
            self.player.stop()
            self.player.release()
        except Exception:                                    # noqa: BLE001
            pass


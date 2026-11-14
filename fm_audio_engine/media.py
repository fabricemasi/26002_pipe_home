"""Service médias commun (sans Qt) : informations, cache PCM des formats compressés, empreinte.

- Le moteur ne lit que du WAV / RF64 : un WAV est utilisé tel quel ; MP3, FLAC, OGG, AIFF, M4A
  sont décodés par PyAV, HORS temps réel (fil de travail de l'appelant), vers un cache PCM local.
- Clé de cache = chemin absolu + taille + date (pas de hachage à chaque clic) ; version du
  décodeur incluse : un cache d'une ancienne version n'est jamais relu.
- `content_hash` (sha256) sert à VÉRIFIER ou dédupliquer un contenu, sur demande, jamais
  d'identité métier (celle-ci est dans la bibliothèque : `library.py`).
- Un média absent reste référencé : `probe` lève `MediaMissing`, il n'est jamais remplacé par un silence.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from . import wavio

DECODER_VERSION = 1
NATIVE_EXT = (".wav", ".wave", ".bwf", ".rf64")


class MediaError(RuntimeError):
    pass


class MediaMissing(MediaError):
    pass


@dataclass
class MediaInfo:
    path: str
    sample_rate: int
    channels: int
    frames: int
    codec: str
    native: bool          # lisible directement par le moteur

    @property
    def duration(self) -> float:
        return self.frames / self.sample_rate if self.sample_rate else 0.0


def cache_dir() -> Path:
    base = os.environ.get("FMZ_AUDIO_CACHE")
    if not base:
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
        base = os.path.join(local, "PIPE_FMZ", "audio_cache")   # hors dossier synchronisé
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _key(path: str) -> str:
    st = os.stat(path)
    raw = f"{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{st.st_mtime_ns}|{DECODER_VERSION}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def is_native(path: str) -> bool:
    if not str(path).lower().endswith(NATIVE_EXT):
        return False
    try:
        wavio.probe(path)
        return True
    except (wavio.WavError, OSError):
        return False


def probe(path: str | os.PathLike) -> MediaInfo:
    path = str(path)
    if not os.path.exists(path):
        raise MediaMissing(f"média absent : {path}")
    if path.lower().endswith(NATIVE_EXT):
        try:
            i = wavio.probe(path)
            return MediaInfo(path, i.sample_rate, i.channels, i.frames, "pcm_f32" if i.is_float else f"pcm_s{i.bits}", True)
        except wavio.WavError:
            pass  # WAV exotique (ADPCM…) : PyAV
    try:
        import av
    except ImportError as e:
        raise MediaError(f"PyAV indisponible pour lire {Path(path).suffix} : {e}")
    try:
        with av.open(path) as c:
            st = next((s for s in c.streams if s.type == "audio"), None)
            if st is None:
                raise MediaError(f"aucune piste audio : {path}")
            sr = int(st.codec_context.sample_rate or st.rate or 0)
            ch = int(st.codec_context.channels or 2)
            if st.duration is not None and st.time_base is not None:
                secs = float(st.duration * st.time_base)
            elif c.duration:
                secs = c.duration / 1_000_000
            else:
                secs = 0.0
            return MediaInfo(path, sr, ch, int(round(secs * sr)), st.codec_context.name, False)
    except av.error.FFmpegError as e:  # type: ignore[attr-defined]
        raise MediaError(f"média illisible : {path} ({e})")


def cached_pcm(path: str) -> str | None:
    """Chemin PCM lisible par le moteur SI disponible sans travail (WAV natif ou déjà décodé)."""
    if not os.path.exists(path):
        return None
    if is_native(path):
        return path
    p = cache_dir() / f"{_key(path)}.wav"
    return str(p) if p.exists() else None


def ensure_pcm(path: str, cancel=None, progress=None) -> str:
    """Décode si besoin (À APPELER DANS UN FIL DE TRAVAIL). Retourne le chemin PCM.
    `cancel()` -> True arrête proprement (aucun fichier partiel laissé)."""
    if not os.path.exists(path):
        raise MediaMissing(f"média absent : {path}")
    got = cached_pcm(path)
    if got:
        return got
    dst = cache_dir() / f"{_key(path)}.wav"
    import av
    info = probe(path)
    w = None
    try:
        with av.open(path) as c:
            st = next(s for s in c.streams if s.type == "audio")
            layout = "mono" if info.channels == 1 else "stereo"
            res = av.AudioResampler(format="fltp", layout=layout, rate=info.sample_rate)
            w = wavio.StreamWriter(dst, info.sample_rate, 1 if layout == "mono" else 2, overwrite=True)
            for frame in c.decode(st):
                if cancel and cancel():
                    w.abort()
                    raise MediaError("décodage annulé")
                for f in res.resample(frame):
                    w.write(f.to_ndarray())
                if progress and info.frames:
                    progress(min(1.0, w.frames / info.frames))
            for f in res.resample(None):
                w.write(f.to_ndarray())
        w.close()
    except MediaError:
        raise
    except Exception as e:
        if w is not None:
            w.abort()
        raise MediaError(f"décodage impossible : {path} ({e})")
    return str(dst)


def content_hash(path: str, chunk: int = 1 << 20) -> str:
    """sha256 du contenu (sur demande : vérification, déduplication)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def resolver(decode: bool = False):
    """Fonction `clip -> chemin PCM` pour `project.compile_spec`. Sans `decode`, ne fait
    aucun travail : un média pas encore décodé est signalé par le moteur (clip muet, diagnostic)."""
    def resolve(clip):
        if not clip.path:
            return None
        if decode:
            try:
                return ensure_pcm(clip.path)
            except MediaError:
                return clip.path
        return cached_pcm(clip.path) or clip.path
    return resolve

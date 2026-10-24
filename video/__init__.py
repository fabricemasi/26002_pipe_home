"""Module vidéo (paquet video/) : lecteur de vidéos et de séquences d'images (EXR, TIFF, DPX, PNG, JPEG…),
navigation exacte à l'image près, timeline zoomable, colorimétrie OpenColorIO + corrections non destructives,
LUT .cube, export FFmpeg / OpenImageIO, conversion de cadence (dont images intermédiaires).

Couches (chacune n'importe que les précédentes) :
- `media`    : détection des séquences, sources (PyAV pour les vidéos, OpenImageIO pour les images), infos ;
- `cache`    : cache d'images borné en mémoire + chargeurs en fond (préchargement, tâches périmées abandonnées) ;
- `color`    : réglages de correction, LUT .cube, OpenColorIO (CPU et shader GPU), même calcul CPU / GPU ;
- `viewer`   : affichage centré (OpenGL, repli CPU), zoom / déplacement, informations en surimpression ;
- `timeline` : timeline zoomable (images / timecode, IN / OUT, défilement) ;
- `export`   : tâches d'export (FFmpeg par tube, séquences OpenImageIO), conversion de cadence ;
- `vlc_engine` : lecture des vidéos par LibVLC (VLC installé) ; images rendues en mémoire, affichées par `viewer` ;
- `scopes`   : histogramme, waveform, vectorscope de l'image affichée (fil de fond) ;
- `thumbs`   : miniatures de la timeline (source à part, en fond, en pause pendant la lecture) ;
- `pane`     : `VideoPane`, le module posé sur la zone des colonnes (comme le board).

Aucune dépendance vers la fenêtre principale : elle pose `pane.HOOKS` (réglages, enregistrement d'une clé).
Tout est optionnel à l'exécution : sans PyAV / OpenImageIO / OpenColorIO / PyOpenGL, l'appli démarre ; le module
dit ce qui manque."""
from __future__ import annotations

import os
from pathlib import Path

# PyOpenGL appelle glGetError après CHAQUE appel OpenGL (et formate le contexte en Python) : ~110 appels par image,
# ~10 ms du fil de l'interface par image de lecture (mesure : 4 440 glCheckError en 2 s). À poser AVANT le 1er
# import d'OpenGL.GL ; les erreurs de compilation des shaders restent signalées (shaders.compileShader).
# PIPELINE_GL_CHECKS=1 rallume la vérification pour déboguer.
try:
    import OpenGL
    OpenGL.ERROR_CHECKING = os.environ.get("PIPELINE_GL_CHECKS") == "1"
    OpenGL.ERROR_LOGGING = False
except Exception:                                           # noqa: BLE001 - PyOpenGL absent : affichage CPU
    pass

VIDEO_EXTENSIONS = frozenset((".mp4", ".mov", ".mkv", ".avi", ".webm", ".mpg", ".mpeg", ".m4v", ".mxf", ".mts",
                              ".m2ts", ".ts", ".wmv", ".flv", ".3gp", ".ogv", ".vob", ".dv"))
# Images lisibles image par image (séquences ou image seule).
IMAGE_EXTENSIONS = frozenset((".exr", ".tif", ".tiff", ".dpx", ".png", ".jpg", ".jpeg", ".tga", ".bmp",
                              ".hdr", ".cin", ".webp", ".psd", ".tx", ".jp2"))
# Images « de pipeline » : leur séquence s'ouvre dans le module au double-clic (réglage).
PRO_IMAGE_EXTENSIONS = frozenset((".exr", ".tif", ".tiff", ".dpx", ".cin", ".hdr"))


def is_video_file(path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def is_media_file(path) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in VIDEO_EXTENSIONS or suffix in IMAGE_EXTENSIONS


def preload():
    """Importe les bibliothèques et modules du module (fil de fond, une fois) et charge la configuration OCIO par
    défaut : la 1re ouverture n'attend plus ~1,5 s d'imports. Ne crée aucun widget."""
    for module in ("numpy", "av", "OpenImageIO", "PyOpenColorIO", "OpenGL.GL", "OpenGL.GL.shaders",
                   "video.media", "video.cache", "video.color", "video.timeline", "video.viewer", "video.export"):
        try:
            __import__(module)
        except Exception:                                   # noqa: BLE001 - bibliothèque absente : dite à l'ouverture
            pass
    try:
        from video import color
        color.load_config("")
    except Exception:                                       # noqa: BLE001
        pass
    try:
        from video import vlc_engine
        vlc_engine.instance()                               # LibVLC prêt (plugins chargés) avant la 1re vidéo
    except Exception:                                       # noqa: BLE001 - VLC absent : moteur PyAV
        pass

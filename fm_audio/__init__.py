"""FM Audio : édition, restauration, enregistrement et mixage. Carte : docs/agents/fm_audio.md.

Ce fichier reste MINIMAL (aucun import lourd) : la fenêtre principale le lit à chaque clic."""
from pathlib import Path

AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".aif", ".aiff", ".m4a", ".bwf", ".rf64")
PROJECT_EXTENSIONS = (".fmaudio",)
EXTENSIONS = AUDIO_EXTENSIONS + PROJECT_EXTENSIONS


def is_audio_file(path) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS


def is_audio_project(path) -> bool:
    return Path(path).suffix.lower() in PROJECT_EXTENSIONS


def opens(path) -> bool:
    return Path(path).suffix.lower() in EXTENSIONS

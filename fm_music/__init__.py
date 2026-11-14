"""FM Music : composition, MIDI, instruments, arrangement. Carte : docs/agents/fm_audio.md (§ FM Music).

Ce fichier reste MINIMAL (aucun import lourd) : la fenêtre principale le lit à chaque clic."""
from pathlib import Path

PROJECT_EXTENSIONS = (".fmmusic",)
MIDI_EXTENSIONS = (".mid", ".midi")
EXTENSIONS = PROJECT_EXTENSIONS + MIDI_EXTENSIONS


def opens(path) -> bool:
    return Path(path).suffix.lower() in EXTENSIONS


def is_music_project(path) -> bool:
    return Path(path).suffix.lower() in PROJECT_EXTENSIONS

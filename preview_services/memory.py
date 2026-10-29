"""Caches mémoire et état partagé des aperçus.

Carte et pièges : docs/agents/apercus.md.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from config import _STALE_PREVIEW_PATHS

_CACHE_MAX_ENTRIES = 300

def _bounded_cache_set(cache: dict, key, value, max_entries: int = _CACHE_MAX_ENTRIES) -> None:
    """Ecrit `value` dans `cache[key]`, puis evince les entrees les plus
    anciennes si la taille depasse `max_entries`. Sans ca, les caches
    d'images ci-dessous (indexes par chemin de fichier, jamais purges
    autrement) grossissent sans jamais redescendre pendant toute la session
    de navigation — jusqu'a plusieurs centaines de Mo sur un pipeline avec
    beaucoup d'images/projets, meme apres qu'on ait quitte ces dossiers."""
    cache.pop(key, None)  # ressort la cle en fin d'ordre d'insertion si deja presente
    cache[key] = value
    while len(cache) > max_entries:
        del cache[next(iter(cache))]

_file_image_cache: dict[str, tuple[float, QPixmap]] = {}

_file_image_high_cache: dict[str, tuple[float, QPixmap]] = {}

_file_image_column_cache: dict[str, tuple[float, QPixmap]] = {}

_FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM = 80

_FILE_IMAGE_COLUMN_CACHE_MAX_ENTRIES = 1200

_FILE_IMAGE_COLUMN_LOOKUP_MISSES: set[tuple[str, int]] = set()

def _cache_file_preview(path_key: str, mtime: float, pix: QPixmap, is_stale: bool = False) -> QPixmap:
    """Garde l'aperçu inspecteur et sa vignette de ligne dans leurs caches dédiés."""
    _bounded_cache_set(_file_image_cache, path_key, (mtime, pix))
    small = pix.scaled(_FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM, _FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM,
                       Qt.KeepAspectRatio, Qt.SmoothTransformation)
    _bounded_cache_set(_file_image_column_cache, path_key, (mtime, small),
                       _FILE_IMAGE_COLUMN_CACHE_MAX_ENTRIES)
    if is_stale:
        _STALE_PREVIEW_PATHS.add(path_key)
    else:
        _STALE_PREVIEW_PATHS.discard(path_key)
    _FILE_IMAGE_COLUMN_LOOKUP_MISSES.discard((path_key, int(mtime)))
    return pix

# Evite de rescanner le cache disque a chaque repaint d'une ligne sans apercu.
# La cle inclut le mtime : une modification du fichier force une nouvelle recherche.
_PREVIEW_STALE_LOOKUP_MISSES: set[tuple[str, int]] = set()

_PREVIEW_CACHE_HAS_PNG: bool | None = None

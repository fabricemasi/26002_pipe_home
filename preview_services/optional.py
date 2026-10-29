"""Dépendances optionnelles des décodeurs.

Carte et pièges : docs/agents/apercus.md.
"""



try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

try:
    import rawpy
    _RAWPY_AVAILABLE = _NUMPY_AVAILABLE
except ImportError:
    _RAWPY_AVAILABLE = False

try:
    import OpenEXR
    _OPENEXR_AVAILABLE = _NUMPY_AVAILABLE
except ImportError:
    _OPENEXR_AVAILABLE = False

__all__ = ["np", "rawpy", "OpenEXR"]

"""Attributs cachés Windows des fichiers générés.

Carte et pièges : docs/agents/apercus.md.
"""

import ctypes
import sys
from pathlib import Path
from config import _FILE_ATTRIBUTE_HIDDEN

def _set_hidden(path: Path) -> None:
    """Marque `path` (fichier ou dossier) cache pour l'explorateur Windows.
    Le prefixe "." (convention Unix) ne suffit pas sur Windows : sans cet
    attribut, les vignettes/caches generes par l'appli (.thumbnail.png dans
    les dossiers de projet, .pipeline_preview_cache, .pipeline_software_icons)
    restaient visibles au milieu des vrais fichiers. No-op silencieux hors
    Windows ou en cas d'echec (ex: fichier verrouille)."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), _FILE_ATTRIBUTE_HIDDEN)
    except (AttributeError, OSError):
        pass

_FILE_ATTRIBUTE_NORMAL = 0x80

def _clear_hidden(path: Path) -> None:
    """Retire l'attribut cache (voir _set_hidden) juste AVANT de RE-ECRIRE
    un fichier deja marque cache lors d'un enregistrement precedent (ex.
    .pipeline_columns.json/.thumbnail.png reecrits a chaque modification) —
    sur Windows, ouvrir en ecriture/troncature (voir Path.write_text, mode
    'w') un fichier EXISTANT ne portant QUE l'attribut HIDDEN echoue avec
    PermissionError (confirme, reproductible a coup sur : SetFileAttributesW
    HIDDEN puis un 2e write_text() du meme fichier echouait TOUJOURS, meme
    en preservant les autres attributs existants) — voir la remarque de
    l'utilisateur, "quand j'essaie d'enregistrer une modification ... il ne
    se passe rien, il ne prend pas en compte les modifs" : c'etait
    exactement cette PermissionError, non rattrapee, qui interrompait
    silencieusement Column._open_column_config/ColumnConfigDialog._on_save
    avant self.accept(). Sans effet si `path` n'existe pas encore (rien a
    reecrire) — l'appelant doit alors re-cacher APRES coup (voir
    _set_hidden), comme avant. No-op silencieux hors Windows."""
    if sys.platform != "win32":
        return
    try:
        if path.is_file():
            ctypes.windll.kernel32.SetFileAttributesW(str(path), _FILE_ATTRIBUTE_NORMAL)
    except (AttributeError, OSError):
        pass

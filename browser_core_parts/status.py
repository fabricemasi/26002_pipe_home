"""Contenu des dossiers et états IN / OVER / OUT. Carte : docs/agents/colonnes.md."""

import os
from pathlib import Path
from config import FLATTEN_FOLDERS, HIDDEN_PREFIXES
from . import scan as _scan

# Dossiers de statut d'un projet/sous-projet (in/over/out), affiches comme
# des indicateurs dedies au-dessus de sa vignette dans l'apercu empile (voir
# _PreviewBlock) plutot que comme des lignes normales : jamais listes tels
# quels dans les colonnes Projets/Sous-projet (voir Column.refresh).
STATUS_FOLDERS = ("in", "over", "out")

_STATUS_FOLDER_SET = frozenset(STATUS_FOLDERS)

def _dir_has_content(directory: Path) -> bool:
    """True des que `directory` contient au moins une entree visible
    (fichier ou dossier, hors HIDDEN_PREFIXES)."""
    if _scan._remote_gui(directory):
        count = _scan.listed_count(directory)
        if count is None:
            _scan._request_directory(directory)
        return bool(count)
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if not entry.name.startswith(HIDDEN_PREFIXES):
                    if entry.is_dir() and _scan._is_globally_omitted_dir(entry.name):
                        continue
                    if not entry.is_dir() and _scan._is_globally_omitted_file(entry.name):
                        continue
                    return True
    except OSError:
        pass
    return False

def status_folder_state(directory: Path, name: str) -> tuple[bool, Path]:
    """Etat d'un dossier de statut (in/over/out) sous `directory` : (actif,
    chemin). Actif = le dossier existe (insensible a la casse) et n'est pas
    vide. Le chemin retourne est celui trouve sur le disque si actif, sinon
    `directory / name` (repli pour l'ouverture eventuelle malgre tout)."""
    if _scan._remote_gui(directory):
        children = _scan._DIR_CHILDREN.get(os.path.normcase(str(directory)))
        if children is None:
            _scan._request_directory(directory)
        path = (children or {}).get(name.lower(), directory / name)
        if children is not None and name.lower() not in children:
            return False, path
        return _dir_has_content(path), path
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_dir() and entry.name.lower() == name:
                    path = Path(entry.path)
                    return _dir_has_content(path), path
    except OSError:
        pass
    return False, directory / name

# Convention du pipeline : les logiciels d'un sous-projet vivent dans un
# sous-dossier "softs" (F:\PIPELINE\...\<sous-projet>\softs\<logiciel>), pas
# directement sous le sous-projet (qui a aussi "in"/"out"...). Voir
# _named_subdir, utilise par PipelineBrowser.on_selected en ouvrant la
# colonne "Logiciels", ET par la chaine de navigation CONFIGUREE (voir
# load_project_columns/ColumnConfigDialog) pour CHAQUE niveau configure —
# meme convention generalisee (nom de sous-dossier FIXE, pas un choix libre)
# — voir la remarque de l'utilisateur, "chaque colonne configuree pointe
# vers un nom de dossier fixe".
SOFTS_FOLDER_NAME = "softs"

def _named_subdir(directory: Path, name: str) -> Path:
    """Repertoire reellement liste pour un niveau de navigation dont le nom
    de dossier est FIXE (voir SOFTS_FOLDER_NAME/_softs_subdir, l'ancien nom
    de cette fonction avant sa generalisation a la chaine configurable) : le
    sous-dossier `name` de `directory` (insensible a la casse) s'il existe,
    sinon `directory` lui-meme (repli si la convention n'est pas suivie)."""
    children = _scan._DIR_CHILDREN.get(os.path.normcase(str(directory)))
    if _scan._remote_gui(directory):
        if children is None:
            _scan._request_directory(directory)
        return (children or {}).get(name.lower(), directory)
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_dir() and entry.name.lower() == name.lower():
                    return Path(entry.path)
    except OSError:
        pass
    return directory

def _softs_subdir(directory: Path) -> Path:
    return _named_subdir(directory, SOFTS_FOLDER_NAME)

def _count_dirs_recursive(directory: Path) -> int:
    """Nombre de dossiers obtenus en listant `directory` avec repli des
    FLATTEN_FOLDERS (memes regles que list_entries, mais ne garde que les
    dossiers) : utilise par count_entries pour les FLATTEN_FOLDERS imbriques."""
    count = 0
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.name.startswith(HIDDEN_PREFIXES):
                    continue
                if entry.is_dir():
                    if _scan._is_globally_omitted_dir(entry.name):
                        continue
                    if entry.name.upper() in FLATTEN_FOLDERS:
                        count += _count_dirs_recursive(Path(entry.path))
                    else:
                        count += 1
    except OSError:
        return 0
    return count

def count_entries(directory: Path, exclude: frozenset[str] | None = None) -> int:
    """Equivalent de len(list_entries(directory, exclude)), sans construire
    ni trier de liste : utilise pour la seule metadonnee « N elements » des
    colonnes a vignettes (Projets, Sous-projet), recalculee pour chaque
    ligne a chaque refresh() — le tri et l'allocation de list_entries y sont
    un travail pur perte, le compte etant la seule chose utilisee."""
    count = 0
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.name.startswith(HIDDEN_PREFIXES):
                    continue
                if exclude and entry.name.lower() in exclude:
                    continue
                if entry.is_dir():
                    if _scan._is_globally_omitted_dir(entry.name):
                        continue
                    if entry.name.upper() in FLATTEN_FOLDERS:
                        count += _count_dirs_recursive(Path(entry.path))
                    else:
                        count += 1
                else:
                    if _scan._is_globally_omitted_file(entry.name):
                        continue
                    count += 1
    except OSError:
        return 0
    return count

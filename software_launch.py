"""Lancer un logiciel « au bon emplacement » depuis une colonne (bouton à côté de la punaise des colonnes
ouvertes sous un dossier de logiciel du groupe LOGICIELS, voir PipelineBrowser._sync_software_buttons) :
le logiciel s'ouvre sur une scène vide dont « Enregistrer sous » propose le dossier de la colonne.

Un lanceur par logiciel (clé de `previews.software_icon_key`) ; Blender et Houdini pour l'instant, les
autres s'ajouteront à `LAUNCHERS`."""
import json
import os
import re
from pathlib import Path

from PySide6.QtCore import QProcess

from config import DATA_DIR
from previews import _blender_executable, _hython_executable


def _free_scene_path(folder: Path, stem: str, suffix: str) -> Path:
    """Premier nom libre du dossier (« untitled.blend », puis « untitled_01.blend »…) : un fichier existant
    serait OUVERT au lieu d'une scène vide."""
    candidate = folder / f"{stem}{suffix}"
    index = 1
    while candidate.exists():
        candidate = folder / f"{stem}_{index:02d}{suffix}"
        index += 1
    return candidate


def _blender_config_dir(blender: str) -> Path | None:
    """Dossier `config` de l'utilisateur pour CE Blender : `BLENDER_USER_CONFIG` s'il est pose, sinon
    l'installation portable (`<dossier de blender.exe>/portable/config`), sinon
    `%APPDATA%/Blender Foundation/Blender/<version>/config` (version = sous-dossier « 5.2 » de l'installation)."""
    configured = os.environ.get("BLENDER_USER_CONFIG")
    if configured:
        return Path(configured)
    install = Path(blender).parent
    if (install / "portable").is_dir():
        return install / "portable" / "config"
    versions = sorted((d.name for d in install.iterdir() if d.is_dir() and re.fullmatch(r"\d+\.\d+", d.name)),
                      key=lambda v: tuple(int(n) for n in v.split(".")))
    appdata = os.environ.get("APPDATA")
    if not versions or not appdata:
        return None
    return Path(appdata) / "Blender Foundation" / "Blender" / versions[-1] / "config"


_SEPARATORS = "/" + chr(92)      # / et \ en fin de chemin

# Panneaux du navigateur de fichiers Blender à replier dès leur première
# création. Le script est volontairement autonome : il est injecté par
# --python-expr et ne dépend d'aucun fichier de configuration Blender.
_BLENDER_FILE_BROWSER_UI_SCRIPT = """\
def _pipeline_fold_file_panels():
    names = (
        'FILEBROWSER_PT_bookmarks_system',
        'FILEBROWSER_PT_bookmarks_volumes',
        'FILEBROWSER_PT_bookmarks_recents',
    )
    for name in names:
        cls = getattr(bpy.types, name, None)
        if cls is None or getattr(cls, '_pipeline_folded', False):
            continue
        try:
            attrs = {k: getattr(cls, k) for k in (
                'bl_idname', 'bl_label', 'bl_space_type', 'bl_region_type',
                'bl_category', 'bl_translation_context', 'bl_parent_id', 'bl_order'
            ) if hasattr(cls, k)}
            attrs.update({
                '__module__': __name__,
                'bl_options': set(getattr(cls, 'bl_options', ())) | {'DEFAULT_CLOSED'},
                '_pipeline_folded': True,
            })
            bpy.utils.unregister_class(cls)
            replacement = type(name, (cls,), attrs)
            bpy.utils.register_class(replacement)
        except Exception:
            pass

bpy.app.timers.register(_pipeline_fold_file_panels, first_interval=0.2)
"""
_BLENDER_FILE_BROWSER_UI_EXPRESSION = f"import bpy; exec({_BLENDER_FILE_BROWSER_UI_SCRIPT!r})"


def add_blender_bookmark(config_dir: Path, folder: Path, name: str | None = None) -> bool:
    """Ajoute `folder` aux favoris (« Bookmarks ») de la fenetre de fichiers de Blender, sous le nom `name`
    (le SET, demande de l'utilisateur ; None = nom du dossier, comme Blender) : section `[Bookmarks]` de son
    `bookmarks.txt`, lu au demarrage — un nom s'y ecrit `!<nom>` sur la ligne au-dessus du chemin. Deja
    present : seul son nom est remis a jour. Le reste du fichier (dossiers recents) et ses fins de ligne sont
    gardes. False si le fichier ne peut etre ecrit."""
    path = config_dir / "bookmarks.txt"
    entry = str(folder).rstrip(_SEPARATORS) + "\\"
    try:
        raw = path.read_bytes().decode("utf-8") if path.is_file() else "[Bookmarks]\r\n[Recent]\r\n"
    except (OSError, UnicodeDecodeError):
        return False
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    if "[Bookmarks]" not in lines:
        lines.insert(0, "[Bookmarks]")
    start = lines.index("[Bookmarks]") + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("[")), len(lines))
    label = [f"!{name.strip()}"] if name and name.strip() else []
    found = next((i for i in range(start, end) if not lines[i].startswith("!")
                  and os.path.normcase(lines[i].rstrip(_SEPARATORS)) == os.path.normcase(entry.rstrip("\\"))), None)
    if found is None:
        lines[end:end] = label + [entry]
    else:
        named = found > start and lines[found - 1].startswith("!")
        if (lines[found - 1:found] if named else []) == label:
            return True
        lines[found - 1 if named else found:found] = label
    # Blender affiche les favoris dans l'ordre du fichier. Recompose chaque
    # entree (libelle optionnel + chemin), puis trie par nom affiche ; pour
    # une entree sans libelle, le nom du dossier sert de repli. La section
    # [Recent] et tout ce qui la suit restent a leur place.
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("[")), len(lines))
    blocks = []
    i = start
    while i < end:
        block = []
        if lines[i].startswith("!"):
            block.append(lines[i])
            i += 1
        if i < end:
            block.append(lines[i])
            i += 1
        if block:
            blocks.append(block)

    def bookmark_key(block):
        label_line = block[0] if block and block[0].startswith("!") else ""
        path_line = block[-1] if block else ""
        display_name = label_line[1:].strip() if label_line else Path(path_line.rstrip(_SEPARATORS)).name
        return (display_name.casefold(), path_line.casefold())

    ordered = [line for block in sorted(blocks, key=bookmark_key) for line in block]
    lines[start:end] = ordered
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_bytes((newline.join(lines) + newline).encode("utf-8"))
        os.replace(temp, path)
    except OSError:
        return False
    return True


# Scenes que l'appli a mises en tete des fichiers recents de Blender (voir add_blender_recent) : celles qui
# n'ont jamais ete enregistrees en sont retirees au lancement suivant.
_RECENT_ADDED = DATA_DIR / "blender_recent_added.json"


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def add_blender_recent(config_dir: Path, scene: Path, added_store: Path | None = None) -> bool:
    """Met `scene` (chemin pas encore enregistre) en TETE des fichiers recents de Blender (`recent-files.txt`,
    lu au demarrage) : File > Open s'ouvre dans le dossier du fichier recent le plus recent tant que la scene
    n'est pas enregistree — sans ca, il s'ouvrait dans celui du dernier fichier travaille ailleurs
    (« Enregistrer sous », lui, suit le chemin de la scene). Mecanisme de Blender lui-meme : menu File, ecran
    d'accueil, Ctrl+O. Les scenes ajoutees par un lancement precedent et jamais enregistrees sont retirees
    (sinon elles resteraient dans File > Open Recent) ; le reste de la liste et ses fins de ligne sont
    gardes. False si le fichier ne peut etre ecrit."""
    store = added_store or _RECENT_ADDED
    path = config_dir / "recent-files.txt"
    try:
        raw = path.read_bytes().decode("utf-8") if path.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return False
    try:
        previous = [str(p) for p in json.loads(store.read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        previous = []
    newline = "\n" if raw and "\r\n" not in raw else "\r\n"
    ghosts = [p for p in previous if not os.path.isfile(p)]
    lines = [line for line in raw.splitlines() if line.strip()
             and not _same_path(line, str(scene)) and not any(_same_path(line, g) for g in ghosts)]
    lines.insert(0, str(scene))
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_bytes((newline.join(lines) + newline).encode("utf-8"))
        os.replace(temp, path)
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps([str(scene)]), encoding="utf-8")
    except OSError:
        return False
    return True


def _launch_blender(folder: Path, set_name: str | None = None) -> bool:
    """Blender ouvert avec un chemin de scène QUI N'EXISTE PAS dans `folder` : il ouvre la scène par défaut
    et retient ce chemin comme celui du fichier (« saving will write to … ») — Enregistrer sous s'ouvre dans
    `folder`, Enregistrer y écrit directement. Rien n'est créé sur le disque avant cet enregistrement.
    (Blender signale au passage qu'il n'a pas pu lire ce fichier : c'est attendu.) Le dossier entre aussi
    dans ses favoris, au nom du set, et la scène en tête de ses fichiers récents (File > Open s'ouvre là)."""
    blender = _blender_executable()
    if not blender:
        return False
    scene = _free_scene_path(folder, "untitled", ".blend")
    config_dir = _blender_config_dir(blender)
    if config_dir is not None:
        add_blender_bookmark(config_dir, folder, set_name)  # favori de sa fenetre de fichiers, nom du set
        add_blender_recent(config_dir, scene)               # File > Open dans ce dossier aussi
    ok, _pid = QProcess.startDetached(
        blender, [str(scene), "--python-expr", _BLENDER_FILE_BROWSER_UI_EXPRESSION], str(folder))
    return bool(ok)


def _houdini_executable() -> str | None:
    """Houdini (interface) : `HOUDINI_EXECUTABLE`, sinon `houdini.exe` (il prend la licence choisie dans les
    preferences de l'utilisateur ; a defaut houdinifx / houdinicore / hindie / happrentice) du `bin` de hython
    (meme recherche que les apercus : HOUDINI_HYTHON, $HFS, version la plus recente installee)."""
    configured = os.environ.get("HOUDINI_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured
    hython = _hython_executable()
    if not hython:
        return None
    bin_dir = Path(hython).parent
    for name in ("houdini.exe", "houdinifx.exe", "houdinicore.exe", "hindie.exe", "happrentice.exe"):
        if (bin_dir / name).is_file():
            return str(bin_dir / name)
    return None


def _launch_houdini(folder: Path, set_name: str | None = None) -> bool:
    """Houdini lance SANS scene, dossier courant = `folder` : une scene sans titre a pour `$HIP` le dossier
    courant (verifie sur Houdini 21 : `<folder>/untitled.hip`) — Enregistrer sous et Ouvrir s'ouvrent donc
    dans `folder`. Rien n'est cree sur le disque."""
    houdini = _houdini_executable()
    if not houdini:
        return False
    ok, _pid = QProcess.startDetached(houdini, [], str(folder))
    return bool(ok)


LAUNCHERS = {
    "BLENDER": _launch_blender,
    "HOUDINI": _launch_houdini,
}


def can_launch(key: str | None) -> bool:
    """Vrai si le logiciel `key` a un lanceur (et donc un bouton dans les colonnes)."""
    return key in LAUNCHERS


def launch(key: str, folder: Path, set_name: str | None = None) -> bool:
    """Ouvre le logiciel `key` au dossier `folder` (`set_name` : nom du set, pour ses favoris) ; False s'il
    n'a pas de lanceur ou n'est pas installé."""
    launcher = LAUNCHERS.get(key)
    if launcher is None or not folder.is_dir():
        return False
    return launcher(folder, set_name)

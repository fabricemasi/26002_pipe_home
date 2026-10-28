"""Lecture / ecriture d'un board `.mro`, et le dossier de ses images (`<nom>_assets`).

Ecriture ATOMIQUE (fichier temporaire du meme dossier puis remplacement : un board n'est jamais a moitie ecrit).
Images : copiees une fois dans `<nom>_assets/` a cote du board (dossier cache), nommees par leur empreinte
(`<16 hexa>.<ext>` : une image collee deux fois n'est copiee qu'une fois) ; ecrites elles aussi par un fichier
temporaire (`.<nom>.part`) puis renommees : un import interrompu ne laisse jamais une image tronquee.

CYCLE DE VIE DES IMAGES (nettoyage sur, `cleanup_assets`) — un fichier du dossier n'est supprime QUE :
- s'il porte un nom d'asset de l'appli (`ASSET_NAME`), est un fichier ordinaire directement dans CE dossier
  (jamais un lien, un sous-dossier, un fichier etranger, un chemin qui en sort) ;
- et qu'il n'est reference ni par l'etat ENREGISTRE du board, ni par un etat encore accessible par
  l'annulation (la scene fournit ces noms, `BoardScene.assets_in_use`).
Moments surs : juste APRES un enregistrement reussi (jamais apres un echec ni pendant un conflit), et a la
fermeture (la pile d'annulation disparait : seul le fichier enregistre compte). A l'ouverture, les restes
d'imports interrompus ou annules (orphelins) ne sont retires que s'ils sont PLUS ANCIENS que le board et que
`ORPHAN_AGE_S` : dans un dossier synchronise, les images d'une version plus recente du board peuvent arriver
avant le board lui-meme. Les fichiers d'origine importes ne sont jamais touches (seules leurs copies)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from .model import EXTENSION, empty_board, normalize

ASSET_NAME = re.compile(r"^[0-9a-f]{16}\.[a-z0-9]{1,5}$")
PART_NAME = re.compile(r"^\.[0-9a-f]{16}\.[a-z0-9]{1,5}\.[0-9a-z_]+\.part$")
ORPHAN_AGE_S = 600


class BoardError(Exception):
    """Board illisible (JSON invalide, autre format)."""


def is_board_file(path) -> bool:
    return path is not None and Path(path).suffix.lower() == EXTENSION


def load(path) -> dict:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BoardError(f"{path.name} n'est pas un board (encodage).") from exc
    if not text.strip():                                  # fichier vide : board vierge
        board = empty_board()
        board["foreign"] = []
        return board
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BoardError(f"{path.name} : JSON invalide (ligne {exc.lineno}).") from exc
    if not isinstance(data, dict) or data.get("format", "pipeline-board") != "pipeline-board":
        raise BoardError(f"{path.name} n'est pas un board.")
    return normalize(data)


def dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)


def save(path, data: dict) -> None:
    path = Path(path)
    text = dumps(data)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def create_board_file(path) -> Path:
    """Nouveau board vierge (refuse d'ecraser un fichier existant)."""
    path = Path(path)
    if path.suffix.lower() != EXTENSION:
        path = path.with_name(path.name + EXTENSION)
    if path.exists():
        raise FileExistsError(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, empty_board())
    return path


def assets_dir(board_path) -> Path:
    board_path = Path(board_path)
    return board_path.with_name(f"{board_path.stem}_assets")


def asset_path(board_path, name: str) -> Path:
    return assets_dir(board_path) / name


def is_asset_name(name) -> bool:
    return isinstance(name, str) and bool(ASSET_NAME.match(name))


def import_asset(board_path, source) -> str:
    """Copie l'image `source` dans le dossier du board ; rend son nom relatif. L'original n'est jamais touche."""
    source = Path(source)
    digest = hashlib.sha1()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    suffix = (source.suffix.lower() or ".png")[:6]
    name = digest.hexdigest()[:16] + (suffix if re.match(r"^\.[a-z0-9]{1,5}$", suffix) else ".img")
    return _store(board_path, name, lambda target: shutil.copyfile(source, target))


def import_image_bytes(board_path, data: bytes, suffix: str = ".png") -> str:
    """Image collee (presse-papiers) : enregistree dans le dossier du board ; rend son nom relatif."""
    name = hashlib.sha1(data).hexdigest()[:16] + suffix
    return _store(board_path, name, lambda target: Path(target).write_bytes(data))


def _store(board_path, name: str, write) -> str:
    folder = assets_dir(board_path)
    target = folder / name
    if not target.exists():
        fresh = not folder.exists()
        folder.mkdir(parents=True, exist_ok=True)
        if fresh:
            try:
                from previews import _set_hidden          # dossier cache (Windows), comme les JSON de l'appli
                _set_hidden(folder)
            except Exception:
                pass
        part = folder / f".{name}.{os.getpid()}_{int(time.time() * 1000) % 100000}.part"
        try:
            write(part)
            os.replace(part, target)
        except BaseException:
            try:
                part.unlink()
            except OSError:
                pass
            raise
    return name


def _own_files(board_path):
    """(chemin, est_un_morceau) des fichiers que l'appli a pu ecrire dans le dossier du board — rien d'autre."""
    folder = assets_dir(board_path)
    try:
        real = folder.resolve()
        entries = list(os.scandir(folder))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
        except OSError:
            continue
        name = entry.name
        part = bool(PART_NAME.match(name))
        if not part and not ASSET_NAME.match(name):
            continue                                       # fichier etranger : jamais touche
        path = Path(entry.path)
        try:
            if path.resolve().parent != real:
                continue
        except OSError:
            continue
        yield path, part


def cleanup_assets(board_path, keep: set[str], min_age_s: float = 0.0, older_than: float | None = None) -> list:
    """Supprime les images de l'appli qui ne sont plus dans `keep` ; rend la liste des fichiers retires.
    `min_age_s` / `older_than` (date) : ne retirer que les fichiers plus anciens (balayage a l'ouverture)."""
    removed = []
    now = time.time()
    for path, part in _own_files(board_path) or ():
        if not part and path.name in keep:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        age_limit = max(min_age_s, ORPHAN_AGE_S if part else 0.0)
        if now - mtime < age_limit or (older_than is not None and mtime >= older_than):
            continue
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            pass
    folder = assets_dir(board_path)
    try:
        if removed and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()                                 # dossier vide : retire (il sera recree au besoin)
    except OSError:
        pass
    return removed

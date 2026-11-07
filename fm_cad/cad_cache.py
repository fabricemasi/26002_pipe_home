"""Module CAD : CACHE DISQUE des dessins DXF / DWG convertis (demande de l'utilisateur, 2026-11-04 : rouvrir un gros
DWG sans refaire la conversion ODA, la lecture ezdxf ni la conversion en board, ~11 s pour 81 000 entites).

- Ou : `%LOCALAPPDATA%/fm_cad/dessins` (jamais dans le dossier du projet, synchronise) ; `PIPELINE_CAD_CACHE_DIR`
  le remplace (tests : `tests/_isolate.py`).
- Quoi : les donnees de board DEJA NORMALISEES (`model.normalize`) et le compte rendu, en `marshal` compresse (zlib,
  niveau 1) : ~2,7 Mo, ~0,15 s a ecrire comme a relire pour 81 000 entites (pickle : 15 Mo non compresse, plus lent ;
  `marshal` ne fabrique que des valeurs, jamais d'objets de l'appli).
- Cle : chemin, taille et date du dessin + dates des fichiers du convertisseur (`CONVERTER`) + versions d'ezdxf, de
  Python et du format : dessin modifie ou convertisseur change = copie refaite (l'ancienne copie du meme dessin est
  supprimee).
- Taille bornee : au plus `MAX_FILES` copies et `MAX_BYTES` octets ; les moins recemment ouvertes partent d'abord.
Aucune erreur ne remonte : cache illisible, abime ou dossier interdit = dessin relu normalement. Sans Qt."""
from __future__ import annotations

import hashlib
import marshal
import os
import sys
import tempfile
import time
import zlib
from pathlib import Path

FORMAT = 1
SUFFIX = ".dessin"
MAX_FILES = 40
MAX_BYTES = 400 * 1024 * 1024
_HERE = Path(__file__).resolve().parent
# Fichiers dont depend le resultat de la conversion (une modification = copies refaites).
CONVERTER = tuple(_HERE / name for name in ("cad_import.py", "cad_model.py", "cad_shapes.py", "cad_geometry.py",
                                            "cad_text.py", "cad_hatch.py", "cad_point.py", "cad_attrib.py",
                                            "cad_block.py", "cad_image.py", "cad_xline.py", "cad_plot.py")) + (_HERE.parent / "fm_board" / "model.py",)


def folder() -> Path:
    env = os.environ.get("PIPELINE_CAD_CACHE_DIR")
    if env:
        return Path(env)
    return Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "fm_cad" / "dessins"


def _converter_stamp() -> str:
    parts = []
    for source in CONVERTER:
        try:
            parts.append(str(source.stat().st_mtime_ns))
        except OSError:
            parts.append("-")
    try:
        from importlib.metadata import version
        parts.append(version("ezdxf"))
    except Exception:                                       # noqa: BLE001 - ezdxf absent : la lecture le dira
        parts.append("?")
    parts += [str(FORMAT), str(marshal.version), "%d.%d" % sys.version_info[:2]]
    return "|".join(parts)


def entry(path) -> tuple[str, str] | None:
    """(prefixe propre au dessin, nom du fichier de cache) pour le dessin TEL QU'IL EST maintenant ; a prendre AVANT
    de le lire (modifie pendant la lecture : la copie garde l'ancienne date, la suivante sera refaite). None =
    dessin introuvable."""
    path = Path(path)
    try:
        stat = path.stat()
        real = str(path.resolve()).lower()
    except OSError:
        return None
    prefix = hashlib.sha1(real.encode("utf-8")).hexdigest()[:16]
    version = hashlib.sha1(f"{stat.st_size}|{stat.st_mtime_ns}|{_converter_stamp()}".encode("utf-8")).hexdigest()
    return prefix, f"{prefix}-{version[:16]}{SUFFIX}"


def load(key) -> tuple[dict, dict] | None:
    """(donnees normalisees, compte rendu) gardes pour `key` (`entry`), sinon None."""
    if key is None:
        return None
    file = folder() / key[1]
    try:
        found = marshal.loads(zlib.decompress(file.read_bytes()))
    except (OSError, ValueError, EOFError, TypeError, zlib.error):
        return None
    if not (isinstance(found, tuple) and len(found) == 2 and isinstance(found[0], dict) and isinstance(found[1], dict)):
        return None
    try:
        os.utime(file)                                      # ouverte recemment : gardee la derniere au nettoyage
    except OSError:
        pass
    return found


def store(key, data: dict, report: dict) -> bool:
    """Copie de `data` (normalisees) et `report` pour `key` ; False si impossible (rien n'est leve)."""
    if key is None:
        return False
    base = folder()
    tmp = None
    try:
        blob = zlib.compress(marshal.dumps((data, report)), 1)
        base.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=base, prefix=key[0], suffix=".tmp")
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
        os.replace(tmp, base / key[1])
        tmp = None
    except (OSError, ValueError):
        return False
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    sweep(base, keep=key)
    return True


def sweep(base: Path | None = None, keep=None):
    """Autres copies du dessin de `keep` supprimees (perimees) ; puis les copies les moins recemment ouvertes au-dela
    de MAX_FILES / MAX_BYTES ; restes d'ecritures interrompues de plus d'une heure."""
    base = base or folder()
    try:
        files = []
        for item in base.iterdir():
            stat = item.stat()
            if item.suffix == ".tmp" and time.time() - stat.st_mtime > 3600:
                item.unlink()
            elif item.suffix == SUFFIX:
                files.append((item, stat))
    except OSError:
        return
    kept = []
    for item, stat in files:
        if keep is not None and item.name != keep[1] and item.name.startswith(keep[0] + "-"):
            _unlink(item)
        else:
            kept.append((item, stat))
    kept.sort(key=lambda pair: pair[1].st_mtime, reverse=True)
    total = 0
    for count, (item, stat) in enumerate(kept, 1):
        total += stat.st_size
        if (count > MAX_FILES or total > MAX_BYTES) and (keep is None or item.name != keep[1]):
            _unlink(item)


def _unlink(item: Path):
    try:
        item.unlink()
    except OSError:
        pass

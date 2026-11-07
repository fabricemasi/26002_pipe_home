"""Format natif `.fmps` (SANS Qt) : archive ZIP avec manifeste et ressources SÉPARÉES.

    manifest.json     {format, version, document{…}, layers[ arbre ], icc, extra{…}}
    layers/<id>.png   pixels d'un calque raster (RGBA 8 bits, alpha DROIT), à (x, y) du manifeste
    masks/<id>.png    masque (niveaux de gris 8 bits)
    icc.bin           profil colorimétrique incorporé (facultatif)
    preview.png       aperçu aplati réduit (facultatif, pour les visionneuses : jamais relu)

Garanties : écriture ATOMIQUE (`.part` puis renommage, copie `.bak` de la version précédente) ; version PLUS RÉCENTE
que la nôtre = refus clair (`TooNewError`), jamais d'ouverture « à moitié » ; clés inconnues du manifeste gardées
(`extra`) et réécrites ; noms d'archive vérifiés (aucune extraction sur disque : lecture en mémoire par nom connu) ;
PNG de calque non réencodé tant que le plan n'a pas changé (`Plane.png`)."""
from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from .model import BLEND_MODES, Document, Layer, Mask, MAX_SIDE
from .planes import Plane

FORMAT = "fm_photoshop"
VERSION = 1
MAX_PIXELS = 600_000_000
RES_NAME = re.compile(r"^(layers|masks)/[0-9a-f]{16}\.png$")
KNOWN_LAYER = {"id", "name", "kind", "visible", "opacity", "blend", "locked", "clip", "passthrough", "x", "y", "w",
               "h", "png", "mask", "children", "source", "adjustment"}
KNOWN_DOC = {"width", "height", "name", "dpi", "icc_name", "depth", "meta", "uid"}
KNOWN_TOP = {"format", "version", "document", "layers", "icc", "extra", "saved_by"}


class ContainerError(Exception):
    """Fichier illisible, incomplet ou invalide (message lisible)."""


class TooNewError(ContainerError):
    """Fichier écrit par une version plus récente du module : refusé plutôt que perdu en silence."""


def _png_encode(data: np.ndarray, channels: int) -> bytes:
    """PNG d'un tableau de pixels (niveau 1 : l'archive est ré-écrite souvent). Pillow libère le GIL : utilisable en fil."""
    mode = "RGBA" if channels == 4 else "L"
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(data if channels == 4 else data[..., 0]), mode).save(buf, "PNG", compress_level=1)
    return buf.getvalue()


def _png_bytes(plane: Plane) -> bytes:
    cached = plane.png
    if cached is not None and cached[0] == plane.rev:
        return cached[1]
    plane.png = (plane.rev, _png_encode(plane.data, plane.channels))
    return plane.png[1]


def _remember(plane: Plane, rev: int, payload: bytes):
    """PNG gardé par un FIL (cliché de la révision `rev`) : jamais à la place d'un cliché plus récent. Il ne sert que tant
    que `plane.rev == rev` (toute écriture suivante l'invalide)."""
    current = plane.png
    if current is None or current[0] < rev:
        plane.png = (rev, payload)


def _layer_entry(layer: Layer, files: dict) -> dict:
    entry = {"id": layer.uid, "name": layer.name, "kind": layer.kind, "visible": layer.visible,
             "opacity": layer.opacity, "blend": layer.blend, "locked": layer.locked, "clip": layer.clip,
             "passthrough": layer.passthrough}
    entry.update(layer.extra)
    if layer.source:
        entry["source"] = layer.source
    if layer.adjustment:
        entry["adjustment"] = layer.adjustment
    if layer.pix is not None and layer.pix.data is not None:
        h, w = layer.pix.data.shape[:2]
        entry.update(x=layer.pix.x, y=layer.pix.y, w=w, h=h, png=f"layers/{layer.uid}.png")
        files[entry["png"]] = layer.pix
    if layer.mask is not None:
        plane = layer.mask.plane
        mask = {"enabled": layer.mask.enabled, "fill": plane.fill, **layer.mask.extra}
        if plane.data is not None:
            h, w = plane.data.shape[:2]
            mask.update(x=plane.x, y=plane.y, w=w, h=h, png=f"masks/{layer.uid}.png")
            files[mask["png"]] = plane
        entry["mask"] = mask
    if layer.children:
        entry["children"] = [_layer_entry(c, files) for c in layer.children]
    return entry


class Cancelled(Exception):
    """Préparation d'archive abandonnée (document fermé pendant l'encodage)."""


class Prepared:
    """Archive en deux temps. `prepare` (fil principal, quelques ms) fige le manifeste et regarde quels plans ont un PNG
    à jour ; `build` (lourd : encodage PNG des plans modifiés + assemblage) peut tourner dans un FIL. Avec `snapshot`,
    les plans à encoder sont COPIÉS : le trait suivant peut commencer sans toucher à ce que le fil encode."""

    def __init__(self, doc: Document, snapshot: bool = False):
        files: dict = {}
        manifest = dict(doc.extra)
        manifest.update(format=FORMAT, version=VERSION, saved_by="fm_photoshop",
                        document={"width": doc.width, "height": doc.height, "name": doc.name, "dpi": doc.dpi,
                                  "icc_name": doc.icc_name, "depth": doc.depth, "meta": doc.meta, "uid": doc.uid},
                        layers=[_layer_entry(layer, files) for layer in doc.layers])
        if doc.icc_profile:
            manifest["icc"] = "icc.bin"
        self.manifest = json.dumps(manifest, ensure_ascii=False, indent=1)     # (texte figé ici : le fil ne lit rien de vivant)
        self.icc = doc.icc_profile
        self.names = list(files)
        self.ready: dict = {}                                       # nom -> PNG déjà à jour
        self.todo: list = []                                        # (nom, plan, révision, pixels) à encoder
        for name, plane in files.items():
            cached = plane.png
            if cached is not None and cached[0] == plane.rev:
                self.ready[name] = cached[1]
            else:
                self.todo.append((name, plane, plane.rev, plane.data.copy() if snapshot else plane.data))

    def encode(self, cancelled=None):
        """Encode les plans sans PNG à jour (et les garde, `Plane.png`)."""
        for name, plane, rev, data in self.todo:
            if cancelled is not None and cancelled():
                raise Cancelled()
            payload = _png_encode(data, plane.channels)
            _remember(plane, rev, payload)
            self.ready[name] = payload
        self.todo = []

    def build(self, preview_png: bytes | None = None, cancelled=None) -> bytes:
        self.encode(cancelled)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("manifest.json", self.manifest, compress_type=zipfile.ZIP_DEFLATED)
            for name in self.names:
                archive.writestr(name, self.ready[name], compress_type=zipfile.ZIP_STORED)    # PNG : déjà compressé
            if self.icc:
                archive.writestr("icc.bin", self.icc, compress_type=zipfile.ZIP_DEFLATED)
            if preview_png is not None:
                archive.writestr("preview.png", preview_png, compress_type=zipfile.ZIP_STORED)
        return buf.getvalue()


def prepare(doc: Document, snapshot: bool = False) -> Prepared:
    return Prepared(doc, snapshot)


def dumps(doc: Document, preview: bool = False) -> bytes:
    """Archive complète en mémoire."""
    small = None
    if preview:
        from .compose import flatten_u8
        image = Image.fromarray(flatten_u8(doc), "RGBA")
        image.thumbnail((512, 512))
        out = io.BytesIO()
        image.save(out, "PNG")
        small = out.getvalue()
    return Prepared(doc).build(small)


def write_atomic(path, payload: bytes, backup: bool = False):
    """Écrit `payload` dans `path` sans jamais laisser un fichier à moitié écrit."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{os.getpid()}_{int(time.time() * 1000) % 100000}.part")
    try:
        with open(part, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if backup and path.exists():
            try:
                os.replace(path, path.with_name(path.name + ".bak"))
            except OSError:
                pass
        os.replace(part, path)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise


def save(doc: Document, path, preview: bool = True, backup: bool = True):
    write_atomic(path, dumps(doc, preview), backup=backup)


# -- lecture --
def _read_png(archive: zipfile.ZipFile, name: str, mode: str, w: int, h: int) -> np.ndarray:
    if not RES_NAME.match(name):
        raise ContainerError(f"Nom de ressource refusé dans l'archive : {name!r}")
    try:
        raw = archive.read(name)
    except KeyError:
        raise ContainerError(f"Ressource absente de l'archive : {name}") from None
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.size != (w, h):
                raise ContainerError(f"{name} : taille {image.size} différente du manifeste ({w} × {h}).")
            array = np.array(image.convert(mode), np.uint8)
    except ContainerError:
        raise
    except Exception as exc:                                   # noqa: BLE001 - PNG corrompu
        raise ContainerError(f"{name} illisible : {exc}") from exc
    return array[..., None] if mode == "L" else array


def _int(value, name, low=-10 ** 7, high=10 ** 7) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ContainerError(f"Manifeste invalide : {name}.") from None
    if not low <= number <= high:
        raise ContainerError(f"Manifeste invalide : {name} hors limites.")
    return number


def _load_layer(entry: dict, archive, depth=0) -> Layer:
    if not isinstance(entry, dict) or depth > 64:
        raise ContainerError("Manifeste invalide : calque.")
    uid = str(entry.get("id") or "")
    kind = entry.get("kind")
    layer = Layer(str(entry.get("name") or "Calque"), kind if kind in ("group", "adjustment") else "raster",
                  uid if re.match(r"^[0-9a-f]{16}$", uid) else None)
    layer.visible = bool(entry.get("visible", True))
    layer.opacity = min(1.0, max(0.0, float(entry.get("opacity", 1.0))))
    blend = entry.get("blend", "normal")
    layer.blend = blend if blend in BLEND_MODES else "normal"
    if blend not in BLEND_MODES:
        layer.extra["blend_unknown"] = blend                 # mode d'une version plus récente : gardé, rendu en normal
    layer.locked = bool(entry.get("locked", False))
    layer.clip = bool(entry.get("clip", False))
    layer.passthrough = bool(entry.get("passthrough", True))
    layer.extra.update({k: v for k, v in entry.items() if k not in KNOWN_LAYER})
    if isinstance(entry.get("source"), dict):
        layer.source = entry["source"]
    if isinstance(entry.get("adjustment"), dict):
        layer.adjustment = entry["adjustment"]
    if entry.get("png") and layer.pix is not None:
        w, h = _int(entry.get("w"), "w", 1, MAX_SIDE), _int(entry.get("h"), "h", 1, MAX_SIDE)
        layer.pix.set_all(_int(entry.get("x", 0), "x"), _int(entry.get("y", 0), "y"),
                          _read_png(archive, str(entry["png"]), "RGBA", w, h))
    mask = entry.get("mask")
    if isinstance(mask, dict):
        layer.mask = Mask(Plane(1, _int(mask.get("fill", 255), "fill", 0, 255)), bool(mask.get("enabled", True)))
        layer.mask.extra = {k: v for k, v in mask.items() if k not in ("enabled", "fill", "x", "y", "w", "h", "png")}
        if mask.get("png"):
            w, h = _int(mask.get("w"), "w", 1, MAX_SIDE), _int(mask.get("h"), "h", 1, MAX_SIDE)
            layer.mask.plane.set_all(_int(mask.get("x", 0), "x"), _int(mask.get("y", 0), "y"),
                                     _read_png(archive, str(mask["png"]), "L", w, h))
    layer.children = [_load_layer(c, archive, depth + 1) for c in entry.get("children") or []]
    # Les plans lus ne sont pas « modifiés » : leur PNG d'origine reste valable tel quel.
    return layer


def loads(payload: bytes) -> Document:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ContainerError(f"Archive illisible ou incomplète : {exc}") from exc
    with archive:
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except KeyError:
            raise ContainerError("Ce fichier n'est pas un document Photoshop du Board (manifeste absent).") from None
        except (ValueError, UnicodeDecodeError) as exc:
            raise ContainerError(f"Manifeste illisible : {exc}") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise ContainerError("Ce fichier n'est pas un document Photoshop du Board.")
        version = manifest.get("version")
        if not isinstance(version, int) or version < 1:
            raise ContainerError("Version de format invalide.")
        if version > VERSION:
            raise TooNewError(f"Document écrit par une version plus récente du format (v{version}, cette version "
                              f"lit jusqu'à v{VERSION}) : mettez l'application à jour. Rien n'a été modifié.")
        info = manifest.get("document")
        if not isinstance(info, dict):
            raise ContainerError("Manifeste invalide : document.")
        width, height = _int(info.get("width"), "width", 1, MAX_SIDE), _int(info.get("height"), "height", 1, MAX_SIDE)
        if width * height > MAX_PIXELS:
            raise ContainerError("Document trop grand pour cette version.")
        doc = Document(width, height, name=str(info.get("name") or "Sans titre"), dpi=float(info.get("dpi", 72.0)),
                       icc_name=str(info.get("icc_name") or "sRGB"), depth=int(info.get("depth", 8)),
                       meta=info.get("meta") if isinstance(info.get("meta"), dict) else {})
        if re.match(r"^[0-9a-f]{16}$", str(info.get("uid") or "")):
            doc.uid = info["uid"]
        doc.extra = {k: v for k, v in manifest.items() if k not in KNOWN_TOP}
        doc.extra.update({"document_extra": {k: v for k, v in info.items() if k not in KNOWN_DOC}} if
                         any(k not in KNOWN_DOC for k in info) else {})
        doc.layers = [_load_layer(e, archive) for e in manifest.get("layers") or []]
        if not doc.layers:
            raise ContainerError("Document sans calque.")
        if manifest.get("icc") == "icc.bin":
            try:
                doc.icc_profile = archive.read("icc.bin")
            except KeyError:
                doc.meta["diagnostic"] = "profil colorimétrique annoncé mais absent de l'archive"
    return doc


def load(path) -> Document:
    path = Path(path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ContainerError(f"{path.name} : {exc.strerror or exc}") from exc
    return loads(payload)

"""Import / export d'images (SANS Qt), par Pillow (HPND, déjà dépendance de l'appli).

Ce qui est LU / ÉCRIT exactement (rien d'autre n'est annoncé) :
- PNG  : lu / écrit, alpha, profil ICC, résolution ;
- TIFF : lu / écrit, alpha (RGBA 8 bits), profil ICC, résolution, compression « tiff_lzw » ;
- JPEG : lu / écrit SANS alpha (composition sur un fond choisi, annoncée dans les notes), profil ICC, qualité ;
- WebP : lu / écrit, alpha, qualité (ou sans perte) ;
- BMP  : lu seulement.
Une image 16 bits / flottante est lue en 8 bits (note explicite : « converti en 8 bits ») ; un mode palette / gris /
CMJN est converti en RGBA 8 bits (note). Aucun mode de couleur n'est converti sans que la note le dise."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .compose import flatten_u8
from .container import write_atomic

READ_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".psd")
WRITE_FORMATS = {".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
OPEN_FILTER = "Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp *.bmp);;Photoshop PSD (*.psd)"
SAVE_FILTER = "PNG (*.png);;TIFF (*.tif *.tiff);;JPEG (*.jpg *.jpeg);;WebP (*.webp)"


class ImageError(Exception):
    """Image illisible ou écriture impossible (message lisible)."""


def import_image(path):
    """(RGBA uint8, dpi, profil ICC ou None, notes) ; EXIF d'orientation appliqué."""
    path = Path(path)
    notes: list[str] = []
    try:
        with Image.open(path) as image:
            image.load()
            icc = image.info.get("icc_profile")
            dpi = image.info.get("dpi")
            dpi = float(dpi[0]) if isinstance(dpi, tuple) and dpi and dpi[0] else 72.0
            image = ImageOps.exif_transpose(image)
            if image.mode in ("I;16", "I;16B", "I;16L", "I", "F") or image.mode.endswith(";16"):
                notes.append(f"{path.name} : image {image.mode} convertie en 8 bits.")
                arr = np.array(image, np.float64)
                top = 65535.0 if arr.max() > 255 else 255.0
                image = Image.fromarray(np.clip(arr / top * 255.0 + 0.5, 0, 255).astype(np.uint8), "L")
            elif image.mode not in ("RGB", "RGBA", "L", "LA"):
                notes.append(f"{path.name} : mode {image.mode} converti en RGBA 8 bits.")
            rgba = np.array(image.convert("RGBA"), np.uint8)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageError(f"{path.name} : image illisible ({exc}).") from exc
    return rgba, dpi, icc, notes


def encode(rgba: np.ndarray, suffix: str, dpi: float = 72.0, icc: bytes | None = None, quality: int = 90,
           lossless: bool = False, background: tuple = (255, 255, 255)):
    """(octets, notes) de l'image RGBA droite dans le format de `suffix`."""
    suffix = suffix.lower()
    if suffix not in WRITE_FORMATS:
        raise ImageError(f"Format non pris en charge en écriture : {suffix}")
    fmt = WRITE_FORMATS[suffix]
    notes: list[str] = []
    image = Image.fromarray(np.ascontiguousarray(rgba), "RGBA")
    options: dict = {}
    if icc:
        options["icc_profile"] = icc
    if fmt == "JPEG":
        base = Image.new("RGB", image.size, tuple(background))
        base.paste(image, mask=image.getchannel("A"))
        image = base
        notes.append("JPEG sans transparence : image composée sur le fond choisi.")
        options.update(quality=int(quality), dpi=(dpi, dpi), optimize=True)
    elif fmt == "PNG":
        options.update(dpi=(dpi, dpi), compress_level=6)
    elif fmt == "TIFF":
        options.update(dpi=(dpi, dpi), compression="tiff_lzw")
    elif fmt == "WEBP":
        options.update(quality=int(quality), lossless=bool(lossless))
    buf = io.BytesIO()
    try:
        image.save(buf, fmt, **options)
    except (OSError, ValueError) as exc:
        raise ImageError(f"Écriture {fmt} impossible : {exc}") from exc
    return buf.getvalue(), notes


def export_document(doc, path, layer=None, **options):
    """Exporte la composition (ou UN calque, rendu dans le cadre du document) ; écriture atomique. Rend les notes."""
    path = Path(path)
    if layer is None:
        rgba = flatten_u8(doc)
    else:
        from .compose import compose, to_straight_u8
        from .ops import _shallow
        solo = _shallow(layer)
        solo.visible, solo.clip = True, False
        rgba = to_straight_u8(compose([solo], doc.rect()))
    payload, notes = encode(rgba, path.suffix, doc.dpi, doc.icc_profile, **options)
    write_atomic(path, payload)
    return notes

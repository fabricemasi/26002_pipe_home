"""Informations d'image (EXIF, PNG, sources) lues en fond pour le panneau d'informations.

Découpé de focus.py (2026-10-28) ; carte : docs/agents/fm_visionneuse.md."""
import math
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImageReader

from config import RAW_EXTENSIONS

from .loader import display_name


# -- Parametres de l'image (panneau a droite de l'image, Reglages > Visionneuse) -----------------
_PIL_MODES = {
    "1": "1 bit (noir et blanc)", "L": "8 bits, niveaux de gris", "LA": "8 bits, gris + alpha",
    "P": "8 bits, palette", "PA": "8 bits, palette + alpha", "RGB": "8 bits par canal, RGB",
    "RGBA": "8 bits par canal, RGBA", "RGBX": "8 bits par canal, RGB", "CMYK": "8 bits par canal, CMJN",
    "YCbCr": "8 bits par canal, YCbCr", "LAB": "8 bits par canal, Lab", "HSV": "8 bits par canal, TSV",
    "I": "32 bits entiers, gris", "F": "32 bits flottants, gris", "I;16": "16 bits, niveaux de gris",
    "I;16B": "16 bits, niveaux de gris", "I;16L": "16 bits, niveaux de gris",
}
_PNG_COLOR = {0: "gris", 2: "RGB", 3: "palette", 4: "gris + alpha", 6: "RGBA"}
_EXIF_ORIENTATION = {1: "normale", 2: "miroir horizontal", 3: "180°", 4: "miroir vertical",
                     5: "miroir + 90° anti-horaire", 6: "90° horaire", 7: "miroir + 90° horaire",
                     8: "90° anti-horaire"}


def _size_text(size: int) -> str:
    for unit, step in (("Go", 1 << 30), ("Mo", 1 << 20), ("Ko", 1 << 10)):
        if size >= step:
            return f"{size / step:.1f} {unit}".replace(".", ",")
    return f"{size} octets"


def _num(value) -> float | None:
    try:
        if isinstance(value, tuple) and len(value) == 2:
            return float(value[0]) / float(value[1]) if value[1] else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _clean(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return " ".join(str(value).replace("\x00", " ").split())


def _gps_degrees(values, ref) -> float | None:
    try:
        d, m, s = (_num(v) for v in values)
        deg = d + m / 60 + s / 3600
        return -deg if str(ref).upper() in ("S", "W") else deg
    except (TypeError, ValueError):
        return None


def _png_header(path: Path) -> str | None:
    """Profondeur et couleurs d'un PNG lues dans son entete IHDR (Pillow ouvre un PNG 16 bits en 8)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(29)
        if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
            return None
        return f"{head[24]} bits par canal, {_PNG_COLOR.get(head[25], '?')}"
    except OSError:
        return None


def _exif_rows(exif, ExifTags, image_rows: list, camera_rows: list):
    """Lignes « Prise de vue » (et l'orientation, cote Image) tirees de l'EXIF lu par Pillow."""
    import datetime
    base = dict(exif)
    sub = dict(exif.get_ifd(ExifTags.IFD.Exif) or {})
    gps = dict(exif.get_ifd(ExifTags.IFD.GPSInfo) or {})
    if base.get(0x0112) in _EXIF_ORIENTATION:
        image_rows.append(("Orientation", _EXIF_ORIENTATION[base[0x0112]]))
    make, model = _clean(base.get(0x010F, "")), _clean(base.get(0x0110, ""))
    if make or model:
        camera_rows.append(("Appareil", model if make and model.startswith(make) else f"{make} {model}".strip()))
    if sub.get(0xA434):
        camera_rows.append(("Objectif", _clean(sub[0xA434])))
    taken = sub.get(0x9003) or base.get(0x0132)
    if taken:
        text = _clean(taken)
        try:
            text = datetime.datetime.strptime(text, "%Y:%m:%d %H:%M:%S").strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            pass
        camera_rows.append(("Date", text))
    exposure = _num(sub.get(0x829A))
    if exposure:
        camera_rows.append(("Exposition", f"1/{round(1 / exposure)} s" if exposure < 1
                            else f"{exposure:g} s".replace(".", ",")))
    aperture = _num(sub.get(0x829D))
    if aperture:
        camera_rows.append(("Ouverture", f"f/{aperture:g}".replace(".", ",")))
    iso = sub.get(0x8827)
    if iso:
        camera_rows.append(("ISO", str(iso[0] if isinstance(iso, tuple) else iso)))
    focal = _num(sub.get(0x920A))
    if focal:
        eq = sub.get(0xA405)
        camera_rows.append(("Focale", f"{focal:g} mm".replace(".", ",") + (f" ({eq} mm éq. 24×36)" if eq else "")))
    bias = _num(sub.get(0x9204))
    if bias:
        camera_rows.append(("Correction", f"{bias:+.1f} IL".replace(".", ",")))
    if 0x9209 in sub:
        camera_rows.append(("Flash", "déclenché" if int(sub[0x9209]) & 1 else "non"))
    if 0xA403 in sub:
        camera_rows.append(("Balance des blancs", "manuelle" if sub[0xA403] else "auto"))
    lat = _gps_degrees(gps.get(2), gps.get(1)) if gps.get(2) else None
    lon = _gps_degrees(gps.get(4), gps.get(3)) if gps.get(4) else None
    if lat is not None and lon is not None:
        camera_rows.append(("GPS", f"{lat:.5f}, {lon:.5f}"))
    for tag, label in ((0x0131, "Logiciel"), (0x013B, "Auteur"), (0x8298, "Copyright"), (0x010E, "Description")):
        value = _clean(base.get(tag, ""))
        if value:
            camera_rows.append((label, value))


def image_sources(path: Path, mtime: float) -> list:
    """Lignes « Source du proxy » (colonnes, inspecteur, diapositives), « Path du proxy » et
    « Source de l'aperçu plein écran » (image en focus). Lit le catalogue / le disque : EN FOND."""
    try:
        import lightroom_bridge as lb
        managed = lb.is_managed(path)
    except (ImportError, OSError, ValueError):
        managed = False
    if managed:
        try:
            found = lb.proxy_file(path)
        except Exception:
            found = None
        return [("Source du proxy", lb.proxy_source(path)),
                ("Path du proxy", str(found[0]) if found is not None else "—"),
                ("Source de l'aperçu plein écran", lb.fullscreen_source(path))]
    from previews import _file_image_cache_path
    cache = _file_image_cache_path(path, mtime)
    proxy = "Application · cache d'aperçus" if cache.is_file() else "Application · pas encore créé"
    full = "Image originale (JPEG intégré au RAW)" if path.suffix.lower() in RAW_EXTENSIONS else "Image originale"
    return [("Source du proxy", proxy), ("Path du proxy", str(cache)),
            ("Source de l'aperçu plein écran", full)]


def image_info(path: Path) -> list:
    """Tous les parametres connus d'un fichier de la visionneuse : [(section, [(libelle, valeur)])].
    Lu sans decoder l'image (entete ; EXIF, profil couleur, ppp via Pillow s'il est installe).
    Appele EN FOND (_InfoTask), jamais sur le fil de l'interface."""
    import datetime
    sections = []
    file_rows = [("Nom", display_name(path)), ("Dossier", str(path.parent)),
                 ("Path de l'image", str(path.resolve())),
                 ("Type", path.suffix.lstrip(".").upper() or "?")]
    try:
        stat = path.stat()
        file_rows += image_sources(path, stat.st_mtime)

        def stamp(t):
            return datetime.datetime.fromtimestamp(t).strftime("%d/%m/%Y %H:%M:%S")

        file_rows += [("Taille", _size_text(stat.st_size)), ("Modifié", stamp(stat.st_mtime)),
                      ("Créé", stamp(stat.st_ctime))]
    except OSError:
        pass
    sections.append(("Fichier", file_rows))
    image_rows, camera_rows, text_rows = [], [], []
    reader = QImageReader(str(path))
    size = reader.size()
    dims = (size.width(), size.height()) if size.isValid() else None
    fmt = bytes(reader.format()).decode("ascii", "ignore").upper()
    for key in reader.textKeys():
        value = _clean(reader.text(key))
        if value and len(value) < 400:
            text_rows.append((key, value))
    depth = _png_header(path) if path.suffix.lower() == ".png" else None
    colors = None
    extra_rows: list = []
    try:
        from PIL import ExifTags, Image
    except ImportError:
        Image = None
    if Image is not None:
        try:
            with Image.open(path) as im:
                dims = dims or im.size
                fmt = fmt or (im.format or "")
                bits = None
                if im.format == "TIFF":
                    sample = getattr(im, "tag_v2", {}).get(258)
                    if sample:
                        first = sample[0] if isinstance(sample, tuple) else sample
                        bits = f"{first} bits par canal, {im.mode}"
                colors = depth or bits or _PIL_MODES.get(im.mode, im.mode)
                if "transparency" in im.info or im.mode in ("RGBA", "LA", "PA"):
                    extra_rows.append(("Transparence", "oui"))
                dpi = im.info.get("dpi")
                if dpi and _num(dpi[0]):
                    extra_rows.append(("Résolution", f"{round(_num(dpi[0]))} × {round(_num(dpi[1]))} ppp"))
                icc = im.info.get("icc_profile")
                if icc:
                    name = "intégré"
                    try:
                        import io
                        from PIL import ImageCms
                        name = ImageCms.getProfileDescription(
                            ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip() or name
                    except Exception:
                        pass
                    extra_rows.append(("Profil couleur", name))
                frames = getattr(im, "n_frames", 1) or 1
                if frames > 1:
                    extra_rows.append(("Images", str(frames)))
                exif = im.getexif()
                if exif:
                    _exif_rows(exif, ExifTags, extra_rows, camera_rows)
        except Exception:
            pass
    if dims:
        w, h = dims
        g = math.gcd(w, h) or 1
        ratio = f"{w // g}:{h // g}" if w // g <= 32 and h // g <= 32 else f"{w / max(1, h):.3f}".replace(".", ",")
        image_rows += [("Dimensions", f"{w} × {h} px"), ("Mégapixels", f"{w * h / 1e6:.1f}".replace(".", ",")),
                       ("Ratio", ratio)]
    if fmt:
        image_rows.append(("Format", fmt.upper()))
    if colors or depth:
        image_rows.append(("Couleurs", colors or depth))
    image_rows += extra_rows
    for title, rows in (("Image", image_rows), ("Prise de vue", camera_rows), ("Textes intégrés", text_rows)):
        if rows:
            sections.append((title, rows))
    return sections


class _InfoSignals(QObject):
    done = Signal(str, float, object)


class _InfoTask(QRunnable):
    def __init__(self, path: Path, mtime: float, signals: _InfoSignals):
        super().__init__()
        self._path, self._mtime, self._signals = path, mtime, signals

    def run(self):
        try:
            info = image_info(self._path)
        except Exception:
            info = [("Fichier", [("Nom", display_name(self._path))])]
        try:
            self._signals.done.emit(str(self._path), self._mtime, info)
        except RuntimeError:                      # panneau detruit entre-temps
            pass

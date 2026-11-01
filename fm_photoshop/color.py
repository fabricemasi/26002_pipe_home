"""Gestion de la couleur (SANS Qt) : profils ICC par LittleCMS (Pillow.ImageCms, déjà dépendance).

DEUX opérations distinctes, jamais confondues :
- ASSIGNER un profil : le document est RÉINTERPRÉTÉ avec ce profil ; AUCUN pixel ne change (seule la façon de les lire) ;
- CONVERTIR vers un profil : les pixels sont recalculés pour garder la même apparence dans le nouvel espace (intention de
  rendu au choix, compensation du point noir) ; l'alpha n'est jamais touché ; les couleurs des textes / formes suivent.
Document sans profil = sRGB (hypothèse affichée). Modèles RVB seulement ; 8 bits (16 bits / flottant : non pris en charge,
voir la doc). Aucune conversion silencieuse : tout passe par une étape d'annulation nommée."""
from __future__ import annotations

import io
import os
from pathlib import Path

import numpy as np
from PIL import ImageCms, Image

from .history import CallCommand

INTENTS = {"perceptual": ("Perceptive", ImageCms.Intent.PERCEPTUAL),
           "relative": ("Colorimétrique relative", ImageCms.Intent.RELATIVE_COLORIMETRIC),
           "saturation": ("Saturation", ImageCms.Intent.SATURATION),
           "absolute": ("Colorimétrique absolue", ImageCms.Intent.ABSOLUTE_COLORIMETRIC)}
SRGB_NAME = "sRGB IEC61966-2.1"


def srgb_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def open_profile(data: bytes):
    try:
        return ImageCms.ImageCmsProfile(io.BytesIO(data))
    except (ImageCms.PyCMSError, OSError) as exc:
        raise ValueError(f"Profil colorimétrique illisible : {exc}") from exc


def describe(data: bytes) -> str:
    try:
        return ImageCms.getProfileDescription(open_profile(data)).strip() or "Profil sans nom"
    except Exception:                                              # noqa: BLE001
        return "Profil illisible"


def is_rgb(data: bytes) -> bool:
    try:
        return open_profile(data).profile.xcolor_space.strip() == "RGB"
    except Exception:                                              # noqa: BLE001
        return False


def system_profiles() -> list:
    """[(nom, octets)] des profils RVB du système (Windows : dossier des profils de couleur) + sRGB."""
    found = [(SRGB_NAME, srgb_bytes())]
    folder = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "spool" / "drivers" / "color"
    try:
        paths = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".icc", ".icm"))
    except OSError:
        paths = []
    for path in paths:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if is_rgb(data):
            name = describe(data)
            if name not in {n for n, _ in found}:
                found.append((name, data))
    return found


def convert_array(rgba: np.ndarray, source: bytes, target: bytes, intent="relative", black_point=True) -> np.ndarray:
    """RGBA uint8 droit converti de `source` vers `target` (l'alpha est conservé tel quel)."""
    flags = ImageCms.Flags.BLACKPOINTCOMPENSATION if black_point else ImageCms.Flags.NONE
    transform = ImageCms.buildTransform(open_profile(source), open_profile(target), "RGB", "RGB",
                                        renderingIntent=INTENTS[intent][1], flags=flags)
    rgb = Image.fromarray(np.ascontiguousarray(rgba[..., :3]), "RGB")
    out = ImageCms.applyTransform(rgb, transform)
    result = rgba.copy()
    result[..., :3] = np.asarray(out, np.uint8)
    return result


def convert_color(color, source: bytes, target: bytes, intent="relative") -> list:
    pixel = np.array([[list(color[:3]) + [255]]], np.uint8)
    out = convert_array(pixel, source, target, intent)[0, 0]
    return [int(out[0]), int(out[1]), int(out[2])] + ([int(color[3])] if len(color) > 3 else [255])


def _planes(doc):
    for node in doc.walk():
        if node.pix is not None:
            yield node, node.pix


def assign(doc, data: bytes | None, name: str):
    """Assigne le profil (None = sans profil) SANS toucher aux pixels."""
    old = (doc.icc_profile, doc.icc_name)
    new = (data, name if data else "sRGB")

    def set_(state):
        doc.icc_profile, doc.icc_name = state
    set_(new)
    return CallCommand("Assigner le profil", lambda: set_(new), lambda: set_(old), rect=None)


def convert(doc, data: bytes, name: str, intent="relative", black_point=True):
    """Convertit TOUS les pixels (et les couleurs des sources de texte / forme) vers le profil `data`."""
    if not is_rgb(data):
        raise ValueError("Seuls les profils RVB sont pris en charge.")
    source = doc.icc_profile or srgb_bytes()
    old_state = [(plane, plane.x, plane.y, None if plane.data is None else plane.data.copy()) for _n, plane in _planes(doc)]
    old_sources = {id(n): (n, n.source) for n in doc.walk() if n.source}
    old_profile = (doc.icc_profile, doc.icc_name)
    new_state, new_sources = [], {}
    for node, plane in _planes(doc):
        new_state.append((plane, plane.x, plane.y,
                          None if plane.data is None else convert_array(plane.data, source, data, intent, black_point)))
    import copy
    for key, (node, src) in old_sources.items():
        moved = copy.deepcopy(src)
        for field in ("color", "fill", "stroke"):
            if moved.get(field):
                moved[field] = convert_color(moved[field], source, data, intent)
        new_sources[key] = (node, moved)

    def restore(states, sources, profile):
        for plane, x, y, array in states:
            if array is None:
                plane.clear()
            else:
                plane.set_all(x, y, array.copy())
        for node, src in sources.values():
            node.source = copy.deepcopy(src)
        doc.icc_profile, doc.icc_name = profile
    new_profile = (data, name)
    restore(new_state, new_sources, new_profile)
    return CallCommand("Convertir en profil " + name,
                       lambda: restore(new_state, new_sources, new_profile),
                       lambda: restore(old_state, old_sources, old_profile), rect=None)

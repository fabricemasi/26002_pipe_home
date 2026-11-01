"""Import de fichiers PSD (psd-tools, MIT, dépendance facultative). LECTURE SEULE : aucun export PSD n'est annoncé ni fait.

Lu : taille, calques de pixels (position, nom, visibilité, opacité), groupes (« passer à travers » ou isolé), modes de
fusion équivalents (normal, produit, écran, incrustation, lumière tamisée / forte, obscurcir, éclaircir, différence,
exclusion, addition = densité linéaire –), masques de calque (activé / désactivé, valeur hors cadre), masques d'écrêtage,
textes / formes / objets dynamiques comme PIXELS (le rendu stocké dans le fichier ; non éditables), résolution.
NON repris (chaque cas est signalé dans les notes, jamais en silence) : calques de réglage, styles de calque, masques
vectoriels, filtres dynamiques, modes de fusion sans équivalent (remplacés par « normal »), couleur CMJN / Lab / 16 et 32
bits (convertis en 8 bits RVB par psd-tools / Pillow, notes explicites), profil ICC (non extrait).
Si les calques sont illisibles, l'image composite du fichier est importée seule (note)."""
from __future__ import annotations

import numpy as np

from .io_images import ImageError
from .model import Document, Layer, Mask, new_uid
from .planes import Plane

SUPPORTED = None          # rempli au premier import (correspondance des modes de fusion)


def available() -> bool:
    try:
        import psd_tools  # noqa: F401
        return True
    except ImportError:
        return False


def _blend_map():
    from psd_tools.constants import BlendMode as B
    return {B.NORMAL: "normal", B.MULTIPLY: "multiply", B.SCREEN: "screen", B.OVERLAY: "overlay",
            B.SOFT_LIGHT: "softlight", B.HARD_LIGHT: "hardlight", B.DARKEN: "darken", B.LIGHTEN: "lighten",
            B.DIFFERENCE: "difference", B.EXCLUSION: "exclusion", B.LINEAR_DODGE: "add"}


def _pil_to_rgba(image) -> np.ndarray:
    return np.array(image.convert("RGBA"), np.uint8)


def read_psd(path):
    """(Document, notes). Lève `ImageError` (message lisible) si psd-tools manque ou si le fichier est invalide."""
    try:
        from psd_tools import PSDImage
        from psd_tools.constants import BlendMode
    except ImportError:
        raise ImageError("Import PSD indisponible : installez psd-tools (pip install psd-tools).") from None
    try:
        psd = PSDImage.open(str(path))
    except Exception as exc:                                             # noqa: BLE001 - fichier corrompu / non PSD
        raise ImageError(f"{getattr(path, 'name', path)} : fichier PSD illisible ({exc}).") from exc
    notes: list[str] = []
    name = str(getattr(path, "name", path))
    if psd.width < 1 or psd.height < 1 or psd.width > 30000 or psd.height > 30000:
        raise ImageError(f"{name} : dimensions PSD hors limites ({psd.width} × {psd.height}).")
    if psd.depth != 8:
        notes.append(f"{name} : profondeur {psd.depth} bits convertie en 8 bits.")
    mode = getattr(psd.color_mode, "name", str(psd.color_mode))
    if mode != "RGB":
        notes.append(f"{name} : mode colorimétrique {mode} converti en RVB 8 bits (couleurs approchées).")
    doc = Document(psd.width, psd.height, name=name.rsplit(".", 1)[0], dpi=72.0)
    mapping = _blend_map()
    lost: set[str] = set()

    def convert(node, depth=0) -> Layer | None:
        if depth > 64:
            lost.add("imbrication trop profonde")
            return None
        if node.is_group():
            layer = Layer(node.name or "Groupe", "group")
            layer.passthrough = node.blend_mode == BlendMode.PASS_THROUGH
            layer.children = [c for c in (convert(child, depth + 1) for child in node) if c is not None]
        else:
            kind = node.kind
            if kind in ("adjustment", "fill", "gradientfill", "patternfill", "solidcolorfill"):
                lost.add(f"calque de réglage / de remplissage « {node.name} »")
            image = node.topil() if node.has_pixels() else None
            if image is None:
                if kind not in ("adjustment", "fill", "gradientfill", "patternfill", "solidcolorfill"):
                    lost.add(f"calque « {node.name} » sans pixels")
                return None
            if kind in ("type", "smartobject", "shape"):
                lost.add(f"{ {'type': 'texte', 'smartobject': 'objet dynamique', 'shape': 'forme'}[kind] } « {node.name} » "
                         "importé comme pixels")
            layer = Layer(node.name or "Calque")
            layer.pix.set_all(int(node.left), int(node.top), _pil_to_rgba(image))
        layer.visible = bool(node.visible)
        layer.opacity = max(0.0, min(1.0, node.opacity / 255.0))
        if not node.is_group():
            blend = mapping.get(node.blend_mode)
            if blend is None:
                lost.add(f"mode de fusion « {getattr(node.blend_mode, 'name', node.blend_mode)} » (remplacé par normal)")
                blend = "normal"
            layer.blend = blend
        elif not layer.passthrough:
            blend = mapping.get(node.blend_mode)
            layer.blend = blend or "normal"
        layer.clip = bool(getattr(node, "clipping", False))
        layer.locked = False
        if node.has_effects():
            lost.add(f"styles de calque de « {node.name} »")
        if node.has_vector_mask():
            lost.add(f"masque vectoriel de « {node.name} »")
        if node.has_mask() and node.mask is not None:
            mask = node.mask
            try:
                image = mask.topil()
                if image is not None:
                    fill = int(getattr(mask, "background_color", 255) or 0)
                    layer.mask = Mask(Plane(1, fill if fill in (0, 255) else 255), enabled=not mask.disabled)
                    layer.mask.plane.set_all(int(mask.left), int(mask.top),
                                             np.array(image.convert("L"), np.uint8)[..., None])
            except Exception as exc:                                    # noqa: BLE001
                lost.add(f"masque de « {node.name} » illisible ({exc})")
        return layer

    try:
        doc.layers = [c for c in (convert(node) for node in psd) if c is not None]
    except Exception as exc:                                            # noqa: BLE001 - structure inattendue
        notes.append(f"{name} : calques illisibles ({exc}) ; image composite importée seule.")
        doc.layers = []
    if not doc.layers:
        try:
            layer = Layer("Composite")
            layer.pix.set_all(0, 0, _pil_to_rgba(psd.composite()))
            doc.layers = [layer]
            if not any("composite" in n for n in notes):
                notes.append(f"{name} : aucun calque lisible ; image composite importée.")
        except Exception as exc:                                        # noqa: BLE001
            raise ImageError(f"{name} : ni calques ni image composite lisibles ({exc}).") from exc
    for item in sorted(lost):
        notes.append(f"{name} : non repris — {item}.")
    return doc, notes

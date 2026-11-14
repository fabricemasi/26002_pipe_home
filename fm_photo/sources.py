"""Pixels SOURCE d'une photo pour le moteur : linéaire de travail float32, avec leur provenance déclarée.

Appelé HORS du fil de l'interface. Décodage par Qt (`QImageReader`, même orientation et même plafond que
l'image de la visionneuse : le rendu se superpose exactement à l'image décodée), en 16 bits par canal.
Espace d'entrée : le profil intégré s'il est reconnu (sRGB, Display P3, Adobe RGB, ProPhoto, Rec.2020 : décodé
par `couleur.py`) ; un autre profil est converti en sRGB par Qt (dit dans la provenance) ; sans profil, sRGB est
SUPPOSÉ (dit aussi). RAW : tant que le dématriçage n'est pas branché (registre FM_PHOTO_PROGRESS.md), la source
est le JPEG intégré, marquée PROVISOIRE : déjà développée par le boîtier, 8 bits, sans latitude."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColorSpace, QImage, QImageReader

from config import RAW_EXTENSIONS
from fm_photo import couleur

COTE_MAX = 8192                      # même plafond que FocusImageLoader.MAX_SIDE


@dataclass
class Source:
    pixels: np.ndarray               # (H, L, 3) float32, linéaire de travail
    provenance: str                  # texte montré à l'utilisateur
    provisoire: bool                 # True : pas la donnée la plus fidèle disponible (JPEG intégré d'un RAW)
    espace_entree: str               # clé de couleur.ESPACES
    cle: int = field(default_factory=itertools.count(1).__next__)    # nom de la source pour les caches du moteur

    @property
    def octets(self) -> int:
        return int(self.pixels.nbytes)


_PRIMAIRES = {QColorSpace.Primaries.SRgb: "srgb", QColorSpace.Primaries.DciP3D65: "display_p3",
              QColorSpace.Primaries.AdobeRgb: "adobe_rgb", QColorSpace.Primaries.ProPhotoRgb: "prophoto"}
_TRANSFERTS_QT = {"srgb": QColorSpace.TransferFunction.SRgb, "display_p3": QColorSpace.TransferFunction.SRgb,
                  "adobe_rgb": QColorSpace.TransferFunction.Gamma, "prophoto": QColorSpace.TransferFunction.ProPhotoRgb}


def espace_de(image: QImage) -> tuple[str | None, str]:
    """(clé de couleur.ESPACES ou None si le profil n'est pas reconnu, texte de provenance)."""
    profil = image.colorSpace()
    if not profil.isValid():
        return "srgb", "sRGB supposé (aucun profil intégré)"
    espace = _PRIMAIRES.get(profil.primaries())
    if espace is not None and profil.transferFunction() == _TRANSFERTS_QT[espace]:
        if espace != "adobe_rgb" or abs(profil.gamma() - 2.2) < 0.01:
            return espace, f"profil intégré {couleur.ESPACES[espace].nom}"
    return None, f"profil intégré « {profil.description() or 'sans nom'} » converti en sRGB par Qt"


def image_vers_tableau(image: QImage) -> np.ndarray:
    """QImage -> (H, L, 3) float32 dans [0, 1], encodé comme l'image (16 bits par canal lus)."""
    image = image.convertToFormat(QImage.Format_RGBX64)
    hauteur, largeur = image.height(), image.width()
    brut = np.frombuffer(image.constBits(), dtype=np.uint16, count=hauteur * image.bytesPerLine() // 2)
    lignes = brut.reshape(hauteur, image.bytesPerLine() // 2)[:, :largeur * 4].reshape(hauteur, largeur, 4)
    return lignes[..., :3].astype(np.float32) / np.float32(65535.0)


def depuis_image(image: QImage, provenance: str = "", provisoire: bool = False) -> Source:
    espace, texte = espace_de(image)
    if espace is None:
        image = image.convertToFormat(QImage.Format_RGBX64)
        image.convertToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
        espace = "srgb"
    pixels = couleur.vers_travail(image_vers_tableau(image), espace)
    return Source(np.ascontiguousarray(pixels, dtype=np.float32), f"{provenance}{texte}", provisoire, espace)


def charger(chemin: Path) -> Source | None:
    """Source de ce fichier, ou None s'il est illisible."""
    chemin = Path(chemin)
    if chemin.suffix.lower() in RAW_EXTENSIONS:
        import previews
        image, _transformation = previews._decode_embedded_jpeg(chemin, COTE_MAX, include_transform=True)
        if image is None or image.isNull():
            return None
        return depuis_image(image, "JPEG intégré au RAW (provisoire, sans dématriçage) ; ", provisoire=True)
    lecteur = QImageReader(str(chemin))
    lecteur.setAutoTransform(True)
    taille = lecteur.size()
    if taille.isValid() and max(taille.width(), taille.height()) > COTE_MAX:
        lecteur.setScaledSize(taille.scaled(COTE_MAX, COTE_MAX, Qt.KeepAspectRatio))
    image = lecteur.read()
    if image.isNull():
        return None
    return depuis_image(image, "Original ; ")

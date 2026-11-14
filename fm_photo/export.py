"""Export d'une photo développée : mêmes opérations et mêmes paramètres que l'aperçu, en pleine définition.

Appelé HORS du fil de l'interface. Un `Travail` FIGE ce qui sera exporté au moment où il est créé (copie de la
suite d'opérations) : une retouche faite ensuite ne change pas un export en attente. Le fichier est écrit sous un
nom provisoire dans le dossier de destination puis renommé d'un seul geste : un fichier au nom final est toujours
complet ; une annulation ou une erreur ne laisse rien. Une destination existante n'est JAMAIS remplacée, et la
source n'est jamais une destination possible.

Formats : JPEG (8 bits), TIFF et PNG (8 ou 16 bits), profil de l'espace de sortie intégré. Aucune réduction de
qualité implicite ; la file d'attente, le lot et la reprise sont au registre (FM_PHOTO_PROGRESS.md)."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtGui import QColorSpace, QImage, QImageWriter

from fm_photo import etat, moteur, operations, sources

FORMATS = {".jpg": ("jpeg", (8,)), ".jpeg": ("jpeg", (8,)), ".tif": ("tiff", (8, 16)), ".tiff": ("tiff", (8, 16)),
           ".png": ("png", (8, 16))}
_PROFILS = {"srgb": QColorSpace.NamedColorSpace.SRgb, "display_p3": QColorSpace.NamedColorSpace.DisplayP3,
            "adobe_rgb": QColorSpace.NamedColorSpace.AdobeRgb, "prophoto": QColorSpace.NamedColorSpace.ProPhotoRgb}


class ExportImpossible(Exception):
    pass


@dataclass
class Travail:
    source: Path
    destination: Path
    suite: list                              # opérations figées (copie profonde)
    espace: str = "srgb"
    bits: int = 8
    qualite: int = 95                        # JPEG seulement
    signature: str = field(default="", init=False)

    def __post_init__(self):
        self.source, self.destination = Path(self.source), Path(self.destination)
        self.suite = copy.deepcopy(self.suite)
        self.signature = etat.signature(self.suite)
        extension = self.destination.suffix.lower()
        if extension not in FORMATS:
            raise ExportImpossible(f"Format non pris en charge : {extension or '(sans extension)'}")
        if self.bits not in FORMATS[extension][1]:
            raise ExportImpossible(f"{extension} : {self.bits} bits non pris en charge")
        if self.espace not in _PROFILS:
            raise ExportImpossible(f"Espace de sortie non pris en charge : {self.espace}")
        if os.path.normcase(os.path.abspath(self.source)) == os.path.normcase(os.path.abspath(self.destination)):
            raise ExportImpossible("La destination est l'original.")


def _image(code: np.ndarray) -> QImage:
    hauteur, largeur = code.shape[:2]
    if code.dtype == np.uint16:
        tampon = np.full((hauteur, largeur, 4), 65535, dtype=np.uint16)
        tampon[..., :3] = code
        return QImage(tampon.data, largeur, hauteur, largeur * 8, QImage.Format_RGBX64).copy()
    tampon = np.ascontiguousarray(code)
    return QImage(tampon.data, largeur, hauteur, largeur * 3, QImage.Format_RGB888).copy()


def _ecrire(image: QImage, chemin: Path, nom_format: str, qualite: int) -> str:
    """Écrit l'image ; renvoie le texte de l'erreur, vide si tout va bien. L'écrivain Qt garde le fichier ouvert
    tant qu'il vit : il meurt ici, avant le renommage."""
    ecrivain = QImageWriter(str(chemin), nom_format.encode("ascii"))
    if nom_format == "jpeg":
        ecrivain.setQuality(int(qualite))
    elif nom_format == "tiff":
        ecrivain.setCompression(1)           # LZW : sans perte
    return "" if ecrivain.write(image) else (ecrivain.errorString() or "erreur inconnue")


def exporter(travail: Travail, annule=None, source: sources.Source | None = None) -> Path:
    """Écrit le fichier et renvoie son chemin. `operations.Annule` si abandonné, `ExportImpossible` sinon."""
    destination = travail.destination
    if destination.exists():
        raise ExportImpossible(f"{destination.name} existe déjà.")
    source = source or sources.charger(travail.source)
    if source is None:
        raise ExportImpossible(f"{travail.source.name} est illisible.")
    code = moteur.rendre_export(source.pixels, travail.suite, travail.espace, travail.bits, annule)
    image = _image(code)
    image.setColorSpace(QColorSpace(_PROFILS[travail.espace]))
    provisoire = destination.with_name(f".{destination.stem}.partiel{destination.suffix}")
    try:
        if annule and annule():
            raise operations.Annule()
        erreur = _ecrire(image, provisoire, FORMATS[destination.suffix.lower()][0], travail.qualite)
        if erreur:
            raise ExportImpossible(f"Écriture impossible : {erreur}")
        if annule and annule():
            raise operations.Annule()
        if destination.exists():             # apparue pendant le calcul : on ne remplace rien
            raise ExportImpossible(f"{destination.name} existe déjà.")
        os.replace(provisoire, destination)
    finally:
        provisoire.unlink(missing_ok=True)
    return destination

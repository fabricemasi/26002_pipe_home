"""Écrit les mires du banc comparatif photo (TIFF 16 bits sRGB + fiche JSON) dans un dossier.

    python tools/mires_photo.py DOSSIER

Les fichiers produits sont les SOURCES à passer dans le logiciel de référence (Dehancer, DxO FilmPack) : même
fichier, paramètres relevés, export TIFF 16 bits sans redimensionnement. Protocole et seuils :
docs/agents/fm_film_protocole.md. Rien n'est remplacé : un fichier existant arrête l'outil."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColorSpace, QGuiApplication

from fm_photo import couleur, export, mires


def ecrire(dossier: Path) -> list:
    dossier.mkdir(parents=True, exist_ok=True)
    ecrits = []
    for nom, (image, pastilles) in (("mire_tonale", mires.mire_tonale()), ("mire_couleurs", mires.mire_couleurs())):
        fichier, fiche = dossier / f"{nom}.tif", dossier / f"{nom}.json"
        if fichier.exists() or fiche.exists():
            raise SystemExit(f"{fichier.name} existe déjà : rien n'est remplacé.")
        code = couleur.quantifier(couleur.depuis_travail(image, "srgb"), 16)
        tiff = export._image(code)
        tiff.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
        erreur = export._ecrire(tiff, fichier, "tiff", 100)
        if erreur:
            raise SystemExit(f"{fichier.name} : {erreur}")
        fiche.write_text(json.dumps(mires.description(pastilles, fichier=fichier.name,
                                                      dimensions=[image.shape[1], image.shape[0]]),
                                    ensure_ascii=False, indent=1), encoding="utf-8")
        ecrits += [fichier, fiche]
    return ecrits


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    _app = QGuiApplication.instance() or QGuiApplication([])
    for chemin in ecrire(Path(sys.argv[1])):
        print(chemin)

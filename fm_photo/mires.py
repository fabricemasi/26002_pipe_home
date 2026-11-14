"""Mires synthétiques du banc comparatif : sources IDENTIQUES pour PIPE FMZ et pour une référence (sans Qt).

Une mire = une image en linéaire de travail faite de pastilles carrées de valeur connue + la liste de ces
pastilles (rectangle, valeur). La même image, exportée en TIFF 16 bits sRGB, est passée dans le logiciel de
référence (Dehancer, FilmPack…) puis relue : `lire_pastilles` moyenne le CENTRE de chaque pastille (la moitié de
son côté : les bords, où un traitement spatial déborde, sont exclus). Protocole : docs/agents/fm_film_protocole.md.

- `mire_tonale` : gris neutres par tiers de diaphragme, du plus sombre au blanc de l'encodage (1,0 linéaire) ;
  le gris 18 % est une pastille exacte. Un TIFF sRGB ne porte rien au-dessus de 1,0 : la latitude en hautes
  lumières se mesure sur des sources RAW ou EXR, pas ici.
- `mire_couleurs` : teintes régulières à plusieurs clartés et saturations (Oklab), SEULEMENT celles que sRGB peut
  encoder (les autres sont omises, pas écrêtées)."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from fm_photo import couleur, warper

FOND = 0.18                      # gris de séparation entre les pastilles (linéaire)


@dataclass
class Pastille:
    nom: str
    x: int
    y: int
    cote: int
    valeur: tuple                # linéaire de travail (r, v, b)


def _assembler(valeurs: list, noms: list, colonnes: int, cote: int, marge: int) -> tuple[np.ndarray, list]:
    lignes = math.ceil(len(valeurs) / colonnes)
    pas = cote + marge
    image = np.full((lignes * pas + marge, colonnes * pas + marge, 3), FOND, dtype=np.float32)
    pastilles = []
    for rang, (valeur, nom) in enumerate(zip(valeurs, noms)):
        x, y = marge + (rang % colonnes) * pas, marge + (rang // colonnes) * pas
        image[y:y + cote, x:x + cote] = np.asarray(valeur, dtype=np.float32)
        pastilles.append(Pastille(nom, x, y, cote, tuple(float(composante) for composante in valeur)))
    return image, pastilles


def mire_tonale(tiers_sous_le_blanc: int = 36, cote: int = 96, marge: int = 16, colonnes: int = 8) -> tuple:
    """Gris de 1,0 (blanc de l'encodage) à 2^(-tiers / 3), par tiers de diaphragme, + le gris 18 % exact."""
    expositions = [-(rang / 3.0) for rang in range(tiers_sous_le_blanc + 1)]
    valeurs = [(2.0 ** ev,) * 3 for ev in expositions] + [(0.18,) * 3]
    noms = [f"gris {ev:+.2f} EV" for ev in expositions] + ["gris 18 %"]
    return _assembler(valeurs, noms, colonnes, cote, marge)


def mire_couleurs(teintes: int = 12, clartes=(0.45, 0.65, 0.85), chromas=(0.04, 0.08, 0.12, 0.16),
                  cote: int = 96, marge: int = 16) -> tuple:
    """Pastilles Oklab (clarté, chroma, teinte) encodables en sRGB ; une ligne par couple clarté / chroma."""
    vers_srgb = couleur.matrice(couleur.TRAVAIL, "srgb")
    valeurs, noms = [], []
    for clarte in clartes:
        for chroma in chromas:
            for rang in range(teintes):
                angle = 2.0 * np.pi * rang / teintes
                lineaire = warper.depuis_oklab(np.array([clarte, chroma * np.cos(angle), chroma * np.sin(angle)]))
                srgb = vers_srgb @ lineaire
                if srgb.min() >= 0.0 and srgb.max() <= 1.0:
                    valeurs.append(tuple(lineaire))
                    noms.append(f"L {clarte:.2f} C {chroma:.2f} h {360 * rang // teintes:03d}")
    return _assembler(valeurs, noms, teintes, cote, marge)


def lire_pastilles(image: np.ndarray, pastilles: list) -> np.ndarray:
    """Moyenne (N, 3) du centre de chaque pastille d'une image de mêmes dimensions que la mire."""
    moyennes = []
    for pastille in pastilles:
        retrait = pastille.cote // 4
        zone = image[pastille.y + retrait:pastille.y + pastille.cote - retrait,
                     pastille.x + retrait:pastille.x + pastille.cote - retrait]
        moyennes.append(zone.reshape(-1, 3).mean(axis=0, dtype=np.float64))    # float32 : erreur de somme ~1e-5
    return np.asarray(moyennes)


def attendues(pastilles: list) -> np.ndarray:
    return np.asarray([pastille.valeur for pastille in pastilles], dtype=np.float64)


def description(pastilles: list, **informations) -> dict:
    """Fiche JSON d'une mire : ce qu'il faut pour relire un export sans cette session."""
    return {"schema": 1, "espace": "linéaire de travail Rec.2020 D65 (valeurs) ; fichier : sRGB 16 bits",
            "fond": FOND, "pastilles": [asdict(pastille) for pastille in pastilles], **informations}

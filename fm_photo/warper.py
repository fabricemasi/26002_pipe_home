"""Color Warper Teinte / Saturation : maillage polaire dans le plan chromatique, RÉFÉRENCE numpy (sans Qt).

Modèle : Oklab (B. Ottosson, 2020, formules publiées, domaine public) calculé depuis le linéaire de travail par
XYZ D65. Le plan (a, b) est la chromaticité perceptuelle : teinte = angle, saturation = rayon (chroma) ; la clarté L
n'est PAS modifiée par cet outil (le Warper Chroma / Luma en est un autre, au registre).

Maillage : `anneaux` cercles de chroma de 0 (axe neutre) à `chroma_max`, `teintes` rayons régulièrement espacés,
cycliques. Chaque nœud porte un DÉPLACEMENT (da, db) dans le plan — cartésien, donc sans problème de raccord
d'angle. Contrats, tous testés :
- maillage nul = identité exacte (l'image est rendue telle quelle) ;
- les nœuds de l'axe neutre ne se déplacent jamais : un gris reste gris ;
- un point posé sur un nœud se déplace exactement du déplacement du nœud (interpolation Catmull-Rom, C1, cyclique
  en teinte, bornée en chroma) ; au-delà de `chroma_max`, le déplacement du dernier anneau s'applique ;
- continuité partout, raccord 0 / 2 pi compris ; à l'axe neutre la transformation est continue mais pas dérivable
  (propre à tout maillage polaire) ;
- `replis` mesure la part du plan où la transformation se retourne (déterminant du jacobien <= 0) : un repli
  mélange des couleurs distinctes, l'interface doit le signaler au lieu de le laisser passer.
Les couleurs sorties du gamut ne sont pas écrêtées ici (voir `couleur.depuis_travail`)."""
from __future__ import annotations

import numpy as np

from fm_photo import couleur, operations

# Oklab : XYZ (D65) -> LMS, puis racine cubique, puis LMS' -> Lab (matrices publiées par l'auteur).
_M1 = np.array([[0.8189330101, 0.3618667424, -0.1288597137],
                [0.0329845436, 0.9293118715, 0.0361456387],
                [0.0482003018, 0.2643662691, 0.6338517070]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])


# LMS du blanc de travail (R = V = B = 1). Les matrices publiées ne placent pas CE blanc exactement sur l'axe
# neutre (a, b ~ 3e-5) : un gris recevait un déplacement infime du maillage. LMS est donc normalisé à ce blanc
# avant la racine cubique : R = V = B donne a = b = 0 (à 4e-8 près) ; l'écart à l'Oklab publié reste < 2e-4.
_BLANC_LMS = _M1 @ couleur.matrice_rgb_xyz(couleur.TRAVAIL) @ np.ones(3)


def vers_oklab(lineaire: np.ndarray) -> np.ndarray:
    """Linéaire de travail -> Oklab (float64 ; racine cubique impaire : les négatifs ne donnent pas de NaN)."""
    xyz = np.asarray(lineaire, dtype=np.float64) @ couleur.matrice_rgb_xyz(couleur.TRAVAIL).T
    return np.cbrt(xyz @ _M1.T / _BLANC_LMS) @ _M2.T


def depuis_oklab(lab: np.ndarray) -> np.ndarray:
    lms = (np.asarray(lab, dtype=np.float64) @ np.linalg.inv(_M2).T) ** 3 * _BLANC_LMS
    return lms @ np.linalg.inv(_M1).T @ np.linalg.inv(couleur.matrice_rgb_xyz(couleur.TRAVAIL)).T


def maillage_nul(anneaux: int = 4, teintes: int = 12) -> np.ndarray:
    """Déplacements (anneaux + 1, teintes, 2) : la ligne 0 est l'axe neutre (toujours nulle)."""
    return np.zeros((anneaux + 1, teintes, 2), dtype=np.float64)


def noeud(anneau: int, teinte: int, anneaux: int, teintes: int, chroma_max: float) -> tuple[float, float]:
    """Position (a, b) d'un nœud du maillage au repos."""
    angle, rayon = 2.0 * np.pi * teinte / teintes, chroma_max * anneau / anneaux
    return rayon * np.cos(angle), rayon * np.sin(angle)


def _poids(t: np.ndarray) -> list:
    """Poids de Catmull-Rom des 4 voisins (-1, 0, 1, 2) pour une position t dans [0, 1[."""
    t2, t3 = t * t, t * t * t
    return [(-t3 + 2 * t2 - t) / 2, (3 * t3 - 5 * t2 + 2) / 2, (-3 * t3 + 4 * t2 + t) / 2, (t3 - t2) / 2]


def deplacement(a: np.ndarray, b: np.ndarray, maillage: np.ndarray, chroma_max: float) -> tuple:
    """Déplacement (da, db) interpolé aux points (a, b) du plan."""
    maillage = np.array(maillage, dtype=np.float64)
    maillage[0] = 0.0                                    # l'axe neutre ne bouge jamais
    anneaux, teintes = maillage.shape[0] - 1, maillage.shape[1]
    u = np.minimum(np.hypot(a, b) / chroma_max * anneaux, anneaux)
    v = np.mod(np.arctan2(b, a) / (2.0 * np.pi) * teintes, teintes)
    i0, j0 = np.minimum(np.floor(u).astype(np.intp), anneaux), np.floor(v).astype(np.intp) % teintes
    poids_u, poids_v = _poids(u - i0), _poids(v - np.floor(v))
    total = np.zeros(a.shape + (2,), dtype=np.float64)
    for di in range(4):
        ligne = np.clip(i0 + di - 1, 0, anneaux)
        for dj in range(4):
            colonne = (j0 + dj - 1) % teintes
            total += (poids_u[di] * poids_v[dj])[..., None] * maillage[ligne, colonne]
    return total[..., 0], total[..., 1]


def deformer(lab: np.ndarray, maillage: np.ndarray, chroma_max: float) -> np.ndarray:
    da, db = deplacement(lab[..., 1], lab[..., 2], maillage, chroma_max)
    sortie = np.array(lab, dtype=np.float64)
    sortie[..., 1] += da
    sortie[..., 2] += db
    return sortie


def replis(maillage: np.ndarray, chroma_max: float, finesse: int = 96) -> float:
    """Part (0 à 1) du disque de chroma où la transformation du plan se retourne ou s'écrase."""
    axe = np.linspace(-chroma_max, chroma_max, finesse)
    a, b = np.meshgrid(axe, axe)
    pas = (axe[1] - axe[0]) * 0.25
    def image(x, y):
        dx, dy = deplacement(x, y, maillage, chroma_max)
        return x + dx, y + dy
    xa, ya = image(a + pas, b)
    xb, yb = image(a - pas, b)
    xc, yc = image(a, b + pas)
    xd, yd = image(a, b - pas)
    determinant = ((xa - xb) * (yc - yd) - (xc - xd) * (ya - yb)) / (4 * pas * pas)
    dedans = np.hypot(a, b) <= chroma_max
    return float((determinant[dedans] <= 0).mean())


def _appliquer(image, params, contexte):
    maillage = np.asarray(params["deplacements"], dtype=np.float64)
    if maillage.size == 0 or not np.any(maillage[1:]):
        return image
    lab = deformer(vers_oklab(image), maillage, float(params["chroma_max"]))
    return depuis_oklab(lab).astype(np.float32)


operations.declarer(operations.Definition(
    "warper_teinte_saturation", 1, "Color Warper Teinte / Saturation", {"deplacements": [], "chroma_max": 0.4},
    _appliquer, bornes={"chroma_max": (0.05, 0.6)},
    notes="`deplacements` : liste (anneaux + 1) x teintes x 2 de déplacements Oklab (a, b), ligne 0 = axe neutre. "
          "Ponctuelle (aucune marge). Pipette, maillage interactif et Warper Chroma / Luma : au registre."))

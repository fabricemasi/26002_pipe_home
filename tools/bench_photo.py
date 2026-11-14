"""Banc du moteur photo (`fm_photo`) : latences de rendu, délai d'annulation, mémoire et copies.

    python tools/bench_photo.py [--mp 24 40] [--rapide]

Mesure, pour une photo synthétique de N mégapixels (3:2) et la chaîne « exposition + diffusion » :
- l'aperçu PROVISOIRE (grand côté <= 1024 px) et le rendu à la définition d'un écran 2560 x 1440 ;
- la pleine définition (export) ; le délai entre une annulation et l'arrêt du calcul ;
- les octets de la source float32 et du tampon d'affichage (copies : 1 à l'entrée, 1 à la sortie).
Budgets (docs/agents/fm_photo.md, « Fluidité ») : provisoire < 100 ms, annulation < 50 ms. L'exécutant est celui
de `fm_photo.moteur.EXECUTANT` : la référence numpy tant que le moteur Rust n'est pas construit."""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from fm_photo import moteur, operations

SUITE = [{"op": "exposition", "version": 1, "actif": True, "params": {"ev": 0.5}},
         {"op": "diffusion", "version": 1, "actif": True, "params": {"quantite": 0.6, "rayon": 0.5}}]


def _photo(megapixels: float) -> np.ndarray:
    hauteur = int(round((megapixels * 1e6 / 1.5) ** 0.5))
    largeur = int(hauteur * 1.5)
    rng = np.random.default_rng(1)
    image = rng.random((hauteur, largeur, 3), dtype=np.float32)
    image[hauteur // 3:hauteur // 3 + 40, largeur // 2:largeur // 2 + 40] = 8.0
    return image


def _chrono(fonction):
    debut = time.perf_counter()
    resultat = fonction()
    return resultat, (time.perf_counter() - debut) * 1000.0


def mesurer(megapixels: float, pleine: bool) -> None:
    pixels = _photo(megapixels)
    hauteur, largeur = pixels.shape[:2]
    print(f"\n{megapixels:g} MP ({largeur} x {hauteur}) — exécutant : {moteur.EXECUTANT} — "
          f"source float32 : {pixels.nbytes / 2**20:.0f} Mo")
    rapide = moteur.facteur_rapide(largeur, hauteur)
    ecran = moteur.facteur_pour(largeur, hauteur, 2560, 1440)
    tampon, duree = _chrono(lambda: moteur.rendre_affichage(pixels, SUITE, rapide))
    print(f"  aperçu provisoire 1/{rapide} : {duree:7.1f} ms   (budget 100 ms)   tampon {tampon.nbytes / 2**20:.1f} Mo")
    tampon, duree = _chrono(lambda: moteur.rendre_affichage(pixels, SUITE, ecran))
    print(f"  définition écran 1/{ecran}   : {duree:7.1f} ms                      tampon {tampon.nbytes / 2**20:.1f} Mo")

    arret = threading.Event()
    instants = {}

    def annulable():
        try:
            moteur.rendre_affichage(pixels, SUITE, ecran, arret.is_set)
        except operations.Annule:
            instants["fin"] = time.perf_counter()

    fil = threading.Thread(target=annulable)
    fil.start()
    time.sleep(min(0.05, duree / 2000.0))
    instants["demande"] = time.perf_counter()
    arret.set()
    fil.join()
    if "fin" in instants:
        print(f"  annulation -> arrêt        : {(instants['fin'] - instants['demande']) * 1000.0:7.1f} ms   (budget 50 ms)")
    else:
        print("  annulation -> arrêt        : le rendu était déjà fini")
    if pleine:
        _code, duree = _chrono(lambda: moteur.rendre_export(pixels, SUITE, "srgb", 16))
        print(f"  pleine définition 16 bits  : {duree:7.1f} ms   ({megapixels * 1000.0 / duree:.1f} MP/s)")


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser()
    analyseur.add_argument("--mp", type=float, nargs="+", default=[24.0, 40.0])
    analyseur.add_argument("--rapide", action="store_true", help="sans la pleine définition")
    choix = analyseur.parse_args()
    for megapixels in choix.mp:
        mesurer(megapixels, not choix.rapide)

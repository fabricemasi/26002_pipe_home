# FM Film : protocole du banc comparatif et seuils (fixés AVANT toute calibration)

Écrit le 2026-11-14, avant qu'aucun outil FM Film n'existe. Les seuils ci-dessous ne se modifient pas après coup
pour faire accepter un résultat : un seuil jugé mal choisi se change ICI, daté et motivé, AVANT de relancer la
comparaison. Références : `fm_film_references.md` ; outils : `fm_photo/mires.py`, `fm_photo/mesures.py`,
`tools/mires_photo.py` ; tests `test_photo_mesures`.

## Quatre évaluations, jamais confondues

| Évaluation | Preuve exigée | Ce qu'elle ne prouve pas |
|---|---|---|
| Compatibilité fonctionnelle | mêmes paramètres, mêmes unités, mêmes dépendances que la référence (matrice) | que les images se ressemblent |
| Proximité visuelle mesurée | écarts sous les seuils, sur le corpus de VALIDATION, version de référence nommée | une équivalence perceptuelle |
| Plausibilité physique | accord avec les données du fabricant du film / support citées | une ressemblance avec Dehancer |
| Équivalence validée | proximité mesurée + évaluation humaine à l'aveugle, conditions écrites | sa validité hors de ces conditions |

## Produire une référence (à faire par l'utilisateur, logiciel sous licence)

1. `python tools/mires_photo.py <dossier>` : `mire_tonale.tif`, `mire_couleurs.tif` (TIFF 16 bits sRGB, profil
   intégré) et leurs fiches JSON. Y ajouter les photos du corpus (TIFF 16 bits, mêmes règles).
2. Dans le logiciel de référence : noter produit, édition, version / build, hôte, version des profils ; réglage de
   la source = sRGB (à relever tel qu'affiché) ; TOUT couper sauf l'outil étudié (grain, halation, bloom, vignette,
   dommages à zéro ou coupés) ; relever chaque paramètre affiché.
3. Exporter en TIFF 16 bits, mêmes dimensions, sans redimensionnement ni accentuation de sortie ; nommer
   `<mire>__<outil>__<paramètres>.tif` ; joindre un fichier texte des réglages relevés.
4. Un export par valeur étudiée : neutre, minimum, maximum, et au moins trois valeurs intermédiaires par paramètre.

## Corpus

- CALIBRATION : les deux mires + la moitié des photos (tirage au sort noté dans le dossier).
- VALIDATION : l'autre moitié des photos, jamais regardée pendant la calibration ; portraits (peaux), paysages,
  couleurs saturées, basses lumières, contre-jours, textures.
- Limite connue : un TIFF sRGB ne porte rien au-dessus du blanc ; hautes lumières et latitude se mesurent sur des
  sources RAW / EXR, quand la chaîne RAW existe.

## Seuils (Delta E 2000, linéaire de travail -> CIELAB D65, `mesures.comparer`)

| Objet | Médiane | 95e centile | Maximum | Justification |
|---|---|---|---|---|
| Vérification d'une optimisation (Rust, GPU, LUT) contre la référence numpy | 0,1 | 0,2 | 0,5 | invisible ; marge sur l'arrondi 8 bits (~0,3 au pire dans les ombres) |
| Tonalité et couleur d'un outil sans composante aléatoire, contre un export de référence (pastilles) | 1,0 | 2,5 | 5,0 | 1 ~ seuil de perception côte à côte ; 2,5 visible à l'examen ; 5 = couleur nettement différente |
| Photos de validation, même outil (pixel à pixel, hors grain / halo) | 1,5 | 4,0 | — (rapporté, non éliminatoire) | détails fins et bords : le pire pixel n'est pas représentatif |

Gris neutres de la mire tonale, en plus : écart de clarté |dL*| <= 1,0 sur chaque pastille, et chroma C* <= 1,0 là
où la référence est neutre.

Grain, halation, bloom : PAS de Delta E pixel à pixel. Grain : moyenne et variance par niveau, autocorrélation,
spectre de puissance radial, corrélation entre canaux, à plusieurs résolutions. Halation / bloom : profil radial
d'une source ponctuelle et d'une marche de contraste (étendue à 50 %, 10 %, 1 % ; énergie ; couleur). Leurs
seuils seront écrits ici AVANT leur première comparaison.

## Compte rendu d'une comparaison

Référence (produit, version, hôte, profil), source, paramètres des deux côtés, médiane / p95 / p99 / maximum, pire
pastille nommée, verdict par évaluation (tableau du haut), limites. Un seul exemple ne fonde aucune fidélité.

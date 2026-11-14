# FM Film : matrice des références (Dehancer, DxO FilmPack, fabricants)

Recherche du 2026-11-14, documentation PUBLIQUE seulement. **[doc]** = affirmé par la documentation de l'éditeur ; **[donnée fabricant]** = fiche Kodak / Fujifilm ; **[à vérifier]** = absent de la doc, à mesurer dans le logiciel ; « n.d. » = non documenté. Pages lues par un outil de résumé : relire la source avant de figer une valeur.

## Carte

1. Carte.
2. Produits Dehancer : hôtes, versions lues, outils par produit.
3. Outils Dehancer : paramètres, outil par outil (a à h, puis les autres).
4. PRINT : supports, paramètres, méthode, données physiques 2383 / 3513DI / Endura.
5. Ordre des opérations : ce que la doc dit et ne dit pas.
6. DxO FilmPack 8.
7. Lacunes et vérifications à faire ; liens à la fin.

## 2. Produits Dehancer

| Produit | Hôtes / système [doc] | Dernière version lue | Source |
|---|---|---|---|
| Pro OFX | DaVinci Resolve 19+ (macOS 13+), 18+ (Windows, Linux) | 7.4.1, 30 juin 2026 ; une 8.0.0 Beta 1 existe (non datée) | [versions][v-ofx], [Acutance][acut] |
| Pro Ae / Pr | Premiere Pro 2022+, After Effects 2021+ | 7.4.1, 30 juin 2026 | [versions][v-aepr] |
| Pro FCP | Final Cut Pro 11 ou 12 | 7.4.2, 2 juil. 2026 | [versions][v-fcp] |
| Film (module photo) | Photoshop, Lightroom, Capture One, Affinity (bêta) ; macOS 15+, Windows 10/11 ; fichiers sRGB | 2.8.0, 24 févr. 2026 | [versions][v-photo] |
| Desktop | autonome, macOS 15+, Windows 10/11 ; RAW (LibRaw, Apple), JPEG, TIFF, PNG | annoncé le 9 avr. 2026 ; **version NON confirmée** (pages en 404 ; un résultat de recherche citait 1.0.0) | [blog][desk-blog], [manuel][desk] |

Baselight, SCRATCH, Vegas, Lite, iOS, Online : versions non lues ([config][sysreq]).

Outils par produit (« oui » = lu dans la source ; « n.d. » = la doc ne dit rien) :

| Outil | Pro (vidéo) | Film (photo) | Desktop |
|---|---|---|---|
| Input / Source, Defringe | oui | oui | oui (+ Darks, Lights) |
| Film Profiles, Push/Pull | oui (60+ films) | oui (60+, 86 préréglages) | oui |
| Film Developer | 6.3.0 (24 févr. 2023) | 2.3.2 (24 févr. 2023) | oui |
| Film Compression | 6.2.0 (27 nov. 2022) | 2.3.0 (27 nov. 2022) | oui |
| Expand, Print, CMY Color Head | oui (supports de tirage : 5.0.0, 1 nov. 2021) | oui | oui |
| Grain, Halation, Bloom, Vignette | oui | oui | oui |
| Film Damage | 7.0.0 (10 juin 2023) | 2.5.0 (23 mai 2024) | oui |
| Overscan | 7.1.0 (12 déc. 2023) | 2.6.0 (18 juil. 2024) | oui |
| Film Breath, Gate Weave | oui | n.d. | absents du manuel |
| Acutance with Skin Mask | 8.0.0 Beta 1 | n.d. | oui |
| LUT Generator, False Color | oui | n.d. | absents (écrêtage dans l'Inspector) |

Sources : pages « versions » et [manuel Desktop][desk]. Entrées : Rec.709, Rec.2020 SDR, ACEScct, DWG, Cineon Film Log côté Pro ; sRGB seul côté photo [doc] ([espaces][cs]).

## 3. Outils Dehancer : paramètres

Presque aucune plage ni défaut dans la doc : chaque « n.d. » est à mesurer (section 7).

### Input ([page][in])

| Paramètre | Rôle (doc) | Plage / défaut | Marque |
|---|---|---|---|
| Source | interprétation de l'entrée ; la sortie reprend l'espace d'entrée | liste | [doc] |
| Choose Camera | profil de caméra (Log ou RAW) | liste, 130+ | [doc] |
| Exposure Comp. ; Temperature Comp., Tint Comp. | corrections techniques de la source, appliquées avec sa conversion | n.d. | [doc] [à vérifier] |
| Defringe (Amount, Radius) | aberration chromatique ; halos possibles avec Bloom / Halation | n.d. | [doc] [à vérifier] |

### (h) Film Profiles et Push/Pull ([page][fp], [article][pp], [construction][build])

| Paramètre | Rôle (doc) | Plage / défaut | Marque |
|---|---|---|---|
| liste de films | 60+ profils ; négatifs N&B tirés sur papier Slavich Bromportrait | — | [doc] |
| Push/Pull (Ev) | exposition du film : couleur et contraste (négatif), densité (inversible) | −2 à +2 Ev ; pas, défaut n.d. | [doc] [à vérifier] |

Nature [doc] : chaque profil réunit TROIS profils échantillonnés (−2 Ev, normal, +2 Ev) ; le curseur passe « en continu » entre eux, interpolation non décrite [à vérifier]. Négatif : exposition ET traitement ; inversible : exposition seule. Construction [doc] : mires photographiées, négatifs tirés optiquement sur papier puis mesurés (spectrophotomètre, densitomètre), LUT 3D issue d'un modèle non linéaire maison ; nombre de plages et papier non précisés.

### (a) Film Developer ([page][fd], [article][fd-art])

| Paramètre | Rôle (doc) | Plage / défaut | Dépendance | Marque |
|---|---|---|---|---|
| Contrast Boost | contraste du révélateur, positif ou négatif | exemples −100 et +100 | — | [doc] [à vérifier] |
| Gamma Correction | tons moyens vers ombres ou hautes lumières | exemples −50 et +50 | seulement si Contrast Boost ≠ 0 | [doc] |
| Color Separation | abaisse d'abord les couleurs les plus saturées | maximum +100 par défaut | seulement si Contrast Boost ≠ 0 | [doc] |
| Color Boost | saturation globale, sans sortie de gamut | exemples 0 et 100 | aucune citée | [doc] [à vérifier] |

Réponse à (a) : OUI pour les deux ; la doc dit la correction de gamma possible « with any Contrast Boost value other than zero ». Curseurs grisés ou ignorés à zéro : non dit [à vérifier].

### (b) Film Compression ([page][fc], [article][fc-art])

| Paramètre | Rôle (doc) | Plage / défaut | Marque |
|---|---|---|---|
| Impact | degré de compression des hautes lumières | n.d. | [doc] [à vérifier] |
| White Point | seuil d'écrêtage ; plus bas = plus de contraste | 50 à 120, défaut 100 | [doc] |
| Tonal Range | largeur de la zone comprimée | 0 (aucune) à 100 | [doc] |
| Color Density | saturation de la zone comprimée (0 : type négatif ; 100 : type inversible) | 0 à 100 | [doc] |

### (c) Expand ([page][ex])

| Paramètre | Rôle (doc) | Plage / défaut | Marque |
|---|---|---|---|
| Black Point, White Point | points noir et blanc relatifs à l'espace de sortie ; compriment, n'écrêtent pas | n.d. ; libellés exacts non confirmés | [doc] [à vérifier] |
| Color Mode | « Luma » : luminance seule ; autres valeurs non décrites | n.d. | [doc] [à vérifier] |

### (d) CMY Color Head et Print Toning ([page][cmy], [article][cmy-art])

| Paramètre | Rôle (doc) | Plage / défaut | Marque |
|---|---|---|---|
| Yellow / Blue, Magenta / Green, Cyan / Red | filtres de tête couleur, d'après des filtres réels mesurés | exemples ±10, ±50 ; unité, bornes n.d. | [doc] [à vérifier] |
| Gang | lie les trois curseurs ; valeurs égales = dérive de teinte quand même | case | [doc] |
| Shadows / Midtones / Highlights Tone | température par zone, 3 zones « equally quantised », masque automatique | n.d. | [doc] [à vérifier] |
| Preserve Exposure | 100 % : exposition compensée ; 0 : la filtration change la densité | 0 à 100 % | [doc] |
| Impact | opacité de l'outil | n.d. | [doc] [à vérifier] |

### (e) Film Grain ([page][gr], [article][gr-art])

| Paramètre | Rôle (doc) | Plage / défaut | Marque |
|---|---|---|---|
| Grain Profiles | 8, 16, 35, 65 mm × ISO 50, 250, 500 | 12 profils | [doc] |
| Film Type | Negative (plus marqué en hautes lumières) / Positive (« classic », plus doux) | 2 choix | [doc] |
| Processing Mode | Analogue (d'origine) / Noise (simplifié ; « Digital » à la 5.3.0) | 2 choix | [doc] |
| Size | taille des grains, corrigée selon la taille de l'image | 1 à 10 (article) | [doc] |
| Amount | quantité, liée à la densité optique | 0 à 100 (article) | [doc] |
| Shadows, Midtones, Highlights | quantité par zone | n.d. | [doc] [à vérifier] |
| Film Resolution | 100 : netteté de la source ; 50 : équilibre | repères 50, 100 | [doc] |
| Chroma | saturation des grains de colorant | 0 à 100 (article) | [doc] |

Grain procédural, généré d'après couleur et luminosité locales [doc]. Profils d'outils : « aspect typique » d'un format, non mesurés ([profils][tp]).

### (f) Halation ([page][ha], [article][ha-art])

| Paramètre | Rôle (doc) | Plage / défaut | Marque |
|---|---|---|---|
| Halation Profiles | 4 formats × (standard, « No Remjet ») | 8 profils | [doc] |
| Source Limiter | luminosité minimale d'une source de halo | défaut 0 | [doc] |
| Background Gain | tons de fond où le halo se voit | défaut « presque au maximum » | [doc] |
| Smoothness ; Local Diffusion | grandes ou petites sources (0 = halos les plus détaillés) ; rayon des halos | n.d. | [doc] [à vérifier] |
| Global Diffusion | reflet secondaire, tons moyens peu contrastés | exemples 0, 100 | [doc] |
| Amplify | sensibilité à la lumière diffusée (pas une opacité), tire vers le jaune | exemples 0, 100 | [doc] |
| Hue | sensibilité de la couche verte ; 0 = couche verte non surexposée | exemples 0, 50, 100 | [doc] |
| Blue Comp. ; Impact ; Mask Mode | compense les fonds froids ; opacité ; aperçu de l'effet seul | n.d. ; case | [doc] [à vérifier] |

### (g) Bloom ([page][bl], [article][bl-art])

| Paramètre | Rôle (doc) | Plage / défaut | Marque |
|---|---|---|---|
| Bloom Profiles | 8, 16, 35, 65 mm, valeurs moyennes | 4 profils | [doc] |
| Highlights | seuil de luminosité ; effet au-delà de 50 % (article) | n.d. | [doc] [à vérifier] |
| Source Limiter ; Details ; Diffusion | coupe le bas de la plage ; petites ou grandes sources ; rayon | n.d. | [doc] [à vérifier] |
| Amplify ; Save Lights ; Saturation | force globale ; protège de l'écrêtage ; désature la lueur | n.d. | [doc] [à vérifier] |
| Impact ; Mask Mode | opacité ; aperçu de l'effet seul | n.d. ; case | [doc] [à vérifier] |

### Autres outils (tous [doc] ; valeurs absentes [à vérifier])

| Outil | Paramètres | Valeurs documentées |
|---|---|---|
| [Vignette][vi] | Exposure, Size, Feather, Aspect Ratio, Center (vidéo) | Center −1 à +1 |
| [Film Damage][dm] | Dust, Hairs, Scratches (Amount, Scale, Size Balance, White-Black) ; Total Amount, Global Period, Global Opacity, Global Chromaticity | aucune |
| [Overscan][ov] | Gate Type (7 formats), Gate Shape, Perforation Mode, Film Orientation, Scale, Lens Zoom, Offset X / Y, Gate Defocus, Exposure, Static Gate, Flip | Scale et Gate Defocus 0 à 100 ; Lens Zoom défaut 100 ; Offset ±100 = demi-image ; Exposure −2 à +2 Ev |
| [Film Breath][br] | Exposure, Tonal Contrast, Color, Period, Impact | aucune |
| [Gate Weave][gw] | Period, Translation X / Y, Rotation, Auto Zoom, Impact | aucune |
| [Monitor][mo] | False Color (IRE, 16 zones), Clipping Indication | bleu RVB 0-5, rouge RVB 250-255 |
| [Output][out] | Total Impact (réduit aussi les effets géométriques), Quality (Normal / High) | aucune |
| [LUT Generator][lut] | couleur et contraste seuls, sans les outils spatiaux | 17³ ou 33³ |
| [Acutance][acut] | Fine / Medium / Large Detail, Shadows / Midtones / Highlights, Total Impact, masque de peau | zones et Mask Impact 0 à 100 |

## 4. PRINT (priorité)

### Supports ([page][pr], [article][pr-art], [manuel Desktop][desk])

| Support | Ce que la doc dit | Marque |
|---|---|---|
| Linear | profil « pur » du film, sans support ; comportement d'avant la 5.0.0 ; conseillé avec les inversibles | [doc] |
| Cineon Film Log | film rendu au format d'un scan Cineon, pour un tirage hors de Dehancer | [doc] |
| Kodak 2383 Print Film | tirage sur Kodak Vision Color Print Film 2383 ; conseillé avec les films cinéma | [doc] |
| Fujifilm 3513 Print Film | tirage sur Fujicolor Positive Film Eterna-CP 3513DI ; version d'ajout non trouvée | [doc] |
| Kodak Endura Glossy Paper | tirage sur Kodak Endura Premier Glossy Paper ; conseillé avec les négatifs photo | [doc] |
| (Slavich Bromportrait BW Paper) | papier des négatifs N&B ; d'après le manuel Desktop, affiché sous le nom « Kodak Endura » | [doc] [à vérifier] |

Aucun autre support nommé.

### Paramètres ([page][pr])

| Paramètre | Rôle (doc) | Plage / défaut | Marque |
|---|---|---|---|
| Target White | température de la source au tirage ; actif SEULEMENT avec 2383 ou 3513 | 5500 à 6500 K ; défaut, pas n.d. | [doc] [à vérifier] |
| Exposure (Ev) | exposition du tirage d'après les courbes de tirages optiques ; change aussi le contraste | en Ev ; bornes n.d. | [doc] [à vérifier] |
| Tonal Contrast | contraste non linéaire, négatif = adoucit ; peut écrêter (reprendre Expand) | n.d. | [doc] [à vérifier] |
| Color Density | saturation perceptive ; peut sortir du gamut | n.d. | [doc] [à vérifier] |
| Saturation | chroma en YCrCb, RÉDUCTION seule ; 0 = N&B pur | bornes n.d. | [doc] [à vérifier] |
| Analogue Range Limiter | coupé (défaut) : noir et blanc normalisés à 0 et 100 ; actif : points noir et blanc mesurés sur les tirages de référence | case | [doc] |

Print exige un profil de film choisi [doc] ([FAQ][faq]).

### Méthode et séparation film / tirage [doc]

- Négatifs tirés optiquement sur papier au laboratoire de l'éditeur, contrôle visuel et instrumental ; un modèle mathématique SOUSTRAIT ensuite le papier : profil de négatif « propre », réutilisable sur d'autres supports ([article][pr-art]).
- Chaîne résumée par « Digital Image + Film Stock + Print Film », tirage facultatif ([chaîne classique][chain]).
- NON documenté [à vérifier] : origine des profils 2383 et 3513 (tirages mesurés ou données fabricant), illuminant, lien entre Target White et les lampes de projection (ni D55 / D65 ni xénon cités).

### Données physiques publiques [donnée fabricant]

| Support | Document | Données lues |
|---|---|---|
| Kodak VISION Color Print Film 2383 / 3383 | [H-1-2383, révisé 3-22][k2383] | support ESTAR 120 µm sans remjet ; couches, de haut en bas : verte (magenta), rouge (cyan), bleue (jaune), antihalo ; procédé ECP-2E dans le texte, graphiques étiquetés ECP-2D ; courbes : 1/500 s tungstène + verre anticalorique 2043 + filtre Series 1700, Status A, axes log H −3 à +3 lux·s, densité 0 à 6 ; colorants normalisés pour une densité neutre visuelle 1,0 sous illuminant de visionnage à arc xénon |
| LAD du 2383 | [H-61B][lad] (© 1992) | plage LAD = gris de densité visuelle 1,0 ; visée Status A : R 1,09, V 1,06, B 1,03 ; près de la visée, 1 lumière de tireuse (0,025 log H) ≈ 0,07 de densité |
| Procédé ECP-2E | [H-24.09, Module 9][ecp] | repéré, NON lu [à vérifier] |
| Fujicolor Eterna-CP 3513DI / 3613DI | manuel Fujifilm réf. KB-0707E, [copie chez un tiers][fuji], p. 50-53 | support PET ; procédé ECP-2B ; visée de tirage Status A sur gris 18 % : R 1,10, V 1,05, B 1,05, pour projection à lampe xénon ; courbes : tungstène 2854 K, 1/100 s, filtres SC-41 + CC-90Y + CC-60M, Status A, V et B décalées de 1,0 log H |
| Kodak Professional Endura Premier Paper | [E-4070, déc. 2017][endura] | surfaces E, F (brillant), N, Y ; procédé RA-4 ; courbes : 0,5 s, RA-4 35 °C 45 s, Status A, axes log H −3 à 0, densité 0 à 3 ; évaluation des tirages : 5000 K ± 1000 |

Ce qui MANQUE :
- Aucune courbe tabulée (graphiques seuls) ; aucun D-min, D-max ni gamma chiffré dans les textes.
- Lectures de graphique approximatives, PAS des valeurs publiées : plateau du 2383 vers 4 ; plateaux de l'Endura entre 2,3 et 2,6 environ (R au-dessus).
- Déduction, pas une valeur publiée : 0,07 / 0,025 ≈ 2,8 de pente locale près de la LAD du 2383.
- Projection : seul le xénon est cité ; ni température de couleur ni luminance d'écran.
- 3513DI : pas de fiche sur fujifilm.com ; date du manuel non lue.

## 5. Ordre des opérations

Ce que la doc dit [doc] ([schéma][diag]) :
- Pas de chaîne linéaire : couches parallèles, analyse préalable, étapes lisant des étapes antérieures ; l'interface montre un « typical pipeline », pas la structure interne.
- Schéma publié (non daté, sans Film Developer, Film Compression, Film Damage, Overscan) : Input → Expand → Film Profiles ; Film Grain, Halation, Bloom branchés en PARALLÈLE après Expand ; puis Print Options, CMY Color Head, Vignette ; puis LUT Generator, False Color ; Output. Un pointillé relie Input à Vignette (elle lit l'exposition de la source).
- Expand est ENTRE Input et Film Profiles : il règle la plage de contraste du profil, il ne corrige pas sa sortie.
- Exposure Comp. s'applique avec la conversion de la source ([Input][in]) ; Color Head et Vignette relèvent du tirage.
- Outils non réordonnables ([FAQ][faq]).

Ce que la doc NE dit PAS [à vérifier] : place de Film Developer et de Film Compression par rapport au profil ; ordre entre Halation, Bloom et Grain, et leur position par rapport au tirage ; place de Film Damage, Overscan, Breath, Gate Weave, Acutance ; point d'application de Total Impact. L'ordre des panneaux ne prouve rien.

## 6. DxO FilmPack

- Version : **DxO FilmPack 8** [doc] ([guide][dxo]). Sortie rapportée par la presse ([30 sept. 2025][dxo-press], page non relue) ; date et mise à jour courante NON confirmées chez DxO (403). Éditions : aucune citée dans le guide [à vérifier].
- Modes [doc] ([configuration][dxo-sys]) : autonome (RAW, DNG, JPEG, TIFF 8 / 16 bits) ; module pour Photoshop, Photoshop Elements, Lightroom Classic (JPEG, TIFF seulement) et DxO PhotoLab.
- Rendus : « 153 authentic film renderings », dont 15 nouveaux (CineStill 800T, Harman Phoenix 200…) ([Nouveautés][dxo-new]) ; l'[index][dxo-idx] annonce 83 films en 4 familles ; écart non expliqué [à vérifier]. Méthode affirmée [doc] : mires photographiées, numérisation, matrice de grain extraite.
- Préréglages ([Presets][dxo-pre]) : Color, Black & White, Legacy films, Designer, Digital film, Cinematic film, Time Machine, My presets ; Time Warp (Time Travel, Ageify).

Onglet [Customize][dxo-cus] (tout [doc] ; valeurs absentes [à vérifier]) :

| Palette | Outils et paramètres | Valeurs documentées |
|---|---|---|
| Film Scan Optimizer | Invert Image ; préréglages Linear et 1 à 13 ; courbes RGB, R, G, B | aucune |
| Film | Rendering (liste) ; Grain : Film (indépendant du rendu), Intensity, Size ; Split toning (Highlights, Shadows : Ferric sulfate, Gold, Selenium, Sepia terra, Sepia gold, Sepia ; Hue, Saturation, Intensity, Balance) | Rendering : défaut « No film rendering », intensité n.d. ; Grain : Intensity défaut 100, Size 24×36, moyen ou grand format, ou 1 à 10 |
| Development | Light (Exposure, Highlights, Midtones, Shadows, Blacks) ; Color (Saturation, Vibrancy) ; Luminosity Masks (11 zones) ; Contrast, Micro-contrast, Fine contrast ; White balance ; HSL (8 canaux + Global) ; Channel Mixer (N&B) ; Tone curve ; corrections automatiques | Vibrancy et Contrast −100 à +100 ; Hue −180° à +180° ; masques et courbe 0 à 255 |
| Graphical effects | Frame (Size, Position) ; Texture, Light leak (Intensity, Randomize) | Intensity défaut 50 |
| Lens effects | Filter (18 filtres + Intensity) ; Creative vignetting (Intensity, Midpoint, Transition, Roundness) ; Blur : Vignetting, Soft Focus (Intensity, Radius, Diffusion) | vignettage −100 (noir) à +100 (blanc) ; Blur : Intensity 0 à 100, défaut 0, Radius défaut 50 |

Ni séparation film / tirage, ni support de tirage, ni Push/Pull, halation ou bloom dans le guide.

## 7. Lacunes et vérifications à faire dans les logiciels

1. **Bornes, pas, défauts** de tous les curseurs Dehancer « n.d. » : minimum, maximum, pas, valeur après double-clic, dans Desktop et le module photo.
2. **Film Developer** : à Contrast Boost = 0, bouger Gamma Correction et Color Separation ; exports TIFF 16 bits identiques ? curseurs grisés ?
3. **Neutralité** : réglages qui laissent une rampe de gris 16 bits inchangée ; écart résiduel.
4. **Print, courbes** : rampe de gris et mire de couleurs exportées par support, même film ; comparer la FORME aux graphiques Kodak / Fuji, jamais les valeurs absolues.
5. **Target White** : défaut, pas, chromaticité d'un gris à 5500 / 6000 / 6500 K ; inactif hors 2383 / 3513 ?
6. **Analogue Range Limiter** : niveaux noir et blanc de sortie, actif puis coupé, par support.
7. **Saturation (Print)** : le maximum est-il neutre, 0 donne-t-il un gris pur ?
8. **Ordre réel** : commutativité par paires (Film Compression et profil, Halation et Grain, Bloom et Print, Vignette et Print).
9. **Push/Pull** : rampe à −2, −1, 0, +1, +2 Ev et aux demi-valeurs ; états intermédiaires = mélange linéaire des trois profils ? pas du curseur.
10. **Expand** : libellés, bornes, liste de Color Mode.
11. **CMY Color Head** : unité, bornes ; dérive d'un gris à +10 par axe et avec Gang ; Preserve Exposure à 0 / 50 / 100 %.
12. **Film Grain** : aplats gris, deux tailles d'image : écart-type, spectre, corrélation des canaux par mode, type et Size.
13. **Halation, Bloom** : point et bord blancs sur fond noir puis bleu ; profil radial par canal et par paramètre.
14. **Papier N&B** : nom affiché du support pour un film N&B (« Kodak Endura » ou Slavich).
15. **Module photo** : présence réelle de Film Breath, Gate Weave, False Color, Acutance.
16. **Pages inaccessibles** : versions de Desktop (404) ; support.dxo.com (403) ; guides rapides PDF Dehancer (images, 2022) et H-24.09 non lus ; fiche Fujifilm du 3513DI non trouvée.
17. **DxO FilmPack** : nombre réel de rendus (83 ou 153), bornes des curseurs, intensité de rendu, éditions vendues.

## Liens

[v-ofx]: https://www.dehancer.com/shop/davinci_resolve/pro/versions
[v-aepr]: https://www.dehancer.com/shop/aepr/pro/versions
[v-fcp]: https://www.dehancer.com/shop/final_cut/pro/versions
[v-photo]: https://dehancer.com/shop/pslr/film/versions
[sysreq]: https://www.dehancer.com/learn/article/system-requirements
[desk]: https://www.dehancer.com/learn/article/desktop-manual
[desk-blog]: https://blog.dehancer.com/2026/04/09/dehancer-desktop-is-out
[cs]: https://www.dehancer.com/learn/article/color-spaces
[in]: https://www.dehancer.com/learn/article/input
[fp]: https://www.dehancer.com/learn/article/film-profiles
[pp]: https://www.dehancer.com/learn/learn_articles/what-is-push-pull
[build]: https://www.dehancer.com/learn/learn_articles/how-we-build-film-profiles
[fd]: https://www.dehancer.com/learn/article/film-developer
[fd-art]: https://www.dehancer.com/learn/learn_articles/dehancer-film-developer
[fc]: https://www.dehancer.com/learn/article/film-compression
[fc-art]: https://www.dehancer.com/learn/learn_articles/dehancer-film-compression
[ex]: https://www.dehancer.com/learn/article/expand
[pr]: https://www.dehancer.com/learn/article/print
[pr-art]: https://www.dehancer.com/learn/learn_articles/print-film-profiles-in-dehancer
[cmy]: https://www.dehancer.com/learn/article/cmy-color-head-and-print-toning
[cmy-art]: https://www.dehancer.com/learn/learn_articles/cmy-color-head
[gr]: https://www.dehancer.com/learn/article/grain
[gr-art]: https://www.dehancer.com/learn/learn_articles/how-does-film-grain-work-in-dehancer-ofx-plugin
[tp]: https://www.dehancer.com/learn/learn_articles/dehancer-tool-profiles
[ha]: https://www.dehancer.com/learn/article/halation
[ha-art]: https://www.dehancer.com/learn/learn_articles/halation-in-dehancer
[bl]: https://www.dehancer.com/learn/article/bloom
[bl-art]: https://www.dehancer.com/learn/learn_articles/bloom-how-it-works
[vi]: https://www.dehancer.com/learn/article/vignette
[dm]: https://www.dehancer.com/learn/article/damage
[ov]: https://www.dehancer.com/learn/article/overscan
[br]: https://www.dehancer.com/learn/article/breath
[gw]: https://www.dehancer.com/learn/article/gate-weave
[mo]: https://www.dehancer.com/learn/article/monitor
[out]: https://www.dehancer.com/learn/article/output-options
[lut]: https://www.dehancer.com/learn/article/lut
[acut]: https://www.dehancer.com/learn/articles/acutance_with_skin_mask_a_new_tool_in_Dehancer
[faq]: https://www.dehancer.com/learn/article/faq-tools
[diag]: https://www.dehancer.com/learn/learn_articles/tools-diagram-of-dehancer-pro-ofx-plugin
[chain]: https://www.dehancer.com/learn/articles/the-classic-color-film-production-process
[k2383]: https://www.kodak.com/content/products-brochures/Film/KODAK-VISION-Color-Print-Film-2383-3383-data-sheet.pdf
[lad]: https://www.kodak.com/content/products-brochures/Film/LAD-for-KODAK-VISION-Color-Print-Film-H-61b.pdf
[ecp]: https://www.kodak.com/content/products-brochures/Film/Processing-KODAK-Motion-Picture-Films-Module-9.pdf
[fuji]: https://www.theodoropoulos.info/attachments/076_fujifilm_motion_picture_film_manual.pdf
[endura]: https://business.kodakmoments.com/sites/default/files/files/products/e4070.pdf
[dxo]: https://userguides.dxo.com/filmpack/en/
[dxo-sys]: https://userguides.dxo.com/en/filmpack/system-requirements-installation-file-formats
[dxo-pre]: https://userguides.dxo.com/en/filmpack/presets
[dxo-cus]: https://userguides.dxo.com/en/filmpack/customize-tab
[dxo-idx]: https://userguides.dxo.com/filmpack/en/index-of-films/
[dxo-new]: https://www.dxo.com/dxo-filmpack/whats-new
[dxo-press]: https://petapixel.com/2025/09/30/dxo-filmpack-8-takes-your-favorite-photos-back-through-time

# FM Photo : sources primaires et décisions de dépendances

Relevé du 2026-11-14. Chaque fait porte sa source `[Sx]` (URL en fin de section). « [à vérifier] » = non lu dans une source primaire ; « résumé » = connu par un résultat de recherche seulement. Pas un avis juridique.

## Carte

1. Films de référence (Gold 200, XP2 Super, Aerocolor IV 2460, Portra 160NC, Vision3 50D) : ce que les fiches donnent VRAIMENT.
2. Fujifilm X-T5 : simulations, matrice des réglages d'image, firmwares, silences du manuel.
3. Grain argentique : modèle booléen de Newson et al. (IPOL 2017), licence, travaux voisins.
4. Dépendances et licences, LibRaw et X-Trans, cinq boîtiers prioritaires.
5. Lacunes.
Bloquants pour une distribution fermée : librtprocess (GPLv3), code IPOL du grain (GPL-3.0-or-later), greffons rapides de LittleCMS (GPL3), darktable (GPL-3.0).

## 1. Films de référence

Constat commun : les fiches donnent des COURBES imprimées, sans tableaux ; seuls le Print Grain Index (PGI) et, pour l'Aerocolor, la granularité RMS sont chiffrés. Toute courbe sera numérisée à la main. Kodak précise que ces courbes sont représentatives de la production, pas des spécifications [S4].

### a. Kodak Gold 200

- Document : **E-7022**, « Revised 06-23 », Kodak Alaris, 4 pages. Lu [S1].
- Génération : la fiche ne nomme ni génération ni code d'émulsion ; « actuelle » = le produit de cette révision, en 135 et 120 [S1]. Éditions antérieures (03-22 ; 2007 commune Gold 100 / 200 ; 02/2016) : résumé [à vérifier] [S2].
- Procédé C-41. Sensibilité : tableau « ISO Speed » 200 lumière du jour, 64 avec filtre 80B, 50 avec 80A ; aucune norme citée. Latitude annoncée −2 à +3 diaphragmes [S1].
- Structure : support ESTAR 0,10 mm pour le 135 ET le 120. Ni couche antihalo ni masque décrits ; le masque ne se lit que dans la courbe de densité minimale [S1].
- Fourni : courbes caractéristiques R, V, B (graphique ; lumière du jour, Status M, Log H Ref −1,14) ; sensibilité spectrale des trois couches (graphique ; 1/50 s, 0,2 au-dessus de D-min) ; densité spectrale des colorants (graphique : neutre moyen et D-min) ; PGI en VALEURS : 135 → 44 (tirage 4x6 po), 64 (8x10) ; 120 → 33 / 44 / 64 (4x6, 8x10, 16x20). Réciprocité : rien à corriger de 1/10 000 s à 1 s [S1].
- Absents : MTF, granularité RMS (le PGI la remplace et n'est pas comparable), pouvoir résolvant [S1].
- Pièges : dans le tableau PGI 135, le grossissement imprimé est 4,4X pour les DEUX tirages (coquille probable) ; le PGI vaut pour un tirage en lumière diffuse vu à 14 pouces, pas pour un scan [S1] ; la fiche dit « low-speed », la page produit dirait « medium-speed » (résumé) [à vérifier] [S3].

### b. Ilford XP2 Super 400

- Document : « Technical Information XP2 SUPER », Harman technology Ltd. Édition LUE : juin 2010, 4 pages (copie d'un revendeur) [S5]. L'édition officielle (annoncée novembre 2018, 5 pages) répond HTTP 403 aux outils : non relue [à vérifier] [S6].
- Procédé : noir et blanc CHROMOGÈNE traité en C-41 standard ; image faite de colorants, pas d'argent [S5].
- Sensibilité : ISO 400/27° lumière du jour, mesurée en C-41 standard ; exposable de EI 50 à 800 sans changer le traitement. La fiche précise que l'indice recommandé vient d'une évaluation pratique, non du critère de la norme ISO ; aucun numéro de norme [S5].
- Structure : 135 sur acétate 0,125 mm ; 120 sur acétate clair 0,110 mm avec dorsale antihalo qui se décolore au développement. Négatif rosé à brun-rouge (reste de colorant sensibilisateur) ; aucun masque orange décrit [S5].
- Fourni : sensibilité spectrale en spectrogramme en coin au tungstène 2850 K (graphique, 400 à 650 nm) ; UNE courbe caractéristique (graphique, log d'exposition RELATIF) ; courbe de réciprocité (rien à corriger de 1/2 s à 1/10 000 s) [S5].
- Absents : MTF, granularité, densité spectrale du colorant, toute valeur numérique [S5].
- Pièges : le grain DIMINUE en surexposition (inverse d'un film classique) ; pousser le développement n'apporte rien ; contraste presque indépendant de l'éclairage de l'agrandisseur [S5].

### c. Kodak Aerocolor IV Negative Film 2460

- Document : **AS-2652**, « New 10-09 », © Eastman Kodak 2009. Lu [S7] ; lié depuis la page Aerial Imaging [S8].
- Nature : négatif couleur aérien à grain très fin. La fiche dit explicitement qu'il n'a PAS de masque coloré intégré (lecture directe du négatif) [S7].
- Structure : ESTAR 3,9 mil (0,10 mm) ; total 5,2 mil = émulsion 0,8 + support 3,9 + dorsale 0,5 ; sous-couche antihalo, dorsale en gélatine teintée, filtre UV intégré [S7].
- Sensibilité : **EAFS ou ISO A 125** (lumière du jour, sans filtre, développement au contraste maximal), arrondie au tiers de diaphragme. La fiche avertit de ne pas confondre ces indices aériens avec les sensibilités classiques. AUCUNE sensibilité conventionnelle n'est donnée. L'équivalent ISO A va de 80 à 125 selon le développement (contraste environ 0,63 à 0,90) [S7].
- Procédé : AN-6 recommandé ; compatible C-41 (5 min 15 s à 38 °C pour égaler l'AN-6 ; 3 min 15 s = contraste bas) [S7].
- Fourni : granularité RMS en VALEURS : 8,5 / 13 / 15,5 pour C-41 à 3:15 / 4:15 / 5:15 (densité diffuse verte nette 1,0, ouverture 48 µm) ; MTF (graphique, AN-6) ; sensibilité spectrale (graphique ; 1/25 s, 0,3 au-dessus de D-min) ; densité spectrale des colorants (graphique) ; TROIS courbes caractéristiques (contraste bas, moyen, maximal) ; réciprocité : rien de 1/10 000 s à 1/10 s [S7].
- Absents : pouvoir résolvant, PGI [S7].
- Pièges : la « sensibilité » dépend du développement, donc l'émulation doit fixer procédé et durée ; le tableau des contrastes contient une incohérence (3:45 noté 255 s) [S7] ; sans masque, l'inversion ne se règle pas comme pour le Gold.

### d. Kodak Portra 160NC (historique)

- Trois états à ne pas mélanger : (1) **E-190, novembre 1998** (Eastman Kodak), lancement de 160NC / 160VC / 400NC / 400VC, lu sur archive [S4] ; (2) E-190 d'octobre 2006 puis **E-4040, février 2009**, famille « repensée » pour un grain plus fin, lu sur copie tierce [S9] (édition 2006 et nom « 160NC-2 » : index d'archive, résumé [à vérifier] [S2]) ; (3) **Portra 160 actuel, E-4051**, « Revised 1-25 », Kodak Alaris, lu [S10].
- 160NC selon E-190 (1998) : couleurs naturelles, éclairage contrôlé ; ISO 160 jour, 50 (80B), 40 (80A) ; C-41 ; 135 sur acétate 0,13 mm, 120 / 220 sur acétate 0,10 mm, plan-film ESTAR 0,19 mm. Fourni : courbes caractéristiques (graphique, Status M), sensibilité spectrale (graphique, 1/25 s), densité spectrale des colorants (graphique), PGI : 135 → 30 / 52 / 81 ; 120 → < 25 / 30 / 52 ; 4x5 → < 25 / < 25 / 29. Pas de MTF. Réciprocité : rien de 1/10 000 s à 10 s [S4].
- 160NC selon E-4040 (2009) : PGI 135 → 32 / 54 / 83 ; 120 → < 25 / 32 / 54 ; 4x5 → < 25 / < 25 / 31 ; MTF en graphique [S9]. Piège : PGI plus élevés qu'en 1998 alors que la fiche annonce un grain plus fin ; les éditions ne se comparent pas telles quelles.
- Différences avec le Portra 160 actuel selon Kodak : annoncé le 21 février 2011, il REMPLACE 160NC et 160VC (communiqué, résumé) [S11] ; E-4051 annonce un grain nettement plus fin pour le scan, la technologie des films VISION ; PGI 135 → 28 / 50 / 79 ; 120 → < 25 / 28 / 50 ; 4x5 → < 25 / < 25 / 26 ; MTF en graphique ; Log H Ref −1,051 ; sensibilité spectrale à 1/50 s [S10].
- Décision : « Portra 160NC » doit dire quelle édition il imite (1998 ou 2009) ; les courbes de E-4051 décrivent un autre film.

### e. Kodak Vision3 50D 5203 / 7203

- Document : **H-1-5203**, « Revised 3-26 » (mars 2026), Eastman Kodak. Lu [S12].
- Nature : négatif couleur cinéma, lumière du jour 5500 K, support acétate. Indice d'exposition (EI, pas « ISO ») 50 ; 12 au tungstène avec filtre 80A. Procédé **ECN-2** [S12].
- Antihalo : la révision 3-26 indique qu'une sous-couche antihalo (AHU) REMPLACE la dorsale remjet, avec un antistatique résistant au traitement [S12]. La révision 3-22 décrivait encore la dorsale remjet (copie tierce lue) [S13]. Kodak a annoncé cette structure pour les Vision3 500T, 200T, 250D, 50D [S14].
- Fourni (graphiques seuls) : courbes sensitométriques R, V, B ; MTF ; granularité RMS en COURBE (ouverture 48 µm ; lire sigma D, multiplier par 1000) ; sensibilité spectrale ; densité spectrale des colorants NORMALISÉE AU PIC. Réciprocité : rien de 1/1000 s à 1 s [S12].
- Pièges : deux structures coexistent selon le lot (remjet, puis AHU), l'émulation du halo doit dire laquelle ; colorants normalisés = pas de densités absolues ; la fiche prévient qu'un scan 10 bits classique peut perdre les hautes lumières [S12] ; l'effet d'un traitement C-41 n'est pas documenté.

Sources :
- [S1] https://www.kodakprofessional.com/sites/default/files/wysiwyg/pro/resources/E7022%20Gold%20tech%20sheet.pdf
- [S2] https://125px.com/techdocs/kodak/
- [S3] https://www.kodak.com/en/still-film/product/consumer/gold-200-film/
- [S4] https://125px.com/docs/unsorted/kodak/e190.pdf
- [S5] https://www.freestylephoto.com/pdf/product_pdfs/ilford/Ilford_XP2.pdf
- [S6] https://www.ilfordphoto.com/amfile/file/download/file/1909/product/703
- [S7] https://www.kodak.com/content/pdfs/amc/KODAK-AEROCOLOR-IV-Negative-Film-2460-datasheet-en.pdf
- [S8] https://www.kodak.com/en/advanced-materials/product/aerial-imaging/
- [S9] https://www.macodirect.de/media/pdf/6b/ab/de/KP8011_Datenblatt_e.pdf
- [S10] https://www.kodakprofessional.com/sites/default/files/2025-07/e4051.pdf
- [S11] https://prnewswire.com/news-releases/kodak-continues-to-bring-new-professional-films-to-market-with-kodak-professional-portra-160-film-116589713.html
- [S12] https://www.kodak.com/content/products-brochures/motion-picture/KODAK-VISION3-50D-5203-7203-technical-information.pdf
- [S13] https://www.andecfilm.de/wp-content/uploads/50D_DATASHEEt.pdf
- [S14] https://www.kodak.com/en/motion/page/ahu-announcement/

## 2. Fujifilm X-T5 : matrice pour l'atelier de recettes

Sources : manuel en ligne, page « Image Quality Setting » [F1] ; fiche technique [F2] ; page Sensibilité [F3] ; firmwares [F4].

**Simulations** (20 avec le firmware 4.00 ou plus) [F1] : PROVIA/STANDARD, Velvia/VIVID, ASTIA/SOFT, CLASSIC CHROME, REALA ACE, PRO Neg. Hi, PRO Neg. Std, CLASSIC Neg., NOSTALGIC Neg., ETERNA/CINEMA, ETERNA BLEACH BYPASS, ACROS (+ filtres Ye, R, G), MONOCHROME (+ Ye, R, G), SEPIA. La fiche technique en compte 19 (état de lancement, sans REALA ACE) [F2].

AUCUNE valeur par défaut n'est donnée par ces pages. Source de chaque ligne : [F1], complétée par [F2] si indiqué.

| Réglage | Valeurs et pas | Dépendances et restrictions documentées |
|---|---|---|
| FILM SIMULATION | les 20 modes | combinable avec ton et netteté |
| MONOCHROMATIC COLOR | axes WARM–COOL et G–M ; plage visible sur une image seulement | réservé à ACROS et MONOCHROME |
| GRAIN EFFECT | ROUGHNESS : STRONG, WEAK, OFF ; SIZE : LARGE, SMALL | aucune |
| COLOR CHROME EFFECT | STRONG, WEAK, OFF | décrit pour les couleurs très saturées |
| COLOR CHROME FX BLUE | STRONG, WEAK, OFF | décrit pour les bleus |
| SMOOTH SKIN EFFECT | STRONG, WEAK, OFF | aucune |
| WHITE BALANCE | WHITE PRIORITY, AUTO, AMBIENCE PRIORITY, CUSTOM 1 à 3, COLOR TEMPERATURE (2500 à 10 000 K par 10 K), DAYLIGHT, SHADE, FLUORESCENT 1 à 3, INCANDESCENT, UNDERWATER | flash pris en compte seulement en AUTO, WHITE PRIORITY, AMBIENCE PRIORITY, UNDERWATER |
| WB SHIFT | grille ouverte après le choix d'une option ; plage non écrite | pas de déplacement en diagonale au levier |
| DYNAMIC RANGE | AUTO, 100 %, 200 %, 400 % | AUTO choisit 100 % ou 200 % ; 200 % : ISO 250 à 12 800 ; 400 % : ISO 500 à 12 800 ; marbrures possibles [F2] |
| D RANGE PRIORITY | AUTO, STRONG, WEAK, OFF | WEAK : ISO 250 à 12 800 ; STRONG : ISO 500 à 12 800 ; hors OFF, TONE CURVE et DYNAMIC RANGE sont réglés automatiquement |
| TONE CURVE | HIGHLIGHTS −2 à +4 ; SHADOWS −2 à +4 ; pas non écrit | voir D RANGE PRIORITY |
| COLOR, SHARPNESS, HIGH ISO NR | −4 à +4, pas entier | aucune |
| CLARITY | −5 à +5, pas entier | hors 0 : enregistrement plus long ; DÉSACTIVÉ en HEIF [F2] |

- HEIF (4:2:2 10 bits) : désactive CLARITY, force COLOR SPACE sur sRGB ; retour automatique au JPEG pour filtres créatifs, panorama, exposition multiple, HDR [F1][F2].
- Sensibilité : standard ISO 125 à 12 800 par tiers ; étendue 64, 80, 100, 25 600, 51 200, qui peut réduire la plage dynamique [F2][F3].
- RAW RECORDING : UNCOMPRESSED, LOSSLESS COMPRESSED, COMPRESSED (avec perte) ; RAF 14 bits [F1][F2].

**Firmwares** (dernier lu : 4.32 du 10 novembre 2026) [F4] : 1.01 corrige les couleurs des zones sous-exposées avec certaines simulations ; 1.03 corrige des images anormales en NOSTALGIC Neg. ou ETERNA BLEACH BYPASS après un réglage WC / MG de MONOCHROMATIC COLOR ; 4.00 ajoute REALA ACE ; 4.20 corrige les réglages personnalisés qui perdaient l'ISO ; 4.32 corrige des images anormales en bracketing ISO et de simulation. Aucune note ne mentionne de changement des plages, du HEIF ou du RAW.

**Ce que le manuel ne dit pas** : les défauts (page « menu_list » en 404) ; les plages de MONOCHROMATIC COLOR et du WB SHIFT (valeurs d'usage ±18 et ±9 [à vérifier] sur le boîtier) ; le pas de TONE CURVE (0,5 d'usage [à vérifier]) ; les températures des préréglages ; toute formule (courbes, matrices, loi du grain, mécanisme du DR) ; l'interaction de GRAIN EFFECT ou COLOR CHROME avec chaque simulation. Une recette ne peut reprendre que les NOMS et PLAGES ; le rendu se mesure sur des fichiers réels.

Sources :
- [F1] https://fujifilm-dsc.com/en/manual/x-t5/menu_shooting/image_quality_setting/index.html
- [F2] https://www.fujifilm-x.com/global/products/cameras/x-t5/specifications/
- [F3] https://fujifilm-dsc.com/en/manual/x-t5/taking_photo/iso/index.html
- [F4] https://www.fujifilm-x.com/global/support/download/firmware/cameras/x-t5/

## 3. Grain argentique : « Realistic Film Grain Rendering »

- Référence : A. Newson, N. Faraj, J. Delon, B. Galerne, Image Processing On Line 7 (2017), p. 165-183, DOI 10.5201/ipol.2017.192 [G1][G2].
- Principe : grains = disques dont les centres suivent un processus de Poisson (modèle BOOLÉEN) ; leur densité suit le niveau de l'image d'entrée (modèle inhomogène) ; l'image binaire continue est filtrée par une gaussienne, convolution estimée par MONTE-CARLO. Modèle continu, donc rendu à toute résolution ou zoom [G2].
- Paramètres : rayon moyen des grains (en pixels d'entrée), écart-type des rayons (constant ou loi log-normale), écart-type du filtre (en pixels de sortie), nombre N de tirages, zoom ; défauts du programme : 0,1 / 0 / 0,8 / 800 [G2][G3].
- Deux algorithmes, « grain-wise » et « pixel-wise », choisis automatiquement selon la taille des grains, tous deux parallélisables [G2].
- Coût et limites selon les auteurs : loin du temps réel ; certaines émulsions mal imitées (Ilford Delta 3200) ; zones sombres peu réalistes [G2]. FLUIDITÉ : inutilisable tel quel dans un aperçu en direct (précalcul, tuiles ou approximation analytique).
- Licences : ARTICLE sous CC-BY-NC-SA [G2] ; CODE (version 1.0) déclaré « GPL-3.0-or-later » dans la notice BibTeX de la page IPOL [G1] ; dépôt GitHub de l'auteur : « GPL V3+ » [G3]. Ne pas copier ni lier ce code dans un produit fermé ; seule voie : réécrire depuis la description mathématique, à faire valider.
- Travaux voisins : (1) Newson, Delon, Galerne, « A Stochastic Film Grain Model for Resolution-Independent Rendering », Computer Graphics Forum 36(8), 2017, DOI 10.1111/cgf.13159, sans code propre [G4] ; (2) Zhang, Wang, Tian, Pappas, « Film Grain Rendering and Parameter Estimation », ACM TOG 2023, DOI 10.1145/3592127 : statistiques analytiques du même modèle, rendu annoncé temps réel ; ni code ni licence trouvés, et un brevet américain au titre voisin existe (n° 12705810), portée et titulaire [à vérifier] AVANT toute implémentation [G5][G6] ; (3) Stephenson et Saunders 2007, grain par spectre de puissance du bruit, DOI 10.2312/LocalChapterEvents/TPCG/TPCG07/069-072, sans code (cité par [G2]).

Sources :
- [G1] https://www.ipol.im/pub/art/2017/192/
- [G2] https://www.ipol.im/pub/art/2017/192/article_lr.pdf
- [G3] https://github.com/alasdairnewson/film_grain_rendering_gpu
- [G4] https://diglib.eg.org/handle/10.1111/cgf13159
- [G5] https://unpaywall.org/10.1145%2F3592127
- [G6] https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12705810

## 4. Dépendances candidates et licences

« Sous conditions » = obligations LGPL (liaison dynamique ou possibilité de refaire l'édition de liens, mentions, bibliothèque remplaçable). « Libre » = mentions de licence seulement.

| Bibliothèque | Rôle | Licence relevée | Produit fermé | Maintenance relevée | Couverture utile |
|---|---|---|---|---|---|
| LibRaw | décodage RAW, dématriçage de base | au choix LGPL 2.1 OU CDDL 1.0 [D1] | sous conditions | 0.22 (2025-12-25), 0.22.3 (2026-10-26), instantané 202611 [D2][D3] | cinq boîtiers listés (plus bas) |
| rawpy | liaison Python de LibRaw | MIT ; roues sans packs GPL [D4][D5] | libre, plus les obligations de LibRaw embarquée | 0.28.0, Python 3.11 ou plus [D5] | roues avec LCMS, DNG deflate et avec perte [D4] |
| RawSpeed | décodage seul | LGPL-2.1 [D6][D7] | sous conditions | actif (envoi du 2026-11-09) [D7] | boîtiers décrits en XML [D6] |
| librtprocess | dématriçages de RawTherapee | GPL v3 (plus Boost 1.0 pour des portions SLEEF) [D8] | **INTERDIT** (copyleft fort) | 0.12.0 ; dernier envoi 2024-01-26 [D9][D10] | AMaZE, RCD, DCB, LMMSE, IGV, VNG4, AHD, HPHD, Markesteijn et xtransfast, aberration chromatique, hautes lumières [D9] |
| darktable | référence de comportement | GPL-3.0 [D11] | **aucun code réutilisable** | 5.6.2 [D11] | embarque RawSpeed et LibRaw, exige Lensfun et LittleCMS 2 [D11] |
| Lensfun | corrections optiques | bibliothèque LGPL-3 ; BASE de profils CC BY-SA 3.0 ; applications GPL-3 [D12] | bibliothèque sous conditions ; base : attribution et partage à l'identique des modifications | v0.3.4 du 2023-07-12 [D13] | objectifs récents [à vérifier] |
| Adobe DNG SDK | lecture / écriture DNG | licence Adobe gratuite : usage, modification, distribution, sous-licence ; mentions à garder, marques interdites, indemnisation en produit commercial [D14] | possible sous ces conditions ; texte de la 1.7.1 non trouvé [à vérifier] [D15] | version courante [à vérifier] (page Adobe en 403) | DNG |
| LittleCMS | gestion ICC | cœur MIT ; greffons « fast float » et multithread : GPL3 OU licence commerciale payante [D16][D17] | cœur libre ; greffons **interdits en GPL3**, sinon licence à acheter | 2.20 du 2026-10-31 [D18] | ICC 4.4 [D16] |
| OpenColorIO | couleurs scène / affichage | BSD-3-Clause [D19] | libre | v2.6.0 du 2026-10-01, projet ASWF [D19][D20] | — |
| wgpu | GPU en Rust | MIT OR Apache-2.0 [D21] | libre | 30.0.2 du 2026-11-12 [D21] | — |
| PyO3 | liaison Rust / Python | MIT OR Apache-2.0 [D22] | libre | 0.30.1 du 2026-10-14 [D22] | — |
| maturin | construction des roues | MIT OR Apache-2.0 [D23] | libre (outil) | 1.16.0 du 2026-10-29 [D23] | — |
| rayon | parallélisme | MIT OR Apache-2.0 [D24] | libre | 1.12.0 du 2026-04-14 [D24] | — |
| rawler (dnglab) | décodage RAW en Rust | LGPL-2.1 [D25][D26] | sous conditions ; Rust lie statiquement par défaut, donc prévoir une bibliothèque dynamique | 0.8.0 du 2026-08-30 ; API non stable [D25][D26] | RAF, ARW, RW2, NEF, CR2, CR3 listés sans détail des compressions [D26] |
| rawloader | décodage RAW en Rust | LGPL-2.1 [D27] | même remarque | 0.37.2 du 2026-08-15 [D27] | [à vérifier] |

**LibRaw et X-Trans.** Dématriçages du cœur selon la documentation : linéaire (0), VNG (1), PPG (2), AHD (3), DCB (4), DHT (11), AHD modifié (12) ; valeur inconnue = repli sur AHD [D28]. Pour X-Trans, `src/demosaic/xtrans_demosaic.cpp` porte l'en-tête de licence de LibRaw (LGPL 2.1 ou CDDL 1.0) et implémente l'algorithme de Frank Markesteijn, `xtrans_interpolate(int passes)` [D29]. Anciens « demosaic packs » GPL2 / GPL3 : plus pris en charge depuis la 0.19, dépôts déclarés abandonnés, absents des roues rawpy [D2][D30][D4] ; ne jamais les réintroduire. L'instantané 202611 corrige l'interpolation X-Trans (double de mémoire image) : comparer 0.22.x et l'instantané sur des RAF réels [D2].

**Cinq boîtiers.** La liste « LibRaw 0.22 supported cameras » contient Nikon « D200 », Canon « EOS 5D Mark III », Panasonic « DC-S5 MkII » (S5IIX absent), Fujifilm « X-T5 », Sony « ILCE-7M4 (A7 IV) ». Aucune ligne ne précise les variantes de compression, et la liste vaut pour une compilation avec toutes les options [D31] : « listé » ne signifie PAS « toutes variantes validées ». Repères du journal : Fujifilm compressé sans perte depuis la 0.20, RAF compressé avec perte depuis l'instantané 202101 ; Sony compressé sans perte ajouté en 2021 (ILCE-1), A7 IV en 0.21 ; Panasonic « encoding 8 » et DC-S5-II en 0.22 [D2].

Variantes à valider sur fichiers réels (X-T5 : noms du manuel [F1] ; autres boîtiers : liste de travail [à vérifier] dans leurs manuels) : D200, NEF compressé et non compressé ; 5D Mark III, CR2 pleine taille, mRAW, sRAW ; S5II, RW2 normal et mode haute résolution ; X-T5, RAF non compressé, compressé sans perte, compressé avec perte, Pixel Shift ; A7 IV, ARW non compressé, compressé sans perte, compressé avec perte.

Sources :
- [D1] https://raw.githubusercontent.com/LibRaw/LibRaw/master/README.md
- [D2] https://raw.githubusercontent.com/LibRaw/LibRaw/master/Changelog.txt
- [D3] https://api.github.com/repos/LibRaw/LibRaw/releases/latest
- [D4] https://github.com/letmaik/rawpy
- [D5] https://pypi.org/pypi/rawpy/json
- [D6] https://github.com/darktable-org/rawspeed
- [D7] https://api.github.com/repos/darktable-org/rawspeed
- [D8] https://raw.githubusercontent.com/CarVac/librtprocess/master/LICENSE.txt
- [D9] https://github.com/CarVac/librtprocess
- [D10] https://api.github.com/repos/CarVac/librtprocess
- [D11] https://github.com/darktable-org/darktable
- [D12] https://github.com/lensfun/lensfun
- [D13] https://api.github.com/repos/lensfun/lensfun/releases/latest
- [D14] https://scancode-licensedb.aboutcode.org/adobe-dng-sdk.html
- [D15] https://community.adobe.com/questions-563/adobe-dng-sdk-terms-of-use-licensing-182173
- [D16] https://github.com/mm2/Little-CMS
- [D17] https://www.littlecms.com/plugin/
- [D18] https://api.github.com/repos/mm2/Little-CMS/releases/latest
- [D19] https://github.com/AcademySoftwareFoundation/OpenColorIO
- [D20] https://api.github.com/repos/AcademySoftwareFoundation/OpenColorIO/releases/latest
- [D21] https://crates.io/api/v1/crates/wgpu
- [D22] https://crates.io/api/v1/crates/pyo3
- [D23] https://crates.io/api/v1/crates/maturin
- [D24] https://crates.io/api/v1/crates/rayon
- [D25] https://crates.io/api/v1/crates/rawler
- [D26] https://github.com/dnglab/dnglab
- [D27] https://crates.io/api/v1/crates/rawloader
- [D28] https://www.libraw.org/docs/API-datastruct-eng.html
- [D29] https://raw.githubusercontent.com/LibRaw/LibRaw/master/src/demosaic/xtrans_demosaic.cpp
- [D30] https://github.com/LibRaw/LibRaw-demosaic-pack-GPL2
- [D31] https://www.libraw.org/supported-cameras

## 5. Lacunes

1. Aucune fiche ne donne de tableaux numériques pour les courbes : numérisation manuelle, erreur à estimer.
2. XP2 Super : édition officielle de novembre 2018 non relue (403) ; seule celle de juin 2010 l'a été.
3. Gold 200 : génération ou code d'émulsion non documentés ; ni MTF ni granularité RMS dans l'édition 06-23.
4. Aerocolor IV : ni sensibilité conventionnelle ni pouvoir résolvant ; rien sur les reconditionnements en 135.
5. Portra 160NC : E-190 d'octobre 2006 non relue ; E-4040 lue sur copie tierce ; communiqué de 2011 connu par résumé.
6. Vision3 50D : date de bascule remjet vers AHU par lot et effet mesuré sur le halo non établis ; avis de changement Kodak introuvable (404).
7. X-T5 : défauts, plages de MONOCHROMATIC COLOR et du WB SHIFT, pas de TONE CURVE non écrits ; aucun algorithme publié par Fujifilm.
8. Grain : temps de calcul chiffrés et traitement de la couleur non relevés ; brevet n° 12705810 non analysé.
9. Licences : texte livré avec le DNG SDK 1.7.1 non lu ; mention « or later » de darktable et de librtprocess non confirmée ; prix de la licence des greffons LittleCMS non vérifié ; aucune validation juridique.
10. LibRaw : aucune variante de compression testée ; S5IIX absent de la liste ; couverture de Lensfun, rawler et rawloader pour ces boîtiers non vérifiée.

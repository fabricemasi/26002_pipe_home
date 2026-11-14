# Suivi de mission : environnement photographique (`fm_photo/`, FM Film, recettes)

Plan, contrats et décisions : `docs/agents/fm_photo.md`. Références : `docs/agents/fm_film_references.md`,
`docs/agents/fm_photo_sources.md`. À chaque reprise : lire CE fichier, puis la Carte de `fm_photo.md` ; ne pas
refaire l'audit.

États : `à faire` · `étudié` · `implémenté` · `testé` · `comparé` (à une référence identifiée) ·
`validation humaine attendue` · `accepté` · `bloqué (qui / quoi)`. Rien n'est « accepté » sans preuve citée.

## Phase actuelle (2026-11-14)

Fondations posées et testées ; moteur Rust `fm_photo_moteur` construit, installé dans `.venv`, comparé à la
référence numpy et branché (tranche : `exposition`, `diffusion`). Prochaine action : panneau de développement, ou
chaîne RAW dès que rawpy et le corpus sont là. Aucun outil de développement n'est encore exposé dans l'interface ;
rien n'est commité.

## Blocages : ce qui est attendu de l'utilisateur

1. ~~Chaîne Rust~~ LEVÉ le 2026-11-14 (accord de l'utilisateur) : Rust 1.100 installé par `tools\install_rust.ps1`
   (PATH non modifié ; désinstaller : `rustup self uninstall`), maturin 1.16 dans `.venv`. Sur une autre machine :
   `tools\install_rust.ps1`, `.venv\Scripts\pip install maturin`, puis `tools\build_moteur_photo.ps1`.
2. **rawpy** absent de `.venv` (pourtant dans `requirements.txt`) : `.venv\Scripts\pip install rawpy`.
3. **Corpus RAW réel** : dossier de fichiers D200 (NEF), 5D Mark III (CR2), S5II (RW2), X-T5 (RAF, variantes de
   compression), A7 IV (ARW, compressé / non) ; idéalement paires RAW + JPEG boîtier X-T5 documentées (firmware,
   objectif, réglages) pour les recettes.
4. **Références logicielles** : versions exactes installées de Dehancer (Pro / Photo / Desktop) et de DxO FilmPack,
   et un dossier d'exports de référence produits selon `docs/agents/fm_film_protocole.md` (sources :
   `python tools/mires_photo.py <dossier>`) — sans eux, « comparé » reste inatteignable pour FM Film.
5. **Décision** : pour une photo d'un dossier associé à Lightroom, comment choisir entre le rendu de Lightroom et un
   développement PIPE FMZ depuis l'original (aujourd'hui : le rendu de Lightroom reste, voir `fm_photo.md`).

## Registre

| # | Exigence | État | Preuves / tests | Dépend de | Prochaine action |
|---|---|---|---|---|---|
| 1 | Audit ciblé, carte, plan | testé | `fm_photo.md` | — | — |
| 2 | Visionneuse = point commun (aucune 2e visionneuse) | testé (entrée des rendus) | `test_photo_tranche.VisionneuseTest` | — | pellicule / planche développées ; panneau |
| 3 | Contrat Lightroom protégé | testé | `test_lightroom_contract` (10), tests `test_lightroom_*` existants | — | métadonnées communes : étudié, à concevoir avec la décision 5 |
| 3b | XMP | étudié | `fm_photo.md` | — | lecture descriptive hors dossiers associés |
| 4 | Tranche Rust (transmission, traitement coûteux, hors fil, annulation, affichage, export, build Windows) | testé et comparé à la référence numpy (pas une validation photographique) | `test_photo_rust` (11), `test_photo_tranche` (16), relevés de `fm_photo.md` « Fluidité », `tools/build_moteur_photo.ps1` | — | pleine définition au zoom ; accélérer le flou (validé contre la référence) ; porter chaque nouvelle primitive |
| 4b | GPU (wgpu), transferts, précision | à faire | — | 4 | étude après le moteur CPU |
| 5a | Contrat colorimétrique | testé | `test_photo_couleur` (16) | — | rendu de gamut de sortie, profil d'écran, profils caméra |
| 5b | État non destructif, versions, copies virtuelles, Undo / Redo, migrations | testé | `test_photo_moteur.EtatTest` | — | masques, graines, historique nommé, application à plusieurs photos |
| 5c | Primitives communes, tuiles, convergence aperçu / export | testé (`exposition`, `diffusion` = tranche technique) | `test_photo_moteur.OperationsTest` | — | primitives de développement une à une |
| 6 | Intégration Browser (module, cadre, icônes, réglages fm_theme) | à faire | — | 4, 7c | panneau de développement, bouton de mode, icône au catalogue |
| 6b | Board : référence photo / RAW / version / preset par les services partagés | à faire | audit : Board copie ses assets, chargeur propre | 2 | élément « photo » qui référence chemin + version, pixels par `ServiceRendu` |
| 7a | RAW 5 boîtiers, dématriçage, X-Trans, hautes lumières, bruit | bloqué (rawpy, corpus) | `fm_photo_sources.md` | blocages 2, 3 | source linéaire LibRaw -> travail, tests sur corpus |
| 7b | Optique (Lensfun ?, profils, calibration) | à faire | `fm_photo_sources.md` (licences) | 7a | choix de bibliothèque |
| 7c | Développement (exposition… color grading), détail, géométrie, HSL, Point Color | à faire (exposition : testé) | — | 4 | balance des blancs, courbes, contraste d'abord |
| 7d | Import, organisation, dérushage, comparaison | à faire | existant : étoiles, couleurs, drapeaux, filtres, planche | — | inventaire de l'écart avec l'existant |
| 7e | Versions, presets, avant / après, lot | implémenté en partie (versions, copies) | `EtatTest` | 6 | presets, synchronisation de réglages |
| 8 | Scopes (histogramme, parade, waveform, vectorscope, CIE xy) | calcul de référence : testé ; affichage : à faire | `test_photo_scopes` (12) ; existant vidéo : `COLOR_ANALYSIS_PROGRESS.md` | 5a, 6 | widget (briques des réglages), calcul en fond annulable, graticules |
| 8b | Color Warpers Chroma/Luma et Hue/Sat | Hue/Sat : calcul de référence testé ; Chroma/Luma, pipette, interface : à faire | `test_photo_warper` (9) | 5a, 4, 6 | Warper Chroma / Luma sur le même socle ; maillage interactif ; contrôle du gamut |
| 9-10 | FM Film : matrice des références Dehancer | étudié (documentation) | `fm_film_references.md` | blocage 4 | vérifications dans le logiciel (liste en fin de doc) |
| 11 | Print (Linear, Cineon, 2383, 3513, Endura) | étudié (documentation) ; socle Cineon / densité / courbes caractéristiques monotones : testé | `fm_film_references.md`, `test_photo_couleur.CineonTest`, `test_photo_courbes` (9) | blocage 4, données fabricants | modèle par support, banc comparatif |
| 12 | Grain, halation, bloom (spatiaux, tuiles, échelle) | à faire (socle tuiles / échelle : testé) | `OperationsTest` | 4, 11 | grain : étude de Newson et al. (licence au doc sources) |
| 13 | DxO FilmPack (calibrations distinctes) | étudié (documentation) | `fm_film_references.md` | blocage 4 | inventaire dans le logiciel |
| 14 | Cinq presets (Gold 200, XP2 Super, Aerocolor IV, Portra 160NC, Vision3 50D) | étudié (fiches fabricants) | `fm_photo_sources.md` | 11, 12 | aucun preset avant validation des fondations |
| 15 | Atelier de recettes (X-T5 d'abord) | format, matrice X-T5 et vérification : testés ; rendu, bibliothèque, atelier : à faire | `test_photo_recettes` (10), `fm_photo_sources.md` | 7a, 6, corpus RAW + JPEG | bibliothèque (familles, tags, favoris, versions) ; plages à relever sur le boîtier ; calibration |
| 16 | Traitements personnels (nodal ?) | à faire | registre d'opérations = socle | 5c | décider après 7c |
| 17 | Procédure de validation (corpus, seuils a priori, calibration / validation séparées) | protocole et seuils écrits ; Delta E 2000 et mires : testés | `fm_film_protocole.md`, `test_photo_mesures` (10) | blocages 3, 4 | seuils grain / halation avant leur première comparaison ; corpus de photos |
| 18 | Fluidité, export rapide | implémenté (hors fil, annulable, périmés abandonnés) ; budgets tenus par Rust sur la chaîne d'essai (relevé d'essai, pas la mesure `fluidite.bat`), non tenus par la référence | relevés dans `fm_photo.md` ; `a_mesurer.md` | 4 | mesure en fenêtre réelle ; file d'export, lot, reprise ; séries réelles X-T5 |

## Décisions (détail dans `fm_photo.md`)

- Travail : Rec.2020 linéaire D65 float32 ; affichage sRGB 8 bits comme la visionneuse.
- État par dossier `.pipeline_photo.json`, propre à PIPE FMZ, jamais envoyé à Lightroom.
- Les rendus entrent dans la visionneuse par `FocusImageLoader.set_rendition` seulement.
- La référence numpy reste le juge de toute optimisation ; `diffusion` est une tranche technique, pas Halation.
- Source d'un RAW tant que le dématriçage manque : JPEG intégré, marqué provisoire dans le badge d'origine.

## Constats documentaires (recherches du 2026-11-14 ; détail et URL dans les deux docs de références)

Relevés par recherche sur la documentation publique, PAS vérifiés dans les logiciels ni sur fichiers réels ; les
pages web de Dehancer ont été lues à travers un outil de résumé (les PDF des fabricants directement) : à recouper
avant de fonder un modèle dessus.
- Dehancer, contrats confirmés par la documentation : Gamma Correction et Color Separation n'agissent que si
  Contrast Boost est non nul ; Push/Pull = trois profils échantillonnés à -2 / 0 / +2 Ev ; schéma officiel (ancien) :
  Expand AVANT Film Profiles, Grain / Halation / Bloom en parallèle, puis Print / Color Head / Vignette. Versions
  lues : Pro OFX 7.4.1, module photo 2.8.0 ; Desktop non confirmée.
- Données des films et des supports de tirage (Kodak, Fujifilm, Ilford) : courbes IMPRIMÉES seulement, aucune table
  de valeurs. Toute courbe caractéristique devra être relevée sur graphique (étape à documenter, avec son
  incertitude) ou mesurée ; c'est une hypothèse à écrire pour chaque support, pas une donnée.
- Licences à écarter d'une distribution fermée : librtprocess (GPLv3 : dématriçages de RawTherapee), code IPOL du
  grain de Newson et al. (GPL-3 : réécrire depuis l'article), darktable (GPL-3), greffons rapides de LittleCMS
  (GPL-3 ou payants). Utilisables sous conditions : LibRaw (LGPL 2.1 / CDDL, Markesteijn X-Trans dans le cœur),
  base Lensfun (CC BY-SA 3.0), RawSpeed / rawler (LGPL 2.1, liaison statique Rust à traiter).
- Vision3 50D : la fiche de 2026 décrit une sous-couche antihalo à la place de la dorsale remjet de la fiche de
  2022 ; l'émulation du halo doit nommer la génération étudiée. Aerocolor IV : pas de masque coloré, indice aérien
  seulement. Portra 160NC : deux générations (1998, 2009), distinctes du Portra 160 actuel.
- X-T5 : 20 simulations depuis le firmware 4.00 ; DR200 exige ISO 250 au moins, DR400 ISO 500 ; D Range Priority
  règle seul Tone Curve et Dynamic Range ; plusieurs plages et valeurs par défaut absentes du manuel (à relever
  sur le boîtier).
- Dehancer : la documentation dit que la chaîne n'est pas linéaire et ne donne presque aucune plage ni valeur par
  défaut ; l'ordre réel des outils et les bornes restent à relever dans le logiciel (liste en fin de
  `fm_film_references.md`).

## Reprise

Ordre conseillé : (1) panneau de développement dans la visionneuse, sur les primitives déjà en Rust ; (2) primitives
de développement une à une, d'abord en référence testée, puis en Rust comparé (`test_photo_rust`), puis exposées ;
(3) chaîne RAW dès que rawpy et le corpus sont là (blocages 2 et 3) ; (4) Print dès que les références existent.
Toute modification de `fm_photo/moteur_rust/src/lib.rs` : `tools\build_moteur_photo.ps1`, puis `test_photo_rust`.

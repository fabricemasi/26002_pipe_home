# Environnement photographique (`fm_photo/`) : visionneuse commune, moteur partagé, Lightroom

Mission du 2026-11-14 (texte complet dans la demande de l'utilisateur ; exigences suivies une par une dans
`FM_PHOTO_PROGRESS.md`, à lire à chaque reprise AVANT ce fichier). Références documentaires : `fm_film_references.md`
(Dehancer, Print, FilmPack), `fm_photo_sources.md` (films, X-T5, licences).

## Carte : fonctionnalité -> fichiers

| Fonctionnalité | Fichier | Contenu |
|---|---|---|
| Contrat colorimétrique (référence numpy) | `fm_photo/couleur.py` | `ESPACES`, `TRAVAIL`, `matrice`, `vers_travail`, `depuis_travail`, `quantifier`, Cineon, densité |
| État non destructif, versions, historique, stockage | `fm_photo/etat.py` | `nouvel_etat`, `definir_operation`, `copie_virtuelle`, `signature`, `Historique`, `lire` / `ecrire`, `MIGRATIONS` |
| Primitives et rendu de référence, tuiles, réduction | `fm_photo/operations.py` | `REGISTRE`, `Definition`, `Contexte`, `chaine`, `appliquer`, `appliquer_par_tuiles`, `reduire` |
| Recettes : format, matrice X-T5, vérification | `fm_photo/recettes.py` | `nouvelle`, `verifier` -> `Rapport`, `X_T5`, `CAPACITES_MOTEUR`, `importer_json` / `exporter_json` |
| Banc comparatif : Delta E 2000, mires, protocole | `fm_photo/mesures.py`, `fm_photo/mires.py`, `tools/mires_photo.py` | `comparer`, `delta_e_2000`, `mire_tonale`, `mire_couleurs`, `lire_pastilles` ; protocole et seuils : `fm_film_protocole.md` |
| Courbes tabulées monotones (tonalité, courbes caractéristiques) | `fm_photo/courbes.py` | `CourbeMonotone` (PCHIP, `derivee`, `inverse`, prolongement explicite), `gamma` |
| Color Warper Teinte / Saturation (calcul seul) | `fm_photo/warper.py` | `vers_oklab`, `maillage_nul`, `deplacement`, `deformer`, `replis`, opération `warper_teinte_saturation` |
| Scopes de référence (calcul seul, sans interface) | `fm_photo/scopes.py` | `histogramme`, `forme_d_onde`, `parade`, `vectorscope`, `diagramme_xy`, `Mesure` |
| Façade du moteur (où se branchera Rust) | `fm_photo/moteur.py` | `rendre_affichage`, `rendre_export`, `facteur_pour`, `EXECUTANT` |
| Pixels source et provenance | `fm_photo/sources.py` | `charger`, `Source`, `espace_de` |
| Rendu asynchrone annulable (Qt) | `fm_photo/rendu.py` | `ServiceRendu` (`demander`, `abandonner`, `pret`, `sans_rendu`), `Rendu` |
| Export (paramètres figés, écriture sûre) | `fm_photo/export.py` | `Travail`, `exporter` |
| Entrée des rendus dans la visionneuse | `fm_visionneuse/loader.py` | `FocusImageLoader.set_rendition` / `clear_rendition` / `has_rendition` |
| Branchement fenêtre principale | `main_window/photo_module.py` | `PhotoModuleMixin` (`_install_photo`, `photo_develop`) |
| Moteur Rust (PyO3 0.30 + rayon), module `fm_photo_moteur` | `fm_photo/moteur_rust/` (`src/lib.rs`, `Cargo.toml`, `Cargo.lock`, `pyproject.toml`) | `Moteur.rendre`, `Moteur.oublier`, `operations()` ; opérations : `exposition` 1, `diffusion` 1 |
| Chaîne Rust et construction | `tools/install_rust.ps1`, `tools/build_moteur_photo.ps1` | rustup officiel (somme vérifiée, PATH inchangé) ; `maturin build --release --locked` puis `pip install` de la roue dans `.venv` ; cible de compilation HORS du dossier synchronisé (`%LOCALAPPDATA%\pipe_fmz\cargo_target`) |
| Banc | `tools/bench_photo.py` | latences, annulation, mémoire |

Tests (par nom, depuis `tests/`) : `test_lightroom_contract.py`, `test_photo_couleur.py`, `test_photo_moteur.py`,
`test_photo_tranche.py`, `test_photo_scopes.py`, `test_photo_warper.py`, `test_photo_courbes.py`, `test_photo_mesures.py`, `test_photo_recettes.py`, `test_photo_rust.py` (sauté si le moteur n'est pas construit) ; `python tests/run.py fm_photo`. Règle d'isolation : `couleur`, `etat`, `operations`,
`moteur` n'importent PAS Qt ; `sources`, `rendu`, `export` importent Qt et les services communs, jamais la fenêtre.

## Audit (2026-11-14) : ce qui existe et ses contrats

- **Visionneuse** (`fm_visionneuse/`, doc `fm_visionneuse.md`) : `FocusOverlay` (image au centre, ruban, zoom),
  `FocusFilmstrip`, `FocusGallery`. Pixels du centre = `FocusImageLoader` (décodage en fond, 2 fils, RGB32, plafond
  8192 px, LRU 700 Mo, validité par date du fichier) ; lu par `_viewer_image`, `_viewer_neighbour`, `_enter_viewer`,
  `_on_focus_image_ready` (`main_window/viewer*.py`) et la visionneuse à côté (`side_module.py`). Pellicule et
  planche passent par les vignettes `previews.file_image_pixmap`, PAS par le chargeur.
- **RAW aujourd'hui** : le centre montre le JPEG INTÉGRÉ (`previews._decode_embedded_jpeg`) ; rawpy n'est pas installé
  dans `.venv` (les colonnes retombent aussi sur le JPEG intégré). `_raw_linear_in_gamut` (`preview_services/images.py`)
  est le seul chemin linéaire existant. `RAW_EXTENSIONS` (`config.py`) : arw, raf, dng, cr2, cr3, nef, orf, rw2.
- **Traitements réutilisables** : `fm_video/color.py` (OCIO, corrections primaires numpy + shader, LUT `.cube`),
  analyse couleur et scopes vidéo (`COLOR_ANALYSIS_PROGRESS.md`), `_apply_cube_lut` (`images.py`). Aucune gestion ICC
  d'écran : la visionneuse affiche les valeurs sRGB telles quelles.
- **Modules** : table `main_window/module_targets.py` (`MODULES`, `OPENERS`, `click_target` : toute image / RAW ->
  visionneuse), un mixin par module, `HOOKS` posés à l'ouverture, cadre de la barre (`TitleBar.*_group`,
  `style_group_button`), réglages `<paquet>/settings.py` + `settings_defaults.py`. Modèle le plus proche : `fm_video`.
- **Board** : une image du board est une COPIE dans le dossier d'assets (`fm_board/serialization.import_asset`),
  décodée par `fm_miro/items.py` (`image_levels`, QImageReader) ; ni RAW ni visionneuse. `fm_photoshop` (élément
  `ps_doc`) et `fm_design` retouchent des images dans le board, sans lien avec la visionneuse.
- **Attributs** (`fm_visionneuse/file_attributes.py`) : `.pipeline_attributes.json` par dossier ; pour un dossier
  associé à Lightroom, Lightroom est la source EXCLUSIVE (aucune écriture locale).

Risques relevés : (1) un rendu qui ne change pas la date du fichier n'est jamais redécodé -> les rendus ont leur
propre entrée dans le chargeur ; (2) `_on_focus_preview_ready` invalide le chargeur à chaque aperçu du pipeline ->
`invalidate` ne retire pas un rendu ; (3) des images float ne doivent pas vivre dans le cache 700 Mo -> cache des
sources à part (`ServiceRendu.BUDGET_SOURCES`) ; (4) pellicule et planche ne montrent pas encore le développement ;
(5) photos Lightroom : l'image du centre est le rendu de Lightroom (recadrage et rotation du catalogue compris).

## Contrat Lightroom OBSERVÉ (figé par `tests/test_lightroom_contract.py`)

Ce que l'appli échange réellement ; rien d'autre n'est synchronisé. Ne pas le modifier sans adapter ces tests.

| Donnée | Sens | Moyen |
|---|---|---|
| Association dossier -> catalogue | fichier `.pipeline_lightroom.json` dans le dossier (ou un parent) | `managed_folder`, mémorisé 30 s |
| Identité (uuid `id_global`, id local), note, libellé de couleur, drapeau, mots clés, orientation, format | Lightroom -> appli | SQLite du `.lrcat` en LECTURE SEULE (`mode=ro`, `query_only`, repli `immutable`) : `_catalog_photo` |
| Révision de développement (`developSettingsIDCache:modTime`) | Lightroom -> appli | même lecture ; sert de clé aux aperçus et au profil |
| Aperçus développés | Lightroom -> appli | pyramide `Previews.lrdata` (lecture) ; à défaut rendu demandé au module SDK (`op=preview`, JPEG 2560) |
| NOM du profil de développement (`Look.Name` / `CameraProfile`) | Lightroom -> appli | module SDK, `op=profile` ; aucun autre réglage de développement n'est lu |
| Note, couleur, drapeau, mots clés | appli -> Lightroom | module SDK seulement, `op=set`, dans `withWriteAccessDo` |
| Ouvrir la photo dans Lightroom | appli -> Lightroom | `op=open` |

- Protocole du module (`plugins/PipelineLightroom.lrplugin/Start.lua`) : fichier `requests/<id>.req` = 9 champs
  (`id, op, uuid, field, before, value, target, collection, catalog`) en hexadécimal UTF-8 séparés par des
  tabulations ; réponse `replies/<id>.json` ; `status.json` (battement < 5 s, table des libellés de couleur). Le
  champ `before` existe mais est toujours vide : aucune détection de conflit à l'écriture aujourd'hui.
- Pas de boucle possible : Lightroom -> appli est une LECTURE à la demande (cache invalidé après une écriture
  confirmée) ; appli -> Lightroom n'a lieu que sur un geste de l'utilisateur. Aucune écriture directe dans le
  catalogue, aucun XMP lu ni écrit.
- Décision (2026-11-14) : l'état de développement PIPE FMZ est PROPRE à l'appli (`.pipeline_photo.json`), jamais
  envoyé à Lightroom. Pour une photo d'un dossier associé, la visionneuse garde le rendu de Lightroom : un état PIPE
  FMZ enregistré ne le remplace pas d'office (`rendu._Tache._geree_par_lightroom`). À ARRÊTER AVEC L'UTILISATEUR :
  comment choisir, par photo, entre « rendu Lightroom » et « développement PIPE FMZ depuis l'original ».

Étude « métadonnées communes » (rien d'implémenté) : trois familles à ne pas mélanger — descriptives (note, couleur,
drapeau, mots clés ; source = Lightroom si dossier associé, sinon `.pipeline_attributes.json`), réglages de
développement (Lightroom : opaques, seul le nom du profil est lisible ; PIPE FMZ : `etat.py`), état propre à PIPE
FMZ (versions, recettes). Représentation visée par valeur : `{valeur, provenance, révision de la source, lu le}` ;
conflit = la révision de la source a changé depuis la dernière lecture ET la valeur locale diffère (le champ
`before` du protocole permettrait une écriture conditionnelle). XMP : les champs descriptifs (`xmp:Rating`,
`xmp:Label`, `dc:subject`) sont lisibles pour des dossiers NON associés ; les réglages `crs:` d'Adobe ne sont ni
interprétables ni reproductibles par un autre moteur ; ne jamais écrire le XMP d'une photo gérée par Lightroom.

## Contrats du moteur

- **Couleur** (`couleur.py`) : travail = Rec.2020 linéaire D65 float32, non borné ; domaines distincts linéaire scène /
  log Cineon / densité / affichage ; matrices calculées des chromaticités, Bradford seulement si les blancs diffèrent ;
  transferts impairs (pas de NaN) ; l'écrêtage est un paramètre nommé de la sortie (`depuis_travail(ecreter=)`), seule
  transformation de sortie à ce jour (pas un rendu de gamut) ; quantification par arrondi, sans tramage. Affichage :
  sRGB 8 bits, comme la visionneuse. Modèle RGB : aucune prétention spectrale.
- **État** (`etat.py`) : dictionnaire JSON, clés inconnues gardées ; version = suite ORDONNÉE d'opérations
  `{op, version, actif, params}` ; chaque opération porte la version de son algorithme, chaque version celle du
  moteur ; fonctions pures (Undo / Redo = `Historique`) ; `signature` = clé des caches ; stockage par dossier,
  écriture atomique, schéma plus récent jamais relu ni réécrit, sauvegarde `.v<n>.bak` avant migration.
- **Opérations** (`operations.py`) : aux défauts = identité (non calculée) ; opération ou version inconnue = erreur,
  jamais ignorée ; `marge` = dépendance spatiale pour les tuiles (égalité au bit près vérifiée) ; grandeurs spatiales
  en fraction de la largeur de la photo (`Contexte.echelle`) ; `validation` : « référence » ou « tranche technique »
  (interdite dans un preset). Disponibles : `exposition` (référence), `diffusion` (tranche technique, PAS l'outil
  Halation).
- **Scopes** (`scopes.py`) : deux points de mesure déclarés — « affichage » (valeurs encodées de sortie NON écrêtées :
  histogramme, forme d'onde, parade, vectorscope ; luma Y' et Cb / Cr de la Rec.709) et « travail » (CIE xy) ; hors
  bornes comptés à part (`sous`, `sur`, `exclus`), jamais rabattus en silence ; `Mesure.exhaustif` faux dès qu'on
  échantillonne. Reste : dessin (briques des réglages), calcul en fond, graticules.
- **Courbes** (`courbes.py`) : toute courbe mesurée (densité / log exposition d'un film ou d'un support, courbe de
  tonalité) est interpolée en Hermite à pentes de Fritsch-Carlson : passe par les points, C1, AUCUN dépassement
  (jamais sous D-min ni au-dessus de D-max) ; hors des données, prolongement nommé (« constante » ou « lineaire »).
  Le module ne contient aucune donnée de film.
- **Warper Teinte / Saturation** (`warper.py`) : maillage polaire (anneaux de chroma x teintes cycliques) dans le plan
  (a, b) d'Oklab, déplacements cartésiens, Catmull-Rom ; identité exacte, nœuds suivis exactement, axe neutre fixe,
  clarté inchangée, raccord 0 / 2 pi continu, `replis` (jacobien) à signaler dans l'interface. PIÈGE trouvé par les
  tests : avec les matrices Oklab publiées, R = V = B de l'espace de travail n'est pas exactement neutre (a, b ~ 3e-5)
  et le maillage teintait les gris de ~1e-4 ; LMS est normalisé au blanc de travail (`_BLANC_LMS`). Reste : Warper
  Chroma / Luma, pipette, maillage interactif, gamut.
- **Recettes** (`recettes.py`) : `type` « boitier » (réglages saisissables sur un boîtier nommé) ou « logicielle »
  (peut porter des `operations` du moteur, jamais dite transposable) ; `verifier` contrôle valeurs, pas, ISO minimale
  de DR200 / DR400 et D Range Priority, firmware, HEIF, et RAPPORTE sans rien corriger : `erreurs`,
  `non_verifiables` (plages que le manuel n'écrit pas : jamais inventées), `non_pris_en_charge` (aucun réglage de
  boîtier n'est encore rendu par le moteur : `CAPACITES_MOTEUR` vide) ; `validation` = « non validée » par défaut.
  Reste : bibliothèque (familles, recherche, favoris, versions), atelier, calibration RAW + JPEG.
- **Rendu** (`rendu.py`) : tout hors du fil de l'interface ; une demande plus récente ou `abandonner` périme les
  précédentes (calcul arrêté, résultat tardif jamais émis) ; provisoire (<= 1024 px) puis définition de l'écran ; le
  badge d'origine dit toujours lequel. La pleine définition au zoom n'est PAS encore rendue (attend le moteur Rust).
- **Export** (`export.py`) : `Travail` fige la suite ; même calcul que l'aperçu (identité pixel à pixel à échelle
  égale, testée) ; fichier provisoire puis renommage ; jamais de remplacement ni d'écriture sur l'original.

## Fluidité : budgets et état

Budgets : retour visuel d'un réglage (aperçu provisoire) < 100 ms ; arrêt après annulation < 50 ms ; aucun travail
sur le fil de l'interface au-delà du lancement d'une tâche. Relevés d'essai du 2026-11-14 (`tools/bench_photo.py`,
chaîne exposition + diffusion, une passe, i9 16 fils ; la mesure de référence reste celle de `fluidite.bat`) :

| Exécutant | Photo | Provisoire | Définition écran | Annulation -> arrêt | Pleine définition 16 bits |
|---|---|---|---|---|---|
| référence numpy | 6 MP | ~900 ms | ~14 s | ~130 ms | — |
| Rust | 24 MP | 37 ms | 267 ms (1/2) | 18 ms | 2,3 s (10,6 MP/s) |
| Rust | 40 MP | 48 ms | 197 ms (1/3) | 3 ms | 6,5 s (6,1 MP/s) |

La référence ne tient PAS les budgets (elle n'est pas faite pour ça) ; le moteur Rust les tient pour cette chaîne.
Une suite qui contient une opération que Rust ne connaît pas (aujourd'hui le Warper) repasse ENTIÈRE par la
référence : toute primitive exposée dans un outil interactif doit d'abord exister en Rust. Pleine définition : le
flou gaussien exact (plus de 240 prises à 24 MP) domine ; une accélération (pyramide, noyau récursif) se validera
contre la référence. Copies : aucune à l'entrée (tampon numpy lu en place), une copie de travail par rendu, une
à la sortie (octets -> QImage).

Écart Rust / référence (`test_photo_rust`, seuils du protocole fixés avant) : exposition identique au bit près ;
réduction à 2e-6 près ; chaîne spatiale sous Delta E 0,1 / 0,2 / 0,5 ; sortie 8 bits à 1 code près sur moins de 0,5 %
des valeurs. PyO3 0.30 : `Python::attach` / `py.detach` (ex `with_gil` / `allow_threads`) ; une fermeture passée à
`detach` capture les CHAMPS d'une structure un à un (un pointeur brut y est refusé : passer par une méthode).

## Plan d'intégration (ordre des dépendances)

1. FAIT — audit, contrat Lightroom testé, contrats couleur / état / opérations, tranche source -> rendu en fond ->
   visionneuse -> export avec l'exécutant de référence.
2. FAIT (tranche) — moteur Rust `fm_photo_moteur` : `exposition` et `diffusion`, lecture du tableau numpy sans copie,
   rayon, annulation, cache des réductions, comparé à la référence. Reste : GPU (wgpu) à évaluer, pleine définition
   au zoom, accélération du flou, chaque nouvelle primitive portée en Rust après sa référence.
3. Chaîne RAW : rawpy / LibRaw (linéaire caméra -> travail), corpus des cinq boîtiers, X-Trans ; puis optique.
4. Panneau de développement dans la visionneuse (briques des réglages, modèle `FocusInfoPanel`), enregistrement de
   l'état, avant / après, comparaison ; pellicule et planche développées.
5. FM Film : fondations densité / log, PRINT en premier, puis film, grain, halation, bloom ; presets ; recettes.
6. Scopes, Color Warpers, traitements personnels, import, lot, Board (référence à une photo + version, par
   `ServiceRendu`, sans copie d'asset ni second moteur).

## PASSATION

- Objectif : environnement photo unique autour de la visionneuse (mission du 2026-11-14) ; registre `FM_PHOTO_PROGRESS.md`.
- Fait : audit ; contrat Lightroom figé par tests ; paquet `fm_photo` (couleur, état, opérations, moteur de référence,
  sources, rendu en fond, export, scopes, Warper Teinte / Saturation, courbes monotones) ; entrée des rendus dans la
  visionneuse (`set_rendition`) branchée dans la fenêtre ; banc de vitesse ; banc comparatif (mires, Delta E 2000,
  protocole et seuils) ; format des recettes (matrice X-T5) ; docs de références.
- Fichiers : `fm_photo/*`, `fm_visionneuse/loader.py`, `main_window/photo_module.py`, `pipeline_browser.py` (3 lignes),
  `tests/test_photo_*.py`, `tests/test_lightroom_contract.py`, `tools/bench_photo.py`, `tools/install_rust.ps1`.
- Décisions : voir « Contrats du moteur » et le registre ; rien n'est commité (branche `nettoyage-code`).
- Moteur Rust construit et installé dans `.venv` (Rust 1.100, PyO3 0.30.1, maturin 1.16) ; reconstruire après toute
  modification de `src/lib.rs` : `tools\build_moteur_photo.ps1`.
- Tests : 118 tests écrits pour la mission, tous verts ; `test_focus_viewer`, `test_lightroom_*` existants verts.
- Non vérifié : coût réel dans la fenêtre entière (lignes de `a_mesurer.md`) ; aucun essai sur RAW réel.
- Reste : tout le registre au-delà des fondations ; blocages 2 à 5 (rawpy, corpus, références, décision Lightroom).
- Prochaine action : panneau de développement dans la visionneuse (exposition d'abord, primitives suivantes portées
  en référence puis en Rust), ou chaîne RAW dès que rawpy et le corpus sont là.

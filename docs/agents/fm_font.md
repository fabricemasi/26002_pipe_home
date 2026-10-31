# Module typographique `fm_font/`

Éditeur de polices professionnel (références : FontLab 8, Glyphs, RoboFont, FontForge ; aucun code ni identité
repris). But de l'utilisateur : créer une famille complète, du premier tracé à des fichiers de police valides.
Mission autonome lancée le 2026-10-30 (aucune question à l'utilisateur, aucun test demandé à l'utilisateur).

**Tests** : `.venv/Scripts/python.exe tests/run.py fm_font` (`tests/test_fm_font*.py` ; les dépendances sont dans
`.venv`, le Python global n'a ni ufo2ft ni uharfbuzz). **Mesures** : `python -m fm_font.bench 1000` (modèle,
multimasters) et `python -m fm_font.bench 1000 --qt` (canvas, grille, aperçu ; offscreen).

**Utilisation** : double-clic sur un `.ufo` / `.designspace` / `.ttf` / `.otf` / `.woff(2)` d'une colonne, ou menu
d'une colonne « Créer un projet typographique ». Pages : Glyphes (Ctrl+1), Éditeur (Ctrl+2, double-clic sur un
glyphe), Aperçu (Ctrl+3), Features (Ctrl+4, Ctrl+Entrée = appliquer), Diagnostic (Ctrl+5). Outils : V sélection,
P plume, B crayon, R rectangle, E ellipse, Y polygone (Alt = étoile), C plume calligraphique, W brosse, M mesure,
K couteau (Maj = 45°), H main ; Espace tenu / bouton du milieu = déplacer la vue ; molette = zoom ; flèches = déplacer (Maj ×10) ;
Suppr ; double-clic sur un nœud = lisse / coin ; clic droit = opérations (nœuds, contours, tracés, transformer,
aligner, composants, ancres). Clic sur une règle = repère. Ctrl+Z / Ctrl+Y, Ctrl+S.

## Carte : fonctionnalité -> fichier

Couches : chaque fichier n'importe que ceux qui le précèdent. Le MODÈLE n'importe pas Qt. Le module n'importe
RIEN de la fenêtre principale (elle lui pose des `HOOKS`).

| Fonctionnalité | Fichier | Points d'entrée |
|---|---|---|
| Extensions reconnues | `__init__.py` | `is_font_source`, `is_font_file` |
| Unicode : nom <-> code, catégorie, écriture, jeux de caractères | `glyph_info.py` | `name_for_unicode`, `unicode_for_name`, `category`, `script`, `CHARSETS`, `decomposition` |
| Annuler / rétablir (une étape = un geste) | `undo.py` | `UndoStack`, `glyph_snapshot`, `glyph_restore` |
| Projet : famille, masters, création / ouverture / sauvegarde atomique, glyphes (créer, supprimer, dupliquer, renommer, Unicode) | `document.py` | `FontProject` (`new`, `open`, `save`, `add_glyph`, `add_glyphs_for_unicodes`, `delete_glyphs`, `duplicate_glyph`, `rename_glyph`, `set_unicodes`, `begin_edit` / `end_edit`, `edit_glyph`, `set_info`, `add_master`), `save_ufo_atomic`, `recover_interrupted_save` |
| Bézier : segments, coin / lisse / symétrique, ajout / suppression / division, ouverture / fermeture, sens, départ, cubique <-> quadratique | `contours.py` | `segments`, `segment_refs`, `insert_point`, `delete_points`, `set_smooth`, `align_handles`, `make_symmetric`, `open_at`, `close`, `reverse`, `set_start_point`, `wrong_directions`, `correct_directions`, `contour_to_quadratic`, `contour_to_cubic`, `nearest_on_segment` |
| Géométrie : transformations, symétrie, booléens, chevauchements, simplification, arrondi, coins arrondis, alignement, mesures | `geometry.py` | `move_points`, `transform_glyph`, `mirror`, `boolean`, `remove_overlaps`, `simplify`, `round_coordinates`, `round_corners`, `align`, `distribute`, `measure`, `intersections_with_line`, `flattened` |
| Formes et crayon (ajustement de Schneider) | `shapes.py` | `rectangle`, `ellipse`, `polygon`, `pencil_contour`, `fit_cubic` |
| Calligraphie : plume à angle, brosse, pression, lissage, contours éditables | `calligraphy.py` | `outline` |
| Couteau : coupe exacte le long d'un segment (contours fermés, contre-formes reliées, contours ouverts) | `knife.py` | `cut` |
| Métriques : approches, chasse, centrage, chaînes de contrôle | `metrics.py` | `left_margin`, `set_left_margin`, `set_right_margin`, `set_width`, `CONTROL_STRINGS` |
| Crénage : paires, classes, exceptions, aide automatique | `kerning.py` | `lookup`, `target_pair`, `set_value`, `set_group`, `is_exception`, `suggest` |
| Composants, ancres, accentués, cycles | `components.py` | `add_component`, `decompose`, `find_cycles`, `would_cycle`, `set_anchor`, `build_accented` |
| Features .fea : vérification lisible, génération, fusion | `features.py` | `check`, `generate`, `merge`, `set_features` |
| Mise en forme HarfBuzz (vérification indépendante) | `shaping.py` | `Shaper` |
| Masters : compatibilité, interpolation, instances | `interpolation.py` | `incompatibilities`, `interpolate_glyph`, `instance_font` |
| Axes de variation : édition, CARTES (avar), positions des masters, instances multi-axes (saisie texte) | `axes.py` | `set_axes`, `parse_axes`, `format_axes`, `set_master_location`, `parse_location`, `parse_instances`, `format_instances`, `design_ranges` |
| Compilation / export (statique, WOFF, WOFF2, variable) | `compile.py` | `compile_static`, `compile_variable`, `export` |
| Import TTF / OTF / WOFF / WOFF2 / UFO / Designspace / SVG | `importer.py` | `open_any`, `import_binary`, `import_svg` |
| Diagnostic trois niveaux, FontBakery facultatif | `validation.py` | `diagnose`, `fontbakery_report` |
| Mesures reproductibles | `bench.py`, `bench_qt.py` | `python -m fm_font.bench [N] [--qt]` |
| Défauts des réglages `typo_*` | `settings_defaults.py` | `TYPO_DEFAULTS` |
| Rendu Qt : chemins des glyphes, cache invalidé finement (glyphe + composés qui l'utilisent) | `render.py` | `PathCache`, `glyph_path`, `QPathPen` |
| Canvas : zoom, pan, règles, grille, métriques, rempli / contour / comparaison, nœuds, ancres, composants, repères, magnétisme | `canvas.py` | `GlyphCanvas` (`set_glyph`, `fit`, `zoom_at`, `pan`, `hit_*`, `snap`, `edit`, `changed_live`, `end_interaction`) |
| Outils : sélection, plume, crayon, rectangle, ellipse, polygone, plume calligraphique, brosse, mesure, couteau, main | `tools.py` | `TOOLS`, `TOOL_KEYS` |
| Grille des glyphes : recherche, filtres, manquants | `glyph_grid.py` | `GlyphGrid` |
| Aperçu : ligne, paragraphe, cascade, masters ; crénage visuel ; HarfBuzz en fond | `preview.py` | `PreviewWidget`, `parse_text` |
| Panneaux (briques des réglages) : glyphe, famille, crénage, masters ; pages Features et Diagnostic | `panels.py` | `GlyphPanel`, `FontPanel`, `KerningPanel`, `MastersPanel`, `FeaturesPage`, `DiagnosticsPage` |
| Menus contextuels (canvas, grille) : opérations réelles | `actions.py` | `canvas_menu`, `grid_menu`, `node_type`, `contour_op`, `glyph_op` |
| Espace de travail plein écran, fichiers, export (dont instances statiques), HOOKS | `pane.py` | `FontPane`, `HOOKS`, `instance_locations` |
| Polices couleur COLR v0 / CPAL (palette, calques ; clés lib d'ufo2ft) | `color.py` | `set_palette`, `set_layers`, `parse_palette`, `parse_layers` |
| Hinting TrueType (ttfautohint, repli « symbole ») | `hinting.py` | `autohint`, `available` |
| Sauvegarde de SECOURS (travail non enregistré, proposée à la réouverture) | `autosave.py` | `Autosaver` (`write`, `find`, `restore`, `discard`), `snapshot` |
| Réglages `typo_*` dans le catalogue (fenêtre « Réglages : Typographie ») | `settings.py` | `TYPO_TAB`, `TYPO_TREE` |
| BRANCHEMENT dans la fenêtre principale (hors du paquet) | `main_window/font_module.py` | `FontModuleMixin` : `_font_claims`, `_open_font`, `_leave_font`, `_close_font` |
| Menu de colonne « Créer un projet typographique » (hors du paquet) | `column_parts/context_menu.py`, `column_parts/file_operations.py` | `_create_font_project` |

## Décisions

- **Bibliothèques** (évaluées le 2026-10-30, Python 3.12 Windows, roues binaires présentes) :
  fontTools 4.66 (MIT, compilateur feaLib / varLib, cu2qu), ufoLib2 0.19 (Apache-2.0, modèle UFO 3),
  ufo2ft 3.10 (MIT, compilateur UFO -> OTF / TTF / variable, feature writers kern / mark),
  uharfbuzz 0.57 (Apache-2.0, HarfBuzz), skia-pathops 0.9 (BSD-3, booléens), brotli (MIT, WOFF2).
  ÉCARTÉS : fontmake (simple surcouche CLI d'ufo2ft), FontBakery (très nombreuses dépendances, lancé s'il est
  installé : `validation.fontbakery_report`), booleanOperations direct (pathops plus robuste ; ufo2ft le tire).
  Aucun compilateur OpenType ni moteur de mise en forme réécrit.
- **Modèle = objets ufoLib2** (UFO 3 natif) enveloppés par `FontProject` : rien à traduire à l'enregistrement,
  données inconnues préservées (lib, data/, images/ ; testé). Ouverture NON paresseuse (`lazy=False`) : la
  sauvegarde atomique renomme le dossier, un UFO paresseux relirait l'ancien.
- **Projet** : un `.ufo` (un master) ou un `.designspace` + `masters/<Famille>-<Style>.ufo`. Les opérations sur
  les glyphes (créer, supprimer, renommer…) touchent TOUS les masters (compatibilité d'interpolation).
- **Sauvegarde atomique** : UFO écrit dans `<nom>.fmf-tmp`, l'ancien renommé `<nom>.fmf-bak`, échange, copie
  supprimée ; `recover_interrupted_save` (appelé à l'ouverture) restaure ou nettoie. Renommage réessayé (Windows,
  dossier synchronisé : PermissionError brève). Fichier importé (TTF…) jamais écrasé (`project.source`, export
  refusé sur ce chemin).
- **Annulation** : une étape par geste (instantané au clic, étape au relâché) ; instantané en tuples (0,06 ms pour
  400 points), jamais de deepcopy pendant un mouvement.
- **Sens des contours** : convention PostScript / UFO (extérieur anti-horaire) ; ufo2ft inverse pour le TTF.
- **kern / mark / mkmk** : générés par ufo2ft depuis le crénage et les ancres (pas écrits dans le .fea).
- **Interpolation** : le modèle de variation de fontTools (le même que la police variable) ; un glyphe incompatible
  lève `InterpolationError` avec la raison exacte, jamais de résultat faux silencieux.
- **Coordonnées** (convention du Designspace) : min / défaut / max d'un axe en valeurs UTILISATEUR (fvar) ;
  positions des masters et des instances en valeurs de CONCEPTION ; la carte de l'axe (avar) les relie.
  L'interpolation normalise dans l'espace de conception (`axes.design_ranges`). L'éditeur des instances parle
  utilisateur ; « Position du master » parle conception. Changer une carte garde la position UTILISATEUR des
  masters (aucun refus surprise) ; on corrige ensuite leur position de conception.
- **Réglages** : préfixe `typo_` (le préfixe `font_` est déjà celui des polices de l'interface). Tolérances en
  DIXIÈMES (curseurs entiers des réglages, `scale: 10`). Appliqués en direct au module ouvert
  (`settings_link._apply_settings`, chemin rapide des clés `typo_`).
- **Accès** (2026-10-30) : double-clic sur une source (`.ufo` = DOSSIER, `.designspace`) ou une police
  (`.ttf`, `.otf`, `.woff`, `.woff2`, importée) dans une colonne (réglage `typo_open_double_click`, vrai par
  défaut) ; menu d'une colonne (zone vide) « Créer un projet typographique » (UFO vierge, puis double-clic). Pas
  d'accès depuis le Board (un projet de police n'est pas un élément de tableau blanc). Modes exclusifs : ouvrir
  l'éditeur Markdown, le board ou la vidéo ferme d'abord le module (`_leave_font`, questions si modifié) ; fermer
  l'appli aussi (`closeEvent`).
- **Ctrl + glisser** (règle de l'appli) : composants et repères se DÉPLACENT avec Ctrl ; nœuds, poignées, ancres
  et crénage à la souris dans l'aperçu (Ctrl + glisser aussi) ; les nœuds et poignées sont des gestes d'édition
  du tracé, tirés sans Ctrl (comme les poignées du CAD et la grille du Tableur).
- **Import** : une police compilée importée n'est PAS « modifiée » tant qu'on n'y touche pas (rien à perdre) ;
  « Enregistrer » demande où écrire la source ; l'export refuse le chemin d'origine.
- **Couleur** : COLR v0 / CPAL par les clés de lib d'ufo2ft (`com.github.googlei18n.ufo2ft.colorPalettes`,
  `.colorLayers`) ; un calque = un glyphe ordinaire. COLR v1 (dégradés) non fait.
- **Secours** : `%LOCALAPPDATA%/fm_font/secours/<clé>/` (clé = empreinte du chemin ; `FM_FONT_AUTOSAVE_DIR` dans
  les tests, jamais le vrai dossier). Sur le fil de l'interface seulement l'instantané en tuples (6,5 ms pour
  1000 glyphes ; un `deepcopy` coûtait 177 ms) ; reconstruction + écriture dans un fil. `secours.json` écrit en
  dernier (sans lui, le secours n'est pas valable). Proposé à l'ouverture s'il est plus récent que le fichier ;
  supprimé après un enregistrement, une fermeture voulue ou un refus.
- **Export en fond** : la compilation (~2 s pour 1000 glyphes, surtout la suppression des chevauchements) ne
  fige jamais l'interface : instantané du projet (`autosave.snapshot`), projet INDÉPENDANT reconstruit dans le fil
  (`project_from_snapshot`), résultat dans la barre d'état. Modifier le projet pendant l'export ne change pas la
  police produite (testé).
- **Hinting** : ttfautohint (ttfautohint-py, roue Windows avec binaire) pour le TrueType ; sans « o » latin, repli
  automatique en mode symbole. Pas de hinting PostScript (CFF).

## État des fonctions

Légende : TERMINÉ (fonctionne, sauvegardé si besoin, testé) / PARTIEL / NON COMMENCÉ / BLOQUÉ.

| Fonctionnalité | Statut | Remarques |
|---|---|---|
| Modèle, projet, sauvegarde atomique, réouverture, récupération | TERMINÉ | `ProjectTest` |
| Glyphes : créer, supprimer (refus si composant), dupliquer, renommer partout, Unicode | TERMINÉ | modèle ; interface : voir plus bas |
| Bézier (modèle) | TERMINÉ | `BezierTest` (division exacte, tolérance cu2qu testée à 0,25 / 1 / 4 u) |
| Géométrie (modèle) : transformations, symétrie, booléens, chevauchements, simplification, arrondi des coordonnées, COINS ARRONDIS, alignement, mesures | TERMINÉ | `GeometryTest` ; coins arrondis entre lignes ET cubiques (segments raccourcis par division exacte, arc tangent ; rayon exact entre droites) ; pas entre quadratiques |
| Crayon, calligraphie (modèle) | TERMINÉ | pression = 3e valeur des échantillons |
| Composants, ancres, accentués, cycles (modèle) | TERMINÉ | propagation structurelle testée |
| Métriques, crénage, aide automatique (modèle) | TERMINÉ | suggestions jamais appliquées seules |
| Features : vérification, génération liga / dlig / smcp / c2sc / onum / lnum / tnum / pnum / case / salt / ssXX | TERMINÉ (modèle) | frac : génération sommaire |
| Compilation OTF / TTF / WOFF / WOFF2, vérifiée fontTools + HarfBuzz (crénage, liga, mark, mkmk) | TERMINÉ | `CompileTest` |
| Masters, interpolation, police variable (fvar / gvar / STAT / avar, instances) | TERMINÉ | `test_fm_font_axes` (avar relue par fontTools, chasse vérifiée par HarfBuzz) |
| Import TTF / OTF / WOFF / WOFF2 / SVG | TERMINÉ | features GSUB non reprises (message) |
| Diagnostic trois niveaux | TERMINÉ | FontBakery non installé |
| Interface : espace de travail, pages, barre, état « modifié », fermeture prudente | TERMINÉ | `test_fm_font_pane` |
| Grille : recherche (nom, caractère, U+), filtres, manquants (création au double-clic), menus | TERMINÉ | virtualisée |
| Éditeur : canvas, zoom / pan, règles + repères, grille, métriques, rempli / contour / comparaison | TERMINÉ | `test_fm_font_canvas` |
| Outils : sélection (points, segments, contours, cadre), plume, crayon, rectangle, ellipse, polygone / étoile, calligraphie, brosse, mesure, couteau, main | TERMINÉ | gestes simulés testés ; couteau : `test_fm_font_knife` (aire conservée, « o » -> deux C) |
| Saisie numérique précise (coordonnées, chasse, approches, Unicode, nom ; métriques de famille) | TERMINÉ | tableaux des réglages |
| Aperçu : ligne, paragraphe, cascade, masters ; crénage visuel (Alt + flèches, Ctrl + glisser) ; HarfBuzz + features | TERMINÉ | compilation de fond |
| Éditeur de features : erreurs lisibles, génération, application | TERMINÉ | |
| Diagnostic (page) + FontBakery facultatif | TERMINÉ | FontBakery non installé ici |
| Masters dans l'interface : ajout (copie compatible), choix, comparaison, compatibilité | TERMINÉ | |
| Instances nommées (éditeur dans le panneau Masters ; fvar de la police variable ; exports statiques interpolés) | TERMINÉ | `InstancesTest`, `test_fm_font_axes` ; plusieurs axes (« Bold Condensed wght=700 wdth=75 ») |
| Polices couleur COLR v0 / CPAL (palette, calques ; panneaux) | TERMINÉ | `test_fm_font_color` ; COLR v1 NON COMMENCÉ |
| Hinting TrueType (ttfautohint) : export TTF / WOFF2 hinté | TERMINÉ | CFF non hinté |
| Classes de crénage depuis la grille (gauche, droite, retirer) | TERMINÉ | |
| Branchement fenêtre principale (double-clic, plein cadre, modes exclusifs, fermeture) | TERMINÉ | `test_fm_font_integration` |
| Menu de colonne « Créer un projet typographique » | TERMINÉ | |
| Réglages `typo_*` (catalogue, fenêtre du module, direct) | TERMINÉ | |
| Récupération après plantage (secours du travail non enregistré, toutes les 60 s, en fond) | TERMINÉ | `test_fm_font_autosave` |
| Métriques DANS la vue : tirer la ligne de chasse / d'origine | TERMINÉ | `test_metrics_dragged_in_view` |
| Chaînes de contrôle dans l'aperçu (minuscules, capitales, chiffres, rondes, glyphe courant) | TERMINÉ | menu du mode de l'aperçu |
| Axes (plusieurs, ajout / retrait / renommage) et cartes avar : édition ; position de conception du master courant | TERMINÉ | panneau Masters, « Variation » ; un changement de carte garde la position UTILISATEUR des masters |

## Mesures (2026-10-30, `python -m fm_font.bench 1000`, dossier temporaire local)

| Parcours | Temps |
|---|---|
| Déplacer un pas (10 contours sélectionnés, glyphe de 400 points) | 0,06 ms |
| Instantané d'annulation / restauration du glyphe de 400 points | 0,06 / 0,10 ms |
| Créer 1000 glyphes | 20 ms |
| Enregistrer 1000 glyphes (UFO atomique) / ouvrir | 1 180 / 515 ms |
| Compiler TTF / OTF 1000 glyphes | ~2 100 ms chacun (toujours hors du fil de l'interface) |
| Diagnostic 1000 glyphes | 330 ms -> 90 ms (sens des contours sans copie du glyphe) |
| Compatibilité de 2 masters (1000 glyphes) / interpoler un glyphe | 6 / 0,3 ms |
| Instance complète interpolée (1000 glyphes) / police variable (1000 glyphes, 2 masters) | 330 / 460 ms |
| Export depuis l'interface | dans un FIL : instantané 6,5 ms sur le fil de l'interface (`export_to(background=True)`) |

### Mesures Qt (`python -m fm_font.bench 200 --qt`, offscreen, 1200 x 900, glyphe de 400 points plein écran)

| Parcours | Avant | Après |
|---|---|---|
| Un pas de glisser (déplacer + invalider + peindre) | 73 ms | 13 ms |
| Zoom (un cran + peinture) | 39 ms | 8,5 ms |
| Pan (un pas + peinture) | 14 ms | 6 ms |
| Chemin du glyphe refait (invalidation) | 0,7 ms | 0,7 ms |
| Grille : filtrer 1000 glyphes / peindre un écran | 1 / 14 ms | |
| Aperçu : ligne de 40 glyphes / un cran de crénage | 1,1 / 1,3 ms | |
| Couteau sur le glyphe de 400 points : aperçu par mouvement (contours aplatis gardés pendant le geste) / coupe | 5,5 -> 2,3 ms / 33 ms | |
| Ouverture de l'espace de travail (fenêtre de réglages déjà chargée) | 180 ms | |

Ce qui a coûté (cProfile) : le REMPLISSAGE ANTICRÉNELÉ (28 ms, proportionnel à la surface) et le TRAIT
ANTICRÉNELÉ DE COURBES par Qt (37 ms). Remèdes : contours tracés en polylignes aplaties dans l'espace écran
(`GlyphCanvas._stroke`, 2 ms), remplissage sans anticrénelage PENDANT un geste seulement (`interacting`, net au
relâché et 160 ms après le dernier cran de molette), fond + grille + métriques en image gardée (`_background`),
nœuds regroupés par aspect (`drawLines` / `drawRects`), stylo d'1 px entier.

Piège des tests : `QTest.qWait` GARDE le verrou Python avec PySide 6.11 ; un fil de fond (compilation de
l'aperçu HarfBuzz) n'avance pas pendant l'attente. Attendre avec `time.sleep` + `processEvents`
(`PaneTest.flush`). L'appli réelle (`app.exec`) libère le verrou.

## PASSATION (2026-10-30)

- Commits (branche `nettoyage-code`, locaux, rien de poussé) : 1) modèle sans Qt ; 2) interface Qt ; 3) branchement
  dans fm_browser + réglages + couleur / hinting / instances / secours / coins arrondis / métriques dans la vue ;
  4) instances nommées, export en fond, mesures multimasters ; 5) aperçu HarfBuzz compilé sur un instantané.
- Cette doc fait ~210 lignes : à découper en sous-docs (`docs/agents/fm_font/<partie>.md` + la carte) si elle
  grandit encore (règle des docs de module).
- Tests : `python tests/run.py fm_font` (7 fichiers, ~70 tests, ~11 s). Suite complète `--tout` après le
  branchement : mêmes échecs que la référence d'avant fm_font (14 fichiers : test_board 1, test_file_attributes 3,
  test_focus_viewer 6 instables, test_input_tabs_settings 1, test_interface_edit_scope 1, test_md_live_preview 1,
  test_render_log 2, test_row_templates 1, test_settings_preload 3+1, test_shadows 1, test_software_launch 1,
  test_table_split 2, test_viewer_buttons 1, test_viewer_filter 4) ; `test_md_tables` a échoué UNE fois
  (`pane.flush()` du moteur web sous charge) puis passé 3 fois sur 3 : intermittent, sans lien.
  `test_settings_window_v2.test_tabs_are_general_ones_only` attend maintenant l'onglet « font ».
- Fichiers PARTAGÉS avec des modifications non commitées d'une autre session : seules MES lignes sont commitées,
  par un index construit sur HEAD (`git hash-object -w` + `git update-index --cacheinfo`, script de la session
  `stage_mine.py` : remplacements appliqués au fichier de travail ET à la version HEAD) : `tests/run.py`,
  `pipeline_browser.py` (mixin, `self._font`, `closeEvent`), `settings_store.py` (TYPO_DEFAULTS),
  `settings_window_v2.py` (onglet, MODULE_SCOPES / TITLES, menu « Restaurer »), `main_window/settings_link.py`
  (chemin rapide `typo_`, `_module_open`), `tests/test_settings_window_v2.py` (onglet attendu). Le reste de ces
  fichiers (travail de l'autre session) est resté intact et non commité.
- Prochaines actions possibles : éditeur des instances nommées et des cartes d'axes (avar) ; COLR v1 ; outil
  couteau ; coins arrondis entre courbes ; hinting PostScript ; FontBakery (installer `fontbakery`, la page
  Diagnostic le lance déjà s'il est présent).
- Limites connues : rendu vérifié en offscreen seulement (pas d'écran ici) ; la tablette (pression) n'est testée
  que par la valeur transmise aux outils (`canvas.pressure`), pas avec un vrai stylet.

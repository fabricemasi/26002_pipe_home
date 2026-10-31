# Module typographique `fm_font/`

Éditeur de polices professionnel (références : FontLab 8, Glyphs, RoboFont, FontForge ; aucun code ni identité
repris). But de l'utilisateur : créer une famille complète, du premier tracé à des fichiers de police valides.
Mission autonome lancée le 2026-10-30 (aucune question à l'utilisateur, aucun test demandé à l'utilisateur).

**Tests** : `python tests/run.py fm_font` (`tests/test_fm_font*.py`). **Mesures** : `python -m fm_font.bench 1000`
(modèle) et `python -m fm_font.bench 1000 --qt` (canvas, offscreen).

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
| Géométrie : transformations, symétrie, booléens, chevauchements, simplification, arrondi, alignement, mesures | `geometry.py` | `move_points`, `transform_glyph`, `mirror`, `boolean`, `remove_overlaps`, `simplify`, `round_coordinates`, `align`, `distribute`, `measure`, `intersections_with_line` |
| Formes et crayon (ajustement de Schneider) | `shapes.py` | `rectangle`, `ellipse`, `polygon`, `pencil_contour`, `fit_cubic` |
| Calligraphie : plume à angle, brosse, pression, lissage, contours éditables | `calligraphy.py` | `outline` |
| Métriques : approches, chasse, centrage, chaînes de contrôle | `metrics.py` | `left_margin`, `set_left_margin`, `set_right_margin`, `set_width`, `CONTROL_STRINGS` |
| Crénage : paires, classes, exceptions, aide automatique | `kerning.py` | `lookup`, `target_pair`, `set_value`, `set_group`, `is_exception`, `suggest` |
| Composants, ancres, accentués, cycles | `components.py` | `add_component`, `decompose`, `find_cycles`, `would_cycle`, `set_anchor`, `build_accented` |
| Features .fea : vérification lisible, génération, fusion | `features.py` | `check`, `generate`, `merge`, `set_features` |
| Mise en forme HarfBuzz (vérification indépendante) | `shaping.py` | `Shaper` |
| Masters : compatibilité, interpolation, instances | `interpolation.py` | `incompatibilities`, `interpolate_glyph`, `instance_font` |
| Compilation / export (statique, WOFF, WOFF2, variable) | `compile.py` | `compile_static`, `compile_variable`, `export` |
| Import TTF / OTF / WOFF / WOFF2 / UFO / Designspace / SVG | `importer.py` | `open_any`, `import_binary`, `import_svg` |
| Diagnostic trois niveaux, FontBakery facultatif | `validation.py` | `diagnose`, `fontbakery_report` |
| Mesures reproductibles | `bench.py`, `bench_qt.py` | `python -m fm_font.bench [N] [--qt]` |
| Défauts des réglages `typo_*` | `settings_defaults.py` | `TYPO_DEFAULTS` |
| Rendu Qt : chemins des glyphes, cache invalidé finement (glyphe + composés qui l'utilisent) | `render.py` | `PathCache`, `glyph_path`, `QPathPen` |
| Canvas : zoom, pan, règles, grille, métriques, rempli / contour / comparaison, nœuds, ancres, composants, repères, magnétisme | `canvas.py` | `GlyphCanvas` (`set_glyph`, `fit`, `zoom_at`, `pan`, `hit_*`, `snap`, `edit`, `changed_live`, `end_interaction`) |
| Outils : sélection, plume, crayon, rectangle, ellipse, polygone, plume calligraphique, brosse, mesure, main | `tools.py` | `TOOLS`, `TOOL_KEYS` |
| Grille des glyphes : recherche, filtres, manquants | `glyph_grid.py` | `GlyphGrid` |
| Aperçu : ligne, paragraphe, cascade, masters ; crénage visuel ; HarfBuzz en fond | `preview.py` | `PreviewWidget`, `parse_text` |
| Panneaux (briques des réglages) : glyphe, famille, crénage, masters ; pages Features et Diagnostic | `panels.py` | `GlyphPanel`, `FontPanel`, `KerningPanel`, `MastersPanel`, `FeaturesPage`, `DiagnosticsPage` |
| Menus contextuels (canvas, grille) : opérations réelles | `actions.py` | `canvas_menu`, `grid_menu`, `node_type`, `contour_op`, `glyph_op` |
| Espace de travail plein écran, fichiers, export, HOOKS | `pane.py` | `FontPane`, `HOOKS` |

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
- **Réglages** : préfixe `typo_` (le préfixe `font_` est déjà celui des polices de l'interface).

## État des fonctions

Légende : TERMINÉ (fonctionne, sauvegardé si besoin, testé) / PARTIEL / NON COMMENCÉ / BLOQUÉ.

| Fonctionnalité | Statut | Remarques |
|---|---|---|
| Modèle, projet, sauvegarde atomique, réouverture, récupération | TERMINÉ | `ProjectTest` |
| Glyphes : créer, supprimer (refus si composant), dupliquer, renommer partout, Unicode | TERMINÉ | modèle ; interface : voir plus bas |
| Bézier (modèle) | TERMINÉ | `BezierTest` (division exacte, tolérance cu2qu testée à 0,25 / 1 / 4 u) |
| Géométrie (modèle) | TERMINÉ | `GeometryTest` |
| Crayon, calligraphie (modèle) | TERMINÉ | pression = 3e valeur des échantillons |
| Composants, ancres, accentués, cycles (modèle) | TERMINÉ | propagation structurelle testée |
| Métriques, crénage, aide automatique (modèle) | TERMINÉ | suggestions jamais appliquées seules |
| Features : vérification, génération liga / dlig / smcp / c2sc / onum / lnum / tnum / pnum / case / salt / ssXX | TERMINÉ (modèle) | frac : génération sommaire |
| Compilation OTF / TTF / WOFF / WOFF2, vérifiée fontTools + HarfBuzz | TERMINÉ | `CompileTest` |
| Masters, interpolation, police variable (fvar / gvar / STAT, instances) | TERMINÉ (modèle) | avar : seulement si le Designspace a des `map` |
| Import TTF / OTF / WOFF / WOFF2 / SVG | TERMINÉ | features GSUB non reprises (message) |
| Diagnostic trois niveaux | TERMINÉ | FontBakery non installé |
| Interface : espace de travail, pages, barre, état « modifié », fermeture prudente | TERMINÉ | `test_fm_font_pane` |
| Grille : recherche (nom, caractère, U+), filtres, manquants (création au double-clic), menus | TERMINÉ | virtualisée |
| Éditeur : canvas, zoom / pan, règles + repères, grille, métriques, rempli / contour / comparaison | TERMINÉ | `test_fm_font_canvas` |
| Outils : sélection (points, segments, contours, cadre), plume, crayon, rectangle, ellipse, polygone / étoile, calligraphie, brosse, mesure, main | TERMINÉ | gestes simulés testés |
| Saisie numérique précise (coordonnées, chasse, approches, Unicode, nom ; métriques de famille) | TERMINÉ | tableaux des réglages |
| Aperçu : ligne, paragraphe, cascade, masters ; crénage visuel (Alt + flèches, Ctrl + glisser) ; HarfBuzz + features | TERMINÉ | compilation de fond |
| Éditeur de features : erreurs lisibles, génération, application | TERMINÉ | |
| Diagnostic (page) + FontBakery facultatif | TERMINÉ | FontBakery non installé ici |
| Masters dans l'interface : ajout (copie compatible), choix, comparaison, compatibilité | TERMINÉ | instances : par l'export variable |

## Mesures (2026-10-30, `python -m fm_font.bench 1000`, dossier temporaire local)

| Parcours | Temps |
|---|---|
| Déplacer un pas (10 contours sélectionnés, glyphe de 400 points) | 0,06 ms |
| Instantané d'annulation / restauration du glyphe de 400 points | 0,06 / 0,10 ms |
| Créer 1000 glyphes | 20 ms |
| Enregistrer 1000 glyphes (UFO atomique) / ouvrir | 1 180 / 515 ms |
| Compiler TTF / OTF 1000 glyphes | ~2 100 ms chacun (toujours hors du fil de l'interface) |
| Diagnostic 1000 glyphes | 330 ms -> 90 ms (sens des contours sans copie du glyphe) |

### Mesures Qt (`python -m fm_font.bench 200 --qt`, offscreen, 1200 x 900, glyphe de 400 points plein écran)

| Parcours | Avant | Après |
|---|---|---|
| Un pas de glisser (déplacer + invalider + peindre) | 73 ms | 13 ms |
| Zoom (un cran + peinture) | 39 ms | 8,5 ms |
| Pan (un pas + peinture) | 14 ms | 6 ms |
| Chemin du glyphe refait (invalidation) | 0,7 ms | 0,7 ms |
| Grille : filtrer 1000 glyphes / peindre un écran | 1 / 14 ms | |
| Aperçu : ligne de 40 glyphes / un cran de crénage | 1,1 / 1,3 ms | |
| Ouverture de l'espace de travail (fenêtre de réglages déjà chargée) | 180 ms | |

Ce qui a coûté (cProfile) : le REMPLISSAGE ANTICRÉNELÉ (28 ms, proportionnel à la surface) et le TRAIT
ANTICRÉNELÉ DE COURBES par Qt (37 ms). Remèdes : contours tracés en polylignes aplaties dans l'espace écran
(`GlyphCanvas._stroke`, 2 ms), remplissage sans anticrénelage PENDANT un geste seulement (`interacting`, net au
relâché et 160 ms après le dernier cran de molette), fond + grille + métriques en image gardée (`_background`),
nœuds regroupés par aspect (`drawLines` / `drawRects`), stylo d'1 px entier.

Piège des tests : `QTest.qWait` GARDE le verrou Python avec PySide 6.11 ; un fil de fond (compilation de
l'aperçu HarfBuzz) n'avance pas pendant l'attente. Attendre avec `time.sleep` + `processEvents`
(`PaneTest.flush`). L'appli réelle (`app.exec`) libère le verrou.

## PASSATION

- Dernière étape validée : modèle complet sans Qt + tests (`tests/test_fm_font_model.py`, 32 tests).
- Étape suivante : interface Qt (rendu avec cache, canvas, outils, grille, panneaux, espace plein écran, branchement
  dans la fenêtre principale), puis réglages `typo_*`.
- Fichiers partagés modifiés AUSSI par une autre session (non commitée) : `tests/run.py` (ligne `fm_font` commitée
  seule par patch ciblé sur HEAD, `git update-index --cacheinfo`).

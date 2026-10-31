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
| Mesures reproductibles | `bench.py` | `python -m fm_font.bench` |

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
| Interface Qt | NON COMMENCÉ | prochaine étape |

## Mesures (2026-10-30, `python -m fm_font.bench 1000`, dossier temporaire local)

| Parcours | Temps |
|---|---|
| Déplacer un pas (10 contours sélectionnés, glyphe de 400 points) | 0,06 ms |
| Instantané d'annulation / restauration du glyphe de 400 points | 0,06 / 0,10 ms |
| Créer 1000 glyphes | 20 ms |
| Enregistrer 1000 glyphes (UFO atomique) / ouvrir | 1 180 / 515 ms |
| Compiler TTF / OTF 1000 glyphes | ~2 100 ms chacun (toujours hors du fil de l'interface) |
| Diagnostic 1000 glyphes | 330 ms -> 90 ms (sens des contours sans copie du glyphe) |

## PASSATION

- Dernière étape validée : modèle complet sans Qt + tests (`tests/test_fm_font_model.py`, 32 tests).
- Étape suivante : interface Qt (rendu avec cache, canvas, outils, grille, panneaux, espace plein écran, branchement
  dans la fenêtre principale), puis réglages `typo_*`.
- Fichiers partagés modifiés AUSSI par une autre session (non commitée) : `tests/run.py` (ligne `fm_font` commitée
  seule par patch ciblé sur HEAD, `git update-index --cacheinfo`).

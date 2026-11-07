# Module typographique `fm_font/`

Éditeur de polices professionnel (références : FontLab 8, Glyphs, RoboFont, FontForge ; aucun code ni identité
repris). But de l'utilisateur : créer une famille complète, du premier tracé à des fichiers de police valides.
Mission autonome lancée le 2026-10-30 (aucune question à l'utilisateur, aucun test demandé à l'utilisateur).

**Tests** : `.venv/Scripts/python.exe tests/run.py fm_font` (`tests/test_fm_font*.py` ; les dépendances sont dans
`.venv`, le Python global n'a ni ufo2ft ni uharfbuzz). **Mesures** : `python -m fm_font.bench 1000` (modèle,
multimasters) et `python -m fm_font.bench 1000 --qt` (canvas, grille, aperçu ; offscreen).

**Utilisation** (JAMAIS au double-clic, demande de l'utilisateur 2026-10-31) : bouton « Typographie » de la barre
de navigation (icône « A » + nœud, kind `"font"`, `btn_font` ; grisé tant que la sélection, y compris dans IN / OVER /
OUT / LOGICIELS, n'est pas une source `.ufo` (dossier) / `.designspace` ou une police `.ttf` / `.otf` / `.woff(2)`,
voir `_sync_mode_buttons` ; module ouvert = le bouton le ferme, `_toggle_font`), menu d'une ligne, de la pellicule, de la planche ou de
l'image du focus « Ouvrir dans le module typographique » (table commune `main_window/module_targets.py`, `font_target`), ou menu d'une colonne « Créer un projet typographique ». Module ouvert :
cadre « Typographie » de la barre (comme « Vidéo » / « Board », `titlebar.font_group`, `_layout_font_buttons`) :
planche / lettre (icône `gallery` <-> `single_image` comme la visionneuse, `_toggle_font_gallery`), annuler, rétablir (grisés selon la pile, libellé de l'étape en infobulle), enregistrer (fond accent si modifié),
exporter (menu des formats), engrenage = fenêtre « Réglages : Typographie », fermer ; le module ne les répète pas
dans sa barre du haut (`HOOKS["navbar_frame"]`) ; le cadre n'est refait que sur `FontPane.stateChanged` (annuler /
rétablir / modifié ont changé : 0,2 ms) ou `pageChanged`, jamais à chaque geste. RETOUR À LA PLANCHE depuis une
lettre (demande de l'utilisateur 2026-10-31) : Échap dans le canvas vide d'abord la sélection, puis revient à la
planche (`GlyphCanvas.backRequested`, la lettre quittée reste choisie et en vue) ; Échap sur la planche ferme le
module (comme avant). Pages : Glyphes (Ctrl+1), Éditeur (Ctrl+2, double-clic sur un
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
| Reprise des features d'une police compilée : GSUB -> .fea (types 1, 2, 3, 4, 7), marques GPOS -> ancres | `feature_import.py` | `gsub_to_fea`, `gpos_marks_to_anchors` |
| Diagnostic trois niveaux, FontBakery facultatif (rapport JSON rangé dans les mêmes niveaux) | `validation.py` | `diagnose`, `run_fontbakery`, `parse_fontbakery` |
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
| Polices couleur COLR v0 / v1 (aplats, dégradés linéaires / radiaux) / CPAL (clés lib d'ufo2ft) ; rendu dans l'aperçu et en fond de l'éditeur (`render.color_brush`) | `color.py`, `render.py`, `preview.py`, `canvas.py` | `set_palette`, `set_layers`, `parse_palette`, `parse_layers`, `compile_layers`, `gradient_geometry` |
| Hinting TrueType (ttfautohint, repli « symbole ») et PostScript / CFF (otfautohint d'afdko ; zones et fûts déduits) | `hinting.py` | `autohint`, `autohint_cff`, `blue_zones`, `stems`, `with_ps_hinting_info` |
| Sauvegarde de SECOURS (travail non enregistré, proposée à la réouverture) | `autosave.py` | `Autosaver` (`write`, `find`, `restore`, `discard`), `snapshot` |
| Réglages `typo_*` dans le catalogue (fenêtre « Réglages : Typographie ») | `settings.py` | `TYPO_TAB`, `TYPO_TREE` |
| BRANCHEMENT dans la fenêtre principale (hors du paquet) | `main_window/font_module.py` | `font_target`, `FontModuleMixin` : `_toggle_font`, `_open_font`, `_leave_font`, `_close_font` |
| Menu de colonne « Créer un projet typographique » (hors du paquet) | `column_parts/context_menu.py`, `column_parts/file_operations.py` | `_create_font_project` |

## Parties de la doc (lire celle du sujet seulement)

- `docs/agents/fm_font_decisions.md` : choix techniques (bibliothèques, coordonnées, fluidité, couleur, hinting,
  import, secours, export en fond).
- `docs/agents/fm_font_etat.md` : état de chaque fonction (TERMINÉ / PARTIEL…) et test qui la couvre.
- `docs/agents/fm_font_mesures.md` : mesures reproductibles (modèle et Qt) et ce qui a coûté.

## PASSATION (2026-10-30, fin de mission)

- Commits (branche `nettoyage-code`, locaux, rien de poussé) : 3312283 modèle sans Qt ; 3bef7bf interface Qt ;
  ac2ace3 branchement fm_browser + réglages + couleur v0 / hinting TTF / secours ; cfbfff4 instances nommées,
  export en fond ; 9e5d7ed aperçu HarfBuzz sur instantané ; puis 2ad4f0f axes multiples + cartes avar ; 6030455
  couteau ; 106e981 coins arrondis entre courbes ; 51ec775 COLR v1 ; 50f2066 hinting CFF (otfautohint) ; 3590f5a
  FontBakery en fond ; e1fe992 reprise des features à l'import + chevauchements par skia-pathops ; f7674fa frac ;
  4a1e3a2 calques couleur dans l'éditeur ; dernier commit : doc découpée + mesures.
- Tests : `python tests/run.py fm_font` (8 fichiers, ~85 tests, ~13 s ; `--lent` ajoute le vrai passage de
  FontBakery, ~5 s). Suite complète : voir le bilan de fin de mission (mêmes échecs que la référence d'avant
  fm_font, 14 fichiers : test_board, test_file_attributes, test_focus_viewer (instable), test_input_tabs_settings,
  test_interface_edit_scope, test_md_live_preview, test_render_log, test_row_templates, test_settings_preload,
  test_shadows, test_software_launch, test_table_split, test_viewer_buttons, test_viewer_filter).
  `test_fm_font_pane` a échoué 2 fois sur ~15 passages du module pendant la mission, jamais reproduit ensuite
  (15 passages de suite verts) : surveiller ; la cause probable est une attente trop courte d'un fil de fond.
- Fichiers PARTAGÉS avec des modifications non commitées d'une autre session : seules les lignes fm_font sont
  commitées, par un index construit sur HEAD (`git hash-object -w` + `git update-index --cacheinfo`) :
  `tests/run.py`, `pipeline_browser.py`, `settings_store.py`, `settings_window_v2.py`,
  `main_window/settings_link.py`, `tests/test_settings_window_v2.py`. Le reste de ces fichiers est intact.
- Bibliothèques facultatives installées dans `.venv` pendant la mission : afdko 5.0.1 (otfautohint), fontbakery
  1.1.0 ; aucune version de fontTools / ufo2ft / uharfbuzz changée.
- Ce qui reste possible (aucune fonction de la mission n'est en attente) : PaintTransform / PaintComposite et
  dégradés à plus de deux couleurs (COLR v1) ; décompilation des lookups GSUB contextuels et des GPOS simples /
  cursifs à l'import ; avar2.
- Limites connues : rendu vérifié en offscreen seulement (pas d'écran ici) ; la tablette (pression) n'est testée
  que par la valeur transmise aux outils (`canvas.pressure`), pas avec un vrai stylet.

- BARRE FLOTTANTE (2026-11-03) : la bande d'outils de l'éditeur est une barre de fm_theme posée sur les pages (`FontPane._build_bars`, `BarManager(self.pages)`, boutons à texte), visible seulement sur la page Éditeur ; disposition retenue dans `typo_bars` (état temps réel). Ouverture par SIMPLE CLIC sur une police dans les colonnes (demande du 2026-11-03, remplace « jamais au double-clic ») ; le bouton « précédent » de la souris le referme.

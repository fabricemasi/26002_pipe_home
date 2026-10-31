# Module Illustrator du board (`fm_illustrator/`, à la manière d'Adobe Illustrator)

Cinquième module du board (après Miro, CAD, Design, Tableur), commencé le 2026-10-31 (mission de l'utilisateur :
« éditeur d'illustration vectorielle professionnel aussi proche que possible d'Adobe Illustrator, intégré au
Board »). Activé par le bouton « Illustrator » du sélecteur de modules (`BoardPane.set_module("illustrator")`).
Tout est LOCAL ; aucun code, icône ni ressource d'Adobe. **Aucune compatibilité `.ai` n'est annoncée** (non faite).

**Tests** : `python tests/run.py fm_illustrator` (`tests/test_illustrator.py`, ~3 s) ; `fm_board` les inclut.
**Mesures** : `python tools/bench_illustrator.py [N]` (offscreen, 2400 × 1300, N tracés ; défaut 2 000).

## Carte : fonctionnalité -> fichiers (à ouvrir directement)

Couches : chaque fichier n'importe que ceux qui le précèdent. `model`, `bezier`, `svg` n'importent PAS Qt.

| Fonctionnalité | Fichier | Points d'entrée |
|---|---|---|
| Types du `.mro` (`ill_artboard`, `ill_path`), défauts, formats de plans, normalisation, style | `model.py` | `DEFAULTS`, `normalize_entity`, `new_entity`, `style_of`, `ARTBOARD_FORMATS`, `PT`, `MM` |
| Bézier : nœuds, segments, cadres exacts, point le plus proche, insertion / suppression / conversion, joindre, inverser, matrices affines, formes, `d` SVG | `bezier.py` | `node`, `segments`, `bounds`, `nearest`, `insert_node`, `set_handle`, `smooth_node`, `join`, `transform`, `rotate`, `scale`, `rect`, `ellipse`, `polygon`, `star`, `from_cubics`, `svg_d` |
| Export / import SVG | `svg.py` | `export_svg`, `path_element`, `import_svg`, `parse_d`, `arc_to_cubics`, `parse_transform`, `parse_color` |
| Éléments de la scène (plan de travail, tracé), chemin Qt gardé, zone cliquable | `items.py` | `IllArtboardItem`, `IllPathItem` (`sync`, `hit_path`, `contains_scene_point`, `geometry_rect`), `notify_moved`, `qpath` |
| Activation, événements, sélection, commandes (style, grouper, disposition, verrou, masquer, joindre, tracé transparent, pipette, plans, export / import) | `controller.py` | `IllustratorController` |
| Gestes partagés (déplacer, transformer, cadre de sélection), Sélection, Sélection directe | `tools.py` | `MoveGesture`, `TransformGesture`, `marquee_select`, `SelectTool`, `DirectTool`, `TOOL_KEYS` |
| Plume, points (ajout / suppression / conversion), formes, crayon, plan de travail, main, zoom, pipette | `tools_draw.py` | `PenTool`, `ShapeTool`…, `PencilTool`, `ArtboardTool`, `make_tools` |
| Dessin temporaire (sélection, poignées, cadre, ligne élastique, noms des plans, bulle) | `overlay.py` | `IllOverlay` |
| Barre d'outils (gauche), témoin fond / contour, barre de contrôle (haut), menus couleur / épaisseur / plans / export | `ui.py` | `IllustratorChrome`, `FillStroke` |
| Menu Objet / clic droit | `menus.py` | `fill_object_menu`, `open_context_menu` |
| Glyphes des boutons | `glyphs.py` | `paint_ill_glyph` (appelé par `fm_board.ui.paint_glyph`) |

Points de branchement dans la coque (MINIMAUX, Miro / CAD / Design inchangés) :
- `fm_board/model.py` : `DEFAULTS` reçoit les types, `normalize_item` appelle `ill_model.normalize_entity`, `ICON_ROWS`
  (`illustrator`).
- `fm_board/scene.py` : import de `fm_illustrator.items` (enregistre les types), `MODULES` + « illustrator ».
- `fm_board/view.py` : `view.illustrator` ; les crochets du module Design sont devenus GÉNÉRIQUES
  (`_module_ctl()` = Design ou Illustrator actif : `claims`, souris, clavier, curseur, dépôt de fichiers).
- `fm_board/ui.py` : `MODULES` (bouton), `paint_glyph` (« illustrator », « ill_… »), `set_module` / `toggle_cad`
  (modules exclusifs), `illustrator_active`, `_place_chrome`, `_on_tool_button` ; `eventFilter` : en mode
  Illustrator, les touches vont au contrôleur (P n'est plus l'outil dessin de Miro ; Échap ferme le board seulement
  si `controller.busy()` est faux).
- `fm_board/serialization.py` : JSON compact au-delà de 2 000 éléments (voir Mesures).

## Choix de conception (2026-10-31)

- **Moteur : la scène du board** (comme Design) : index BSP, cache par élément, pan rapide, annulation,
  enregistrement automatique, presse-papiers, griser / masquer sont ceux du board. Un objet = un élément du `.mro`
  (annulation fine, pas de copie de tout le document à chaque geste).
- **Modèle sans Qt** : géométrie dans `data["subpaths"]` (nœuds à poignées absolues, repère de l'élément) ; un
  déplacement ne change que (x, y) ; échelle / rotation / symétrie sont APPLIQUÉES aux nœuds (comme Illustrator,
  pas de matrice gardée). `rotation` du board reste 0.
- **Plans de travail** = éléments `ill_artboard` ; les objets n'en sont PAS enfants (comme Illustrator : ils
  débordent, l'export découpe). Sous les pages Design et les cadres Miro (`ARTBOARD_Z`).
- **Règle de l'appli Ctrl + glisser** (prime sur Illustrator, où glisser déplace) : Sélection = clic choisit (tout
  le groupe), glisser sans Ctrl = cadre de sélection (même depuis un objet), Ctrl + glisser = déplacer, Ctrl + Alt =
  copie ; poignées de la boîte et points / poignées de Bézier = géométrie, sans Ctrl. Sélection directe : Ctrl +
  glisser = déplacer l'objet entier. Plan de travail : Ctrl + glisser = le déplacer.
- **Mutualisation** : crayon = `fm_font.shapes.fit_cubic`, `rdp`, `smooth_polyline` (fonctions pures, import
  tardif) ; barres / menus / curseurs / sélecteur de couleur = briques du board et des réglages (`_bar`,
  `_GlyphButton`, `_TextButton`, `_menu`, `_slider`, `_ColorPickerPopup`). Les contours UFO de fm_font ne sont PAS
  réutilisés (autre modèle de points : couplage artificiel).
- Couleurs : « #rrggbb » ou « #aarrggbb », vide = aucun. Épaisseur en unités du board (1 pt = 4/3), affichée en pt.

## Illustrator : ce qui est repris, et à quel degré

- VÉRIFIÉ (source secondaire, aide-mémoire Windows Illustrator 2026 ; la page d'Adobe
  helpx.adobe.com/illustrator/using/default-keyboard-shortcuts.html a répondu 403) : V Sélection, A Sélection
  directe, P Plume, Y = Baguette magique (d'où : Polygone / Étoile SANS lettre ici).
- CONNAISSANCE GÉNÉRALE, NON VÉRIFIÉE cette session : + / - points, Maj+C conversion, M rectangle, L ellipse,
  \ segment, N crayon, Maj+O plan de travail, H, Z, I ; Ctrl+G / Ctrl+Maj+G, Ctrl+2 / Ctrl+Alt+2, Ctrl+3 /
  Ctrl+Alt+3, Ctrl+J, Ctrl+8 / Ctrl+Alt+Maj+8, Ctrl+Y, Ctrl+] / [ (+ Maj), X / Maj+X / D / « / » ; plume (clic =
  angle, glisser = lisse, Alt = casser, clic sur le 1er point = fermer, Ctrl + clic = terminer) ; Sélection directe
  (Suppr ouvre le tracé). Clavier AZERTY : Ctrl+é / Ctrl+" / Ctrl+_ acceptés pour 2 / 3 / 8.
- DÉDUIT / CHOIX DU MODULE : marges de tolérance, zone de rotation hors des coins, bulle de taille, rendu des points.
- Différence assumée : pendant une mise à l'échelle, le contour paraît mis à l'échelle (matrice posée sur l'élément) ;
  au relâché il garde son épaisseur (défaut d'Illustrator « mettre à l'échelle contours et effets » coupé).

## Mesures (offscreen, `tools/bench_illustrator.py 2000`, 2400 × 1300 ; médiane, p95)

| Geste | Avant correction | Après |
|---|---|---|
| Survol (mouvement + peinture de la zone changée) | 18 ms (image entière) | 0,6 ms (2,3) |
| Cadre de sélection | 18 ms | 1,6 ms (2,7) |
| Ctrl + glisser 200 objets | 289 ms : `scene.item_moved` parcourt TOUT le board pour CHAQUE objet déplacé | 18-20 ms (34) : `IllItem.quiet_moves` + `notify_moved` une fois à la fin |
| Mise à l'échelle de 200 objets | 62 ms : nœuds recalculés à chaque image | 30 ms (40) : `QTransform` posé, nœuds au relâché, cache de l'élément coupé pendant le geste |
| Tout choisir (2 000) | 41 s : un `selectionChanged` par objet (quadratique) | 0,25 s : `controller.select` en un seul signal |
| Ligne élastique de la plume | 24 ms : zone de la sélection repeinte à chaque mouvement | 7 ms : seules les zones qui changent (`overlay._state_key`) |
| Enregistrement automatique (2 000 tracés) | ~1,2 s sur le fil de l'interface | ~0,17 s : `IllItem.to_dict` en `clone_data` (86 -> 17 ms), JSON compact au-delà de 2 000 éléments (179 -> 67 ms) |
| Image entière | 20 ms | 16 ms |
Clic de plume ~21 ms (p95 ~80 : premier clic, création de l'élément).

## État fonctionnel

| Fonction | État | Test |
|---|---|---|
| Bouton du module, exclusivité, griser / masquer | Terminé | `ShellTest` |
| Plans de travail (outil, formats, aller à, renommer, Ctrl + glisser, poignées) | Partiel (pas de panneau Plans de travail, pas d'options d'export par plan) | `test_artboard_tool…` |
| Rectangle, ellipse, polygone, étoile, segment (Maj, Alt, flèches) | Terminé (pas de formes « dynamiques », pas de dialogue de taille au clic) | `ToolsTest` |
| Sélection, cadre, Ctrl + glisser, copie, poignées d'échelle / rotation, flèches | Terminé (pas de repères commentés / magnétisme) | `ToolsTest` |
| Plume, ajout / suppression / conversion de points, sélection directe, segments tirés | Terminé | `test_pen…`, `test_direct…` |
| Crayon (ajustement Bézier) | Terminé | `test_pencil_fits_bezier` |
| Fond / contour (couleur, aucun, X, Maj+X, D, /), épaisseur, extrémités, angles, tirets, opacité, pipette | Partiel (pas de nuancier ni de panneau Contour complet) | `test_keyboard…` |
| Grouper, disposition, verrouiller, masquer, joindre, tracé transparent, symétries, rotation 90° | Terminé | `CommandsTest` |
| Mode Tracés (Ctrl+Y) | Terminé (affichage) | — |
| Enregistrement / réouverture (`.mro`) | Terminé | `test_save_and_reopen` |
| Export SVG (plan, tous, dessin, sélection), import SVG (fichier, glisser-déposer) | Terminé pour les tracés (pas de dégradés, texte, images, masques) | `SvgTest`, `test_export_and_import…` |
| Dégradés, nuancier, calques, Pathfinder, Shape Builder, texte, pinceaux / largeur, masques, Aspect / effets, images, vectorisation, PDF, outils avancés, réglages du module | Non commencé | — |

## PASSATION (2026-10-31)

- Commit de la tranche 1-5 (intégration, document, plans de travail, formes, sélection, transformations, plume,
  sauvegarde, export / import SVG) : voir `git log -- fm_illustrator`.
- Référence de la suite complète AVANT le module (`tests/run.py --tout`, venv) : 13 fichiers en échec, tous
  préexistants : test_file_attributes, test_focus_viewer, test_input_tabs_settings, test_interface_edit_scope,
  test_md_live_preview, test_render_log, test_row_templates, test_settings_preload, test_shadows,
  test_software_launch, test_table_split, test_viewer_buttons, test_viewer_filter.
- Les tests du board affichent des « TypeError: Unknown return type » à la destruction des panneaux (signaux
  `canUndoChanged` du board) : déjà présents dans `test_design`, sans effet sur les résultats.
- Prochaine tranche conseillée (ordre de la mission) : 6 couleurs / dégradés + nuancier (fond = dict
  `{"type": "linear", stops…}` à côté de la couleur unie, rendu `QLinearGradient`, export `<linearGradient>`),
  7 calques (`ill_layer` = élément du `.mro`, `layer` sur chaque objet, panneau avec les briques des réglages),
  8 Pathfinder (skia-pathops, déjà dans `requirements.txt` : convertir les sous-tracés en `pathops.Path`).
- Pistes de fluidité restantes : enregistrement JSON hors du fil de l'interface (coque, tous modules) ; clic de
  plume (création d'élément).

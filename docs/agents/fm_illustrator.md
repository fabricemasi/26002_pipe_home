# Module Illustrator du board (`fm_illustrator/`, à la manière d'Adobe Illustrator)

Cinquième module du board (après Miro, CAD, Design, Tableur), commencé le 2026-10-31 (mission de l'utilisateur :
« éditeur d'illustration vectorielle professionnel aussi proche que possible d'Adobe Illustrator, intégré au
Board »). Activé par le bouton « Illustrator » du sélecteur de modules (`BoardPane.set_module("illustrator")`).
Tout est LOCAL ; aucun code, icône ni ressource d'Adobe. **Aucune compatibilité `.ai` n'est annoncée** (non faite).

**Tests** : `python tests/run.py fm_illustrator` (`tests/test_illustrator*.py`, ~5 s) ; `fm_board` les inclut.
**Mesures** : `python tools/bench_illustrator.py [N]` (offscreen, 2400 × 1300, N tracés ; défaut 2 000).

## Carte : fonctionnalité -> fichiers (à ouvrir directement)

Couches : chaque fichier n'importe que ceux qui le précèdent. `model`, `bezier`, `paint`, `pathfinder`, `svg`
n'importent PAS Qt.

| Fonctionnalité | Fichier | Points d'entrée |
|---|---|---|
| Types du `.mro` (`ill_artboard`, `ill_path`), défauts, formats de plans, normalisation, style | `model.py` | `DEFAULTS`, `normalize_entity`, `new_entity`, `style_of`, `ARTBOARD_FORMATS`, `PT`, `MM` |
| Bézier : nœuds, segments, cadres exacts, point le plus proche, insertion / suppression / conversion, joindre, inverser, matrices affines, formes, `d` SVG | `bezier.py` | `node`, `segments`, `bounds`, `nearest`, `insert_node`, `set_handle`, `smooth_node`, `join`, `transform`, `rotate`, `scale`, `rect`, `ellipse`, `polygon`, `star`, `from_cubics`, `svg_d` |
| Dégradés (modèle en fractions de la boîte, outil Dégradé, SVG), nuancier par défaut | `paint.py` | `valid_gradient`, `new_gradient`, `absolute`, `set_from_drag`, `svg_gradient`, `SWATCHES` |
| Pathfinder (skia-pathops) : modes de forme, division, découpe, fusion, recadrage, soustraction arrière, vectoriser le contour | `pathfinder.py` | `combine`, `divide`, `trim`, `merge`, `crop`, `outline_stroke`, `to_path`, `from_path` |
| Shape Builder (Maj+M) : zones de la sélection, survol hachuré, glisser = réunir, Alt = supprimer | `shape_builder.py` | `ShapeBuilderTool` (`apply`, `region_at`) |
| Texte (Qt) : mise en page point / captif / curviligne (police de base 100 px), chemin des lettres, créer les contours, SVG `<text>` / `<textPath>`, éditeur sur place | `text.py` | `layout`, `base_font`, `outline_subpaths`, `svg_text`, `TextEditor` |
| Calques : accès, bandes de hauteur, panneau | `layers.py` | `layers`, `layer_of`, `top_z`, `members`, `LayersPanel` |
| Export / import SVG (dégradés compris) | `svg.py` | `export_svg`, `path_element`, `import_svg`, `parse_d`, `arc_to_cubics`, `parse_transform`, `parse_color` |
| Éléments de la scène (plan de travail, calque, tracé, texte), chemin et pinceaux Qt gardés, zone cliquable, MASQUES (écrêtage, opacité : `mask_item`, `_paint_through_opacity_mask`, registre `scene.ill_masks`) | `items.py` | `IllArtboardItem`, `IllLayerItem`, `IllPathItem` (`sync`, `apply_visibility`, `hit_path`, `contains_scene_point`, `geometry_rect`), `notify_moved`, `qpath`, `gradient_brush` |
| Activation, événements, sélection, commandes (style, grouper, disposition dans le calque, verrou, masquer, joindre, tracé transparent, pipette, plans, calques, Pathfinder, vectoriser le contour, export / import) | `controller.py` | `IllustratorController` |
| Gestes partagés (déplacer, transformer, cadre de sélection), Sélection, Sélection directe | `tools.py` | `MoveGesture`, `TransformGesture`, `marquee_select`, `SelectTool`, `DirectTool`, `TOOL_KEYS` |
| Plume, points (ajout / suppression / conversion), formes, crayon, plan de travail, main, zoom, pipette, dégradé (G), texte (T) | `tools_draw.py` | `PenTool`, `ShapeTool`…, `PencilTool`, `ArtboardTool`, `make_tools` |
| Dessin temporaire (sélection, poignées, cadre, ligne élastique, noms des plans, bulle) | `overlay.py` | `IllOverlay` |
| Barre d'outils (gauche), témoin fond / contour, barre de contrôle (haut), menus couleur (nuancier, dégradé) / épaisseur / Pathfinder / plans / export, panneau Calques | `ui.py` | `IllustratorChrome`, `FillStroke` |
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
- **Dégradés** (`fill_gradient` / `stroke_gradient`, None = couleur unie) : points en FRACTIONS de la boîte de la
  géométrie (suivent déplacement et mise à l'échelle ; une rotation ne tourne pas le dégradé : limite connue). Une
  couleur unie choisie retire le dégradé ; un dégradé garde sa 1re couleur dans `fill` (lecteurs plus anciens).
- **Calques** = éléments `ill_layer` (annulation fine) ; `layer` sur chaque objet (vide = le plus bas). Ordre de
  dessin par BANDES de hauteur (`layers.BAND` × (index + 1)) : objet neuf en haut de son calque, disposition
  (Ctrl+] …) dans le calque, ordre des calques changé = objets re-rangés (une étape). Le 1er objet d'un dessin crée
  « Calque 1 » dans la MÊME étape d'annulation (`_pending_layer`). Supprimer un calque supprime ses objets.
  Masqué / verrouillé = affichage et clic seulement (valeurs des objets inchangées).
- **Texte** (`ill_text`, 2026-10-31) : point (origine = ligne de base du 1er trait, comme Illustrator et SVG :
  l'import / export SVG se passe de Qt pour la position), captif (cadre `w` × `h`, retour à la ligne aux espaces,
  justifié, « + » rouge si le texte dépasse), curviligne (clic de l'outil Texte sur un tracé OUVERT : le tracé
  devient le tracé de base, dans la MÊME étape que le texte ; un tracé fermé n'est pas transformé en zone de texte :
  non fait). Rendu = chemin des lettres (police de base 100 px mise à l'échelle : indépendant du DPI), donc fond,
  contour et dégradés comme un tracé. Édition sur place = `QGraphicsTextItem` ENFANT de l'élément (la vue le
  reconnaît par `editing()` / `owner`, comme les textes de Miro) ; les clics dans l'éditeur lui sont confiés
  (`controller._forward`), un clic ailleurs ou Échap termine (une étape ; texte neuf vide = rien). Pendant l'édition,
  le texte curviligne est montré droit (comme le texte courbé de Design). Mise à l'échelle : point = corps × l'échelle,
  captif = cadre redimensionné (corps inchangé), curviligne = tracé de base transformé ; rotation gardée dans
  `rotation` (point, captif). Les opérations de géométrie (Pathfinder, joindre, tracé transparent, Shape Builder,
  vectoriser le contour) ignorent les textes : Ctrl+Maj+O (Créer les contours) d'abord, comme Illustrator. Un seul
  style par texte (pas de styles de caractères par partie). Tests : `QT_QPA_FONTDIR` = `C:\Windows\Fonts`
  (l'offscreen n'a sinon aucune police : des carrés).
- **Masques** (tranche 12) : un masque = l'objet le plus HAUT d'un groupe, `mask` = « clip » ou « opacity » ; les
  autres objets du groupe sont masqués. Créer (Ctrl+7, ou menu Objet ; AZERTY : Ctrl+è) = la sélection devient UN
  groupe, son objet le plus haut le masque, en une étape ; écrêtage : le masque perd sa peinture (comme Illustrator).
  Annuler le masque (Ctrl+Alt+7) : objets dégroupés, le masque reste (sans peinture). Écrêtage = `setClipPath` à la
  peinture ; opacité = luminance du masque (avec ses couleurs) en alpha, hors du masque = caché (option « Écrêter »
  d'Illustrator active par défaut), « Inverser le masque » ; masque d'un texte : ses lettres. Seule la partie visible
  d'un objet écrêté se clique ; la boîte de sélection est réduite au masque. Rendu GARDÉ en image (cache de l'élément)
  : écrêtage et composition refaits au zoom, quand le masque change (`_refresh_members` jette l'image des membres :
  `update()` ne suffit pas pour un rendu hors vue), quand un objet entre / sort d'un groupe masqué (`_mask_key`), et
  pendant un déplacement d'un membre SANS son masque (ou l'inverse : `MoveGesture.loose`, peints sans image le temps
  du geste). Limites : un masque par groupe, pas de groupes imbriqués, options du panneau Transparence (« Écrêter »
  décochable, mode de fusion) non faites. SVG : `<clipPath>` / `<mask>` dans `<defs>`, `<g clip-path=…>` /
  `<g mask=…>` ; import des `clip-path` / `mask` qui visent un élément du document (formes réunies en un masque).
- **Pathfinder** : style du plus haut (Soustraction : du plus bas) ; Division / Découpe / Fusion / Recadrage :
  morceaux groupés, chacun au style de son objet ; Découpe, Fusion, Recadrage retirent les contours (connaissance
  générale d'Illustrator, non vérifiée cette session ; Division garde les contours). Mode « Contour » du panneau :
  non fait. Réunion / Exclusion : une seule simplification de tous les contours (règle winding / pair-impair).

## Illustrator : ce qui est repris, et à quel degré

- VÉRIFIÉ (source secondaire, aide-mémoire Windows Illustrator 2026 ; la page d'Adobe
  helpx.adobe.com/illustrator/using/default-keyboard-shortcuts.html a répondu 403) : V Sélection, A Sélection
  directe, P Plume, Y = Baguette magique (d'où : Polygone / Étoile SANS lettre ici).
- CONNAISSANCE GÉNÉRALE, NON VÉRIFIÉE cette session : + / - points, Maj+C conversion, M rectangle, L ellipse,
  \ segment, N crayon, Maj+O plan de travail, H, Z, I, G dégradé, T texte, Maj+M Shape Builder,
  Ctrl+Maj+O créer les contours ; Ctrl+G / Ctrl+Maj+G, Ctrl+2 / Ctrl+Alt+2, Ctrl+3 /
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
| Pathfinder Réunion de 200 ellipses | 99 ms (réunions deux à deux) | 18 ms (une passe) |
| Pathfinder Exclusion de 200 ellipses | 4,1 s (XOR deux à deux) | 69 ms (une passe pair-impair) |
| Division de 20 objets (98 zones) / Découpe | 44 ms / 5 ms | — |
| 200 objets écrêtés par un cercle : image entière / Ctrl + glisser le groupe | 34 ms / 49 ms (écrêtage refait à chaque image : membres sans image gardée) | 4,6 ms / 20 ms (images gardées) |
| Masque d'opacité 600 × 400 : recomposition / pan | 27 ms / 21 ms | 10 ms / 5 ms |
| Mise en page d'un texte (à la validation, à l'annulation, pas pendant la frappe) : point 11 lettres / curviligne 200 lettres / captif 300 mots | — / — / 40 ms (un `addText` par mot) | 0,3 ms / 17 ms / 19 ms (36 ms justifié) |
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
| Fond / contour (couleur, aucun, X, Maj+X, D, /), épaisseur, extrémités, angles, tirets, opacité, pipette | Partiel (pas de panneau Contour complet : profils, alignement du contour) | `test_keyboard…` |
| Nuancier (couleurs de base + du document) | Partiel (pas de nuances globales ni de bibliothèques) | `test_gradient_tool…` |
| Dégradés linéaire / radial (menu, couleurs de départ / fin, inverser, outil G, SVG aller-retour) | Partiel (2 couleurs éditables ; pas d'éditeur d'arrêts multiples, pas de dégradé de forme libre) | `PaintModelTest`, `GradientAndPathfinderTest` |
| Calques (panneau, nouveau, masquer, verrouiller, ordre Ctrl + glisser, renommer, déplacer la sélection, supprimer) | Partiel (pas de sous-calques ni de liste des objets) | `LayersTest` |
| Pathfinder (4 modes de forme, Division, Découpe, Fusion, Recadrage, Soustraction arrière) + Vectoriser le contour | Terminé (sauf mode Contour) | `PathfinderModelTest`, `GradientAndPathfinderTest` |
| Grouper, disposition, verrouiller, masquer, joindre, tracé transparent, symétries, rotation 90° | Terminé | `CommandsTest` |
| Mode Tracés (Ctrl+Y) | Terminé (affichage) | — |
| Enregistrement / réouverture (`.mro`) | Terminé | `test_save_and_reopen` |
| Export SVG (plan, tous, dessin, sélection), import SVG (fichier, glisser-déposer) | Terminé pour les tracés (pas de dégradés, texte, images, masques) | `SvgTest`, `test_export_and_import…` |
| Shape Builder (zones, réunir, supprimer, survol) | Terminé (pas de mode « boucle fermée » ni d'option de couleur du nuancier) | `ShapeBuilderTest` |
| Texte : point, captif (retour à la ligne, justifié, débordement), curviligne, édition sur place, police / corps / gras / italique / alignement / interligne / approche / départ sur le tracé, créer les contours, SVG aller-retour | Partiel (un style par texte ; pas de zone de texte dans une forme quelconque, de chaînage de cadres, de styles de paragraphe, de glyphes OpenType) | `test_illustrator_text.py` |
| Masques d'écrêtage et d'opacité (créer, annuler, inverser, rendu vérifié au pixel, SVG aller-retour) | Partiel (un masque par groupe, pas de groupes imbriqués, options Transparence non faites) | `test_illustrator_masks.py` |
| Pinceaux / largeur variable, Aspect / effets, images placées, vectorisation, export PDF, outils avancés (dégradé de forme, filet, déformation…), réglages du module (Réglages : Board), repères commentés / magnétisme | Non commencé | — |

## PASSATION (2026-10-31)

- Commits (branche `nettoyage-code`, locaux, rien de poussé) : 27c3bf7 tranche 1-5 (intégration, document, plans
  de travail, formes, sélection, transformations, plume, sauvegarde, export / import SVG) ; e344fd5 tranche 6-8
  (dégradés, nuancier, calques, Pathfinder) ; puis tranche 9 (Shape Builder) : `git log -- fm_illustrator`.
- Après chaque tranche, suite complète = référence + `FramePacerTest` de test_cad (instable connu) ; une fois
  `test_md_tables` (Markdown), vert en le relançant seul : instable, sans lien avec le module.
- Référence de la suite complète AVANT le module (`tests/run.py --tout`, venv) : 13 fichiers en échec, tous
  préexistants : test_file_attributes, test_focus_viewer, test_input_tabs_settings, test_interface_edit_scope,
  test_md_live_preview, test_render_log, test_row_templates, test_settings_preload, test_shadows,
  test_software_launch, test_table_split, test_viewer_buttons, test_viewer_filter.
- Les tests du board affichent des « TypeError: Unknown return type » à la destruction des panneaux (signaux
  `canUndoChanged` du board) : déjà présents dans `test_design`, sans effet sur les résultats.
- Tranches 6-8 (dégradés, nuancier, calques, Pathfinder) : commit suivant (voir `git log -- fm_illustrator`).
- Tranche 9 (Shape Builder) : commit suivant. Zones calculées une fois par sélection (clé : identifiants + étape
  d'annulation), ~44 ms pour 20 objets / 98 zones, puis survol = `QPainterPath.contains` par zone.
- Tranche 10 (texte) : 68ab7c1. Tranche 12 (masques) : commit suivant.
- POINT DE REPRISE : tranche 11 (pinceaux, largeur variable : profil de largeur le long du tracé, contour
  vectorisé par `pathfinder.outline_stroke` puis déformé), 13 Aspect / effets (ombre portée, flou : rendu dans
  l'image gardée de l'élément, comme le masque d'opacité), 14 images (`asset` du board, `_bring_asset`), 16 PDF
  (`QPdfWriter` + `paint_path`, vectoriel).
- Pistes de fluidité restantes : enregistrement JSON hors du fil de l'interface (coque, tous modules) ; clic de
  plume (création d'élément).

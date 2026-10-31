# Module Illustrator du board (`fm_illustrator/`, à la manière d'Adobe Illustrator)

Cinquième module du board (après Miro, CAD, Design, Tableur), commencé le 2026-10-31 (mission de l'utilisateur :
« éditeur d'illustration vectorielle professionnel aussi proche que possible d'Adobe Illustrator, intégré au
Board »). Activé par le bouton « Illustrator » du sélecteur de modules (`BoardPane.set_module("illustrator")`).
Tout est LOCAL ; aucun code, icône ni ressource d'Adobe. **Aucune compatibilité `.ai` n'est annoncée** (non faite).

**Tests** : `python tests/run.py fm_illustrator` (`tests/test_illustrator*.py`, 12 fichiers, ~20 s) ; `fm_board` les inclut.
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
| Aspect (SANS Qt) : effets d'un objet (un par type, ordre fixe), contours supplémentaires, géométrie des effets vectoriels (décalage, arrondis), marges, filtres SVG | `appearance.py` | `valid_effects`, `valid_strokes`, `render_subpaths`, `margin`, `svg_filter`, `ORDER`, `PARAMS` |
| Effets tramés (Qt) : flou, contour progressif, ombre portée, lueur externe, image composée gardée pendant le zoom | `effects.py` | `paint_with_effects`, `soften`, `tinted` |
| Menu Effets (curseurs en direct, couleur, activer, supprimer, contours supplémentaires, décomposer l'aspect) | `appearance_ui.py` | `effects_menu` |
| Vectorisation d'une image (SANS Qt, numpy) : quantification (noir et blanc, gris, couleurs : k-moyennes), contours orientés des pixels, bruit, angles, courbes (Schneider) | `trace.py` | `trace`, `quantize`, `loops`, `smooth_loop`, `PRESETS`, `settings_for` |
| Export PDF : une page par plan de travail à sa taille exacte, objets peints un à un (vectoriel), images en pleine résolution | `pdf.py` | `export_pdf`, `DPI` ; `controller.export_pdf` |
| Texte (Qt) : mise en page point / captif / curviligne (police de base 100 px), chemin des lettres, créer les contours, SVG `<text>` / `<textPath>`, éditeur sur place | `text.py` | `layout`, `base_font`, `outline_subpaths`, `svg_text`, `TextEditor` |
| Calques : accès, bandes de hauteur, panneau | `layers.py` | `layers`, `layer_of`, `top_z`, `members`, `LayersPanel` |
| Export / import SVG (dégradés compris) | `svg.py` | `export_svg`, `path_element`, `import_svg`, `parse_d`, `arc_to_cubics`, `parse_transform`, `parse_color` |
| Éléments de la scène (plan de travail, calque, tracé, texte, IMAGE placée `IllImageItem`), chemin et pinceaux Qt gardés, zone cliquable, MASQUES (écrêtage, opacité : `mask_item`, `_paint_through_opacity_mask`, registre `scene.ill_masks`) | `items.py` | `IllArtboardItem`, `IllLayerItem`, `IllPathItem` (`sync`, `apply_visibility`, `hit_path`, `contains_scene_point`, `geometry_rect`), `notify_moved`, `qpath`, `gradient_brush` |
| CŒUR du contrôleur : activation, zoom, événements, sélection, création / modification annulable, outils, clavier, dépôt de fichiers | `controller.py` | `IllustratorController` (= `ContentMixin` + `CommandMixin`) |
| Commandes sur la sélection : effets, masques, style (copier / coller, pipette, X / D), supprimer, flèches, transformer (de nouveau, Déplacer…), aligner / répartir, symétries, grouper, disposition, Pathfinder, vectoriser le contour, verrou, masquer, joindre, tracé transparent, profils et pinceaux | `ctl_commands.py` | `CommandMixin`, `_split_without` |
| Contenu : images (placer, vectoriser, recadrer), textes (créer, éditer, attributs, contours), calques, plans de travail, export SVG / PDF, import SVG | `ctl_content.py` | `ContentMixin`, `IMAGE_SUFFIXES` |
| Images de la vue pendant un zoom continu et un Ctrl + glisser de nombreux objets (objets non repeints, `IllItem.snapshot_ids`) | `snapshot.py` | `take`, `drop`, `drag_start`, `drag_end`, `SNAPSHOT_MIN`, `DRAG_MIN_MOVING`, `DRAG_MIN_VISIBLE` |
| Gestes partagés (déplacer, transformer, cadre de sélection), Sélection, Sélection directe | `tools.py` | `MoveGesture`, `TransformGesture`, `marquee_select`, `SelectTool`, `DirectTool`, `TOOL_KEYS` |
| Pinceaux et largeur variable (SANS Qt, numpy) : profils de largeur, pointe calligraphique, contour-surface, point le plus proche | `brushes.py` | `outline`, `outline_polygons`, `PROFILES`, `CALLIGRAPHIC`, `nib_width`, `locate`, `valid_profile`, `valid_brush` |
| Pinceau (B), Forme de tache (Maj+B), Largeur (Maj+W) | `tools_draw.py` | `PaintbrushTool`, `BlobTool`, `WidthTool` |
| Outils à origine (Rotation R, Mise à l'échelle S, Symétrie O ; Alt + clic = valeur), repères commentés (`Snapper`), aligner / répartir | `tools_xform.py` | `RotateTool`, `ScaleTool`, `ReflectTool`, `Snapper`, `align`, `distribute`, `reflect_matrix` |
| Plume, points (ajout / suppression / conversion), formes, crayon, plan de travail, main, zoom, pipette, dégradé (G), texte (T) | `tools_draw.py` | `PenTool`, `ShapeTool`…, `PencilTool`, `ArtboardTool`, `make_tools` |
| Dessin temporaire (sélection, poignées, cadre, ligne élastique, noms des plans, bulle) | `overlay.py` | `IllOverlay` |
| Barre d'outils (gauche), témoin fond / contour, barre de contrôle (haut), menus couleur (nuancier, dégradé) / épaisseur / Pathfinder / plans / export, panneau Calques | `ui.py` | `IllustratorChrome`, `FillStroke` |
| Menu Objet / clic droit | `menus.py` | `fill_object_menu`, `open_context_menu` |
| Glyphes des boutons | `glyphs.py` | `paint_ill_glyph` (appelé par `fm_board.ui.paint_glyph`) |
| Réglages (onglet « Illustrator » de « Réglages : Board », clés `board_ill_*`) : lignes et arbre ; défauts | `settings.py` ; `settings_defaults.py` | `ILL_TAB`, `ILL_TREE` ; `ILL_DEFAULTS` |
| Réglages APPLIQUÉS (sans Qt) : `LOOK`, recopie dans les modules chargés, unité affichée, format des plans | `look.py` | `apply_settings`, `push`, `value`, `to_display`, `artboard_size` |

Points de branchement dans la coque (MINIMAUX, Miro / CAD / Design inchangés) :
- `fm_board/model.py` : `DEFAULTS` reçoit les types, `normalize_item` appelle `ill_model.normalize_entity`, `ICON_ROWS`
  (`illustrator` + une ligne `ill_<genre>` par bouton du module : icône réglable dans Module MRO > Icônes, glyphe
  peint sans icône choisie ; `test_every_button_icon_is_settable` vérifie qu'aucun bouton n'en manque).
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
- **Réglages** (tranche 18) : onglet « Illustrator » de la fenêtre « Réglages : Board » (bouton engrenage du cadre
  Board), comme Design / Tableur : Sélection et repères (couleur de sélection, tailles des poignées et des points,
  couleur et distance des repères commentés, repères actifs à l'ouverture), Nouveaux objets (format du plan de
  travail, police et corps des textes, unité affichée pt / mm / px), Clavier et outils (flèches, Maj + flèches,
  fidélité du crayon / pinceau, détail de la vectorisation), Export (DPI des parties tramées du PDF). Appliqués EN
  DIRECT : `BoardPane.apply_settings` -> `look.apply_settings` (4 µs quand rien ne change : chemin rapide) ->
  `look.push` recopie dans les modules CHARGÉS (`tools.HANDLE_PX`, `overlay.ANCHOR_SIDE`, `tools_xform.SNAP_PX`,
  `controller.NUDGE`…, lus à chaque usage ; jamais `from … import CONSTANTE`, qui figerait la valeur) ->
  `controller.apply_settings` repeint. Valeur invalide = défaut. Fichiers PARTAGÉS touchés (lignes du module
  seulement) : `settings_store.py` (`DEFAULT_SETTINGS.update(ILL_DEFAULTS)`), `settings_window_v2.py` (import,
  `STANDALONE_TABS`, `MODULE_SCOPES["board"]`, `TAB_LABELS`, menu « Restaurer »), `tests/test_settings_window_v2.py`
  (listes d'onglets du Board).
- **Pinceaux et largeur variable** (tranche 11) : `width_profile` ([[t, facteur]] le long du tracé) et `brush`
  (pointe calligraphique : angle, rondeur, taille ; la largeur dépend de la direction) d'un tracé. Le contour est
  alors une SURFACE calculée (`brushes.outline`, numpy : points échantillonnés, normales, largeurs, extrémités
  rondes ou plates, anneau pour un tracé fermé, points presque alignés retirés) : rendu, zone cliquable, SVG (surface
  à la couleur du contour, au-dessus du fond), PDF, Vectoriser le contour (surface nettoyée par une réunion pathops).
  Calculée À LA DEMANDE (1er affichage ou clic) et gardée jusqu'au `sync` suivant : à la création / ouverture, un
  trait au pinceau ne coûte pas plus qu'un autre. Outils : Pinceau (B : crayon + pointe courante, contour à la
  couleur du contour), Forme de tache (Maj+B : surface ronde à la couleur du contour, réunie aux surfaces de même
  couleur sans contour qu'elle touche dans le calque, une étape), Largeur (Maj+W : glisser depuis un point du
  contour = sa largeur, profil symétrique ; Alt + clic = retirer le point). Bouton « Pinceau » de la barre de
  contrôle : profils prédéfinis (Uniforme, Fuseau, Effilés, Renflé), pointe calligraphique en direct (sélection et
  Pinceau), taille de la Forme de tache, Vectoriser le contour. Limites : pas de pinceaux Diffusion / Motif / Art /
  Soies, ni de largeur asymétrique, ni de pression du stylet, ni de bibliothèque de pinceaux.
- **Outils avancés** (tranche 17) : Rotation (R), Mise à l'échelle (S), Symétrie (O) : origine = centre de la
  sélection, un clic la déplace (repère bleu de l'overlay), glisser transforme autour d'elle (Maj : 45° / uniforme /
  axe à 45°), Alt + clic = valeur saisie autour du point cliqué ; pas de Ctrl (géométrie). Transformer de nouveau
  (Ctrl+D, PRIS au Dupliquer du board en mode Illustrator) : la dernière transformation (déplacement, poignées,
  outils, commandes, saisies) refaite ; après Ctrl + Alt + glisser (copie), Ctrl+D fait une NOUVELLE copie au même
  écart (pas et répétition d'Illustrator). Objet > Transformer : Déplacer… (« dx, dy »), Rotation…, Mise à
  l'échelle…, Symétrie…. Aligner / Répartir (bouton de la barre de contrôle, menu Objet) : sur la boîte de la
  sélection, un objet ou un groupe seul : sur son plan de travail ; un groupe compte pour un ; répartir les centres
  ou l'espacement (3 unités au moins). Repères commentés (Ctrl+U, actifs par défaut, magenta) : pendant Ctrl +
  glisser et le glisser d'UN point en Sélection directe, bords et centres aimantés à ceux des objets VISIBLES et des
  plans de travail à 6 px d'écran ; relevé une fois au début du geste par l'index de la scène, en nombres simples,
  recherche par dichotomie ; ligne vers l'objet aligné le PLUS PROCHE (courte). Limites : pas de copie Alt pendant
  les outils à origine (Ctrl+D la remplace), pas de repères d'angle / de points d'ancrage, pas d'outil Transformation
  manuelle (E), pas de répartition par écart imposé.
- **Export PDF** (tranche 16) : menu Exporter : le plan courant, tous les plans (UNE page par plan, chacune à sa
  taille : 1 unité = 1/96 de pouce = 0,75 pt), ou le dessin entier sans plan de travail (cadre + 20 unités).
  `QPdfWriter` ; seuls les objets du module, peints un à un par leur propre peinture (pas de rendu de la scène : ni
  sélection, ni repères, ni Miro / CAD / Design). Restent VECTORIELS : tracés, dégradés, masques d'écrêtage, textes
  (en contours : police non incorporée, texte non sélectionnable dans le PDF). Sont des IMAGES : effets tramés et
  masques d'opacité (à `pdf.DPI` = 300) ; images placées incorporées en PLEINE résolution (`IllImageItem.export_images`
  le temps de l'export, au lieu de l'image réduite à 2 400 px de l'affichage). Mode Tracés ignoré, texte en édition
  terminé. Écriture atomique. Limites : pas de PDF/X, de fond perdu, de traits de coupe, de profils colorimétriques
  (RVB seulement), ni de PDF « modifiable dans Illustrator » (non annoncé).
- **Vectorisation** (tranche 15) : menu Objet > Vectoriser l'image : préréglages aux noms d'Illustrator (Noir et
  blanc, Niveaux de gris, 3 / 6 / 16 couleurs) et curseurs (seuil, couleurs, détail = grand côté de l'image tracée,
  fidélité, bruit, angles), gardés pour la session. Algorithme propre au module (idée générale de potrace, aucun code
  repris) : quantification numpy (k-moyennes, départ « k-means++ » à graine fixe : même image -> même résultat),
  bords des pixels orientés (trous dans l'autre sens, vidés par la règle non nulle ; sommets ambigus : on tourne à
  droite), bruit écarté, milieux des bords + Ramer-Douglas-Peucker, angles gardés au-delà du seuil, courbes de
  Bézier entre les angles (`fm_font.shapes.fit_cubic`). Empilement : couleur la plus fréquente = rectangle de fond
  (pas de jour entre zones voisines ; pas de fond si l'image a de la transparence). Calcul en FIL DE FOND (bulle
  « Vectorisation… n / total »), puis l'image est remplacée par un GROUPE de tracés en une étape (annulable) ; rien
  trouvé = image gardée. Limites : pas de vectorisation « en direct » (objet de vectorisation modifiable puis
  « Décomposer » d'Illustrator), pas de mode « contour » (traits centraux), pas de palette imposée.
- **Images placées** (tranche 14, `ill_image`) : Importer (Ctrl+Maj+P, menu Exporter / importer, ou dépôt de
  fichiers PNG / JPEG / GIF / BMP / WebP / TIFF ; un SVG déposé ou importé devient des objets) : l'image est COPIÉE
  dans le dossier d'images du board (`serialization.import_asset`, comme les images de Miro : incorporée, jamais
  liée ; nettoyage, copier-coller entre boards et annulation la protègent par la clé `asset`, sans rien changer à la
  coque), posée à 100 % (1 pixel = 1 unité) au centre de la vue, une étape. Géométrie = rectangle (0, 0, w, h) et
  `matrix` (échelle, rotation, symétrie, inclinaison appliquées par `bake`). Rendu = image décodée une fois et
  partagée (`fm_miro.items.asset_pixmap`, plafonnée à 2 400 px), lissée, dans l'image gardée de l'élément. Effets
  tramés, masques (l'image peut être masquée ou servir de masque d'opacité), opacité : comme un tracé ; pas de fond /
  contour ni d'effets vectoriels ; ignorée par Pathfinder et les opérations de tracés. « Recadrer l'image (masque) »
  : un rectangle à sa taille devient son masque d'écrêtage (à modifier en Sélection directe). SVG : `<image>`
  incorporée en URI data: avec sa matrice ; à l'import, `<image>` (URI data: ou fichier relatif au SVG) copiée dans le
  board. Image absente : cadre gris barré. Limites : pas d'images liées (mise à jour à la source), pas de
  ré-échantillonnage ni de profil colorimétrique, pas d'outil Recadrer dédié.
- **Aspect et effets** (tranche 13) : non destructifs, dans l'objet (`effects`, `extra_strokes`) ; un effet par
  type, ordre fixe (géométrie puis trame). Vectoriels (décalage du tracé par skia-pathops, arrondis des angles entre
  segments droits) : le chemin DESSINÉ change (`draw_path`, zone cliquable comprise), la géométrie de l'objet et sa
  boîte de sélection non (comme Illustrator sans « limites d'aperçu »). Tramés (flou, contour progressif, ombre
  portée, lueur externe) : peints dans l'image gardée de l'élément ; flou = réductions / agrandissements lissés
  (approximation rapide du flou gaussien). Contours supplémentaires : sous le contour principal. Menu « fx » de la
  barre de contrôle : curseurs EN DIRECT (une étape par geste, terminée à la fermeture du menu). Décomposer l'aspect
  (menu Objet) : effets vectoriels appliqués aux nœuds, contours supplémentaires devenus des surfaces groupées sous
  l'objet ; les effets tramés RESTENT des effets (pas de pixellisation). Pas sur le texte : les effets vectoriels
  (Créer les contours d'abord) ; les tramés oui. SVG : `<filter>` (feGaussianBlur, feOffset, feFlood, feComposite,
  feMerge), contours supplémentaires = `<path>` sous l'objet, effets vectoriels exportés appliqués. Limites : un
  effet de chaque type, pas de styles graphiques, pas d'ombre / lueur internes, pas de modes de fusion.
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
| 200 objets avec ombre + lueur : pan / zoom continu / image refaite (zoom fixé, fin du zoom) | — / 174 ms / 174 ms | 10,5 ms / 35 ms (dernière image composée reposée à l'échelle) / 174 ms (une fois, à l'arrêt du zoom : reste à étaler) |
| Curseur d'effet en direct (1 objet) | — | ~15-30 ms par mouvement |
| 20 photos 3 000 × 2 000 (zoom 30 %) : pan / zoom continu / importer les 20 | — | 4,9 ms / 9 ms / 285 ms (copie + empreinte, une fois) |
| Vectoriser une illustration 1 200 × 900 (détail 500) : 6 / 16 couleurs ; interface pendant le calcul en fond | — | 0,12 s / 0,26 s ; boucle d'événements : médiane 5 ms, p95 16 ms, pire ~50 ms |
| Contour d'un trait au pinceau (20 courbes) | 104 ms (long tracé), puis 1,2 ms (Ramer-Douglas-Peucker quasi quadratique, boucles Python) | 0,5 ms (numpy, tri des points alignés vectorisé) |
| 500 traits au pinceau : création / 1re image (~260 visibles) / image suivante | 2 s (contour refait à chaque `sync`, deux fois à la création) | 253 ms (comme sans pinceau) / 427 ms (99 sans pinceau) / 8 ms |
| Ctrl + glisser 200 objets parmi 2 000 avec repères commentés (sans enregistrement automatique pendant la mesure) | 1er mouvement 67 ms, régime ~16 ms (relevé : milliers de `QRectF`, lignes vers des objets lointains) | 1er mouvement ~37 ms (sans repères ~25), régime médiane 15-16 ms / p95 24-27 ms, comme sans repères |
| Export PDF d'un plan avec 2 000 tracés / + 100 ombres tramées | — | 0,09 s (88 Ko) / 0,33 s (729 Ko) |
| Mise en page d'un texte (à la validation, à l'annulation, pas pendant la frappe) : point 11 lettres / curviligne 200 lettres / captif 300 mots | — / — / 40 ms (un `addText` par mot) | 0,3 ms / 17 ms / 19 ms (36 ms justifié) |
Clic de plume ~21 ms (p95 ~80 : premier clic, création de l'élément).

### Vraie fenêtre Windows (tranche 19 ; 1 600 × 1 000, 2 000 tracés dont 1/7 en dégradé, zoom 80 %, ~1 300 visibles)

Sonde temporaire (`QT_QPA_PLATFORM=windows`, événements envoyés au viewport + `repaint`, enregistrement automatique
coupé) ; l'offscreen sous-estimait le coût du zoom (sans image gardée pendant le geste) et du Ctrl + glisser.

| Geste | Avant | Après |
|---|---|---|
| Zoom continu (cran) | 104 ms : tous les tracés visibles repeints à chaque cran | 34 ms : image affichée relevée au 1er cran et reposée à l'échelle, objets qu'elle contient non peints, rendu net 300 ms après (`snapshot.take`) |
| Ctrl + glisser 200 objets : 1er mouvement / médiane / p95 / relâché | 86 / 48 / — / — ms | 62 / 16,9 / 33,6 / 71 ms : fond (vue sans les objets déplacés) + calque (objets déplacés) relevés une fois, calque décalé ; objets à opacité nulle pendant le geste (les MASQUER jetait leurs images gardées : 138 ms au relâché), repositionnés au relâché seulement |
| Ctrl + glisser 30 objets parmi ~1 300 visibles | — | 51 / 16,7 / 31,3 / 50 ms (même chemin dès 300 objets visibles) |

## État fonctionnel

| Fonction | État | Test |
|---|---|---|
| Bouton du module, exclusivité, griser / masquer | Terminé | `ShellTest` |
| Plans de travail (outil, formats, aller à, renommer, Ctrl + glisser, poignées) | Partiel (pas de panneau Plans de travail, pas d'options d'export par plan) | `test_artboard_tool…` |
| Rectangle, ellipse, polygone, étoile, segment (Maj, Alt, flèches) | Terminé (pas de formes « dynamiques », pas de dialogue de taille au clic) | `ToolsTest` |
| Sélection, cadre, Ctrl + glisser, copie, poignées d'échelle / rotation, flèches | Terminé (repères commentés : tranche 17) | `ToolsTest` |
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
| Export SVG (plan, tous, dessin, sélection), import SVG (fichier, glisser-déposer) | Terminé : tracés, dégradés, textes, masques, effets (`<filter>`), images incorporées, contours au pinceau ; import sans CSS `<style>`, `<use>`, motifs | `SvgTest`, tests de chaque tranche |
| Shape Builder (zones, réunir, supprimer, survol) | Terminé (pas de mode « boucle fermée » ni d'option de couleur du nuancier) | `ShapeBuilderTest` |
| Texte : point, captif (retour à la ligne, justifié, débordement), curviligne, édition sur place, police / corps / gras / italique / alignement / interligne / approche / départ sur le tracé, créer les contours, SVG aller-retour | Partiel (un style par texte ; pas de zone de texte dans une forme quelconque, de chaînage de cadres, de styles de paragraphe, de glyphes OpenType) | `test_illustrator_text.py` |
| Masques d'écrêtage et d'opacité (créer, annuler, inverser, rendu vérifié au pixel, SVG aller-retour) | Partiel (un masque par groupe, pas de groupes imbriqués, options Transparence non faites) | `test_illustrator_masks.py` |
| Aspect et effets : décalage, arrondis, flou, contour progressif, ombre portée, lueur externe, contours supplémentaires, décomposer l'aspect, SVG `<filter>` | Partiel (un effet par type, pas de styles graphiques, d'ombre / lueur internes, de modes de fusion) | `test_illustrator_effects.py` |
| Images placées (importer, dépôt, transformations, recadrage par masque, effets, SVG `<image>` aller-retour) | Partiel (incorporées seulement, pas d'images liées ni de ré-échantillonnage) | `test_illustrator_images.py` |
| Vectorisation (préréglages, curseurs, fil de fond, remplacement annulable) | Partiel (pas d'objet de vectorisation modifiable en direct, ni de mode contour, ni de palette imposée) | `test_illustrator_trace.py` |
| Export PDF (plan courant, tous les plans, dessin entier ; vectoriel, images pleine résolution ; relu par QtPdf dans les tests) | Partiel (pas de PDF/X, fond perdu, traits de coupe, CMJN ; texte en contours) | `test_illustrator_pdf.py` |
| Outils avancés : Rotation / Échelle / Symétrie à origine, saisies, Transformer de nouveau (pas et répétition), Aligner / Répartir, repères commentés | Partiel (pas de Transformation manuelle E, de repères d'angle / de points, de copie Alt pendant les outils à origine) | `test_illustrator_xform.py` |
| Pinceaux : profils de largeur, outil Largeur, pointe calligraphique, Pinceau, Forme de tache, Vectoriser le contour, SVG / PDF | Partiel (pas de pinceaux Diffusion / Motif / Art / Soies, largeur asymétrique, pression) | `test_illustrator_brushes.py` |
| Réglages du module (onglet Illustrator de Réglages : Board, en direct) ; icônes des boutons réglables (Module MRO > Icônes) | Terminé | `test_illustrator_settings.py` |
| Fluidité en vraie fenêtre : images du zoom continu et du Ctrl + glisser de nombreux objets | Terminé | `SnapshotTest` (`test_illustrator_xform.py`) |
| Outils restants (dégradé de forme libre, filet de dégradé, Transformation manuelle E, déformation / enveloppe, symboles, motifs, perspective, Largeur asymétrique, pinceaux Diffusion / Motif / Art), compatibilité .ai (non annoncée) | Non commencé | — |

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
- Tranche 10 (texte) : 68ab7c1. Tranche 12 (masques) : 3bf4f4d. Tranche 13 (aspect et effets) : ac3a4f4. Tranche 14
  (images) : d97b2ae (corrige aussi l'import SVG du contrôleur, qui créait tout en tracés). Tranche 15
  (vectorisation) : 7cf18e0. Tranche 16 (export PDF) : 9cd1b20. Tranche 17 (outils avancés) : 889f7dc. Tranche 11
  (pinceaux) : d129836. Tranche 18 (réglages) : 0c7598b. Tranche 19 (finition : contrôleur découpé en
  `controller` / `ctl_commands` / `ctl_content`, icônes réglables, images du zoom et du glisser) : commit suivant.
- POINT DE REPRISE : les 19 tranches prévues sont faites. Suite possible, au choix de l'utilisateur : lignes « Non
  commencé » et « Partiel » de l'état fonctionnel (Transformation manuelle E, dégradé de forme libre, éditeur
  d'arrêts multiples, sous-calques, panneau Contour complet, pinceaux Diffusion / Motif / Art, symboles, motifs),
  puis les pistes de fluidité ci-dessous. Compatibilité .ai : NON faite, ne pas l'annoncer.
- Vérifier dans la vraie fenêtre après tout changement de peinture : l'offscreen ne montre ni le coût du zoom
  continu ni celui des images gardées (voir « Vraie fenêtre Windows » dans Mesures).
- Pistes de fluidité restantes : 1er mouvement d'un Ctrl + glisser nombreux (~50-60 ms : relevé du fond et peinture
  du calque) ; enregistrement JSON hors du fil de l'interface (coque, tous modules) ; clic de
  plume (création d'élément) ; 1re image de nombreux traits au pinceau (~1,2 ms chacun : contour + `QPointF`) ; images d'effets refaites à l'arrêt d'un zoom (~0,9 ms par objet à ombre + lueur :
  à étaler par tranches, ou à faire seulement pour les objets visibles).

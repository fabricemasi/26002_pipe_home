# Module Design du board (`fm_design/`, à la manière de Canva)

Troisième module du board (après Miro et CAD), créé le 2026-10-29 à la demande de l'utilisateur (mission autonome :
« éditeur graphique local inspiré de Canva »). Activé par le bouton « Design » du sélecteur de modules
(`BoardPane.set_module("design")`). Tout est LOCAL (aucun compte, aucun réseau, aucune ressource de Canva).

**Tests du module** : `python tests/run.py fm_design` (`tests/test_design.py`) ; `fm_board` les inclut.
**Sondes de fluidité** (hors dépôt, à recréer si besoin) : voir « Mesures ».

## Carte : fonctionnalité -> fichiers (à ouvrir directement)

| Fonctionnalité | Fichier | Contenu |
|---|---|---|
| Types du `.mro`, défauts, formats de page, palette, normalisation (SANS Qt) | `design_model.py` | `DEFAULTS`, `PAGE_FORMATS`, `normalize_entity`, `layout_positions` |
| Géométrie pure (magnétisme, alignement, répartition, recadrage) | `geometry.py` | testable sans Qt |
| Éléments de la scène : page, forme, image ; peinture (dégradés, ombres, retouches d'image), image de page (zoom, gestes) | `items.py` | `DesignPageItem`, `DesignShapeItem`, `DesignImageItem` |
| Textes : boîte, parties stylées (`spans`), listes, contour, ombre, éditeur sur place | `text_items.py` | `DesignTextItem`, `_DesignText`, `spans_of`, `apply_spans` |
| Tableaux (édition des cellules sur place, Tab) et graphiques (barres, courbe, secteurs, anneau) | `datavis.py` | `DesignTableItem`, `_CellEditor`, `DesignChartItem` |
| Opérations du document (1 étape d'annulation chacune) : pages, éléments, groupes, alignement, ordre, modèles | `document.py` | `add_page`, `duplicate_page`, `delete_page`, `move_page`, `resize_page`, `insert_elements`, `restack`, `apply_template`… |
| Activation, souris, clavier, sélection, poignées (lecture) | `controller.py` | `DesignController` (mélange les deux suivants) |
| Gestes : cadre de sélection, Ctrl + glisser, poignées, rotation, recadrage, magnétisme | `gestures.py` | `GestureMixin` |
| Commandes : ajouter page / forme / texte / image, dépôt, dupliquer, verrou, presse-papiers, style, présenter | `commands.py` | `CommandMixin` |
| Dessin temporaire (titres de page, survol, poignées, guides, cadre de sélection, recadrage, bulle) | `overlay.py` | `DesignOverlay` (un seul QGraphicsItem, hors fichier) |
| Barres : rail, barre contextuelle, barre des pages (miniatures) | `ui.py` | `DesignChrome`, `build_context_bar`, `PageThumb` |
| Menus : couleurs (document, marque), fond / dégradé, contour, ombre, position, masque, réglages / filtres d'image, redimensionner, clic droit, repères | `menus.py` | `*_menu`, `open_context_menu`, `parse_size` |
| Menus du texte (effets, police, taille, alignement, listes) | `menus_text.py` | — |
| Menus des tableaux / graphiques, données d'un graphique | `menus_data.py` | `table_menu`, `chart_menu`, `edit_chart_data` |
| Menu Exporter | `menus_export.py` | `export_menu`, `run_export` |
| Présentation plein écran | `present.py` | `PresentationWindow` |
| Règles graduées (haut, gauche) | `rulers.py` | `Rulers`, `Ruler`, `tick_step` |
| Panneau latéral (modèles et formats, éléments, texte, images, position et calques) | `panels.py` | `build_<onglet>`, `LayerList`, `PositionPanel` |
| Modèles de conception (originaux) | `templates.py` | `TEMPLATES` |
| Rendu hors écran : miniatures, export PNG / JPEG / PDF / SVG | `render.py` | `paint_page`, `export_pages` |
| Glyphes des boutons | `glyphs.py` | `paint_design_glyph` (appelé par `fm_board.ui.paint_glyph`) |

Points de branchement dans la coque (modifications MINIMALES, Miro et CAD inchangés) :
- `fm_board/model.py` : `DEFAULTS` reçoit les types Design, `normalize_item` appelle `design_model.normalize_entity`,
  `ICON_ROWS` (icônes réglables `design*`).
- `fm_board/scene.py` : `MODULES` + « design » ; `module_of` lit `MODULE` ; crochets génériques dans `_add`
  (`added_to_scene`), `_remove` (`removing_from_scene`), `delete_items` (`dependent_ids`), `item_opacity`
  (`module_opacity`) ; `_bring_asset` pour tout élément à `asset`.
- `fm_board/view.py` : `view.design` reçoit souris / clavier / dépôt de fichiers quand il est actif (même schéma que
  `view.cad`).
- `fm_board/ui.py` : `MODULES` (bouton Design), `set_module` / `toggle_cad` (modules exclusifs), `design_active`,
  `_place_chrome`, `paint_glyph` (genres `design…`).

## Note de conception (décisions, 2026-10-29)

- **Moteur : la scène du board (QGraphicsScene / QGraphicsView), pas un canvas à part.** Écartés : un QPainter
  maison (tout l'index spatial, le cache par élément, le zoom, le pan rapide, l'annulation, l'enregistrement
  automatique, le presse-papiers et l'export seraient à refaire) ; une scène séparée (deux vues, deux fichiers, plus
  de griser / masquer par module). Gains mesurés en réutilisant : pan du board (image décalée, ~9 ms / image),
  `DeviceCoordinateCache`, index BSP calé sur le contenu.
- **Pages = éléments `design_page` (plans de travail), éléments = ENFANTS de leur page** (`setParentItem`) :
  coordonnées relatives (`x`, `y` dans la page), découpe par la page (`ItemClipsChildrenToShape`), déplacer une page
  déplace son contenu sans rien réécrire ; pages empilées verticalement (`layout_positions`, écart 60) comme Canva.
- **Format** : nouveaux types dans le `.mro` existant (version 2 inchangée). Une version plus ANCIENNE de l'appli
  garde les éléments Design dans `foreign` et les réécrit tels quels (règle déjà en place) ; champs inconnus gardés.
- **Annulation** : la commande unique du board (`StateCommand`, états avant / après par identifiant) ; un geste =
  une étape ; un modèle = une macro (`beginMacro`) ; curseurs en direct = `live_change` (une étape par geste).
- **Contrôleur à la manière du CAD** : actif, il reçoit la souris et le clavier avant la vue (mêmes crochets que
  `view.cad`) ; les éléments Design n'ont NI poignées NI déplacement Qt (`ItemIsMovable` faux) : la règle Ctrl est
  donc tenue au seul endroit qui décide (`DesignController.mouse_press`), Miro et CAD ne sont pas touchés.
- **Groupes** : un champ `group` (identifiant) ; un clic choisit tout le groupe (pas de hiérarchie d'éléments).
- **Texte** : un style pour la boîte + des parties stylées (`spans` : début / fin en caractères, gras, italique,
  souligné, taille ; lues du document Qt à `to_dict`, réappliquées après formats remis à zéro). Un style pour toute la boîte (police, taille, couleur, gras, italique, souligné, majuscules,
  alignement, interligne, espacement des lettres, surlignage) ; édition sur place par le texte du board (`_Text`).
- **Images** : copiées dans `<board>_assets/` (cycle de vie du board, nettoyage sûr) ; recadrage NON destructif
  (`crop` = partie visible, fractions) ; retouches calculées une fois par réglage (numpy si présent, sinon noir et
  blanc et flou seulement) sur une image de travail de 1 600 px au plus.

### Piège Qt : Tab dans un élément de scène (rencontré, contourné)
`QGraphicsView.event` envoie Tab à la scène, et `QGraphicsItem.sceneEvent` le donne à la chaîne de focus de la scène
avant `keyPressEvent` : l'éditeur de cellule perdait le focus. `_CellEditor.sceneEvent` traite Tab lui-même ; la vue
du board n'est pas modifiée.

### Piège PySide6 (rencontré, contourné)
`setParentItem` sur un élément dont la classe surcharge `itemChange` en Python : PySide6 ne sait pas rendre un
QGraphicsItem depuis Python pour `ItemParentChange` → le parent devient None (même en rendant la valeur reçue).
Les éléments Design gardent l'`itemChange` de Qt (`itemChange = QGraphicsObject.itemChange`) ; ce que faisait celui du
board est fait à la main (`_notify_cad_layer`, `scene.item_moved` en fin de geste).

## Interactions (règle Ctrl de l'appli)

- Clic = choisir (tout le groupe) ; Maj + clic = ajouter / retirer ; glisser SANS Ctrl (sur un élément ou dans le
  vide) = cadre de sélection ; clic sur un élément d'une multi-sélection sans glisser = lui seul.
- **Ctrl + glisser = déplacer** (sur un élément ou dans la sélection) ; Ctrl + Alt + glisser = déplacer une COPIE ;
  magnétisme sur les bords / centres de la page et des autres éléments (réglages de magnétisme du board, Alt = sans) ;
  déposé sur une autre page = rattaché à elle.
- Poignées (sans Ctrl : ce n'est pas un déplacement) : coins = proportions gardées (Maj = libre pour une forme),
  côtés = largeur / hauteur ; TEXTE : coins = taille de police, côtés G / D = largeur ; IMAGE : côtés = recadrage
  (l'échelle ne change pas) ; LIGNE : extrémités G / D ; sélection multiple : coins seulement (tout à l'échelle).
  Rotation : poignée sous la sélection, aimantée à 45° (3°), Maj = pas de 15° ; multi-sélection : autour du centre.
- Déposer un fichier image SUR une image ou un cadre vide le remplace (cadrage couvrant, taille du cadre gardée) ; un
  clic dans la bibliothèque remplit le cadre vide choisi. Petits éléments à l'écran (< 36 px) : poignées de côté retirées.
- Double-clic : texte = édition (un texte vidé disparaît), image = recadrage (poignées = bords visibles,
  Ctrl + glisser = image dans son cadre, Entrée / Échap / clic dehors = fin).
- Clavier (module actif, hors édition de texte) : Suppr, Ctrl+C / X / V / D / A, Ctrl+G / Ctrl+Maj+G, Ctrl+] / [
  (Alt : premier plan / arrière-plan), Alt+Maj+L verrou, flèches (Maj = 10), PageUp / PageDown pages, T texte,
  R rectangle, C cercle, L ligne ; texte : Ctrl+B / I / U, Ctrl+Maj+K majuscules, Ctrl+Maj+L / E / R / J alignement,
  Ctrl+Maj+> / < taille. Les autres lettres sont prises (les outils de Miro ne s'activent pas). Molette, bouton du
  milieu, Espace : zoom / pan du board.
- Repères : Ctrl + glisser = déplacer (sans Ctrl : cadre de sélection), aimantants ; glisser un élément SANS Ctrl
  affiche la bulle « Ctrl + glisser pour déplacer ».
- Pages (barre du bas) : clic = aller à la page (affichée dans la zone libre, hors panneau) ; Ctrl + glisser =
  réordonner (fantôme `DRAG_GHOST_OPACITY`) ; clic droit = dupliquer, renommer, monter / descendre, redimensionner,
  supprimer ; « + » = page du même format. Calques (panneau) : Ctrl + glisser = ordre, cadenas = verrou.

## Étude de Canva (Phase 1, 2026-10-29)

Sources consultées (aide officielle) : canva.com/help/canva-keyboard-shortcuts, /help/layer-group-align,
/help/resize-and-crop, /help/finding-and-arranging-layers, /help/using-frames.
- VÉRIFIÉ (aide) : Ctrl+D dupliquer, Ctrl+G / Ctrl+Maj+G grouper / dissocier, Ctrl+Maj+L / C / R alignement du texte
  (Ctrl+Maj+E retenu ici pour « centré » : Ctrl+Maj+C est la copie de l'appli), alignement via « Position » (un seul
  élément : sur la page ; plusieurs : entre eux), panneau Calques (glisser pour réordonner), recadrage non destructif
  (les parties cachées restent), double-clic sur une image de cadre pour la repositionner.
- DÉDUIT (usage courant, non revérifié ici) : T / R / C / L pour texte / rectangle / cercle / ligne, Alt + glisser
  pour dupliquer (ici Ctrl + Alt + glisser à cause de la règle Ctrl), flèches 1 px / Maj 10 px, pages empilées
  verticalement, rotation aimantée, poignées de côté d'une image = recadrage, coins = proportions gardées.
- NON reproduit (hors périmètre local ou non confirmé) : comptes, cloud, collaboration, bibliothèque en ligne,
  IA, publication, impression ; animations ; cadres-masques à formes (« frames ») ; texte multistyle par caractère.

## Mesures (fluidité, offscreen 2 400 × 1 300, une page 1 920 × 1 080, éléments mêlés formes / textes / lignes)

Sonde : `probe_perf.py N` (hors dépôt : événement souris envoyé au viewport + `processEvents`, qui peint).
| Geste | 300 éléments AVANT → APRÈS | 1 000 éléments |
|---|---|---|
| Ctrl + glisser 1 élément | 50 → 15 ms / image (p95 18) | 43 ms |
| Ctrl + glisser 20 éléments | 50 → 16 ms | 38 ms |
| Redimensionner / pivoter | 49-55 → 16-17 ms | 38 ms |
| Changer de sélection (barre refaite) | 59 → 23 ms | 52 ms |
| Zoom (un cran) | 104 → 47-55 ms | 137-174 ms |
| Pan (bouton du milieu) | 23 → 9 ms | 7 ms |
| Curseur en direct (opacité de 20 éléments) | 24 → 14 ms | 14 ms |
VRAIE FENÊTRE Windows (même sonde, `QT_QPA_PLATFORM=windows`, 300 éléments, 2 400 × 1 300) : Ctrl + glisser
20 ms / image (p95 36), redimensionner / pivoter 19 ms, changer de sélection 31 ms, zoom 55 ms / cran, pan 13 ms,
curseur en direct 19 ms, changer de page 32 ms (dont ~10 ms d'envoi de la fenêtre à Windows, comme le board).
Après le texte multistyle (hors écran, 300 éléments) : inchangé (déplacer 15,5 ms, sélection 19 ms, zoom 44 ms).
IMAGE DE PAGE (2026-10-30) : une page d'au moins `SNAPSHOT_MIN` (60) éléments est peinte comme UNE image
(`DesignPageItem.snapshot`, `render.render_image`, côté ≤ 2 400 px) pendant un zoom continu (`_zoom_changed`, nette
300 ms après le dernier cran) et pendant un geste (`GestureMixin._freeze_page` : tout sauf les éléments manipulés,
les autres MASQUÉS — Qt redessinait sinon leur image gardée à chaque image) ; magnétisme par recherche
dichotomique (`geometry.best_snap`, ~4 ms par mouvement à 1 000 éléments avant). Vraie fenêtre, avant → après :
300 éléments : déplacer 20 → 11 ms, pivoter 19 → 10 ms, zoom 55 → 17 ms / cran ; 1 000 éléments : déplacer
~45 → 14 ms, pivoter → 10 ms, zoom ~150 → 32 ms. Contrepartie : pendant le geste, l'élément manipulé passe
au-dessus des autres (sa place dans l'ordre revient au relâché) ; l'image est prise au 1er mouvement / cran.
Reste : changer de sélection à 1 000 éléments ~38 ms (repeinture entière de la vue, `FullViewportUpdate` de la coque).
Corrections : (1) `boundingRect` GARDÉ par élément (Qt le demande ~3 fois par élément et par image ; 108 000 appels
Python pour 60 images) ; (2) contenu du panneau latéral OPAQUE (Qt retire les voisins opaques de la zone à
peindre : les miniatures des modèles étaient repeintes à chaque image du board, ~5 ms) ; (3) miniatures des pages
refaites seulement pour les pages touchées par les commandes d'annulation (une empreinte JSON de tout coûtait
~60 ms à 1 000 éléments). Reste : zoom à 1 000 éléments (peinture réelle de chaque élément, cache coupé pendant le
zoom par la coque) ; la mesure en vraie fenêtre Windows n'a pas été faite (sonde hors écran).

## Limites connues (2026-10-29)

- Validation à la main en vraie fenêtre NON faite (session autonome) : gestes vérifiés par tests automatiques hors
  écran (événements souris / clavier envoyés au viewport) et captures hors écran ; mesures en vraie fenêtre faites.
- Retouches d'image (luminosité, contraste, saturation) : seulement avec numpy (présent dans l'environnement) ;
  sans numpy, noir et blanc et flou seulement.
- Un élément Design ne peut pas être déplacé en mode Miro (pas de `ItemIsMovable`) : on passe en mode Design.
- Page sans rotation ; pas d'animation ni de vidéo ; secteurs et anneau n'utilisent que la 1re série ; kit de marque
  partagé entre boards limité aux couleurs et polices (pas de logos ni de styles de texte complets).

## PLAN DE TRAVAIL (persistant, mis à jour à chaque étape)

| Tâche | État | Dépend de |
|---|---|---|
| Audit, référence des tests (34 FAIL / ERROR connus, dont `test_board.BoardModeTest.test_create_mro_then_open_and_close_it`, présent sur HEAD propre) | Terminée | — |
| Étude Canva, note de conception | Terminée | — |
| Tranche 1 : pages, rectangle, sélection, poignées, Ctrl + glisser, sauvegarde, réouverture | Terminée | — |
| Formes (19, dont cœur et anneau), lignes / flèches, dégradés, contours, arrondis, ombres, opacité, miroir | Terminée | Tranche 1 |
| Texte (édition, polices, styles, interligne, espacement, surlignage, ombre, contour / creux) | Terminée | Tranche 1 |
| Images (import, dépôt, coller, recadrage non destructif, retouches, filtres, arrondi, contour, masque en forme, arrière-plan de page) | Terminée | Tranche 1 |
| Copier / coller le style (Ctrl+Alt+C / V), couleurs du document dans les menus | Terminée | — |
| Présentation plein écran (Ctrl+Alt+P, bouton du rail) | Terminée | Rendu |
| Découpage : contrôleur (gestes, commandes) et interface (menus) en fichiers de moins de 650 lignes | Terminée | — |
| Groupes, alignement, répartition, ordre, verrou, calques, position numérique | Terminée | Tranche 1 |
| Pages : ajouter, dupliquer, supprimer, réordonner, renommer, redimensionner (avec le contenu) | Terminée | Tranche 1 |
| Modèles locaux (8), formats (12), combinaisons de polices, bibliothèque d'images locale | Terminée | Pages |
| Export PNG / JPEG / PDF multipage / SVG, échelle, qualité, fond transparent | Terminée | Rendu |
| Tableaux (lignes / colonnes, en-tête, couleurs, cellules modifiées sur place, Tab) et graphiques (barres, courbe, secteurs, anneau ; données « Libellé ; valeur ») | Terminée | Éléments |
| Image de page pendant le zoom et les gestes (pages de 60 éléments et plus) | Terminée | Fluidité |
| Graphiques à plusieurs séries (jusqu'à 8) : données « Libellé ; valeur ; valeur… », 1re ligne facultative = noms (légende) ; barres groupées, une courbe par série ; enregistrés en `values` (1re série, format d'origine) + `more_series` + `series_names` | Terminée | Tableaux et graphiques |
| Validation graphique en vraie fenêtre Windows (pas seulement hors écran) | À faire | — |
| Texte multistyle : gras / italique / souligné / taille / couleur / police sur une PARTIE du texte (pendant l'édition : raccourcis, ou barre contextuelle : boutons sans focus, menus qui gardent l'édition — `_DesignText.focusOutEvent` ignore `PopupFocusReason`), enregistré en `spans`, mis à l'échelle avec la boîte | Terminée | Texte |
| Listes à puces / numérotées (toute la boîte, menu Alignement) | Terminée | Texte |
| « Autre couleur… » sur une partie du texte (le sélecteur des réglages est une fenêtre Qt.Popup : l'édition continue ; Échap = couleur d'avant) | Terminée | Texte |
| Grilles de photos (6 mises en page), cadres vides en forme, dépôt / bibliothèque = remplir le cadre (cadrage couvrant), « Remplacer l'image… » | Terminée | Images |
| Repères de page (clic droit sur la page : ajouter ; Ctrl + glisser : déplacer ; clic droit dessus : retirer ; aimantants), marges affichées (5 % du petit côté) | Terminée | Pages |
| Règles graduées (Maj+R, unités de la page courante ; tirer depuis une règle = nouveau repère), aide des raccourcis (? ou clic droit) | Terminée | Pages |
| Fond perdu (3 mm) et traits de coupe à l'export PDF (impression) | Terminée | Export |
| Styles du document : couleurs utilisées (menus de couleur), styles de texte utilisés (onglet Texte : appliquer / nouveau texte) | Terminée | Texte, Styles |
| Kit de marque partagé entre TOUS les boards (couleurs et polices favorites : menus de couleur « Marque » / « Ajouter à la marque », menu Police) : réglage d'état `board_design_brand` (`BOARD_DEFAULTS`, `_LIVE_STATE_KEYS` de `settings_store`, écrit par `save_live_state` comme `board_pen_presets`) | Terminée | Réglages |
| Espacement égal entre deux voisins pendant Ctrl + glisser (segments tracés), renommer un calque, export d'une plage de pages (« 1-3, 5 ») | Terminée | Gestes, Export |
| Icônes réglables : lignes `design*` ajoutées à `ICON_ROWS` (fenêtre de réglages : vérifier l'affichage) | Partielle | — |

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
| Éléments de la scène : page, forme, texte, image ; peinture (dégradés, ombres, retouches d'image) | `items.py` | `DesignPageItem`, `DesignShapeItem`, `DesignTextItem`, `DesignImageItem` |
| Opérations du document (1 étape d'annulation chacune) : pages, éléments, groupes, alignement, ordre, modèles | `document.py` | `add_page`, `duplicate_page`, `delete_page`, `move_page`, `resize_page`, `insert_elements`, `restack`, `apply_template`… |
| Activation, souris, clavier, sélection, poignées (lecture) | `controller.py` | `DesignController` (mélange les deux suivants) |
| Gestes : cadre de sélection, Ctrl + glisser, poignées, rotation, recadrage, magnétisme | `gestures.py` | `GestureMixin` |
| Commandes : ajouter page / forme / texte / image, dépôt, dupliquer, verrou, presse-papiers, style, présenter | `commands.py` | `CommandMixin` |
| Dessin temporaire (titres de page, survol, poignées, guides, cadre de sélection, recadrage, bulle) | `overlay.py` | `DesignOverlay` (un seul QGraphicsItem, hors fichier) |
| Barres : rail, barre contextuelle, barre des pages (miniatures) | `ui.py` | `DesignChrome`, `build_context_bar`, `PageThumb` |
| Menus : couleurs (dont couleurs du document), fond / dégradé, contour, ombre, position, masque, effets du texte, police, réglages / filtres d'image, redimensionner, export, clic droit | `menus.py` | `*_menu`, `open_context_menu`, `export_menu`, `parse_size` |
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
Corrections : (1) `boundingRect` GARDÉ par élément (Qt le demande ~3 fois par élément et par image ; 108 000 appels
Python pour 60 images) ; (2) contenu du panneau latéral OPAQUE (Qt retire les voisins opaques de la zone à
peindre : les miniatures des modèles étaient repeintes à chaque image du board, ~5 ms) ; (3) miniatures des pages
refaites seulement pour les pages touchées par les commandes d'annulation (une empreinte JSON de tout coûtait
~60 ms à 1 000 éléments). Reste : zoom à 1 000 éléments (peinture réelle de chaque élément, cache coupé pendant le
zoom par la coque) ; la mesure en vraie fenêtre Windows n'a pas été faite (sonde hors écran).

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
| Validation graphique en vraie fenêtre Windows (pas seulement hors écran) | À faire | — |
| Texte multistyle : gras / italique / souligné / taille / couleur / police sur une PARTIE du texte (pendant l'édition : raccourcis, ou barre contextuelle : boutons sans focus, menus qui gardent l'édition — `_DesignText.focusOutEvent` ignore `PopupFocusReason`), enregistré en `spans`, mis à l'échelle avec la boîte | Terminée | Texte |
| Couleur « Autre couleur… » d'une partie (le sélecteur des réglages n'est pas un menu : il termine l'édition), listes à puces | À faire | Texte |
| Grilles de photos (6 mises en page), cadres vides en forme, dépôt / bibliothèque = remplir le cadre (cadrage couvrant), « Remplacer l'image… » | Terminée | Images |
| Repères de page (clic droit sur la page : ajouter ; Ctrl + glisser : déplacer ; clic droit dessus : retirer ; aimantants), marges affichées (5 % du petit côté) | Terminée | Pages |
| Règles graduées (Maj+R, unités de la page courante ; tirer depuis une règle = nouveau repère), aide des raccourcis (? ou clic droit) | Terminée | Pages |
| Fond perdu (3 mm) et traits de coupe à l'export PDF (impression) | Terminée | Export |
| Styles du document : couleurs utilisées (menus de couleur), styles de texte utilisés (onglet Texte : appliquer / nouveau texte) | Terminée | Texte, Styles |
| Kit de marque enregistré hors d'un design (polices / couleurs partagées entre boards) | À faire | Réglages |
| Espacement égal entre deux voisins pendant Ctrl + glisser (segments tracés), renommer un calque, export d'une plage de pages (« 1-3, 5 ») | Terminée | Gestes, Export |
| Icônes réglables : lignes `design*` ajoutées à `ICON_ROWS` (fenêtre de réglages : vérifier l'affichage) | Partielle | — |

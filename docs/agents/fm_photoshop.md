# Module Photoshop du Board (`fm_photoshop/`, retouche et composition d'images matricielles)

Sixième module du Board (après Miro, CAD, Design, Tableur, Illustrator), commencé le 2026-11-01 (mission de l'utilisateur :
« module professionnel de création et de retouche d'images matricielles, inspiré des usages de Photoshop »). Bouton
« Photoshop » de la barre des modules (`BoardPane.set_module("photoshop")`). Tout est LOCAL ; aucun code, icône ni
ressource d'Adobe. **Aucune compatibilité PSD n'est annoncée** (non faite, voir « État »). À ne pas confondre avec
`fm_cad/cad_photoshop.py` (ENVOI d'entités CAD vers l'application Adobe Photoshop installée : autre responsabilité).

**Tests** : `python tests/run.py fm_photoshop` (`tests/test_photoshop_*.py`) ; `python tests/run.py fm_board` (coque) pour
tout changement des crochets. **Mesures** : `python tools/bench_photoshop.py [petit|4k|grand]` (offscreen).

## Carte : fonctionnalité -> fichiers (à ouvrir directement)

Couches : chaque fichier n'importe que ceux qui le précèdent. Tout ce qui est avant `render.py` est SANS Qt.

| Fonctionnalité | Fichier | Points d'entrée |
|---|---|---|
| Plan de pixels à bords variables (calque, masque, sélection), rectangles | `planes.py` | `Plane` (`read`, `write`, `ensure`, `trim`, `shift`), `rect_union`, `rect_intersect` |
| Document, calques, groupes, masques, modes de fusion (noms et libellés) | `model.py` | `Document`, `Layer`, `Mask`, `new_document`, `BLEND_MODES` |
| Formules des modes de fusion | `blend.py` | `blend_over` |
| Composition par région (opacité, groupes, masques, écrêtage) | `compose.py` | `compose`, `flatten_u8`, `to_straight_u8`, `to_premult_u8` |
| Historique par zones (patches de pixels) et par fonctions (structure) | `history.py` | `History`, `TilesCommand`, `CallCommand`, `Compound` |
| Brosse, gomme, peinture de masque (tampons, tuiles, sélection, pression, lissage) | `brush.py` | `Brush`, `Stroke`, `dab_alpha` |
| Opérations sur le document annulables (calques, groupes, fusion, aplatir, masques, remplir, déplacer) | `ops.py` | `add_layer`, `duplicate_layer`, `set_props`, `move_layer`, `group_layers`, `merge_down`, `flatten`, `add_mask`… |
| Format natif `.fmps` (ZIP : manifeste JSON + PNG par calque / masque) | `container.py` | `dumps`, `loads`, `save`, `load`, `write_atomic`, `ContainerError`, `TooNewError` |
| Import / export d'images (Pillow) | `io_images.py` | `import_image`, `export_document`, `encode` |
| Session partagée (document + historique + outil + vue), registre | `session.py` | `Session`, `create`, `open_asset`, `flush` |
| Type « ps_doc » du `.mro`, défauts, normalisation | `board_model.py` | `PS_DOC`, `DEFAULTS`, `normalize_entity`, `fit_size` |
| Réglages appliqués (couleurs du contenu, zoom) ; défauts | `look.py` ; `settings_defaults.py` | `apply_settings`, `LOOK` ; `PS_DEFAULTS` |
| Tuiles composées gardées par session, damier | `render.py` | `TileCache`, `cache_for`, `checker_brush` |
| Établi : zoom, déplacement de la vue, outils souris / stylet / clavier | `canvas.py` | `CanvasView` |
| Panneaux : calques (liste, réglages, masques), brosse (curseurs, couleurs) | `panels.py` | `LayersPanel`, `BrushPanel` |
| Éditeur Standard plein cadre (même session) | `standard.py` | `StandardPane` |
| Élément du Board (présentation, Ctrl + glisser, ⤢, enregistrement du conteneur) | `board_item.py` | `PsItem` (`session`, `before_save`, `open_standard`) |
| Barre d'outils du module dans le Board (nouveau, importer, Standard, exporter) | `board_ui.py` | `PhotoshopController`, `NewDocumentDialog` |

Crochets dans la COQUE (minimaux, listés par `hooks` du dépôt de la session) :
- `fm_board/model.py` : `DEFAULTS` reçoit `ps_doc`, `normalize_item` -> `ps_model.normalize_entity`, `ICON_ROWS` (« photoshop »).
- `fm_board/scene.py` : import de `fm_photoshop.board_item` (enregistre le type), `MODULES` + « photoshop »,
  `assets_in_use` (tout élément qui porte un `asset`), `to_data` appelle `before_save()` des éléments qui l'ont.
- `fm_board/ui.py` : `MODULES` (bouton), `paint_glyph` (« photoshop »), `set_module` / `toggle_cad` (modules exclusifs),
  `_place_chrome`, réglages (`ps_look.apply_settings` -> `photoshop.refresh_look`).
- `fm_board/modulebar.py` (`MODULE_NAMES`), `fm_board/settings.py` / `settings_defaults.py` (couleur du module),
  `settings_store.py` (`DEFAULT_SETTINGS.update(PS_DEFAULTS)`).

## Décisions (2026-11-01)

- **Conventions de pixels** : calques en RGBA 8 bits, couleurs encodées sRGB, alpha DROIT ; composition en flottants
  PRÉMULTIPLIÉS dans l'espace encodé (comme Photoshop par défaut, pas de passage en linéaire) ; conversion en droit à
  l'export (`to_straight_u8`, pixels transparents = couleur 0), en prémultiplié 8 bits BGRA à l'affichage. Pas de halo :
  un pixel rouge à 50 % d'alpha sur transparent ressort rouge pur à 50 % (test).
- **Plans à bords variables** (`Plane`) : un calque ne coûte que son contenu ; il grandit à l'écriture (marge de 96 px), se
  réduit avec `trim`. Hors du plan : `fill` (0 = transparent ; masque 255 = visible). Rectangles `(x0, y0, x1, y1)`,
  bord droit exclu, repère du document.
- **Composition** (voir l'en-tête de `compose.py`) : groupe « passer à travers » à 100 % / normal / sans masque = enfants
  composés directement sur le dessous ; sinon groupe ISOLÉ (enfants sur transparent, puis traité comme un calque) ;
  écrêtage : un calque `clip` est limité à l'alpha de la base (premier calque non écrêté dessous), composés ensemble puis
  posés avec l'opacité et le mode de la base. Calque invisible = absent avec ses calques écrêtés. Fusion `W3C` séparable.
- **Brosse** : le trait n'est jamais recomposé en entier. Lecture / écriture par tuiles de 64 ; couverture flottante par
  tuile ; débit (accumulation), opacité (plafond du trait), sélection (multiplie la couverture, bords progressifs
  respectés), pression (taille / débit), lissage (moyenne exponentielle + rattrapage à la fin). Annulation par ZONES :
  `TilesCommand` ne garde que les tuiles touchées (avant / après), jamais le document. Historique plafonné
  (`history.LIMIT_BYTES`, réglage `board_ps_history_mb`).
- **Format natif `.fmps`** : ZIP, `manifest.json` (version 1, document, arbre des calques, clés inconnues gardées dans
  `extra`), `layers/<id>.png`, `masks/<id>.png`, `icc.bin`, `preview.png`. Pas de pixels en JSON. Écriture ATOMIQUE
  (`.part` + `fsync` + renommage, `.bak` de la version précédente) ; version PLUS RÉCENTE refusée (`TooNewError`),
  jamais ouverte à moitié ; noms d'archive vérifiés (`^(layers|masks)/[0-9a-f]{16}\.png$`), rien n'est extrait sur
  disque ; PNG de calque non réencodé tant que son plan n'a pas changé (`Plane.png`).
- **Pixels dans le Board** : l'élément `ps_doc` ne porte que `asset` (nom d'empreinte du conteneur dans
  `<board>_assets/`, même cycle de vie que les images : écriture atomique, nettoyage après enregistrement réussi,
  copie au collage entre boards, suit le dossier du board) et `init` (document neuf tant qu'aucun conteneur n'existe).
  `BoardScene.to_data` appelle `PsItem.before_save` : le conteneur n'est réécrit que si le document a changé
  (`Session.flush`, comparaison des versions de l'historique). Ressource absente / illisible : session vide avec
  `error` (affiché sur l'élément) et la référence d'origine N'EST PAS écrasée.
- **Session partagée** : l'élément et l'éditeur Standard affichent la MÊME `Session` (document, historique, outil, brosse,
  couleurs, zoom, position) et la MÊME `TileCache` ; passer de l'un à l'autre ne recharge, ne copie ni ne recompose rien
  (test : au plus 4 tuiles recalculées au retour). Registre par (jeton de la scène, identifiant de l'élément).
- **Annulation** : l'historique du DOCUMENT est distinct de celui du Board (comme le Tableur) ; annuler un déplacement
  de l'élément ne touche pas aux pixels.
- **Règle Ctrl + glisser** : déplacer l'élément dans le Board et déplacer un calque (outil Déplacer) démarrent
  seulement avec Ctrl ; sans Ctrl l'outil dit « Ctrl + glisser ».
- **Bibliothèques** : NumPy (BSD, déjà là) pour les calculs, Pillow (HPND, déjà là) pour PNG / JPEG / TIFF / WebP / BMP,
  OpenImageIO (déjà dans `requirements.txt`) seulement dans les TESTS pour relire les exports avec une bibliothèque
  indépendante. Pas de GPU, pas de ICC engine (voir « Limites »). `psd-tools` : voir « État ».

## Format de lecture / écriture exact

| Format | Lu | Écrit | Détails |
|---|---|---|---|
| `.fmps` (natif) | oui | oui | tout le document |
| PNG | oui | oui | RGBA 8 bits, profil ICC et résolution conservés |
| TIFF | oui | oui | RGBA 8 bits, compression LZW, profil ICC, résolution |
| JPEG | oui | oui | SANS alpha (composé sur un fond, annoncé), qualité réglable, profil ICC |
| WebP | oui | oui | alpha, qualité ou sans perte |
| BMP | oui | non | |
| 16 bits / flottant | lu en 8 bits | non | note explicite « converti en 8 bits » |
| PSD / PSB / OpenRaster | non | non | non commencé |

## État des fonctions

(mise à jour à chaque tranche — voir la fin du fichier)

## Mesures

(voir la fin du fichier)

## PASSATION

(voir la fin du fichier)

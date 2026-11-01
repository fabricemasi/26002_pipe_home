# Module Photoshop du Board (`fm_photoshop/`, retouche et composition d'images matricielles)

Sixième module du Board (après Miro, CAD, Design, Tableur, Illustrator), commencé le 2026-11-01 (mission de l'utilisateur :
« module professionnel de création et de retouche d'images matricielles, inspiré des usages de Photoshop »). Bouton
« Photoshop » de la barre des modules (`BoardPane.set_module("photoshop")`). Tout est LOCAL ; aucun code, icône ni
ressource d'Adobe. **Aucune compatibilité PSD en écriture** (lecture seule, voir « Formats »). À ne pas confondre avec
`fm_cad/cad_photoshop.py` (ENVOI d'entités CAD vers l'application Adobe Photoshop installée : autre responsabilité).

**Tests** : `python tests/run.py fm_photoshop` (18 fichiers `tests/test_photoshop_*.py`, ~165 tests, ~35 s) ; `python tests/run.py
fm_board` (coque + tous les modules) pour tout changement des crochets. **Mesures** : `python tools/bench_photoshop.py [petit|4k|grand]`
(calcul, mémoire, conteneur) et `python tools/probe_photoshop_latency.py [petit|4k]` (latence visible : évènements réels + peinture).

## Carte : fonctionnalité -> fichiers (à ouvrir directement)

Couches : chaque fichier n'importe que ceux qui le précèdent. Sans Qt : `planes` … `diagnostics`, `io_images`, `io_psd`, `color`,
`filters`, `selection`, `adjust`, `transform`, `presets`, `look`, `board_model`, `settings*`. Avec Qt : `render` et au-delà.

| Fonctionnalité | Fichier | Points d'entrée |
|---|---|---|
| Plan de pixels à bords variables (calque, masque, sélection), rectangles | `planes.py` | `Plane` (`read`, `write`, `ensure`, `trim`, `shift`), `rect_union`, `rect_intersect` |
| Document, calques, groupes, masques, modes de fusion | `model.py` | `Document`, `Layer` (`source` = texte / forme), `Mask`, `new_document`, `BLEND_MODES` |
| Formules des modes de fusion (sans division) | `blend.py` | `blend_over`, `blend_over_reference` |
| Composition par région (opacité, groupes, masques, écrêtage) | `compose.py` | `compose`, `flatten_u8`, `to_straight_u8`, `to_premult_u8` |
| Historique par zones (patches) et par fonctions (structure, sélection) | `history.py` | `History`, `TilesCommand`, `CallCommand`, `Compound`, `SelectionCommand` |
| Brosse, gomme, masque ET retouche (clone, correcteur, flou, netteté, doigt, densité) | `brush.py` | `Brush` (`mode`), `Stroke`, `dab_alpha`, `MODES` |
| Présélections de brosses (usine + utilisateur) | `presets.py` | `all_presets`, `with_saved`, `without` |
| Sélections (formes, lasso, baguette, couleur, combinaisons, adoucir, agrandir, contour) | `selection.py` | `rectangle`, `ellipse`, `polygon`, `wand`, `color_range`, `combine`, `invert`, `feather`, `resize`, `outline_segments` |
| Flou gaussien, accentuation, bruit | `filters.py` | `gaussian_blur`, `unsharp`, `add_noise` |
| Réglages d'image et filtres (registre) | `adjust.py` | `EFFECTS`, `run`, `curve_lut`, `clean_params` |
| Transformations, recadrage, tailles, symétries | `transform.py` | `TransformSession`, `resample`, `crop`, `resize_image`, `canvas_size`, `flip_canvas` |
| Opérations annulables sur le document | `ops.py` | `add_layer`, `duplicate_layer`, `set_props`, `move_layer`, `group_layers`, `merge_down`, `flatten`, masques, `fill_rect`, `shift_layer` |
| Texte et formes éditables (rendu Qt) | `vector.py` | `normalize`, `render`, `apply_source` |
| Couleur (ICC par LittleCMS) | `color.py` | `assign`, `convert`, `system_profiles`, `convert_array` |
| Format natif `.fmps` (ZIP : manifeste + PNG) | `container.py` | `dumps`, `loads`, `save`, `load`, `write_atomic`, `ContainerError`, `TooNewError` |
| Import / export d'images (Pillow) | `io_images.py` | `import_image`, `export_document`, `encode` |
| Import PSD (psd-tools, lecture seule) | `io_psd.py` | `read_psd`, `available` |
| Diagnostic d'un document | `diagnostics.py` | `diagnose`, `report` |
| Session partagée (document + historique + outil + vue), registre | `session.py` | `Session`, `create`, `open_asset`, `flush` |
| Actions d'édition (sélection, presse-papiers, remplir, réglages, texte, conversion…) | `actions.py` | `Actions` |
| Type « ps_doc » du `.mro`, défauts, normalisation | `board_model.py` | `PS_DOC`, `DEFAULTS`, `normalize_entity`, `fit_size` |
| Réglages appliqués ; défauts ; lignes du catalogue | `look.py` ; `settings_defaults.py` ; `settings.py` | `apply_settings`, `LOOK` ; `PS_DEFAULTS` ; `PS_TAB`, `PS_TREE` |
| Tuiles composées gardées par session, damier | `render.py` | `TileCache`, `cache_for`, `checker_brush` |
| Aperçu du déplacement d'un calque (sans recomposer la pile) | `movepreview.py` | `MovePreview` |
| Établi : zoom, vue, outils souris / stylet / clavier, contour animé | `canvas.py` | `CanvasView` |
| Panneaux : calques (liste, réglages, masques), brosse (curseurs, couleurs, présélections) | `panels.py` | `LayersPanel`, `BrushPanel` |
| Fenêtres : réglages avec aperçu, transformation, tailles, texte, forme, profil | `dialogs.py` | `EffectDialog`, `TransformDialog`, `SizeDialog`, `TextDialog`, `ShapeDialog`, `ProfileDialog` |
| Menus de l'éditeur (Édition, Sélection, Image, Calque, Réglages, Filtre) | `menus.py` | `MenuBar` |
| Export en tâche de fond sur un instantané | `exporter.py` | `start`, `snapshot`, `Exporter` |
| Éditeur Standard plein cadre (même session) | `standard.py` | `StandardPane` |
| Élément du Board (présentation, Ctrl + glisser, ⤢, enregistrement du conteneur) | `board_item.py` | `PsItem` (`session`, `before_save`, `open_standard`) |
| Barre d'outils du module dans le Board | `board_ui.py` | `PhotoshopController`, `NewDocumentDialog` |

Crochets dans la COQUE (minimaux ; Miro / CAD / Design / Tableur / Illustrator inchangés) :
- `fm_board/model.py` : `DEFAULTS` reçoit `ps_doc`, `normalize_item` -> `ps_model.normalize_entity`, `ICON_ROWS` (« photoshop »).
- `fm_board/scene.py` : import de `fm_photoshop.board_item` (enregistre le type), `MODULES` + « photoshop », `assets_in_use`
  (tout élément qui porte un `asset`), `to_data` appelle `before_save()` des éléments qui l'ont.
- `fm_board/ui.py` : `MODULES` (bouton), `paint_glyph` (« photoshop »), `set_module` / `toggle_cad` (modules exclusifs),
  `_place_chrome`, réglages (`ps_look.apply_settings` -> `photoshop.refresh_look`).
- `settings_store.py` (`DEFAULT_SETTINGS.update(PS_DEFAULTS)`), `settings_window_v2.py` (import, `STANDALONE_TABS`,
  `MODULE_SCOPES["board"]`, `TAB_LABELS`, menu « Restaurer »), `tests/test_settings_window_v2.py` (listes d'onglets).
- **À COMMITER AVEC LA SESSION QUI POSSÈDE LA BARRE DES MODULES** (fichiers non suivis / modifiés par elle, lignes déjà posées
  dans l'arbre de travail, jamais indexées par moi) : `fm_board/modulebar.py` (`MODULE_NAMES` + « photoshop »),
  `fm_board/settings.py` (couleur « Photoshop » de la ligne « Couleurs des modules »), `fm_board/settings_defaults.py`
  (`board_modulebar_color_photoshop`). Sans elles, la barre des modules de cette autre session ne montre pas le bouton.

## Décisions (2026-11-01)

- **Conventions de pixels** : calques en RGBA 8 bits, couleurs encodées sRGB, alpha DROIT ; composition en flottants
  PRÉMULTIPLIÉS dans l'espace encodé (comme Photoshop par défaut, pas de passage en linéaire sauf l'exposition) ; conversion en droit à
  l'export (`to_straight_u8`, pixels transparents = couleur 0), en prémultiplié 8 bits BGRA à l'affichage. Pas de halo :
  un pixel rouge à 50 % d'alpha sur transparent ressort rouge pur à 50 % (test), aussi après flou, rotation, filtre.
- **Plans à bords variables** (`Plane`) : un calque ne coûte que son contenu ; il grandit à l'écriture (marge de 96 px), se réduit
  avec `trim`. Hors du plan : `fill` (0 = transparent ; masque 255 = visible). Rectangles `(x0, y0, x1, y1)`, bord droit exclu.
- **Composition** (en-tête de `compose.py`) : groupe « passer à travers » à 100 % / normal / sans masque = enfants composés
  directement sur le dessous ; sinon groupe ISOLÉ ; écrêtage : un calque `clip` est limité à l'alpha de la base (premier calque
  non écrêté dessous), composés ensemble puis posés avec l'opacité et le mode de la base ; calque invisible = absent avec ses
  calques écrêtés. Fusion séparable W3C, formules SANS division en prémultiplié (testées contre la définition en couleurs droites).
  Chaque calque ne traite que la partie de la zone qu'il recouvre.
- **Brosse** : le trait n'est jamais recomposé en entier. Lecture / écriture par tuiles de 64 ; couverture flottante par tuile ; débit
  (accumulation), opacité (plafond du trait), sélection (multiplie la couverture, bords progressifs respectés), pression (taille /
  débit : réglages « Pression », valeur lue des évènements de stylet Qt), lissage (moyenne exponentielle + rattrapage à la fin).
  Annulation par ZONES : `TilesCommand` ne garde que les tuiles touchées (avant / après). Historique plafonné (`board_ps_history_mb`).
- **Retouche** (même moteur, `Brush.mode`) : tampon de duplication à source EXPLICITE (Alt + clic, décalage aligné gardé dans la
  session), correcteur (basses fréquences de la destination + hautes fréquences de la source, convolution normalisée par l'alpha :
  ni collage ni simple flou, mais PAS une reconstruction de Poisson), flou local, netteté locale, doigt, densité - / +. Clone /
  correcteur / flou / netteté lisent une copie du plan prise UNE fois au début du trait.
- **Réglages et filtres DESTRUCTIFS, explicitement** (annulables) : toujours calculés depuis l'original (`adjust.run` ne modifie
  rien), aperçu en fil de fond, résultat périmé rejeté, sélection partielle respectée, une seule étape à la validation. Les
  calques de réglage (non destructifs) existent en plus pour les 8 réglages « rgb ».
- **Texte et formes** : `Layer.source` (contenu, police, corps, couleur, alignement, bloc, interligne ; rectangle / ellipse / ligne,
  remplissage, contour, arrondi) + `pix` = rendu enregistré aussi. Peindre / remplir / filtrer / transformer est REFUSÉ tant que
  le calque n'est pas converti en pixels (menu Calque > Convertir en pixels, annulable) ; le déplacer entraîne la source.
- **Format natif `.fmps`** : ZIP, `manifest.json` (version 1, document, arbre des calques, clés inconnues gardées), `layers/<id>.png`,
  `masks/<id>.png`, `icc.bin`, `preview.png`. Pas de pixels en JSON. Écriture ATOMIQUE (`.part` + `fsync` + renommage, `.bak`) ;
  version PLUS RÉCENTE refusée (`TooNewError`), jamais ouverte à moitié ; noms d'archive vérifiés (rien n'est extrait sur disque) ;
  PNG de calque non réencodé tant que son plan n'a pas changé (`Plane.png`). Fichier `.fmps` ouvert / exporté depuis la barre du module.
- **Pixels dans le Board** : l'élément `ps_doc` ne porte que `asset` (nom d'empreinte du conteneur dans `<board>_assets/`, même
  cycle de vie que les images : écriture atomique, nettoyage après enregistrement réussi, copie au collage entre boards, suit
  le dossier du board — test « dossier déplacé ») et `init` (document neuf tant qu'aucun conteneur n'existe). `BoardScene.to_data`
  appelle `PsItem.before_save` : le conteneur n'est réécrit que si le document a changé. Ressource absente / illisible : session vide
  avec `error` (affiché sur l'élément, dans le diagnostic) et la référence d'origine N'EST PAS écrasée.
- **Session partagée** : l'élément et l'éditeur Standard affichent la MÊME `Session` (document, historique, outil, brosse, couleurs,
  zoom, position, sélection) et la MÊME `TileCache` ; passer de l'un à l'autre ne recharge, ne copie ni ne recompose rien (test :
  au plus 4 tuiles recalculées au retour). Registre par (jeton de la scène, identifiant de l'élément).
- **Annulation** : l'historique du DOCUMENT est distinct de celui du Board (comme le Tableur) ; il inclut les changements de sélection
  et de structure. Annuler un déplacement de l'élément ne touche pas aux pixels.
- **Règle Ctrl + glisser** : déplacer l'élément dans le Board et déplacer un calque (outil Déplacer) démarrent seulement avec
  Ctrl ; sans Ctrl l'outil dit « Ctrl + glisser ». Main / Espace / molette : vue seulement (pas un déplacement d'élément).
- **Aperçu du déplacement d'un calque** (`movepreview.py`) : base sans le calque + image du calque posée au décalage (mode de
  composition de Qt) ; le modèle est décalé UNE fois au relâchement et le cache recompose le résultat exact. APPROXIMATION
  TEMPORAIRE annoncée : l'aperçu pose le calque au-dessus de ce qui le recouvre dans la pile.
- **Export** : sur un INSTANTANÉ du document (copie des pixels) dans un fil de fond, écriture atomique ; peindre pendant l'export ne
  le change pas (test). Jamais de widget touché depuis un fil.
- **Couleur** : assigner ≠ convertir (`color.py`, LittleCMS de Pillow) ; document sans profil = sRVB (affiché) ; 8 bits seulement.
- **Bibliothèques** : NumPy (BSD) et Pillow (HPND, avec LittleCMS = ICC) déjà requis ; **psd-tools 1.26 (MIT)** ajouté à
  `requirements.txt` (import PSD facultatif : absent, le module le dit clairement) ; OpenImageIO (déjà requis par fm_video)
  UNIQUEMENT dans les tests pour relire les exports avec une bibliothèque indépendante. Écartés : OpenColorIO (pipeline
  d'écran / ACES de fm_video, pas ICC), OpenEXR (flottant : non traité), GPU (non nécessaire aux mesures).

## Formats : ce qui est lu et écrit EXACTEMENT

| Format | Lu | Écrit | Détails |
|---|---|---|---|
| `.fmps` (natif) | oui | oui | tout le document : calques, groupes, masques, modes, opacité, écrêtage, textes / formes éditables, profil, résolution, clés inconnues |
| PNG | oui | oui | RGBA 8 bits, profil ICC et résolution conservés |
| TIFF | oui | oui | RGBA 8 bits, LZW, profil ICC, résolution |
| JPEG | oui | oui | SANS alpha (composé sur un fond, annoncé dans les notes), qualité réglable, profil ICC |
| WebP | oui | oui | alpha ; qualité ou sans perte (`lossless`) |
| BMP | oui | non | |
| PSD | oui | **non** | psd-tools : calques de pixels (position, nom, visibilité, opacité), groupes (traversés ou isolés), 11 modes de fusion, masques de calque (activé, valeur hors cadre), écrêtage ; textes / formes / objets dynamiques importés comme PIXELS ; **non repris et signalé** : calques de réglage, styles, masques vectoriels, modes sans équivalent (remplacés par « normal »), profil ICC, CMJN / Lab / 16-32 bits (convertis) |
| PSB, OpenRaster, 16 bits, flottant | non | non | non commencé |
| Export d'UN calque | PNG / TIFF / JPEG / WebP | — | rendu dans le cadre du document (le format natif refuse un seul calque) |

## État des fonctions

Légende : **Terminé et testé** / **Partiel** / **Non commencé** / **Bloqué**.

| Fonction | Statut | Remarques |
|---|---|---|
| Intégration Board, cadre de la barre des modules, élément, Standard, retour sans perte, plusieurs documents | Terminé et testé | `test_photoshop_board`, `_e2e` ; bouton de la barre : voir « À COMMITER » ci-dessus |
| Créer / importer un document, import comme calque, export PNG / TIFF / JPEG / WebP / natif | Terminé et testé | exports relus par OpenImageIO |
| Enregistrement / réouverture, dossier déplacé, ressource absente, version future | Terminé et testé | |
| Calques : créer, supprimer, dupliquer, ordre (boutons), visibilité, opacité, verrou, groupes, fusionner, aplatir, 10 modes + normal | Terminé et testé | |
| Écrêtage, masques (ajouter, peindre, activer, inverser, appliquer, supprimer, cible pixels / masque) | Terminé et testé | |
| Miniatures de calques (refaites seulement si le plan a changé, 300 ms après le geste) | Terminé et testé | `LayersPanel._thumb` |
| Sélection de PLUSIEURS calques (Ctrl / Maj + clic) : grouper (Ctrl+G), dupliquer, supprimer, déplacer ensemble (une étape) | Terminé et testé | aperçu du déplacement groupé = groupe isolé temporaire |
| Réorganisation des calques par glisser dans la liste | Non commencé | ordre par boutons Monter / Descendre (règle Ctrl + glisser à définir pour la liste) |
| Pinceau rond dur / doux, taille, dureté, opacité, débit, espacement, lissage, pression, pipette, permutation, curseur à taille réelle, gomme, présélections persistantes | Terminé et testé | pression testée en simulant la valeur (`canvas._pressure`) : évènements de stylet réels non testables ici |
| Sélections : rectangle, ellipse, lasso, polygonal, baguette (tolérance, contiguë), plage de couleurs, 4 modes, tout / rien / inverser, adoucir, agrandir, contracter, copier / couper / coller, calque via copier / couper, remplir, effacer | Terminé et testé | « Plage de couleurs » = menu Sélection (couleur de premier plan, tolérance de la baguette) ; agrandir / contracter = octogone |
| Transformation numérique (décalage, échelle, rotation, symétries, qualité), aperçu, annulation | Terminé et testé | |
| Transformation libre avec poignées sur l'établi (Ctrl+T : échelle autour du centre, Maj proportions, rotation, Ctrl + glisser, Entrée / Échap) | Terminé et testé | `freetransform.py` ; aperçu bilinéaire regroupé, validation bicubique ; échelle ancrée au CENTRE (pas au coin opposé) |
| Recadrage (sur la sélection), taille de l'image, taille de la zone de travail (ancrage), symétries du document | Terminé et testé | recadrage = suppression des pixels hors cadre |
| Tampon (source explicite), correcteur (texture), flou, netteté, doigt, densité | Terminé et testé | correcteur ≠ Poisson (documenté) ; échantillonnage sur le calque actif seulement |
| Réglages : luminosité / contraste, niveaux, courbes, exposition, teinte / saturation, balance, N&B, négatif | Terminé et testé | destructifs, aperçu + annuler ; courbes et niveaux : canal maître seulement |
| Réglages NON destructifs (calques de réglage : 8 réglages « rgb », opacité, masque) | Terminé et testé | `compose._apply_adjustment`, `ops.add_adjustment`, `dialogs.AdjustmentLayerDialog` ; pas de filtre de voisinage ni d'écrêtage en calque de réglage |
| Filtres : gaussien, accentuation, bruit | Terminé et testé | |
| Texte et formes éditables, conversion en pixels | Terminé et testé | un seul style par calque de texte |
| Couleur : profil ICC assigner / convertir, alpha préservé, profil dans les exports | Terminé et testé | 8 bits ; 16 bits et flottant : Non commencé |
| Import PSD | Terminé et testé | lecture seule ; PSD en écriture : Non commencé |
| Menus, raccourcis, indicateur « modifié » (barre du Board), diagnostic, réglages du module | Terminé et testé | |
| Menus contextuels (clic droit) de l'établi et de la liste des calques | Terminé et testé | mêmes entrées que les menus de l'éditeur (Édition ou Sélection selon l'état, Calque) |
| Sauvegarde de secours | Partiel | `.bak` pour `.fmps` ; dans le Board, l'ancien conteneur (nom d'empreinte) reste jusqu'au nettoyage après enregistrement réussi ; restauration automatique après plantage : non (le Board enregistre 800 ms après chaque changement) |
| Écriture du conteneur du Board dans un fil de fond | Partiel | `before_save` encode sur le fil de l'interface (seuls les calques modifiés sont réencodés : 4K × 24 calques ≈ 0,6 s) |
| Opacité / visibilité d'un calque : fluidité | Partiel | ~35 ms par cran en 4K × 24 calques (voir Mesures) ; cache des calques inférieurs à faire |

## Tests et référence

- `python tests/run.py fm_photoshop` : 18 fichiers, tous OK (2026-11-01). Chaque fichier commence par `import _isolate`.
  `tests/_photoshop_case.py` : Board réel (`BoardPane`), VRAI chemin (icône de la barre des modules -> bouton de la barre du module ->
  fenêtre « Nouveau document » -> double-clic -> Standard). Piège de test : `QTest` laisse les modificateurs d'un clic tenus pour
  l'application (`release_modifiers`).
- `python tests/run.py fm_board` : 23 fichiers OK AVANT mes crochets (référence initiale) et 23 fichiers OK APRÈS (212 s) ; le groupe
  `fm_board` de `tests/run.py` inclut désormais `test_photoshop*.py` (38 fichiers au total).
- Messages « TypeError: Unknown return type … canUndoChanged / canRedoChanged » imprimés à la création d'un `BoardPane` en test :
  de la coque (`fm_board/ui.py`, PySide6 6.11), sans effet sur les tests, déjà présents sans mon travail.
- Échecs du module `reglages` observés (autre session, travail non commité dans l'arbre de travail, sans rapport avec Photoshop :
  polices du séparateur, décalage de 2 px d'un contrôle, `_settings_dialog_v2` absent, clé « Image » absente, menu de scission de
  tableau) : `test_input_tabs_settings`, `test_interface_edit_scope`, `test_row_templates`, `test_settings_preload`, `test_shadows`,
  `test_table_split`. `test_settings_window_v2` (qui touche mes lignes) : 46 tests OK.

## Mesures (2026-11-01, Windows 11, offscreen, 1 processus)

`tools/bench_photoshop.py` / `tools/probe_photoshop_latency.py`. « 4K » = 3840 × 2160, 24 calques (1 plein cadre + 23 de 1/4 de
surface, alpha 60-255 aléatoire, 4 modes de fusion tournants : cas DÉFAVORABLE), 224 Mo de pixels. « Petit » = 1024 × 768, 4 calques
pleins cadre (13 Mo). Fenêtre d'établi 1600 × 900. Latence = évènement réel + peinture synchrone.

| Mesure | Petit | 4K × 24 |
|---|---|---|
| Composition d'une tuile 256² | 20 ms | 27 ms (248 avant l'optimisation) |
| Composition complète (calcul) | 263 ms | 6,1 s (30,6 s avant) — jamais faite d'un bloc à l'écran |
| Premier affichage complet (zoom 100 %, tuiles par tranches de 25 ms) | 0,3 s | 2,4-2,8 s, progressif |
| Un tampon de brosse (calcul) | 0,43 ms | 0,43 ms |
| Trait : évènement + tuiles recomposées + peinture (médiane / p95) | 3,6 / 6,6 ms | 9,8 / 18 ms |
| Annuler un trait | 0,1 ms | 0,1 ms |
| Déplacer un calque, Ctrl + glisser (médiane / p95) | 1,9 / 2,9 ms | 3,7 / 11 ms (1 014 ms avant l'aperçu) ; ≤ 0,3 s de préparation au début du geste |
| Opacité d'un calque, par cran | 35 ms | 36 ms |
| Afficher / masquer un calque | 33 ms | 35 ms |
| Zoom, un cran de molette | 2,5 ms | 3 ms (tuiles prêtes) ; 80 ms quand de nouvelles tuiles apparaissent |
| Déplacer la vue (médiane / p95) | 1,6 / 2,9 ms | 2,7 / 64 ms (tuiles voisines précalculées pendant les temps morts) |
| Conteneur : 1re écriture / après UN calque modifié / ouverture | 261 / 82 / 60 ms (10 Mo) | 4,3 s / 0,6 s / 1,1 s (202 Mo) |
| Mémoire : pixels des calques / processus | 13 Mo / +16 Mo | 224 Mo / ~740 Mo en fin de sonde (tuiles, copies d'annulation, bancs) |
| « Grand » 8000 × 6000, 8 calques : pixels / processus | — | 528 Mo / ~1,4 Go ; tuile 256² 11 ms ; trait 1,2 ms (p95 2,2) ; conteneur 357 Mo : 1re écriture 8,3 s, après UN calque 1,8 s, ouverture 2,3 s |
| Filtre / réglage en fil de fond | calcul hors du fil de l'interface (aperçu), résultat périmé rejeté | |

Mémoire : le conteneur garde en mémoire les octets PNG encodés de chaque calque (`Plane.png`) pour ne réencoder que ce qui change ;
sur des pixels aléatoires (cas défavorable, incompressible) cela ajoute ~0,7 × la taille des pixels ; sur de vraies images, bien moins.

Pièges trouvés : (1) un tableau NumPy construit par `np.frombuffer(image.constBits())` puis `ascontiguousarray` SANS copie
pointe dans la mémoire du `QImage` libéré -> octets aléatoires (copie obligatoire, `vector._to_rgba`) ; (2) l'Alt d'un `QTest`
reste « tenu » et fait ISOLER un module au clic suivant ; (3) recomposer toute la pile sous un calque déplacé coûte ~1 s en 4K :
d'où `movepreview.py` ; (4) formules de fusion avec divisions : 5× plus lentes que les formules en prémultiplié.

## Limites réelles

- 8 bits par canal uniquement (pas de 16 bits, pas de flottant, pas de CMJN / Lab de travail) ; espace de composition = espace
  encodé du document.
- Pas de PSD en écriture ; l'import PSD ne reprend ni styles, ni réglages, ni masques vectoriels, ni profil.
- Pas d'objets dynamiques ; calques de réglage limités aux réglages « rgb » (pas de flou, netteté, bruit).
- Opacité / visibilité d'un calque : 35 ms par cran dans le pire cas mesuré (pas de cache des calques inférieurs).
- L'écriture du conteneur à l'enregistrement du Board est sur le fil de l'interface (incrémentale par calque).
- Pression de stylet : lue via `tabletEvent` mais jamais testée avec un vrai stylet.
- Un grand zoom arrière dessine les tuiles pleine résolution mises à l'échelle (rapide pendant le geste, lissé ensuite) : pas de pyramide.

## PASSATION

Reprise : lire d'abord cette doc, puis `docs/agents/fm_board.md` (coque) ; les tests du module sont la spécification.
Prochain travail PRÉCIS, par ordre de valeur :
1. FAIT (2e passe) : cache pivot (`TileCache.begin_pivot`) pour l'opacité en direct ; transformation libre ; calques de réglage. Reste pour
   la fluidité : une tuile 256² coûte 5-27 ms selon les calques qui la recouvrent, donc un cran de curseur converge en plusieurs images
   (tuiles en retard affichées en version précédente) ; pistes : tuiles plus petites pendant un réglage, composition en fil de fond
   sur un instantané.
4. **Miniatures de calques** (image réduite gardée par `Plane.rev`), **sélection multiple** de calques (déplacer, grouper, aligner),
   (le menu contextuel existe déjà : il réutilise les menus de l'éditeur).
5. 16 bits (dtype `uint16` dans `Plane`, composition float32 inchangée) puis export TIFF 16 bits ; PSD en écriture (psd-tools sait
   modifier un PSD existant) seulement si une demande l'exige.
6. Commiter les 3 lignes de la barre des modules avec la session qui possède `fm_board/modulebar.py` (voir « Crochets »).

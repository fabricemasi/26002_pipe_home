# Module PDF (`fm_pdf/`) — éditeur PDF intégré (Board + barre de navigation)

Mission de l'utilisateur (2026-11-06) : éditeur PDF professionnel, priorité ABSOLUE aux formulaires XFA (« Please
wait… ») et à la CRÉATION de formulaires AcroForm remplissables dans Acrobat Reader. Suivi de mission, matrice de
compatibilité et rapport : `PDF_MODULE_PROGRESS.md` (racine).

**Tests** : `python tests/run.py fm_pdf` (10 fichiers, ~45 tests, ~16 s ; le Board seul : `python -m unittest
tests.test_pdf_board`, 3 s) ; `--lent` ajoute l'IMM 1344 (XFA, 7 s, éditeur et Board) et l'appli complète
(`test_pdf_app.py`). **Mesures** : `QT_QPA_PLATFORM=windows python tools/probe_pdf_latency.py [rapport.json]`
(éditeur), `tools/probe_pdf_board.py` (élément du Board). **Moteur XFA** : `python tools/install_pdfium_xfa.py [--check]`. **Sonde XFA brute** :
`tools/probe_pdf_xfa.py`. **Contre-vérification Acrobat** (COM, bloquée ici, voir Limites) :
`tools/acrobat_crosscheck.py`.

## Carte : fonctionnalité -> fichier

Couches : sans Qt d'abord (`native` … `content`), puis Qt (`session` et au-delà). Aucun import de la fenêtre
principale (crochets `pane.HOOKS`).

| Fonctionnalité | Fichier | Points d'entrée |
|---|---|---|
| DLL PDFium V8 + XFA (ou standard de pypdfium2), bindings ctypes de pypdfium2 réutilisés | `native.py`, `native/` | `load`, `info`, `xfa_engine_installed`, `PINNED_*` |
| Fil UNIQUE du moteur : priorités, annulation, minuteries de PDFium | `worker.py` | `get_engine`, `Engine.submit / call / open_document / close_document`, `PRIO_*` |
| Document : rendu (tuiles, dans un QImage sans copie), texte, recherche, liens, signets, champs, souris / clavier, enregistrement | `engine.py` | `Document`, `fold`, `PasswordError` |
| Rappels de formulaire + POLITIQUE DE SÉCURITÉ (réseau / fichiers / envoi refusés) | `formfill.py` | `FormHost`, `FIELD_TYPES` |
| Réparation des paquets XFA écrits par PDFium | `xfa_packets.py`, `xfa_save.py` | `undo_pdfium_newlines`, `repair`, `packet_streams` |
| Mise à jour incrémentale (chiffrée RC4 / AES si besoin), correctif `/Type /XRef` | `incremental.py` | `replace_streams`, `repair_xref_stream_type` |
| Conception AcroForm (créer, lire, modifier, supprimer, ordre de tabulation, calculs, formats) | `acroform.py` | `FieldSpec`, `add_fields`, `read_fields`, `update_field`, `delete_fields`, `set_tab_order`, `calc_script` |
| Pages (déplacer, supprimer, pivoter, dupliquer, insérer, fusionner, diviser, extraire, recadrer, numéros, en-tête, filigrane) | `pages.py` | une fonction par opération (octets -> octets) |
| Annotations (balisage, note, texte, dessin, ligne / flèche, formes, tampons, coches ; liste, modification, suppression, aplatissement sur demande) | `annots.py` | `add`, `list_all`, `update`, `delete`, `flatten_annotations` |
| Édition RÉELLE du contenu (objets de page PDFium + `FPDFPage_GenerateContent`) | `content.py` | `objects`, `object_at`, `set_text`, `move`, `resize`, `rotate`, `set_colors`, `add_text / add_image / add_shape`, `restack`, `delete` |
| Caviardage réel vérifié, chiffrement, métadonnées, signatures (visuelle / pyHanko) | `security.py` | `redact`, `verify_redaction`, `encrypt`, `decrypt`, `strip_metadata`, `sign`, `verify`, `self_signed_pkcs12` |
| OCR Windows (Windows.Media.Ocr) + couche texte invisible | `ocr.py` | `available_languages`, `recognize`, `add_text_layer`, `is_scanned` |
| Fichiers : lecture unique, écriture transactionnelle vérifiée, conflit, secours | `fileio.py` | `write_atomic`, `verify_pdf`, `signature`, `write_recovery`, `pending_recovery` |
| Export (images, texte, PDF optimisé, aplati), impression | `exporting.py`, `printing.py` | `export_menu`, `optimize`, `print_dialog` |
| Session Qt : pont vers le moteur, éditions annulables (`edit` octets, `edit_doc` objets), enregistrement | `session.py` | `PdfSession` |
| Cache des tuiles (octets bornés, tuiles périmées gardées à l'écran) | `tiles.py` | `TileCache`, `TILE` |
| Vue : mise en page, zoom, défilement, formulaires interactifs, sélection, recherche, liens, surcouches | `view.py` | `PdfView` |
| Éditeur plein cadre (barres, panneaux, bandeau, modes) | `pane.py` | `PdfPane`, `HOOKS`, `TOOLS` |
| Panneaux : miniatures (Ctrl + glisser), signets, champs, commentaires, infos | `panels.py` | `ThumbsPanel`, `OutlinePanel`, `ListPanel`, `InfoPanel` |
| Mode Conception (surcouche + propriétés) | `designer.py` | `DesignController`, `DesignOverlay`, `PropertiesPanel` |
| Outils Commentaires / Contenu / Protéger / Pages / OCR (Qt) | `annot_tools.py`, `edit_tools.py`, `protect_actions.py`, `page_actions.py`, `ocr_actions.py` | contrôleurs et surcouches |
| Briques d'interface (réglages / fm_theme) | `ui_kit.py` | `button`, `label`, `text_field`, `confirm`, `ask_text`, `choose`, `Table`, `menu` |
| Board : type `pdf_doc` (lien, ajustement, zoom, défilement), élément (aperçu de TOUTES les pages, édition sur place), contrôleur + barres « PDF », « Document », « Affichage » | `board_model.py`, `board_item.py`, `board_ui.py` | `PdfItem`, `layout_pages`, `PdfBoardController` (`make_live`, `sync_bar`) |
| Board : UN document par élément (session ouverte une fois, JS + XFA ; aperçu ET édition), images de pages de l'aperçu, confirmation à la fermeture | `board_docs.py` | `DocEntry`, `entry_for`, `confirm_leave`, `save` |
| Board : document vivant DANS l'élément (QGraphicsProxyWidget `EMBEDDED`), raccourcis, plein écran | `board_live.py` | `LiveDoc`, `EmbeddedPdf` |
| Réglages (catalogue, défauts) | `settings.py`, `settings_defaults.py` | `PDF_TAB`, `PDF_TREE`, `PDF_DEFAULTS` |

Crochets HORS du paquet (minimaux) :
- Fenêtre principale : `main_window/pdf_module.py` (`PdfModuleMixin` : `_open_pdf`, `_close_pdf`, `_leave_pdf`,
  `_toggle_pdf`, `_layout_pdf_buttons`, `_pdf_claims`), `pipeline_browser.py` (mixin, `btn_pdf`, `closeEvent`),
  `main_window/title_bar.py` (`pdf_group`), `chrome.py` (bouton de mode), `module_targets.py` (« Ouvrir dans
  l'éditeur PDF »), `viewer.py` (double-clic sur un .pdf, avant la visionneuse), `font_module.py` / `md_module.py` /
  `board_module.py` / `video_module.py` (`_leave_pdf`), `settings_link.py` (chemin rapide des clés `pdf_`),
  `preview_column.py` (glyphe « pdf »).
- Board : `fm_board/ui.py` (`MODULES`, glyphe, `set_module` / `toggle_cad`, `_place_chrome`, `self.pdf`,
  `confirm_leave` -> `PdfBoardController.confirm_leave` / `board_docs.confirm_leave`),
  `modulebar.py` / `scene.py` (`MODULE_NAMES`, `MODULES`, enregistrement du type), `model.py` (défauts, normalisation),
  `settings.py` / `settings_defaults.py` (couleur du module).
- Réglages : `settings_store.py` (`DEFAULT_SETTINGS.update(PDF_DEFAULTS)`), `settings_window_v2.py` (onglet
  « Module PDF », `MODULE_SCOPES["pdf"]` et dans « board »), `tests/test_settings_window_v2.py` (listes d'onglets).

## Décisions

- MOTEUR : PDFium compilé avec V8 + XFA (pdfium-binaries, chromium/8076, même révision que les bindings de
  pypdfium2 5.14.0 ; empreinte SHA-256 vérifiée = celle publiée par GitHub). Seul moteur libre qui exécute XFA
  dynamique (mise en page, scripts JS / FormCalc). Le correctif V8 de pdfium-binaries initialise lui-même V8, la
  plateforme et le tas XFA dans `FPDF_InitLibraryWithConfig`. Repli : DLL standard (XFA signalé non pris en charge).
- UN fil pour PDFium (V8 lié au fil, PDFium non réentrant) ; ctypes rend le GIL : rendu parallèle à l'interface.
- Écriture : PyMuPDF (AGPL, usage personnel) pour AcroForm / annotations / pages / caviardage ; pikepdf (qpdf) pour
  la structure et les mises à jour incrémentales ; pyHanko pour les signatures ; OCR intégré à Windows.
- Éditions structurelles = instantané des octets + document rouvert (annuler = rouvrir l'instantané, pile bornée à
  400 Mo) ; la saisie dans un champ s'annule dans PDFium (FORM_Undo).
- Enregistrement : incrémental si signatures ou XFA (droits d'usage /Perms préservés), sinon complet ; écriture
  temporaire + fsync + relecture qpdf + os.replace ; fichier modifié ailleurs = « Garder ma version / Enregistrer
  sous / Recharger ».
- Sécurité : JavaScript des formulaires exécuté (calculs, validations, XFA) mais AUCUN accès réseau / fichier /
  courriel / envoi (rappels refusés et listés dans Infos) ; liens externes : http(s) / mailto seulement, avec accord.
- Règles de l'appli suivies : Échap n'ouvre ni ne ferme jamais le module ; réorganisation des pages au Ctrl +
  glisser ; styles = briques des réglages (ui_kit) ; réglages appliqués à chaud (seul ce qui a changé).
- BOARD (demande de l'utilisateur, 2026-11-06 : « je veux que le document apparaisse et qu'il soit modifiable quand
  le module est actif, avec toutes ses pages et avec sa barre des outils ; dans la barre d'outils une option plein
  écran ; les options pleine page, pleine largeur ») :
  - UN document par élément (`board_docs.DocEntry`, registre (jeton de la scène, identifiant)) ouvert UNE fois avec
    JavaScript et XFA, à la première peinture ; il sert à l'APERÇU et à l'ÉDITION (activer = rien à rouvrir, l'aperçu
    montre les saisies non enregistrées). Fermé avec la scène.
  - APERÇU = toutes les pages en défilement continu, à l'ajustement / zoom / défilement retenus dans l'élément
    (`fit`, `zoom`, `scroll` en points, `page` : ceux de la dernière édition, enregistrés dans le .brd), même mise en
    page que la vue (`layout_pages`) : rien ne bouge entre aperçu et édition. Images de pages entières à une largeur
    arrondie à la puissance de 2 (≤ 2 fois trop grande), 192 Mo au plus, priorité « miniatures ».
  - ÉDITION SUR PLACE : module PDF actif, un clic dans le document (double-clic : active le module) pose la vue du
    module (`PdfView`, continu, barres de défilement masquées comme l'aperçu) dans l'élément par un
    `QGraphicsProxyWidget` marqué `EMBEDDED` (mécanisme du Tableur : souris, molette, clavier lui reviennent ;
    Ctrl + molette = zoom du Board). Un seul document édité à la fois ; clic ailleurs = le clavier le quitte, il reste
    éditable ; module quitté = retour à l'aperçu (endroit retenu). Ctrl + S enregistre le FICHIER LIÉ (vérifié,
    conflit « Garder ma version / Recharger »), Ctrl + Z / Y, F11.
  - Barres (fm_theme) : « PDF » (insérer, nouveau, éditeur plein cadre), « Document » (Remplir, Main, Annuler,
    Rétablir, Enregistrer en accent si modifié), « Affichage » (zoom, Pleine page, Pleine largeur, Plein écran, pages).
    Une disposition enregistrée avant (seulement « PDF ») reçoit les nouveaux boutons dans sa première barre.
  - PLEIN ÉCRAN : le MÊME widget quitte l'élément et recouvre tout le Board, la fenêtre passe en plein écran (état
    d'avant rendu : maximisée reste maximisée) ; Échap (rien d'autre à annuler), F11 ou le bouton en sortent, à la
    même page. Le Board fermé en plein écran rend l'état de la fenêtre.
  - SEULEMENT LES PAGES (capture annotée de l'utilisateur, 2026-11-06 : « pas d'en-tête », « pas de fond, je veux
    uniquement les pages », « le fond doit être le fond du board ») : plus de barre de titre rouge (`TITLE_H` = 0)
    ni de fond gris, en aperçu comme en édition (`PdfView.set_transparent` : fond, viewport et feuille de style
    transparents) ; autour et entre les pages, le Board. Sélection = celle de tous les éléments (`paint_selection`).
    Nom, page / pages, « modifié » : infobulle de l'élément. En attendant le document : une page blanche qui le dit.
    Plein écran : la COULEUR du fond du Board (`scene.background`, pas les éléments qui seraient derrière).
  - « PLEINE PAGE » (barre du module, Ctrl+0 ; demande du même jour : « recentrer la page en cours de manière à
    remplir l'écran ») : une page entière dans l'élément (`LiveDoc.fit_page`), puis la vue du Board recadrée sur la
    page EN COURS (`PdfBoardController._fit_page_screen` → `BoardView.fit_rect`, page de la vue embarquée ramenée
    dans la scène par le proxy). « PLEINE LARGEUR » (même jour : « mettre le document en pleine largeur à
    l'écran ») : pleine largeur dans l'élément, puis la largeur de la page remplit l'écran, le haut de la page en
    cours en haut de l'écran (`_fit_width_screen` → `BoardView.fit_width_rect`). Les menus contextuels « Pleine
    page » / « Pleine largeur » de l'élément ne font que l'ajustement dans l'élément.
  - CADRE AIMANTÉ AU DOCUMENT (capture annotée, même jour : « le cadre bleu doit se snapper au document ») : en
    redimensionnant l'élément dans le Board, le bord tiré colle au bas d'une page / à la largeur du contenu
    (`PdfItem.snap_document_sizes`, appelé par `BoardScene.snap_resize` ; guide « Cadre sur son document » de
    Réglages > Module MRO > Magnétisme ; détail : `docs/agents/fm_board.md`, RÉGLAGES). Test `FrameOnDocumentTest`.
  - BORD À BORD (capture annotée, même jour : « pas d'écart entre le bord de la page et le cadre ») : dans le Board,
    aucune marge autour des pages (`board_item.MARGIN` / `PAD` = 0, posés sur la vue : `PdfView.margin`,
    `fit_pad` ; ailleurs la vue garde 16 pt et 2 px) ; seul l'écart ENTRE deux pages reste (12 pt) ; aller à une page
    la met au bord haut. Un PDF inséré a le cadre de sa page (`fit_size(page)`, `framed` vrai) ; un élément posé
    avant (marges, titre : un vide sous la page) est recalé UNE fois sur sa première page en pleine largeur à
    l'ouverture de son document (`PdfItem.fit_frame_once`, `framed` ; largeur et coin haut gauche gardés). Test
    `test_pages_touch_the_frame_and_old_frames_are_fitted_once`.
  - Fermeture du Board : chaque document modifié demande Enregistrer / Ne pas enregistrer / Annuler. L'éditeur plein
    cadre ouvert sur un document modifié dans le Board : enregistrement demandé d'abord ; à sa fermeture, les
    documents de ce fichier (non modifiés) sont rouverts s'il a changé.

## Pièges (tous mesurés, corrigés)

1. PDFium ajoute « \n » après chaque balise des paquets XFA qu'il réécrit (`datasets`, `form`) : valeurs rouvertes
   préfixées d'un saut de ligne (listes en valeur brute, dates rejetées, légendes décalées) -> `xfa_packets`.
2. Sauvegarde incrémentale PDFium d'un fichier à flux de références : flux SANS `/Type /XRef` (qpdf le refuse) ->
   `incremental.repair_xref_stream_type`.
3. Mise en page XFA différée : le 1er évènement passe l'IMM 1344 de 10 à 14 pages et périme les pages chargées
   (clics sans effet) -> `_settle_xfa` + rechargement après FFI_PageEvent.
4. Repère XFA ≠ repère PDF : toujours FPDF_DeviceToPage / PageToDevice (sinon zones de clic en miroir).
5. XFA : la frappe ne remplace pas la sélection -> FORM_ReplaceSelection ; le caret XFA est dessiné par PDFium.
6. AFSimple_Calculate de PDFium lit « 12,5 » comme 12 -> calculs par AFMakeNumber (même résultat dans Acrobat).
7. Recherche PDFium sans repliement de casse des accents -> recherche Python alignée sur les indices de PDFium.
8. PyMuPDF `xref_set_key(…, "null")` écrit « /Clé null » (lu comme valeur) -> `pdf_dict_dels` ; radios regroupés.
9. Image d'accueil créée avec int() et page rendue avec round() : pas mémoire trop étroit, rendu refusé -> tuile
   EXPLICITE (0, 0, largeur, hauteur) partout où l'on rend dans un QImage.
10. Clic sans survol préalable : focus de formulaire inconnu, la frappe n'apparaissait qu'au clignotement du caret
    (~500 ms mesurés) -> le moteur confirme le champ dans la tâche du clic (`_pending_focus`).
11. Tâches annulées : leur rappel restait dans la session (fuite, attente infinie) -> `Job.on_cancel`.
12. Éditeur fermé : ~21 Mo d'images par éditeur restaient -> `PdfPane.shutdown` vide les caches (0,6 Mo / cycle).
13. Tests : `QTest.keyClicks("é")` fait tomber PySide6 6.11 ; `QTest.mouseMove` n'atteint pas un widget enfant hors
    écran ; destructions différées à exécuter avant la fin du processus (`sendPostedEvents(DeferredDelete)`).
14. pyHanko : `load_pkcs12_data(données, other_certs, passphrase)` (2e argument = autres certificats).
15. Signature (signalé par l'utilisateur, 2026-11-06 : « pas réussi, je ne comprends pas le fonctionnement ») : la
    dernière étape attendait un RECTANGLE glissé et ne l'annonçait que dans la ligne d'état ; un simple clic ne
    faisait rien. Désormais : bandeau de consigne, un clic pose la signature en taille standard (180 × 54 pt), Échap
    annule, fenêtre finale qui explique « validité inconnue » d'un certificat auto-signé dans Acrobat. Test
    `test_digital_signature_by_a_simple_click` (vrai clic Qt).
16. Board (signalé par l'utilisateur, 2026-11-06, imm5707f de l'IRCC : « Please wait… », une seule page) : l'aperçu
    ouvrait le fichier SANS JavaScript ; PDFium ne charge le XFA qu'avec la plateforme JS (sonde : IMM 1344 = 1 page
    de repli sans, 14 pages avec). Et chaque largeur d'aperçu ROUVRAIT le document (7 s pour l'IMM 1344). ->
    `board_docs` (un document par élément, JS + XFA). Tests `test_xfa_preview_is_the_real_form_not_the_fallback_page`,
    `test_ircc_xfa_shows_all_its_pages_in_the_board` (lent).
17. Vue embarquée dans le Board : peinte par le proxy à l'échelle du Board -> tuiles floues au zoom et, à 400 %,
    TOUTE la surface de l'élément rendue en haute résolution. -> `PdfView.render_scale` (zoom du Board par 1/8
    d'octave, rendu net 120 ms après le dernier cran) et `clip_to_exposed` (tuiles et préchargement limités à la zone
    exposée : le proxy ne peint que la partie visible). Hors Board : inchangé (échelle 1, tout le viewport).
18. Tab dans un champ embarqué : arrive bien au widget (QGraphicsProxyWidget le transmet) ; un filtre de scène essayé
    d'abord était inutile (retiré, vérifié par le test sans lui).

## Mesures (2026-11-06, Windows 11, vraie fenêtre 1600 × 1000, `tools/probe_pdf_latency.py`)

| Mesure | Valeur |
|---|---|
| Ouverture 300 pages de texte / premier rendu net | 196 ms / 291 ms (moteur 21 ms) |
| Changement de page jusqu'au rendu net (médiane / pire) | 79 / 85 ms (miniature floue avant les tuiles) |
| Image de défilement (médiane / pire) | 5,6 / 11,7 ms |
| Cran de zoom (image) / net après le dernier cran | 13,4 ms / 192 ms |
| Frappe AcroForm : touche -> champ redessiné | 506 -> **11,5 ms** (pire 16,5) |
| Frappe XFA ACIA / IMM 1344 | 296 -> **29 ms** / 602 -> **45 ms** |
| Ouverture XFA ACIA / IMM 1344 | 87 ms / 8,6 s (dont 6,3 s dans `FPDF_LoadXFA`, fil du moteur) |
| Mémoire : 40 ouvertures moteur AcroForm / XFA | +10,7 / +18,5 Mo ; éditeur : 21 -> 0,64 Mo par cycle |

Board (2026-11-06, vraie fenêtre 1600 × 1000, `QT_QPA_PLATFORM=windows python tools/probe_pdf_board.py [rapport]`) :

| Mesure (AcroForm / 300 pages / XFA ACIA / IMM 1344) | Valeur |
|---|---|
| Ouverture du document de l'élément -> aperçu peint | 107 / 77 / 144 ms / 9,1 s (dont 6,8 s d'ouverture XFA, fil du moteur, interface libre) |
| Clic (module actif) -> édition sur place / tuiles nettes | 9-11 ms / 27-70 ms |
| Image du Board (pan, peinture), aperçu -> document édité | 2,6-7,7 -> 3,5-8,4 ms (médianes) |
| Cran de zoom du Board avec document édité / net après | 3,8-8,7 ms / 9-66 ms |
| Frappe dans un champ embarqué (touche -> champ redessiné à l'écran) | AcroForm 17,6 ms ; XFA ACIA 22 ms ; IMM 1344 27 ms |
| Pleine page / pleine largeur (clic -> net, dont la pause de 120 ms) | 122-137 ms |
| Plein écran (clic -> net ; l'image étirée est montrée tout de suite) / retour | 86-318 ms / 27-51 ms |

## Limites réelles

- Acrobat : compatibilité VÉRIFIÉE À LA MAIN par l'utilisateur le 2026-11-06 (AcroForm créé et rempli par le
  module, XFA de l'ACIA rempli et enregistré par le module : « ça marche »). Pas de vérification automatique :
  l'automatisation COM d'Acrobat est refusée sur cette machine (`AcroExch.App` : E_NOINTERFACE), l'accès à Acrobat
  par pilotage d'écran aussi ; `tools/acrobat_crosscheck.py` reste prêt.
- XFA : pas de couche texte (recherche, sélection) ; conception XFA non prise en charge (AcroForm pour les
  nouveaux formulaires) ; pages, commentaires et contenu refusés sur un XFA (comme Acrobat) ; XFA statique (XFAF) non
  testé faute de fichier ; ouverture lourde d'un gros formulaire (PDFium).
- Signatures : révocation non vérifiée (pas de réseau) ; PAdES de base (pas d'horodatage).
- Export DOCX et PDF/A : non proposés (aucune conversion / validation fiable intégrée).
- Édition de texte : une police incorporée en sous-ensemble est remplacée EXPLICITEMENT par une police standard
  (signalé) ; pas de réagencement de paragraphe (objet par objet).

## PASSATION

Board, 2026-11-06 : document affiché et ÉDITÉ dans l'élément (toutes les pages, XFA réel), barres « Document » et
« Affichage » (pleine page, pleine largeur, plein écran) ; `tests/test_pdf_board.py` (7 rapides + 1 lent IMM 1344).
RETRAIT PRÉVU, PAS ENCORE (demande de l'utilisateur, 2026-11-06 : « j'aimerais bien pouvoir supprimer le second
panneau que tu as créé, par la suite mais pas dans l'immédiat » ; CONFIRMÉ : il s'agit de l'éditeur PDF PLEIN CADRE
posé au-dessus du Board). Il RESTE tant que l'utilisateur ne demande pas son retrait. Ce qui en dépend côté Board
(à retirer ensemble le jour venu) : bouton « Éditeur PDF » de la barre « PDF » (`open_selected`),
`PdfBoardController.open_editor` / `close_editor` / `self.editor`, `PdfItem.open_editor`, « Nouveau formulaire »
(ouvre l'éditeur en Conception : il faudra un autre chemin vers la conception AcroForm), sa partie de `place` et
de `confirm_leave`, et le test `test_module_item_preview_editor_and_reload`. Le `PdfPane` lui-même sert aussi aux
colonnes (barre de navigation) : NE PAS le supprimer.
Non fait au Board : réglages « pdf_ » changés pendant une édition appliqués au document édité (repris à la
prochaine édition) ; recherche ; outils Conception / Commentaires / Pages / Protéger (éditeur plein cadre).

État : module livré et intégré (colonnes + Board), 40 tests rapides + 2 lents verts. Pistes : test XFA statique,
ajout / suppression de sections XFA par bouton (pagination dynamique), recherche dans les valeurs XFA (paquet
datasets), barres flottantes fm_theme pour l'éditeur plein cadre (aujourd'hui barres fixes), tampons d'horodatage
pour les signatures.

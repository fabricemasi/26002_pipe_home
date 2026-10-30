# Module Tableur (`fm_tableur/`)

Quatrième module du Board (après Miro, CAD, Design), créé le 2026-10-30 (mission autonome de l'utilisateur :
« un véritable tableur, moteur de calcul, compatibilité Excel, Board + mode Standard comme fm_markdown »).

**Tests du module** : `python tests/run.py fm_tableur` (~6 s ; aussi dans `fm_board`).
**Sonde de fluidité** : `python tests/_probe_tableur.py [cellules]` (défaut 100 000).
**Matrice des fonctions** : `python tools/tableur_functions.py` -> `docs/agents/fm_tableur_fonctions.md` +
`fm_tableur/fonctions_verifiees.txt` (à relancer après une mise à jour de formualizer).
Règle d'isolation : le paquet n'importe jamais `pipeline_browser.py` ; le cœur (sans Qt) n'importe aucun Qt.

## Carte : fonctionnalité -> fichiers (à ouvrir directement)

Cœur SANS Qt (testable seul) :

| Fonctionnalité | Fichier | Contenu |
|---|---|---|
| Références A1, plages, réécriture des formules (copie, insertion / suppression, feuilles, couper) | `refs.py` | `iter_refs`, `translate`, `shift_insert`, `shift_delete`, `move_refs`, `rename_sheet`, `remove_sheet` |
| Formats de nombres d'Excel (sections, dates, %, E+, fractions, couleurs, conditions), séries de dates | `numfmt.py` | `format_value`, `Locale`, `serial_to_datetime`, `change_decimals`, `PRESETS` |
| Saisie typée, erreurs, texte d'édition, valeurs du moteur | `values.py` | `parse_input`, `XLError`, `edit_text`, `from_engine` |
| Modèle : classeur, feuilles, cellules éparses, styles internés, axes (tailles, masquage, styles de ligne / colonne) | `document.py` | `Workbook`, `Sheet`, `Cell`, `StyleTable`, `Axis` |
| Moteur de calcul (formualizer) : lots, noms définis, débordements, formule hors cellule | `engine.py` | `CalcEngine`, `cell_value`, `check_formula`, `expand_names` |
| Fonctions absentes de formualizer ajoutées (MMULT, MINVERSE, MDETERM, MUNIT, FVSCHEDULE, DISC, INTRATE) | `extra_functions.py` | `register`, `FUNCTIONS` |
| Commandes annulables, pile d'annulation du DOCUMENT | `commands.py` | `SetCells`, `SheetState`, `Lines`, `SheetsCommand`, `Names`, `UndoStack` |
| Opérations (saisie, styles, bordures, copier / coller, recopie, tri, filtre, fusion, feuilles, rechercher, doublons, convertir) | `ops.py` | une fonction = une étape d'annulation |
| Tableaux structurés : définition, noms de colonnes, traduction des références structurées pour le moteur | `structured.py` | `resolve`, `iter_structured`, `columns`, `at`, `STYLES`, `rename_column_refs` |
| Opérations sur les tableaux (créer, convertir, renommer, style, totaux, extension auto, colonne calculée) | `tables_ops.py` | `create`, `convert_to_range`, `rename`, `toggle_totals`, `after_input`, `header_renamed` |
| Filtres automatiques : feuille ET chaque tableau (portées, critères, lignes masquées) | `filters.py` | `scopes`, `scope_at`, `values`, `apply`, `clear`, `set_table_buttons` |
| Format natif (JSON dans l'élément du `.mro`) | `io_native.py` | `to_dict`, `from_dict` |
| Excel .xlsx / .xlsm (openpyxl) : import, export, préfixes `_xlfn.`, contrôle de l'archive | `io_xlsx.py` | `read`, `write`, `check_archive`, `unsupported_parts` |
| Graphiques d'un fichier Excel (XML `xl/charts/`, qu'openpyxl ne lit pas) -> graphiques liés | `io_xlsx_charts.py` | `read_charts` |
| CSV / TSV | `io_csv.py` | `read`, `write` |
| Session partagée Board / Standard (document + moteur + annulation + navigation) | `session.py` | `Session`, `obtain`, `SheetView` |
| Élément « sheet » du `.mro` (défauts, normalisation) | `board_model.py` | `DEFAULTS`, `normalize_entity` |
| Catalogue des fonctions (« Insérer une fonction ») | `functions.py` + `fonctions_verifiees.txt` | `catalog` |
| Formules en français à l'écran (`=SOMME(A1;B2)`, virgule décimale), anglais dans le classeur | `formula_lang.py` | `to_local`, `to_english`, `FR` |
| Défauts des réglages `tableur_*` (fusionnés dans `DEFAULT_SETTINGS` par `settings_store`) | `settings_defaults.py` | `TABLEUR_DEFAULTS` |
| Réglages (onglet « Tableur » de « Réglages : Board » : Ouverture, Nouveaux classeurs, Saisie, Formules et nombres, Couleurs) | `settings.py` | `TABLEUR_TAB`, `TABLEUR_TREE` |
| Police et mode de calcul des NOUVEAUX classeurs (posés par `BoardPane.apply_settings` ; un fichier ouvert garde les siens) | `document.py` ; `io_native.from_dict` (classeur vide -> `new_workbook`) | `NEW_BOOK`, `set_new_book_defaults` |

Qt :

| Fonctionnalité | Fichier | Contenu |
|---|---|---|
| Peinture des cellules (grille ET aperçu du Board), cache d'affichage, plans de dessin | `render.py` | `paint_cells`, `DisplayCache`, `visible_span`, `LOOK` |
| Mise en forme conditionnelle (évaluée à la peinture) | `condfmt.py` | `Evaluator`, `TYPES` |
| Grille : géométrie, volets figés, défilement par décalage, peinture, éditeur de cellule | `grid.py` | `GridWidget`, `CellEditor` |
| Souris / clavier d'Excel, poignée de recopie, pointage des références, presse-papiers | `grid_input.py` | `GridInput`, `data_edge` |
| Classeur complet : barre de formule, onglets, barre d'état, recherche, menus, commandes | `widget.py` | `SpreadsheetWidget`, `SheetTabs`, `FindBar` |
| Ruban (Accueil, Insertion, Formules, Données, Affichage) | `ribbon.py` | `Ribbon` |
| Graphiques liés aux données (peinture, calque déplaçable, export Excel) | `charts.py` | `paint_chart`, `ChartLayer`, `export_charts` |
| Import / export depuis l'interface (feuilles ajoutées, une étape d'annulation) | `io_files.py` | `load`, `merge_book`, `import_into`, `export_to` |
| Élément du Board : aperçu, édition sur place, Ctrl + glisser, mode Standard | `board_item.py` | `SheetItem`, `_Embedded` |
| Module dans le sélecteur du Board (barre : nouveau, importer, mode Standard) | `board_ui.py` | `TableurController` |
| Mode Standard plein cadre (même session) ; Enregistrer / Exporter | `standard.py` | `StandardPane` |
| Classeur ouvert depuis l'explorateur (board en mémoire + mode Standard, enregistrement prudent) | `files_mode.py` | `read_as_board`, `attach`, `save`, `leave` |

Crochets dans la COQUE (modifications minimales, Miro / CAD / Design inchangés) :
- `fm_board/model.py` : `DEFAULTS` reçoit « sheet », `normalize_item` -> `board_model.normalize_entity`,
  `ICON_ROWS` (« tableur »).
- `fm_board/scene.py` : `MODULES` + « tableur » ; import de `fm_tableur.board_item` (enregistre le type).
- `fm_board/view.py` : widgets EMBARQUÉS (`_embedded_at`, `_end_embedded`) : un `QGraphicsProxyWidget` marqué
  `EMBEDDED` reçoit souris / double-clic / molette par Qt ; clic ailleurs = fin de son édition
  (`scene.embedded_item.stop_edit()`) ; le clavier passe déjà par `editing_text()` (le proxy a `editing()`).
- `fm_board/ui.py` : `MODULES` (bouton Tableur), `set_module` / `toggle_cad` (modules exclusifs), `_place_chrome`,
  `paint_glyph` (genre « tableur »), `confirm_leave` (`import_leave_hook` : classeur ouvert depuis l'explorateur).

Crochets dans la FENÊTRE PRINCIPALE (fm_tableur ne l'importe jamais) : `main_window/board_module.py`
(`_is_spreadsheet`, `_open_spreadsheet` : lecture dans un fil à part comme un dessin DXF, puis `_open_board(…,
imported=…)` + `files_mode.attach`), `_toggle_board` (bouton « board » de la barre sur un .xlsx / .csv),
`main_window/chrome.py` (bouton actif sur un classeur), `main_window/viewer.py` (`on_activated` : double-clic si
`tableur_open_double_click`, faux par défaut : Excel reste le logiciel du double-clic), `settings_store.py`
(`TABLEUR_DEFAULTS`).

## Décisions (2026-10-30)

- **Moteur : formualizer 0.13** (Rust, MIT / Apache-2.0, roue Windows, `requirements.txt`), après essais
  (sondes de session) : PMT / IRR / XIRR / XNPV justes, LET, FILTER, SEQUENCE, débordements, cycles (#CIRC!),
  modification + recalcul INCRÉMENTAL (~0,4 ms, 10 000 formules dépendantes ~9 ms), lecture ~0,3 µs.
  Écartés : `formulas` (lourd : numpy + schedula, pas d'incrémental), `pycel` (GPL), `xlcalculator` (couverture
  faible), moteur écrit à la main (des centaines de fonctions à refaire). openpyxl ne CALCULE rien.
- **Le modèle est la source de vérité**, le moteur un miroir (`push` puis `recalc`). Limites de formualizer
  contournées dans `engine.py` : pas de suppression / renommage de feuille ni d'insertion de lignes (moteur
  reconstruit, ou cellules réécrites), pas de noms définis (développés dans la formule envoyée), débordement non
  recalculé quand un obstacle apparaît / disparaît (formules à débordement reposées, `_DYNAMIC`), écriture cellule
  par cellule lente (LOTS par bandes de 512 lignes, `_write`). `LAMBDA(x,…)(4)` appelé directement : #N/IMPL.
- **Formules en syntaxe d'Excel anglaise DANS le classeur** (celle des .xlsx : `=SUM(A1:B2)`, virgules) ; À
  L'ÉCRAN en français par défaut (`tableur_formula_lang` = « fr » : `=SOMME(A1:B2;2,5)`, comme Excel en
  français ; ~170 fonctions traduites, les autres gardent leur nom anglais) ; à la saisie, noms français OU
  anglais acceptés. Piège : en français, `=SUM(1,2)` tapé = SOMME(1,2) = 1,2 (comme Excel en français).
- **Format interne = JSON natif**, pas le .xlsx : sans perte pour le module, rapide (100 000 cellules ~0,1 s,
  gardé tant que rien ne change), clés inconnues gardées ; valeur calculée rangée avec chaque formule.
- **Cellules immuables** ; **pile d'annulation du DOCUMENT** (`commands.UndoStack`), distincte de celle du
  Board : déplacer / redimensionner l'élément = Board ; saisir = classeur (comme un texte édité sur place). Annuler
  un déplacement du Board ne touche pas au classeur (`SheetItem.apply` garde le classeur en cours).
- **Grille peinte** (`QAbstractScrollArea`), pas `QTableView` : débordement du texte, volets, fusions, bordures,
  poignée, surlignage des références, et le MÊME peintre pour l'aperçu dans le Board.
- **Board** : élément « sheet » ; hors édition un aperçu (là où l'on travaillait) ; double-clic = édition sur
  place (classeur complet embarqué) ; Échap / clic ailleurs = fin ; ⤢ = mode Standard. Déplacer = Ctrl + glisser
  (règle de l'appli, comme Design) ; graphiques dans la grille : Ctrl + glisser aussi ; onglets de feuilles :
  Ctrl + glisser. Les gestes de grille d'Excel (sélection, glisser une plage, poignée de recopie) restent sans Ctrl.
- **Mode Standard** (sur le modèle de fm_markdown : le module recouvre la zone de travail, une barre, un bouton
  de retour) : `StandardPane`, enfant du `BoardPane`, même session que l'élément ; rien n'est rechargé ni
  recalculé ; Ctrl+S enregistre le board. Un .xlsx / .csv de l'explorateur s'ouvre AUSSI directement en mode
  Standard (bouton « board » de la barre sur le fichier choisi, ou double-clic si le réglage est mis) : board en
  mémoire ; « Enregistrer » ne remplace l'original qu'après confirmation, si l'import n'a rien perdu, avec une
  copie `.bak` ; sinon « Enregistrer sous » ; fermeture d'un classeur modifié = enregistrer / garder en .mro /
  fermer sans enregistrer / annuler.
- **Tableaux structurés** (2026-10-30, demande de l'utilisateur) : Ctrl+T / Ctrl+L, Insertion > Tableau, menu
  contextuel « Tableau » (renommer, style, ligne des totaux, bandes, sélectionner, convertir en plage). Le module
  TRADUIT lui-même les références structurées en plages A1 avant le moteur (`structured.resolve`) : formualizer
  0.13 ne sait ni `T[[#Data],[Col]]` (#N/IMPL), ni `[@Col]`, ni le nom seul, ni redimensionner / supprimer un
  tableau. Le texte d'Excel reste dans le classeur. Comme Excel : extension automatique (saisie juste sous / à
  droite), colonne calculée (formule recopiée sur la colonne vide, et sur chaque ligne ajoutée), entête renommée =
  formules réécrites (`header_renamed`), lignes insérées dans le tableau = tableau agrandi, mots-clés français
  acceptés (`#En-têtes`, `#Données`, `#Totaux`, `#Tout`, `#Cette ligne`). Noms de colonnes = textes des entêtes
  (vide : « Colonne<n> », doublon suffixé). Fichier .xlsx : `[@Col]` écrit sous la forme longue
  `T[[#This Row],[Col]]` (`to_file_syntax`), colonnes du tableau écrites explicitement (sinon Excel « répare »).
  Fluidité (tableau de 10 000 lignes, colonne calculée) : saisie sous le tableau 932 -> ~45 ms (formules
  « ligne courante » non retraduites quand seule la taille change, `row_only` ; noms de colonnes gardés par
  cellules d'entête, `columns`) ; renommer une entête ~0,95 s (10 000 formules réécrites puis renvoyées au moteur).
  Piège : une mémoire indexée sur `book.revision` rendait les ANCIENS noms au milieu d'une étape d'annulation (la
  révision ne change qu'à la fin) : indexée sur les objets des cellules d'entête (immuables).
- **Filtres des tableaux** (2026-10-30, demande de l'utilisateur) : chaque tableau a ses boutons de filtre dans son
  entête (comme Excel, actifs à la création ; menu « Tableau » > masquer / afficher les boutons), en plus du filtre
  de la feuille ; même mécanique (`filters.py` : une PORTÉE = entête, lignes de données sans la ligne des totaux,
  colonnes, critères). Critères d'un tableau rangés par POSITION dans le tableau (`table["filters"]`, clés « 0 »,
  « 1 »…) : ils suivent le tableau déplacé. Menu du bouton : trier A → Z / Z → A (données du tableau seulement),
  effacer le filtre de la colonne, effacer tous les filtres, cases des valeurs affichées. Bandes calculées sur les
  lignes VISIBLES (Excel). Excel : `autoFilter` du tableau et critères « liste de valeurs » (vides compris) lus et
  écrits, aussi pour le filtre de la feuille ; les filtres personnalisés / par couleur / top 10 d'un fichier ne sont
  pas repris (le masquage des lignes, lui, l'est).
- **Styles de tableau, trois familles comme Excel** (2026-10-30, demande de l'utilisateur ; `structured.STYLES`,
  menu « Tableau » > Style > Clair / Moyen / Foncé) : Clair = filets de couleur sous l'entête et en bas, bandes
  claires, entête en gras (TableStyleLight 1, 2, 3, 4, 5, 7) ; Moyen = entête colorée, texte blanc
  (TableStyleMedium 2, 3, 4, 5, 7 ; les anciennes clés « bleu »… n'ont pas changé) ; Foncé = entête noire, données
  sur fond de couleur en texte blanc, totaux noirs (TableStyleDark 1, 2, 3, 4, 5, 7) ; « Aucun ». Un style d'un
  fichier Excel que le module ne sait pas peindre exactement (ex. TableStyleMedium15) est AFFICHÉ avec le plus
  proche de sa famille (`style_from_excel`) et RÉÉCRIT TEL QUEL à l'export (`table["excel_style"]`, effacé quand
  l'utilisateur choisit un autre style).
- **Poignée de redimensionnement** (coin en bas à droite de chaque tableau, `grid_input.table_handle_at`,
  `tables_ops.resize_to`) : tirer à la souris, sans Ctrl (ce n'est pas un déplacement), aperçu en pointillés ; le
  coin en haut à gauche ne bouge pas ; nouvelles colonnes nommées « Colonne<n> » ; la ligne des totaux suit le bas ;
  les données sorties du tableau restent dans la feuille (Excel) ; chevauchement d'un autre tableau ou d'une
  fusion refusé (message) ; une étape d'annulation. La poignée de recopie de la sélection passe AVANT celle du
  tableau quand les deux coins coïncident (choisir une autre cellule pour tirer la poignée du tableau).
- **Ruban** : rangée de commandes dans une zone qui DÉFILE horizontalement (fenêtre étroite) ; jamais écrasée
  (piège : la mise en page rétrécissait les boutons sous leur taille utile, « G » devenait « : »).
- **Colonne élargie** quand un NOMBRE saisi n'y tient pas et que sa largeur est celle par défaut (Excel) ; une
  largeur choisie n'est jamais touchée ; même étape d'annulation que la saisie.
- **Contenu à l'aspect d'Excel** (fond blanc, quadrillage gris), comme le contenu du Board suit Miro ; chrome
  (ruban, barres, menus) = briques de l'appli (`_TextButton`, `settings_menu.Menu`, `FontPicker`, `_SwatchGrid`).
- **Erreurs jamais masquées** : #DIV/0!, #VALUE!, #REF!, #NAME?, #NUM!, #N/A, #SPILL!, #CIRC! (référence
  circulaire, au lieu du 0 d'Excel), #N/IMPL ; formule non valable refusée à la saisie (message, l'édition reste).
- **Sécurité** : jamais d'`eval` ; archive .xlsx contrôlée (2 Go décompressés, taux de compression, nombre de
  parties) ; macros jamais exécutées ni gardées (signalé) ; liens externes non suivis (valeurs en cache) ; calcul
  borné (`MAX_EVAL_MS`) ; CSV ≤ 512 Mo. L'import ne modifie jamais le fichier lu ; l'export écrit un NOUVEAU
  fichier (atomique `.part` puis remplacement).

## Compatibilité Excel (réelle, vérifiée par les tests)

- Import / export .xlsx : feuilles (ordre, noms, masquées, couleur d'onglet), valeurs typées, formules (préfixes
  `_xlfn.` / `_xlws.` retirés / remis), styles (police, couleur, fond uni, alignements, retour à la ligne, retrait,
  bordures, format, verrouillage), tailles, masquage, fusions, volets, quadrillage, zoom, noms globaux,
  commentaires, listes déroulantes, filtre automatique (plage), tableaux structurés (nom, plage, entêtes, totaux,
  styles Clair / Moyen / Foncé, style inconnu gardé tel quel, bandes ; références structurées), mises en forme conditionnelles courantes,
  protection, graphiques du module (vrais graphiques Excel + définitions gardées dans les propriétés
  personnalisées pour la réimport). Excel recalcule tout à l'ouverture (`fullCalcOnLoad`).
- Graphiques d'un fichier Excel RELUS (`io_xlsx_charts`) : histogrammes / barres, courbes, aires, secteurs
  (anneaux en secteurs), nuages, combinés barres + courbes, si leurs séries sont contiguës ; sinon signalés.
- Perdu, SIGNALÉ : macros, images / formes, graphiques aux séries non contiguës, tableaux croisés, segments,
  liens externes, sparklines, contrôles, mises en forme conditionnelles non reconnues ;
  styles de lignes / colonnes entières (seulement les cellules remplies à l'export). Formules à débordement :
  Excel peut les afficher avec « @ » (openpyxl n'écrit pas les métadonnées des tableaux dynamiques).
- `.xls` / `.xlsb` : refusés avec un message (enregistrer en .xlsx depuis Excel).
- Ouverture du fichier exporté dans Microsoft Excel : NON vérifiée ici (Excel absent de la machine de test) ;
  vérifié : relu par openpyxl et par l'import du module.

## Mesures (sonde, hors écran, 2400 x 1300, 2026-10-30)

100 000 cellules dont 10 000 formules : moteur construit 0,7 s (2,4 s avant les lots) ; saisie d'une cellule
0,2-0,4 ms ; saisie dont dépendent 10 000 formules ~9 ms ; insertion d'une ligne en haut ~1,2 s (moteur
reconstruit au-delà de 40 000 cellules touchées) ; sérialisation native ~0,1 s (puis gardée : 0,004 ms) ;
relecture ~0,9 s ; export .xlsx ~1,6 s, import ~1,6 s. Grille : peinture complète ~11-16 ms ; molette (3 lignes,
image décalée, bande peinte) ~3,5 ms ; flèche ~2 ms (région exacte) ; changement de feuille ~10 ms ; seconde
présentation de la même session (mode Standard) ~21 ms. Pièges trouvés : `QAbstractScrollArea.scrollContentsBy`
repeint tout (neutralisé) ; décalage d'image seulement si le viewport est OPAQUE ; `QRect.united` = rectangle
englobant (une région `QRegion` pour la sélection) ; texte : `QStaticText` + plan gardé par cellule
(38 -> 12 ms la peinture complète).

## Tests

- `tests/test_tableur_engine.py` (36) : références, formats, saisie, moteur avec valeurs de RÉFÉRENCE
  indépendantes du code (exemples publiés par Microsoft pour PMT, FV, PV, NPV, IRR, RATE, XNPV, XIRR, STDEV, VAR,
  NETWORKDAYS, WORKDAY, DATEDIF, textes), recalcul, cycles, feuilles, lignes, noms, mode manuel, annulation,
  copier / couper, recopie, tri, filtre, fusion, rechercher, format natif.
- `tests/test_tableur_ui.py` (17) : clavier / souris de la grille, pointage, poignée, presse-papiers, barre de
  formule, feuilles, peinture < 50 ms, aller-retour Excel (fichier écrit par openpyxl -> modifié -> exporté ->
  relu -> comparé), éléments non repris signalés, archive malformée / bombe refusées, CSV à la française.
- `tests/test_tableur_tables.py` (18) : styles Clair / Moyen / Foncé, style d'Excel inconnu conservé, poignée
  (à la souris, colonnes ajoutées, totaux qui suivent, chevauchement refusé, annulation) ; filtres des tableaux (critères, ET, effacer, boutons, annulation,
  déplacement du tableau, filtre de la feuille, aller-retour Excel, clic sur le bouton dans la grille) ; traduction de toute la syntaxe, mots-clés français, échappements,
  recalcul quand le tableau change, extension, colonne calculée, totaux, renommer (tableau / entête), insertion
  de lignes, convertir en plage, annulation, format natif, aller-retour Excel, Ctrl+T.
- `tests/test_tableur_board.py` (11) : sélecteur, griser / masquer, Ctrl pour déplacer, édition sur place,
  clavier gardé par le classeur, enregistrement / réouverture, annulation du Board sans perte, mode Standard sur la
  même session, ancien fichier et champs inconnus gardés, classeur de l'explorateur (original intact, `.bak`).

## Reste (plan de travail, par priorité)

1. FAIT : classeur de l'explorateur en mode Standard (voir Décisions).
2. FAIT : formules en français (`formula_lang.py`).
3. FAIT (onglet « Tableur » de Réglages : Board, `fm_tableur/settings.py`, appliqué en direct ; avant : section
   de l'onglet Module MRO) : ouverture au double-clic, langue des formules, séparateurs, ordre des dates, noms des
   jours, Entrée, couleurs du contenu, police / taille et mode de calcul des nouveaux classeurs (« » = Calibri).
4. EN PARTIE : 7 fonctions ajoutées (`extra_functions.py`, matrice : 385 / 423 présentes) ; restent les
   fonctions obligataires (COUP*, PRICE*, ODD*…), LAMBDA appliquée, BYROW / MAP…, REGEX*, AREAS.
5. FAIT : graphiques d'un fichier Excel relus ; tableaux structurés (voir Décisions).
6. Insertion de lignes sur très gros classeurs (~1,2 s pour 100 000 cellules) : moteur en tâche de fond ?

## PASSATION

- 2026-10-30 — FAIT et commité : étape 1 (cœur sans Qt), étape 2 (grille, classeur, Excel / CSV, graphiques,
  mise en forme conditionnelle), étape 3 (intégration Board + mode Standard + optimisations de fluidité).
- 2026-10-30 — FAIT : classeur de l'explorateur en mode Standard (`files_mode.py` + crochets de la fenêtre),
  formules en français.
- 2026-10-30 — FAIT : réglages « Tableur », 7 fonctions ajoutées, graphiques d'Excel relus, ruban défilant
  (boutons jamais écrasés), colonne élargie pour un nombre saisi (comme Excel).
- 2026-10-30 — FAIT : tableaux structurés (création, références structurées traduites, extension, colonne
  calculée, totaux, renommer, convertir, import / export Excel), `tests/test_tableur_tables.py`.
- Fonctions obligataires : écartées pour l'instant par l'utilisateur (2026-10-30).
- 2026-10-30 — FAIT : filtres des tableaux (`filters.py`), bandes sur lignes visibles.
- 2026-10-30 — FAIT : styles Clair / Foncé des tableaux, poignée de redimensionnement.
- 2026-10-30 — FAIT : onglet « Tableur » de Réglages : Board (police et calcul des nouveaux classeurs).
- Prochaine action : vérifier l'ouverture des fichiers exportés dans
  Microsoft Excel (non disponible ici).

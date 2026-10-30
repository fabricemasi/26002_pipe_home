# Module Tableur (`fm_tableur/`)

Quatrième module du Board (après Miro, CAD, Design), créé le 2026-10-30 (mission autonome de l'utilisateur :
« un véritable tableur, moteur de calcul, compatibilité Excel, Board + mode Standard comme fm_markdown »).

**Tests du module** : `python tests/run.py fm_tableur` (aussi dans `fm_board`).
Règle d'isolation : le paquet n'importe jamais `pipeline_browser.py` ; le cœur (sans Qt) n'importe aucun Qt.

## Carte : fonctionnalité -> fichiers (à ouvrir directement)

| Fonctionnalité | Fichier | Contenu |
|---|---|---|
| Références A1, plages, réécriture des formules (copie, insertion / suppression, feuilles, couper) | `refs.py` | `iter_refs`, `translate`, `shift_insert`, `shift_delete`, `move_refs`, `rename_sheet`, `remove_sheet` |
| Formats de nombres d'Excel (sections, dates, %, E+, fractions, couleurs), séries de dates | `numfmt.py` | `format_value`, `Locale`, `serial_to_datetime`, `change_decimals`, `PRESETS` |
| Saisie typée, erreurs, texte d'édition, valeurs du moteur | `values.py` | `parse_input`, `XLError`, `edit_text`, `from_engine` |
| Modèle : classeur, feuilles, cellules éparses, styles internés, axes | `document.py` | `Workbook`, `Sheet`, `Cell`, `StyleTable`, `Axis` |
| Moteur de calcul (formualizer), noms définis, débordements | `engine.py` | `CalcEngine`, `cell_value`, `check_formula`, `expand_names` |
| Commandes annulables, pile d'annulation du DOCUMENT | `commands.py` | `SetCells`, `SheetState`, `Lines`, `SheetsCommand`, `Names`, `UndoStack` |
| Opérations (saisie, styles, bordures, copier / coller, recopie, tri, filtre, fusion, feuilles, rechercher) | `ops.py` | une fonction = une étape d'annulation |
| Format natif (JSON dans l'élément du `.mro`) | `io_native.py` | `to_dict`, `from_dict` |
| Session partagée Board / Standard (document + moteur + annulation + navigation) | `session.py` | `Session`, `obtain`, `SheetView` |

## Décisions (2026-10-30)

- **Moteur : formualizer 0.13** (Rust, MIT / Apache-2.0, roue Windows, `requirements.txt`), après essais
  (sondes de session) : PMT / IRR / XIRR / XNPV justes, LET, FILTER, SEQUENCE, débordements, cycles (#CIRC!),
  20 000 formules en chaîne évaluées en 39 ms, modification + recalcul INCRÉMENTAL 0,4 ms (2 000 formules),
  lecture d'une valeur ~0,3 µs. Écartés : `formulas` (lourd : numpy + schedula, pas d'incrémental), `pycel`
  (GPL), `xlcalculator` (couverture faible), moteur écrit à la main (des centaines de fonctions à refaire).
  openpyxl ne CALCULE rien : il sert seulement à lire / écrire les fichiers.
- **Le modèle est la source de vérité**, le moteur un miroir : chaque commande pousse ses cellules (`push`), puis
  `recalc` (mode automatique). Limites de formualizer contournées dans `engine.py` : pas de suppression /
  renommage de feuille (moteur reconstruit), pas de noms définis (développés dans la formule envoyée),
  débordement non recalculé quand un obstacle apparaît / disparaît (formules à débordement reposées à chaque
  modification de leur feuille, `_DYNAMIC`). `LAMBDA(x,…)(4)` appelé directement : #N/IMPL (moteur).
- **Formules en syntaxe d'Excel anglaise** (celle des .xlsx : `=SUM(A1:B2)`, virgules). Saisie en français
  (`=SOMME(A1;B2)`) : PAS ENCORE (voir « Reste »).
- **Format interne = JSON natif**, pas le .xlsx (voir `io_native.py`) : sans perte pour le module, rapide, clés
  inconnues gardées.
- **Cellules immuables** : une commande garde les anciennes sans copie ; une opération de structure garde la table
  de la feuille (copie de surface).
- **Pile d'annulation du DOCUMENT** (`commands.UndoStack`), distincte de celle du Board : un déplacement de
  l'élément dans le Board est annulé par le Board, une saisie par le classeur (comme un texte édité sur place).
- Erreurs jamais masquées : #DIV/0!, #VALUE!, #REF!, #NAME?, #NUM!, #N/A, #SPILL!, #CIRC! (référence circulaire,
  affichée au lieu du 0 d'Excel), #N/IMPL (fonction non implémentée par le moteur).

## Tests

`tests/test_tableur_engine.py` (36 tests, ~0,2 s) : valeurs de RÉFÉRENCE indépendantes du code (exemples publiés
dans l'aide de Microsoft Excel pour PMT, FV, PV, NPV, IRR, RATE, XNPV, XIRR, STDEV, VAR, NETWORKDAYS, WORKDAY,
DATEDIF, textes ; calculs à la main ailleurs).

## Reste (plan de travail)

Voir la PASSATION en fin de fichier.

## PASSATION

- 2026-10-30, étape 1 (cœur sans Qt) : FAITE — modèle, moteur, commandes, opérations, format natif, tests.
- Prochaine action : grille Qt (`render.py`, `grid.py`, `widget.py`), puis intégration au Board et mode Standard.

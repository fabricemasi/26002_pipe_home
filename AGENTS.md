# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet

Pipeline Browser : navigateur de fichiers en colonnes (Miller columns) en PySide6, pour une arborescence de projets de production (racine par défaut `F:\PIPELINE`, réglable via `root_path` dans `data/pipeline_settings.json`). Application Windows (DPI per-monitor, attributs « caché » Windows, chemins `.exe`) ; le code et les commentaires sont en français. Le dépôt est édité depuis WSL mais l'appli tourne sous Windows.

## Commandes

- Lancer : `pipeline_browser_debug.bat` (crée `.venv`, installe PySide6/ezdxf/matplotlib, lance l'appli) ou `python pipeline_browser.py` (`pythonw` pour éviter la console).
- Dépendances : `requirements.txt` (PySide6 ; optionnels : OpenEXR, numpy, ezdxf, matplotlib).
- Tests (unittest, offscreen Qt, certains exigent Blender installé) :
  - tous : `python -m unittest discover -s tests`
  - un fichier : `python -m unittest discover -s tests -p test_turntable.py`
  - un test : `python -m unittest tests.test_render_log.RenderLogTest.test_requested_columns_and_render_metadata` (lancer depuis la racine ; les tests importent `previews`, `detail_panel`… : patcher un nom dans le module qui l'utilise, pas dans celui qui l'a importé).
- Pas de linter ni de build configuré.
- `.venv/` est ignoré par git (ne pas l'éditer).

## Architecture

Modules plats à la racine (aucun package), en couches : chaque module n'importe que ceux qui le précèdent (les imports tardifs `import browser_core as pb_core` dans `settings_*` évitent le cycle).

Application (ordre de dépendance) :
- `config.py` : constantes (extensions, listes d'omission `GLOBAL_OMIT_*`) ; `ui_state.py` : réglages d'interface **réassignés à l'exécution** (`WINDOW_RADIUS`, `HEADER_HEIGHT`, `STEP_BADGE_STYLE`…). Ils se lisent toujours via `ui_state.X` (jamais `from ui_state import X`, qui figerait la valeur).
- `previews.py` : décodeurs d'aperçus, caches mémoire/disque, rendus Blender/Maya, ordonnanceur de fond, journal de rendu.
- `browser_core.py` : scan disque, config projet/layout/raccourcis, helpers de peinture/redimensionnement.
- `row_delegates.py` (`RowDelegate`, `ProjectTileDelegate`), `column_config.py` (dialogue de configuration des colonnes), `capture_widgets.py` (capture, `_PreviewBlock`, `_ColumnCard`…), `column.py` (`Column`), `preview_column.py` (`PreviewColumn`, export PureRef), `detail_panel.py` (`DetailPanel`, inspecteur).
- `focus.py` : état « focus » (se concentrer sur un objet : aperçu image/turntable pour l'instant, d'autres types à venir) ; `FocusOverlay` anime l'objet de l'inspecteur au centre quand on masque les colonnes. Tout le nouveau code de cet état va ici.
- `pipeline_browser.py` : `IconButton`, `TitleBar`, `PipelineBrowser(QMainWindow)`, `apply_all_settings`, `main()` (`load_settings()` → `apply_all_settings()` → `QApplication` → `apply_style()` → fenêtre). Point d'entrée.

Fenêtre de réglages (ordre de dépendance) : `settings_store.py` (palette `M`, `DEFAULT_SETTINGS`, `load/save_settings`, presets), `settings_theme.py` (rôles de texte, arrondis communs), `settings_widgets.py` (champs de base : `_Toggle`, `_MiniSlider`, `_FontSelectField`…), `settings_colorpicker.py`, `settings_layout.py` (sections/tableaux), `settings_sections.py` (registre des champs, polices/couleurs/entêtes/géométrie), `settings_window.py` (`SettingsWindow`).

`app_style.py` : tokens de style (couleurs, polices par rôle) et `build_stylesheet()`/`apply_style()`.

Les données propres à l'appli sont dans `data/` (réglages, presets, état des fenêtres, cache d'aperçus, icônes de logiciels) ; `files/` contient les modèles Blender et profils de rendu, `icons/` les SVG de l'interface.

### Réglages
`DEFAULT_SETTINGS` (settings_store.py) est la source de vérité : `load_settings` fusionne `data/pipeline_settings.json` par-dessus et ignore les clés inconnues — toute nouvelle clé doit donc y être déclarée. `apply_all_settings()` (pipeline_browser.py) est le point d'entrée unique qui recopie les réglages dans des globals/tokens ; il n'a d'effet visible qu'avec un refresh derrière (`refresh_all_columns`, `refresh_colors`…, cf. `PipelineBrowser._apply_settings`). Presets : `data/pipeline_settings.presets.json`.

### Configuration par projet/dossier (JSON cachés à la racine des dossiers)
`.pipeline_columns.json` (étapes/colonnes d'un projet, `load/save_project_columns`), `.pipeline_layout.json` (`load/save_layout_settings`), `.pipeline_shortcuts.json` (raccourcis), `.pipeline_protected_previews.json`. Ces fichiers sont versionnés ici car le dépôt contient une copie de travail ; les écritures utilisent `_set_hidden` (attribut caché Windows).

### Pipeline d'aperçus
Aperçus asynchrones : `_PreviewDecodeManager` / `_PreviewDecodeTask` (QRunnable), `_IdlePreviewScheduler` (rendu en tâche de fond quand l'appli est inactive). Cache disque dans `data/.pipeline_preview_cache/` (clé = chemin + mtime ; métadonnées, nettoyage des caches périmés). Décodeurs par format : OBJ (numpy/QPainter ou Blender EEVEE), Alembic `.abc` et `.blend` (Blender), `.ma` (mayapy), PSD, EXR/HDR/TX (OpenEXR / oiiotool), vidéo, DWG (ezdxf + ODA File Converter). Les rendus Blender/Maya sont des **scripts Python embarqués dans des chaînes** exécutés en sous-processus (voir `_render_wireframe_eevee`, `_render_ma_wireframe`) — ce code s'exécute dans l'interpréteur de Blender/Maya, pas dans l'appli. Les profils de rendu (low/high…, turntable) viennent de `files/parametres rendus.txt` (`_load_render_profiles`) ; journal de rendu quotidien `pipeline_preview_render_<date>.html` / `.log`.
Les fichiers du cache ont un nom explicite `<set>__<fichier>__<code16>_<mtime>.png` (set = jusqu'à 3 dossiers sous la racine, voir `_cache_label`) ; turntables `<set>__<fichier>__turntable_<code16>`. `migrate_cache_names()` (appelée par `main()`) renomme les anciens noms opaques.

Outils externes détectés dynamiquement : `BLENDER_EXECUTABLE`, `MAYA_PYTHON_EXECUTABLE`/`MAYA_LOCATION`, `ODA_FILE_CONVERTER`, `oiiotool` dans le PATH. Tous optionnels : l'appli doit rester fonctionnelle sans (fichiers simplement sans aperçu).

`tools/` : scripts autonomes de conversion/validation Alembic (`convert_legacy_alembic.py`, `validate_alembic_blender.py`).

### Animations des colonnes
- Overlays dans `browser_core.py` : `_FadeOverlay` (fondu d'un instantané, avec `retarget`/`finish_now`) et `_SlideOverlay` (repli/dépli glissant des colonnes du projet) ; `_fine_timer` (timer Windows haute résolution) et `_HoverPrime` (pré-chauffe au survol).
- Orchestration dans `PipelineBrowser` (`pipeline_browser.py`) : `_set_columns_hidden` / `_apply_project_columns_collapsed` (masquage et repli, animés ou non), `_animate_column_in` (apparition par dessous, fondu échelonné), `_fade_before_select` (fondu de l'ancien contenu à la sélection).
- Principe : on anime un **instantané** (`grab`) plutôt que les vrais widgets ; les instantanés sont pré-calculés (`_prewarm_snapshots`, `_prime_*`) et validés (`_snapshot_blank`, `_fade_snapshot_fresh`). L'état final réel est toujours posé par `*_now` / `finish_now` : toute nouvelle animation doit finir par là pour ne pas laisser l'UI dans un état intermédiaire.
- Tester « une animation est en cours » avec `_anim_running(overlay)` (pipeline_browser.py), jamais `overlay.running` seul (un overlay détruit sans finir garderait `running` vrai et bloquerait tout). Les fins d'overlay (`_finish`/`_complete`) sont en try/finally : l'overlay disparaît même si un rappel lève une erreur. Un clic pendant un glissement le termine (`finish_now`) au lieu d'abandonner le fondu. Stress : `tests/_probe_anim_stress.py` (clics rapides, repli, masquage ; vérifie qu'aucun overlay ne reste et compte les fondus sautés).
- À surveiller : un `retarget` ou un clic pendant une animation doit terminer/rediriger l'overlay en cours (sinon colonnes fantômes) ; instantané obsolète ou vide après changement de réglages/taille (re-prime) ; `_install_qt_message_filter` masque certains avertissements Qt, à vérifier si un vrai message disparaît.
- Fenêtres natives : `main()` pose `AA_DontCreateNativeWidgetSiblings`. Sans lui, le `winId()` d'une fenêtre enfant (`apply_dwm_frame` des réglages) rendait `#CentralFrame` natif et les animations ne s'affichaient plus qu'en une image. Ne jamais appeler `winId()` sur un widget non fenêtre. Mesure de ce qui s'affiche réellement à l'écran : `tests/_probe_screen_anim.py` (compte les images par repli/dépli, réglages fermés/ouverts).
- `files/parametres rendus.txt` : le chemin HDRI pointe maintenant vers `F:\SYNC\Sync\IMAGES\hdri\` (chemin propre à la machine, à adapter ailleurs).

## Réutilisation de la fenêtre de réglages (intention)

La fenêtre de réglages (surtout la fenêtre « Paramètres généraux », mode `general`, et ses briques : `settings_widgets.py`, `settings_layout.py`, `settings_theme.py`, `settings_colorpicker.py`, gabarits de `over/Notes.txt`) servira de **point de départ aux fenêtres de réglages des futures applications** de l'utilisateur : on copiera ces modules dans la nouvelle appli puis on les fera évoluer là-bas (pas de paquet partagé pour l'instant). Conséquences, à respecter dès maintenant :
- Garder le moteur (widgets, sections, tableaux, rôles de texte, arrondis, construction de haut en bas, réutilisation de la fenêtre) **séparé des réglages propres à Pipeline Browser** (colonnes, étapes, logiciels, aperçus, racine de projets).
- Ne pas ajouter de nouvelle dépendance de `settings_*` vers du code propre à l'appli (`browser_core`, `column`, `previews`…) ; passer par des paramètres, des signaux ou un module de réglages dédié.
- Pour un nouveau réglage, déclarer clé, type, défaut et libellé de façon générique plutôt que de coder la clé en dur dans la logique commune.
- Quand l'utilisateur démarre une nouvelle appli à partir de cette fenêtre : demander le chemin de ce projet, copier ce qui est utile, retirer les sections propres à Pipeline Browser, et noter l'origine de la fenêtre dans l'`AGENTS.md` de la nouvelle appli. Réfléchir à la structure de la nouvelle appli (couches, modules) avant de coder.

## Conventions du projet

`over/Notes.txt` définit des **gabarits** pour les lignes de la fenêtre de réglages, à appliquer à toute ligne existante ou future du même type sans que l'utilisateur le répète :
- Lignes *police* : une seule ligne ; toggles app/système sans texte, collés au menu déroulant ; toggle « gras » avec le texte « gras » avant (les deux états) ; texte « Hauteur » avant le slider.
- Lignes *arrondi des angles* : une ligne, pas de bouton copier, toggle « lier les 4 » (texte avant, les deux états), 4 sliders avec champ de saisie, valeur mise à jour en temps réel.
- Lignes *bordures* : pas de bouton copier, toggle « lier les 4 », 4 toggles chacun au-dessus du choix de couleur de son côté.
Styles de la fenêtre de réglages — une seule source par type d'élément, jamais de style posé à la main :
- Textes : un **rôle** (`TEXT_ROLES` dans `settings_theme.py`, appliqué par `_set_text_role` / `_text_label`). Changer l'apparence d'un type de texte = modifier son rôle, pas les sites d'appel.
- Arrondis des zones de saisie et des boutons : chaque widget s'inscrit à sa création (`_register_input` / `_register_radius`) et suit le réglage tout seul. Un nouveau widget habillé en zone de saisie doit s'inscrire ; ne jamais tenir de liste de champs à mettre à jour.
- Tableaux : tous ont un entête (`_ResizableTableHeader` : sélection de colonnes Maj+clic, toggle « largeurs égales »). `_build_flat_table` / `_build_override_flat_table` ajoutent eux-mêmes l'entête Paramètre|Valeur (`_attach_flat_head`) et s'inscrivent (`_register_flat_table`) ; les tableaux à cellules (Icônes, Logiciels) passent par `_register_cells_table`. Arrondi, bordure, padding et couleur d'entête passent par `_set_flat_tables_style` / `_TABLE_HEAD`.
- Dimensions : la bordure droite de chaque `_TableFrame` est agrippable (largeur du tableau, collé à gauche au niveau du titre) ; largeur du tableau + largeurs de colonnes sont enregistrées dans `table_dims` (clé = titres des sections + rang, voir `_TableFrame.dimsKey`).
- Vérification : `tests/test_settings_window.py` (aller-retour des valeurs, suivi des styles) et `tests/_probe_compare.sh` (captures de toutes les pages avant/après, comparées au pixel ; `tests/_probe_diff.py` localise les différences).

Lire `over/Notes.txt` en entier avant de modifier la fenêtre de réglages (`over/Prompts.txt` contient l'historique des demandes).

## Fenêtre de réglages v2 (`settings_window_v2.py`, `settings_cells.py`)

Règles à appliquer à tout tableau de la v2, actuel et futur, sans que l'utilisateur le répète :
- **Tout tableau a un entête** (`build_cells_table`, `_ResizableTableHeader`). Les tableaux Paramètre|Valeur et à colonnes passent par `settings_cells.build_cells_table` (cellules `_Cell`).
- **Toggles de tableau : type 2, sans texte** (« actif »/« sans », « gras », « italique », « lier les 4 »… sont remplacés par la légende de la colonne ou de la sous-cellule). `normalize_toggles` l'impose après construction. Ne plus mettre de texte avec un toggle, sauf demande expresse.
- **Lignes « Padding »** : cellule divisée `lier les 4 | G | H | B | D` (`_f_padding`).
- **Lignes « Bordures »** : cellule divisée `lier les 4 | G | H | B | D | épaisseur` (toggle du côté au-dessus de sa couleur ; pas d'épaisseur quand la ligne n'en a pas) (`_f_sides`, `_f_sides_thick`).
- **Lignes « Border radius »** (toutes les lignes d'arrondi des coins s'appellent ainsi) : cellule divisée `lier les 4 | HG | HD | BD | BG` (`_f_corners` ; les 4 coins, pas des côtés).
- **Lignes « police »** : cellule divisée `police | gras | italique | hauteur | niveau de lissage | couleur`, avec les champs de référence de la v1 (Titre > Polices) ; le tableau Titre > Polices reproduit exactement celui de la v1 (`COLUMN_TABLES`).
- **Champs de référence** à reprendre tels quels : police (`_DualFontSelectField`), gras/italique (`_Toggle` type 2), lissage (`_OverrideSmoothingField`, sans titre), slider (`_SliderField`, cf. Titre > Retraits > Valeur), couleur (`_CompactAppOrCustomColorField`).
- Une cellule divisée = `_split_field(champ_existant, parts)` : on réutilise les widgets du champ (valeurs, signaux, lecteur inchangés), seul l'habillage change.
- Clic droit sur une cellule : justification horizontale (gauche/centre/droite) et verticale (haut/centre/bas) ; clic droit sur un curseur : modifier sa plage (`slider_ranges`, enregistrée aussitôt). Toute bordure de colonne se tire aussi sur les cellules des lignes (`_CellEdgeDrag`), pas seulement sur l'entête.
- **Enregistrement en temps réel** (sans valider, `AUTOSAVE`) : taille/position de la fenêtre (`pipeline_settings_window_state.json`, clé `v2`), `table_dims` (largeurs de tableau/colonnes, justifications, largeurs des sous-cellules) et `slider_ranges`. Un nouvel élément redimensionnable doit passer par `_TableFrame.dimsChanged` / `collectDims` / `applyDims` (`frame._extra_dims` pour ce qui sort des largeurs de colonnes).
- **Justifications individuelles** : chaque cellule a la sienne, et chaque sous-cellule d'une cellule divisée aussi (clic droit sur celle-ci, jamais une justification commune à toute la cellule).
- **Cellules divisées** : la cellule englobante n'a pas de padding (elle va de filet à filet), mais le CONTENU de chaque sous-cellule reçoit le même padding que les cellules normales (`SplitCell.setContentPadding`, appelé par `cell_padding`). Elles restent **toujours accessibles** : ne JAMAIS poser `WA_TransparentForMouseEvents` sur un widget qui contient des contrôles (l'attribut vaut aussi pour ses enfants et les rend inertes). Les bords se saisissent par un filtre d'événements (`SplitCell.eventFilter`) ou sur la bande de légendes. `test_controls_of_split_cells_are_reachable` le vérifie.
- **Dimensionnement vertical** : la bordure basse de chaque ligne se tire (`_RowHeights`, jamais plus petite que le contenu) ; clic droit sur l'entête d'un tableau = « Lignes : hauteurs égales » (`equal_rows`). Les deux sont enregistrés (`row_heights`, `equal_rows`).
- **TOUT ce qui se dimensionne ou se règle à la souris s'enregistre en temps réel et se retrouve à la réouverture** : largeurs de tableau/colonnes/sous-cellules, hauteurs de lignes, justifications, options de tableau (hauteurs égales), plages des sliders (`slider_ranges`), taille/position de la fenêtre. Tout nouvel élément de ce genre doit entrer dans `collectDims`/`applyDims` (ou `_autosave`) ET dans `RoundTripTest` (`tests/test_settings_cells.py`).
- **Accordéon** : déplier un titre replie ses frères, sauf Ctrl (`_make_accordion` branché sur les `_LazyNode` frères, sections et sous-sections). Un nouveau niveau d'imbrication doit le rebrancher.
- **Titre > Espacements** est identique à celui de la v1 (Niveau | Titre replié | Titre déplié | Avec le niveau suivant) ; Titre > Polices aussi (`COLUMN_TABLES`).
- **Styles de toggle** : registre dynamique (`_TOGGLE_STYLES`, `_toggle_style_dict`) ; clic droit sur la cellule Toggles > Style > « Ajouter un nouveau toggle… » crée `toggleN` (réglages `toggleN_*` copiés du Toggle 1, clé `toggle_custom_styles`, conservés au chargement par `_DYNAMIC_KEY`) et sa sous-section Toggles > <nom> (Cadre + Coche). Coche > « Habillage » : aucun / texte (police de référence) / icône (fichier de `icons/`, avec aperçu et couleur) dessiné dans la coche (`_paint_coche_skin`). Un nouveau réglage de toggle doit exister pour TOUS les styles (`_toggle_specs`, `_sync_toggle_shape_style`, DEFAULT_SETTINGS pour toggle1/toggle2).
- Les filets verticaux sont repeints après chaque passe de layout (`_TableRow.event`, `_ResizableTableHeader.event`, `SplitCell.event`) : Qt ne repeint que le rectangle des cellules déplacées, pas le filet situé entre deux. Ne pas retirer.
- Les **presets** ne sont pas recréés en v2 : à repenser avec l'utilisateur avant (celui de la v1 ne lui plaît pas).
- **Alignement** : de façon générale, les éléments s'alignent entre eux, sur l'axe vertical comme sur l'axe horizontal (ex. l'axe d'un toggle doit coïncider avec celui du cadre de couleur situé en dessous). Vérifier l'alignement des centres à chaque nouvelle cellule.
- **Éléments grisés** : couleur d'origine à 20 % d'opacité (valeur réglable : entrée « éléments grisés » avec curseur de pourcentage à prévoir dans la section Couleurs).
- **État enregistré en temps réel** (`table_dims`, `slider_ranges`, `toggle_custom_styles`, clés `toggleN_*`) : `load_settings` le réapplique APRÈS le preset par défaut (`_LIVE_STATE_KEYS`), sinon le preset l'écrase à chaque ouverture. Toute nouvelle clé de ce genre y entre (test `PresetDoesNotClobberLiveStateTest`).
- **Sélection d'entêtes = largeur commune** : plus de toggle « largeurs égales » dans les entêtes. Cliquer un titre de colonne (Maj = ajouter) ou une légende de cellule divisée la sélectionne ; tirer la bordure d'une colonne sélectionnée (≥ 2) impose EXACTEMENT la même largeur à toutes, en temps réel. Même comportement pour `_ResizableTableHeader` et `SplitCell`.
- **Largeur affichée** : pendant un redimensionnement (colonne de tableau ou sous-cellule), le titre des colonnes concernées affiche « N px » (restauré au relâchement).
- **Déplacer une colonne** : tirer son titre (après 6 px) la fait suivre le curseur (colonne entière, translucide) avec tous les emplacements possibles marqués et le plus proche en surbrillance (`_ReorderOverlay`) ; l'ordre (`col_order` dans `table_dims`) est enregistré. Les colonnes gardent leur indice LOGIQUE (clés `r<ligne>c<colonne>`, largeurs) ; seul l'ordre d'affichage change (`_ResizableTableHeader._order`, `_column_spans`).
- **Sous-cellules déplaçables** : même geste et même retour visuel (`_ReorderOverlay`) en tirant la légende d'une sous-cellule dans sa cellule divisée ; ordre enregistré (`split_order`), indices logiques inchangés.
- **Aimantation** : la bordure d'une sous-cellule s'aimante (9 px) aux bordures verticales des autres lignes (`SplitCell.snap_provider`, fourni par `build_cells_table`).
- **Justification des titres** : clic droit sur un titre d'entête ou sur la légende d'une sous-cellule = gauche/centre/droite ; enregistrée (`head_align`, `split_head_align` dans `table_dims`).
- **Tests isolés** : `tests/test_settings_cells.py` remplace `v2.load_settings` par les valeurs par défaut (jamais les réglages réels de l'utilisateur, qui contiennent ses dimensions enregistrées).
- **Raccourcis** : « Renommer le raccourci… » ne change que le nom AFFICHÉ (clé `name` de `.pipeline_shortcuts.json`), jamais le dossier cible.
- Vérification : `tests/test_settings_cells.py` et `tests/test_settings_window_v2.py`.

## Commit et push

- Commit depuis WSL avec `git` (identité globale déjà configurée) ; `git add -u` pour les fichiers suivis, `lancer.sh` (non suivi) n'est pas à ajouter.
- Le push se fait avec `git.exe push` (Git for Windows, via le Gestionnaire d'identifiants Windows) : un `git push` WSL échoue (« could not read Username for 'https://github.com' »). Sinon, pousser depuis un terminal Windows dans le dossier.
- Messages de commit en français, terminés par la ligne `Co-Authored-By` demandée par l'environnement.

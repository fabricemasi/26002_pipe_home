# AGENTS.md : instructions du projet PIPE FMZ

Lu par Claude Code (via `CLAUDE.md` : `@AGENTS.md`) et par Codex. Chargé à CHAQUE appel : seulement les règles valables pour toute l'appli. Le détail d'un sujet est dans `docs/agents/<sujet>.md`, lu à la demande. Une décision durable est écrite UNE fois, au bon endroit (doc du module, jamais ici sauf règle générale).

## Règles absolues de l'utilisateur

- **Toujours répondre en FRANÇAIS** (réponses, questions, récapitulatifs ; code et commentaires le sont déjà).
- **FLUIDITÉ (intransigeant)** : l'appli ET les réglages réagissent TOUT DE SUITE, jamais « quelques secondes plus tard ». Avant d'ajouter un travail dans un aperçu en direct, une peinture, un clic ou une navigation : estimer son coût (rien d'O(n) par image ou par événement, ne rien refaire qui n'a pas changé). La MESURE (cProfile, fenêtre de réglages entière ~24 000 widgets, bancs `tools/bench_*.py`) se fait à temps perdu : la noter avec sa commande dans `docs/agents/a_mesurer.md` ; l'utilisateur lance `fluidite.bat`, et ce qui échoue dans `docs/agents/rapport_fluidite.md` se corrige EN PRIORITÉ à la requête suivante (le lire s'il est plus récent que la dernière lecture). Pièges : `docs/agents/pieges-generaux.md`.
- **PETITE REQUÊTE = QUELQUES SECONDES À QUELQUES MINUTES.** Tests : SEULEMENT ceux écrits pour la modification et ceux qui couvrent la fonction modifiée, appelés PAR NOM (`tests.test_x.Classe` ou `.test_y`), ~30 s au total ; un fichier de test entier seulement s'il est absent de `tools/hooks/tests_lourds.txt` ; JAMAIS `tests/run.py`, `discover` sans `-p`, `--lent`, `PIPELINE_TESTS_LENTS=1` (l'utilisateur les lance via `fluidite.bat`). « rapide » dans la demande = seulement le test écrit. Le hook `tools/hooks/garde_fous.py` (`.claude/settings.json`) refuse ces commandes et toute recherche récursive à la racine ; le contourner (`GARDE_FOUS_OK=1 commande`) SEULEMENT si l'utilisateur le demande en toutes lettres. Un échec SANS LIEN avec la modification : le signaler, ne pas enquêter.
- **EFFICACITÉ** : coût d'une modification proportionnel à sa complexité, jamais à la taille de l'appli ni à l'âge de la conversation. Proposer d'office toute alternative qui rendrait les requêtes plus efficaces (découpage, doc, tests). Garder le code découpé (modules isolés, fichiers de taille raisonnable ; plan : `docs/agents/fm_theme.md`, « Isolation des modules de fm_browser »).

## Traiter une demande : recherche progressive

1. Comprendre précisément ce qui doit changer.
2. Trouver le module dans la table « Documentation par sujet » ci-dessous (ou `docs/agents/carte_reglages.md` pour un réglage).
3. Dans sa doc : lire la section « Carte » (en tête) puis CHERCHER le mot-clé (Grep sur ce seul fichier). Ne JAMAIS lire une doc entière : elles font 35 à 150 Ko, et tout ce qui est lu reste dans le contexte jusqu'à la fin de la conversation.
4. Grep du symbole dans les fichiers indiqués, puis lire seulement les lignes utiles (Read avec offset / limit) ; un fichier de plus de 1 500 lignes ne se lit jamais en entier.
5. Modifier le plus localement possible, sans refactoring adjacent ; vérifier une interface partagée seulement si la modification peut l'affecter.
6. Tester par nom (règle ci-dessus). 7. Compte rendu bref ; noter dans la doc du module ce que l'utilisateur a demandé ou le piège trouvé.

Recherche globale seulement si le module est introuvable ou le risque réellement transversal ; jamais `grep -r` sur la racine (`data/` et les caches font expirer la commande). Pas de sous-agents ni de long plan pour une correction simple. Ne pas refaire une recherche déjà faite dans la session, sauf si le fichier a changé depuis.

## Sessions courtes et passation (2026-11-07)

Mesuré sur les 66 conversations du projet : le contexte de départ est ~86 k tokens, mais 82 % des tokens d'entrée sont partis dans des appels à plus de 250 k, c'est-à-dire dans l'historique des longues conversations.
- Une tâche = une session. Quand une tâche est finie et que la demande suivante est indépendante, CONSEILLER à l'utilisateur une nouvelle session (nouvelle conversation, ou `/clear`) ; ne jamais prétendre l'avoir fait. Garder la session tant que les demandes portent sur la même fonctionnalité.
- `/compact` seulement quand la tâche continue et que le contexte est lourd, avec la consigne : objectif, décisions, fichiers, modifications, tests, problèmes ouverts, prochaine action. Ne pas changer de modèle en cours de conversation (le cache est perdu : tout le contexte est réécrit).
- PASSATION : si une tâche complexe reste INACHEVÉE au changement de session, REMPLACER (jamais empiler) la section `## PASSATION` de la doc du module : 15 lignes au plus (objectif, fait, fichiers, décisions, état des tests, reste, prochaine action), sans code ni sortie d'outil ; l'effacer quand la tâche est finie. L'état Git et les fichiers restent la source de vérité. Pas de passation pour une petite correction.

## Projet et commandes

Pipeline Browser / PIPE FMZ : navigateur de fichiers en colonnes (Miller columns) en PySide6, Windows (DPI par écran, attributs cachés, chemins `.exe`), racine par défaut `F:\PIPELINE` (`root_path` dans `data/pipeline_settings.json`). Code et commentaires en français. Le dossier est SYNCHRONISÉ (cloud) : voir `docs/agents/pieges-generaux.md`.

- Lancer : `pipeline_browser_debug.bat` (crée `.venv`, installe les dépendances de `requirements.txt`) ou `python pipeline_browser.py`.
- Tests (unittest, Qt offscreen, certains exigent Blender) : un test `python -m unittest tests.test_render_log.RenderLogTest.test_x` (depuis la racine) ; un fichier léger `python -m unittest discover -s tests -p test_x.py`. Tout fichier de test commence par `import _isolate` (OBLIGATOIRE : réglages, presets, état des fenêtres redirigés vers des copies) ; patcher un nom dans le module qui l'utilise ; doubler les presets dans `settings_store`. Fenêtres de réglages construites par un test : détruites à la fin (`tests/_window_cleanup.py`, `WindowTestCase`) ; jamais de filtre d'événements permanent sur l'application. Tout nouveau fichier de test est rangé dans `MODULES` de `tests/run.py` ; les tests lourds sont marqués `@lent` (`tests/_lent.py`). Les tests Illustrator exigent `.venv/Scripts/python.exe`.
- Pas de linter ni de build. `.venv/` ignoré par git.

## Architecture

Modules plats à la racine, en couches : chaque module n'importe que ceux qui le précèdent (imports tardifs `import browser_core as pb_core` dans `settings_*` contre le cycle). Ordre : `config.py` (constantes) ; `ui_state.py` (réglages d'interface réassignés à l'exécution : TOUJOURS `ui_state.X`, jamais `from ui_state import X`) ; `previews.py` (aperçus, caches, rendus Blender / Maya) ; `browser_core.py` (scan disque, config projet, peinture) ; `row_delegates.py`, `column_config.py`, `capture_widgets.py`, `column.py`, `preview_column.py`, `detail_panel.py` (+ `detail_panel_parts/`) ; `software_launch.py` ; `fm_markdown/preview.py` ; `fm_visionneuse/` ; `lightroom_bridge.py` ; `pipeline_browser.py` (point d'entrée : `main()` = `load_settings()` → `apply_all_settings()` → `QApplication` → `apply_style()` → fenêtre ; cœur de `PipelineBrowser`, le reste dans les mixins de `main_window/`).

`fm_theme/` = l'aspect (n'importe RIEN de l'appli ; `fm_theme/hooks.py`) ; les anciens noms (`app_style.py`, `settings_widgets.py`…) sont des alias `sys.modules` ; éditeur d'aspect seul : `fm_theme.bat` (`theme_editor.py`). Fenêtre de réglages : `settings_store.py` → `settings_theme.py` → `settings_menu.py` → `settings_dialogs.py` → `settings_widgets.py` → `settings_colorpicker.py` → `settings_layout.py` → `settings_sections.py` → `settings_window.py` → `settings_window_v2.py` (seule fenêtre ; une par module = `SettingsWindowV2(module=…)`). `settings_catalog.py` (sans Qt) : `CATALOG` ; chaque paquet décrit ses réglages dans `<paquet>/settings.py`, défauts dans `<paquet>/settings_defaults.py`.

Paquets de modules (aucun ne dépend de la fenêtre principale, elle leur pose des `HOOKS`) : `fm_board`, `fm_miro`, `fm_cad`, `fm_design`, `fm_visionneuse`, `fm_markdown`, `fm_video`, `fm_tableur`, `fm_illustrator`, `fm_photoshop`, `fm_font`, `fm_pdf`, `fm_agenda`. Données de l'appli dans `data/`, modèles Blender dans `files/`, SVG dans `icons/`.

Réglages : `DEFAULT_SETTINGS` (`settings_store.py`) est la source de vérité, toute nouvelle clé y est déclarée (les inconnues sont ignorées) ; `apply_all_settings()` recopie les réglages dans les globals, avec un refresh derrière (`PipelineBrowser._apply_settings`). Enregistrer UNE clé d'état temps réel : `settings_store.save_live_state(clé, valeur)`, jamais `load_settings()` + `save_settings()`. Presets : `data/pipeline_settings.presets.json` (détail : `docs/agents/reglages.md`).

## Documentation par sujet (lire la Carte, puis chercher dedans)

| Sujet | Doc |
|---|---|
| Où vit chaque réglage (GÉNÉRÉE : `python tools/carte_reglages.py` après ajout / déplacement de section) | `carte_reglages.md` |
| Pièges de fluidité, isolation des tests, outillage, méthode de travail | `pieges-generaux.md` |
| Fenêtre principale découpée (`pipeline_browser.py` + `main_window/`) | `fm_browser.md` |
| Colonnes, navigation, boutons de mode, logiciels, opérations sur les fichiers | `colonnes.md` |
| Inspecteur (`detail_panel.py` + `detail_panel_parts/`) | `inspecteur.md` |
| Aperçus, caches, rendus Blender / Maya / Houdini, Lightroom | `apercus.md` |
| Visionneuse, pellicule, planche, PureRef, attributs, filtres | `fm_visionneuse.md` |
| Fenêtre de réglages v2 et ses briques, presets, menus contextuels, gabarits | `reglages.md` (+ `over/Notes.txt` en entier avant de toucher la fenêtre de réglages) |
| fm_theme (aspect, variantes, presets, isolation des modules), barres flottantes | `fm_theme.md`, `barres_outils_spec.md` |
| Board (`.brd`) / tableau blanc / CAD / Design / Tableur | `fm_board.md` / `fm_miro.md` / `fm_cad.md` / `fm_design.md` / `fm_tableur.md` |
| Illustrator / Photoshop / Typographie | `fm_illustrator.md` / `fm_photoshop.md` / `fm_font.md` |
| Markdown / Vidéo / PDF / Agenda / Tâches | `fm_markdown.md` / `fm_video.md` / `fm_pdf.md` / `fm_agenda.md` / `fm_taches.md` |

Suivis de mission à la racine : `PDF_MODULE_PROGRESS.md`, `FM_AGENDA_PROGRESS.md`, `FM_TACHES_PROGRESS.md`, `COLOR_ANALYSIS_PROGRESS.md`.

## Règles de l'appli

- **Styles jamais inventés** : tout élément qui a son équivalent dans les réglages (tableau, titre, zone de saisie, toggle, panneau…) est construit AVEC les briques des réglages (`settings_window_v2.seed_window_look` puis `_flat_cells_table` / `build_cells_table`, rôles de texte, `_title_font`, `_PanelFrame` + `M`, `make_field`) ; précédents : `settings_quick_style.QuickStyleWindow`, `focus.FocusInfoPanel`. Gabarits : `docs/agents/reglages.md`.
- **Ctrl + glisser** : TOUT déplacement d'élément (colonnes, sous-cellules et lignes des tableaux, titres de la v2, éléments des menus contextuels, lignes des colonnes, colonnes IN/OVER/OUT/LOGICIELS) démarre seulement avec Ctrl enfoncé au départ du geste (`QApplication.keyboardModifiers()`), avec l'opacité `DRAG_GHOST_OPACITY` ; sans Ctrl le geste garde son sens habituel. EXCEPTION voulue : les barres d'outils flottantes (glissées SANS Ctrl, Ctrl + clic sur le titre = renommer), identiques à `docs/agents/prototype_barres_outils.html` (spec `barres_outils_spec.md`).
- **Échap ne fait jamais sortir d'un module** (board et ses modules, vidéo, typographie, visionneuse…) : il annule seulement (geste, sélection, outil, plein écran, zoom).

## Commit et push

`git add -u` pour les fichiers suivis (jamais `lancer.sh`) ; messages en français, terminés par la ligne `Co-Authored-By` demandée par l'environnement. Push : `git.exe push` (Git for Windows, Gestionnaire d'identifiants) ; un `git push` de WSL échoue (« could not read Username »).

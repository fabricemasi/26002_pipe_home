# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> ## ⚠️ IL FAUT QUE CE SOIT FLUIDE !
> **Demande expresse de l'utilisateur, intransigeant sur ce point : l'appli ET les réglages doivent réagir TOUT DE SUITE, sans lourdeur, jamais « quelques secondes plus tard ».** Tout changement de code est jugé d'abord là-dessus. Avant d'ajouter un travail dans un aperçu en direct, une peinture, un clic ou une navigation : le mesurer (sonde cProfile, fenêtre de réglages ENTIÈREMENT construite — ~24 000 widgets) et ne rien refaire qui n'a pas changé. Pièges déjà rencontrés : `docs/agents/pieges-generaux.md`.

> ## 🇫🇷 Langue : toujours parler FRANÇAIS à l'utilisateur
> **Demande expresse de l'utilisateur** : toutes les réponses, questions, récapitulatifs et messages de fin de tour sont en français (le code et les commentaires le sont déjà).

## Projet

Pipeline Browser : navigateur de fichiers en colonnes (Miller columns) en PySide6, pour une arborescence de projets de production (racine par défaut `F:\PIPELINE`, réglable via `root_path` dans `data/pipeline_settings.json`). Application Windows (DPI per-monitor, attributs « caché » Windows, chemins `.exe`) ; le code et les commentaires sont en français. Le dépôt est édité depuis WSL mais l'appli tourne sous Windows.

## Commandes

- Lancer : `pipeline_browser_debug.bat` (crée `.venv`, installe PySide6/ezdxf/matplotlib, lance l'appli) ou `python pipeline_browser.py` (`pythonw` pour éviter la console).
- Dépendances : `requirements.txt` (PySide6 ; optionnels : OpenEXR, numpy, ezdxf, matplotlib).
- Tests (unittest, offscreen Qt, certains exigent Blender installé) :
  - tous : `python -m unittest discover -s tests`
  - un fichier : `python -m unittest discover -s tests -p test_turntable.py`
  - un test : `python -m unittest tests.test_render_log.RenderLogTest.test_requested_columns_and_render_metadata` (lancer depuis la racine ; les tests importent `previews`, `detail_panel`… : patcher un nom dans le module qui l'utilise, pas dans celui qui l'a importé).
- Tout fichier de test commence par `import _isolate` (`tests/_isolate.py` : réglages, presets et état des fenêtres redirigés vers des COPIES temporaires) — OBLIGATOIRE (un test a déjà écrit dans le vrai preset de l'utilisateur). Doubler des fonctions de presets : les remplacer dans `settings_store`. Détail : `docs/agents/pieges-generaux.md`.
- Fenêtres de réglages construites par un test : DÉTRUITES à la fin du test (`tests/_window_cleanup.py`, `WindowTestCase`). Ne jamais poser de filtre d'événements sur l'application en permanence. Détail : `docs/agents/pieges-generaux.md`.
- Pas de linter ni de build configuré.
- `.venv/` est ignoré par git (ne pas l'éditer).

## Architecture

Modules plats à la racine (aucun package), en couches : chaque module n'importe que ceux qui le précèdent (les imports tardifs `import browser_core as pb_core` dans `settings_*` évitent le cycle).

Application (ordre de dépendance) :
- `config.py` : constantes (extensions, listes d'omission `GLOBAL_OMIT_*`) ; `ui_state.py` : réglages d'interface **réassignés à l'exécution** (`WINDOW_RADIUS`, `HEADER_HEIGHT`, `STEP_BADGE_STYLE`…). Ils se lisent toujours via `ui_state.X` (jamais `from ui_state import X`, qui figerait la valeur).
- `previews.py` : décodeurs d'aperçus, caches mémoire/disque, rendus Blender/Maya, ordonnanceur de fond, journal de rendu.
- `browser_core.py` : scan disque, config projet/layout/raccourcis, helpers de peinture/redimensionnement.
- `row_delegates.py` (`RowDelegate`, `ProjectTileDelegate`), `column_config.py` (dialogue de configuration des colonnes), `capture_widgets.py` (capture, `_PreviewBlock`, `_ColumnCard`…), `column.py` (`Column`), `preview_column.py` (`PreviewColumn`, export PureRef), `detail_panel.py` (`DetailPanel`, inspecteur).
- `software_launch.py` : ouvrir un logiciel (Blender, Houdini) dans le dossier d'une colonne (détail : `docs/agents/colonnes.md`).
- `markdown_preview.py` : rendu Markdown -> HTML partagé par le module Markdown et l'inspecteur (détail : `docs/agents/markdown.md`).
- `focus.py` : visionneuse, pellicule, planche (détail : `docs/agents/visionneuse.md`).
- `lightroom_bridge.py` : dossiers liés à un catalogue Lightroom Classic (détail : `docs/agents/apercus.md`).
- `pipeline_browser.py` : `IconButton`, `TitleBar`, `PipelineBrowser(QMainWindow)`, `apply_all_settings`, `main()` (`load_settings()` → `apply_all_settings()` → `QApplication` → `apply_style()` → fenêtre). Point d'entrée.

Fenêtre de réglages (ordre de dépendance) : `settings_store.py` (palette `M`, `DEFAULT_SETTINGS`, `load/save_settings`, presets), `settings_theme.py` (rôles de texte, arrondis communs), `settings_menu.py` (menus contextuels, voir `docs/agents/reglages.md`), `settings_dialogs.py` (fenêtre de confirmation `confirm`, briques des réglages), `settings_widgets.py` (champs de base : `_Toggle`, `_MiniSlider`, `_FontSelectField`…), `settings_colorpicker.py`, `settings_layout.py` (sections/tableaux), `settings_sections.py` (registre des champs, polices/couleurs/entêtes/géométrie), `settings_window.py` (briques communes ; la fenêtre v1 est RETIRÉE, seule la v2 `settings_window_v2.py` existe).

`app_style.py` : tokens de style (couleurs, polices par rôle) et `build_stylesheet()`/`apply_style()`.

Les données propres à l'appli sont dans `data/` (réglages, presets, état des fenêtres, cache d'aperçus, icônes de logiciels) ; `files/` contient les modèles Blender et profils de rendu, `icons/` les SVG de l'interface.

Paquets : `board/` (module MRO + CAD), `mdeditor/` (module Markdown), `video/` (module vidéo) ; aucun ne dépend de la fenêtre principale (elle leur pose des `HOOKS`).

### Réglages (règles de base)
Enregistrer UNE clé d'état temps réel : `settings_store.save_live_state(clé, valeur)` (écrit cette clé dans le fichier tel qu'il est), jamais `load_settings()` + `save_settings()` (cela fige dans le fichier les valeurs du preset actif, même périmées).
`DEFAULT_SETTINGS` (settings_store.py) est la source de vérité : `load_settings` fusionne `data/pipeline_settings.json` par-dessus (puis le preset actif, voir « Presets » dans `docs/agents/reglages.md`) et ignore les clés inconnues — toute nouvelle clé doit donc y être déclarée. `apply_all_settings()` (pipeline_browser.py) est le point d'entrée unique qui recopie les réglages dans des globals/tokens ; il n'a d'effet visible qu'avec un refresh derrière (`refresh_all_columns`, `refresh_colors`…, cf. `PipelineBrowser._apply_settings`). Presets : `data/pipeline_settings.presets.json`.

## Documentation détaillée par sujet (À LIRE AVANT d'y travailler)

Le détail de chaque module (choix de l'utilisateur, pièges, mesures, tests) est dans `docs/agents/`, lu seulement quand on travaille dessus. Avant de modifier un sujet : lire son fichier. Après une demande de l'utilisateur ou un piège trouvé : l'y noter (jamais ici, sauf règle valable pour toute l'appli).

- `docs/agents/pieges-generaux.md` : pièges de fluidité déjà rencontrés, isolation des tests.
- `docs/agents/colonnes.md` : colonnes (configuration `.pipeline_*.json`, animations, navigation réactive, réseau, dessin), boutons de mode de la barre, lancement des logiciels, opérations sur les fichiers (confirmations, corbeille, glisser-déposer).
- `docs/agents/apercus.md` : pipeline d'aperçus, caches, rendus Blender / Maya / Houdini, rendu automatique SUSPENDU, Lightroom.
- `docs/agents/visionneuse.md` : visionneuse, pellicule, planche, PureRef, cadre « Visionneuse », attributs des fichiers, filtres.
- `docs/agents/markdown.md` : module Markdown / code (`mdeditor/`), aperçu des notes, CSS / Obsidian.
- `docs/agents/board.md` : module Board (`board/`, clone de Miro).
- `docs/agents/cad.md` : module CAD du board (`board/cad*.py`).
- `docs/agents/video.md` : module vidéo (`video/`).
- `docs/agents/reglages.md` : fenêtre de réglages v2 et ses briques (tableaux, toggles, presets, menus contextuels, fenêtres additionnelles, « Changement de style à la volée », « Override settings », couleurs, cheminement / barre de navigation, préchargement), gabarits de lignes, réutilisation dans d'autres applis.
- `docs/agents/fm_theme.md` : PROJET (non codé) de séparation en deux entités, fm_theme (aspect : variantes d'éléments, presets) et fm_browser (tout le reste) ; ordre de migration, questions ouvertes.

## Déplacements : Ctrl + glisser (règle de l'appli)

Demande de l'utilisateur : TOUT déplacement d'élément (colonnes, sous-cellules et lignes des tableaux, titres de la v2, éléments des menus contextuels, lignes des colonnes, colonnes IN/OVER/OUT/LOGICIELS) démarre seulement avec Ctrl enfoncé (`QApplication.keyboardModifiers()` au départ du geste) ; sans Ctrl, le geste garde son sens habituel (clic, glisser de fichiers pour les lignes des colonnes). Tout nouveau déplacement doit suivre cette règle (et l'opacité `DRAG_GHOST_OPACITY`).

## Conventions du projet

**Styles : jamais inventés.** Tout élément qui a déjà son équivalent dans les réglages (tableau, titre, zone de saisie, toggle, panneau…), y compris dans la fenêtre principale, est construit AVEC les briques des réglages (`settings_window_v2.seed_window_look` puis `_flat_cells_table` / `build_cells_table`, rôles de texte, `_title_font`, `_PanelFrame` + `M`, `make_field`) ; précédents : `settings_quick_style.QuickStyleWindow`, `focus.FocusInfoPanel`. Demande expresse de l'utilisateur, valable pour tout élément à venir.

Gabarits des lignes de réglages et sources uniques des styles : `docs/agents/reglages.md` ; lire `over/Notes.txt` en entier avant de modifier la fenêtre de réglages.

## Commit et push

- Commit depuis WSL avec `git` (identité globale déjà configurée) ; `git add -u` pour les fichiers suivis, `lancer.sh` (non suivi) n'est pas à ajouter.
- Le push se fait avec `git.exe push` (Git for Windows, via le Gestionnaire d'identifiants Windows) : un `git push` WSL échoue (« could not read Username for 'https://github.com' »). Sinon, pousser depuis un terminal Windows dans le dossier.
- Messages de commit en français, terminés par la ligne `Co-Authored-By` demandée par l'environnement.

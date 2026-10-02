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
- `pipeline_browser.py` : `IconButton`, `TitleBar`, `PipelineBrowser(QMainWindow)`, `apply_all_settings`, `main()` (`load_settings()` → `apply_all_settings()` → `QApplication` → `apply_style()` → fenêtre). Point d'entrée.

Fenêtre de réglages (ordre de dépendance) : `settings_store.py` (palette `M`, `DEFAULT_SETTINGS`, `load/save_settings`, presets), `settings_widgets.py` (champs de base : `_Toggle`, `_MiniSlider`, `_FontSelectField`…), `settings_colorpicker.py`, `settings_layout.py` (sections/tableaux), `settings_sections.py` (registre des champs, polices/couleurs/entêtes/géométrie), `settings_window.py` (`SettingsWindow`).

`app_style.py` : tokens de style (couleurs, polices par rôle) et `build_stylesheet()`/`apply_style()`.

Les données propres à l'appli sont dans `data/` (réglages, presets, état des fenêtres, cache d'aperçus, icônes de logiciels) ; `files/` contient les modèles Blender et profils de rendu, `icons/` les SVG de l'interface.

### Réglages
`DEFAULT_SETTINGS` (settings_store.py) est la source de vérité : `load_settings` fusionne `data/pipeline_settings.json` par-dessus et ignore les clés inconnues — toute nouvelle clé doit donc y être déclarée. `apply_all_settings()` (pipeline_browser.py) est le point d'entrée unique qui recopie les réglages dans des globals/tokens ; il n'a d'effet visible qu'avec un refresh derrière (`refresh_all_columns`, `refresh_colors`…, cf. `PipelineBrowser._apply_settings`). Presets : `data/pipeline_settings.presets.json`.

### Configuration par projet/dossier (JSON cachés à la racine des dossiers)
`.pipeline_columns.json` (étapes/colonnes d'un projet, `load/save_project_columns`), `.pipeline_layout.json` (`load/save_layout_settings`), `.pipeline_shortcuts.json` (raccourcis), `.pipeline_protected_previews.json`. Ces fichiers sont versionnés ici car le dépôt contient une copie de travail ; les écritures utilisent `_set_hidden` (attribut caché Windows).

### Pipeline d'aperçus
Aperçus asynchrones : `_PreviewDecodeManager` / `_PreviewDecodeTask` (QRunnable), `_IdlePreviewScheduler` (rendu en tâche de fond quand l'appli est inactive). Cache disque dans `data/.pipeline_preview_cache/` (clé = chemin + mtime ; métadonnées, nettoyage des caches périmés). Décodeurs par format : OBJ (numpy/QPainter ou Blender EEVEE), Alembic `.abc` et `.blend` (Blender), `.ma` (mayapy), PSD, EXR/HDR/TX (OpenEXR / oiiotool), vidéo, DWG (ezdxf + ODA File Converter). Les rendus Blender/Maya sont des **scripts Python embarqués dans des chaînes** exécutés en sous-processus (voir `_render_wireframe_eevee`, `_render_ma_wireframe`) — ce code s'exécute dans l'interpréteur de Blender/Maya, pas dans l'appli. Les profils de rendu (low/high…, turntable) viennent de `files/parametres rendus.txt` (`_load_render_profiles`) ; journal de rendu quotidien `pipeline_preview_render_<date>.html` / `.log`.

Outils externes détectés dynamiquement : `BLENDER_EXECUTABLE`, `MAYA_PYTHON_EXECUTABLE`/`MAYA_LOCATION`, `ODA_FILE_CONVERTER`, `oiiotool` dans le PATH. Tous optionnels : l'appli doit rester fonctionnelle sans (fichiers simplement sans aperçu).

`tools/` : scripts autonomes de conversion/validation Alembic (`convert_legacy_alembic.py`, `validate_alembic_blender.py`).

## Conventions du projet

`over/Notes.txt` définit des **gabarits** pour les lignes de la fenêtre de réglages, à appliquer à toute ligne existante ou future du même type sans que l'utilisateur le répète :
- Lignes *police* : une seule ligne ; toggles app/système sans texte, collés au menu déroulant ; toggle « gras » avec le texte « gras » avant (les deux états) ; texte « Hauteur » avant le slider.
- Lignes *arrondi des angles* : une ligne, pas de bouton copier, toggle « lier les 4 » (texte avant, les deux états), 4 sliders avec champ de saisie, valeur mise à jour en temps réel.
- Lignes *bordures* : pas de bouton copier, toggle « lier les 4 », 4 toggles chacun au-dessus du choix de couleur de son côté.
Lire `over/Notes.txt` en entier avant de modifier la fenêtre de réglages (`over/Prompts.txt` contient l'historique des demandes).

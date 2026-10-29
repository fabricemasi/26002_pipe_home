# Fenêtre principale (`pipeline_browser.py` + paquet `main_window/`)

Détail lu À LA DEMANDE : à lire avant de travailler sur la fenêtre principale. Les COLONNES elles-mêmes (`column.py`, configuration, dessin, opérations sur les fichiers) : `docs/agents/colonnes.md`.

**Tests** : la fenêtre touche tous les modules ; après une retouche, lancer le module concerné (`python tests/run.py colonnes`, `fm_visionneuse`…), et `python tests/run.py --tout` (~8 min) avant un commit qui touche `pipeline_browser.py` lui-même.

## Carte : responsabilité -> fichier (à ouvrir directement)

`pipeline_browser.py` (≈ 1 100 lignes, découpé le 2026-10-28) garde : les imports historiques (réexportés : `pipeline_browser.X` marche en LECTURE pour les tests), la classe finale `PipelineBrowser` = ses MIXINS + `QMainWindow`, avec le CŒUR (`__init__`, restauration de la fenêtre, `_navigate_to`, menus d'espace, `closeEvent`, `nativeEvent`, `resizeEvent` est dans `columns_hidden`), puis `main()` et l'installation des menus / filtres / journal d'erreurs.

Chaque mixin est une classe SANS Qt (`class XMixin:`) dont les méthodes utilisent `self` comme avant ; `super()` y marche (ordre des bases). Pour PATCHER un nom dans un test, viser le module de `main_window/` qui l'appelle (ex. `main_window.viewer_chrome.save_settings`), jamais `pipeline_browser.X`.

| Fichier (`main_window/`, lignes) | Responsabilité | Classes / méthodes principales |
|---|---|---|
| `helpers.py` (69) | Petits outils de la fenêtre principale : filtres d'événements (bouton « précédent » de la souris, activité), QSS | `_anim_running`, `_set_qss` (= `fm_theme.style.set_qss` : rien si la feuille est identique), `CentralFrame` (cadre central PEINT : fond, filet, coins ; plus en QSS, qui repolissait toute la fenêtre à chaque cran), `_MouseBackFilter`, `_AppInputWatch` |
| `title_bar.py` (731) | Barre de titre / barre de navigation (TitleBar), cheminement (puces), cadre « Visionneuse » | `_crumb_look`, `_build_crumb_look`, `_crumb_state`, `_CrumbChip` |
| `interface_move.py` (2073) | Mode « Déplacer l'interface » : objets libres de la fenêtre, cadres de déplacement, positions enregistrées | `_InterfaceMoveFrame`, `_InterfaceObjectStore`, `_InterfaceMoveMode` |
| `columns.py` (299) | Colonnes : rechargement, ajout, boutons des logiciels, rafraîchissement de toutes les colonnes | `reload`, `add_column`, `prune_after`, `refresh_all_columns`, `_detach_group_stack`, `_clear_group_stack`, `_clear_image_preview_columns` |
| `crumbs.py` (170) | Cheminement de la barre de navigation : entrées, clics, dossier de la visionneuse | `_request_crumbs`, `_refresh_crumbs`, `_viewer_crumb_items`, `_relative_parts`, `_set_viewer_folder`, `_crumb_entries`, `_crumb_items` |
| `preview_stack.py` (569) | Colonne active, chaîne de colonnes, pile d'aperçus (colonnes IN / OVER / OUT / LOGICIELS) | `update_active_column`, `update_preview_stack`, `_chain_expected_total`, `_chain_terminal_path`, `_chain_set_name`, `_preview_style_snapshot`, `_preview_stack_key` |
| `group_columns.py` (418) | Colonnes de groupe (Logiciels / IN / OVER / OUT) : sélection, largeur, hauteur, agrandir / égaliser, ordre | `_on_group_item_selected`, `_open_group_folder`, `_on_group_column_resized`, `_on_group_column_resize_end`, `_sync_group_widths`, `_on_group_height_resize_begin`, `_on_group_height_resized`… |
| `selection.py` (456) | Sélection dans une colonne : navigation, fondus, animation d'apparition, état replié | `on_selected`, `on_reclicked`, `_navigation_data_ready`, `_column_loaded`, `_raise_select_fade`, `_fade_before_select`, `_on_selected_now` |
| `columns_hidden.py` (376) | Masquer / montrer les colonnes de projet (fondu, instantanés) et l'image focus qui en sort | `resizeEvent`, `_toggle_project_columns_hidden`, `_hideable_widgets`, `_toggled_widgets`, `_apply_columns_hidden`, `_columns_visible_rect`, `_columns_content_right`… |
| `gallery.py` (650) | Planche des images du dossier (état focus) et ses filtres | `eventFilter`, `_toggle_focus_gallery`, `_focus_file_column`, `_gallery_paths`, `_filtered_gallery`, `_filter_root`, `_filter_provenances`… |
| `viewer.py` (631) | Visionneuse : entrée, ruban, planches PureRef, dossier + récursif, ouverture d'un fichier (double-clic) | `on_activated`, `browse_root`, `_enter_viewer`, `_expand_viewer_pureref`, `_pur_files`, `_remember_pur`, `_start_pur_images`… |
| `viewer_buttons.py` (286) | Rangée des boutons de la visionneuse / planche : ordre choisi à la main (Ctrl + glisser) | `_shown_or_pending`, `_ViewerButtonDrag`, `_viewer_row_items`, `_layout_viewer_buttons`, `_host_in_group`, `_send_home`, `_release_viewer_buttons`, `_move_viewer_button`, `_filmstrip_enabled`… |
| `viewer_chrome.py` (609) | Visionneuse : pellicule, diapositives, panneau d'infos, navigation d'image, touches, zoom | `_on_filmstrip_split`, `_on_gallery_split`, `_filmstrip_menu`, `_open_filmstrip_style`, `_film_style_open`, `_forget_film_style_window`, `_on_filmstrip_style`… |
| `collapse.py` (374) | Repli des colonnes de projet : glissement, instantanés préparés, largeur de l'inspecteur | `_enforce_hidden_columns`, `_enforce_hidden_columns_now`, `_auto_expand_now`, `_auto_collapse_now`, `_toggle_project_columns`, `_on_preview_column_resized`, `_apply_project_columns_collapsed`… |
| `settings_link.py` (478) | Presets, fenêtre de réglages (ouverture, préchargement sur inactivité), application des réglages | `settings_window_v2_preload_enabled`, `open_settings_v2`, `open_settings`, `_choose_preset`, `_refresh_preset_ui`, `_open_preset_manager`, `_make_settings_v2`, `open_module_settings` (fenêtre de réglages d'un module), `_heavy_foreground_work`, `_restyle_bricks` (chemin rapide de l'aspect des briques : curseurs, titres, tableaux, toggles, menus, fenêtres additionnelles, préfixes `_BRICK_PREFIXES`), `_start_theme_link` / `_on_theme_live` / `_on_theme_file_changed` (preset fm_theme lié)… |
| `chrome.py` (235) | Habillage de la fenêtre : boutons de mode, styles, tailles, polices, couleurs, ombres des boutons | `refresh_chrome_sizes`, `refresh_chrome_fonts`, `refresh_colors`, `_nav_input_height`, `_sync_collapse_button`, `_set_button_usable`, `_selected_path`… |
| `md_module.py` (252) | Branchement du module Markdown (fm_markdown) : cadre « Éditeur », ouverture, synchro CSS, hooks | `_set_md_margin`, `_persist_md_margin`, `_md_pane`, `_save_md_state`, `_start_css_sync`, `_apply_md_external`, `_preload_md_editor`… |
| `video_module.py` (215) | Branchement du module vidéo (fm_video) : cadre « Vidéo », ouverture, hooks, réglages | `_preload_video`, `_video_claims`, `_install_video_hooks`, `_write_video_setting`, `_save_video_state`, `_toggle_video`, `_open_video` |
| `board_module.py` (170) | Branchement du board (fm_board / fm_cad) : cadre « Board », ouverture, dessins DXF / DWG | `_DrawingRelay`, `_board_icon`, `_toggle_board`, `_open_cad_drawing`, `_cad_drawing_read`, `_open_board`, `_close_board`, `_layout_board_buttons` |

Règles :
- Un mixin n'importe jamais `pipeline_browser` (annotations seulement, sous `TYPE_CHECKING`) ; les classes de tête (`helpers`, `title_bar`, `interface_move`, `viewer_buttons`) se chargent avant les mixins.
- Nouvelle méthode de la fenêtre : dans le mixin de sa responsabilité (pas dans `pipeline_browser.py`, réservé au cœur).
- Les modules (fm_video, fm_markdown, fm_board…) se branchent par `md_module.py`, `video_module.py`, `board_module.py` (leurs `HOOKS`).

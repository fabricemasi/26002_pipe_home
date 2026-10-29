# Inspecteur (`detail_panel.py` + paquet `detail_panel_parts/`)

Détail lu À LA DEMANDE : à lire avant de travailler sur l'inspecteur (panneau de droite : aperçu, informations, notes, rendus).

**Tests** : `python tests/run.py colonnes` (`test_inspector_resize`), `fm_markdown` (`test_markdown_edit`), `apercus` (`test_render_log`, `test_turntable*`), `reglages` (`test_settings_window_v2`) ; `--tout` avant un commit qui touche `detail_panel.py` lui-même.

## Carte : responsabilité -> fichier (à ouvrir directement)

`detail_panel.py` (≈ 900 lignes, découpé le 2026-10-29) garde : `_TurntableSlider`, `_VideoView`, la classe finale `DetailPanel` = ses MIXINS + `QWidget` avec le CŒUR (`__init__`, `refresh_header`, `clear`, `resizeEvent`, `_update_preview`), et l'état de la fenêtre principale (`load_window_state` / `save_window_state`).
Chaque mixin est une classe sans Qt dont les méthodes utilisent `self` comme avant. Pour PATCHER un nom dans un test, viser le module qui l'appelle (ex. `detail_panel_parts.render_log._write_render_log`), pas `detail_panel.X`.

| Fichier (`detail_panel_parts/`, lignes) | Responsabilité | Méthodes principales |
|---|---|---|
| `resize.py` (137) | largeur tirée à la souris sur la bordure gauche, curseur et survol | `eventFilter`, `mouseMoveEvent`, `mousePressEvent`, `mouseReleaseEvent`, `leaveEvent`, `_max_width`… |
| `preview_controls.py` (155) | boutons et menu contextuel de l'aperçu (supprimer, Lightroom, vidéo) | `_delete_preview`, `_set_preview_controls_visible`, `_request_lightroom_preview`, `_restore_lightroom_preview_button`, `_reflow_preview_controls`, `_show_preview_context_menu`… |
| `info_table.py` (155) | polices, couleurs et tableau d'informations (type, taille, date, sources) | `refresh_fonts`, `refresh_colors`, `_build_info_table`, `_fit_info_table`, `_attach_controls_row`, `_restyle_info_table`… |
| `markdown.py` (266) | notes Markdown (rendu de fm_markdown, édition, enregistrement fidèle) | `refresh_markdown_style`, `_md_widgets`, `_text_shown`, `_hide_markdown`, `_hide_text_views`, `_ensure_markdown_widgets`… |
| `sources.py` (126) | source de l'image focus, badges d'aperçu périmé / d'origine, sources et profil Lightroom | `focus_source`, `_refresh_preview_stale_badge`, `_refresh_preview_origin_badge`, `_on_lightroom_sources`, `_set_source_rows_visible`, `_on_lightroom_profile_ready`… |
| `turntable.py` (166) | médias 3D rendus (image / turntable), curseur et lecture du turntable | `_selected_preview_media`, `_render_preview_media`, `_refresh_render_action_buttons`, `_select_preview_media`, `_update_turntable_control_state`, `_on_turntable_slider_changed`… |
| `pdf_pur.py` (203) | PDF (zoom, pages) et planches PureRef (navigation, export) | `select_pur_image`, `_pdf_geometry`, `_pdf_clamp_view`, `_pdf_set_zoom`, `_pdf_event`, `_navigate_pdf_page`… |
| `render_log.py` (304) | rendus 3D (lancement, progression, protection) et journal de rendu | `prepare_auto_preview_log`, `open_preview_render_log`, `_start_3d_preview`, `_load_selected_render_log`, `_refresh_open_render_log`, `_on_preview_generation_started`… |
| `show.py` (278) | affichage d'un chemin (show_path), vidéo, nombre d'éléments d'un dossier | `show_path`, `_show_video`, `_fill_folder_count` |

Détails par sujet : notes Markdown -> `docs/agents/fm_markdown.md` ; aperçus, rendus Blender / turntable, journal de rendu, Lightroom -> `docs/agents/apercus.md` ; largeur / repli de l'inspecteur dans la fenêtre -> `docs/agents/fm_browser.md` (`collapse.py`).

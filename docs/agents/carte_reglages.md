# Carte des réglages (GÉNÉRÉE : `python tools/carte_reglages.py`, ne pas éditer à la main)

Trouver en une recherche où vit un réglage : section affichée -> groupe du catalogue (`CATALOG[...]`, settings_window_v2.py ou `<paquet>/settings.py`) -> clés. « fm_theme » = la clé est enregistrée dans le preset fm_theme (`fm_theme.presets.theme_key`).

## Qui applique quoi

| Préfixe | Appliqué par |
|---|---|
| `navbar_` | main_window/title_bar.py (`refresh_sizes`, `refresh_look`) ; chemin rapide `refresh_navbar` (main_window/chrome.py) |
| `crumb_` | main_window/title_bar.py (`refresh_crumbs`, `_crumb_look`) |
| `statusbar_` | fm_theme/status_bar.py (`apply_status_bar`) via `ChromeMixin.refresh_status_bar` |
| `extra_window_` | settings_window_v2.seed_extra_window_look, fm_theme/window.py (`install_extra_window`) |
| `window_border` | browser_core.apply_window_border, main_window/helpers.CentralFrame |
| `button_ / input_ / tabs_` | fm_theme/style.build_stylesheet, settings_theme.apply_input_look, _TabStrip |
| `slider_ / title_ / table_ / toggle / ctx_ / palette_` | settings_link._restyle_bricks (briques fm_theme) |
| `colors / font_` | app_style.apply_all_settings -> refresh_colors / refresh_fonts |
| `item_ / header_ / column_` | column.py, row_delegates.py, column_parts/appearance.py |
| `preview_ / viewer_` | capture_widgets.py, preview_column.py, fm_visionneuse/ |
| `md_` | fm_markdown/pane.py (`apply_settings`), fm_markdown/css_sync.py |
| `video_` | fm_video/pane.py (`apply_settings`) |
| `board_ / tableur_` | fm_board/ui.py (`apply_settings`) ; CAD : fm_cad/settings.py ; Photoshop : fm_photoshop/settings.py |
| `typo_` | fm_font/pane.py (`apply_settings`) |
| `auto_` | automatic_tasks.py |

## Sections

| Onglet | Section | Groupe | Stockage | Clés |
|---|---|---|---|---|
| General | Colonnes > Colonnes | `G Colonnes` | appli | `item_column_width`, `column_gap`, `column_padding`, `column_bg_color`, `column_border_enabled`, `column_border_radius`, `folder_reorder_enabled` |
| General | Colonnes > Encart | `G Encart` | appli | `resize_badge_position`, `resize_badge_font_family`, `resize_badge_bg_color`, `resize_badge_border_enabled`, `resize_badge_border_radius` |
| General | Colonnes > Entetes | `G Entetes` | appli | `header_visible`, `header_height`, `header_padding`, `header_color`, `header_radius`, `header_border_enabled`, `header_icon_right_padding`, `header_font_family` |
| General | Colonnes > Lignes > Lignes | `G Lignes` | appli | `item_row_height`, `item_row_spacing`, `item_header_gap`, `item_row_bg_color`, `item_row_border_enabled` |
| General | Colonnes > Lignes > Texte | `G Texte` | appli | `item_font_family`, `item_text_padding`, `item_ext_color_enabled` |
| General | Colonnes > Lignes > Icone | `G Icone` | appli | `item_icon_size`, `item_icon_padding_left` |
| General | Colonnes > Lignes > Apercu | `G Apercu` | appli | `item_image_padding`, `item_image_border_enabled`, `item_image_shadow_enabled`, `item_image_radius`, `item_image_ratio` |
| General | Colonnes > Raccourci | `Raccourci` | appli | `shortcut_font_family` |
| General | Colonnes > Selection > Focus | `Selection : Focus` | appli | `item_selection_focus_color`, `item_selection_padding`, `item_selection_border_enabled`, `item_selection_radius`, `item_selection_edge_border` |
| General | Colonnes > Selection > Non focus | `Selection : Non focus` | appli | `item_selection_unfocus_color`, `item_selection_unfocus_padding`, `item_selection_unfocus_border_enabled`, `item_selection_unfocus_radius`, `item_selection_unfocus_edge_border` |
| General | Colonnes > Selection > Survol | `Selection : Survol` | appli | `item_hover_color`, `item_selection_hover_padding`, `item_selection_hover_border_enabled`, `item_selection_hover_radius`, `item_selection_hover_edge_border` |
| General | Colonnes > Selection > Non selectionne | `Selection : Non selectionne` | appli | `item_idle_color`, `item_selection_idle_padding`, `item_selection_idle_border_enabled`, `item_selection_idle_radius`, `item_selection_idle_edge_border` |
| General | Colonnes spéciales > Colonne Projets > Icône de niveaux | `Projets : Icone de niveaux` | appli | `step_badge_width`, `step_badge_border_enabled`, `step_badge_border_smoothing`, `step_badge_radius`, `step_badge_text_color_base2`, `step_badge_text_color_base3`, `step_badge_text_color_base4`, `step_badge_text_color_base5`, `… (+4)` |
| General | Colonnes spéciales > Colonne Focus > Image | `Focus : Image` | appli | `preview_padding`, `preview_radius`, `preview_shadow_enabled`, `preview_image_ratio` |
| General | Colonnes spéciales > Colonne Focus > Zone titre | `Focus : Zone titre` | appli | `preview_title_zone_height`, `preview_title_font_family`, `preview_title_padding`, `preview_status_font_family`, `preview_status_font_color_idle`, `preview_status_padding` |
| General | Application | `Application` | appli | `root_path`, `default_preset`, `auto_collapse_set_columns` |
| General | Application > Chargement et génération automatique | `Chargement et génération automatique` | appli | `auto_settings_enabled`, `auto_settings_when`, `auto_settings_delay`, `auto_moodboard_enabled`, `auto_moodboard_when`, `auto_moodboard_delay`, `auto_video_enabled`, `auto_video_when`, `… (+1)` |
| General | Dossiers et fichiers à omettre | `Omettre` | appli | `application_omit_dir_names`, `application_omit_file_names` |
| General | LUT | `LUT` | appli | `lut_test_images` |
| General | Barre de navigation | `Barre de navigation (appli)` | appli | `navtool_bottom_enabled`, `navtool_title_font_family`, `navtool_height`, `navtool_extra_height`, `navtool_bg_color`, `navtool_border_enabled`, `navtool_corner_radius`, `navtool_hover_bg_color`, `… (+3)` |
| General | Barre de navigation > Icônes | `Barre de navigation : Icones (appli)` | appli | `ui_icon:app_logo`, `ui_icon:navbar_browse`, `ui_icon:navbar_presets`, `ui_icon:settings_gear`, `ui_icon:navbar_theme`, `ui_icon:navbar_columns`, `ui_icon:navbar_viewer`, `ui_icon:navbar_text_editor`, `… (+16)` |
| General | Barre de navigation > Cheminement | `Barre de navigation : Cheminement` | fm_theme | `crumb_left_spacing`, `crumb_spacing`, `crumb_cut_border_active`, `crumb_cut_border_others`, `crumb_bg_color`, `crumb_border_enabled`, `crumb_corner_radius`, `crumb_active_bg_color`, `… (+4)` |
| General | Barre de navigation > Cadre des modules | `Barre de navigation : Cadre des modules` | appli | `viewer_group_bg_color`, `viewer_group_border_enabled`, `viewer_group_corner_radius`, `viewer_group_label_enabled`, `viewer_group_label_font_family`, `viewer_group_padding`, `viewer_group_margin`, `viewer_group_btn_bg_color`, `… (+4)` |
| General | Barre de navigation > Fenêtres additionnelles | `Barre de navigation : Fenetres additionnelles` | fm_theme | `extra_window_title_height`, `extra_window_title_bg`, `extra_window_title_text_font_family`, `extra_window_title_button_width`, `extra_window_title_button_radius`, `extra_window_title_line_enabled` |
| General | ICONES > General | `Icones : General` | appli | `ui_icon:pin`, `ui_icon:folder_default`, `ui_icon:file_default`, `ui_icon:settings_gear`, `ui_icon:settings_style`, `ui_icon:shortcut` |
| General | ICONES > Couleur des dossiers | `Icones : Couleurs des dossiers` | appli | `folder_icon_color_standard`, `folder_text_color_standard_enabled`, `folder_text_color_standard_from_icon`, `folder_text_color_standard`, `folder_icon_color_shortcut`, `folder_text_color_shortcut_enabled`, `folder_text_color_shortcut_from_icon`, `folder_text_color_shortcut`, `… (+4)` |
| General | ICONES > Logiciels | `Icones : Logiciels` | appli | `custom_softwares` |
| Thème | Général | `Thème : Général` | fm_theme | `ui_scale`, `window_radius`, `dimmed_opacity`, `dimmed_text_opacity`, `dimmed_icon_opacity`, `navtool_icon_base_color`, `icon_margin`, `icon_library_style`, `… (+4)` |
| Thème | Couleurs | `Couleurs` | appli | `colors:skinAccent`, `colors:navbar`, `colors:skinN1`, `colors:selCur`, `colors:skinN2`, `colors:selDone`, `colors:fond`, `colors:hover`, `… (+9)` |
| Thème | Polices principales | `Polices principales` | fm_theme | `font_main`, `font_info`, `font_titles`, `font_files`, `font_code` |
| Thème | TITRES > Polices | `Titre : Polices` | fm_theme | `title_level1_font_family`, `title_level2_font_family`, `title_level3_font_family`, `title_level4_font_family`, `title_level5_font_family` |
| Thème | TITRES > Paragraphes > Niveau 1 | `Titre : Fond 1` | fm_theme | `title_level1_bg_enabled`, `title_level1_bg_margin`, `title_level1_bg_padding`, `title_level1_text_padding`, `title_level1_body_padding`, `title_level1_bg_border_enabled`, `title_level1_bg_radius`, `title_level1_open_bg_color`, `… (+4)` |
| Thème | TITRES > Paragraphes > Niveau 2 | `Titre : Fond 2` | fm_theme | `title_level2_bg_enabled`, `title_level2_bg_margin`, `title_level2_bg_padding`, `title_level2_text_padding`, `title_level2_body_padding`, `title_level2_bg_border_enabled`, `title_level2_bg_radius`, `title_level2_open_bg_color`, `… (+4)` |
| Thème | TITRES > Paragraphes > Niveau 3 | `Titre : Fond 3` | fm_theme | `title_level3_bg_enabled`, `title_level3_bg_margin`, `title_level3_bg_padding`, `title_level3_text_padding`, `title_level3_body_padding`, `title_level3_bg_border_enabled`, `title_level3_bg_radius`, `title_level3_open_bg_color`, `… (+4)` |
| Thème | TITRES > Paragraphes > Niveau 4 | `Titre : Fond 4` | fm_theme | `title_level4_bg_enabled`, `title_level4_bg_margin`, `title_level4_bg_padding`, `title_level4_text_padding`, `title_level4_body_padding`, `title_level4_bg_border_enabled`, `title_level4_bg_radius`, `title_level4_open_bg_color`, `… (+4)` |
| Thème | TITRES > Paragraphes > Niveau 5 | `Titre : Fond 5` | fm_theme | `title_level5_bg_enabled`, `title_level5_bg_margin`, `title_level5_bg_padding`, `title_level5_text_padding`, `title_level5_body_padding`, `title_level5_bg_border_enabled`, `title_level5_bg_radius`, `title_level5_open_bg_color`, `… (+4)` |
| Thème | Toggles | `Toggles : Style` | fm_theme | `toggle_style` |
| Thème | Toggles > Toggle 1 > Type | `toggle1 : Type` | fm_theme | `toggle1_kind`, `toggle1_motion`, `toggle1_icon_on`, `toggle1_icon_frames`, `toggle1_anim_ms` |
| Thème | Toggles > Toggle 1 > État OFF | `toggle1 : OFF` | fm_theme | `toggle1_off_bg_width`, `toggle1_off_bg_height`, `toggle1_off_bg_border_enabled`, `toggle1_off_bg_border_radius`, `toggle1_off_bg_color`, `toggle1_off_coche_skin`, `toggle1_off_coche_text`, `toggle1_off_coche_text_font_family`, `… (+1)` |
| Thème | Toggles > Toggle 1 > État ON | `toggle1 : ON` | fm_theme | `toggle1_on_bg_width`, `toggle1_on_bg_height`, `toggle1_on_bg_border_enabled`, `toggle1_on_bg_border_radius`, `toggle1_on_bg_color`, `toggle1_on_coche_skin`, `toggle1_on_coche_text`, `toggle1_on_coche_text_font_family`, `… (+1)` |
| Thème | Toggles > Toggle 2 > Type | `toggle2 : Type` | fm_theme | `toggle2_kind`, `toggle2_motion`, `toggle2_icon_on`, `toggle2_icon_frames`, `toggle2_anim_ms` |
| Thème | Toggles > Toggle 2 > État OFF | `toggle2 : OFF` | fm_theme | `toggle2_off_bg_width`, `toggle2_off_bg_height`, `toggle2_off_bg_border_enabled`, `toggle2_off_bg_border_radius`, `toggle2_off_bg_color`, `toggle2_off_coche_skin`, `toggle2_off_coche_text`, `toggle2_off_coche_text_font_family`, `… (+1)` |
| Thème | Toggles > Toggle 2 > État ON | `toggle2 : ON` | fm_theme | `toggle2_on_bg_width`, `toggle2_on_bg_height`, `toggle2_on_bg_border_enabled`, `toggle2_on_bg_border_radius`, `toggle2_on_bg_color`, `toggle2_on_coche_skin`, `toggle2_on_coche_text`, `toggle2_on_coche_text_font_family`, `… (+1)` |
| Thème | Sliders > Rail | `Slider : Rail` | fm_theme | `slider_track_height`, `slider_track_fill_color`, `slider_track_empty_color`, `slider_track_border_enabled`, `slider_track_radius` |
| Thème | Sliders > Selecteur | `Slider : Selecteur` | fm_theme | `slider_thumb_width`, `slider_thumb_height`, `slider_thumb_color`, `slider_thumb_border_enabled`, `slider_thumb_radius` |
| Thème | Zone de saisie | `Zone de saisie` | fm_theme | `input_bg_color`, `input_border_enabled`, `input_font_family`, `input_corner_radius`, `input_height` |
| Thème | Bouton | `Bouton` | fm_theme | `button_bg_color`, `button_border_enabled`, `button_hover_follow`, `button_hover_color`, `button_hover_border_enabled`, `button_hover_font_family`, `button_hover_corner_radius`, `button_hover_offset_x`, `… (+19)` |
| Thème | Tableaux | `Tableaux` | appli | `columns_resizable`, `table_bg_color`, `table_border_enabled`, `table_shadow_enabled`, `table_inner_h_enabled`, `table_inner_v_enabled`, `table_radius`, `table_cell_padding`, `… (+5)` |
| Thème | Tabs | `Tabs` | fm_theme | `tabs_bg_color`, `tabs_active_bg_color`, `tabs_hover_bg_color`, `tabs_strip_color`, `tabs_border_enabled`, `tabs_inactive_border_enabled`, `tabs_font_family`, `tabs_corner_radius`, `… (+3)` |
| Thème | Barres d'outils > Grille | `Palette : Grille` | fm_theme | `palette_cell_size`, `palette_cell_gap`, `palette_margin`, `palette_snap_distance` |
| Thème | Barres d'outils > Barre | `Palette : Barre` | fm_theme | `palette_bg_color`, `palette_border_enabled`, `palette_corner_radius`, `palette_shadow_enabled`, `palette_drag_border_color`, `palette_snap_side`, `palette_snap_separator`, `palette_snap_header_color`, `… (+2)` |
| Thème | Barres d'outils > En-tête | `Palette : En-tete` | fm_theme | `palette_header_shown`, `palette_header_height`, `palette_header_bg_color`, `palette_title_font_family`, `palette_title_align`, `palette_title_caps`, `palette_title_tracking`, `palette_grip_enabled`, `… (+1)` |
| Thème | Barres d'outils > Icônes | `Palette : Icones` | fm_theme | `palette_cell_bg_color`, `palette_cell_border_enabled`, `palette_cell_radius`, `palette_icon_ratio`, `palette_icon_color`, `palette_cell_hover_color`, `palette_cell_active_color`, `palette_cell_active_border_color`, `… (+4)` |
| Thème | Barres d'outils > Contrôleur | `Palette : Controleur` | fm_theme | `palette_bar_bg_color`, `palette_bar_border_enabled`, `palette_bar_radius`, `palette_bar_join_gap`, `palette_bar_padding`, `palette_bar_font_family`, `palette_bar_value_color`, `palette_bar_grip_enabled`, `… (+3)` |
| Thème | Barres d'outils > Contrôleur > Slider | `Palette : Slider` | fm_theme | `palette_slider_style`, `palette_slider_track_height`, `palette_slider_thumb_width`, `palette_slider_thumb_height`, `palette_slider_radius`, `palette_slider_track_color`, `palette_slider_fill_color`, `palette_slider_thumb_color`, `… (+1)` |
| Thème | Barres d'outils > Contrôleur > Liste déroulante | `Palette : Liste` | fm_theme | `palette_select_min_width`, `palette_select_height` |
| Thème | Barres d'outils > Contrôleur > Zone de saisie | `Palette : Saisie` | fm_theme | `palette_input_min_width`, `palette_input_height` |
| Thème | Barres d'outils > Contrôleur > Toggle | `Palette : Toggle` | fm_theme | `palette_toggle_style`, `palette_toggle_labels` |
| Thème | Menu contextuel > Menu | `Menu contextuel : Menu` | fm_theme | `ctx_menu_editable`, `ctx_menu_bg`, `ctx_menu_border_enabled`, `ctx_menu_border_color`, `ctx_menu_border_radius`, `ctx_menu_shadow_enabled`, `ctx_menu_padding` |
| Thème | Menu contextuel > Lignes | `Menu contextuel : Lignes` | fm_theme | `ctx_menu_font_family`, `ctx_menu_item_padding`, `ctx_menu_disabled_color`, `ctx_menu_ghost_color`, `ctx_menu_current_color`, `ctx_menu_icon_size`, `ctx_menu_control_gap`, `ctx_menu_slider_width` |
| Thème | Menu contextuel > Survol | `Menu contextuel : Survol` | fm_theme | `ctx_menu_hover_color`, `ctx_menu_hover_text_color`, `ctx_menu_hover_border_enabled`, `ctx_menu_hover_radius`, `ctx_menu_hover_margin` |
| Thème | Menu contextuel > Libellés | `Menu contextuel : Libelles` | fm_theme | `ctx_menu_label_font_family`, `ctx_menu_label_bg`, `ctx_menu_label_padding`, `ctx_menu_label_uppercase` |
| Thème | Menu contextuel > Séparateurs | `Menu contextuel : Separateurs` | fm_theme | `ctx_menu_sep_color`, `ctx_menu_sep_thickness`, `ctx_menu_sep_padding` |
| Thème | Fenêtres additionnelles | `Fenêtres additionnelles` | fm_theme | `extra_window_bg_color`, `extra_window_border_enabled`, `extra_window_radius`, `extra_window_shadow_enabled`, `extra_window_buttons_line_enabled` |
| Thème | Barre de navigation | `Barre de navigation` | fm_theme | `navbar_bg_color`, `navbar_bottom_enabled`, `navbar_title_font_family`, `navbar_height` |
| Thème | Barre de navigation > Boutons fenêtre | `Barre de navigation : Boutons fenetre` | fm_theme | `navbar_winbtn_size`, `navbar_winbtn_margin`, `navbar_winbtn_padding`, `navbar_winbtn_bg_color`, `navbar_winbtn_border_enabled`, `navbar_winbtn_corner_radius`, `navbar_winbtn_hover_bg_color`, `navbar_winbtn_close_hover_bg_color` |
| Thème | Barre de navigation > Icônes | `Barre de navigation : Icones` | appli | `ui_icon:navbar_min`, `ui_icon:navbar_max`, `ui_icon:navbar_close`, `ui_icon:navbar_pin` |
| Thème | Barre d'état | `Barre d'état` | fm_theme | `statusbar_height`, `statusbar_bg_color`, `statusbar_top_enabled`, `statusbar_padding_x`, `statusbar_spacing`, `statusbar_path_font_family`, `statusbar_info_font_family` |
| Module vidéo | Ouverture | `Vidéo : Ouverture` | appli | `video_open_videos`, `video_open_sequences`, `video_detect_sequences` |
| Module vidéo | Affichage | `Vidéo : Affichage` | appli | `video_bg_color`, `video_default_zoom`, `video_fit_margin`, `video_wheel_zoom`, `video_zoom_step`, `video_interpolation`, `video_mipmaps`, `video_pan`, `… (+15)` |
| Module vidéo | Informations en surimpression | `Vidéo : Informations` | appli | `video_info_enabled`, `video_info_opacity`, `video_info_bg`, `video_info_font_family`, `video_info_label_color`, `video_info_title_color`, `video_info_corner`, `video_info_margin_x`, `… (+14)` |
| Module vidéo | Lecture | `Vidéo : Lecture` | appli | `video_sequence_fps`, `video_autoplay`, `video_engine`, `video_cache_local_ms`, `video_cache_network_ms`, `video_loop`, `video_end_behavior`, `video_volume`, `… (+8)` |
| Module vidéo | Timeline | `Vidéo : Timeline` | appli | `video_timeline_height`, `video_timeline_tick`, `video_timeline_density`, `video_time_display`, `video_timeline_zoom_step`, `video_timeline_zoom_cursor`, `video_timeline_cache`, `video_timeline_thumbs`, `… (+8)` |
| Module vidéo | Moodboard | `Vidéo : Moodboard` | appli | `video_match_lut_size`, `video_match_intensity`, `video_match_method`, `video_analysis_colors`, `video_analysis_exclude_black`, `video_analysis_exclude_white`, `video_moodboard_bg_color`, `video_moodboard_proxy_width` |
| Module vidéo | Moodboard > Infos dans images | `Vidéo : Infos dans images` | appli | `video_mood_info_format`, `video_mood_info_position`, `video_mood_info_margin_x`, `video_mood_info_margin_y`, `video_mood_info_enabled`, `video_mood_info_timestamp`, `video_mood_info_interval`, `video_mood_info_font_size`, `… (+5)` |
| Module vidéo | Moodboard > Analyse colorimétrique | `Vidéo : Analyse colorimétrique` | appli | `video_analysis_order`, `video_analysis_font_family`, `video_analysis_mono_family`, `video_analysis_font_size`, `video_analysis_inspector_width`, `video_analysis_section_padding`, `video_analysis_radius`, `video_analysis_button_height`, `… (+47)` |
| Module vidéo | Aide pédagogique | `Vidéo : Aide pédagogique` | appli | `video_help_enabled`, `video_help_delay`, `video_help_width` |
| Module vidéo | Couleur (OCIO, EXR / TIFF, vidéo) | `Vidéo : Couleur` | appli | `video_ocio_config`, `video_display`, `video_view_video`, `video_view_image`, `video_input_video`, `video_input_exr`, `video_input_float`, `video_input_int`, `… (+4)` |
| Module vidéo | LUT | `Vidéo : LUT` | appli | `video_lut_dir`, `video_lut_default`, `video_lut_auto`, `video_lut_mix`, `video_lut_position` |
| Module vidéo | Performances | `Vidéo : Performances` | appli | `video_cache_mb`, `video_workers`, `video_backend`, `video_diagnostics` |
| Module vidéo | Export et interpolation | `Vidéo : Export` | appli | `video_export_format`, `video_export_codec`, `video_export_crf`, `video_export_preset`, `video_export_dir`, `video_export_color`, `video_export_lut`, `video_export_fps_mode`, `… (+6)` |
| Module Markdown | Ouverture | `Markdown : Ouverture` | appli | `md_open_extensions`, `md_open_md`, `md_default_mode`, `md_live_preview`, `md_preload` |
| Module Markdown | CSS | `Markdown : CSS` | appli | `md_css_path` |
| Module Markdown | Page | `Markdown : Page` | appli | `md_bg_color`, `md_bg_secondary`, `md_accent_color`, `md_selection_color`, `md_module_padding`, `md_content_width`, `md_page_margin`, `md_page_border_enabled`, `… (+10)` |
| Module Markdown | Typographie > Texte | `Markdown : Texte` | appli | `md_text_font_family`, `md_text_weight`, `md_line_height`, `md_letter_spacing` |
| Module Markdown | Typographie > Titre de la note | `Markdown : Titre de la note` | appli | `md_title_enabled`, `md_title_font_family`, `md_title_weight`, `md_title_spacing` |
| Module Markdown | Typographie > Mise en forme | `Markdown : Mise en forme` | appli | `md_bold_color`, `md_bold_weight`, `md_italic_color`, `md_strike_color`, `md_strike_line_color`, `md_strike_bg`, `md_highlight_bg`, `md_highlight_color`, `… (+3)` |
| Module Markdown | Typographie > Liens | `Markdown : Liens` | appli | `md_link_font_family`, `md_link_letter_spacing`, `md_link_underline`, `md_link_hover_underline`, `md_link_unresolved_opacity` |
| Module Markdown | Titres H1-H6 > H1 | `Markdown : H1` | appli | `md_h1_font_family`, `md_h1_weight`, `md_h1_line_height`, `md_h1_space_before`, `md_h1_space_after` |
| Module Markdown | Titres H1-H6 > H2 | `Markdown : H2` | appli | `md_h2_font_family`, `md_h2_weight`, `md_h2_line_height`, `md_h2_space_before`, `md_h2_space_after` |
| Module Markdown | Titres H1-H6 > H3 | `Markdown : H3` | appli | `md_h3_font_family`, `md_h3_weight`, `md_h3_line_height`, `md_h3_space_before`, `md_h3_space_after` |
| Module Markdown | Titres H1-H6 > H4 | `Markdown : H4` | appli | `md_h4_font_family`, `md_h4_weight`, `md_h4_line_height`, `md_h4_space_before`, `md_h4_space_after` |
| Module Markdown | Titres H1-H6 > H5 | `Markdown : H5` | appli | `md_h5_font_family`, `md_h5_weight`, `md_h5_line_height`, `md_h5_space_before`, `md_h5_space_after` |
| Module Markdown | Titres H1-H6 > H6 | `Markdown : H6` | appli | `md_h6_font_family`, `md_h6_weight`, `md_h6_line_height`, `md_h6_space_before`, `md_h6_space_after` |
| Module Markdown | Paragraphes et listes | `Markdown : Paragraphes et listes` | appli | `md_paragraph_spacing`, `md_list_indent`, `md_list_spacing`, `md_bullet_1_char`, `md_bullet_1_vertical_offset`, `md_bullet_2_char`, `md_bullet_2_vertical_offset`, `md_bullet_3_char`, `… (+6)` |
| Module Markdown | Citations | `Markdown : Citations` | appli | `md_quote_font_family`, `md_quote_bg`, `md_quote_border_enabled`, `md_quote_radius`, `md_quote_padding`, `md_quote_spacing` |
| Module Markdown | Callouts | `Markdown : Callouts` | appli | `md_callout_bg`, `md_callout_border_color`, `md_callout_border_width`, `md_callout_title_color`, `md_callout_radius` |
| Module Markdown | Code > Code en ligne | `Markdown : Code en ligne` | appli | `md_code_inline_font_family`, `md_code_inline_weight`, `md_code_inline_bg`, `md_code_inline_radius`, `md_code_inline_padding` |
| Module Markdown | Code > Blocs de code | `Markdown : Blocs de code` | appli | `md_codeblock_font_family`, `md_codeblock_weight`, `md_codeblock_line_height`, `md_codeblock_bg`, `md_codeblock_border_enabled`, `md_codeblock_radius`, `md_codeblock_padding`, `md_codeblock_spacing` |
| Module Markdown | Code > Coloration syntaxique | `Markdown : Coloration syntaxique` | appli | `md_syntax_comment`, `md_syntax_keyword`, `md_syntax_string`, `md_syntax_number`, `md_syntax_def`, `md_syntax_variable`, `md_syntax_type`, `md_syntax_builtin`, `… (+6)` |
| Module Markdown | Tableaux | `Markdown : Tableaux` | appli | `md_table_font_family`, `md_table_head_font_family`, `md_table_grid_color`, `md_table_grid_width`, `md_table_cell_bg`, `md_table_alt_bg`, `md_table_head_bg`, `md_table_radius`, `… (+2)` |
| Module Markdown | Séparateurs | `Markdown : Séparateurs` | appli | `md_hr_color`, `md_hr_thickness`, `md_hr_spacing` |
| Module Markdown | Images | `Markdown : Images` | appli | `md_image_max_width`, `md_image_align`, `md_image_radius`, `md_image_spacing` |
| Module Markdown | Éditeur | `Markdown : Éditeur` | appli | `md_caret_color`, `md_caret_width`, `md_code_file_font_family`, `md_code_file_line_height`, `md_code_file_bg`, `md_active_line_bg`, `md_line_numbers`, `md_note_line_numbers`, `… (+4)` |
| Module Markdown | Barre d'outils | `Markdown : Barre d'outils` | appli | `md_toolbar_enabled` |
| Board | Barre de sélection > Général | `Board : Barre de sélection` | appli | `board_modulebar_buttons`, `board_modulebar_long_press_ms`, `board_modulebar_reset`, `board_modulebar_alt_solo`, `board_modulebar_pill`, `board_modulebar_fold_style`, `board_modules_fade_opacity`, `board_modules_fade_saturation` |
| Board | Barre de sélection > Aspect | `Board : Barre de sélection : Aspect` | appli | `board_modulebar_bg_color`, `board_modulebar_border_color`, `board_modulebar_icon_size`, `board_modulebar_button_size`, `board_modulebar_spacing`, `board_modulebar_padding`, `board_modulebar_row_radius`, `board_modulebar_row_color`, `… (+10)` |
| Board | Barre de sélection > Couleurs des modules | `Board : Barre de sélection : Couleurs des modules` | appli | `board_modulebar_color_miro`, `board_modulebar_color_cad`, `board_modulebar_color_design`, `board_modulebar_color_tableur`, `board_modulebar_color_illustrator`, `board_modulebar_color_photoshop`, `board_modulebar_color_pdf` |
| Board | Barre de sélection > Languette et pastille | `Board : Barre de sélection : Languette et pastille` | appli | `board_modulebar_tab_width`, `board_modulebar_tab_height`, `board_modulebar_tab_color`, `board_modulebar_tab_ink`, `board_modulebar_pill_color`, `board_modulebar_pill_font_size` |
| Board | Barre de sélection > Icônes | `Board : Barre de sélection : Icônes` | appli | `ui_icon:ui_board_miro`, `ui_icon:ui_board_cad`, `ui_icon:ui_board_design`, `ui_icon:ui_board_tableur`, `ui_icon:ui_board_illustrator`, `ui_icon:ui_board_photoshop`, `ui_icon:ui_board_pdf`, `ui_icon:ui_board_show`, `… (+22)` |
| Board | Ouverture | `Board : Ouverture` | appli | `board_open_cad_drawings`, `board_cad_import_blocks` |
| Board | Navigation | `Board : Navigation` | appli | `board_zoom_speed`, `board_zoom_fine` |
| Board | Grille | `Board : Grille` | appli | `board_grid_step`, `board_grid_unit`, `board_grid_factor`, `board_grid_levels`, `board_grid_fade_start`, `board_grid_fade_full`, `board_grid_origin_x`, `board_grid_origin_y`, `… (+9)` |
| MRO | Magnétisme | `MRO` | appli | `board_snap_enabled`, `board_snap_objects`, `board_snap_grid`, `board_snap_resize`, `board_snap_guides`, `board_snap_doc_guides`, `board_snap_inner_guides`, `board_snap_frame_guides`, `… (+1)` |
| MRO | Barres d'outils | `MRO : Barres d'outils` | appli | `board_toolbar_bg_color`, `board_toolbar_border_enabled`, `board_toolbar_corner_radius`, `board_toolbar_padding`, `board_toolbar_shadow_enabled`, `board_toolbar_text_font_family`, `board_toolbar_invert`, `board_toolbar_focus_width`, `… (+4)` |
| MRO | Menus contextuels > Menu | `MRO : Menu contextuel : Menu` | appli | `board_ctx_menu_editable`, `board_ctx_menu_bg`, `board_ctx_menu_border_enabled`, `board_ctx_menu_border_color`, `board_ctx_menu_border_radius`, `board_ctx_menu_shadow_enabled`, `board_ctx_menu_padding` |
| MRO | Menus contextuels > Lignes | `MRO : Menu contextuel : Lignes` | appli | `board_ctx_menu_font_family`, `board_ctx_menu_item_padding`, `board_ctx_menu_disabled_color`, `board_ctx_menu_ghost_color`, `board_ctx_menu_current_color`, `board_ctx_menu_icon_size`, `board_ctx_menu_control_gap`, `board_ctx_menu_slider_width` |
| MRO | Menus contextuels > Survol | `MRO : Menu contextuel : Survol` | appli | `board_ctx_menu_hover_color`, `board_ctx_menu_hover_text_color`, `board_ctx_menu_hover_border_enabled`, `board_ctx_menu_hover_radius`, `board_ctx_menu_hover_margin` |
| MRO | Menus contextuels > Libellés | `MRO : Menu contextuel : Libelles` | appli | `board_ctx_menu_label_font_family`, `board_ctx_menu_label_bg`, `board_ctx_menu_label_padding`, `board_ctx_menu_label_uppercase` |
| MRO | Menus contextuels > Séparateurs | `MRO : Menu contextuel : Separateurs` | appli | `board_ctx_menu_sep_color`, `board_ctx_menu_sep_thickness`, `board_ctx_menu_sep_padding` |
| MRO | Icônes | `MRO : Icones` | appli | `ui_icon:ui_board_select`, `ui_icon:ui_board_hand`, `ui_icon:ui_board_sticky`, `ui_icon:ui_board_text`, `ui_icon:ui_board_shape`, `ui_icon:ui_board_connector`, `ui_icon:ui_board_draw`, `ui_icon:ui_board_comment`, `… (+26)` |
| CAD | Unités | `CAD : Unités` | appli | `board_cad_unit` |
| CAD | Types de ligne | `CAD : Types de ligne` | appli | `board_cad_linetypes` |
| CAD | Accrochages | `CAD : Accrochages` | appli | `board_cad_osnap`, `board_cad_osnap_end`, `board_cad_osnap_mid`, `board_cad_osnap_cen`, `board_cad_osnap_gcen`, `board_cad_osnap_qua`, `board_cad_osnap_int`, `board_cad_osnap_appint`, `… (+13)` |
| CAD | Suivi et saisie | `CAD : Suivi et saisie` | appli | `board_cad_ortho`, `board_cad_polar`, `board_cad_polar_increment`, `board_cad_polar_custom`, `board_cad_otrack`, `board_cad_track_polar`, `board_cad_track_color`, `board_cad_dyn` |
| CAD | Grille | `CAD : Grille` | appli | `board_cad_grid_snap` |
| CAD | Réticule | `CAD : Réticule` | appli | `board_cad_crosshair`, `board_cad_crosshair_size`, `board_cad_crosshair_full`, `board_cad_crosshair_auto_color`, `board_cad_crosshair_color`, `board_cad_crosshair_negative`, `board_cad_crosshair_negative_tol`, `board_cad_pickbox`, `… (+4)` |
| CAD | Sélection > Clic et poignées | `CAD : Sélection et poignées` | appli | `board_cad_pickadd`, `board_cad_grip_size`, `board_cad_grip_color`, `board_cad_grip_border_color` |
| CAD | Sélection > Fenêtre (de gauche à droite) | `CAD : Fenêtre de sélection` | appli | `board_cad_window_bg`, `board_cad_window_border_enabled`, `board_cad_window_radius`, `board_cad_window_line` |
| CAD | Sélection > Capture (de droite à gauche) | `CAD : Capture` | appli | `board_cad_crossing_bg`, `board_cad_crossing_border_enabled`, `board_cad_crossing_radius`, `board_cad_crossing_line` |
| CAD | Ajuster | `CAD : Ajuster` | appli | `board_cad_trim_mode`, `board_cad_trim_edge` |
| CAD | Affichage | `CAD : Affichage` | appli | `board_cad_gpu`, `board_cad_lineweights`, `board_cad_aa_samples`, `board_cad_aa_filter`, `board_cad_antialiasing`, `board_cad_linear_blend`, `board_cad_crisp_lines`, `board_cad_dense_px`, `… (+3)` |
| CAD | Cotations | `CAD : Cotations` | appli | `board_cad_dim_text`, `board_cad_dim_arrow`, `board_cad_dim_gap`, `board_cad_dim_over`, `board_cad_dim_scale`, `board_cad_dim_arrow_kind`, `board_cad_dim_decimals`, `board_cad_dim_baseline` |
| CAD | Hachures | `CAD : Hachures` | appli | `board_cad_hatch_pattern`, `board_cad_hatch_angle`, `board_cad_hatch_spacing`, `board_cad_hatch_alpha` |
| CAD | Textes | `CAD : Textes` | appli | `board_cad_text_height`, `board_cad_text_font`, `board_cad_text_justify`, `board_cad_mtext_justify`, `board_cad_text_spacing` |
| CAD | Points | `CAD : Points` | appli | `board_cad_point_mode`, `board_cad_point_size` |
| CAD | Raccourcis clavier | `CAD : Raccourcis clavier` | appli | `board_cad_pgp_path` |
| CAD | Icônes | `CAD : Icônes` | appli | `ui_icon:ui_board_cad_line`, `ui_icon:ui_board_cad_pline`, `ui_icon:ui_board_cad_circle`, `ui_icon:ui_board_cad_arc`, `ui_icon:ui_board_cad_rect`, `ui_icon:ui_board_cad_hatch`, `ui_icon:ui_board_cad_polygon`, `ui_icon:ui_board_cad_ellipse`, `… (+32)` |
| Design | Nouveau design | `Design : Nouveau design` | appli | `board_design_page_format`, `board_design_page_bg` |
| Design | Nouveaux éléments | `Design : Nouveaux éléments` | appli | `board_design_font`, `board_design_text_color`, `board_design_heading_size`, `board_design_subheading_size`, `board_design_body_size`, `board_design_shape_fill` |
| Design | Sélection et repères | `Design : Sélection et repères` | appli | `board_design_accent`, `board_design_handle_size`, `board_design_guide_color`, `board_design_page_titles`, `board_design_rulers` |
| Design | Clavier | `Design : Clavier` | appli | `board_design_nudge`, `board_design_nudge_big` |
| Design | Présentation | `Design : Présentation` | appli | `board_design_transition_ms`, `board_design_animation_ms` |
| Design | Icônes | `Design : Icônes` | appli | `ui_icon:ui_board_design_templates`, `ui_icon:ui_board_design_elements`, `ui_icon:ui_board_design_text`, `ui_icon:ui_board_design_images`, `ui_icon:ui_board_design_layers`, `ui_icon:ui_board_design_export`, `ui_icon:ui_board_design_present`, `ui_icon:ui_board_design_add_page` |
| Tableur | Ouverture | `Tableur : Ouverture` | appli | `tableur_open_double_click` |
| Tableur | Nouveaux classeurs | `Tableur : Nouveaux classeurs` | appli | `tableur_font_family`, `tableur_font_size`, `tableur_calc_mode` |
| Tableur | Saisie | `Tableur : Saisie` | appli | `tableur_enter_moves`, `tableur_date_order` |
| Tableur | Formules et nombres | `Tableur : Formules et nombres` | appli | `tableur_formula_lang`, `tableur_decimal_sep`, `tableur_thousands_sep`, `tableur_lang` |
| Tableur | Couleurs | `Tableur : Couleurs` | appli | `tableur_background`, `tableur_text`, `tableur_grid`, `tableur_header_bg`, `tableur_header_text`, `tableur_selection` |
| Illustrator | Sélection et repères | `Illustrator : Sélection et repères` | appli | `board_ill_accent`, `board_ill_handle_size`, `board_ill_anchor_size`, `board_ill_smart_guides`, `board_ill_snap_px` |
| Illustrator | Nouveaux objets | `Illustrator : Nouveaux objets` | appli | `board_ill_artboard_format`, `board_ill_font`, `board_ill_text_size`, `board_ill_units` |
| Illustrator | Clavier et outils | `Illustrator : Clavier et outils` | appli | `board_ill_nudge`, `board_ill_nudge_big`, `board_ill_pencil_fidelity`, `board_ill_trace_detail` |
| Illustrator | Export | `Illustrator : Export` | appli | `board_ill_pdf_dpi` |
| Illustrator | Icônes | `Illustrator : Icônes` | appli | `ui_icon:ui_board_ill_select`, `ui_icon:ui_board_ill_direct`, `ui_icon:ui_board_ill_pen`, `ui_icon:ui_board_ill_add_anchor`, `ui_icon:ui_board_ill_delete_anchor`, `ui_icon:ui_board_ill_convert`, `ui_icon:ui_board_ill_text`, `ui_icon:ui_board_ill_brush`, `… (+23)` |
| Photoshop | Établi | `Photoshop : Établi` | appli | `board_ps_checker_a`, `board_ps_checker_b`, `board_ps_checker_size`, `board_ps_bench_color`, `board_ps_frame_color`, `board_ps_selection_color` |
| Photoshop | Navigation | `Photoshop : Navigation` | appli | `board_ps_zoom_pct`, `board_ps_max_zoom_pct`, `board_ps_cursor_outline` |
| Photoshop | Mémoire | `Photoshop : Mémoire` | appli | `board_ps_history_mb` |
| Photoshop | Documents | `Photoshop : Documents` | appli | `board_ps_new_paste_clipboard` |
| PDF | Affichage | `PDF : Affichage` | appli | `pdf_default_fit`, `pdf_default_zoom`, `pdf_default_mode`, `pdf_view_background`, `pdf_show_thumbnails`, `pdf_left_panel`, `pdf_actual_size_dpi` |
| PDF | Rendu et mémoire | `PDF : Rendu et mémoire` | appli | `pdf_cache_mb`, `pdf_prefetch_screens` |
| PDF | Formulaires | `PDF : Formulaires` | appli | `pdf_forms_highlight`, `pdf_forms_highlight_color`, `pdf_forms_highlight_alpha`, `pdf_javascript`, `pdf_js_alerts`, `pdf_design_font_size` |
| PDF | Ouverture et enregistrement | `PDF : Ouverture et enregistrement` | appli | `pdf_open_double_click`, `pdf_save_mode`, `pdf_autosave_recovery_s` |
| PDF | Sécurité | `PDF : Sécurité` | appli | `pdf_confirm_links`, `pdf_warn_active_content` |
| PDF | Commentaires | `PDF : Commentaires` | appli | `pdf_annot_color`, `pdf_annot_ink_color`, `pdf_annot_width` |
| PDF | OCR et impression | `PDF : OCR et impression` | appli | `pdf_ocr_languages`, `pdf_print_dpi`, `pdf_print_annotations` |
| Visionneuse | Affichage | `Visionneuse` | appli | `viewer_filmstrip_enabled`, `viewer_slide_enabled`, `viewer_gallery_ripple_enabled`, `viewer_scroll_animated`, `viewer_info_enabled`, `viewer_recursive` |
| Visionneuse | Tableau | `Visionneuse : Tableau` | appli | `viewer_film_table_border_enabled`, `viewer_film_table_border_radius`, `viewer_film_table_shadow_enabled`, `viewer_film_table_font_family`, `viewer_film_table_bg`, `viewer_film_table_inner_h_enabled`, `viewer_film_table_inner_v_enabled`, `viewer_film_table_focus_color`, `… (+1)` |
| Visionneuse | Cellules | `Visionneuse : Cellule image` | appli | `viewer_film_image_cell_border_enabled`, `viewer_film_image_cell_border_radius`, `viewer_film_bg_padding`, `viewer_film_image_padding`, `viewer_film_attr_padding`, `viewer_film_image_border_enabled`, `viewer_film_image_border_radius`, `viewer_film_image_shadow_enabled`, `… (+2)` |
| Visionneuse | Focus | `Visionneuse : Focus` | appli | `viewer_focus_image_border_enabled`, `viewer_focus_image_border_radius`, `viewer_focus_image_shadow_enabled` |
| Visionneuse | Filtres | `Visionneuse : Filtres` | appli | `viewer_filter_color_1_name`, `viewer_filter_color_1`, `viewer_filter_color_2_name`, `viewer_filter_color_2`, `viewer_filter_color_3_name`, `viewer_filter_color_3`, `viewer_filter_color_4_name`, `viewer_filter_color_4`, `… (+8)` |
| Visionneuse | Icônes | `Visionneuse : Icones` | appli | `ui_icon:viewer_hide`, `ui_icon:viewer_show`, `ui_icon:viewer_gallery`, `ui_icon:viewer_single`, `ui_icon:viewer_filter`, `ui_icon:viewer_recursive`, `ui_icon:viewer_star_on`, `ui_icon:viewer_star_off`, `… (+3)` |
| Module Typographie | Secours | `Typographie : Secours` | appli | `typo_autosave_seconds` |
| Module Typographie | Nouveaux projets | `Typographie : Nouveaux projets` | appli | `typo_new_upm`, `typo_new_ascender`, `typo_new_descender`, `typo_new_cap_height`, `typo_new_x_height` |
| Module Typographie | Éditeur | `Typographie : Éditeur` | appli | `typo_display`, `typo_node_size`, `typo_show_grid`, `typo_grid_step`, `typo_show_rulers`, `typo_snap_distance`, `typo_snap_integer`, `typo_wheel_zoom` |
| Module Typographie | Tracé | `Typographie : Tracé` | appli | `typo_quadratic_tolerance`, `typo_pencil_error`, `typo_pencil_smoothing`, `typo_corner_radius`, `typo_nib_width`, `typo_nib_angle`, `typo_brush_width`, `typo_use_pressure` |
| Module Typographie | Grille et aperçu | `Typographie : Grille et aperçu` | appli | `typo_cell_size`, `typo_preview_size` |
| Module Typographie | Couleurs | `Typographie : Couleurs` | appli | `typo_canvas_bg`, `typo_fill`, `typo_outline`, `typo_node`, `typo_node_smooth`, `typo_handle`, `typo_selection`, `typo_metrics`, `… (+4)` |
| PDF | Affichage | `PDF : Affichage` | appli | `pdf_default_fit`, `pdf_default_zoom`, `pdf_default_mode`, `pdf_view_background`, `pdf_show_thumbnails`, `pdf_left_panel`, `pdf_actual_size_dpi` |
| PDF | Rendu et mémoire | `PDF : Rendu et mémoire` | appli | `pdf_cache_mb`, `pdf_prefetch_screens` |
| PDF | Formulaires | `PDF : Formulaires` | appli | `pdf_forms_highlight`, `pdf_forms_highlight_color`, `pdf_forms_highlight_alpha`, `pdf_javascript`, `pdf_js_alerts`, `pdf_design_font_size` |
| PDF | Ouverture et enregistrement | `PDF : Ouverture et enregistrement` | appli | `pdf_open_double_click`, `pdf_save_mode`, `pdf_autosave_recovery_s` |
| PDF | Sécurité | `PDF : Sécurité` | appli | `pdf_confirm_links`, `pdf_warn_active_content` |
| PDF | Commentaires | `PDF : Commentaires` | appli | `pdf_annot_color`, `pdf_annot_ink_color`, `pdf_annot_width` |
| PDF | OCR et impression | `PDF : OCR et impression` | appli | `pdf_ocr_languages`, `pdf_print_dpi`, `pdf_print_annotations` |
| Agenda | Affichage | `Agenda : Affichage` | appli | `agenda_theme`, `agenda_accent`, `agenda_today_color`, `agenda_density`, `agenda_default_view`, `agenda_restore_state`, `agenda_first_weekday`, `agenda_time_format`, `… (+17)` |
| Agenda | Comportement | `Agenda : Comportement` | appli | `agenda_default_duration`, `agenda_default_calendar`, `agenda_default_reminder`, `agenda_create_mode`, `agenda_week_click`, `agenda_month_click`, `agenda_recurring_move`, `agenda_confirm_delete`, `… (+2)` |
| Agenda | Rappels | `Agenda : Rappels` | appli | `agenda_reminders_enabled`, `agenda_notify_mode`, `agenda_snooze_minutes`, `agenda_missed_minutes` |
| Agenda | Données | `Agenda : Données` | appli | `agenda_panel_data`, `agenda_timezone`, `agenda_data_dir`, `agenda_backup_daily`, `agenda_backup_keep`, `agenda_backup_dir` |
| Agenda | Synchronisation | `Agenda : Synchronisation` | appli | `agenda_panel_google`, `agenda_sync_auto`, `agenda_sync_interval_min`, `agenda_sync_on_change`, `agenda_conflict_policy`, `agenda_server_url` |
| Tâches | Affichage | `Tâches : Affichage` | appli | `taches_theme`, `taches_accent`, `taches_density`, `taches_start_view`, `taches_show_sidebar`, `taches_sidebar_width`, `taches_show_details`, `taches_show_done`, `… (+3)` |
| Tâches | Comportement | `Tâches : Comportement` | appli | `taches_new_on_top`, `taches_default_list`, `taches_confirm_delete`, `taches_drag_requires_ctrl` |
| Tâches | Rappels | `Tâches : Rappels` | appli | `taches_reminders_enabled`, `taches_remind_at_due`, `taches_notify_mode`, `taches_snooze_minutes`, `taches_missed_minutes` |
| Tâches | Synchronisation | `Tâches : Synchronisation` | appli | `taches_panel_google`, `taches_sync_auto`, `taches_sync_interval_min`, `taches_sync_on_change`, `taches_conflict_policy` |
| Tâches | Données | `Tâches : Données` | appli | `taches_data_dir`, `taches_backup_daily`, `taches_backup_keep` |

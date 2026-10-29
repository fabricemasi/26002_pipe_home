# Inventaire des réglages pour fm_theme (étape 1)

Produit par `python tools/inventaire_reglages.py` (ne pas éditer à la main : corriger le script, `EXCEPTIONS` ou les familles, puis relancer). Plan : `fm_theme.md`, « Ordre de migration ».

| Catégorie | Clés |
|---|---|
| Aspect générique → fm_theme | 420 |
| Aspect propre à fm_browser → références vers fm_theme | 960 |
| Fonctionnement → reste dans fm_browser | 240 |

## Aspect générique → fm_theme

<details><summary><code>button_</code> : 20 clés (bouton)</summary>

`button_frame`, `button_radius`, `button_bg_color`, `button_border_enabled`, `button_border`, `button_border_thickness`, `button_corner_radius`, `button_font_family`, `button_font_size`, `button_font_bold`, `button_font_italic`, `button_font_color`, `button_font_smoothing_enabled`, `button_font_smoothing`, `button_shadow_enabled`, `button_shadow`, `button_shadow_size`, `button_shadow_enabled_linked`, `button_border_enabled_linked`, `button_corner_radius_linked`

</details>
<details><summary><code>colors</code> : 1 clés (palette)</summary>

`colors`

</details>
<details><summary><code>ctx_</code> : 53 clés (menu contextuel)</summary>

`ctx_menu_editable`, `ctx_menu_bg`, `ctx_menu_border_enabled`, `ctx_menu_border`, `ctx_menu_border_thickness`, `ctx_menu_border_color`, `ctx_menu_border_radius`, `ctx_menu_border_radius_linked`, `ctx_menu_padding`, `ctx_menu_padding_linked`, `ctx_menu_font_family`, `ctx_menu_font_bold`, `ctx_menu_font_italic`, `ctx_menu_font_size`, `ctx_menu_font_smoothing_enabled`, `ctx_menu_font_smoothing`, `ctx_menu_font_color`, `ctx_menu_item_padding`, `ctx_menu_item_padding_linked`, `ctx_menu_hover_color`, `ctx_menu_hover_text_color`, `ctx_menu_hover_radius`, `ctx_menu_hover_radius_linked`, `ctx_menu_hover_border_enabled`, `ctx_menu_hover_border`, `ctx_menu_hover_border_thickness`, `ctx_menu_hover_border_enabled_linked`, `ctx_menu_hover_margin`, `ctx_menu_hover_margin_linked`, `ctx_menu_disabled_color`, `ctx_menu_icon_size`, `ctx_menu_control_gap`, `ctx_menu_slider_width`, `ctx_menu_label_font_family`, `ctx_menu_label_font_bold`, `ctx_menu_label_font_italic`, `ctx_menu_label_font_size`, `ctx_menu_label_font_smoothing_enabled`, `ctx_menu_label_font_smoothing`, `ctx_menu_label_font_color`, `ctx_menu_label_bg`, `ctx_menu_label_padding`, `ctx_menu_label_padding_linked`, `ctx_menu_label_uppercase`, `ctx_menu_sep_color`, `ctx_menu_sep_thickness`, `ctx_menu_sep_padding`, `ctx_menu_sep_padding_linked`, `ctx_menu_shadow_enabled`, `ctx_menu_shadow`, `ctx_menu_shadow_size`, `ctx_menu_shadow_enabled_linked`, `ctx_menu_border_enabled_linked`

</details>
<details><summary><code>divers</code> : 1 clés (échelle générale de l'interface)</summary>

`ui_scale`

</details>
<details><summary><code>extra_</code> : 29 clés (fenêtre additionnelle)</summary>

`extra_window_border_enabled`, `extra_window_border`, `extra_window_border_thickness`, `extra_window_radius`, `extra_window_radius_linked`, `extra_window_title_height`, `extra_window_title_bg`, `extra_window_title_line_enabled`, `extra_window_title_line_color`, `extra_window_title_line_thickness`, `extra_window_buttons_line_enabled`, `extra_window_buttons_line_color`, `extra_window_buttons_line_thickness`, `extra_window_title_button_width`, `extra_window_title_button_height`, `extra_window_title_button_radius`, `extra_window_title_button_radius_linked`, `extra_window_title_text_font_family`, `extra_window_title_text_font_bold`, `extra_window_title_text_font_italic`, `extra_window_title_text_font_size`, `extra_window_title_text_font_smoothing_enabled`, `extra_window_title_text_font_smoothing`, `extra_window_title_text_font_color`, `extra_window_shadow_enabled`, `extra_window_shadow`, `extra_window_shadow_size`, `extra_window_shadow_enabled_linked`, `extra_window_border_enabled_linked`

</details>
<details><summary><code>font_</code> : 9 clés (rôles de texte)</summary>

`font_main`, `font_titles`, `font_folders`, `font_files`, `font_buttons`, `font_colhead`, `font_info`, `font_info2`, `font_code`

</details>
<details><summary><code>input_</code> : 17 clés (champ de saisie)</summary>

`input_frame`, `input_radius`, `input_bg_color`, `input_border_enabled`, `input_border`, `input_border_thickness`, `input_corner_radius`, `input_font_family`, `input_font_size`, `input_font_bold`, `input_font_italic`, `input_font_color`, `input_font_smoothing_enabled`, `input_font_smoothing`, `input_height`, `input_border_enabled_linked`, `input_corner_radius_linked`

</details>
<details><summary><code>slider_</code> : 16 clés (slider)</summary>

`slider_thumb_width`, `slider_thumb_height`, `slider_thumb_color`, `slider_thumb_border`, `slider_thumb_border_enabled`, `slider_thumb_radius`, `slider_thumb_radius_linked`, `slider_track_height`, `slider_track_fill_color`, `slider_track_empty_color`, `slider_track_border`, `slider_track_border_enabled`, `slider_track_radius`, `slider_track_radius_linked`, `slider_thumb_border_enabled_linked`, `slider_track_border_enabled_linked`

</details>
<details><summary><code>table_</code> : 27 clés (tableau)</summary>

`table_radius`, `table_cell_padding_linked`, `table_cell_padding`, `table_head_color`, `table_selection_color`, `table_cell_head_color`, `table_border_enabled`, `table_border`, `table_border_thickness`, `table_above_text_font_family`, `table_above_text_font_bold`, `table_above_text_font_italic`, `table_above_text_font_size`, `table_above_text_font_smoothing_enabled`, `table_above_text_font_smoothing`, `table_above_text_font_color`, `table_inner_h_enabled`, `table_inner_h_color`, `table_inner_h_thickness`, `table_inner_v_enabled`, `table_inner_v_color`, `table_inner_v_thickness`, `table_shadow_enabled`, `table_shadow`, `table_shadow_size`, `table_shadow_enabled_linked`, `table_border_enabled_linked`

</details>
<details><summary><code>tabs_</code> : 26 clés (onglets)</summary>

`tabs_bottom_enabled`, `tabs_bottom_color`, `tabs_bottom_thickness`, `tabs_height`, `tabs_spacing`, `tabs_strip_color`, `tabs_inactive_border_enabled`, `tabs_inactive_border`, `tabs_inactive_border_thickness`, `tabs_bg_color`, `tabs_active_bg_color`, `tabs_hover_bg_color`, `tabs_border_enabled`, `tabs_border`, `tabs_border_thickness`, `tabs_corner_radius`, `tabs_font_family`, `tabs_font_size`, `tabs_font_bold`, `tabs_font_italic`, `tabs_font_color`, `tabs_font_smoothing_enabled`, `tabs_font_smoothing`, `tabs_border_enabled_linked`, `tabs_inactive_border_enabled_linked`, `tabs_corner_radius_linked`

</details>
<details><summary><code>title_</code> : 145 clés (titres (niveaux 1-5))</summary>

`title_level1_font_family`, `title_level1_font_bold`, `title_level1_font_italic`, `title_level1_font_size`, `title_level1_font_smoothing_enabled`, `title_level1_font_smoothing`, `title_level1_font_color`, `title_level1_indent`, `title_level1_gap_collapsed`, `title_level1_gap_expanded`, `title_level1_gap_next`, `title_level1_text_padding`, `title_level1_text_padding_linked`, `title_level1_space_before`, `title_level1_space_after`, `title_level1_bg_enabled`, `title_level1_bg_color`, `title_level1_bg_margin`, `title_level1_bg_margin_linked`, `title_level1_bg_padding`, `title_level1_bg_padding_linked`, `title_level1_body_padding`, `title_level1_body_padding_linked`, `title_level1_bg_border_enabled`, `title_level1_bg_border`, `title_level1_bg_border_thickness`, `title_level1_bg_border_enabled_linked`, `title_level1_bg_radius`, `title_level1_bg_radius_linked`, `title_level2_font_family`, `title_level2_font_bold`, `title_level2_font_italic`, `title_level2_font_size`, `title_level2_font_smoothing_enabled`, `title_level2_font_smoothing`, `title_level2_font_color`, `title_level2_indent`, `title_level2_gap_collapsed`, `title_level2_gap_expanded`, `title_level2_gap_next`, `title_level2_text_padding`, `title_level2_text_padding_linked`, `title_level2_space_before`, `title_level2_space_after`, `title_level2_bg_enabled`, `title_level2_bg_color`, `title_level2_bg_margin`, `title_level2_bg_margin_linked`, `title_level2_bg_padding`, `title_level2_bg_padding_linked`, `title_level2_body_padding`, `title_level2_body_padding_linked`, `title_level2_bg_border_enabled`, `title_level2_bg_border`, `title_level2_bg_border_thickness`, `title_level2_bg_border_enabled_linked`, `title_level2_bg_radius`, `title_level2_bg_radius_linked`, `title_level3_font_family`, `title_level3_font_bold`, `title_level3_font_italic`, `title_level3_font_size`, `title_level3_font_smoothing_enabled`, `title_level3_font_smoothing`, `title_level3_font_color`, `title_level3_indent`, `title_level3_gap_collapsed`, `title_level3_gap_expanded`, `title_level3_gap_next`, `title_level3_text_padding`, `title_level3_text_padding_linked`, `title_level3_space_before`, `title_level3_space_after`, `title_level3_bg_enabled`, `title_level3_bg_color`, `title_level3_bg_margin`, `title_level3_bg_margin_linked`, `title_level3_bg_padding`, `title_level3_bg_padding_linked`, `title_level3_body_padding`, `title_level3_body_padding_linked`, `title_level3_bg_border_enabled`, `title_level3_bg_border`, `title_level3_bg_border_thickness`, `title_level3_bg_border_enabled_linked`, `title_level3_bg_radius`, `title_level3_bg_radius_linked`, `title_level4_font_family`, `title_level4_font_bold`, `title_level4_font_italic`, `title_level4_font_size`, `title_level4_font_smoothing_enabled`, `title_level4_font_smoothing`, `title_level4_font_color`, `title_level4_indent`, `title_level4_gap_collapsed`, `title_level4_gap_expanded`, `title_level4_gap_next`, `title_level4_text_padding`, `title_level4_text_padding_linked`, `title_level4_space_before`, `title_level4_space_after`, `title_level4_bg_enabled`, `title_level4_bg_color`, `title_level4_bg_margin`, `title_level4_bg_margin_linked`, `title_level4_bg_padding`, `title_level4_bg_padding_linked`, `title_level4_body_padding`, `title_level4_body_padding_linked`, `title_level4_bg_border_enabled`, `title_level4_bg_border`, `title_level4_bg_border_thickness`, `title_level4_bg_border_enabled_linked`, `title_level4_bg_radius`, `title_level4_bg_radius_linked`, `title_level5_font_family`, `title_level5_font_bold`, `title_level5_font_italic`, `title_level5_font_size`, `title_level5_font_smoothing_enabled`, `title_level5_font_smoothing`, `title_level5_font_color`, `title_level5_indent`, `title_level5_gap_collapsed`, `title_level5_gap_expanded`, `title_level5_gap_next`, `title_level5_text_padding`, `title_level5_text_padding_linked`, `title_level5_space_before`, `title_level5_space_after`, `title_level5_bg_enabled`, `title_level5_bg_color`, `title_level5_bg_margin`, `title_level5_bg_margin_linked`, `title_level5_bg_padding`, `title_level5_bg_padding_linked`, `title_level5_body_padding`, `title_level5_body_padding_linked`, `title_level5_bg_border_enabled`, `title_level5_bg_border`, `title_level5_bg_border_thickness`, `title_level5_bg_border_enabled_linked`, `title_level5_bg_radius`, `title_level5_bg_radius_linked`

</details>
<details><summary><code>toggle1_</code> : 36 clés (toggle)</summary>

`toggle1_outer_width`, `toggle1_outer_height`, `toggle1_outer_border_enabled`, `toggle1_outer_border_thickness`, `toggle1_outer_border_radius`, `toggle1_outer_border_radius_linked`, `toggle1_outer_border`, `toggle1_outer_bg`, `toggle1_outer_bg_on`, `toggle1_coche_width`, `toggle1_coche_margin`, `toggle1_coche_border_enabled`, `toggle1_coche_border_thickness`, `toggle1_coche_border_radius`, `toggle1_coche_border_radius_linked`, `toggle1_coche_border`, `toggle1_coche_color`, `toggle1_coche_skin`, `toggle1_coche_text`, `toggle1_coche_text_font_family`, `toggle1_coche_text_font_bold`, `toggle1_coche_text_font_italic`, `toggle1_coche_text_font_size`, `toggle1_coche_text_font_smoothing_enabled`, `toggle1_coche_text_font_smoothing`, `toggle1_coche_text_font_color`, `toggle1_coche_icon`, `toggle1_coche_icon_color`, `toggle1_kind`, `toggle1_motion`, `toggle1_icon_on`, `toggle1_icon_off`, `toggle1_icon_frames`, `toggle1_anim_ms`, `toggle1_outer_border_enabled_linked`, `toggle1_coche_border_enabled_linked`

</details>
<details><summary><code>toggle2_</code> : 36 clés (toggle)</summary>

`toggle2_outer_width`, `toggle2_outer_height`, `toggle2_outer_border_enabled`, `toggle2_outer_border_thickness`, `toggle2_outer_border_radius`, `toggle2_outer_border_radius_linked`, `toggle2_outer_border`, `toggle2_outer_bg`, `toggle2_outer_bg_on`, `toggle2_coche_width`, `toggle2_coche_margin`, `toggle2_coche_border_enabled`, `toggle2_coche_border_thickness`, `toggle2_coche_border_radius`, `toggle2_coche_border_radius_linked`, `toggle2_coche_border`, `toggle2_coche_color`, `toggle2_coche_skin`, `toggle2_coche_text`, `toggle2_coche_text_font_family`, `toggle2_coche_text_font_bold`, `toggle2_coche_text_font_italic`, `toggle2_coche_text_font_size`, `toggle2_coche_text_font_smoothing_enabled`, `toggle2_coche_text_font_smoothing`, `toggle2_coche_text_font_color`, `toggle2_coche_icon`, `toggle2_coche_icon_color`, `toggle2_kind`, `toggle2_motion`, `toggle2_icon_on`, `toggle2_icon_off`, `toggle2_icon_frames`, `toggle2_anim_ms`, `toggle2_outer_border_enabled_linked`, `toggle2_coche_border_enabled_linked`

</details>
<details><summary><code>toggle_custom_styles</code> : 1 clés (toggle)</summary>

`toggle_custom_styles`

</details>
<details><summary><code>toggle_style</code> : 1 clés (toggle)</summary>

`toggle_style`

</details>
<details><summary><code>toggle_styles</code> : 1 clés (toggle)</summary>

`toggle_styles`

</details>
<details><summary><code>window_radius</code> : 1 clés (fenêtre)</summary>

`window_radius`

</details>

## Aspect propre à fm_browser → références vers fm_theme

<details><summary><code>board_</code> : 178 clés (board / CAD)</summary>

`board_grid_fade_start`, `board_grid_fade_full`, `board_grid_style`, `board_grid_thickness`, `board_grid_auto_color`, `board_grid_intensity`, `board_grid_color`, `board_grid_levels`, `board_grid_dot_size`, `board_grid_axes`, `board_grid_axes_color`, `board_grid_axes_thickness`, `board_toolbar_bg_color`, `board_toolbar_border_enabled`, `board_toolbar_border`, `board_toolbar_border_thickness`, `board_toolbar_border_enabled_linked`, `board_toolbar_corner_radius`, `board_toolbar_corner_radius_linked`, `board_toolbar_padding`, `board_toolbar_padding_linked`, `board_toolbar_shadow_enabled`, `board_toolbar_shadow`, `board_toolbar_shadow_size`, `board_toolbar_shadow_enabled_linked`, `board_toolbar_text_font_family`, `board_toolbar_text_font_size`, `board_toolbar_text_font_bold`, `board_toolbar_text_font_italic`, `board_toolbar_text_font_color`, `board_toolbar_text_font_smoothing_enabled`, `board_toolbar_text_font_smoothing`, `board_toolbar_focus_width`, `board_toolbar_focus_color`, `board_toolbar_focus_radius`, `board_toolbar_hover_color`, `board_toolbar_hover_radius`, `board_cad_marker_size`, `board_cad_marker_color`, `board_cad_marker_thickness`, `board_cad_grip_size`, `board_cad_crosshair_size`, `board_cad_crosshair_auto_color`, `board_cad_crosshair_color`, `board_cad_dim_gap`, `board_cad_dim_arrow_kind`, `board_cad_hatch_spacing`, `board_cad_text_font`, `board_cad_text_justify`, `board_cad_mtext_justify`, `board_cad_text_spacing`, `board_cad_bar_color`, `board_cad_grip_color`, `board_cad_grip_border_color`, `board_cad_track_color`, `board_cad_ghost_color`, `board_cad_window_bg`, `board_cad_window_border_enabled`, `board_cad_window_border_enabled_linked`, `board_cad_window_border`, `board_cad_window_border_thickness`, `board_cad_window_radius`, `board_cad_window_radius_linked`, `board_cad_window_line`, `board_cad_window_line_scale`, `board_cad_crossing_bg`, `board_cad_crossing_border_enabled`, `board_cad_crossing_border_enabled_linked`, `board_cad_crossing_border`, `board_cad_crossing_border_thickness`, `board_cad_crossing_radius`, `board_cad_crossing_radius_linked`, `board_cad_crossing_line`, `board_cad_crossing_line_scale`, `board_ctx_menu_bg`, `board_ovr_ctx_menu_bg`, `board_ctx_menu_border_enabled`, `board_ovr_ctx_menu_border_enabled`, `board_ctx_menu_border`, `board_ovr_ctx_menu_border`, `board_ctx_menu_border_thickness`, `board_ovr_ctx_menu_border_thickness`, `board_ctx_menu_border_color`, `board_ovr_ctx_menu_border_color`, `board_ctx_menu_border_radius`, `board_ovr_ctx_menu_border_radius`, `board_ctx_menu_border_radius_linked`, `board_ovr_ctx_menu_border_radius_linked`, `board_ctx_menu_padding`, `board_ovr_ctx_menu_padding`, `board_ctx_menu_padding_linked`, `board_ovr_ctx_menu_padding_linked`, `board_ctx_menu_font_family`, `board_ovr_ctx_menu_font_family`, `board_ctx_menu_font_bold`, `board_ovr_ctx_menu_font_bold`, `board_ctx_menu_font_italic`, `board_ovr_ctx_menu_font_italic`, `board_ctx_menu_font_size`, `board_ovr_ctx_menu_font_size`, `board_ctx_menu_font_smoothing_enabled`, `board_ovr_ctx_menu_font_smoothing_enabled`, `board_ctx_menu_font_smoothing`, `board_ovr_ctx_menu_font_smoothing`, `board_ctx_menu_font_color`, `board_ovr_ctx_menu_font_color`, `board_ctx_menu_item_padding`, `board_ovr_ctx_menu_item_padding`, `board_ctx_menu_item_padding_linked`, `board_ovr_ctx_menu_item_padding_linked`, `board_ctx_menu_hover_color`, `board_ovr_ctx_menu_hover_color`, `board_ctx_menu_hover_text_color`, `board_ovr_ctx_menu_hover_text_color`, `board_ctx_menu_hover_radius`, `board_ovr_ctx_menu_hover_radius`, `board_ctx_menu_hover_radius_linked`, `board_ovr_ctx_menu_hover_radius_linked`, `board_ctx_menu_hover_border_enabled`, `board_ovr_ctx_menu_hover_border_enabled`, `board_ctx_menu_hover_border`, `board_ovr_ctx_menu_hover_border`, `board_ctx_menu_hover_border_thickness`, `board_ovr_ctx_menu_hover_border_thickness`, `board_ctx_menu_hover_border_enabled_linked`, `board_ovr_ctx_menu_hover_border_enabled_linked`, `board_ctx_menu_hover_margin`, `board_ovr_ctx_menu_hover_margin`, `board_ctx_menu_hover_margin_linked`, `board_ovr_ctx_menu_hover_margin_linked`, `board_ctx_menu_disabled_color`, `board_ovr_ctx_menu_disabled_color`, `board_ctx_menu_icon_size`, `board_ovr_ctx_menu_icon_size`, `board_ctx_menu_control_gap`, `board_ovr_ctx_menu_control_gap`, `board_ctx_menu_slider_width`, `board_ovr_ctx_menu_slider_width`, `board_ctx_menu_label_font_family`, `board_ovr_ctx_menu_label_font_family`, `board_ctx_menu_label_font_bold`, `board_ovr_ctx_menu_label_font_bold`, `board_ctx_menu_label_font_italic`, `board_ovr_ctx_menu_label_font_italic`, `board_ctx_menu_label_font_size`, `board_ovr_ctx_menu_label_font_size`, `board_ctx_menu_label_font_smoothing_enabled`, `board_ovr_ctx_menu_label_font_smoothing_enabled`, `board_ctx_menu_label_font_smoothing`, `board_ovr_ctx_menu_label_font_smoothing`, `board_ctx_menu_label_font_color`, `board_ovr_ctx_menu_label_font_color`, `board_ctx_menu_label_bg`, `board_ovr_ctx_menu_label_bg`, `board_ctx_menu_label_padding`, `board_ovr_ctx_menu_label_padding`, `board_ctx_menu_label_padding_linked`, `board_ovr_ctx_menu_label_padding_linked`, `board_ctx_menu_label_uppercase`, `board_ovr_ctx_menu_label_uppercase`, `board_ctx_menu_sep_color`, `board_ovr_ctx_menu_sep_color`, `board_ctx_menu_sep_thickness`, `board_ovr_ctx_menu_sep_thickness`, `board_ctx_menu_sep_padding`, `board_ovr_ctx_menu_sep_padding`, `board_ctx_menu_sep_padding_linked`, `board_ovr_ctx_menu_sep_padding_linked`, `board_ctx_menu_shadow_enabled`, `board_ovr_ctx_menu_shadow_enabled`, `board_ctx_menu_shadow`, `board_ovr_ctx_menu_shadow`, `board_ctx_menu_shadow_size`, `board_ovr_ctx_menu_shadow_size`, `board_ctx_menu_shadow_enabled_linked`, `board_ovr_ctx_menu_shadow_enabled_linked`, `board_ctx_menu_border_enabled_linked`, `board_ovr_ctx_menu_border_enabled_linked`

</details>
<details><summary><code>column_</code> : 10 clés (colonne (cadre))</summary>

`column_gap`, `column_padding_linked`, `column_padding`, `column_border_enabled`, `column_border`, `column_border_thickness`, `column_border_radius`, `column_border_radius_linked`, `column_bg_color`, `column_border_enabled_linked`

</details>
<details><summary><code>crumb_</code> : 101 clés (cheminement)</summary>

`crumb_font_family`, `crumb_font_size`, `crumb_font_bold`, `crumb_font_italic`, `crumb_font_color`, `crumb_font_smoothing_enabled`, `crumb_font_smoothing`, `crumb_spacing`, `crumb_separator_kind`, `crumb_separator_char`, `crumb_sep_font_family`, `crumb_sep_font_size`, `crumb_sep_font_bold`, `crumb_sep_font_italic`, `crumb_sep_font_color`, `crumb_sep_font_smoothing_enabled`, `crumb_sep_font_smoothing`, `crumb_set_bg_color`, `crumb_after_bg_color`, `crumb_border_enabled`, `crumb_border`, `crumb_border_thickness`, `crumb_corner_radius`, `crumb_corner_radius_linked`, `crumb_padding`, `crumb_padding_linked`, `crumb_margin`, `crumb_margin_linked`, `crumb_after_font_family`, `crumb_after_font_size`, `crumb_after_font_bold`, `crumb_after_font_italic`, `crumb_after_font_color`, `crumb_after_font_smoothing_enabled`, `crumb_after_font_smoothing`, `crumb_after_border_enabled`, `crumb_after_border`, `crumb_after_border_thickness`, `crumb_after_border_enabled_linked`, `crumb_after_corner_radius`, `crumb_after_corner_radius_linked`, `crumb_after_padding_linked`, `crumb_after_margin_linked`, `crumb_after_padding`, `crumb_after_margin`, `crumb_after_ovr_font`, `crumb_after_ovr_bg`, `crumb_after_ovr_border`, `crumb_after_ovr_radius`, `crumb_after_ovr_padding`, `crumb_after_ovr_margin`, `crumb_after_ovr_shadow`, `crumb_afterfocus_font_family`, `crumb_afterfocus_font_size`, `crumb_afterfocus_font_bold`, `crumb_afterfocus_font_italic`, `crumb_afterfocus_font_color`, `crumb_afterfocus_font_smoothing_enabled`, `crumb_afterfocus_font_smoothing`, `crumb_afterfocus_bg_color`, `crumb_afterfocus_border_enabled`, `crumb_afterfocus_border`, `crumb_afterfocus_border_thickness`, `crumb_afterfocus_border_enabled_linked`, `crumb_afterfocus_corner_radius`, `crumb_afterfocus_corner_radius_linked`, `crumb_afterfocus_padding_linked`, `crumb_afterfocus_margin_linked`, `crumb_afterfocus_padding`, `crumb_afterfocus_margin`, `crumb_afterfocus_ovr_font`, `crumb_afterfocus_ovr_bg`, `crumb_afterfocus_ovr_border`, `crumb_afterfocus_ovr_radius`, `crumb_afterfocus_ovr_padding`, `crumb_afterfocus_ovr_margin`, `crumb_afterfocus_ovr_shadow`, `crumb_hover_bg_color`, `crumb_hover_border_enabled`, `crumb_hover_border`, `crumb_hover_border_thickness`, `crumb_hover_border_enabled_linked`, `crumb_focus_bg_color`, `crumb_focus_border_enabled`, `crumb_focus_border`, `crumb_focus_border_thickness`, `crumb_focus_border_enabled_linked`, `crumb_separator_enabled`, `crumb_shadow_enabled`, `crumb_shadow`, `crumb_shadow_size`, `crumb_shadow_enabled_linked`, `crumb_after_shadow_enabled`, `crumb_after_shadow`, `crumb_after_shadow_size`, `crumb_after_shadow_enabled_linked`, `crumb_afterfocus_shadow_enabled`, `crumb_afterfocus_shadow`, `crumb_afterfocus_shadow_size`, `crumb_afterfocus_shadow_enabled_linked`, `crumb_border_enabled_linked`

</details>
<details><summary><code>header_</code> : 17 clés (colonne (entête))</summary>

`header_height`, `header_padding`, `header_color`, `header_radius`, `header_radius_linked`, `header_border_enabled`, `header_border`, `header_border_thickness`, `header_font_family`, `header_icon_right_padding`, `header_font_bold`, `header_font_color`, `header_font_size`, `header_font_italic`, `header_font_antialias_override_enabled`, `header_font_antialias_override`, `header_border_enabled_linked`

</details>
<details><summary><code>item_</code> : 80 clés (colonne (lignes))</summary>

`item_font_family`, `item_font_size`, `item_font_bold`, `item_font_italic`, `item_color`, `item_icon_enabled`, `item_row_height`, `item_icon_size`, `item_icon_padding_left`, `item_row_spacing`, `item_column_width`, `item_ext_color_enabled`, `item_ext_color`, `item_row_border_enabled`, `item_row_border_color`, `item_row_border_thickness`, `item_header_gap`, `item_text_padding`, `item_image_padding_linked`, `item_image_padding`, `item_image_border_enabled`, `item_image_border`, `item_image_border_thickness`, `item_image_radius`, `item_image_radius_linked`, `item_image_ratio`, `item_selection_focus_color`, `item_selection_unfocus_color`, `item_hover_color`, `item_idle_color`, `item_row_bg_color`, `item_selection_padding_linked`, `item_selection_padding`, `item_selection_border_enabled`, `item_selection_border`, `item_selection_radius`, `item_selection_radius_linked`, `item_selection_edge_border`, `item_selection_unfocus_padding_override`, `item_selection_unfocus_padding`, `item_selection_unfocus_border_override`, `item_selection_unfocus_border_enabled`, `item_selection_unfocus_border`, `item_selection_unfocus_radius_override`, `item_selection_unfocus_radius`, `item_selection_unfocus_radius_linked`, `item_selection_unfocus_edge_border_override`, `item_selection_unfocus_edge_border`, `item_selection_hover_padding_override`, `item_selection_hover_padding`, `item_selection_hover_border_override`, `item_selection_hover_border_enabled`, `item_selection_hover_border`, `item_selection_hover_radius_override`, `item_selection_hover_radius`, `item_selection_hover_radius_linked`, `item_selection_hover_edge_border_override`, `item_selection_hover_edge_border`, `item_selection_idle_padding_override`, `item_selection_idle_padding`, `item_selection_idle_border_override`, `item_selection_idle_border_enabled`, `item_selection_idle_border`, `item_selection_idle_radius_override`, `item_selection_idle_radius`, `item_selection_idle_radius_linked`, `item_selection_idle_edge_border_override`, `item_selection_idle_edge_border`, `item_image_shadow_enabled`, `item_image_shadow`, `item_image_shadow_size`, `item_image_shadow_enabled_linked`, `item_selection_unfocus_padding_linked`, `item_selection_hover_padding_linked`, `item_selection_idle_padding_linked`, `item_image_border_enabled_linked`, `item_selection_border_enabled_linked`, `item_selection_unfocus_border_enabled_linked`, `item_selection_hover_border_enabled_linked`, `item_selection_idle_border_enabled_linked`

</details>
<details><summary><code>md_</code> : 291 clés (Markdown)</summary>

`md_bg_color`, `md_bg_secondary`, `md_accent_color`, `md_selection_color`, `md_content_width`, `md_module_padding`, `md_page_padding`, `md_page_padding_linked`, `md_page_margin`, `md_page_margin_linked`, `md_page_border_enabled`, `md_page_border`, `md_page_border_thickness`, `md_page_border_enabled_linked`, `md_page_radius`, `md_page_radius_linked`, `md_scroll_width`, `md_scroll_radius`, `md_scroll_thumb_color`, `md_scroll_thumb_hover_color`, `md_scroll_track_color`, `md_scroll_offset`, `md_scroll_padding`, `md_text_font_family`, `md_text_font_bold`, `md_text_font_italic`, `md_text_font_size`, `md_text_font_smoothing_enabled`, `md_text_font_smoothing`, `md_text_font_color`, `md_text_weight`, `md_line_height`, `md_letter_spacing`, `md_paragraph_spacing`, `md_title_font_family`, `md_title_font_bold`, `md_title_font_italic`, `md_title_font_size`, `md_title_font_smoothing_enabled`, `md_title_font_smoothing`, `md_title_font_color`, `md_title_weight`, `md_title_spacing`, `md_h1_font_family`, `md_h1_font_bold`, `md_h1_font_italic`, `md_h1_font_size`, `md_h1_font_smoothing_enabled`, `md_h1_font_smoothing`, `md_h1_font_color`, `md_h1_weight`, `md_h1_line_height`, `md_h1_space_before`, `md_h1_space_after`, `md_h2_font_family`, `md_h2_font_bold`, `md_h2_font_italic`, `md_h2_font_size`, `md_h2_font_smoothing_enabled`, `md_h2_font_smoothing`, `md_h2_font_color`, `md_h2_weight`, `md_h2_line_height`, `md_h2_space_before`, `md_h2_space_after`, `md_h3_font_family`, `md_h3_font_bold`, `md_h3_font_italic`, `md_h3_font_size`, `md_h3_font_smoothing_enabled`, `md_h3_font_smoothing`, `md_h3_font_color`, `md_h3_weight`, `md_h3_line_height`, `md_h3_space_before`, `md_h3_space_after`, `md_h4_font_family`, `md_h4_font_bold`, `md_h4_font_italic`, `md_h4_font_size`, `md_h4_font_smoothing_enabled`, `md_h4_font_smoothing`, `md_h4_font_color`, `md_h4_weight`, `md_h4_line_height`, `md_h4_space_before`, `md_h4_space_after`, `md_h5_font_family`, `md_h5_font_bold`, `md_h5_font_italic`, `md_h5_font_size`, `md_h5_font_smoothing_enabled`, `md_h5_font_smoothing`, `md_h5_font_color`, `md_h5_weight`, `md_h5_line_height`, `md_h5_space_before`, `md_h5_space_after`, `md_h6_font_family`, `md_h6_font_bold`, `md_h6_font_italic`, `md_h6_font_size`, `md_h6_font_smoothing_enabled`, `md_h6_font_smoothing`, `md_h6_font_color`, `md_h6_weight`, `md_h6_line_height`, `md_h6_space_before`, `md_h6_space_after`, `md_bold_color`, `md_bold_weight`, `md_italic_color`, `md_strike_color`, `md_strike_line_color`, `md_strike_bg`, `md_highlight_bg`, `md_highlight_color`, `md_markup_color`, `md_tag_color`, `md_tag_bg`, `md_link_font_family`, `md_link_font_bold`, `md_link_font_italic`, `md_link_font_size`, `md_link_font_smoothing_enabled`, `md_link_font_smoothing`, `md_link_font_color`, `md_link_letter_spacing`, `md_link_underline`, `md_link_hover_underline`, `md_link_unresolved_opacity`, `md_list_indent`, `md_list_spacing`, `md_bullet_1_char`, `md_bullet_1_font_size`, `md_bullet_1_font_color`, `md_bullet_1_vertical_offset`, `md_bullet_2_char`, `md_bullet_2_font_size`, `md_bullet_2_font_color`, `md_bullet_2_vertical_offset`, `md_bullet_3_char`, `md_bullet_3_font_size`, `md_bullet_3_font_color`, `md_bullet_3_vertical_offset`, `md_number_color`, `md_checkbox_color`, `md_checkbox_size`, `md_task_done_strike`, `md_task_done_color`, `md_quote_font_family`, `md_quote_font_bold`, `md_quote_font_italic`, `md_quote_font_size`, `md_quote_font_smoothing_enabled`, `md_quote_font_smoothing`, `md_quote_font_color`, `md_quote_bg`, `md_quote_border_enabled`, `md_quote_border`, `md_quote_border_thickness`, `md_quote_border_enabled_linked`, `md_quote_radius`, `md_quote_radius_linked`, `md_quote_padding`, `md_quote_padding_linked`, `md_quote_spacing`, `md_callout_bg`, `md_callout_border_color`, `md_callout_border_width`, `md_callout_title_color`, `md_callout_radius`, `md_callout_radius_linked`, `md_code_inline_font_family`, `md_code_inline_font_bold`, `md_code_inline_font_italic`, `md_code_inline_font_size`, `md_code_inline_font_smoothing_enabled`, `md_code_inline_font_smoothing`, `md_code_inline_font_color`, `md_code_inline_weight`, `md_code_inline_bg`, `md_code_inline_radius`, `md_code_inline_radius_linked`, `md_code_inline_padding`, `md_code_inline_padding_linked`, `md_codeblock_font_family`, `md_codeblock_font_bold`, `md_codeblock_font_italic`, `md_codeblock_font_size`, `md_codeblock_font_smoothing_enabled`, `md_codeblock_font_smoothing`, `md_codeblock_font_color`, `md_codeblock_weight`, `md_codeblock_line_height`, `md_codeblock_bg`, `md_codeblock_border_enabled`, `md_codeblock_border`, `md_codeblock_border_thickness`, `md_codeblock_border_enabled_linked`, `md_codeblock_radius`, `md_codeblock_radius_linked`, `md_codeblock_padding`, `md_codeblock_padding_linked`, `md_codeblock_spacing`, `md_syntax_comment`, `md_syntax_keyword`, `md_syntax_string`, `md_syntax_number`, `md_syntax_def`, `md_syntax_variable`, `md_syntax_type`, `md_syntax_builtin`, `md_syntax_operator`, `md_syntax_property`, `md_syntax_tag`, `md_syntax_attribute`, `md_syntax_meta`, `md_syntax_italic_comments`, `md_table_font_family`, `md_table_font_bold`, `md_table_font_italic`, `md_table_font_size`, `md_table_font_smoothing_enabled`, `md_table_font_smoothing`, `md_table_font_color`, `md_table_head_font_family`, `md_table_head_font_bold`, `md_table_head_font_italic`, `md_table_head_font_size`, `md_table_head_font_smoothing_enabled`, `md_table_head_font_smoothing`, `md_table_head_font_color`, `md_table_grid_color`, `md_table_grid_width`, `md_table_cell_bg`, `md_table_alt_bg`, `md_table_head_bg`, `md_table_radius`, `md_table_radius_linked`, `md_table_cell_padding`, `md_table_cell_padding_linked`, `md_table_spacing`, `md_hr_color`, `md_hr_thickness`, `md_hr_spacing`, `md_image_max_width`, `md_image_align`, `md_image_radius`, `md_image_radius_linked`, `md_image_spacing`, `md_caret_color`, `md_caret_width`, `md_active_line_bg`, `md_code_file_font_family`, `md_code_file_font_bold`, `md_code_file_font_italic`, `md_code_file_font_size`, `md_code_file_font_smoothing_enabled`, `md_code_file_font_smoothing`, `md_code_file_font_color`, `md_code_file_line_height`, `md_code_file_bg`, `md_gutter_color`, `md_gutter_bg`, `md_toolbar_font_color`, `md_toolbar_background_color`, `md_toolbar_bg`, `md_toolbar_icon_color`, `md_toolbar_icon_size`, `md_toolbar_button_size`, `md_toolbar_radius`, `md_toolbar_radius_linked`, `md_toolbar_hover_bg`, `md_toolbar_active_bg`, `md_toolbar_button_radius`, `md_toolbar_button_radius_linked`, `md_toolbar_padding`, `md_toolbar_padding_linked`, `md_toolbar_margin`, `md_toolbar_margin_linked`, `md_toolbar_shadow_enabled`, `md_toolbar_shadow`, `md_toolbar_shadow_size`, `md_toolbar_shadow_enabled_linked`, `md_toolbar_gap`, `md_toolbar_border_enabled`, `md_toolbar_border`, `md_toolbar_border_thickness`, `md_toolbar_border_enabled_linked`, `md_code_font_zoom`

</details>
<details><summary><code>navbar_</code> : 11 clés (barre de navigation)</summary>

`navbar_height`, `navbar_bottom_enabled`, `navbar_bottom_color`, `navbar_bottom_thickness`, `navbar_title_font_family`, `navbar_title_font_size`, `navbar_title_font_bold`, `navbar_title_font_italic`, `navbar_title_font_color`, `navbar_title_font_smoothing_enabled`, `navbar_title_font_smoothing`

</details>
<details><summary><code>preview_</code> : 38 clés (carte d'aperçu)</summary>

`preview_padding`, `preview_padding_linked`, `preview_image_ratio`, `preview_radius`, `preview_radius_linked`, `preview_title_zone_height`, `preview_title_font_size`, `preview_title_font_color`, `preview_title_font_family`, `preview_title_font_bold`, `preview_title_font_italic`, `preview_title_font_smoothing_enabled`, `preview_title_font_smoothing`, `preview_title_padding_linked`, `preview_title_padding`, `preview_status_font_size`, `preview_status_font_color`, `preview_status_font_color_idle`, `preview_status_font_family`, `preview_status_font_bold`, `preview_status_font_italic`, `preview_status_font_smoothing_enabled`, `preview_status_font_smoothing`, `preview_status_padding_linked`, `preview_status_padding`, `preview_toggle_width`, `preview_toggle_height`, `preview_toggle_bg_color`, `preview_toggle_border_enabled`, `preview_toggle_border`, `preview_toggle_border_thickness`, `preview_toggle_radius`, `preview_toggle_x`, `preview_toggle_y`, `preview_shadow_enabled`, `preview_shadow`, `preview_shadow_size`, `preview_shadow_enabled_linked`

</details>
<details><summary><code>resize_</code> : 17 clés (badge de redimensionnement)</summary>

`resize_badge_position`, `resize_badge_offset_x`, `resize_badge_offset_y`, `resize_badge_font_family`, `resize_badge_font_bold`, `resize_badge_font_italic`, `resize_badge_font_size`, `resize_badge_font_smoothing_enabled`, `resize_badge_font_smoothing`, `resize_badge_text_color`, `resize_badge_bg_color`, `resize_badge_border_enabled`, `resize_badge_border`, `resize_badge_border_thickness`, `resize_badge_border_radius`, `resize_badge_border_radius_linked`, `resize_badge_border_enabled_linked`

</details>
<details><summary><code>shortcut_</code> : 7 clés (texte des raccourcis)</summary>

`shortcut_font_family`, `shortcut_font_bold`, `shortcut_font_italic`, `shortcut_color`, `shortcut_font_size`, `shortcut_font_smoothing_enabled`, `shortcut_font_smoothing`

</details>
<details><summary><code>step_</code> : 27 clés (badges d'étapes)</summary>

`step_badge_width`, `step_badge_height`, `step_badge_border_enabled`, `step_badge_border`, `step_badge_border_thickness`, `step_badge_radius`, `step_badge_radius_linked`, `step_badge_color_base2`, `step_badge_color_base3`, `step_badge_color_base4`, `step_badge_color_base5`, `step_badge_color_base6`, `step_badge_color_basen`, `step_badge_text_color_base2`, `step_badge_text_color_base3`, `step_badge_text_color_base4`, `step_badge_text_color_base5`, `step_badge_text_color_base6`, `step_badge_text_color_basen`, `step_badge_offset_x`, `step_badge_offset_y`, `step_badge_font_family`, `step_badge_font_bold`, `step_badge_font_smoothing_enabled`, `step_badge_font_smoothing`, `step_badge_border_smoothing`, `step_badge_border_enabled_linked`

</details>
<details><summary><code>video_</code> : 58 clés (vidéo)</summary>

`video_frame_shadow_enabled`, `video_frame_shadow`, `video_frame_shadow_size`, `video_frame_shadow_enabled_linked`, `video_bg_color`, `video_moodboard_bg_color`, `video_analysis_colors`, `video_help_width`, `video_mood_info_font_size`, `video_mood_info_color`, `video_mood_info_bg`, `video_mood_info_opacity`, `video_mood_info_radius`, `video_mood_info_padding`, `video_mood_info_position`, `video_mood_info_margin_x`, `video_mood_info_margin_y`, `video_fit_margin`, `video_checker`, `video_checker_size`, `video_checker_a`, `video_checker_b`, `video_controls_bg`, `video_controls_color`, `video_controls_height`, `video_frame_border_enabled`, `video_frame_border_enabled_linked`, `video_frame_border`, `video_frame_border_thickness`, `video_frame_radius`, `video_frame_radius_linked`, `video_frame_shadow_offset_x`, `video_frame_shadow_offset_y`, `video_frame_shadow_spread`, `video_info_opacity`, `video_info_bg`, `video_info_font_family`, `video_info_font_bold`, `video_info_font_size`, `video_info_font_color`, `video_info_label_color`, `video_info_title_color`, `video_info_margin_x`, `video_info_margin_y`, `video_info_line_spacing`, `video_info_padding`, `video_info_radius`, `video_info_width`, `video_timeline_height`, `video_timeline_playhead`, `video_timeline_selection`, `video_timeline_in`, `video_timeline_out`, `video_timeline_bg`, `video_timeline_ruler`, `video_timeline_text`, `video_timeline_thumb_height`, `video_export_color`

</details>
<details><summary><code>viewer_</code> : 125 clés (visionneuse)</summary>

`viewer_scroll_animated`, `viewer_focus_image_border_enabled`, `viewer_filter_color_1`, `viewer_filter_color_2`, `viewer_filter_color_3`, `viewer_filter_color_4`, `viewer_filter_color_5`, `viewer_filter_color_1_name`, `viewer_filter_color_2_name`, `viewer_filter_color_3_name`, `viewer_filter_color_4_name`, `viewer_filter_color_5_name`, `viewer_filter_active_color`, `viewer_filter_mark_opacity`, `viewer_filter_mark_border`, `viewer_filter_mark_border_thickness`, `viewer_filter_row_bg_enabled`, `viewer_filter_row_bg_color`, `viewer_filter_row_border_enabled`, `viewer_filter_row_border`, `viewer_filter_row_border_thickness`, `viewer_filter_row_radius`, `viewer_filter_row_radius_linked`, `viewer_filter_row_margin`, `viewer_filter_row_margin_linked`, `viewer_focus_image_border`, `viewer_focus_image_border_thickness`, `viewer_focus_image_border_radius`, `viewer_focus_image_border_radius_linked`, `viewer_film_text_ratio`, `viewer_gallery_text_height`, `viewer_film_table_border_enabled`, `viewer_film_table_border`, `viewer_film_table_border_thickness`, `viewer_film_table_border_radius`, `viewer_film_table_border_radius_linked`, `viewer_film_table_font_family`, `viewer_film_table_font_bold`, `viewer_film_table_font_italic`, `viewer_film_table_font_size`, `viewer_film_table_font_smoothing_enabled`, `viewer_film_table_font_smoothing`, `viewer_film_table_font_color`, `viewer_film_table_bg`, `viewer_film_table_inner_h_enabled`, `viewer_film_table_inner_h_color`, `viewer_film_table_inner_h_thickness`, `viewer_film_table_inner_v_enabled`, `viewer_film_table_inner_v_color`, `viewer_film_table_inner_v_thickness`, `viewer_film_table_focus_color`, `viewer_film_table_hover_color`, `viewer_film_image_cell_border_enabled`, `viewer_film_image_cell_border`, `viewer_film_image_cell_border_thickness`, `viewer_film_image_cell_border_radius`, `viewer_film_image_cell_border_radius_linked`, `viewer_film_image_border_enabled`, `viewer_film_image_border`, `viewer_film_image_border_thickness`, `viewer_film_image_border_radius`, `viewer_film_image_border_radius_linked`, `viewer_film_bg_padding`, `viewer_film_bg_padding_linked`, `viewer_film_image_padding`, `viewer_film_image_padding_linked`, `viewer_film_attr_padding`, `viewer_film_attr_padding_linked`, `viewer_film_image_cell_font_family`, `viewer_film_image_cell_font_bold`, `viewer_film_image_cell_font_italic`, `viewer_film_image_cell_font_size`, `viewer_film_image_cell_font_smoothing_enabled`, `viewer_film_image_cell_font_smoothing`, `viewer_film_image_cell_font_color`, `viewer_film_image_cell_bg`, `viewer_film_text_cell_border_enabled`, `viewer_film_text_cell_border`, `viewer_film_text_cell_border_thickness`, `viewer_film_text_cell_border_radius`, `viewer_film_text_cell_border_radius_linked`, `viewer_film_text_cell_font_family`, `viewer_film_text_cell_font_bold`, `viewer_film_text_cell_font_italic`, `viewer_film_text_cell_font_size`, `viewer_film_text_cell_font_smoothing_enabled`, `viewer_film_text_cell_font_smoothing`, `viewer_film_text_cell_font_color`, `viewer_film_text_cell_bg`, `viewer_group_bg_color`, `viewer_group_label_font_family`, `viewer_group_label_font_size`, `viewer_group_label_font_bold`, `viewer_group_label_font_italic`, `viewer_group_label_font_color`, `viewer_group_label_font_smoothing_enabled`, `viewer_group_label_font_smoothing`, `viewer_group_border_enabled`, `viewer_group_border`, `viewer_group_border_thickness`, `viewer_group_border_enabled_linked`, `viewer_group_corner_radius`, `viewer_group_corner_radius_linked`, `viewer_group_padding`, `viewer_group_padding_linked`, `viewer_group_margin`, `viewer_group_margin_linked`, `viewer_film_image_shadow_enabled`, `viewer_film_image_shadow`, `viewer_film_image_shadow_size`, `viewer_film_image_shadow_enabled_linked`, `viewer_focus_image_shadow_enabled`, `viewer_focus_image_shadow`, `viewer_focus_image_shadow_size`, `viewer_focus_image_shadow_enabled_linked`, `viewer_film_table_shadow_enabled`, `viewer_film_table_shadow`, `viewer_film_table_shadow_size`, `viewer_film_table_shadow_enabled_linked`, `viewer_film_table_border_enabled_linked`, `viewer_film_image_cell_border_enabled_linked`, `viewer_film_image_border_enabled_linked`, `viewer_film_text_cell_border_enabled_linked`, `viewer_focus_image_border_enabled_linked`, `viewer_filter_row_border_enabled_linked`

</details>

## Fonctionnement → reste dans fm_browser

<details><summary><code>active_</code> : 1 clés (fonctionnement)</summary>

`active_preset`

</details>
<details><summary><code>application_</code> : 3 clés (fonctionnement)</summary>

`application_omit_file_names`, `application_omit_extensions`, `application_omit_dir_names`

</details>
<details><summary><code>auto_</code> : 10 clés (fonctionnement)</summary>

`auto_collapse_set_columns`, `auto_settings_enabled`, `auto_settings_when`, `auto_settings_delay`, `auto_moodboard_enabled`, `auto_moodboard_when`, `auto_moodboard_delay`, `auto_video_enabled`, `auto_video_when`, `auto_video_delay`

</details>
<details><summary><code>board_</code> : 73 clés (board / CAD : comportement ; comportement ; unités du dessin CAD (contenu, pas aspect))</summary>

`board_open_cad_drawings`, `board_snap_enabled`, `board_snap_objects`, `board_snap_grid`, `board_snap_guides`, `board_snap_resize`, `board_snap_distance`, `board_pen_presets`, `board_grid_step`, `board_grid_unit`, `board_grid_factor`, `board_grid_origin_x`, `board_grid_origin_y`, `board_zoom_speed`, `board_zoom_fine`, `board_toolbar_invert`, `board_cad_osnap`, `board_cad_osnap_end`, `board_cad_osnap_mid`, `board_cad_osnap_cen`, `board_cad_osnap_gcen`, `board_cad_osnap_qua`, `board_cad_osnap_int`, `board_cad_osnap_appint`, `board_cad_osnap_ext`, `board_cad_osnap_per`, `board_cad_osnap_tan`, `board_cad_osnap_nea`, `board_cad_osnap_par`, `board_cad_osnap_node`, `board_cad_osnap_ins`, `board_cad_aperture`, `board_cad_markers`, `board_cad_tooltips`, `board_cad_magnet`, `board_cad_ortho`, `board_cad_polar`, `board_cad_polar_increment`, `board_cad_polar_custom`, `board_cad_otrack`, `board_cad_track_polar`, `board_cad_dyn`, `board_cad_grid_snap`, `board_cad_unit`, `board_cad_linetypes`, `board_cad_pickbox`, `board_cad_pickadd`, `board_cad_crosshair`, `board_cad_crosshair_full`, `board_cad_crosshair_memory`, `board_cad_dim_text`, `board_cad_dim_arrow`, `board_cad_dim_over`, `board_cad_dim_scale`, `board_cad_dim_decimals`, `board_cad_hatch_pattern`, `board_cad_hatch_angle`, `board_cad_hatch_alpha`, `board_cad_text_height`, `board_cad_pgp_path`, `board_cad_gpu`, `board_cad_precision`, `board_cad_lineweights`, `board_cad_aa_filter`, `board_cad_aa_samples`, `board_cad_antialiasing`, `board_cad_linear_blend`, `board_cad_crisp_lines`, `board_cad_dense_px`, `board_cad_trim_mode`, `board_cad_trim_edge`, `board_ctx_menu_editable`, `board_ovr_ctx_menu_editable`

</details>
<details><summary><code>collapse_</code> : 1 clés (fonctionnement)</summary>

`collapse_toggle_mode`

</details>
<details><summary><code>column_</code> : 4 clés (override d'élément (reste côté appli))</summary>

`column_type_overrides`, `column_type_override_enabled`, `column_overrides_by_title`, `column_override_enabled_by_title`

</details>
<details><summary><code>columns_</code> : 2 clés (fonctionnement)</summary>

`columns_resizable`, `columns`

</details>
<details><summary><code>context_</code> : 1 clés (fonctionnement)</summary>

`context_menu_layouts`

</details>
<details><summary><code>custom_</code> : 1 clés (fonctionnement)</summary>

`custom_softwares`

</details>
<details><summary><code>default_</code> : 1 clés (fonctionnement)</summary>

`default_preset`

</details>
<details><summary><code>detail_</code> : 1 clés (fonctionnement)</summary>

`detail_panel_width`

</details>
<details><summary><code>divers</code> : 1 clés (override d'élément (reste côté appli))</summary>

`toggle_style_overrides`

</details>
<details><summary><code>element_</code> : 3 clés (fonctionnement)</summary>

`element_style_overrides`, `element_spaces`, `element_spaces_below`

</details>
<details><summary><code>folder_</code> : 1 clés (fonctionnement)</summary>

`folder_reorder_enabled`

</details>
<details><summary><code>font_</code> : 1 clés (disposition du tableau des polices)</summary>

`font_table_columns`

</details>
<details><summary><code>geo_</code> : 1 clés (fonctionnement)</summary>

`geo_table_columns`

</details>
<details><summary><code>header_</code> : 1 clés (colonne (entête) : comportement)</summary>

`header_visible`

</details>
<details><summary><code>item_</code> : 2 clés (colonne (lignes) : comportement)</summary>

`item_antialias_override_enabled`, `item_antialias_override`

</details>
<details><summary><code>lut_</code> : 3 clés (fonctionnement)</summary>

`lut_test_images`, `lut_default_image`, `lut_image_curves`

</details>
<details><summary><code>md_</code> : 14 clés (Markdown : comportement ; comportement)</summary>

`md_open_extensions`, `md_open_md`, `md_default_mode`, `md_live_preview`, `md_preload`, `md_css_path`, `md_zoom`, `md_title_enabled`, `md_line_numbers`, `md_code_wrap`, `md_tab_size`, `md_toolbar_enabled`, `md_toolbar_centered`, `md_last_mode`

</details>
<details><summary><code>quick_</code> : 1 clés (fonctionnement)</summary>

`quick_style_positions`

</details>
<details><summary><code>removed_</code> : 1 clés (fonctionnement)</summary>

`removed_softwares`

</details>
<details><summary><code>root_</code> : 1 clés (fonctionnement)</summary>

`root_path`

</details>
<details><summary><code>slider_</code> : 1 clés (plages des curseurs choisies au clic droit)</summary>

`slider_ranges`

</details>
<details><summary><code>table_</code> : 2 clés (comportement (Ctrl + glisser des lignes) ; disposition (largeurs des colonnes des tableaux))</summary>

`table_rows_movable`, `table_dims`

</details>
<details><summary><code>theme_</code> : 2 clés (fonctionnement)</summary>

`theme_preset`, `theme_default_variants`

</details>
<details><summary><code>title_</code> : 1 clés (disposition (ordre des titres))</summary>

`title_order`

</details>
<details><summary><code>ui_</code> : 2 clés (fonctionnement)</summary>

`ui_spaces`, `ui_spaces_below`

</details>
<details><summary><code>video_</code> : 96 clés (comportement ; vidéo : comportement)</summary>

`video_open_videos`, `video_open_sequences`, `video_detect_sequences`, `video_moodboard_proxy_width`, `video_default_zoom`, `video_wheel_zoom`, `video_zoom_step`, `video_analysis_exclude_black`, `video_analysis_exclude_white`, `video_match_lut_size`, `video_match_intensity`, `video_match_method`, `video_help_enabled`, `video_help_delay`, `video_mood_info_enabled`, `video_mood_info_timestamp`, `video_mood_info_interval`, `video_mood_info_format`, `video_interpolation`, `video_mipmaps`, `video_pan`, `video_backend`, `video_fullscreen_autohide`, `video_fullscreen_info`, `video_info_enabled`, `video_info_corner`, `video_info_compact`, `video_info_titles`, `video_info_temporary`, `video_info_timeout`, `video_info_media`, `video_info_image`, `video_info_playback`, `video_info_display`, `video_info_pixel`, `video_sequence_fps`, `video_autoplay`, `video_loop`, `video_volume`, `video_engine`, `video_cache_local_ms`, `video_cache_network_ms`, `video_end_behavior`, `video_priority`, `video_missing`, `video_prefetch_ahead`, `video_prefetch_behind`, `video_reset_position`, `video_key_in`, `video_key_out`, `video_key_clear`, `video_timeline_tick`, `video_timeline_density`, `video_time_display`, `video_timeline_zoom_step`, `video_timeline_zoom_cursor`, `video_timeline_cache`, `video_timeline_thumbs`, `video_ocio_config`, `video_display`, `video_view_video`, `video_view_image`, `video_input_video`, `video_input_exr`, `video_input_float`, `video_input_int`, `video_alpha_mode`, `video_channel`, `video_grade_on_change`, `video_clipping`, `video_lut_dir`, `video_lut_default`, `video_lut_auto`, `video_lut_mix`, `video_lut_position`, `video_cache_mb`, `video_workers`, `video_diagnostics`, `video_export_format`, `video_export_codec`, `video_export_crf`, `video_export_preset`, `video_export_dir`, `video_export_lut`, `video_export_fps_mode`, `video_export_interp`, `video_export_audio`, `video_export_depth`, `video_export_numbering`, `video_export_overwrite`, `video_rife_path`, `video_grade`, `video_grade_presets`, `video_export_last`, `video_last_zoom`, `video_scopes`

</details>
<details><summary><code>viewer_</code> : 8 clés (visionneuse : comportement)</summary>

`viewer_filmstrip_enabled`, `viewer_filmstrip_shortcut`, `viewer_slide_enabled`, `viewer_info_enabled`, `viewer_info_shortcut`, `viewer_gallery_ripple_enabled`, `viewer_button_order`, `viewer_recursive`

</details>

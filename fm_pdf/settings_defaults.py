"""Valeurs par défaut des réglages du module PDF (sans Qt). Fusionnées dans `settings_store.DEFAULT_SETTINGS`
(toute clé `pdf_*` doit être déclarée ici pour être gardée par `load_settings`)."""

PDF_DEFAULTS = {
    # Affichage
    "pdf_default_fit": "width",            # "width", "page", "" (zoom fixe)
    "pdf_default_zoom": 100,               # % quand l'ajustement est désactivé
    "pdf_default_mode": "continuous",      # continuous, single, two, two_continuous
    "pdf_view_background": "#3a3d40",
    "pdf_zoom_step": 1.15,                 # facteur par cran de molette (Ctrl + molette)
    "pdf_actual_size_dpi": True,           # « Taille réelle » = DPI logique de l'écran
    "pdf_show_thumbnails": True,           # panneau de gauche ouvert à l'ouverture
    "pdf_left_panel": "Pages",
    "pdf_render_quality": "high",          # high, fast (sans lissage du texte), grayscale
    "pdf_cache_mb": 256,                   # mémoire des tuiles rendues
    "pdf_prefetch_screens": 1,             # hauteurs d'écran préchargées au-dessus / au-dessous
    # Formulaires
    "pdf_forms_highlight": True,           # fond des champs interactifs
    "pdf_forms_highlight_color": "#dde4ff",
    "pdf_forms_highlight_alpha": 100,
    "pdf_javascript": True,                # scripts des formulaires (calculs, validations, XFA) ; réseau toujours bloqué
    "pdf_js_alerts": True,                 # montrer les alertes des scripts
    "pdf_open_double_click": True,         # double-clic sur un .pdf des colonnes : éditeur PDF
    "pdf_design_font_size": 0,             # taille du texte des nouveaux champs (0 = automatique)
    # OCR
    "pdf_ocr_languages": "fr;en",
    # Enregistrement
    "pdf_save_mode": "auto",               # auto (incrémental si signé / XFA), incremental, full
    "pdf_autosave_recovery_s": 60,         # copie de secours d'un document modifié (0 = jamais)
    # Sécurité
    "pdf_confirm_links": True,             # lien externe : demander avant d'ouvrir
    "pdf_warn_active_content": True,       # bandeau quand le document contient des scripts / pièces jointes
    # Annotations
    "pdf_annot_author": "",
    "pdf_annot_color": "#ffd400",
    "pdf_annot_ink_color": "#d32f2f",
    "pdf_annot_width": 2,
    "pdf_annot_opacity": 1.0,
    # Impression
    "pdf_print_dpi": 300,
    "pdf_print_annotations": True,
}

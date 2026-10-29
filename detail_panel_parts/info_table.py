"""Inspecteur : polices, couleurs et tableau d'informations (type, taille, date, sources).

Découpé de detail_panel.py (2026-10-29) ; carte : docs/agents/inspecteur.md."""
import json

from PySide6.QtCore import Qt

from app_style import C, INSPECTOR_TITLE, role_color, role_font, scaled, column_frame_style, column_header_qss
from settings_store import M, _sync_dynamic_M, load_settings
from settings_theme import _set_text_role
from settings_widgets import _sync_toggle_style
import ui_state


class InfoTableMixin:
    """Méthodes de DetailPanel : inspecteur : polices, couleurs et tableau d'informations (type, taille, date, sources)."""

    def refresh_fonts(self, is_dir: bool = True):
        """Reapplique les polices de role (voir role_font) : necessaire car
        ce panneau, contrairement aux colonnes, n'est pas reconstruit par
        PipelineBrowser.reload() apres un changement de reglages. Geometrie
        de l'entete (hauteur/padding) desormais dans refresh_header, PAS
        ici (voir sa docstring). Police/couleur du TITRE d'entete
        (self.header_title) AUSSI desormais dans refresh_header (bug
        corrige, voir sa remarque) — cette methode-ci ne touche plus qu'au
        NOM du fichier/dossier selectionne et aux champs de detail."""
        self.name.setFont(role_font("folders" if is_dir else "files", 12, 600, tracking=0.12))
        self.name.setStyleSheet(
            f"color: {role_color('folders' if is_dir else 'files', C['text'])}; background: transparent;"
        )
        self.open_render_log_button.setFont(role_font("buttons", 10, 500))
        # Valeurs du tableau : role de texte des reglages (voir _build_info_table).
        for value in (*self.values.values(), self.preview_dimensions_value):
            _set_text_role(value, "value")
        self.preview_stale_badge.setFont(role_font("info2", 8, 700))

    def refresh_colors(self):
        """Reapplique les couleurs — MEME logique que Column.refresh_colors
        (voir sa docstring), applique ici a l'inspecteur pour la premiere
        fois (voir la remarque de l'utilisateur, "je veux exactement le
        meme style, parametres par parametres") : fond/bordure/rayon du
        cadre suivent desormais Colonnes > Colonnes, comme toute colonne."""
        self.header_fill.setStyleSheet(column_header_qss("DetailHeader", INSPECTOR_TITLE))
        frame = column_frame_style(INSPECTOR_TITLE, self._suppress_left())
        # scaled() ICI, sur le MEME dict que celui repasse tel quel au
        # masque (voir _update_card_mask/Column.refresh_colors, MEME raison).
        scaled_radius = {k: scaled(v, 0) for k, v in frame["radius"].items()}
        self.card.setFrameStyle(
            frame["bg"], scaled_radius, frame["enabled"], frame["colors"], scaled(frame["thickness"], 0))
        self._update_card_mask()
        self.well.setStyleSheet(self._well_qss())
        self._apply_preview_table_style()
        self.open_render_log_button.setStyleSheet(
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; border: 1px solid {C['btn_border']}; "
            f"border-radius: 3px; padding: 0 7px; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
        )
        self.refresh_fonts(True if not self.values["kind"].text() else self.values["kind"].text() == "Dossier")

    INFO_TABLE_DIMS = "Inspecteur/Informations#0"

    _INFO_ROWS = (("kind", "Type"), ("size", "Taille"), ("modified", "Modifié"),
                  ("dimensions", "Dimensions · ratio · taille"),
                  # Photos Lightroom (demande de l'utilisateur) : d'ou vient le proxy (colonnes, inspecteur,
                  # diapositives) et l'image en plein ecran ; lignes masquees pour les autres fichiers.
                  ("proxy_source", "Source du proxy"),
                  ("full_source", "Source de l'aperçu plein écran"))
    _SOURCE_ROWS = ("proxy_source", "full_source")

    def _build_info_table(self):
        """Tableau des informations : le tableau Parametre | Valeur des reglages (_flat_cells_table) ;
        style commun des tableaux, Override settings au clic droit, dimensions enregistrees."""
        import settings_window_v2 as v2
        from settings_cells import keep_table_dims
        settings = ui_state.APPLIED_SETTINGS or load_settings()
        v2.seed_window_look(settings)
        rows = []
        for key, label in self._INFO_ROWS:
            value = self.preview_dimensions_value if key == "dimensions" else self.values[key]
            _set_text_role(value, "value")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)     # meme justification que sa cellule
            rows.append((label, value, None))
        frame = v2._flat_cells_table(rows)
        keep_table_dims(frame, self.INFO_TABLE_DIMS, settings)
        return frame

    def _fit_info_table(self):
        """Tant que les colonnes n'ont pas ete reglees a la main (dimensions enregistrees), le tableau
        prend toute la largeur de l'inspecteur : la colonne Valeur recoit ce que laisse celle des
        libelles ; reglees, elles gardent leur largeur (comme tout tableau des reglages)."""
        from settings_layout import _ResizableTableHeader
        from settings_widgets import _TABLE_DIMS
        frame = getattr(self, "preview_info_table", None)
        if frame is None or _TABLE_DIMS.get(frame.dimsKey()):
            return
        head = frame.findChild(_ResizableTableHeader)
        margins = self._content_layout.contentsMargins() if hasattr(self, "_content_layout") else None
        room = self.width() - (margins.left() + margins.right() if margins is not None else 32)
        room -= frame.layout().contentsMargins().left() + frame.layout().contentsMargins().right()
        if head is None or room < 120:
            return
        widths = head.columnWidths()
        widths = [widths[0], max(60, room - widths[0])]
        if widths == head.columnWidths():
            return
        frame._dims_autosave_paused = True
        try:
            head.setColumnWidths(widths)
        finally:
            frame._dims_autosave_paused = False

    def _attach_controls_row(self):
        """Ligne des boutons d'apercu : une ligne du tableau sur toute sa largeur (style des lignes du
        tableau, alternance et arrondi du bas compris)."""
        from settings_layout import _table_row
        row, row_layout = _table_row(M["table_row_b"], False)
        row_layout.setContentsMargins(6, 4, 6, 4)
        row_layout.addWidget(self.preview_controls_cell)
        self.preview_info_table.layout().addWidget(row)
        self._controls_row = row
        self._controls_row_meta = (row, M["table_row_b"], False)
        self.preview_info_table._flat_rows.append(self._controls_row_meta)
        self._restyle_info_table()

    def _restyle_info_table(self):
        """Style du tableau : le sien s'il a un override (clic droit > Override settings), sinon le commun."""
        from settings_layout import set_table_look
        from settings_widgets import ELEMENT_LOOKS
        frame = self.preview_info_table
        set_table_look(frame, ELEMENT_LOOKS.get(f"table:{frame.dimsKey()}"))
        from settings_layout import apply_part_looks
        from settings_widgets import PART_LOOKS
        if PART_LOOKS.get(frame.dimsKey()) or getattr(frame, "_text_look", None):    # cellule / ligne / colonne, police
            apply_part_looks(frame)

    def _apply_preview_table_style(self):
        """Applique au tableau de l'inspecteur le style des tableaux des reglages (ceux APPLIQUES, apercu
        en direct compris : relire le disque ecrasait l'apercu de la fenetre de reglages ouverte)."""
        import settings_window_v2 as v2
        settings = ui_state.APPLIED_SETTINGS or load_settings()
        # Rien de ce que lit ce tableau n'a change (ex. couleur d'un menu en cours de glisser) : ~10 ms
        # economisees a chaque cran de l'apercu en direct.
        sig = json.dumps({k: v for k, v in settings.items()
                          if k == "colors" or k.startswith(("table_", "toggle", "element_style", "slider_"))},
                         sort_keys=True, default=str)
        if sig == getattr(self, "_preview_table_sig", None):
            return
        self._preview_table_sig = sig
        colors = settings.get("colors") or {}
        _sync_dynamic_M(colors)
        if "colors" in settings:
            v2.seed_window_look(settings)
        self._restyle_info_table()
        _sync_toggle_style(settings)
        self.render_protection_toggle.apply_style()

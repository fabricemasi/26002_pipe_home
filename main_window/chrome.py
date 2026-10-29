"""Habillage de la fenêtre : boutons de mode, styles, tailles, polices, couleurs, ombres des boutons.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QPushButton

from app_style import C, resolve_color_ref, build_stylesheet, role_color, role_font, scaled
from settings_widgets import shadow_look
from browser_core import TITLEBAR_HEIGHT, entry_is_dir
import ui_state

from .helpers import _set_qss


class ChromeMixin:
    """Méthodes de PipelineBrowser : habillage de la fenêtre : boutons de mode, styles, tailles, polices, couleurs, ombres des boutons."""

    @staticmethod
    def _nav_input_height() -> int:
        """Hauteur des champs de la barre de navigation : Reglages > Zone de saisie > Hauteur (0 = 20 px), sans
        depasser la rangee des boutons."""
        from settings_store import input_height
        return min(scaled(TITLEBAR_HEIGHT), scaled(input_height() or 20))

    def _sync_collapse_button(self):
        """Icone / infobulle / disponibilite du bouton de repli des colonnes de la barre : replie ou deplie
        selon l'etat, grise quand les colonnes sont masquees (visionneuse)."""
        button = getattr(self, "btn_collapse", None)
        if button is None:
            return
        collapsed = bool(getattr(self, "_project_columns_collapsed", False))
        button.set_kind("dchevron_left" if collapsed else "dchevron_right")
        button.setToolTip("Deplier les colonnes de set" if collapsed else "Replier les colonnes de set")
        usable = (not getattr(self, "_project_columns_hidden", False) and not getattr(self, "_md_open", False)
                  and getattr(self, "_board", None) is None)
        self._set_button_usable(button, usable)
        self._sync_mode_buttons()

    @staticmethod
    def _set_button_usable(button, usable: bool):
        if button.isEnabled() == usable and (button.graphicsEffect() is None) == usable:
            return
        button.setEnabled(usable)
        button.setGraphicsEffect(None)
        if not usable:
            effect = QGraphicsOpacityEffect(button)
            effect.setOpacity(0.35)
            button.setGraphicsEffect(effect)

    def _selected_path(self) -> tuple:
        """(colonne, chemin) du choix le plus profond des colonnes, ou (None, None)."""
        for column in reversed(getattr(self, "columns", [])):
            try:
                path = column.current_path()
            except RuntimeError:
                continue
            if path is not None:
                return column, Path(path)
        return None, None

    def _sync_mode_buttons(self):
        """Boutons visionneuse / editeur de texte de la barre : l'editeur n'est disponible que sur un fichier
        texte selectionne (ou deja ouvert, pour en sortir) ; la visionneuse sur une selection (ou ouverte)."""
        if not hasattr(self, "btn_text_editor"):
            return
        import fm_markdown as mdeditor
        editing = getattr(self, "_md_open", False)
        _column, path = self._selected_path()
        viewer_open = getattr(self, "_project_columns_hidden", False)
        # Type repris de la lecture du dossier (un `is_file()` par bouton = 3 allers-retours par clic en reseau).
        is_file = path is not None and not entry_is_dir(path)
        self._set_button_usable(self.btn_text_editor,
                                editing or (not viewer_open and is_file and mdeditor.is_text_file(path)))
        self._set_button_usable(self.btn_viewer, viewer_open or editing or path is not None)
        self.btn_text_editor.set_alert(self._mode_on_color() if editing else None)
        self.btn_viewer.set_alert(self._mode_on_color() if viewer_open else None)
        import fm_board as board
        on_board = self._board is not None
        self._set_button_usable(self.btn_board, on_board or (not viewer_open and is_file and (
            board.is_board_file(path) or board.is_cad_drawing(path))))
        self.btn_board.set_alert(self._mode_on_color() if on_board else None)
        import fm_video as video
        on_video = getattr(self, "_video", None) is not None
        self._set_button_usable(self.btn_video, on_video or (not viewer_open and is_file
                                                             and video.is_media_file(path)))
        self.btn_video.set_alert(self._mode_on_color() if on_video else None)

    @staticmethod
    def _mode_on_color() -> str:
        color = QColor(C["accent"])
        color.setAlpha(90)
        return color.name(QColor.HexArgb)

    # -- Bouton « visionneuse » de la barre --

    def _on_viewer_button(self):
        """Visionneuse ouverte : retour aux colonnes. Sinon elle s'ouvre sur la selection : un fichier a apercu
        tel quel, un dossier (sa premiere photo), un autre fichier (les photos de son dossier)."""
        if self._project_columns_hidden:
            self._toggle_project_columns_hidden()
            return
        if not self._close_md_editor():
            return
        if self._board is not None and not self._close_board():
            return
        self._close_video()
        from column import opens_in_viewer
        column, path = self._selected_path()
        if path is None:
            return
        if path.is_dir():
            self._view_folder_in_viewer(path, column)
        elif opens_in_viewer(path):
            self._view_in_viewer(path, column)
        else:
            self._view_folder_in_viewer(path.parent, column)

    def _apply_global_stylesheet(self):
        """Feuille de style commune (boutons, zones de saisie, couleurs) reappliquee a la fenetre principale et a
        tout ce qui en depend — PAS a l'application entiere : `QApplication.setStyleSheet` repolit TOUS les
        widgets, y compris ceux de la fenetre de reglages gardee en memoire (~24 000, soit ~70 s) ; sur la seule
        fenetre principale (~160 widgets) : ~0,05 s. La feuille de l'application (posee au lancement) reste la base ;
        celle-ci passe devant pour tout ce qui est dans la fenetre principale."""
        self.setStyleSheet(build_stylesheet())

    def refresh_chrome_sizes(self):
        """Reapplique l'echelle courante (voir app_style.scaled) aux
        widgets permanents de la fenetre (barre de titre, barre du haut),
        qui comme leurs polices (voir refresh_chrome_fonts) ne sont
        construits qu'une fois et ne suivraient donc pas le slider d'echelle
        sans ce rafraichissement explicite."""
        self.titlebar.refresh_sizes()
        self.titlebar.refresh_look()
        self.root_field.setFixedHeight(self._nav_input_height())
        self.root_field.setFixedWidth(scaled(190))
        self.preset_picker.select.setFixedHeight(self._nav_input_height())

    def refresh_chrome_fonts(self):
        """Reapplique les polices de role aux widgets permanents de la
        fenetre (topbar, statut, panneau de detail), qui contrairement aux
        colonnes ne sont pas recrees par reload()."""
        self.titlebar.refresh_look()
        self.root_field.setFont(role_font("info", 11, 400))
        for btn in (self.btn_browse, self.btn_presets, self.btn_settings, self.btn_style, self.btn_collapse,
                    self.btn_viewer, self.btn_text_editor, self.btn_board, self.btn_video):
            btn.set_colors(role_color("buttons", "#c4cacf"), C["text"])
        self.path_label.setFont(role_font("info", 11, 400))
        self.path_label.setStyleSheet(f"color: {role_color('info', C['text_mono'])}; background: transparent;")
        self.status_right.setFont(role_font("info2", 11, 400))
        self.status_right.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")
        for column in self.columns:
            column.refresh_header()
        self.detail.refresh_header()
        for column in self.image_preview_columns:
            column.refresh_header()
        for column in self.group_columns:
            column.refresh_header()
        is_dir = True
        if self.columns:
            selected = self.columns[-1].current_path()
            if selected is not None:
                is_dir = selected.is_dir()
        self.detail.refresh_fonts(is_dir)

    def refresh_colors(self, rebuild_stylesheet: bool = True):
        """Reapplique toutes les couleurs (voir app_style.C, mutable via
        set_color) aux widgets dont le style QSS a ete fixe une fois pour
        toutes a la construction — indispensable pour que la page Couleurs
        de la fenetre de parametres s'applique en temps reel (voir la
        remarque sur set_color dans app_style.py).

        rebuild_stylesheet=False saute uniquement le app.setStyleSheet
        global (repolissage de TOUS les widgets de l'appli, tres couteux) :
        a utiliser quand on sait qu'aucune des valeurs lues par
        build_stylesheet (couleurs, cadre/rayon des boutons, cadre/rayon des
        zones de saisie, rayon des tableaux) n'a bouge (voir _apply_settings),
        le reste de cette methode restant assez leger pour tourner a chaque
        rafraichissement."""
        if rebuild_stylesheet:
            self._apply_global_stylesheet()
        self.central.update()          # cadre central peint (CentralFrame) : fond, filet et coins relus
        _set_qss(self.columns_host, f"#ColumnsHost {{ background: {C['window']}; }}")
        self.titlebar.refresh_look()
        for btn in (self.titlebar.btn_min, self.titlebar.btn_max, self.titlebar.btn_close):
            btn.set_colors(C["label"], C["text"])
        self._refresh_button_shadows()
        _set_qss(self.statusbar, f"#StatusBar {{ background: {C['chrome']}; border-top: 1px solid {C['border']}; }}")
        for column in self.columns:
            column.refresh_colors()
        for column in self.group_columns:
            column.refresh_colors()
        for column in self.image_preview_columns:
            column.refresh_colors()
        self.detail.refresh_colors()
        self.refresh_chrome_fonts()

    def _refresh_button_shadows(self):
        """Ombre du groupe Bouton sur les boutons de la fenêtre principale."""
        look = shadow_look(ui_state.APPLIED_SETTINGS or {}, "button_shadow", resolve_color_ref)
        # Meme ombre que la derniere fois : seuls les boutons NOUVEAUX en ont besoin (chaque tick d'un glisser
        # de couleur reposait l'effet sur tous les boutons : effets graphiques recalcules, lent).
        sig = repr(look)
        unchanged = sig == getattr(self, "_button_shadow_sig", None)
        self._button_shadow_sig = sig
        for button in self.findChildren(QPushButton):
            own = getattr(button, "_app_shadow_effect", None)
            if unchanged and (own is not None or look is None):
                continue
            if look is None:
                if own is not None:
                    button.setGraphicsEffect(None)
                    button._app_shadow_effect = None
                continue
            if own is None and button.graphicsEffect() is not None:
                continue
            if own is None:
                own = QGraphicsDropShadowEffect(button)
                button._app_shadow_effect = own
                button.setGraphicsEffect(own)
            sides = look["on"]
            size = look["size"]
            own.setBlurRadius(max(1, size * 2))
            own.setOffset((int(sides["right"]) - int(sides["left"])) * size / 3,
                          (int(sides["bottom"]) - int(sides["top"])) * size / 3)
            color = next((look["colors"][side] for side in ("bottom", "right", "top", "left") if sides[side]), None)
            if color is None:                      # aucun cote allume : pas d'ombre (jamais d'exception ici)
                button.setGraphicsEffect(None)
                button._app_shadow_effect = None
                continue
            own.setColor(QColor(color))

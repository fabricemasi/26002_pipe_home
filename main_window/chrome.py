"""Habillage de la fenêtre : boutons de mode, styles, tailles, polices, couleurs, ombres des boutons.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsOpacityEffect, QPushButton

from app_style import C, resolve_color_ref, build_stylesheet, role_color, role_font, scaled
from browser_core import TITLEBAR_HEIGHT
import ui_state

from .helpers import _set_qss


class ChromeMixin:
    """Méthodes de PipelineBrowser : habillage de la fenêtre : boutons de mode, styles, tailles, polices, couleurs, ombres des boutons."""

    @staticmethod
    def _nav_input_height() -> int:
        """Hauteur du champ racine et du menu des presets de la barre de navigation : celle du cadre des icones
        (fm_browser > Barre de navigation > Taille des icones, demande de l'utilisateur 2026-11-07), et non plus
        Reglages > Zone de saisie > Hauteur."""
        from main_window.title_bar import nav_tool_metrics
        from settings_store import navbar_effective
        settings = navbar_effective(ui_state.APPLIED_SETTINGS or {})      # hauteur : override de fm_browser
        try:                                     # 1re ligne de la barre : fm_theme > Barre de navigation > Hauteur
            row = max(scaled(16, 0), scaled(int(settings.get("navbar_height", TITLEBAR_HEIGHT)), 0))
        except (TypeError, ValueError):
            row = scaled(TITLEBAR_HEIGHT, 0)
        return nav_tool_metrics(settings, row)[0]

    def _sync_collapse_button(self):
        """Icone / infobulle / disponibilite du bouton de repli des colonnes de la barre : replie ou deplie
        selon l'etat, grise quand les colonnes sont masquees (visionneuse)."""
        sync_back = getattr(self, "_sync_mouse_back", None)
        if sync_back is not None:
            sync_back()                         # bouton « precedent » : suit l'ouverture / fermeture des modules
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
        # Bouton a couleur desactivee propre (icones de la barre, Icones > Couleur des icones) : son icone change de
        # couleur, plus de voile d'opacite.
        dim = not usable and not getattr(button, "_disabled_color", None)
        if button.isEnabled() == usable and (button.graphicsEffect() is not None) == dim:
            return
        button.setEnabled(usable)
        button.setGraphicsEffect(None)
        if dim:
            from fm_theme.widgets import dimmed_opacity
            effect = QGraphicsOpacityEffect(button)
            effect.setOpacity(dimmed_opacity())              # Valeur du grise (fm_theme > General), avant 0.35
            button._unusable_veil = True                     # suivi en direct quand la valeur change
            button.setGraphicsEffect(effect)

    def _selected_path(self) -> tuple:
        """(colonne, chemin) du choix le plus profond des colonnes, ou (None, None). Une ligne choisie dans le groupe
        IN / OVER / OUT / LOGICIELS (hors de `self.columns`) compte tant qu'aucune colonne ouverte après lui n'a de
        sélection : même règle que le focus (`update_active_column`)."""
        def deepest(columns):
            for column in reversed(columns):
                try:
                    path = column.current_path()
                except RuntimeError:
                    continue
                if path is not None:
                    return column, Path(path)
            return None, None
        columns = getattr(self, "columns", [])
        group = getattr(self, "_last_active_group_column", None)
        if group is not None:
            found = deepest([group])
            if found[1] is not None:
                after = deepest(columns[self._chain_expected_total():])
                return after if after[1] is not None else found
        return deepest(columns)

    def _sync_mode_buttons(self):
        """Boutons de mode de la barre : chaque module est dégrisé sur un fichier qu'il sait ouvrir (ou quand il
        est ouvert, pour en sortir), que le fichier soit choisi dans les colonnes ou montré par la visionneuse
        (focus, planche) : `_module_path`, table `module_targets`. La visionneuse : sur un fichier qu'elle sait
        montrer (`opens_in_viewer`), ou ouverte (pour en sortir)."""
        if not hasattr(self, "btn_text_editor"):
            return
        editing = getattr(self, "_md_open", False)
        keys = self._module_keys()
        viewer_open = getattr(self, "_project_columns_hidden", False)
        self._set_button_usable(self.btn_text_editor, editing or "md" in keys)
        self._set_button_usable(self.btn_viewer, viewer_open or "viewer" in keys)
        self.btn_text_editor.set_alert(self._mode_on_color() if editing else None)
        self.btn_viewer.set_alert(self._mode_on_color() if viewer_open else None)
        on_board = self._board is not None
        self._set_button_usable(self.btn_board, on_board or not keys.isdisjoint(("board", "cad", "sheet")))
        self.btn_board.set_alert(self._mode_on_color() if on_board else None)
        on_video = getattr(self, "_video", None) is not None
        self._set_button_usable(self.btn_video, on_video or "video" in keys)
        self.btn_video.set_alert(self._mode_on_color() if on_video else None)
        on_font = getattr(self, "_font", None) is not None
        self._set_button_usable(self.btn_font, on_font or "font" in keys)
        self.btn_font.set_alert(self._mode_on_color() if on_font else None)
        btn_pdf = getattr(self, "btn_pdf", None)                       # éditeur PDF (fm_pdf)
        if btn_pdf is not None:
            on_pdf = getattr(self, "_pdf", None) is not None
            self._set_button_usable(btn_pdf, on_pdf or "pdf" in keys)
            btn_pdf.set_alert(self._mode_on_color() if on_pdf else None)
        btn_agenda = getattr(self, "btn_agenda", None)                 # agenda (fm_agenda) : toujours actif
        if btn_agenda is not None:
            on_agenda = self._agenda_open() if hasattr(self, "_agenda_open") else False
            self._set_button_usable(btn_agenda, True)
            btn_agenda.set_alert(self._mode_on_color() if on_agenda else None)
        btn_taches = getattr(self, "btn_taches", None)                 # tâches (fm_taches) : toujours actif
        if btn_taches is not None:
            on_taches = self._taches_open() if hasattr(self, "_taches_open") else False
            self._set_button_usable(btn_taches, True)
            btn_taches.set_alert(self._mode_on_color() if on_taches else None)
        for name, kind in (("btn_audio", "audio"), ("btn_music", "music")):   # FM Audio / FM Music : toujours actifs
            btn = getattr(self, name, None)
            if btn is not None:
                pane = getattr(self, "_audio_pane" if kind == "audio" else "_music_pane", None)
                self._set_button_usable(btn, True)
                btn.set_alert(self._mode_on_color() if pane is not None and pane.isVisible() else None)

    @staticmethod
    def _mode_on_color() -> str:
        color = QColor(C["accent"])
        color.setAlpha(90)
        return color.name(QColor.HexArgb)

    # -- Bouton « visionneuse » de la barre --

    def _toggle_columns_shown(self):
        """Bouton de la barre : masque / montre toutes les colonnes (pas pendant un module ni la visionneuse, qui
        les recouvrent déjà)."""
        host = self.scroll.widget()
        if (host is None or self._project_columns_hidden or getattr(self, "_md_open", False)
                or getattr(self, "_board", None) is not None or getattr(self, "_font", None) is not None
                or (hasattr(self, "_agenda_open") and self._agenda_open())
                or (hasattr(self, "_taches_open") and self._taches_open())):
            return
        hidden = not host.isHidden()
        host.setVisible(not hidden)
        self._columns_user_hidden = hidden
        self.btn_columns.set_kind("show_columns" if hidden else "fade_columns")
        self.btn_columns.setToolTip("Montrer les colonnes" if hidden else "Masquer les colonnes")
        self._set_button_usable(self.btn_columns, True)

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
        leave_agenda = getattr(self, "_leave_agenda", None)        # agenda ouvert : rangé d'abord (fm_agenda)
        if leave_agenda is not None:
            leave_agenda()
        leave_taches = getattr(self, "_leave_taches", None)        # tâches ouvertes : rangées d'abord (fm_taches)
        if leave_taches is not None:
            leave_taches()
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

    # Bouton de la barre -> sa cle de la colonne Couleur (fm_browser > Barre de navigation > Icones).
    _NAV_ICON_COLORS = (("btn_theme", "theme"), ("btn_viewer", "viewer"), ("btn_text_editor", "text_editor"),
                        ("btn_board", "board"), ("btn_video", "video"), ("btn_font", "font"), ("btn_pdf", "pdf"),
                        ("btn_agenda", "agenda"), ("btn_taches", "taches"), ("btn_audio", "audio"),
                        ("btn_music", "music"))

    def _refresh_navbar_icons(self):
        """Icones de la barre : couleur de base et couleur desactivee (fm_browser > ICONES > Couleur des icones) ;
        chaque bouton de la colonne Couleur (fm_browser > Barre de navigation > Icones), s'il est actif, sa couleur
        en mode de fusion (produit) (demande de l'utilisateur, 2026-11-08 ; jamais les couleurs des modules du
        board)."""
        if not hasattr(self, "btn_browse"):
            return
        settings = ui_state.APPLIED_SETTINGS or {}
        base = resolve_color_ref(settings.get("navtool_icon_base_color"), role_color("buttons", "#c4cacf"))
        # Bouton inutilisable : la couleur de base a l'opacite de la « Valeur du grise » (fm_theme > General,
        # `dimmed_opacity`), comme tout objet non utilisable (demande de l'utilisateur, 2026-11-12 ; remplace la
        # « Couleur desactivee » de fm_browser > ICONES).
        # Bouton inutilisable : fond et bordures a la valeur du grise « elements d'interface », icone (couleur de
        # base) a celle des « icones » (fm_theme > General).
        from fm_theme.widgets import dimmed_icon_opacity, dimmed_opacity
        grey, grey_icon = dimmed_opacity(), dimmed_icon_opacity()
        theme = getattr(self, "btn_theme", None)
        for btn in (self.btn_browse, self.btn_presets, self.btn_settings, self.btn_style, self.btn_collapse,
                    self.btn_columns, self.btn_viewer, self.btn_text_editor, self.btn_board, self.btn_video,
                    self.btn_font, getattr(self, "btn_pdf", None), getattr(self, "btn_agenda", None),
                    getattr(self, "btn_taches", None), getattr(self, "btn_audio", None),
                    getattr(self, "btn_music", None), theme):
            if btn is None:
                continue
            btn.set_colors(base, C["text"])
            btn.set_disabled_color(base)                        # inutilisable : icone de la couleur de base...
            btn.set_disabled_opacity(grey, grey_icon)           # ...cadre et icone, chacun a sa valeur du grise
            if btn.graphicsEffect() is not None and not btn.isEnabled():
                btn.setGraphicsEffect(None)                     # ancien voile d'opacite : la couleur le remplace
        from settings_store import DEFAULT_SETTINGS
        try:
            tone = int(settings.get("navtool_icon_tone_value", DEFAULT_SETTINGS["navtool_icon_tone_value"]))
        except (TypeError, ValueError):
            tone = DEFAULT_SETTINGS["navtool_icon_tone_value"]
        for name, suffix in self._NAV_ICON_COLORS:
            btn = getattr(self, name, None)
            if btn is not None:
                key = f"navtool_icon_color_{suffix}"
                default = DEFAULT_SETTINGS.get(key, "#ffffff")
                btn.set_icon_tone_value(tone)       # fond de l'icone coloree, module ouvert (2026-11-08)
                btn.set_icon_blend(resolve_color_ref(settings.get(key) or default, default))

    def refresh_navbar(self):
        """Barre de navigation seule (fm_theme > Barre de navigation : hauteur, bordure, titre, bouton fm_theme) :
        chemin rapide des apercus en direct, sans toucher aux colonnes."""
        self.titlebar.refresh_sizes()
        self.titlebar.refresh_look()
        self.titlebar.restyle_module_groups()      # cadre des modules : habillage, taille des boutons = icones
        self._refresh_navbar_icons()
        self.root_field.setFixedHeight(self._nav_input_height())      # jamais plus haut que la 1re ligne
        self.preset_picker.select.setFixedHeight(self._nav_input_height())

    def refresh_status_bar(self):
        """Barre d'etat : fm_theme > Barre d'etat (hauteur, fond, bordure, marges, textes), `fm_theme.status_bar`."""
        from fm_theme.status_bar import apply_status_bar
        apply_status_bar(self.statusbar, {"path": self.path_label, "info": self.status_right},
                         ui_state.APPLIED_SETTINGS or {})

    def refresh_chrome_fonts(self):
        """Reapplique les polices de role aux widgets permanents de la
        fenetre (topbar, statut, panneau de detail), qui contrairement aux
        colonnes ne sont pas recrees par reload()."""
        self.titlebar.refresh_look()
        self.root_field.setFont(role_font("info", 11, 400))
        self._refresh_navbar_icons()
        self.refresh_status_bar()
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
        self.central.sync_margins()    # cadre central peint (CentralFrame) : fond, bordure et coins relus
        self.central.update()
        _set_qss(self.columns_host, f"#ColumnsHost {{ background: {C['window']}; }}")
        self.titlebar.refresh_look()
        for btn in (self.titlebar.btn_min, self.titlebar.btn_max, self.titlebar.btn_close):
            btn.set_colors(C["label"], C["text"])
        self._refresh_button_shadows()
        self.refresh_status_bar()
        for column in self.columns:
            column.refresh_colors()
        for column in self.group_columns:
            column.refresh_colors()
        for column in self.image_preview_columns:
            column.refresh_colors()
        self.detail.refresh_colors()
        self.refresh_chrome_fonts()

    def _refresh_button_shadows(self):
        """Ombre du groupe Bouton : posée sur TOUS les boutons de l'appli par le style commun
        (fm_theme.style._AppStyle, à la création) et reposée quand le réglage change (set_control_look) ;
        ici seulement le filet de sécurité (rien n'est refait si l'ombre est déjà la bonne)."""
        from fm_theme.style import apply_button_shadow
        for button in self.findChildren(QPushButton):
            apply_button_shadow(button)

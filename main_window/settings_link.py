"""Presets, fenêtre de réglages (ouverture, préchargement sur inactivité), application des réglages.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

from app_style import C, STYLESHEET_COLOR_KEYS, column_gap, scaled
from config import GLOBAL_OMIT_DIR_NAMES, GLOBAL_OMIT_FILE_EXTENSIONS, GLOBAL_OMIT_FILE_NAMES
from settings_store import load_settings
from browser_core import COLUMN_SETTINGS, _is_globally_omitted_path, apply_all_settings
from column import Column
import ui_state

from .helpers import _AppInputWatch


# Aspect des briques (fm_theme) : chemin rapide de _apply_settings, seuls ces widgets sont refaits.
_BRICK_PREFIXES = ("slider_", "title_level", "table_", "toggle", "ctx_", "extra_window_")


def settings_window_v2_preload_enabled() -> bool:
    """Prechargement de la fenetre de reglages au lancement (coupe par PIPELINE_NO_PREBUILD : tests)."""
    return not os.environ.get("PIPELINE_NO_PREBUILD")


class SettingsLinkMixin:
    """Méthodes de PipelineBrowser : presets, fenêtre de réglages (ouverture, préchargement sur inactivité), application des réglages."""

    # -- Presets (menu deroulant de la barre du haut, fenetre « Gerer les presets ») --

    def _choose_preset(self, name: str):
        """Menu deroulant : `name` devient le preset actif ("" = aucun) ; ses valeurs sont appliquees a
        toute l'appli et enregistrees (pipeline_settings.json)."""
        from settings_store import apply_preset
        settings = apply_preset(name)
        self._apply_settings(settings)
        # Valeurs de punaise propres au preset (browser_core.PIN_LAYOUT_KEYS) : chaque colonne reprend les siennes.
        for column in self.findChildren(Column):
            try:
                column.reload_pin_state()
            except RuntimeError:
                pass
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            if dialog is not None and dialog.isVisible():
                dialog.external_values(settings)        # ses champs ouverts suivent le preset
        except RuntimeError:
            pass
        self._refresh_preset_ui(settings)

    # -- Preset fm_theme lie (theme_preset) : fichier surveille, canal temps reel de l'editeur (fm_theme/live.py) --

    def _start_theme_link(self):
        """Au lancement (main) : l'aspect suit le preset fm_theme lie, modifie ailleurs (fm_theme.bat, autre appli)
        pendant le geste par le canal, a la fin du geste par son fichier."""
        from fm_theme import live
        self._theme_watcher = live.PresetWatcher(self)
        self._theme_watcher.changed.connect(self._on_theme_file_changed)
        self._theme_live = live.LiveClient(self)
        self._theme_live.received.connect(self._on_theme_live)
        self._sync_theme_watch(ui_state.APPLIED_SETTINGS or load_settings())

    def _sync_theme_watch(self, settings: dict):
        """Surveille le fichier du preset fm_theme lie (change avec le preset choisi). Rien si inchange."""
        watcher = getattr(self, "_theme_watcher", None)
        name = settings.get("theme_preset") or ""
        if watcher is None or name == getattr(self, "_theme_watch_name", None):
            return
        from settings_store import theme_in_use
        import fm_theme.presets as theme_presets
        self._theme_watch_name = name
        watcher.watch(theme_presets.find_preset(name) if theme_in_use(settings) else None)

    def _on_theme_file_changed(self):
        """Preset fm_theme enregistre ailleurs : relu et applique (seul ce qui a change est refait)."""
        settings = load_settings()
        self._apply_settings(settings)
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            if dialog is not None and dialog.isVisible():
                dialog.external_values(settings)        # ses champs ouverts suivent
        except RuntimeError:
            pass

    def _on_theme_live(self, preset: str, values: dict):
        """Valeurs diffusees PENDANT un geste dans l'editeur (au plus une fois par image) : appliquees tout de
        suite si elles visent le preset fm_theme a l'ecran, sans lire ni ecrire le disque."""
        from settings_store import theme_in_use
        current = ui_state.APPLIED_SETTINGS or {}
        if not values or not preset or preset != theme_in_use(current):
            return
        settings = dict(current)
        settings.update(values)
        self._apply_settings(settings, set(values))

    def open_theme_editor(self):
        """Editeur fm_theme (aspect generique) sur le preset fm_theme lie, dans ce processus : ses gestes
        s'appliquent en direct a cette fenetre (`_on_theme_live`), ses enregistrements par le fichier surveille."""
        import theme_editor
        from settings_store import theme_in_use
        editor = getattr(self, "_theme_editor", None)
        try:
            if editor is not None and editor.window.isVisible():
                editor.window.raise_()
                editor.window.activateWindow()
                return
        except RuntimeError:
            pass
        name = theme_in_use(ui_state.APPLIED_SETTINGS or load_settings()) or theme_editor.initial_preset()
        self._theme_editor = theme_editor.ThemeEditor(name, listeners=[self._on_theme_live])

    def _refresh_preset_ui(self, settings: dict | None = None):
        import settings_window_v2
        settings = settings or ui_state.APPLIED_SETTINGS or load_settings()
        settings_window_v2.seed_window_look(settings)
        self.preset_picker.restyle()
        self.preset_picker.refresh(settings)

    def _open_preset_manager(self):
        from settings_presets import PresetManagerWindow
        window = self._preset_manager
        try:
            if window is not None and window.isVisible():
                window.raise_()
                window.activateWindow()
                return
        except RuntimeError:
            pass
        window = self._preset_manager = PresetManagerWindow(ui_state.APPLIED_SETTINGS or load_settings(), parent=self)
        window.presetsChanged.connect(lambda: self.preset_picker.refresh())
        # Theme d'un preset change : s'il est a l'ecran, l'aspect suit tout de suite.
        window.themeChanged.connect(lambda _n: self._apply_settings(load_settings()))
        window.destroyed.connect(lambda *_a: setattr(self, "_preset_manager", None))
        window.adjustSize()
        anchor = self.preset_picker.mapToGlobal(QPoint(0, self.preset_picker.height() + 6))
        window.move(anchor)
        window.show()

    def open_settings_v2(self):
        """Ouvre la fenetre de reglages (settings_window_v2.py), gardee en memoire d'une ouverture a l'autre."""
        import settings_window_v2
        existing = getattr(self, "_settings_dialog_v2", None)
        try:
            if existing is not None and existing.isVisible():
                existing.raise_()
                return
        except RuntimeError:
            pass
        # Fenetre gardee en memoire (preparee sur inactivite, voir _start_settings_idle_watch) : on la rouvre telle
        # quelle, remise a jour des reglages changes entre-temps. Fermee en annulant des modifications, ses
        # champs gardent ces valeurs : elle est jetee et refaite.
        try:
            if existing is not None and not existing.isVisible() and not existing.discard_on_reopen():
                existing.reopen()
                return
            if existing is not None:
                existing.deleteLater()
        except RuntimeError:
            pass
        dialog = self._make_settings_v2()
        dialog.show()

    def _make_settings_v2(self):
        """Cree la fenetre de reglages v2 (cachee) et la garde pour toute la session."""
        import settings_window_v2
        # SANS parent (lien « transitoire » de fenetre seulement : elle reste au-dessus de celle-ci) : la feuille de
        # style de la fenetre principale ne se propage pas a ses ~20 000 widgets (voir _apply_global_stylesheet).
        dialog = settings_window_v2.SettingsWindowV2(None)
        dialog.prebuild_unattended = self._settings_unattended
        dialog.prebuild_progress = self._on_settings_prebuild_progress
        self._wire_settings_dialog(dialog)
        dialog.moduleSettingsRequested.connect(self.open_module_settings)
        dialog.themeEditorRequested.connect(self.open_theme_editor)
        self._settings_dialog_v2 = dialog
        return dialog

    def _wire_settings_dialog(self, dialog):
        """Commun a la fenetre generale et a celles des modules : au-dessus de la fenetre principale, apercu en
        direct et enregistrement par les memes rappels."""
        dialog.prebuild_hold = self._settings_prebuild_hold
        dialog.create()
        handle, owner = dialog.windowHandle(), self.windowHandle()
        if handle is not None and owner is not None:
            handle.setTransientParent(owner)
        dialog.settingsChanged.connect(
            lambda settings, d=dialog: self._apply_settings(settings, getattr(d, "live_changed_keys", None)))
        dialog.settingsSaved.connect(self._apply_settings)

    def open_module_settings(self, module: str):
        """Fenetre de reglages d'un module (cle de settings_window_v2.MODULE_SCOPES : video, markdown, board, viewer),
        ouverte par le bouton du cadre du module ou par la rangee de la fenetre generale. MEME classe que la
        generale (seuls ses onglets changent), construite a la premiere ouverture puis gardee comme elle."""
        import settings_window_v2
        windows = getattr(self, "_module_settings", None)
        if windows is None:
            windows = self._module_settings = {}
        existing = windows.get(module)
        try:
            if existing is not None and existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return
            if existing is not None and not existing.discard_on_reopen():
                existing.reopen()
                return
            if existing is not None:
                existing.deleteLater()
        except RuntimeError:
            pass
        dialog = settings_window_v2.SettingsWindowV2(None, module=module)
        self._wire_settings_dialog(dialog)
        windows[module] = dialog
        dialog.show()

    def _heavy_foreground_work(self) -> bool:
        """Vrai quand l'appli a besoin de toute la boucle d'interface : lecture video en cours. Les preparations
        de fond qui s'executent sur le fil de l'interface (fenetre de reglages) attendent."""
        pane = getattr(self, "_video", None)
        return bool(pane is not None and getattr(pane, "_playing", False))

    # -- Chargement des reglages sur inactivite (demande de l'utilisateur) --
    # Plus rien au lancement : la fenetre de reglages est creee cachee et ses sections construites en fond
    # seulement apres SETTINGS_IDLE_LOAD_S sans aucune action sur l'APPLI (l'activite du reste de l'ordinateur ne
    # compte pas), jamais pendant qu'un module (Markdown, board, visionneuse, video) est ouvert. Le moindre geste
    # sur l'appli l'arrete aussitot (filtre d'application pose seulement pendant le chargement) ; il reprend ou
    # il en etait a la prochaine minute d'inactivite. Avancement : barre « Réglages n % » de la barre de navigation.

    SETTINGS_IDLE_LOAD_S = 60.0
    _INPUT_EVENTS = frozenset((QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonDblClick,
                               QEvent.Wheel, QEvent.KeyPress, QEvent.NonClientAreaMouseMove,
                               QEvent.NonClientAreaMouseButtonPress, QEvent.TouchBegin, QEvent.TabletPress))

    def _start_settings_idle_watch(self):
        """Releve de l'activite de l'appli, une fois par seconde (aucun filtre d'evenements permanent)."""
        if not settings_window_v2_preload_enabled() or getattr(self, "_settings_idle_timer", None) is not None:
            return
        self._settings_idle_loading = False
        self._app_input_at = time.monotonic()
        from automatic_tasks import AutomaticTasks
        self._automatic_tasks = AutomaticTasks(self)
        self.titlebar.set_load_progress(0)
        self.titlebar.set_load_progress(None)
        timer = self._settings_idle_timer = QTimer(self)
        timer.setInterval(1000)
        timer.timeout.connect(self._settings_idle_tick)
        timer.start()

    def _module_open(self) -> bool:
        """Un module occupe l'appli : Markdown / code, board, visionneuse (ou planche), video."""
        return bool(getattr(self, "_md_open", False) or getattr(self, "_board", None) is not None
                    or getattr(self, "_video", None) is not None or getattr(self, "_project_columns_hidden", False))

    def _app_used_recently(self) -> bool:
        """Entree clavier / souris recente ET destinee a l'appli (fenetre active, ou curseur sur l'une de ses
        fenetres) : l'horloge d'entree de Windows seule compterait tout l'ordinateur."""
        import settings_window_v2
        if QApplication.mouseButtons() != Qt.NoButton and QApplication.activeWindow() is not None:
            return True
        idle = settings_window_v2._system_idle_ms()
        cursor = QCursor.pos()
        if idle is None:                                   # hors Windows : mouvement du curseur sur l'appli
            last, self._idle_cursor = getattr(self, "_idle_cursor", None), cursor
            return last is not None and last != cursor and QApplication.widgetAt(cursor) is not None
        if idle > 1500:
            return False
        return QApplication.activeWindow() is not None or QApplication.widgetAt(cursor) is not None

    def _live_settings_dialog(self):
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            if dialog is not None:
                dialog.isVisible()
            return dialog
        except RuntimeError:
            self._settings_dialog_v2 = None                # detruite
            return None

    def _settings_idle_tick(self):
        automatic = getattr(self, "_automatic_tasks", None)
        if automatic is not None:
            automatic.tick()
            return
        now = time.monotonic()
        dialog = self._live_settings_dialog()
        if self._settings_idle_loading:
            if self._module_open() or self._heavy_foreground_work() or (dialog is not None and dialog.isVisible()):
                self._stop_settings_idle_load()
            return
        if self._module_open() or self._heavy_foreground_work() or self._app_used_recently():
            self._app_input_at = now                       # module ouvert : la minute ne compte qu'apres sa fermeture
            return
        if dialog is not None and (dialog.isVisible()
                                   or (dialog.prebuild_finished() and not dialog.discard_on_reopen())):
            return                                         # ouverte (elle se construit seule) ou deja prete
        if now - self._app_input_at >= self.SETTINGS_IDLE_LOAD_S:
            self._begin_settings_idle_load()

    def _begin_settings_idle_load(self):
        dialog = self._live_settings_dialog()
        if dialog is not None and dialog.discard_on_reopen():
            dialog.deleteLater()                           # fermee en annulant : ses champs ne servent plus
            dialog = self._settings_dialog_v2 = None
        self._settings_idle_loading = True
        self._background_status.report('settings', 'Chargement des réglages en mémoire')
        watch = getattr(self, "_idle_input_watch", None)
        if watch is None:
            watch = self._idle_input_watch = _AppInputWatch(self._INPUT_EVENTS, self._stop_settings_idle_load)
        QApplication.instance().installEventFilter(watch)
        if dialog is None:
            dialog = self._make_settings_v2()
        self.titlebar.set_load_progress(int(dialog.prebuild_fraction() * 100))
        dialog.start_background_build()

    def _stop_settings_idle_load(self):
        """L'utilisateur revient (ou un module s'ouvre) : chargement suspendu, barre retiree, minute recomptee."""
        self._app_input_at = time.monotonic()
        if not getattr(self, "_settings_idle_loading", False):
            return
        self._settings_idle_loading = False
        self._background_status.finish('settings', 'Chargement des réglages terminé ou suspendu')
        watch = getattr(self, "_idle_input_watch", None)
        if watch is not None:
            QApplication.instance().removeEventFilter(watch)
        self.titlebar.set_load_progress(None)

    def _settings_unattended(self) -> bool:
        """Chargement sur inactivite en cours, fenetre de reglages cachee."""
        dialog = self._live_settings_dialog()
        return bool(getattr(self, "_settings_idle_loading", False) and dialog is not None
                    and not dialog.isVisible())

    def _settings_prebuild_hold(self) -> bool:
        """Preparation suspendue : lecture video, ou fenetre cachee hors du chargement sur inactivite (fenetre
        ouverte par l'utilisateur : elle se prepare comme avant)."""
        automatic = getattr(self, "_automatic_tasks", None)
        if automatic is not None and getattr(self, "_settings_idle_loading", False):
            import ui_state
            if not automatic.eligible('settings', ui_state.APPLIED_SETTINGS or {}):
                self._stop_settings_idle_load()
                return True
        if self._heavy_foreground_work():
            return True
        dialog = self._live_settings_dialog()
        visible = dialog is not None and dialog.isVisible()
        return not visible and not getattr(self, "_settings_idle_loading", False)

    def _on_settings_prebuild_progress(self, fraction: float):
        self.titlebar.set_load_progress(int(fraction * 100))
        if not getattr(self, "_settings_idle_loading", False):
            self.titlebar.set_load_progress(None)
            return
        if fraction >= 1.0:
            self._stop_settings_idle_load()                # tout est pret : la barre disparait
            return
        self.titlebar.set_load_progress(int(fraction * 100))

    def open_settings(self, mode: str = "visuel"):
        """Ouvre la fenetre de reglages (v2 ; l'ancienne fenetre v1 a ete retiree)."""
        self.open_settings_v2()

    def _apply_settings(self, settings: dict, changed_keys: set | None = None):
        """Applique des reglages (live, pendant qu'on les ajuste dans la
        fenetre de parametres, ou definitifs a l'enregistrement — les deux
        cas appellent cette meme methode). N'ecrit jamais sur le disque
        (voir SettingsWindow._on_save pour la persistance).

        Si la racine n'a pas change, les colonnes existantes sont juste
        rafraichies sur place (refresh_all_columns) : la navigation en cours
        (profondeur, selection) n'est PAS perdue. Un reload() complet n'a
        lieu que si la racine elle-meme a change, ce qui invalide de toute
        facon le chemin courant."""
        # Cliche AVANT/APRES (voir refresh_all_columns(relayout_titles=...))
        # de la hauteur/l'espacement de ligne EFFECTIFS (COLUMN_SETTINGS,
        # deja resolus general/surcharge par apply_all_settings) de CHAQUE
        # colonne : seules celles ou cette paire a reellement change auront
        # besoin d'un doItemsLayout() plus bas — un cran de slider qui ne
        # touche qu'une couleur/bordure/rayon/padding n'affecte le sizeHint()
        # d'AUCUNE ligne, quelle que soit la colonne — voir la remarque de
        # l'utilisateur, "il y a des ralentissements dans les animations,
        # optimise un maximum".
        self._sync_theme_watch(settings)
        if changed_keys and all(k.startswith("auto_") for k in changed_keys):
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS.update({k: settings.get(k) for k in changed_keys})
            automatic = getattr(self, "_automatic_tasks", None)
            if automatic is not None:
                automatic.tick()
            return
        if self._last_style_key is None:
            # Premier changement : la reference est l'etat DEJA applique (sans
            # elle, le tout premier cran de n'importe quel slider declenchait
            # une reconstruction globale de plus d'une seconde).
            self._last_style_key = self._style_key(load_settings())
        # Chemin RAPIDE (glisser une couleur / un rayon dans Bouton, Zone de saisie, Tabs : un apercu toutes les
        # ~30 ms) : si seules des cles de ces trois groupes ont change depuis ce qui est applique, rien d'autre ne
        # bouge (ni colonnes, ni couleurs de l'appli, ni tailles) — pas de rafraichissement de toutes les colonnes.
        previous = ui_state.APPLIED_SETTINGS or {}
        # `changed_keys` (apercu en direct de la v2) : les cles que le geste a vraiment changees.
        changed = set(changed_keys) if changed_keys else (
            {k for k, v in settings.items() if previous.get(k) != v} | (previous.keys() - settings.keys()))
        md_changed = {k for k in changed if k.startswith("md_")}
        if md_changed:
            # Feuille CSS partagee avec Obsidian : apercu aussitot, ecriture regroupee apres le geste (css_sync).
            import fm_markdown.css_sync as css_sync
            css_sync.engine().update(settings, md_changed)
        if changed and all(k.startswith("md_") for k in changed):
            # Onglet Markdown : seule la page du module (si elle existe) les reprend, sans rechargement ; l'apercu
            # des notes de l'inspecteur suit a la prochaine note affichee.
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS.update({k: settings.get(k) for k in changed})
            if changed.intersection({"md_toolbar_enabled", "md_toolbar_margin", "md_toolbar_border_enabled",
                                    "md_toolbar_border", "md_toolbar_border_thickness"}):
                self.titlebar.refresh_look()
            if "md_module_padding" in changed:
                self.md_margin_slider.blockSignals(True)
                self.md_margin_slider.setValue(int(settings.get("md_module_padding") or 0))
                self.md_margin_slider.blockSignals(False)
            import fm_markdown.pane as md_pane
            pane = md_pane.instance(create=False)
            if pane is not None:
                pane.apply_settings(ui_state.APPLIED_SETTINGS or settings, changed)
            timer = getattr(self, "_md_inspector_timer", None)
            if timer is None:                    # apercu de l'inspecteur : une fois, apres le geste
                timer = self._md_inspector_timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(350)
                timer.timeout.connect(self.detail.refresh_markdown_style)
            timer.start()
            return
        if changed and all(k.startswith("video_") for k in changed):
            # Reglages > Module video : seul le module ouvert est refait.
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS.update({k: settings.get(k) for k in changed})
            if getattr(self, "_video", None) is not None:
                self._video.apply_settings(ui_state.APPLIED_SETTINGS or settings)
            return
        if changed and all(k.startswith("board_") for k in changed):
            # Reglages > Module MRO (magnetisme du board) : rien d'autre a refaire que le board ouvert.
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS.update({k: settings.get(k) for k in changed})
            if getattr(self, "_board", None) is not None:
                self._board.apply_settings(ui_state.APPLIED_SETTINGS or settings)
            return
        if changed and all(k.startswith(_BRICK_PREFIXES) for k in changed):
            self._restyle_bricks(settings, changed)
            return
        if getattr(self, "_board", None) is not None:
            self._board.apply_settings(settings)
        if getattr(self, "_video", None) is not None:
            self._video.apply_settings(settings)
        if changed and all(k.startswith(("button_", "input_", "tabs_", "crumb_")) for k in changed):
            apply_all_settings(settings)
            style_key = self._style_key(settings)
            if style_key != self._last_style_key:
                self._last_style_key = style_key
                self._pending_stylesheet_rebuild = True
                self._stylesheet_rebuild_timer.start()
            self._refresh_button_shadows()
            if "input_height" in changed:
                self.refresh_chrome_sizes()               # champs de la barre de navigation
            if any(k.startswith("crumb_") for k in changed):
                self.titlebar.refresh_crumbs()            # cheminement : habillage et hauteur de la barre
            return
        prev_geometry = {title: (conf["height"], conf["spacing"]) for title, conf in COLUMN_SETTINGS.items()}
        prev_omissions = (GLOBAL_OMIT_DIR_NAMES.copy(), GLOBAL_OMIT_FILE_NAMES.copy(),
                          GLOBAL_OMIT_FILE_EXTENSIONS.copy())
        apply_all_settings(settings)
        picker = getattr(self, "preset_picker", None)
        if picker is not None:
            picker.restyle()                        # habillage des reglages (palette M) : suit
        omissions_changed = prev_omissions != (GLOBAL_OMIT_DIR_NAMES, GLOBAL_OMIT_FILE_NAMES,
                                                GLOBAL_OMIT_FILE_EXTENSIONS)
        changed_titles = {
            title for title, conf in COLUMN_SETTINGS.items()
            if (conf["height"], conf["spacing"]) != prev_geometry.get(title)
        }
        # column_gap() : apply_all_settings vient de le mettre a jour (voir
        # set_column_gap ci-dessus), mais c'est un global — encore besoin
        # de le repercuter ICI sur l'instance reelle de columns_layout,
        # comme refresh_all_columns le fait deja pour la largeur/hauteur
        # des colonnes.
        self.columns_layout.setSpacing(scaled(max(0, column_gap()), 0))
        if settings["root_path"] != self.root_field.text():
            self.root_field.setText(settings["root_path"])
            self.reload()
        else:
            self.refresh_all_columns(
                rescan=omissions_changed,
                relayout_titles=None if omissions_changed else changed_titles,
            )
        if omissions_changed:
            hidden_path = self.detail._current_path
            if hidden_path and _is_globally_omitted_path(Path(hidden_path)):
                self.detail.clear()
            idle_scheduler = getattr(self, "_idle_preview_scheduler", None)
            if idle_scheduler is not None:
                if idle_scheduler.scan_cancel_event is not None:
                    idle_scheduler.scan_cancel_event.set()
                idle_scheduler.queue.clear()
                idle_scheduler.done.clear()
                if (idle_scheduler.active_key is not None and idle_scheduler.cancel_event is not None):
                    if _is_globally_omitted_path(Path(idle_scheduler.active_key)):
                        idle_scheduler.cancel_event.set()
                idle_scheduler.last_scan = 0.0
        # app.setStyleSheet (dans refresh_colors -> refresh_style) repolit
        # TOUS les widgets de TOUTES les fenetres de l'appli — le poste le
        # plus cher, et de loin, de tout ce rafraichissement (mesure a
        # plus de 3 SECONDES par appel une fois la fenetre de parametres
        # ouverte, voir _flush_stylesheet_rebuild). Un slider qui ne
        # touche ni aux couleurs, ni au cadre/rayon des boutons, ni au
        # cadre/rayon des zones de saisie, ni au rayon des tableaux (largeur
        # de colonne, echelle, hauteur d'entete...) n'a aucune raison de le
        # declencher a chaque cran : seule une vraie difference sur ces
        # points (les seuls que build_stylesheet lit reellement) force la
        # reconstruction complete de la feuille de style — MAIS durant un
        # glisser de COULEUR, cette difference est reelle a CHAQUE tick, ce
        # gate seul ne suffit donc plus (voir la remarque de l'utilisateur,
        # "il y a toujours un tres gros problemes de performance") : la
        # reconstruction elle-meme est donc REGROUPEE (voir
        # _flush_stylesheet_rebuild), jamais appelee directement ici.
        style_key = self._style_key(settings)
        if style_key != self._last_style_key:
            self._last_style_key = style_key
            self._pending_stylesheet_rebuild = True
            # Relance a chaque changement (et non plus toutes les 250 ms) : la reconstruction coute ~430 ms
            # (toutes les fenetres repolies) ; faite PENDANT un glisser de couleur, elle le figeait (signale).
            self._stylesheet_rebuild_timer.start()
        self.refresh_colors(rebuild_stylesheet=False)
        self.refresh_chrome_sizes()
        self._apply_native_frame()
        self._apply_viewer_settings()
        import settings_element_style            # styles propres des elements : pas effaces par le restylage
        settings_element_style.reapply_soon(self, ui_state.APPLIED_SETTINGS)

    def _restyle_bricks(self, settings: dict, changed: set):
        """Chemin rapide de l'ASPECT DES BRIQUES (curseurs, titres, tableaux, toggles, menus contextuels, fenetres
        additionnelles : un pas de curseur dans fm_theme ou dans les reglages) : seuls les widgets de ces
        familles sont refaits, dans la fenetre principale et les fenetres ouvertes construites avec les briques ;
        ni colonnes, ni couleurs, ni tailles (budget : une image, docs/agents/fm_theme.md)."""
        import settings_window_v2 as v2
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS.update({k: settings.get(k) for k in changed})
        merged = ui_state.APPLIED_SETTINGS if isinstance(ui_state.APPLIED_SETTINGS, dict) else settings
        # Fenetres de reglages : elles se restylent elles-memes (leur apercu, ou leurs valeurs relues a la fin).
        roots = [self] + [w for w in QApplication.topLevelWidgets()
                          if w is not self and w.isVisible() and not isinstance(w, v2.SettingsWindowV2)]
        families = (("slider_", v2.restyle_sliders_in), ("title_level", v2.restyle_titles_in),
                    ("table_", v2.restyle_tables_in), ("toggle", v2.restyle_toggles_in))
        for prefix, restyle in families:
            if any(k.startswith(prefix) for k in changed):
                for root in roots:
                    restyle(root, merged)
        if any(k.startswith("extra_window_") for k in changed):
            v2.seed_extra_window_look(merged)        # fenetres additionnelles ouvertes : reprises aussitot
        if any(k.startswith("table_") for k in changed):
            style_key = self._style_key(merged)      # rayon des tableaux : lu aussi par la feuille de style
            if style_key != self._last_style_key:
                self._last_style_key = style_key
                self._pending_stylesheet_rebuild = True
                self._stylesheet_rebuild_timer.start()
        # Menus contextuels (ctx_) : relus a chaque ouverture, rien a refaire.

    @staticmethod
    def _style_key(settings: dict) -> tuple:
        """Ce que build_stylesheet lit reellement : si elle ne bouge pas, la
        feuille de style globale n'a pas a etre reconstruite."""
        colors = settings.get("colors") or {}
        return (
            tuple(colors.get(k, C[k]) for k in STYLESHEET_COLOR_KEYS),
            settings.get("button_radius"),
            settings.get("button_frame"),
            settings.get("input_radius"),
            settings.get("input_frame"),
            settings.get("table_radius"),
            json.dumps({k: v for k, v in settings.items()
                        if k.startswith(("button_", "input_"))}, sort_keys=True, default=str),
        )

    def _flush_stylesheet_rebuild(self):
        """Reconstruction DIFFEREE et REGROUPEE de la feuille de style
        globale (voir _apply_settings/app_style.refresh_style) — le SEUL
        appel a ce chemin couteux (mesure a plus de 3 SECONDES une fois la
        fenetre de parametres ouverte, des milliers de widgets ayant
        chacun leur propre QSS local a re-cascader contre le nouveau QSS
        d'appli). `_stylesheet_rebuild_timer` (250ms, singleShot, voir
        __init__) le declenche au plus tot 250ms apres le DERNIER
        changement de style_key — pendant un glisser continu de couleur,
        cela ramene un cout de plusieurs secondes PAR TICK (~30ms) a un
        seul appel toutes les ~250ms, invisible a l'oeil (le style
        GENERIQUE — boutons/scrollbars/menus — n'est de toute facon pas ce
        qu'on regarde en glissant une pastille de couleur ; tout le reste
        du retour visuel en direct passe par refresh_colors(rebuild_
        stylesheet=False), deja rejoue a chaque tick, DEJA rapide)."""
        if not self._pending_stylesheet_rebuild:
            return
        if QApplication.mouseButtons() != Qt.NoButton:
            # Geste en cours (curseur de couleur tenu) : on attend qu'il soit relache.
            self._stylesheet_rebuild_timer.start()
            return
        self._pending_stylesheet_rebuild = False
        self._apply_global_stylesheet()

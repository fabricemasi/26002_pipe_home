"""Branchement de l'agenda (fm_agenda) : bouton « Agenda » de la barre de navigation (toujours actif : l'agenda
ne dépend d'aucun fichier choisi), ouverture plein cadre (colonnes masquées), cadre « Agenda » de la barre
(annuler, rétablir, panneau latéral, réglages, fermer), autre module qui le ferme (`_leave_agenda`), service de
l'agenda démarré en fond peu après le lancement (rappels et synchronisation même agenda fermé), fermeture propre.

Le panneau est GARDÉ (caché) après fermeture : le rouvrir est immédiat. Carte du module : docs/agents/fm_agenda.md ;
de la fenêtre : docs/agents/fm_browser.md."""
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer

import ui_state
from app_style import C, role_color, scaled
from settings_store import load_settings

log = logging.getLogger("fm_agenda.window")


def _warm_agenda_imports():
    """Fil de fond : modules de l'agenda importés (et compilés au premier lancement) hors du fil de l'interface."""
    try:
        import dateutil.rrule  # noqa: F401
        import fm_agenda.services.agenda  # noqa: F401
        import fm_agenda.services.reminders  # noqa: F401
        import fm_agenda.sync.manager  # noqa: F401
        import fm_agenda.ui.pane  # noqa: F401
        import fm_agenda.ui.editor  # noqa: F401
        from fm_agenda.core import timeutil
        timeutil.get_tz(None)
        timeutil.get_tz("Europe/Paris")
    except Exception:                                     # noqa: BLE001 - l'import se refera dans le fil Qt
        log.exception("pré-import de l'agenda")


class AgendaModuleMixin:
    """Méthodes de PipelineBrowser : agenda (fm_agenda) recouvrant les colonnes."""

    # -- service (rappels et synchronisation, agenda ouvert ou non) --

    def _agenda_settings(self) -> dict:
        return ui_state.APPLIED_SETTINGS or load_settings()

    def _agenda_service_ready(self):
        """Service de l'agenda (base SQLite locale), créé à la première demande."""
        service = getattr(self, "_agenda_service", None)
        if service is not None:
            return service
        try:
            from fm_agenda.services.agenda import AgendaService
            service = AgendaService(dict(self._agenda_settings()), parent=self)
        except Exception as exc:                          # noqa: BLE001 - l'appli reste utilisable sans agenda
            log.exception("ouverture de l'agenda")
            self.path_label.setText(f"Agenda indisponible : {exc}")
            return None
        self._agenda_service = service
        from fm_agenda import runtime
        runtime.set_service(service, self._agenda_service_ready)
        service.message.connect(lambda level, text: self.path_label.setText(("⚠ " if level == "erreur" else "")
                                                                            + text))
        for text in service.open_report.messages:
            self.path_label.setText(text)
        self._start_agenda_reminders(service)
        self._start_agenda_sync(service)
        return service

    def _start_agenda_background(self):
        """Lancé peu après l'ouverture de la fenêtre. Fluidité : les modules de l'agenda sont importés dans un fil
        de fond (aucune compilation ni import dans le fil de l'interface), puis, une étape par seconde d'INACTIVITÉ de
        l'appli, le service (rappels, synchronisation), le panneau caché et l'éditeur sont préparés : le premier clic
        sur « Agenda » est aussi immédiat que les suivants."""
        import threading
        from fm_agenda import runtime
        runtime.set_service(getattr(self, "_agenda_service", None), self._agenda_service_ready)
        settings = self._agenda_settings()
        steps = ["pane", "editor"]
        if settings.get("agenda_reminders_enabled", True) or settings.get("agenda_sync_auto", True):
            steps.insert(0, "service")
        self._agenda_steps = steps
        self._agenda_warm = threading.Thread(target=_warm_agenda_imports, name="fm_agenda-imports", daemon=True)
        self._agenda_warm.start()
        timer = self._agenda_idle_timer = QTimer(self)
        timer.setInterval(700)
        timer.timeout.connect(self._agenda_idle_step)
        timer.start()

    def _agenda_idle_step(self):
        warm = getattr(self, "_agenda_warm", None)
        steps = getattr(self, "_agenda_steps", [])
        if warm is not None and warm.is_alive():
            return
        if not steps:
            self._agenda_idle_timer.stop()
            return
        busy = getattr(self, "_app_used_recently", None)
        if callable(busy) and busy():
            return                                        # l'utilisateur agit : rien dans le fil de l'interface
        step = steps.pop(0)
        try:
            if step == "service":
                self._agenda_service_ready()
            elif step == "pane" and getattr(self, "_agenda", None) is None and \
                    getattr(self, "_agenda_service", None) is not None:
                self._build_agenda_pane()
            elif step == "editor" and getattr(self, "_agenda", None) is not None:
                self._agenda.prebuild_editor()
        except Exception:                                 # noqa: BLE001 - une préparation ratée se refera au clic
            log.exception("préparation de l'agenda (%s)", step)

    def _start_agenda_reminders(self, service):
        try:
            from fm_agenda.services.reminders import ReminderScheduler
        except ImportError:
            return
        scheduler = ReminderScheduler(service, self)
        scheduler.openRequested.connect(self._open_agenda_on)
        scheduler.start()
        self._agenda_reminders = scheduler

    def _start_agenda_sync(self, service):
        try:
            from fm_agenda.sync.manager import SyncManager
        except ImportError:
            return
        try:
            manager = SyncManager(service, self)
            service.sync = manager
            manager.start()
        except Exception:                                 # noqa: BLE001
            log.exception("synchronisation de l'agenda")

    # -- panneau --

    def _install_agenda_hooks(self):
        import fm_agenda.ui.pane as agenda_pane
        agenda_pane.HOOKS.update({
            "settings": self._agenda_settings,
            "status": self.path_label.setText,
            "open_settings": lambda: self.open_module_settings("agenda"),
            "open_folder": self._agenda_open_folder,
            "project_folder": self._agenda_project_folder,
            "save_setting": self._agenda_save_setting,
            "navbar_frame": True,
        })

    def _agenda_save_setting(self, key, value):
        from settings_store import save_live_state
        save_live_state(key, value)
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value

    def _agenda_project_folder(self, project: str) -> str:
        """« 26014 Teaser » -> <racine>\\26014_Teaser s'il existe (ligne « Dossier » des détails, comme le design)."""
        try:
            root = Path(self.root_field.text())
            for name in (project, project.replace(" ", "_")):
                candidate = root / name
                if candidate.is_dir():
                    return str(candidate)
        except (OSError, ValueError):
            pass
        return ""

    def _agenda_open_folder(self, path: str):
        """« Ouvrir le dossier » : l'agenda se ferme, les colonnes vont au dossier (sinon l'Explorateur)."""
        target = Path(path)
        root = Path(self.root_field.text())
        try:
            target.relative_to(root)
            inside = target.exists()
        except ValueError:
            inside = False
        if inside:
            self._close_agenda()
            self._navigate_to(target)
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _toggle_agenda(self):
        pane = getattr(self, "_agenda", None)
        if pane is not None and pane.isVisible():
            self._close_agenda()
            return
        self._open_agenda()

    def _open_agenda_on(self, day=None, key=None):
        """Rappel cliqué : l'agenda s'ouvre sur le jour de l'événement."""
        if self._open_agenda() and day is not None:
            from fm_agenda.core.model import Occurrence  # noqa: F401
            self._agenda._goto(day, "jour", key)

    def _open_agenda(self) -> bool:
        """L'agenda recouvre les colonnes (modes exclusifs : éditeur, board, vidéo, typographie, PDF, visionneuse)."""
        if self._project_columns_hidden:
            self._set_columns_hidden(False, animate=False)
        if not self._close_md_editor():
            return False
        if self._board is not None and not self._close_board():
            return False
        if not self._leave_font():
            return False
        leave_pdf = getattr(self, "_leave_pdf", None)
        if leave_pdf is not None and not leave_pdf():
            return False
        self._close_video()
        service = self._agenda_service_ready()
        if service is None:
            return False
        pane = getattr(self, "_agenda", None)
        if pane is None:
            pane = self._build_agenda_pane()
            QTimer.singleShot(400, pane, pane.prebuild_editor)  # première édition sans attente
        else:
            self._install_agenda_hooks()
            pane.apply_settings(self._agenda_settings())
            pane.setGeometry(self.scroll.viewport().rect())
            pane.refresh()
        pane.show()
        pane.raise_()
        pane.focus_view()
        self._show_agenda_width_slider(True)
        host = self.scroll.widget()
        if host is not None and host.isVisible():
            host.hide()
            self._agenda_hid_columns = True
        self._layout_agenda_buttons()
        self._sync_collapse_button()
        self._sync_mode_buttons()
        return True

    def _build_agenda_pane(self):
        """Panneau construit caché (au premier clic, ou à l'avance pendant l'inactivité)."""
        from fm_agenda.ui.pane import AgendaPane
        self._install_agenda_hooks()
        pane = AgendaPane(self._agenda_service, self.scroll.viewport())
        pane.hide()
        pane.closeRequested.connect(self._close_agenda)
        pane.stateChanged.connect(self._layout_agenda_buttons)
        self._agenda = pane
        return pane

    def _leave_agenda(self) -> bool:
        """Un autre mode s'ouvre : l'agenda se range (tout est déjà enregistré)."""
        pane = getattr(self, "_agenda", None)
        if pane is not None and pane.isVisible():
            self._close_agenda()
        return True

    def _close_agenda(self):
        pane = getattr(self, "_agenda", None)
        if pane is None:
            return
        pane.hide()
        self._show_agenda_width_slider(False)
        self.titlebar.agenda_group().hide()
        if getattr(self, "_agenda_hid_columns", False):
            self._agenda_hid_columns = False
            host = self.scroll.widget()
            if host is not None and not getattr(self, "_columns_user_hidden", False):
                host.show()
        self._sync_collapse_button()
        self._sync_mode_buttons()
        column, _path = self._selected_path()
        if column is not None:
            column.list.setFocus()

    # -- curseur « Largeur de l'agenda » de la barre d'état (comme celui des marges du module Markdown) --

    def _agenda_width_value(self) -> int:
        try:
            return max(30, min(100, int(self._agenda_settings().get("agenda_width", 100) or 100)))
        except (TypeError, ValueError):
            return 100

    def _show_agenda_width_slider(self, shown: bool):
        """Montré seulement agenda ouvert, à la place du texte de droite ; créé à la première ouverture."""
        slider = getattr(self, "agenda_width_slider", None)
        if slider is None:
            if not shown:
                return
            from PySide6.QtWidgets import QSlider
            slider = self.agenda_width_slider = QSlider(Qt.Horizontal)
            slider.setRange(30, 100)
            slider.setFixedWidth(scaled(140))
            slider.hide()
            slider.valueChanged.connect(self._set_agenda_width)
            self.statusbar.layout().addWidget(slider)
            timer = self._agenda_width_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(300)
            timer.timeout.connect(self._persist_agenda_width)
        if shown:
            self._sync_agenda_width_slider()
            self.status_right.hide()
            slider.show()
        elif slider.isVisible():
            slider.hide()
            self.status_right.show()

    def _sync_agenda_width_slider(self, _settings=None):
        """Valeur posée sans rien déclencher (ouverture, Réglages : Agenda > Affichage modifié)."""
        slider = getattr(self, "agenda_width_slider", None)
        if slider is None:
            return
        value = self._agenda_width_value()
        if slider.value() != value:
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
        slider.setToolTip(f"Largeur de l'agenda : {value} %")

    def _set_agenda_width(self, value: int):
        """Curseur glissé : seules les marges de l'agenda changent ; l'enregistrement attend la fin du geste."""
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS["agenda_width"] = value
        pane = getattr(self, "_agenda", None)
        if pane is not None:
            pane.set_width_percent(value)
        self.agenda_width_slider.setToolTip(f"Largeur de l'agenda : {value} %")
        self._agenda_width_timer.start()

    def _persist_agenda_width(self):
        value = self.agenda_width_slider.value()
        from settings_store import save_live_state
        save_live_state("agenda_width", value)
        import browser_core
        browser_core._sync_default_preset_override(ui_state.APPLIED_SETTINGS or {},
                                                   lambda preset: preset.update(agenda_width=value))
        for dialog in (getattr(self, "_settings_dialog_v2", None),
                       (getattr(self, "_module_settings", None) or {}).get("agenda")):
            try:
                if dialog is not None and dialog.isVisible():
                    dialog.external_values({"agenda_width": value})
            except RuntimeError:
                pass

    def _agenda_open(self) -> bool:
        pane = getattr(self, "_agenda", None)
        return pane is not None and pane.isVisible()

    def _shutdown_agenda(self):
        """Fermeture de l'appli : écritures en attente terminées, base fermée proprement (témoin d'incident ôté)."""
        timer = getattr(self, "_agenda_idle_timer", None)
        if timer is not None:
            timer.stop()
        pane = getattr(self, "_agenda", None)
        if pane is not None:
            pane.shutdown()
        scheduler = getattr(self, "_agenda_reminders", None)
        if scheduler is not None:
            scheduler.stop()
        service = getattr(self, "_agenda_service", None)
        if service is not None:
            try:
                service.close()
            except Exception:                             # noqa: BLE001
                log.exception("fermeture de l'agenda")

    def _layout_agenda_buttons(self):
        """Cadre « Agenda » de la barre : annuler, rétablir, panneau latéral, réglages, fermer."""
        from preview_column import IconButton, style_focus_button
        pane = getattr(self, "_agenda", None)
        group = self.titlebar.agenda_group()
        if pane is None or not pane.isVisible():
            group.hide()
            return
        buttons = self.__dict__.setdefault("_agenda_buttons", [])
        if not buttons:
            for kind, tip, slot in (
                    ("undo", "Annuler (Ctrl+Z)", lambda: self._agenda and self._agenda.undo()),
                    ("redo", "Rétablir (Ctrl+Y)", lambda: self._agenda and self._agenda.redo()),
                    ("fade_columns", "Panneau latéral (Ctrl+B)", lambda: self._agenda and self._agenda.toggle_sidebar()),
                    ("gear", "Réglages de l'agenda", lambda: self.open_module_settings("agenda")),
                    ("close", "Fermer l'agenda", self._close_agenda)):
                button = IconButton(kind, role_color("buttons", "#c4cacf"), C["text"], parent=group)
                button.setCursor(Qt.ArrowCursor)
                button.setFlat(True)
                button.setToolTip(tip)
                button.clicked.connect(slot)
                button._agenda_kind = kind
                buttons.append(button)
        service = pane.service
        origin = group.content_origin()
        x, height = origin.x(), 0
        for button in buttons:
            style_focus_button(button)
            kind = button._agenda_kind
            if kind == "undo":
                self._set_button_usable(button, service.can_undo())
                button.setToolTip("Annuler : %s (Ctrl+Z)" % service.undo_label() if service.can_undo() else "Annuler")
            elif kind == "redo":
                self._set_button_usable(button, service.can_redo())
                button.setToolTip("Rétablir : %s (Ctrl+Y)" % service.redo_label() if service.can_redo()
                                  else "Rétablir")
            button.move(x, origin.y())
            button.show()
            x += button.width() + scaled(6, 0)
            height = max(height, button.height())
        group.restyle()
        group.fit(x - scaled(6, 0), height)
        group.show()
        group.raise_()
        self.titlebar.place_viewer_group()

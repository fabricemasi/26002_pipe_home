"""Branchement du module Tâches (fm_taches) : bouton « Tâches » de la barre de navigation (toujours actif : les
tâches ne dépendent d'aucun fichier choisi), ouverture plein cadre (colonnes masquées), cadre « Tâches » de la barre
(annuler, rétablir, panneau latéral, détails, réglages, fermer), autre module qui le ferme (`_leave_taches`),
service ouvert en fond pendant l'inactivité (le premier clic est immédiat), fermeture propre.

Le panneau est GARDÉ (caché) après fermeture : le rouvrir est immédiat. Même schéma que `agenda_module.py`.
Carte du module : docs/agents/fm_taches.md ; de la fenêtre : docs/agents/fm_browser.md."""
import logging

from PySide6.QtCore import Qt, QTimer

import ui_state
from app_style import C, role_color, scaled
from settings_store import load_settings

log = logging.getLogger("fm_taches.window")


def _warm_taches_imports():
    """Fil de fond : modules des tâches importés (et compilés au premier lancement) hors du fil de l'interface."""
    try:
        import fm_taches.services.tasks  # noqa: F401
        import fm_taches.ui.pane  # noqa: F401
    except Exception:                                     # noqa: BLE001 - l'import se refera dans le fil Qt
        log.exception("pré-import des tâches")


class TasksModuleMixin:
    """Méthodes de PipelineBrowser : module Tâches (fm_taches) recouvrant les colonnes."""

    # -- service --

    def _taches_settings(self) -> dict:
        return ui_state.APPLIED_SETTINGS or load_settings()

    def _taches_service_ready(self):
        """Service des tâches (base SQLite locale), créé à la première demande."""
        service = getattr(self, "_taches_service", None)
        if service is not None:
            return service
        try:
            from fm_taches.services.tasks import TaskService
            service = TaskService(dict(self._taches_settings()), parent=self)
        except Exception as exc:                          # noqa: BLE001 - l'appli reste utilisable sans tâches
            log.exception("ouverture des tâches")
            self.path_label.setText(f"Tâches indisponibles : {exc}")
            return None
        self._taches_service = service
        from fm_taches import runtime
        runtime.set_service(service, self._taches_service_ready)
        service.message.connect(lambda level, text: self.path_label.setText(("⚠ " if level == "erreur" else "")
                                                                            + text))
        for text in service.open_report.messages:
            self.path_label.setText(text)
        service.changed.connect(self._taches_changed_for_agenda)
        service.listsChanged.connect(self._taches_changed_for_agenda)
        self._start_taches_sync(service)
        self._start_taches_reminders(service)
        self._taches_changed_for_agenda()                 # agenda déjà ouvert : les tâches y arrivent
        return service

    # -- tâches datées dans l'agenda (HOOKS `tasks_due`, `toggle_task`, `open_task` de fm_agenda/ui/pane.py) --

    def _taches_due_for_agenda(self, start, end) -> list:
        """Tâches dont l'échéance tombe dans [start, end[ (index par date du service : ~0,1 ms la semaine). Le
        service n'est jamais démarré pour l'agenda : il l'est en fond peu après le lancement."""
        service = getattr(self, "_taches_service", None)
        if service is None:
            return []
        lists = {lst.id: lst for lst in service.lists()}
        out = []
        for t in service.due_between(start, end):
            lst = lists.get(t.list_id)
            out.append({"id": t.id, "title": t.title or "Sans titre", "date": t.due, "time": t.due_time,
                        "done": t.done, "color": lst.color if lst else "gris", "list": lst.name if lst else "",
                        "notes": bool(t.notes)})
        return out

    def _taches_toggle_from_agenda(self, task_id: str):
        service = getattr(self, "_taches_service", None)
        task = service.get(task_id) if service is not None else None
        if task is not None:
            service.set_done(task_id, not task.done)

    def _taches_open_from_agenda(self, task_id: str):
        """Double-clic (ou « Ouvrir dans Tâches ») sur une tâche de l'agenda : le module Tâches s'ouvre dessus."""
        if self._open_taches():
            self._taches.reveal(task_id)

    def _taches_changed_for_agenda(self, *_args):
        pane = getattr(self, "_agenda", None)
        if pane is not None and pane.isVisible():
            pane._schedule()                              # une fois par tour de boucle, quoi qu'il arrive

    def _start_taches_reminders(self, service):
        """Rappels des tâches (fm_taches/services/reminders.py), module ouvert ou non."""
        try:
            from fm_taches.services.reminders import TaskReminders
            reminders = TaskReminders(service, self)
            reminders.openRequested.connect(self._taches_open_from_agenda)
            reminders.start()
            self._taches_reminders = reminders
        except Exception:                                 # noqa: BLE001 - les tâches restent utilisables sans
            log.exception("rappels des tâches")

    def _start_taches_sync(self, service):
        """Synchronisation Google Tasks (fm_taches/sync/manager.py) : rien ne part tant qu'aucun compte n'est
        connecté ; réseau et OAuth importés au premier passage."""
        try:
            from fm_taches.sync.manager import TasksSyncManager
            manager = TasksSyncManager(service, self)
            service.sync = manager
            manager.start()
        except Exception:                                 # noqa: BLE001 - les tâches restent utilisables en local
            log.exception("synchronisation des tâches")

    def _start_taches_background(self):
        """Peu après l'ouverture de la fenêtre : imports dans un fil de fond, puis service et panneau caché
        préparés une étape par tick d'INACTIVITÉ (jamais pendant que l'utilisateur agit)."""
        import threading
        from fm_taches import runtime
        runtime.set_service(getattr(self, "_taches_service", None), self._taches_service_ready)
        self._taches_steps = ["service", "pane"]
        self._taches_warm = threading.Thread(target=_warm_taches_imports, name="fm_taches-imports", daemon=True)
        self._taches_warm.start()
        timer = self._taches_idle_timer = QTimer(self)
        timer.setInterval(900)
        timer.timeout.connect(self._taches_idle_step)
        timer.start()

    def _taches_idle_step(self):
        warm = getattr(self, "_taches_warm", None)
        steps = getattr(self, "_taches_steps", [])
        if warm is not None and warm.is_alive():
            return
        if not steps:
            self._taches_idle_timer.stop()
            return
        busy = getattr(self, "_app_used_recently", None)
        if callable(busy) and busy():
            return
        step = steps.pop(0)
        try:
            if step == "service":
                self._taches_service_ready()
            elif step == "pane" and getattr(self, "_taches", None) is None and \
                    getattr(self, "_taches_service", None) is not None:
                self._build_taches_pane()
        except Exception:                                 # noqa: BLE001 - une préparation ratée se refera au clic
            log.exception("préparation des tâches (%s)", step)

    # -- panneau --

    def _install_taches_hooks(self):
        import fm_taches.ui.pane as taches_pane
        taches_pane.HOOKS.update({
            "settings": self._taches_settings,
            "status": self.path_label.setText,
            "open_settings": lambda: self.open_module_settings("taches"),
            "save_setting": self._taches_save_setting,
            "navbar_frame": True,
        })

    def _taches_save_setting(self, key, value):
        from settings_store import save_live_state
        save_live_state(key, value)
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value

    def _toggle_taches(self):
        pane = getattr(self, "_taches", None)
        if pane is not None and pane.isVisible():
            self._close_taches()
            return
        self._open_taches()

    def _open_taches(self) -> bool:
        """Les tâches recouvrent les colonnes (modes exclusifs : éditeur, board, vidéo, typographie, PDF, agenda)."""
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
        leave_agenda = getattr(self, "_leave_agenda", None)
        if leave_agenda is not None:
            leave_agenda()
        service = self._taches_service_ready()
        if service is None:
            return False
        pane = getattr(self, "_taches", None)
        if pane is None:
            pane = self._build_taches_pane()
        else:
            self._install_taches_hooks()
            pane.apply_settings(self._taches_settings())
            pane.setGeometry(self.scroll.viewport().rect())
            pane.refresh()
        pane.show()
        pane.raise_()
        pane.focus_view()
        host = self.scroll.widget()
        if host is not None and host.isVisible():
            host.hide()
            self._taches_hid_columns = True
        self._layout_taches_buttons()
        self._sync_collapse_button()
        self._sync_mode_buttons()
        return True

    def _build_taches_pane(self):
        """Panneau construit caché (au premier clic, ou à l'avance pendant l'inactivité)."""
        from fm_taches.ui.pane import TasksPane
        self._install_taches_hooks()
        pane = TasksPane(self._taches_service, self.scroll.viewport())
        pane.hide()
        pane.closeRequested.connect(self._close_taches)
        pane.stateChanged.connect(self._layout_taches_buttons)
        self._taches = pane
        return pane

    def _leave_taches(self) -> bool:
        """Un autre mode s'ouvre : les tâches se rangent (tout est déjà enregistré)."""
        pane = getattr(self, "_taches", None)
        if pane is not None and pane.isVisible():
            self._close_taches()
        return True

    def _close_taches(self):
        pane = getattr(self, "_taches", None)
        if pane is None:
            return
        pane.list.cancel_edit()
        pane.hide()
        self.titlebar.taches_group().hide()
        if getattr(self, "_taches_hid_columns", False):
            self._taches_hid_columns = False
            host = self.scroll.widget()
            if host is not None and not getattr(self, "_columns_user_hidden", False):
                host.show()
        self._sync_collapse_button()
        self._sync_mode_buttons()
        column, _path = self._selected_path()
        if column is not None:
            column.list.setFocus()

    def _taches_open(self) -> bool:
        pane = getattr(self, "_taches", None)
        return pane is not None and pane.isVisible()

    def _shutdown_taches(self):
        """Fermeture de l'appli : écritures en attente terminées, base fermée proprement (témoin d'incident ôté)."""
        timer = getattr(self, "_taches_idle_timer", None)
        if timer is not None:
            timer.stop()
        pane = getattr(self, "_taches", None)
        if pane is not None:
            pane.shutdown()
        reminders = getattr(self, "_taches_reminders", None)
        if reminders is not None:
            reminders.stop()
        service = getattr(self, "_taches_service", None)
        if service is not None:
            try:
                service.close()
            except Exception:                             # noqa: BLE001
                log.exception("fermeture des tâches")

    def _layout_taches_buttons(self):
        """Cadre « Tâches » de la barre : annuler, rétablir, panneau latéral, détails, réglages, fermer."""
        from preview_column import IconButton
        pane = getattr(self, "_taches", None)
        group = self.titlebar.taches_group()
        if pane is None or not pane.isVisible():
            group.hide()
            return
        buttons = self.__dict__.setdefault("_taches_buttons", [])
        if not buttons:
            for kind, tip, slot in (
                    ("undo", "Annuler (Ctrl+Z)", lambda: self._taches and self._taches.undo()),
                    ("redo", "Rétablir (Ctrl+Y)", lambda: self._taches and self._taches.redo()),
                    ("fade_columns", "Panneau latéral (Ctrl+B)", lambda: self._taches and self._taches.toggle_sidebar()),
                    ("info", "Détails (Ctrl+I)", lambda: self._taches and self._taches.toggle_details()),
                    ("gear", "Réglages des tâches", lambda: self.open_module_settings("taches")),
                    ("close", "Fermer les tâches", self._close_taches)):
                button = IconButton(kind, role_color("buttons", "#c4cacf"), C["text"], parent=group)
                button.setCursor(Qt.ArrowCursor)
                button.setFlat(True)
                button.setToolTip(tip)
                button.clicked.connect(slot)
                button._taches_kind = kind
                buttons.append(button)
        service = pane.service
        origin = group.content_origin()
        x, height = origin.x(), 0
        for button in buttons:
            self.titlebar.style_group_button(button)
            kind = button._taches_kind
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

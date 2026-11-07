"""Champs d'ACTIONS de « Réglages : Agenda » (briques des réglages) : compte Google (identifiant OAuth de
l'application, connexion par le navigateur, calendriers synchronisés, synchronisation manuelle, état, conflits,
déconnexion) et données locales (emplacement, sauvegarde, import / export .ics). Ils n'enregistrent aucune valeur :
ils agissent sur le service de l'agenda en cours (`runtime`)."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from .. import runtime
from . import kit


class _Panel(QWidget):
    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 4, 0, 4)
        self.lay.setSpacing(6)

    def row(self, *widgets) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        for w in widgets:
            row.addWidget(w)
        row.addStretch(1)
        self.lay.addLayout(row)
        return row


class GoogleAccountsField(_Panel):
    def __init__(self):
        super().__init__()
        self.status = kit.label("", "value")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status.setMinimumWidth(340)
        self.status.setMaximumWidth(400)
        self.lay.addWidget(self.status)
        self.b_client = kit.button("Importer l'identifiant OAuth…", self._import_client,
                                   tip="Fichier « client_secret_….json » téléchargé de la console Google Cloud "
                                       "(étapes : docs/agents/fm_agenda.md, « Connecter Google Agenda »)")
        self.b_connect = kit.button("Connecter Google Agenda…", self._connect, accent=True)
        self.b_cancel = kit.button("Annuler la connexion", self._cancel)
        self.row(self.b_client, self.b_connect, self.b_cancel)
        self.b_sync = kit.button("Synchroniser", self._sync)
        self.b_conflicts = kit.button("Conflits…", self._conflicts)
        self.b_disconnect = kit.button("Déconnecter…", self._disconnect)
        self.row(self.b_sync, self.b_conflicts, self.b_disconnect)
        self.cal_box = QVBoxLayout()
        self.cal_box.setSpacing(2)
        self.lay.addLayout(self.cal_box)
        self.help = kit.label("La connexion s'ouvre dans votre navigateur : PIPE FMZ ne voit jamais votre mot de "
                              "passe Google ; le jeton est rangé dans le Gestionnaire d'identifiants Windows.",
                              "inline_label")
        self.help.setWordWrap(True)
        self.help.setMaximumWidth(400)
        self.lay.addWidget(self.help)
        self._toggles = {}
        manager = runtime.manager()
        if manager is not None:
            manager.changed.connect(self.refresh)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(5000)
        self.refresh()

    def refresh(self) -> None:
        manager = runtime.manager()
        service = runtime.service()
        if manager is None or service is None:
            self.status.setText("Agenda non démarré (ouvrir l'agenda une fois).")
            for b in (self.b_connect, self.b_sync, self.b_conflicts, self.b_disconnect, self.b_cancel):
                b.setEnabled(False)
            return
        accounts = manager.accounts()
        has_client = manager.has_client()
        self.status.setText(manager.status_text() + ("" if has_client else
                                                     "\nIdentifiant OAuth de l'application : à importer."))
        connecting = manager.running and "Connexion" in manager.state.get("message", "")
        self.b_client.setText("Remplacer l'identifiant OAuth…" if has_client else "Importer l'identifiant OAuth…")
        self.b_connect.setVisible(has_client and not connecting)
        self.b_connect.setText("Ajouter un compte Google…" if accounts else "Connecter Google Agenda…")
        self.b_cancel.setVisible(connecting)
        n = len(manager.conflicts())
        self.b_conflicts.setText(f"Conflits ({n})…")
        for b, on in ((self.b_sync, bool(accounts) and not manager.running), (self.b_conflicts, n > 0),
                      (self.b_disconnect, bool(accounts))):
            b.setVisible(bool(accounts))
            b.setEnabled(on)
        cals = [c for c in service.calendars() if c.source == "google"]
        ids = [c.id for c in cals]
        if ids != list(self._toggles):
            while self.cal_box.count():
                item = self.cal_box.takeAt(0)
                lay = item.layout()
                if lay is not None:
                    while lay.count():
                        w = lay.takeAt(0).widget()
                        if w is not None:
                            w.deleteLater()
            self._toggles = {}
            for cal in cals:
                t = kit.toggle(cal.sync_enabled, lambda on, cid=cal.id: manager.set_calendar_sync(cid, on))
                role = {"owner": "propriétaire", "writer": "modification", "reader": "lecture seule",
                        "freeBusyReader": "disponibilités"}.get(cal.access_role, cal.access_role)
                row = QHBoxLayout()
                row.setSpacing(8)
                row.addWidget(t)
                row.addWidget(kit.label(f"{cal.name}  ·  {role}", "row_label"))
                row.addStretch(1)
                self.cal_box.addLayout(row)
                self._toggles[cal.id] = t
        else:
            for cal in cals:
                t = self._toggles[cal.id]
                if t.isChecked() != cal.sync_enabled:
                    t.blockSignals(True)
                    t.setChecked(cal.sync_enabled)
                    t.blockSignals(False)

    def _import_client(self) -> None:
        path, _f = QFileDialog.getOpenFileName(self, "Identifiant OAuth de l'application", "", "JSON (*.json)")
        if not path:
            return
        try:
            runtime.manager().import_client(path)
        except Exception as exc:                         # noqa: BLE001
            kit.confirm(self, "Identifiant OAuth", f"Fichier refusé : {exc}", "OK")
        self.refresh()

    def _connect(self) -> None:
        manager = runtime.manager()
        try:
            manager.connect_google(lambda url: QDesktopServices.openUrl(QUrl(url)), on_done=lambda _r: self.refresh())
        except Exception as exc:                         # noqa: BLE001
            kit.confirm(self, "Google Agenda", str(exc), "OK")
        self.refresh()

    def _cancel(self) -> None:
        runtime.manager().cancel_connect()

    def _sync(self) -> None:
        runtime.manager().sync_now(on_done=lambda _r: self.refresh())
        self.refresh()

    def _conflicts(self) -> None:
        from .dialogs import ConflictsDialog
        dialog = ConflictsDialog(self, runtime.manager())
        dialog.exec()
        dialog.deleteLater()
        self.refresh()

    def _disconnect(self) -> None:
        manager = runtime.manager()
        accounts = manager.accounts()
        if not accounts:
            return
        choices = [(a["id"], a["email"] or "Compte Google") for a in accounts]
        account_id = choices[0][0] if len(choices) == 1 else kit.choose(self, "Déconnecter", "Quel compte ?",
                                                                         choices)
        if not account_id:
            return
        pending = runtime.service().repo.outbox_count()
        keep = kit.choose(self, "Déconnecter Google Agenda",
                          "Le jeton est révoqué chez Google et effacé de Windows."
                          + (f" {pending} modification(s) non envoyée(s) seront perdues pour Google." if pending else "")
                          + " Que faire des copies locales de ses calendriers ?",
                          [("delete", "Les supprimer de PIPE FMZ"), ("keep", "Les garder en calendriers locaux")])
        if keep is None:
            return
        manager.disconnect(account_id, delete_local=keep == "delete", on_done=lambda _r: self.refresh())


SHORTCUTS = (("← / →, Page préc. / suiv.", "Période précédente / suivante"), ("T", "Aujourd'hui"),
             ("1 à 6 (ou Ctrl + 1 à 6)", "Jour, Semaine, Travail, Mois, Année, Liste"),
             ("N ou Ctrl+N", "Nouvel événement"), ("Entrée", "Modifier l'événement choisi"),
             ("Suppr", "Supprimer l'événement choisi"), ("Ctrl+D", "Dupliquer"), ("Ctrl+C / Ctrl+V", "Copier / coller"),
             ("Ctrl+Z / Ctrl+Y", "Annuler / rétablir"), ("Ctrl+F ou /", "Rechercher"), ("Ctrl+G", "Aller à une date"),
             ("Tab / Maj+Tab", "Événement suivant / précédent"), ("Ctrl+B", "Panneau latéral"),
             ("Ctrl + molette, Ctrl + + / −", "Hauteur des heures"),
             ("Échap", "Annuler le geste, la recherche, la sélection (ne ferme jamais l'agenda)"),
             ("Éditeur : Ctrl+Entrée", "Enregistrer"))


class ShortcutsField(_Panel):
    """Raccourcis de l'agenda (lecture seule : non personnalisables pour l'instant)."""

    def __init__(self):
        super().__init__()
        for keys, action in SHORTCUTS:
            k = kit.label(keys, "value")
            k.setFixedWidth(210)
            self.row(k, kit.label(action, "row_label"))


class DataField(_Panel):
    def __init__(self):
        super().__init__()
        self.info = kit.label("", "value")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info.setMinimumWidth(300)
        self.info.setMaximumWidth(380)
        self.lay.addWidget(self.info)
        self.row(kit.button("Ouvrir le dossier", self._open_dir), kit.button("Sauvegarder maintenant", self._backup))
        self.row(kit.button("Importer un .ics…", self._import), kit.button("Exporter tout en .ics…", self._export))
        self.refresh()

    def refresh(self) -> None:
        service = runtime.service()
        if service is None:
            self.info.setText("Agenda non démarré.")
            return
        last = service.last_backup() or {}
        when = datetime.fromtimestamp(last["at"]).strftime("%d/%m/%Y %H:%M") if last.get("at") else "jamais"
        self.info.setText(f"Base : {service.path}\n{service.count()} événement(s) · dernière sauvegarde : {when}")

    def _open_dir(self) -> None:
        service = runtime.service()
        if service is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(service.path.parent)))

    def _backup(self) -> None:
        service = runtime.service()
        if service is not None:
            service.backup_now(lambda _dest: self.refresh())

    def _import(self) -> None:
        service = runtime.service()
        if service is None:
            return
        path, _f = QFileDialog.getOpenFileName(self, "Importer un calendrier", "", "iCalendar (*.ics)")
        if not path:
            return
        cals = service.writable_calendars()
        cal_id = kit.choose(self, "Importer", "Dans quel calendrier ?", [(c.id, c.name) for c in cals[:6]])
        if not cal_id:
            return
        from ..services import ics_io
        try:
            report = ics_io.import_file(service, path, cal_id)
            kit.confirm(self, "Import", report.summary(), "OK")
        except Exception as exc:                         # noqa: BLE001
            kit.confirm(self, "Import", f"Import impossible : {exc}", "OK")
        QTimer.singleShot(500, self, self.refresh)

    def _export(self) -> None:
        service = runtime.service()
        if service is None:
            return
        path, _f = QFileDialog.getSaveFileName(self, "Exporter l'agenda", time.strftime("agenda-%Y%m%d.ics"),
                                               "iCalendar (*.ics)")
        if not path:
            return
        from ..services import ics_io
        n = ics_io.export_events(service, path, calendar_ids=[c.id for c in service.calendars()])
        kit.confirm(self, "Export", f"{n} événement(s) exporté(s) dans {path}", "OK")

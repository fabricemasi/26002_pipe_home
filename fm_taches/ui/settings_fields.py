"""Champ d'ACTIONS de « Réglages : Tâches > Synchronisation » (briques des réglages) : identifiant OAuth de
l'application (le même que l'Agenda), connexion Google Tasks par le navigateur, synchronisation manuelle, état,
déconnexion. N'enregistre aucune valeur : agit sur le service des tâches en cours (`runtime`)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from fm_agenda.ui import kit
from .. import runtime


class GoogleTasksField(QWidget):
    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 4, 0, 4)
        self.lay.setSpacing(6)
        self.status = kit.label("", "value")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status.setMinimumWidth(340)
        self.status.setMaximumWidth(420)
        self.lay.addWidget(self.status)
        self.b_client = kit.button("Importer l'identifiant OAuth…", self._import_client,
                                   tip="Fichier « client_secret_….json » de la console Google Cloud (le même que "
                                       "pour l'Agenda ; activer aussi « Google Tasks API » dans le projet)")
        self.b_connect = kit.button("Connecter Google Tasks…", self._connect, accent=True)
        self.b_cancel = kit.button("Annuler la connexion", self._cancel)
        self._row(self.b_client, self.b_connect, self.b_cancel)
        self.b_sync = kit.button("Synchroniser", self._sync)
        self.b_disconnect = kit.button("Déconnecter…", self._disconnect)
        self._row(self.b_sync, self.b_disconnect)
        self.help = kit.label("La connexion s'ouvre dans votre navigateur : PIPE FMZ ne voit jamais votre mot de "
                              "passe Google ; le jeton est rangé dans le Gestionnaire d'identifiants Windows. Les "
                              "listes Google arrivent dans « Mes listes » ; une liste locale s'envoie vers Google "
                              "par son menu (clic droit).", "inline_label")
        self.help.setWordWrap(True)
        self.help.setMaximumWidth(420)
        self.lay.addWidget(self.help)
        manager = runtime.manager()
        if manager is not None:
            manager.changed.connect(self.refresh)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(5000)
        self.refresh()

    def _row(self, *widgets) -> None:
        row = QHBoxLayout()
        row.setSpacing(6)
        for w in widgets:
            row.addWidget(w)
        row.addStretch(1)
        self.lay.addLayout(row)

    def refresh(self) -> None:
        manager = runtime.manager()
        if manager is None:
            self.status.setText("Tâches non démarrées (ouvrir le module Tâches une fois).")
            for b in (self.b_connect, self.b_sync, self.b_disconnect, self.b_cancel):
                b.setEnabled(False)
            return
        accounts = manager.accounts()
        has_client = manager.has_client()
        self.status.setText(manager.status_text() + ("" if has_client else
                                                     "\nIdentifiant OAuth de l'application : à importer."))
        connecting = manager.running and "Connexion" in manager.state.get("message", "")
        self.b_client.setText("Remplacer l'identifiant OAuth…" if has_client else "Importer l'identifiant OAuth…")
        self.b_connect.setVisible(has_client and not connecting)
        self.b_connect.setEnabled(True)
        reconnect = any(a.get("status") == "auth_error" for a in accounts)
        self.b_connect.setText("Reconnecter Google Tasks…" if reconnect else
                               ("Ajouter un compte Google…" if accounts else "Connecter Google Tasks…"))
        self.b_cancel.setVisible(connecting)
        for b, on in ((self.b_sync, bool(accounts) and not manager.running), (self.b_disconnect, bool(accounts))):
            b.setVisible(bool(accounts))
            b.setEnabled(on)

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
            kit.confirm(self, "Google Tasks", str(exc), "OK")
        self.refresh()

    def _cancel(self) -> None:
        runtime.manager().cancel_connect()

    def _sync(self) -> None:
        runtime.manager().sync_now(on_done=lambda _r: self.refresh())
        self.refresh()

    def _disconnect(self) -> None:
        manager = runtime.manager()
        accounts = manager.accounts()
        if not accounts:
            return
        account = accounts[0]
        if len(accounts) > 1:
            choice = kit.choose(self, "Déconnecter", "Quel compte ?",
                                [(a["id"], a.get("email") or "Compte Google") for a in accounts])
            if choice is None:
                return
            account = next(a for a in accounts if a["id"] == choice)
        keep = kit.choose(self, "Déconnecter Google Tasks",
                          f"Déconnecter {account.get('email') or 'ce compte'} ? Les listes Google peuvent rester "
                          "sur ce PC comme listes locales (rien n'est supprimé chez Google).",
                          [("keep", "Garder les listes ici"), ("drop", "Retirer les listes de ce PC")])
        if keep is None:
            return
        manager.disconnect(account["id"], keep_tasks=keep == "keep", on_done=lambda _r: self.refresh())
        self.refresh()

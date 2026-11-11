"""Réglages du module Tâches (fenêtre « Réglages : Tâches ») : lignes `CATALOG["Tâches : …"]` et arbre
`TACHES_TREE`. Défauts : `settings_defaults.py`. Appliqués EN DIRECT au panneau ouvert (chemin rapide des clés
`taches_` de `PipelineBrowser._apply_settings` -> `TasksPane.apply_settings`)."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec

from .settings_defaults import TACHES_DEFAULTS as D

TACHES_TAB = "Module Tâches"

START_CHOICES = (("last", "Vue quittée"), ("today", "Aujourd'hui"), ("planned", "Planifiées"),
                 ("flagged", "Marquées"), ("all", "Toutes"))


def _list_choices():
    from . import runtime
    service = runtime.service()
    out = [("", "Première liste")]
    if service is not None:
        out += [(lst.id, lst.name) for lst in service.lists()]
    return tuple(out)


CATALOG["Tâches : Affichage"] = [
    Spec("taches_theme", "Thème", "choice", D["taches_theme"],
         {"choices": (("sombre", "Sombre"), ("clair", "Clair")), "width": 160}),
    Spec("taches_accent", "Couleur d'accent (vide = celle de l'appli)", "text", D["taches_accent"], {"width": 120}),
    Spec("taches_density", "Densité", "choice", D["taches_density"],
         {"choices": (("compacte", "Compacte"), ("normal", "Normale"), ("confortable", "Confortable")),
          "width": 160}),
    Spec("taches_start_view", "Vue à l'ouverture", "choice", D["taches_start_view"],
         {"choices": START_CHOICES, "width": 190}),
    Spec("taches_show_sidebar", "Panneau latéral", "bool", D["taches_show_sidebar"]),
    Spec("taches_sidebar_width", "Largeur du panneau latéral", "slider", D["taches_sidebar_width"],
         {"min": 200, "max": 420, "unit": "px"}),
    Spec("taches_show_details", "Panneau de détails", "bool", D["taches_show_details"]),
    Spec("taches_show_done", "Tâches terminées dans les listes", "bool", D["taches_show_done"]),
    Spec("taches_done_last", "Terminées en bas", "bool", D["taches_done_last"]),
    Spec("taches_show_notes", "Première ligne des notes sous le titre", "bool", D["taches_show_notes"]),
    Spec("taches_width", "Largeur du module", "slider", D["taches_width"], {"min": 30, "max": 100, "unit": "%"}),
]
CATALOG["Tâches : Comportement"] = [
    Spec("taches_new_on_top", "Nouvelle tâche en tête de liste", "bool", D["taches_new_on_top"]),
    Spec("taches_default_list", "Liste par défaut", "choice", D["taches_default_list"],
         {"choices": _list_choices, "width": 230}),
    Spec("taches_confirm_delete", "Confirmer la suppression (liste, tâche à sous-tâches)", "bool",
         D["taches_confirm_delete"]),
    Spec("taches_drag_requires_ctrl", "Déplacer une tâche seulement avec Ctrl", "bool",
         D["taches_drag_requires_ctrl"]),
]
CATALOG["Tâches : Données"] = [
    Spec("taches_data_dir", "Dossier des données (vide = %LOCALAPPDATA%, redémarrage)", "text", D["taches_data_dir"],
         {"width": 330}),
    Spec("taches_backup_daily", "Sauvegarde quotidienne automatique", "bool", D["taches_backup_daily"]),
    Spec("taches_backup_keep", "Sauvegardes gardées", "slider", D["taches_backup_keep"], {"min": 1, "max": 90}),
]

CATALOG["Tâches : Rappels"] = [
    Spec("taches_reminders_enabled", "Rappels actifs", "bool", D["taches_reminders_enabled"]),
    Spec("taches_remind_at_due", "Rappel à l'heure d'une tâche à heure (sans rappel choisi)", "bool",
         D["taches_remind_at_due"]),
    Spec("taches_notify_mode", "Notification", "choice", D["taches_notify_mode"],
         {"choices": (("both", "Windows + fenêtre de l'appli"), ("windows", "Notification Windows"),
                      ("app", "Fenêtre de l'appli")), "width": 250}),
    Spec("taches_snooze_minutes", "Rappel reporté de", "choice", D["taches_snooze_minutes"],
         {"choices": ((5, "5 minutes"), (10, "10 minutes"), (15, "15 minutes"), (30, "30 minutes"),
                      (60, "1 heure")), "width": 160}),
    Spec("taches_missed_minutes", "Rappel manqué montré au lancement (jusqu'à)", "slider",
         D["taches_missed_minutes"], {"min": 0, "max": 720, "unit": "min"}),
]

CATALOG["Tâches : Synchronisation"] = [
    Spec("taches_panel_google", "Google Tasks", "taches_google", None),
    Spec("taches_sync_auto", "Synchronisation automatique", "bool", D["taches_sync_auto"]),
    Spec("taches_sync_interval_min", "Fréquence", "slider", D["taches_sync_interval_min"],
         {"min": 1, "max": 120, "unit": "min"}),
    Spec("taches_sync_on_change", "Envoyer aussitôt une modification locale", "bool", D["taches_sync_on_change"]),
    Spec("taches_conflict_policy", "Champ modifié des deux côtés", "choice", D["taches_conflict_policy"],
         {"choices": (("recent", "La modification la plus récente"), ("google", "La version Google l'emporte"),
                      ("local", "La version de PIPE FMZ l'emporte")), "width": 280}),
]

TACHES_TREE = (
    Node("Affichage", "Tâches : Affichage"),
    Node("Comportement", "Tâches : Comportement"),
    Node("Rappels", "Tâches : Rappels"),
    Node("Synchronisation", "Tâches : Synchronisation"),
    Node("Données", "Tâches : Données"),
)


# -- champ d'actions (construit par la fenêtre de réglages ; aucune valeur enregistrée) --

def _f_google(spec, v, colors):
    from .ui.settings_fields import GoogleTasksField
    return GoogleTasksField()


FIELD_FACTORIES = {"taches_google": _f_google}
FIELD_READERS = {kind: (lambda sp, w: {}) for kind in FIELD_FACTORIES}

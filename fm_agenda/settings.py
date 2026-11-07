"""Réglages de l'agenda (fenêtre « Réglages : Agenda ») : lignes `CATALOG["Agenda : …"]` et arbre `AGENDA_TREE`.
Données seulement, sauf deux champs d'ACTIONS (comptes Google, données locales) construits avec les briques des
réglages. Défauts : `settings_defaults.py`. Appliqués EN DIRECT à l'agenda ouvert (chemin rapide des clés `agenda_`
de `PipelineBrowser._apply_settings` -> `AgendaPane.apply_settings`)."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec

from .core.timeutil import COMMON_ZONES
from .settings_defaults import AGENDA_DEFAULTS as D

AGENDA_TAB = "Module Agenda"

VIEW_CHOICES = (("jour", "Jour"), ("semaine", "Semaine"), ("travail", "Semaine de travail"), ("mois", "Mois"),
                ("annee", "Année"), ("planning", "Liste"))
WEEKDAY_CHOICES = ((0, "Lundi"), (1, "Mardi"), (2, "Mercredi"), (3, "Jeudi"), (4, "Vendredi"), (5, "Samedi"),
                   (6, "Dimanche"))
REMINDER_CHOICES = ((-1, "Aucun"), (0, "À l'heure de l'événement"), (5, "5 minutes avant"), (10, "10 minutes avant"),
                    (15, "15 minutes avant"), (30, "30 minutes avant"), (60, "1 heure avant"),
                    (1440, "1 jour avant"))


def _calendar_choices():
    from . import runtime
    service = runtime.service()
    out = [("", "Premier calendrier modifiable")]
    if service is not None:
        out += [(c.id, c.name) for c in service.writable_calendars()]
    return tuple(out)


def _zone_choices():
    return (("", "Fuseau de Windows"),) + tuple((z, z) for z in COMMON_ZONES)


CATALOG["Agenda : Affichage"] = [
    Spec("agenda_theme", "Thème", "choice", D["agenda_theme"],
         {"choices": (("sombre", "Sombre"), ("clair", "Clair")), "width": 160}),
    Spec("agenda_accent", "Couleur d'accent (vide = celle de l'appli)", "text", D["agenda_accent"], {"width": 120}),
    Spec("agenda_today_color", "Couleur d'aujourd'hui (vide = #cc3d35)", "text", D["agenda_today_color"],
         {"width": 120}),
    Spec("agenda_density", "Densité", "choice", D["agenda_density"],
         {"choices": (("compacte", "Compacte"), ("normal", "Normale"), ("confortable", "Confortable")),
          "width": 160}),
    Spec("agenda_default_view", "Vue à l'ouverture", "choice", D["agenda_default_view"],
         {"choices": VIEW_CHOICES, "width": 190}),
    Spec("agenda_restore_state", "Rouvrir sur la vue et la date quittées", "bool", D["agenda_restore_state"]),
    Spec("agenda_first_weekday", "Premier jour de la semaine", "choice", D["agenda_first_weekday"],
         {"choices": WEEKDAY_CHOICES, "width": 160}),
    Spec("agenda_time_format", "Format des heures", "choice", D["agenda_time_format"],
         {"choices": (("24", "24 h (14:00)"), ("12", "12 h (2:00 PM)")), "width": 160}),
    Spec("agenda_show_weekends", "Week-ends dans la vue Semaine", "bool", D["agenda_show_weekends"]),
    Spec("agenda_day_start", "Début de journée (heure montrée en haut)", "slider", D["agenda_day_start"],
         {"min": 0, "max": 23, "unit": "h"}),
    Spec("agenda_day_end", "Fin de journée", "slider", D["agenda_day_end"], {"min": 1, "max": 24, "unit": "h"}),
    Spec("agenda_limit_hours", "Grille limitée à la journée (comme la maquette)", "bool", D["agenda_limit_hours"]),
    Spec("agenda_hour_height", "Hauteur d'une heure", "slider", D["agenda_hour_height"],
         {"min": 24, "max": 160, "unit": "px"}),
    Spec("agenda_snap_minutes", "Pas du glisser et de la création", "choice", D["agenda_snap_minutes"],
         {"choices": ((5, "5 minutes"), (10, "10 minutes"), (15, "15 minutes"), (30, "30 minutes")), "width": 160}),
    Spec("agenda_show_sidebar", "Panneau latéral", "bool", D["agenda_show_sidebar"]),
    Spec("agenda_sidebar_width", "Largeur du panneau latéral", "slider", D["agenda_sidebar_width"],
         {"min": 220, "max": 480, "unit": "px"}),
    Spec("agenda_width", "Largeur de l'agenda (aussi dans la barre d'état)", "slider", D["agenda_width"],
         {"min": 30, "max": 100, "unit": "%"}),
    Spec("agenda_show_upcoming", "Prochains jours dans le panneau latéral", "bool", D["agenda_show_upcoming"]),
    Spec("agenda_list_days", "Jours de la vue Liste", "slider", D["agenda_list_days"],
         {"min": 7, "max": 365, "unit": "j"}),
    Spec("agenda_day_autoselect", "Vue Jour : sélectionner le prochain événement", "bool",
         D["agenda_day_autoselect"]),
    Spec("agenda_long_bars", "Événements longs en barres", "bool", D["agenda_long_bars"]),
    Spec("agenda_long_threshold", "Barre à partir de", "choice", D["agenda_long_threshold"],
         {"choices": ((2, "2 heures"), (3, "3 heures"), (4, "4 heures"), (6, "6 heures"), (8, "8 heures"),
                      (12, "12 heures")), "width": 160}),
    Spec("agenda_bar_width", "Épaisseur de la barre", "slider", D["agenda_bar_width"],
         {"min": 4, "max": 24, "unit": "px"}),
    Spec("agenda_arrow_width", "Épaisseur de la flèche", "slider", D["agenda_arrow_width"],
         {"min": 3, "max": 24, "unit": "px"}),
]
CATALOG["Agenda : Comportement"] = [
    Spec("agenda_default_duration", "Durée d'un nouvel événement", "choice", D["agenda_default_duration"],
         {"choices": ((15, "15 minutes"), (30, "30 minutes"), (45, "45 minutes"), (60, "1 heure"),
                      (90, "1 h 30"), (120, "2 heures")), "width": 160}),
    Spec("agenda_default_calendar", "Calendrier par défaut", "choice", D["agenda_default_calendar"],
         {"choices": _calendar_choices, "width": 230}),
    Spec("agenda_default_reminder", "Rappel par défaut", "choice", D["agenda_default_reminder"],
         {"choices": REMINDER_CHOICES, "width": 230}),
    Spec("agenda_create_mode", "Double-clic dans une case vide", "choice", D["agenda_create_mode"],
         {"choices": (("editor", "Ouvrir l'éditeur"), ("direct", "Créer aussitôt")), "width": 190}),
    Spec("agenda_week_click", "Clic sur un événement de la semaine", "choice", D["agenda_week_click"],
         {"choices": (("selection", "Le sélectionner"), ("jour", "Ouvrir son jour (maquette)")), "width": 230}),
    Spec("agenda_month_click", "Clic dans le mois", "choice", D["agenda_month_click"],
         {"choices": (("jour", "Ouvrir le jour (maquette)"), ("selection", "Sélectionner (double-clic : ouvrir)")),
          "width": 260}),
    Spec("agenda_recurring_move", "Déplacer un événement récurrent", "choice", D["agenda_recurring_move"],
         {"choices": (("ask", "Demander"), ("this", "Cette occurrence"), ("all", "Toute la série")), "width": 190}),
    Spec("agenda_confirm_delete", "Confirmer la suppression", "bool", D["agenda_confirm_delete"]),
    Spec("agenda_drag_requires_ctrl", "Déplacer un événement seulement avec Ctrl", "bool",
         D["agenda_drag_requires_ctrl"]),
    Spec("agenda_panel_shortcuts", "Raccourcis clavier", "agenda_shortcuts", None),
]
CATALOG["Agenda : Rappels"] = [
    Spec("agenda_reminders_enabled", "Rappels actifs", "bool", D["agenda_reminders_enabled"]),
    Spec("agenda_notify_mode", "Notification", "choice", D["agenda_notify_mode"],
         {"choices": (("both", "Windows + fenêtre de l'appli"), ("windows", "Notification Windows"),
                      ("app", "Fenêtre de l'appli")), "width": 250}),
    Spec("agenda_snooze_minutes", "Rappel reporté de", "choice", D["agenda_snooze_minutes"],
         {"choices": ((5, "5 minutes"), (10, "10 minutes"), (15, "15 minutes"), (30, "30 minutes")), "width": 160}),
    Spec("agenda_missed_minutes", "Rappel manqué montré au lancement (jusqu'à)", "slider",
         D["agenda_missed_minutes"], {"min": 0, "max": 240, "unit": "min"}),
]
CATALOG["Agenda : Données"] = [
    Spec("agenda_panel_data", "Base locale", "agenda_data", None),
    Spec("agenda_timezone", "Fuseau horaire", "choice", D["agenda_timezone"],
         {"choices": _zone_choices, "width": 230}),
    Spec("agenda_data_dir", "Dossier des données (vide = %LOCALAPPDATA%, redémarrage)", "text", D["agenda_data_dir"],
         {"width": 330}),
    Spec("agenda_backup_daily", "Sauvegarde quotidienne automatique", "bool", D["agenda_backup_daily"]),
    Spec("agenda_backup_keep", "Sauvegardes gardées", "slider", D["agenda_backup_keep"], {"min": 1, "max": 90}),
    Spec("agenda_backup_dir", "Dossier des sauvegardes (vide = celui des données)", "text", D["agenda_backup_dir"],
         {"width": 330}),
]
CATALOG["Agenda : Synchronisation"] = [
    Spec("agenda_panel_google", "Google Agenda", "agenda_google", None),
    Spec("agenda_sync_auto", "Synchronisation automatique", "bool", D["agenda_sync_auto"]),
    Spec("agenda_sync_interval_min", "Fréquence", "slider", D["agenda_sync_interval_min"],
         {"min": 1, "max": 120, "unit": "min"}),
    Spec("agenda_sync_on_change", "Envoyer aussitôt une modification locale", "bool", D["agenda_sync_on_change"]),
    Spec("agenda_conflict_policy", "Conflit (modifié des deux côtés)", "choice", D["agenda_conflict_policy"],
         {"choices": (("ask", "Garder les deux versions, demander"), ("remote", "La version Google l'emporte"),
                      ("local", "La version de PIPE FMZ l'emporte")), "width": 280}),
    Spec("agenda_server_url", "Serveur personnel (futur Raspberry Pi, non utilisé)", "text", D["agenda_server_url"],
         {"width": 280}),
]

AGENDA_TREE = (
    Node("Affichage", "Agenda : Affichage"),
    Node("Comportement", "Agenda : Comportement"),
    Node("Rappels", "Agenda : Rappels"),
    Node("Données", "Agenda : Données"),
    Node("Synchronisation", "Agenda : Synchronisation"),
)


# -- champs d'actions (construits par la fenêtre de réglages ; aucune valeur enregistrée) --

def _f_google(spec, v, colors):
    from .ui.settings_fields import GoogleAccountsField
    return GoogleAccountsField()


def _f_data(spec, v, colors):
    from .ui.settings_fields import DataField
    return DataField()


def _f_shortcuts(spec, v, colors):
    from .ui.settings_fields import ShortcutsField
    return ShortcutsField()


FIELD_FACTORIES = {"agenda_google": _f_google, "agenda_data": _f_data, "agenda_shortcuts": _f_shortcuts}
FIELD_READERS = {kind: (lambda sp, w: {}) for kind in FIELD_FACTORIES}

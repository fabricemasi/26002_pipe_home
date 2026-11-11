"""Valeurs par défaut des réglages du module Tâches (sans Qt). Fusionnées dans `settings_store.DEFAULT_SETTINGS`
(toute clé `taches_*` doit être déclarée ici pour être gardée par `load_settings`). Les préférences de NAVIGATION
(vue ouverte, listes repliées, largeur du panneau latéral) vivent dans la base des tâches (table `meta`)."""

TACHES_DEFAULTS = {
    # Affichage
    "taches_theme": "sombre",              # sombre | clair (bouton soleil / lune de la barre)
    "taches_accent": "",                   # vide = accent de l'appli (palette M), sinon « #rrggbb »
    "taches_density": "normal",            # compacte | normal | confortable
    "taches_start_view": "last",           # last (vue quittée) | today | all | flagged | planned
    "taches_show_sidebar": True,
    "taches_sidebar_width": 250,
    "taches_show_details": True,           # panneau de détails à droite
    "taches_show_done": True,              # tâches terminées montrées dans les listes
    "taches_done_last": True,              # terminées en bas de leur fratrie
    "taches_show_notes": True,             # première ligne des notes sous le titre
    "taches_width": 100,                   # % de la place (contenu centré), comme l'agenda
    # Comportement
    "taches_new_on_top": False,            # nouvelle tâche en tête de liste (Google) plutôt qu'en fin (Apple)
    "taches_default_list": "",             # id ; vide = première liste
    "taches_confirm_delete": True,         # confirmer la suppression d'une liste ou d'une tâche à sous-tâches
    "taches_drag_requires_ctrl": True,     # règle de l'appli : déplacer seulement avec Ctrl
    # Rappels (locaux : Google Tasks n'en a pas)
    "taches_reminders_enabled": True,
    "taches_remind_at_due": True,          # tâche à heure sans rappel : rappel à l'heure de l'échéance
    "taches_notify_mode": "both",          # both | windows | app
    "taches_snooze_minutes": 10,
    "taches_missed_minutes": 60,           # rappel manqué (appli fermée) montré au lancement jusqu'à
    # Synchronisation (Google Tasks)
    "taches_sync_auto": True,
    "taches_sync_interval_min": 5,
    "taches_sync_on_change": True,         # envoyer ~3 s après une modification locale
    "taches_conflict_policy": "recent",    # recent | google | local (champ modifié des deux côtés)
    # Données
    "taches_data_dir": "",                 # vide = %LOCALAPPDATA%\PIPE_FMZ\fm_taches (redémarrage)
    "taches_backup_daily": True,
    "taches_backup_keep": 14,
}

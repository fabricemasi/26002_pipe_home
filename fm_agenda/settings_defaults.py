"""Valeurs par défaut des réglages de l'agenda (sans Qt). Fusionnées dans `settings_store.DEFAULT_SETTINGS` (toute
clé `agenda_*` doit être déclarée ici pour être gardée par `load_settings`). Les préférences de NAVIGATION (vue et
date affichées, largeur du panneau latéral, zoom des heures) vivent dans la base de l'agenda (table `meta`), pas
ici : elles changent à chaque clic."""

AGENDA_DEFAULTS = {
    # Affichage
    "agenda_theme": "sombre",              # sombre | clair (bouton soleil / lune de la barre)
    "agenda_accent": "",                   # vide = accent de l'appli (palette M), sinon « #rrggbb »
    "agenda_today_color": "",              # vide = #cc3d35 (design)
    "agenda_density": "normal",            # compacte | normal | confortable
    "agenda_default_view": "semaine",      # jour | semaine | travail | mois | annee | planning
    "agenda_restore_state": True,          # rouvrir sur la vue et la date quittées
    "agenda_first_weekday": 0,             # 0 = lundi … 6 = dimanche
    "agenda_time_format": "24",            # 24 | 12
    "agenda_show_weekends": True,          # faux : la vue Semaine ne montre que les jours ouvrés
    "agenda_work_days": [0, 1, 2, 3, 4],   # jours de la semaine de travail
    "agenda_day_start": 8,                 # heure montrée en haut de la grille à l'ouverture
    "agenda_day_end": 20,
    "agenda_limit_hours": False,           # vrai : grille limitée à [début, fin] (comme la maquette, 8 h – 20 h)
    "agenda_hour_height": 52,              # px par heure (design : 52)
    "agenda_snap_minutes": 15,             # pas du glisser / de la création
    "agenda_show_sidebar": True,
    "agenda_sidebar_width": 272,
    "agenda_width": 100,                   # % de la place : contenu centré (curseur de la barre d'état)
    "agenda_show_upcoming": True,          # agenda des prochains jours dans le panneau latéral
    "agenda_show_tasks": True,             # tâches datées du module Tâches (fm_taches) dans l'agenda
    "agenda_list_days": 30,                # jours de la vue Planning
    "agenda_day_autoselect": True,         # vue Jour : sélectionne le prochain événement (design)
    "agenda_long_bars": True,              # événements longs en barres fléchées (Jour / Semaine, maquette v10)
    "agenda_long_threshold": 4,            # heures à partir desquelles un événement devient une barre
    "agenda_bar_width": 10,                # épaisseur de la barre (px)
    "agenda_arrow_width": 9,               # épaisseur de la flèche : du flanc de la barre à la pointe (px)
    "agenda_week_click": "selection",      # selection | jour (clic sur un événement de la semaine = vue Jour)
    "agenda_month_click": "jour",          # jour (design : ouvre le jour) | selection (double-clic : ouvrir / créer)
    # Comportement
    "agenda_default_duration": 60,         # minutes
    "agenda_default_calendar": "",         # identifiant ; vide = premier calendrier modifiable
    "agenda_default_reminder": -1,         # minutes avant ; -1 = aucun
    "agenda_create_mode": "editor",        # editor (double-clic ouvre l'éditeur) | direct (crée aussitôt)
    "agenda_confirm_delete": True,
    "agenda_recurring_move": "ask",        # ask | this | all
    "agenda_drag_requires_ctrl": False,    # règle « Ctrl + glisser » de l'appli appliquée aux événements
    # Rappels
    "agenda_reminders_enabled": True,
    "agenda_notify_mode": "both",          # both | windows | app
    "agenda_snooze_minutes": 5,
    "agenda_missed_minutes": 30,           # rappel manqué (appli fermée) montré au lancement s'il date de moins
    # Données
    "agenda_data_dir": "",                 # vide = %LOCALAPPDATA%\PIPE_FMZ\fm_agenda (hors du dossier synchronisé)
    "agenda_backup_daily": True,
    "agenda_backup_keep": 14,
    "agenda_backup_dir": "",               # vide = <données>\backups
    "agenda_timezone": "",                 # vide = fuseau de Windows
    # Synchronisation
    "agenda_sync_auto": True,
    "agenda_sync_interval_min": 5,
    "agenda_sync_on_change": True,         # envoi quelques secondes après une modification locale
    "agenda_conflict_policy": "ask",       # ask (conflit gardé, à résoudre) | remote | local
    "agenda_server_url": "",               # futur serveur personnel (Raspberry Pi) : non utilisé pour l'instant
}

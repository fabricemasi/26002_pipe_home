"""Données de la maquette Claude Design (« Agenda — sombre ») chargées dans un service de test : comparaison
visuelle avec le design et tests de l'interface. Aujourd'hui = vendredi 6 novembre 2026, 14:20 (maquette)."""
from datetime import date, datetime, timedelta

from fm_agenda.core import timeutil as tu

TODAY = date(2026, 11, 6)
NOW = (14, 20)
CALS = {"bleu": "Projets et revues", "violet": "Rendus", "orange": "Livraisons et jalons", "vert": "Équipe",
        "rouge": "Tâches"}

EVENTS = [
    ("2026-01-12", "10:00", "11:00", None, "bleu", "Lancement — 26002 Identité", "26002 Identité", "", "", False),
    ("2026-02-20", None, None, 1, "orange", "Jalon : livraison 26002", "26002 Identité", "", "", False),
    ("2026-03-09", "10:00", "11:00", None, "bleu", "Lancement — 26005 Clip", "26005 Clip", "", "", False),
    ("2026-04-03", None, None, 1, "orange", "Jalon : livraison 26005 Clip", "26005 Clip", "", "", False),
    ("2026-04-13", None, None, 5, "vert", "Congés de printemps", "", "", "", True),
    ("2026-05-18", "10:00", "11:00", None, "bleu", "Lancement — 26009 Configurateur", "26009 Configurateur", "", "", False),
    ("2026-06-26", None, None, 1, "orange", "Jalon : V1 26009 Configurateur", "26009 Configurateur", "", "", False),
    ("2026-08-03", None, None, 12, "vert", "Fermeture d'été", "", "", "", True),
    ("2026-09-07", "10:00", "11:30", None, "bleu", "Lancement — 26014 Teaser", "26014 Teaser", "", "", False),
    ("2026-09-21", "10:00", "11:00", None, "bleu", "Lancement — 26017 Packshot", "26017 Packshot", "", "", False),
    ("2026-10-09", None, None, 1, "orange", "Jalon : animatique 26014", "26014 Teaser", "", "", False),
    ("2026-10-19", "18:00", "21:00", None, "violet", "Rendu de nuit — 26014, tests", "26014 Teaser", "", "", False),
    ("2026-10-28", "14:00", "15:00", None, "bleu", "Revue anim — 26009 Configurateur", "26009 Configurateur", "", "", False),
    ("2026-10-30", "16:00", "17:00", None, "orange", "Livraison V1 — 26014 Teaser", "26014 Teaser",
     "F:\\PIPELINE\\26014_Teaser\\OUT\\V1", "", False),
    ("2026-11-02", None, None, 3, "vert", "Congés — Léa", "", "", "", False),
    ("2026-11-02", "14:00", "16:00", None, "bleu", "Revue layout — 26014 Teaser", "26014 Teaser", "", "", False),
    ("2026-11-03", "10:00", "11:00", None, "bleu", "Revue client — 26009 Configurateur", "26009 Configurateur", "", "", False),
    ("2026-11-03", "13:00", "task", None, "rouge", "Nettoyer le dossier OUT", "26014 Teaser",
     "F:\\PIPELINE\\26014_Teaser\\OUT", "", False),
    ("2026-11-03", "18:00", "21:00", None, "violet", "Rendu de nuit — 26014, plans 010 à 040", "26014 Teaser", "", "", False),
    ("2026-11-04", "09:00", "task", None, "rouge", "Exporter les caches Alembic", "26017 Packshot", "", "", False),
    ("2026-11-04", "11:00", "12:30", None, "bleu", "Revue lookdev — 26017 Packshot", "26017 Packshot", "", "", False),
    ("2026-11-04", "15:00", "16:00", None, "vert", "Point équipe 3D", "", "", "", False),
    ("2026-11-05", None, None, 2, "orange", "Jalon : V2 Teaser 26014", "26014 Teaser", "", "", False),
    ("2026-11-05", "10:00", "11:00", None, "bleu", "Visio client — 26009", "26009 Configurateur", "", "", False),
    ("2026-11-05", "14:00", "17:00", None, "violet", "Ferme de rendu — 26017", "26017 Packshot", "", "", False),
    ("2026-11-05", "14:30", "15:30", None, "bleu", "Revue compo — 26014", "26014 Teaser", "", "", False),
    ("2026-11-06", "09:30", "10:00", None, "vert", "Point de prod", "", "", "", False),
    ("2026-11-06", "11:00", "task", None, "rouge", "Valider les plans 050 à 080", "26014 Teaser", "",
     "Contrôle qualité des plans 050 à 080 avant la livraison de 15:00.", False),
    ("2026-11-06", "15:00", "16:00", None, "orange", "Livraison V2 — 26014 Teaser", "26014 Teaser",
     "F:\\PIPELINE\\26014_Teaser\\OUT\\V2",
     "Vérifier les plans 050 à 080, puis envoyer le lien de téléchargement au client.", False),
    ("2026-11-06", "17:00", "18:00", None, "vert", "Revue de fin de semaine", "", "",
     "Bilan de la semaine et planning des rendus du week-end.", False),
    ("2026-11-07", "10:00", "15:00", None, "violet", "Rendu ferme — 26017 Packshot", "26017 Packshot", "", "", False),
    ("2026-11-09", "14:00", "15:00", None, "bleu", "Revue anim — 26014 Teaser", "26014 Teaser", "", "", False),
    ("2026-11-12", "10:00", "11:00", None, "vert", "Point équipe 3D", "", "", "", False),
    ("2026-11-12", "15:00", "16:30", None, "bleu", "Revue lookdev — 26017 Packshot", "26017 Packshot", "", "", False),
    ("2026-11-13", "16:00", "17:00", None, "orange", "Livraison images — 26017 Packshot", "26017 Packshot",
     "F:\\PIPELINE\\26017_Packshot\\OUT", "", False),
    ("2026-11-17", "11:00", "12:00", None, "bleu", "Revue client — 26009 Configurateur", "26009 Configurateur", "", "", False),
    ("2026-11-19", "14:00", "15:00", None, "bleu", "Revue compo — 26014", "26014 Teaser", "", "", False),
    ("2026-11-19", "19:00", "21:00", None, "violet", "Rendu de nuit — 26009", "26009 Configurateur", "", "", False),
    ("2026-11-20", None, None, 1, "orange", "Jalon : livraison finale 26014", "26014 Teaser", "", "", False),
    ("2026-11-24", "10:00", "11:30", None, "bleu", "Lancement — 26021 Série animée", "26021 Série animée", "", "", False),
    ("2026-11-24", "15:00", "16:00", None, "vert", "Point équipe 3D", "", "", "", False),
    ("2026-11-26", "18:00", "21:00", None, "violet", "Rendu de nuit — 26021", "26021 Série animée", "", "", False),
    ("2026-11-27", None, None, 1, "orange", "Jalon : V1 26017 Packshot", "26017 Packshot", "", "", False),
    ("2026-12-01", "10:00", "11:00", None, "bleu", "Revue client — 26017 Packshot", "26017 Packshot", "", "", False),
    ("2026-12-04", "16:00", "17:00", None, "orange", "Livraison V2 — 26017 Packshot", "26017 Packshot", "", "", False),
    ("2026-12-18", None, None, 1, "orange", "Jalon : pilote 26021", "26021 Série animée", "", "", False),
    ("2026-12-24", None, None, 8, "vert", "Fermeture de fin d'année", "", "", "", True),
]


def load(service, tz_name="Europe/Paris"):
    """Les événements de la maquette, et le « Point de prod hebdo » (série du lundi, sauf jours fermés)."""
    tz = tu.get_tz(tz_name)
    cal_ids = {color: next(c.id for c in service.calendars() if c.name == name) for color, name in CALS.items()}
    off_days = set()
    for d, s, e, days, color, title, project, folder, note, off in EVENTS:
        day = date.fromisoformat(d)
        draft = service.new_draft(day, day + timedelta(days=days or 1), all_day=bool(days),
                                  calendar_id=cal_ids[color])
        if not days:
            h, m = (int(x) for x in s.split(":"))
            start = tu.localize(datetime(day.year, day.month, day.day, h, m), tz)
            draft.all_day = False
            draft.start_date = draft.end_date = None
            draft.start = start
            if e == "task":
                draft.end = start
                draft.is_task = True
            else:
                h2, m2 = (int(x) for x in e.split(":"))
                draft.end = tu.localize(datetime(day.year, day.month, day.day, h2, m2), tz)
            draft.tzid = tz_name
        else:
            if off:
                for i in range(days):
                    off_days.add(day + timedelta(days=i))
        draft.title = title
        draft.project = project
        draft.folder = folder
        draft.notes = note
        draft.reminders = []
        service.create(draft)
    first = date(2026, 1, 5)
    start = tu.localize(datetime(2026, 1, 5, 9, 30), tz)
    weekly = service.new_draft(start, start + timedelta(hours=1), calendar_id=cal_ids["vert"])
    weekly.title = "Point de prod hebdo"
    weekly.notes = "Avancement des projets et planning des rendus de la semaine."
    weekly.rrule = "FREQ=WEEKLY;BYDAY=MO;UNTIL=20261231T225959Z"
    weekly.tzid = tz_name
    weekly.reminders = []
    ex = []
    d = first
    while d.year == 2026:
        if d in off_days:
            ex.append(tu.rid_for_datetime(tu.localize(datetime(d.year, d.month, d.day, 9, 30), tz)))
        d += timedelta(days=7)
    weekly.exdates = ex
    service.create(weekly)


def freeze(ctx):
    ctx._now_override = tu.localize(datetime(TODAY.year, TODAY.month, TODAY.day, *NOW), ctx.tz)

"""Schéma SQLite de l'agenda et ses migrations (`PRAGMA user_version`).

Une migration = (version, script SQL) ; elles s'appliquent dans l'ordre, chacune dans une transaction, après une
sauvegarde de la base existante (`database.open_database`). Ne JAMAIS modifier une migration publiée : en ajouter
une nouvelle. Conçu pour passer tel quel à PostgreSQL (types simples, clés textuelles UUID, horodatages epoch).

Tables :
- `meta`        clé / valeur (identifiant de l'appareil, horloge de révision, préférences de l'interface) ;
- `accounts`    comptes distants (Google, futur serveur) ; AUCUN jeton ici (Gestionnaire d'identifiants Windows) ;
- `calendars`   calendriers (source, droits, jeton de synchronisation incrémentale) ;
- `events`      événements simples, maîtres de séries, exceptions (series_id + recurrence_id) ; suppression
                douce (`deleted`) tant que la source distante ne l'a pas confirmée ;
- `sync_outbox` file persistante des envois (un par événement, regroupés ; essais, prochain essai, erreur) ;
- `conflicts`   versions locale / distante / de base d'un conflit non résolu (rien n'est perdu) ;
- `changes`     journal des modifications (révision, provenance) : base du futur serveur et anti-boucles ;
- `reminder_log` rappels déjà montrés (jamais deux fois la même notification)."""

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'connected',
    last_error TEXT NOT NULL DEFAULT '',
    last_sync_at INTEGER NOT NULL DEFAULT 0,
    settings TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE calendars (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'bleu',
    visible INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'local',
    account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
    remote_id TEXT,
    access_role TEXT NOT NULL DEFAULT 'owner',
    sync_enabled INTEGER NOT NULL DEFAULT 0,
    sync_token TEXT,
    description TEXT NOT NULL DEFAULT '',
    timezone TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    props TEXT NOT NULL DEFAULT '{}',
    deleted INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX cal_remote ON calendars(account_id, remote_id) WHERE remote_id IS NOT NULL;
CREATE TABLE events (
    id TEXT PRIMARY KEY,
    calendar_id TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    series_id TEXT REFERENCES events(id) ON DELETE CASCADE,
    recurrence_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    all_day INTEGER NOT NULL DEFAULT 0,
    start_ts INTEGER NOT NULL,
    end_ts INTEGER NOT NULL,
    tzid TEXT NOT NULL DEFAULT '',
    start_date TEXT,
    end_date TEXT,
    rrule TEXT,
    exdates TEXT NOT NULL DEFAULT '[]',
    until_ts INTEGER,
    color TEXT,
    categories TEXT NOT NULL DEFAULT '[]',
    transparency TEXT NOT NULL DEFAULT 'opaque',
    status TEXT NOT NULL DEFAULT 'confirmed',
    is_task INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    project TEXT NOT NULL DEFAULT '',
    folder TEXT NOT NULL DEFAULT '',
    attendees TEXT NOT NULL DEFAULT '[]',
    reminders TEXT NOT NULL DEFAULT '[]',
    reminders_default INTEGER NOT NULL DEFAULT 0,
    ical_uid TEXT,
    remote_id TEXT,
    etag TEXT,
    sequence INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    sync_state TEXT NOT NULL DEFAULT 'local',
    base TEXT,
    origin TEXT NOT NULL DEFAULT '',
    deleted INTEGER NOT NULL DEFAULT 0,
    extra TEXT NOT NULL DEFAULT '{}',
    CHECK (end_ts >= start_ts)
);
-- Événements simples : fenêtre [début, fin[ (le début est borné par la durée maximale connue, voir repository).
CREATE INDEX ev_simple ON events(start_ts) WHERE deleted = 0 AND rrule IS NULL AND series_id IS NULL;
-- Maîtres de séries : début et fin de la dernière occurrence (NULL = infinie).
CREATE INDEX ev_master ON events(start_ts, until_ts) WHERE deleted = 0 AND rrule IS NOT NULL;
-- Exceptions : par série, et par leur propre horaire (une occurrence déplacée loin de sa date d'origine).
CREATE INDEX ev_series ON events(series_id) WHERE series_id IS NOT NULL;
CREATE INDEX ev_override_time ON events(start_ts) WHERE series_id IS NOT NULL AND deleted = 0;
CREATE INDEX ev_calendar ON events(calendar_id);
CREATE UNIQUE INDEX ev_remote ON events(calendar_id, remote_id) WHERE remote_id IS NOT NULL;
CREATE INDEX ev_pending ON events(sync_state) WHERE sync_state IN ('dirty', 'deleted', 'conflict');
CREATE INDEX ev_reminders ON events(start_ts) WHERE deleted = 0 AND (reminders != '[]' OR reminders_default = 1);
CREATE TABLE sync_outbox (
    event_id TEXT PRIMARY KEY,
    calendar_id TEXT NOT NULL,
    account_id TEXT,
    created_at INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_at INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    detected_at INTEGER NOT NULL,
    local TEXT NOT NULL,
    remote TEXT NOT NULL,
    base TEXT,
    fields TEXT NOT NULL DEFAULT '[]',
    resolved INTEGER NOT NULL DEFAULT 0,
    resolution TEXT NOT NULL DEFAULT ''
);
CREATE INDEX conflict_open ON conflicts(event_id) WHERE resolved = 0;
CREATE TABLE changes (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    op TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    origin TEXT NOT NULL DEFAULT '',
    at INTEGER NOT NULL
);
CREATE INDEX changes_entity ON changes(entity_id);
CREATE TABLE reminder_log (
    occurrence TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    fired_at INTEGER NOT NULL,
    PRIMARY KEY (occurrence, minutes)
);
"""),
    # v2 : recherche par UID iCalendar (réimport d'un .ics sans doublon, correspondance avec les identifiants iCal
    # des sources distantes).
    (2, """
CREATE INDEX ev_uid ON events(calendar_id, ical_uid) WHERE ical_uid IS NOT NULL;
"""),
]

LATEST = MIGRATIONS[-1][0]

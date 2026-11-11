"""Schéma SQLite des tâches et ses migrations (`PRAGMA user_version`), appliquées par
`fm_agenda.store.database.open_database(path, MIGRATIONS, prefix="taches")`. Ne JAMAIS modifier une migration
publiée : en ajouter une nouvelle.

Tables (mêmes principes que l'agenda, voir `fm_agenda/store/schema.py`) :
- `meta`         clé / valeur (identifiant de l'appareil, préférences de l'interface) ;
- `accounts`     comptes distants (Google, pont Apple) ; AUCUN jeton ici (Gestionnaire d'identifiants Windows) ;
- `lists`        listes (source, identifiant distant, horodatage de la dernière réception `sync_cursor`) ;
- `tasks`        tâches ; suppression douce (`deleted`) tant que la source distante ne l'a pas confirmée ;
- `sync_outbox`  file persistante des envois (une entrée par tâche ou liste) ;
- `conflicts`    versions locale / distante / de base d'un conflit non résolu ;
- `changes`      journal des modifications (révision, provenance) ;
- `reminder_log` rappels déjà montrés."""

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
CREATE TABLE lists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'bleu',
    source TEXT NOT NULL DEFAULT 'local',
    account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
    remote_id TEXT,
    etag TEXT,
    sync_enabled INTEGER NOT NULL DEFAULT 0,
    sync_cursor TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    props TEXT NOT NULL DEFAULT '{}',
    deleted INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX list_remote ON lists(account_id, remote_id) WHERE remote_id IS NOT NULL;
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    list_id TEXT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
    parent_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    position REAL NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    completed_at INTEGER,
    due_date TEXT,
    due_time TEXT,
    reminder_at INTEGER,
    priority INTEGER NOT NULL DEFAULT 0,
    flagged INTEGER NOT NULL DEFAULT 0,
    url TEXT NOT NULL DEFAULT '',
    remote_id TEXT,
    etag TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    sync_state TEXT NOT NULL DEFAULT 'local',
    base TEXT,
    origin TEXT NOT NULL DEFAULT '',
    deleted INTEGER NOT NULL DEFAULT 0,
    props TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX task_list ON tasks(list_id, position) WHERE deleted = 0;
CREATE INDEX task_parent ON tasks(parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX task_due ON tasks(due_date) WHERE deleted = 0 AND due_date IS NOT NULL;
CREATE INDEX task_reminder ON tasks(reminder_at) WHERE deleted = 0 AND done = 0 AND reminder_at IS NOT NULL;
CREATE UNIQUE INDEX task_remote ON tasks(list_id, remote_id) WHERE remote_id IS NOT NULL;
CREATE INDEX task_pending ON tasks(sync_state) WHERE sync_state IN ('dirty', 'deleted', 'conflict');
CREATE TABLE sync_outbox (
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    list_id TEXT NOT NULL,
    account_id TEXT,
    created_at INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_at INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (entity, entity_id)
);
CREATE TABLE conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    list_id TEXT NOT NULL,
    detected_at INTEGER NOT NULL,
    local TEXT NOT NULL,
    remote TEXT NOT NULL,
    base TEXT,
    fields TEXT NOT NULL DEFAULT '[]',
    resolved INTEGER NOT NULL DEFAULT 0,
    resolution TEXT NOT NULL DEFAULT ''
);
CREATE INDEX conflict_open ON conflicts(task_id) WHERE resolved = 0;
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
    task_id TEXT NOT NULL,
    reminder_at INTEGER NOT NULL,
    fired_at INTEGER NOT NULL,
    PRIMARY KEY (task_id, reminder_at)
);
"""),
]

LATEST = MIGRATIONS[-1][0]

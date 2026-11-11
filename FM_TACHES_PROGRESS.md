# Suivi de mission : module Tâches (`fm_taches/`)

Plan et décisions : `docs/agents/fm_taches.md`.

## Phase actuelle

Mission TERMINÉE (2026-11-11). Phase 5 (Apple Rappels) annulée par l'utilisateur. Restent à faire PAR
L'UTILISATEUR : connexion Google réelle (étapes : `docs/agents/fm_taches.md`, « Connecter Google Tasks ») et mesure de
volume à temps perdu (`fluidite.bat`, ligne de `docs/agents/a_mesurer.md`).

## Phases

- [x] 1. Cœur + base (modèle, schéma, dépôt, `TaskService`, tests) — 16 tests, `test_taches_*.py`
- [x] 2. Interface (bouton, `TasksPane`, saisie rapide, détails, vues intelligentes, réglages) — `test_taches_ui.py`
- [x] 3. Google Tasks (OAuth partagé avec l'Agenda, client, moteur, faux serveur) — `test_taches_sync.py`
- [x] 4. Tâches datées dans l'Agenda (HOOK `tasks_due`) — `test_taches_agenda.py`
- [-] 5. Apple Rappels par Raccourci iPhone — ANNULÉE (décision de l'utilisateur, 2026-11-11)
- [x] 6. Rappels / notifications, mesures de volume, doc finale — `test_taches_reminders.py`, `test_taches_perf.py`

## Reste à faire / étapes de reprise

Rien côté code. Pistes possibles si l'utilisateur le demande : `move` entre listes Google au lieu de recréer,
recréer chez Google une liste synchronisée dont la suppression est annulée, tâches dans la vue Année et la recherche
de l'agenda, rappels appli fermée (comme l'agenda : tâche planifiée Windows).

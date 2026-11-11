"""fm_taches : module Tâches de PIPE FMZ (listes, sous-tâches, échéances), synchronisé avec Google Tasks et Apple
Rappels (Raccourci iPhone), tâches datées montrées dans l'Agenda. Doc : `docs/agents/fm_taches.md`.

Couches : `core` (sans Qt ni SQLite) -> `store` (SQLite) -> `services` (`TaskService`, seule porte de l'interface).
Réutilise sans copie la base, le fil d'écriture et les dates de `fm_agenda`."""

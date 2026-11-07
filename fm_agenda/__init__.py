"""fm_agenda : agenda personnel et professionnel de PIPE FMZ (module « Agenda » de la barre de navigation).

Couches (chacune n'importe que celles du dessous) :
- `core/`     domaine SANS Qt : dates et fuseaux, modèle (calendriers, événements), récurrences RFC 5545,
              disposition des événements simultanés, import / export iCalendar.
- `store/`    base SQLite locale (offline-first) : schéma et migrations, sauvegardes, dépôt (requêtes).
- `services/` logique fonctionnelle (Qt sans widget) : service de l'agenda (cache, écritures en fond,
              annuler / rétablir, portée des modifications d'une série), rappels.
- `sync/`     synchronisation : moteur générique (file d'opérations, conflits, provenance), adaptateur Google
              Calendar (OAuth 2.0 + PKCE, jetons dans le Gestionnaire d'identifiants Windows), interface du
              futur serveur personnel.
- `ui/`       interface Qt : thème (jetons du design Claude Design), vues peintes, panneau, dialogues.

L'interface ne connaît QUE `services.agenda.AgendaService` : ni SQLite ni Google. Le module n'importe rien de la
fenêtre principale (elle pose `ui.pane.HOOKS`). Carte détaillée : docs/agents/fm_agenda.md."""

MODULE_ID = "agenda"
MODULE_LABEL = "Agenda"

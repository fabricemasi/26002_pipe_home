# FM_AGENDA — suivi de mission (reprise après interruption)

Mission : module agenda `fm_agenda` de PIPE FMZ (cahier des charges du 2026-11-06 + directives complémentaires).
Détail technique, décisions, protocole serveur, mesures : **`docs/agents/fm_agenda.md`**.

## Phase actuelle
Phases 0 à 9 faites (audit, interface, moteur, SQLite, rappels / ICS, Google, préparation multi-appareils,
réglages, optimisation, tests). Phase 10 (finalisation) : en cours — voir « Reste à faire ».

## Architecture retenue
- `fm_agenda/core` (domaine sans Qt) · `store` (SQLite, migrations, sauvegardes) · `services` (AgendaService,
  fil d'écriture, rappels, ICS) · `sync` (interface de source distante, Google, moteur, OAuth, coffre Windows) ·
  `ui` (thème = jetons du design, vues peintes, éditeur, panneau).
- Branchement : `main_window/agenda_module.py` (bouton calendrier de la barre, cadre « Agenda », service en fond).
- Interface Qt native peinte (pas QtWebEngine : voir la doc, « Décisions »).
- Base : `%LOCALAPPDATA%\PIPE_FMZ\fm_agenda\agenda.sqlite3` (hors du dossier synchronisé), sauvegardes `backups\`.

## Référence au design
Zip Claude Design « Agenda — sombre-html.zip » (`Main.dc.html` : vues Jour / Semaine / Mois / Année, thèmes sombre
et clair, accent #3f6f9f, aujourd'hui #cc3d35). Reproduit dans `fm_agenda/ui/theme.py` (jetons) et les vues peintes ;
données de la maquette pour comparer : `tests/_agenda_demo.py`. Ajouts : vues « Travail » et « Liste », recherche,
éditeur, menus, état de synchronisation (bas du panneau latéral).

## Fonctionnalités intégrées et testées (automatiquement)
- Vues Jour (+ détails), Semaine, Travail, Mois, Année (intensité), Liste ; mini-calendrier ; prochains jours ;
  calendriers (afficher / masquer, seul, renommer, couleur, défaut, créer, supprimer, import / export .ics).
- Création (bouton, N, double-clic, tracé), modification (éditeur complet), suppression (confirmation), duplication,
  copier / coller, glisser-déposer (y compris vers un autre jour, dans le mois), durée par le bord, tâches (case),
  couleur, catégories, lieu, lien, projet, dossier (« Ouvrir le dossier » -> colonnes), participants, rappels,
  disponibilité, statut, notes, fuseau.
- Récurrences RFC 5545 (jours, jours ouvrés, semaines, mois N / n-ième jour / dernier, ans, personnalisée, fin date
  / nombre / jamais) ; portée « cette occurrence / suivantes / toute la série » ; exceptions ; changements d'heure.
- Annuler / rétablir (Ctrl+Z / Ctrl+Y, cadre de la barre) ; raccourcis ; recherche ; Échap ne ferme jamais.
- SQLite : transactions, WAL, migrations (v1 -> v2 testée avec sauvegarde), sauvegarde quotidienne + rotation,
  récupération après corruption (base mise de côté, sauvegarde restaurée), persistance après relance.
- Rappels : dus une fois (même après relance), rattrapage des manqués, report, séries, journée ; notification
  Windows (zone de notification) + fenêtre de rappel.
- Google (faux serveur) : réception complète / incrémentale, pagination, 410, envoi minimal (PATCH), aucun doublon
  (réponse perdue), conflits (fusion 3 voies, conservation, résolution), hors ligne (file persistante), quotas,
  jeton expiré / révoqué, droits (lecture seule, droits retirés), séries + exceptions + occurrences annulées.
- Réglages « Agenda » (5 sections, appliqués en direct) ; état de la synchronisation dans le panneau latéral.
- Curseur « Largeur de l'agenda » dans la barre d'état (agenda ouvert seulement ; `agenda_width`, contenu centré),
  ajouté le 2026-11-06 à la demande de l'utilisateur.

## Tests
`python tests/run.py fm_agenda` : 8 fichiers, ~79 tests rapides, tous verts (2026-11-06).
`python tests/run.py fm_agenda --lent` : + appli complète (`test_agenda_app.py`, 2 tests dont la préparation sur
inactivité) et volumes (`test_agenda_perf.py`), verts. Non-régression vérifiée : `test_pdf_app` (lent),
`test_pdf_settings`, `test_settings_window_v2` (un test qui énumère les fenêtres de réglages par module, complété),
`test_navigation_bar`, `test_md_editor`, `test_inspector_resize`, `test_theme_status_bar`.
Échec SANS LIEN constaté : `test_viewer_buttons.test_ctrl_drag_moves_a_button_and_keeps_the_order` (« sp1 absent de
Sous-projet ») échoue aussi agenda désactivé — non examiné (règle : signaler seulement).

## Performances mesurées (50 000 événements)
Semaine 26 ms à froid / 0,2 ms en cache ; changement de semaine 33 ms ; peinture 20 ms ; glisser 22 ms par
mouvement ; éditeur 5 ms ; création visible 1,6 ms (disque 2,3 ms) ; cache 12 mois 5,3 Mo. Tableau complet : doc.
Premier clic sur « Agenda » : panneau préparé pendant l'inactivité (imports dans un fil de fond) -> ~10 ms.

## État de la connexion Google
Code complet (OAuth 2.0 + PKCE, coffre Windows, API v3, moteur) et testé contre un faux serveur. **Aucune connexion
réelle n'a été faite** : il faut un identifiant OAuth « Application de bureau » de l'utilisateur (étapes : doc,
« Connecter Google Agenda »).

## Problèmes connus / limitations
- Fuseau de Windows de cette machine = Est des États-Unis (UTC-5) : si besoin, Réglages : Agenda > Données >
  Fuseau horaire = Europe/Paris.
- Notification Windows et fenêtre de rappel non vues à l'écran (tests hors écran).
- Rappels appli fermée : étudiés, non installés (tâche planifiée Windows à créer avec l'accord de l'utilisateur).
- RDATE ignorées ; VTIMEZONE non écrit ; pas de réponse aux invitations ; restauration de sauvegarde manuelle ;
  raccourcis non personnalisables (liste dans Réglages : Agenda > Comportement).

## Problèmes corrigés pendant la mission
Titre tronqué par une barre trop chargée (vues renommées, priorité au titre, mode compact) ; recherche qui prenait
le focus à l'ouverture ; chemin du dossier coupé dans les détails ; minuteurs visant un panneau détruit ;
préchargement après fermeture de la base ; état « Synchronisation… » bloqué (compteur de tâches) ; premier clic
lent (153 ms : 76 feuilles de style, imports réseau) ; fenêtre des conflits sur fond clair ; champs d'actions des
réglages trop larges ; bascule « journée » -> horaire qui laissait une fin égale au début.

## Reste à faire / étapes de reprise
1. Avec l'utilisateur : importer le JSON OAuth, connecter Google, vérifier un aller-retour réel (créer ici -> voir
   dans Google ; modifier dans Google -> « Synchroniser maintenant »).
2. Voir une notification de rappel à l'écran (créer un événement dans 6 min avec un rappel de 5 min).
3. Rien n'est commité (le dépôt porte d'autres travaux) : demander avant de commiter.

## Commandes
- Lancer : `pipeline_browser_debug.bat` (installe aussi python-dateutil et tzdata) ; bouton calendrier de la barre.
- Tests : `python tests/run.py fm_agenda` ; `python tests/run.py fm_agenda --lent -v` (tableau des mesures).

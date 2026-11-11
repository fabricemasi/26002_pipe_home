# Module Tâches (`fm_taches/`)

Gestionnaire de tâches de PIPE FMZ : bouton « Tâches » de la barre de navigation, vue plein cadre (comme l'Agenda),
synchronisé avec **Google Tasks**, tâches datées montrées dans l'**Agenda**, rappels. Choix de l'utilisateur
(2026-11-11) : module séparé + affichage dans l'Agenda ; Apple Rappels prévu puis abandonné ; plan validé avant
construction. Suivi de mission : `FM_TACHES_PROGRESS.md`.

**État : TERMINÉ (2026-11-11) : cœur, base, interface, réglages, synchronisation Google Tasks (testée contre
un faux serveur ; connexion RÉELLE à valider par l'utilisateur), tâches datées dans l'Agenda, rappels. Apple
Rappels abandonné (décision de l'utilisateur).**

**Tests** (module `fm_taches` du lanceur de tests) ; par nom : `PYTHONPATH="tests;." python -m unittest
test_taches_core test_taches_service test_taches_ui test_taches_sync test_taches_agenda test_taches_reminders`
(41 tests, ~1,5 s ; faux serveur Google Tasks : `tests/_fake_gtasks.py`). Volume (LENT, à temps perdu, noté dans
`a_mesurer.md`) : `test_taches_perf.py` (10 000 tâches ; `-v` affiche le tableau).

## Carte : responsabilité -> fichier

Même découpage en couches que `fm_agenda` (voir `fm_agenda.md`) : l'interface ne connaît QUE `TaskService`.

| Fichier | Responsabilité |
|---|---|
| `core/model.py` | `TaskList` (source : `local`, `google:<compte>`, `apple`), `TaskRecord`, `new_id()` |
| `core/ordering.py` | Positions fractionnaires (insérer entre deux tâches sans renuméroter), arbre parent / sous-tâches |
| `core/quickadd.py` | Saisie rapide : « Appeler Paul demain 14h #Studio !! * » -> titre, échéance, heure, liste, priorité, marquée ; un nombre seul n'est jamais une heure (« Plan 12 ») ; « lundi » = le prochain, jamais aujourd'hui |
| `core/smart.py` | Vues intelligentes : Aujourd'hui (en retard compris), En retard, Planifiées, Marquées, Toutes, Terminées |
| `store/schema.py`, `store/repository.py` | Schéma SQLite + migrations ; écriture des lignes (UPSERT, jamais `INSERT OR REPLACE` : il supprimerait les tâches d'une liste par la cascade), file d'envoi, journal `changes`, rappels montrés |
| `store/database.py` | Emplacement (`FM_TACHES_DIR` en test) ; ouverture = `fm_agenda.store.database` paramétré (`migrations`, `prefix="taches"`) |
| `services/reminders.py` | `TaskReminders` : rappels (calcul par index, une fois, manqués, report), notification Windows + fenêtre de rappel |
| `services/tasks.py` | `TaskService` : TOUTES les tâches en mémoire (index par liste et par échéance), modifications en mémoire puis fil d'écriture (`fm_agenda.services.writer.DbWriter(conn, repo=…)`), commandes annulables `(genre, id, avant, après)`, `create_task` / `update_task` / `set_done` (coche aussi les sous-tâches) / `delete_tasks` / `move` / `indent` / `outdent`, listes, `tasks_of` (en cache par liste), `smart`, `due_between` (Agenda), `search`, `counts`, sauvegarde quotidienne. Signal `changed(listes touchées)` |
| `sync/mapping.py` | Correspondance des champs (date seule pour `due`, `status` + `completed`), `base` (état commun, en termes locaux : `_list`, `_parent`, `_pos`), champs changés, déplacement |
| `sync/google_tasks.py` | Client Google Tasks v1 (listes, tâches, `move`) : sous-classe de `fm_agenda.sync.google.GoogleProvider` (racine `api`) ; `TasksTokenSource` (coffre `taches/google/<compte>`) ; portées `SCOPES` |
| `sync/engine.py` | Fil de synchronisation, LECTURE SEULE de la base : listes (envoi, nouvelles, disparues), réception `updatedMin`, envoi de la file (parents d'abord, `move`, `PATCH` des seuls champs changés) -> `SyncResult` |
| `sync/merge.py` | Fil de l'interface : fusion du `SyncResult` (création, écho par `etag`, trois voies, suppressions, résultats d'envoi) -> `TaskService.apply_sync` |
| `sync/manager.py` | `TasksSyncManager` : fil, minuteries (`taches_sync_*`), connexion OAuth (`connect_google`), déconnexion, `status_text` ; le passage suivant attend la fusion du précédent (`_applied`) |
| `ui/settings_fields.py` | Champ « Google Tasks » de Réglages : Tâches > Synchronisation (identifiant OAuth, connecter, synchroniser, déconnecter) |
| `ui/theme.py` | Thème de l'agenda réglé par `taches_theme` / `taches_accent` / `taches_density` + métriques des lignes ; texte des échéances (`due_text`) |
| `ui/pane.py` | `TasksPane` : barre du haut (titre, recherche, thème, « Nouvelle tâche »), saisie rapide (`QuickAdd`), vues / listes / recherche (`refresh`), actions clavier, menus contextuels, listes (créer, renommer, couleur, supprimer), `HOOKS` |
| `ui/tasklist.py` | `TaskListView` PEINTE (seules les lignes visibles), sélection (Ctrl / Maj), édition en place (renommer, ligne de saisie continue), Ctrl + glisser (avant / après / dans), clavier |
| `ui/sidebar.py` | Panneau latéral PEINT : vues intelligentes + nombre, « Mes listes » + « + » |
| `ui/details.py` | Détails (titre, notes, échéance + heure + raccourcis, priorité, marquée, liste, lien, sous-tâches, dates) en briques fm_theme (`fm_agenda.ui.kit`) |
| `settings.py`, `settings_defaults.py`, `runtime.py` | Catalogue « Tâches : Affichage / Comportement / Données », défauts `taches_*` (déclarés dans `settings_store.py`), service en cours pour les champs des réglages |
| `main_window/tasks_module.py` | Bouton « Tâches » (icône `taches` peinte dans `preview_column.IconButton`), cadre « Tâches » de la barre (annuler, rétablir, panneau latéral, détails, réglages, fermer), service + panneau préparés en fond pendant l'inactivité, `_leave_taches` (appelé par les autres modules), fermeture |

Réutilisé de `fm_agenda` (aucune copie) : `sync/oauth.py`, `sync/http.py`, `sync/credentials.py`,
`store/database.py`, `services/writer.py`, `core/timeutil.py`, `ui/theme.py`, `ui/widgets.py` (boutons, cases), `ui/kit.py` (briques des réglages).
Changement nécessaire : `oauth.authorize(..., scopes=...)` au lieu de la constante `SCOPES` seule.

## Décisions (et pourquoi)

- **Base SQLite hors du dossier synchronisé** (`%LOCALAPPDATA%\PIPE_FMZ\fm_taches\taches.sqlite3`) : même raison
  que l'Agenda (un client cloud corrompt une base WAL copiée à moitié).
- **Modèle = sur-ensemble des deux sources** : titre, notes, statut, date de fin, échéance (date + heure
  facultative), rappel, priorité (0-3), marquée, URL, parent, position, liste. Un champ que la source ignore reste
  local (`props`) et n'est jamais effacé par une synchro. Google Tasks n'a qu'une DATE d'échéance (l'heure est
  ignorée par l'API) et un seul niveau de sous-tâches : l'interface le signale sur les listes Google.
- **Google : même identifiant OAuth que l'Agenda** (JSON importé une seule fois, `google/client`), portée
  `https://www.googleapis.com/auth/tasks`, jeton d'actualisation à part
  (« PIPE_FMZ/fm_taches/google/<compte> ») : connecter / déconnecter les tâches ne touche pas l'Agenda.
- **Google Tasks n'a pas de `syncToken`** : réception par `updatedMin` = heure serveur de la dernière réception
  moins 1 min de marge, avec `showDeleted` et `showHidden` ; écho de notre propre envoi reconnu à l'`etag`.
- **Agenda sans dépendance** : l'Agenda n'importe pas `fm_taches` ; voir « Tâches dans l'Agenda » ci-dessous.
- **Glisser une tâche (réordonner, changer de liste, sous-tâche)** : Ctrl + glisser (règle de l'appli) ; réglage
  `taches_drag_requires_ctrl` si l'utilisateur préfère sans Ctrl.
- **Fluidité** : liste peinte (modèle / délégué), lectures indexées par liste, écritures dans le fil dédié ; cible
  10 000 tâches : changement de liste < 15 ms, cocher visible < 2 ms.
- **Aspect** : jetons de `fm_agenda/ui/theme.py` (les deux modules se ressemblent) ; fenêtres et champs en
  briques des réglages. Pas de maquette fournie : une maquette Claude Design pourra remplacer la mise en page.

- **Mémoire = référence, pas de cache par période** (différent de l'Agenda) : les tâches sont peu nombreuses et
  sans répétition ; tout charger une fois rend chaque lecture immédiate. Un échec d'écriture recharge la base.
- **Profondeur** : `max_depth` = 1 pour une liste Google ou Apple (un seul niveau de sous-tâches), illimitée en
  local ; `create_task` / `move` refusent au-delà (message).
- **Suppression d'une liste synchronisée** : liste marquée supprimée + envoyée ; ses tâches supprimées en douceur.
  À traiter en phase 3 : annuler cette suppression doit recréer la liste à distance (identifiants distants périmés).

## Interface (phase 2)

- Vues : Aujourd'hui (en retard compris), Planifiées, Marquées, Toutes, Terminées ; une liste ; une recherche
  (titre et notes, 120 ms après la frappe). Vue rouverte = la vue quittée (`taches_start_view`), gardée dans la
  base (`pref:view`) comme les sous-tâches repliées (`pref:collapsed`) et la largeur du panneau latéral.
- Saisie rapide en haut de la liste (Ctrl+N) : dans Aujourd'hui / Planifiées, une tâche sans date prend la date du
  jour (sinon elle disparaîtrait de la vue) ; dans Marquées, elle est marquée. Liste visée : `#nom`, sinon la liste
  ouverte, sinon la liste par défaut.
- Dans une liste : Entrée ouvre une ligne de saisie après la tâche sélectionnée ; Entrée la valide et en rouvre
  une (saisie continue, comme Rappels) ; Échap l'abandonne ; rien n'est créé avant Entrée.
- Cocher plusieurs tâches = une commande par tâche (annulables une à une). Supprimer une tâche à sous-tâches ou
  plusieurs tâches demande confirmation (`taches_confirm_delete`).
- Panneaux : latéral (Ctrl+B) rangé sous 640 px de contenu, détails (Ctrl+I) sous 900 px.
- Thème clair : les champs du panneau de détails gardent l'aspect de l'appli (briques fm_theme), comme l'éditeur
  de l'agenda.

## Mesures (2026-11-11, 10 000 tâches sur 20 listes, offscreen ; refaites par `test_taches_perf.py`)

Dans l'appli (fenêtre entière, base presque vide) : premier clic sur « Tâches » à froid 109 ms (service + panneau ;
normalement déjà préparés en fond 4 s après le lancement), réouverture 3 ms.

Ouverture du service 125 ms (à faire en fond, comme l'Agenda, en phase 2) ; liste de 500 tâches 1,1 ms à froid,
0,003 ms en cache ; cocher (visible) 0,4 ms ; semaine de l'Agenda 0,08 ms, année 4 ms ; vue Aujourd'hui 1,8 ms ;
compteurs 2,2 ms ; recherche 2,3 ms.

## Apple Rappels : ABANDONNÉ (décision de l'utilisateur, 2026-11-11)

L'étape 5 (pont par Raccourci iPhone et fichiers iCloud Drive) est annulée. Raison technique gardée pour mémoire :
depuis iOS 13, les listes Rappels ne passent plus par CalDAV et Apple n'offre aucune API sous Windows ; seul un
Raccourci iPhone écrivant / lisant des fichiers dans iCloud Drive aurait pu servir de pont (identifiant stable d'un
rappel non garanti dans Raccourcis). La source `apple` du modèle reste prévue mais rien ne l'utilise.

## Rappels (phase 6)

- `services/reminders.py` (`TaskReminders`, démarré par `main_window/tasks_module._start_taches_reminders`, module
  ouvert ou non) : rappel choisi (`reminder_at`, champ « Rappel » des détails : à l'échéance, 15 min / 1 h avant,
  la veille à 9:00, dans 1 heure, demain à 9:00, retirer), sinon l'heure d'une tâche à heure
  (`taches_remind_at_due`). Tâches à faire seulement ; local (Google Tasks n'a pas de rappel).
- Calcul par les index du service (`reminder_candidates` : tâches à rappel `_by_reminder` + échéances par date),
  toutes les 30 s et au déclenchement exact ; une seule fois par rappel (`reminder_log` + `_fired` en mémoire,
  8 jours) ; manqué au lancement jusqu'à `taches_missed_minutes`.
- Notification Windows et / ou fenêtre de l'appli (Ouvrir, Terminer, +N min, Fermer), `taches_notify_mode`.
  « Ouvrir » = module Tâches sur la tâche. Appli fermée : aucun rappel (comme l'agenda).
- Liste : « Rappel jj/mm hh:mm » sous le titre d'une tâche à faire qui en a un.

## Tâches dans l'Agenda (phase 4)

- La fenêtre principale pose trois HOOKS sur `fm_agenda/ui/pane.py` (`_install_agenda_hooks`) : `tasks_due(début,
  fin)` -> dictionnaires simples (`main_window/tasks_module._taches_due_for_agenda`, index par date du service),
  `toggle_task(id)`, `open_task(id)` (ouvre le module Tâches sur la tâche : `TasksPane.reveal`).
- Dans l'agenda, TOUTES les lectures du panneau passent par `AgendaPane._occurrences` (service + tâches) : les
  tâches deviennent des `Occurrence.external_task` (clé « tache:<id> », lecture seule) et profitent de tout
  l'affichage existant : bande « Journée » (sans heure), ligne de tâche à l'heure (avec heure, durée nulle comme
  les tâches de l'agenda), Mois, Liste, prochains jours et points du mini-calendrier. Couleur = celle de la liste.
- Gestes : case = cocher (aussi dans la bande Journée, ajoutée pour l'occasion : `paint_bar(task=, done=)`, 22 px
  cliquables), double-clic / Entrée / « Ouvrir dans Tâches » = module Tâches ; jamais glissée, dupliquée, copiée
  ni supprimée par l'agenda (message).
- Rafraîchissement : `changed` / `listsChanged` du service des tâches -> `AgendaPane._schedule` seulement si
  l'agenda est visible (il se rafraîchit de toute façon à l'ouverture). Le service des tâches n'est jamais démarré
  POUR l'agenda : préparé en fond 4 s après le lancement, ses tâches arrivent dès qu'il est prêt.
- Réglage `agenda_show_tasks` (Réglages : Agenda > Affichage). Pas dans la vue Année ni la recherche de l'agenda.

## Synchronisation Google Tasks (phase 3)

- **Qui écrit quoi** : le fil de synchronisation ne fait que lire la base (après `writer.flush`) et parler à
  Google ; la fusion se fait dans le fil de l'interface, l'écriture dans le fil d'écriture (`apply_sync` : jamais
  annulable, jamais renvoyé). Le passage suivant attend la fusion du précédent : sinon il relirait une base sans
  les identifiants Google tout juste reçus et RECRÉERAIT les tâches (doublons).
- **Identité** : `remote_id` Google par tâche ; écho de notre propre envoi = même `etag` -> ignoré.
- **Ordre** : position Google (« 000…03 ») convertie en nombre local du même ordre ; une tâche créée ici part avec
  `parent` / `previous` (sœur précédente déjà chez Google) ; un déplacement local = `move`.
- **Modifiée des deux côtés** (même passage) : pas envoyée ; fusionnée à trois voies contre `base` ; le passage
  suivant est relancé 1,5 s après. Champ changé des deux côtés : `taches_conflict_policy` (récent / Google / local).
- **Supprimée ici, encore reçue** : ignorée (la suppression part dans le même passage) — sinon recréée et collision
  sur l'index unique `(list_id, remote_id)` (piège trouvé par les tests).
- **Supprimée chez Google mais modifiée ici** : recréée chez Google. **Liste disparue chez Google** : devient locale.
  **Déconnexion** : listes gardées en local (ou retirées, au choix).
- **Liste locale -> Google** : menu de la liste > « Envoyer vers Google Tasks » (`publish_list` ; les niveaux de
  sous-tâches au-delà du premier sont remontés, après confirmation). Repère « G » des listes Google dans le panneau.
- **Hors ligne en route** : ce qui est déjà envoyé est rapporté (sinon doublon), le reste attend dans `sync_outbox` ;
  un échec non réseau repousse l'entrée (30 s -> 1 h).
- Non fait : annuler une suppression de LISTE synchronisée ne la recrée pas chez Google ; une tâche déplacée vers
  une autre liste Google est recréée (supprimée de l'ancienne) au lieu d'un `move` entre listes.

## Connecter Google Tasks (actions de l'utilisateur, une fois)

1. Dans le projet Google Cloud déjà créé pour l'Agenda (sinon : étapes de `fm_agenda.md`, « Connecter Google
   Agenda ») : « API et services » > « Bibliothèque » > activer **Google Tasks API**.
2. PIPE FMZ > Tâches > engrenage (Réglages : Tâches) > Synchronisation : **Importer l'identifiant OAuth…** (si ce
   n'est pas déjà fait pour l'Agenda : le même fichier sert aux deux), puis **Connecter Google Tasks…** : le
   navigateur s'ouvre, accepter ; les listes Google arrivent dans « Mes listes » (repère « G »).

Portées demandées : `tasks`, `openid email`. En mode « En test », Google expire le jeton au bout de 7 jours
(voir `fm_agenda.md`).

# Module Agenda (`fm_agenda/`)

Agenda personnel et professionnel de PIPE FMZ : bouton « Agenda » de la barre de navigation (icône calendrier),
plein cadre (les colonnes sont masquées), cadre « Agenda » de la barre (annuler, rétablir, panneau latéral,
réglages, fermer). Design de référence : maquette Claude Design « Agenda — sombre » (`Main.dc.html`, fournie en
zip le 2026-11-06, thèmes sombre et clair). Suivi de mission : `FM_AGENDA_PROGRESS.md`.

**Tests** : `python tests/run.py fm_agenda` (rapides, ~5 s ; barres longues : `test_agenda_longbars.py`, < 1 s) ;
`--lent` ajoute l'appli complète
(`test_agenda_app.py`) et les mesures de volume (`test_agenda_perf.py`, ~15 s, `-v` affiche le tableau).

## Carte : responsabilité -> fichier

Couches : chaque couche n'importe que celles du dessous. L'interface ne connaît QUE `AgendaService`.

| Fichier | Responsabilité |
|---|---|
| `core/timeutil.py` | Fuseaux (IANA par `zoneinfo` + `tzdata` ; fuseau de Windows lu au registre ; repli `_SystemLocal`), conversions, heures inexistantes / ambiguës (`localize`), semaines ISO, grilles de mois, libellés français, saisie libre des dates / heures |
| `core/model.py` | `Calendar`, `EventRecord` (simple, maître de série, exception), `Attendee`, `Occurrence` (affichée, `__slots__`), `new_id()` (UUID hexa) |
| `core/recurrence.py` | RRULE (lecture / écriture / description française), déroulement en heure murale (dateutil), saut rapide des règles jour / semaine, fin de série, découpe « cette occurrence et les suivantes », choix rapides de l'éditeur |
| `core/layout.py` | Voies des événements simultanés (algorithme du design), lignes des barres « journée » |
| `core/ics.py` | iCalendar sans dépendance : lecture (repli, échappements, TZID, VALARM, RECURRENCE-ID, EXDATE, X-PIPE-*) et écriture (repli à 75 octets, CRLF) |
| `store/schema.py` | Schéma SQLite et migrations (`PRAGMA user_version` ; v1 tables, v2 index UID) |
| `store/database.py` | Emplacement, connexions (WAL, NORMAL, clés étrangères), transactions explicites, sauvegardes (API backup), rotation, témoin d'arrêt brutal + `quick_check`, mise de côté d'une base illisible + restauration. PARTAGÉ avec fm_taches (`migrations`, `prefix`, `label` en paramètres ; défauts = agenda) |
| `store/repository.py` | Requêtes : fenêtre d'affichage indexée (bornée par la durée maximale), séries, exceptions, recherche, rappels, file d'envoi, conflits, journal `changes`, méta / préférences |
| `services/writer.py` | Fil d'écriture SQLite unique (une transaction par tâche, rappels dans le fil Qt). PARTAGÉ avec fm_taches (`repo=`, `name=`) |
| `services/agenda.py` | `AgendaService` : cache par mois, modifications en mémoire puis sur disque, annuler / rétablir, portées des séries, brouillons de l'éditeur, compteurs de la vue Année, sauvegarde quotidienne |
| `services/reminders.py` | Planificateur de rappels (30 s + minuteur exact), rattrapage, report, notification Windows (zone de notification) + fenêtre de rappel |
| `services/ics_io.py` | Import (une commande annulable, mise à jour par UID, jamais de doublon) / export .ics |
| `sync/provider.py` | Interface d'une source distante + erreurs typées ; `ServerProvider` (futur serveur, non implémenté) |
| `sync/credentials.py` | Gestionnaire d'identifiants Windows par ctypes (mémoire en test) |
| `sync/oauth.py` | OAuth 2.0 application installée : navigateur du système, boucle 127.0.0.1, PKCE S256, `state`, jetons. PARTAGÉ avec fm_taches (`authorize(..., scopes=, product=)`, `TokenSource` sous-classé) |
| `sync/http.py` | Transport HTTP (urllib, TLS) ; `FM_AGENDA_NO_NETWORK` |
| `sync/google.py` | Client Google Calendar v3 (reprises exponentielles, 401 -> actualisation) et correspondance des champs. `GoogleProvider.api` = racine de l'API (fm_taches la change pour Google Tasks) |
| `sync/engine.py` | Moteur : réception incrémentale / complète, 410, envoi idempotent, fusion à trois voies, conflits, provenance |
| `sync/manager.py` | Pilote Qt : fil de synchronisation, minuteries, comptes, état, conflits |
| `ui/theme.py` | SOURCE UNIQUE de l'aspect : jetons du design (sombre relu dans `M` de fm_theme, clair), couleurs d'événements, polices, métriques |
| `ui/widgets.py`, `ui/painting.py` | Briques peintes du design (`.btn`, `.grp`, `.seg`, `.search`, icônes) ; blocs / barres / pastilles d'événements |
| `ui/timegrid.py` | Jour / Semaine / Travail : en-têtes, bande « Journée », grille défilante, gestes (création, glisser, durée) ; état des barres longues (survol, épinglé, glisser des poignées) |
| `ui/longbars.py` | Événements longs en barres fléchées, SANS état : tracé coté (`round_path`, `build_seg`), relief, zones des poignées, encart (`layout_popover`, `paint_popover`), texte des horaires |
| `ui/monthview.py`, `ui/yearview.py`, `ui/listview.py` | Mois, Année (intensité), listes (panneau latéral, Liste, résultats de recherche) |
| `ui/sidebar.py`, `ui/details.py` | Mini-calendrier, prochains jours, calendriers ; détails de la vue Jour |
| `ui/editor.py`, `ui/dialogs.py`, `ui/kit.py` | Éditeur (fenêtre additionnelle + tableau des réglages), règle personnalisée, conflits ; briques fm_theme |
| `ui/pane.py` | `AgendaPane` : assemblage, navigation, recherche, raccourcis, menus contextuels, `HOOKS` |
| `ui/settings_fields.py` | Champs d'actions des réglages (compte Google, données) |
| `settings.py`, `settings_defaults.py`, `runtime.py` | Catalogue « Agenda : … », défauts `agenda_*`, service en cours pour les champs des réglages |
| `main_window/agenda_module.py` | Branchement dans la fenêtre principale (bouton, cadre, service en fond, fermeture) |

## Décisions (et pourquoi)

- **Qt natif PEINT, pas QtWebEngine** : le design est un mockup React simple (grilles CSS) ; le reproduire en
  widgets peints donne la même fidélité, un glisser à ~10-20 ms par mouvement à 50 000 événements, aucune page web
  de ~100 Mo en mémoire, l'accès direct au service et aux briques fm_theme (éditeur, menus, confirmations).
  QtWebEngine aurait imposé un pont JS <-> Python pour chaque geste et doublé le thème.
- **Base hors du dossier du projet** (`%LOCALAPPDATA%\PIPE_FMZ\fm_agenda\agenda.sqlite3`) : le projet est dans un
  dossier synchronisé par un client cloud, qui corrompt une base SQLite en WAL copiée à moitié.
- **Écritures dans un fil dédié, lectures dans le fil de l'interface** : une lecture indexée d'un mois prend 10 à
  60 ms à 50 000 événements, servie ensuite par le cache (0,2 ms) ; une écriture n'attend jamais le disque
  (visible en ~1,5 ms, écrite en ~2,3 ms). `_pending` garde la modification jusqu'à la confirmation du fil ; un
  échec d'écriture l'annule et le signale.
- **Thème sombre = palette `M`** (le design en dérive) : l'agenda suit fm_theme ; le clair garde les valeurs du
  design. Fenêtres (éditeur, conflits, confirmations, menus) : briques des réglages (règle de l'appli).
- **Glisser un événement SANS Ctrl** (exception à la règle « Ctrl + glisser » de l'appli, comme le contenu des
  canevas) : c'est le geste principal d'un agenda et la demande expresse de la mission. Réglage
  `agenda_drag_requires_ctrl` pour appliquer la règle de l'appli.
- **Clics de la maquette** : clic sur un jour du mois = vue Jour (design) ; clic sur un événement de la semaine =
  sélection (le design ouvrait le jour ; réglage `agenda_week_click`). Vue « Liste » et « Travail » ajoutées au
  choix de vue (libellés courts pour garder la barre d'une ligne).
- **Grille 0 h – 24 h défilante**, ouverte à 8 h (la maquette montre 8 h – 20 h : réglage `agenda_limit_hours`).
- **Largeur de l'agenda** (demande de l'utilisateur, 2026-11-06) : curseur dans la BARRE D'ÉTAT, montré seulement
  agenda ouvert à la place du texte de droite (comme celui des marges du module Markdown), créé à la première
  ouverture (`AgendaModuleMixin._show_agenda_width_slider`). Réglage `agenda_width` (% de la place, 30 – 100,
  aussi dans Réglages : Agenda > Affichage) ; contenu centré, jamais sous `AgendaPane.MIN_CONTENT` (600 px) ; bords
  peints du fond de l'agenda + filet (`paintEvent` : le fond QSS du panneau n'est pas garanti là). Glisser ne
  change que les marges (`set_width_percent`) ; enregistré 300 ms après le geste (`save_live_state` + preset par
  défaut + fenêtre de réglages ouverte), comme le curseur Markdown. Sous 700 px de contenu, le panneau latéral se
  range (même règle qu'une fenêtre étroite). Mesure (fenêtre 1600 px) : 11,6 ms par pas, mise en page + peinture.
- **Événements longs en barres fléchées** (demande de l'utilisateur, 2026-11-07, maquette Claude Design v10 +
  cote dessinée) : à partir de `agenda_long_threshold` h (4 par défaut ; `agenda_long_bars` pour revenir aux
  blocs), un événement horaire est une barre SANS texte collée au bord gauche de la colonne, d'épaisseur
  `agenda_bar_width` (10 px) ; chevron à 45° en haut, POINTE sur l'heure de début, et en bas en miroir, pointe sur
  l'heure de fin ; `agenda_arrow_width` (9 px) = du flanc de la barre à la pointe ; arrondis flèche / 5 (coins,
  creux) et flèche / 10 (pointes) ; passage de minuit = bords droits. Relief discret (liseré clair haut-gauche,
  sombre bas-droite, ombre légère) : chemins calculés à la DISPOSITION (`build_seg`, opérations booléennes), la
  peinture ne fait que remplir. Blocs décalés à droite des barres (voies de `lane_width` = T + A + 3). Un événement
  horaire de plus de 24 h reste dans la grille (barre) au lieu de la bande « Journée » quand l'option est active.
  Encart (titre, horaires + durée, calendrier · projet) : au SURVOL à la hauteur du curseur, qui le suit (seuls
  l'ancien et le nouvel encart sont repeints), retiré dès que le curseur quitte la forme ; au CLIC épinglé (× ;
  « Ouvrir la journée » en Semaine), reclic = retiré et pas de survol avant d'avoir quitté la barre ; Échap le
  retire. Poignées (traits sur les pointes, trois points au milieu de l'événement) : début, fin, décaler, au pas
  `agenda_snap_minutes`, vers un autre jour en Semaine, 30 min au moins ; fantôme + encart en direct, puis
  `moveRequested` (annuler / série comme tout déplacement). Le corps de la barre ne se glisse pas (maquette).
- **Journée** : un rappel compte à partir de 9:00 le jour même.
- **Invitations** : la synchronisation n'envoie aucun courriel (`sendUpdates=none`).
- **Tâches du module Tâches** (2026-11-11) : HOOKS `tasks_due` / `toggle_task` / `open_task` du panneau ; toutes
  les lectures du panneau passent par `AgendaPane._occurrences` (service + `Occurrence.external_task`, clé
  « tache:<id> », lecture seule, `occ.external`). Bande « Journée » : case des tâches (`paint_bar(task=, done=)`,
  clic dans les 22 px de gauche = cocher), aussi pour les tâches de l'agenda. Réglage `agenda_show_tasks`.
  Détail : `fm_taches.md`, « Tâches dans l'Agenda ».

## Connecter Google Agenda (actions de l'utilisateur, une fois)

1. https://console.cloud.google.com/ : créer un projet (ex. « PIPE FMZ »).
2. « API et services » > « Bibliothèque » : activer **Google Calendar API**.
3. « Écran de consentement OAuth » : type **Externe**, statut **En test**, ajouter son adresse Google en
   **utilisateur test** (pas de validation Google nécessaire pour un usage personnel).
4. « Identifiants » > « Créer des identifiants » > **ID client OAuth** > type **Application de bureau** ;
   télécharger le JSON (`client_secret_….json`).
5. PIPE FMZ > Agenda > engrenage (Réglages : Agenda) > Synchronisation : **Importer l'identifiant OAuth (JSON)…**,
   puis **Connecter Google Agenda…** : le navigateur s'ouvre, accepter ; les calendriers arrivent (cases pour
   choisir ceux à synchroniser).

Portées demandées : `calendar.events` (lecture / écriture des événements), `calendar.readonly` (liste des
calendriers), `openid email` (adresse du compte). Jeton d'actualisation : Gestionnaire d'identifiants Windows
(« PIPE_FMZ/fm_agenda/google/<compte> ») ; jeton d'accès en mémoire. En mode « En test », Google expire le jeton
d'actualisation au bout de 7 jours : « Publier » l'application (sans validation pour un seul utilisateur, avec un
avertissement « appli non validée » au consentement) évite de reconnecter chaque semaine.

## Synchronisation : règles

- Passage par calendrier activé : réception (jeton `syncToken`, pages, une transaction par page) puis envoi (file
  `sync_outbox`, un élément par événement, attente exponentielle 30 s -> 1 h en cas d'échec réseau).
- Première synchronisation / jeton périmé (410) : liste complète sur `PAST_DAYS` (730 j) ; seules les copies
  PROPRES absentes sont supprimées ; une ligne modifiée localement n'est jamais effacée.
- Identité : `events.id` = UUID local ; `remote_id` par calendrier ; création envoyée sous l'id local (409 =
  déjà créé -> relu) ; exceptions = instance Google `<maître>_<YYYYMMDDTHHMMSSZ>` (PATCH) ; écho de notre envoi
  (même etag) ignoré.
- Envoi minimal : PATCH des seuls champs changés depuis la base (`base`), `If-Match: etag` ; 412 -> relecture +
  fusion. Les champs inconnus de l'agenda (visioconférence, pièces jointes) restent intacts côté Google.
- Conflits : fusion à trois voies par groupes (horaire, répétition, titre…) ; politique « ask » (défaut) : la
  version locale reste, les deux sont enregistrées (`conflicts`), l'envoi attend ; Réglages > Synchronisation >
  Conflits… compare et tranche. Suppression d'un côté / modification de l'autre : conflit aussi.
- Droits : calendrier `reader` = lecture seule partout (éditeur, glisser, menus) ; droits retirés à distance ->
  calendrier gardé en lecture seule (`props.removed`).
- Provenance (anti-boucles) : ce qui vient de Google est écrit avec `origin = "google:<compte>"` et n'entre jamais
  dans la file d'envoi ; le journal `changes` garde l'origine de CHAQUE modification.

## Futur serveur personnel (Raspberry Pi) et iPhone — protocole prévu (non codé)

- Serveur : API REST (FastAPI) + PostgreSQL ; tables `calendars`, `events`, `changes` du schéma actuel (types
  simples, clés UUID, epoch) ; une table `replicas` (appareil, dernière révision reçue).
- Identité : l'UUID local d'un événement est GLOBAL (créé une fois, sur l'appareil d'origine). `version` =
  compteur de modifications ; `origin` = `device:<id>`, `google:<compte>`, `server`.
- Échanges : `GET /v1/agenda/changes?since=<rev>&exclude_origin=device:<id>` (les changements des autres) ;
  `PUT /v1/agenda/events/<uuid>` avec `If-Match: <version>` (409 = conflit -> fusion à trois voies comme Google).
- Anti-boucle Google -> PIPE FMZ -> serveur -> iPhone -> serveur -> Google : seul UN appareil (ou le serveur) est
  « propriétaire » d'un compte Google (`accounts.settings.sync_owner`) ; les autres reçoivent les événements Google
  du serveur avec `origin = google:<compte>` et ne les renvoient jamais à Google ; un changement n'est jamais
  renvoyé à l'origine qu'il porte. Réplication vers le serveur : par calendrier, explicite
  (`calendars.props.replicate_to_server`).
- iPhone : même modèle (SQLite local, UUID, `version`, `origin`), synchronisé avec le serveur seulement.
- Autres bases (cinémathèque…) : même schéma de réplication (`changes` + `version` + `origin`) par base ; le
  service commun du serveur ne connaît que ces trois notions.
- Passage à PostgreSQL : schéma portable tel quel (TEXT / INTEGER, pas de type SQLite propre) ; les index
  partiels existent aussi dans PostgreSQL ; `PRAGMA user_version` -> table `schema_version`.

## Rappels appli fermée (étude, non installé)

Les rappels ne fonctionnent que PIPE FMZ ouvert. Pour l'appli fermée, deux voies : (1) une tâche planifiée
Windows (Planificateur de tâches) créée par l'agenda pour chaque rappel à venir (24 h glissantes), lançant un petit
script de notification ; (2) un processus léger lancé à l'ouverture de session (clé `Run`) qui lit la base en
lecture seule et notifie. Aucune des deux n'est installée : elle modifie la configuration de Windows et demande
l'accord de l'utilisateur.

## Mesures (2026-11-06, offscreen, `test_agenda_perf.py`)

| | 100 | 1 000 | 10 000 | 50 000 |
|---|---|---|---|---|
| ouverture de la base (ms) | 4 | 4 | 8 | 22 |
| semaine à froid / suivante en cache (ms) | 18 / 0,1 | 11 / 0,1 | 11 / 0,1 | 26 / 0,2 |
| mois à froid (ms) | 17 | 21 | 23 | 62 |
| vue Année (ms) | 52 | 58 | 57 | 85 |
| changement de semaine dans le panneau (ms) | 15 | 16 | 30 | 33 |
| peinture de la semaine / mouvement de glisser (ms) | 7 / 8 | 8 / 8 | 11 / 11 | 20 / 22 |
| ouverture de l'éditeur (ms) | 5 | 5 | 4 | 5 |
| création visible / écrite (ms) | 0,8 / 1,5 | 1,1 / 2,1 | 1,4 / 2,1 | 1,6 / 2,3 |
| cache de 12 mois (Mo) | 1,6 | 1,6 | 2,3 | 5,3 |

(50 000 = dix ans à ~14 événements par jour : 131 événements dans la semaine mesurée.) Fenêtre de réglages
« Agenda » : 45 ms à l'ouverture.

Ouverture dans l'appli : les modules de l'agenda sont importés dans un fil de fond 2,5 s après l'affichage de la
fenêtre (`_warm_agenda_imports`), puis service, panneau CACHÉ et éditeur sont préparés une étape par tick
d'inactivité (`_agenda_idle_step`, jamais pendant que l'utilisateur agit) : le premier clic sur « Agenda » montre
un panneau déjà construit (~10 ms, comme une réouverture). Construction du panneau : 30 ms (une seule feuille de
style par panneau — 76 `setStyleSheet` séparés coûtaient 47 ms) ; imports réseau (urllib, ssl, http.server)
seulement à la première synchronisation.

Piège : la feuille de la fenêtre principale pose `QWidget { background; color }` sur tout son contenu ; les couleurs
des libellés de l'agenda passent donc par des règles à nom d'objet (`#AgendaDetails QLabel#dMuted`…) dans la feuille
du panneau, pas par la palette. L'éditeur est une fenêtre SANS parent (comme les réglages) pour y échapper.

## Limites connues

- Connexion Google RÉELLE non testée ici (aucun identifiant OAuth disponible) : tout le moteur est testé contre un
  faux serveur (`tests/_fake_google.py`). À valider par l'utilisateur après les étapes ci-dessus.
- Notification Windows et fenêtre de rappel : code testé hors écran (calcul, déduplication, report) ; l'affichage
  réel n'a pas pu être vu (pas de bureau dans les tests).
- Fuseau de Windows de cette machine : **Est des États-Unis** (UTC-5) ; si l'utilisateur vit en France, régler
  Réglages : Agenda > Données > Fuseau horaire = Europe/Paris.
- Course rare : une modification locale encore en mémoire (≈ 2 ms) pendant qu'une modification Google du même
  événement est appliquée peut l'emporter sans conflit (l'etag est alors déjà le nouveau).
- RDATE (dates ajoutées à une règle) ignorées ; VTIMEZONE non écrit (TZID IANA, accepté par Google / Apple /
  Outlook récents) ; participants : pas de réponse aux invitations depuis l'agenda.
- Rappels : notification « popup » seulement ; 5 rappels au plus vers Google (limite de l'API).
- Restauration d'une sauvegarde : manuelle (fermer PIPE FMZ, copier `backups\agenda-….sqlite3` sur
  `agenda.sqlite3`).

## PASSATION

- Ouvrir : bouton calendrier de la barre. Base : `%LOCALAPPDATA%\PIPE_FMZ\fm_agenda\` (sauvegardes dans
  `backups\`, une par jour, 14 gardées).
- Ajouter un réglage : défaut dans `settings_defaults.py` + `Spec` dans `settings.py` ; il arrive EN DIRECT par
  `AgendaPane.apply_settings` (préfixe `agenda_` de `settings_link`).
- Changer l'aspect : `ui/theme.py` seulement (jetons, couleurs, métriques).
- Nouvelle source distante : implémenter `sync/provider.RemoteProvider` ; le moteur ne change pas.
- Données de la maquette (captures, tests d'interface) : `tests/_agenda_demo.py`.

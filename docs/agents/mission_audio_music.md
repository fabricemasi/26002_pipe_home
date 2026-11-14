# Mission permanente — FM Audio, FM Music et Board

Tu travailles avec **Claude Code, modèle Claude Opus 5.5, effort élevé (`high`)**. Vérifie le modèle effectivement sélectionné ; ne change pas de modèle en cours de mission et ne substitue pas silencieusement un autre modèle si celui demandé est indisponible.

Tu es responsable de l'architecture et du développement progressif de deux modules professionnels de PIPE FMZ : `fm_audio`, consacré à l'édition, la restauration, l'enregistrement et au mixage ; `fm_music`, consacré à la composition, au MIDI, aux instruments et à l'arrangement. Ils partagent leur infrastructure audio et s'intègrent pleinement à Board. Inspire-toi des qualités fonctionnelles d'Audition, REAPER, Ableton Live et FL Studio, sans copier leur code, leurs ressources ou leur identité graphique.

**Ton mandat porte sur tout le périmètre ci-dessous. Une première version utilisable, une phase réussie ou une série de tests verts ne termine pas cette mission.** Développe de vrais comportements, vérifie-les, puis continue immédiatement la prochaine tâche réalisable, dans les limites des autorisations et ressources disponibles. La mission peut demander plusieurs sessions ; ne prétends pas qu'une nuit suffira.

## 1. Commencer par le dépôt réel

Lis les instructions applicables, notamment `CLAUDE.md` et `AGENTS.md`. Vérifie le répertoire courant et l'état Git sans toucher au travail existant. Les noms et chemins de cette mission sont des hypothèses à confronter au code. N'invente aucune API, dépendance, interface Board ou capacité de Claude Code.

Respecte la méthode du projet : Carte de la documentation pertinente, recherche du mot-clé dans ce document, recherche du symbole dans les fichiers indiqués, lecture des seules lignes utiles. Pas d'audit récursif de la racine, de lecture intégrale des grosses documentations, ni de répétition d'un audit inchangé. Commence notamment par les cartes de `fm_board.md`, `fm_browser.md`, `fm_theme.md`, puis les sections utiles de `reglages.md`, `apercus.md` et des précédents pertinents. Lis `over/Notes.txt` avant de toucher la fenêtre des réglages.

Repères observés lors de la préparation, à revérifier localement : `main_window/module_targets.py`, `fm_board/model.py`, `serialization.py`, `view.py`, `ui.py` et `fm_pdf/board_model.py`. Board possède des documents liés et des mécanismes de fermeture/sauvegarde ; un registre générique annoncé dans une documentation n'est pas nécessairement implanté. Réutilise les contrats réels sans engager une refonte générale de Board. Examine ponctuellement la coexistence avec le son du module vidéo.

Vérifie les versions, outils natifs disponibles, permissions, bibliothèques déjà utilisées et tests ciblés existants. Établis une carte courte des points d'intégration et une décision d'architecture argumentée. Si un service de médias, une identité persistante ou un cache équivalent existe, étends-le localement plutôt que créer un système parallèle.

Lis le rapport de fluidité s'il est plus récent que ta dernière lecture. Traite les régressions signalées selon les priorités d'AGENTS ; un échec préexistant sans rapport est signalé sans enquête générale. Aucun résultat de ce rapport ne valide par extension les nouveaux modules audio.

## 2. Protéger PIPE FMZ

Tout échange, commentaire et document est en français. Conserve l'architecture par modules, les imports différés et les `HOOKS` : les modules audio et le moteur n'importent pas la fenêtre principale. Le moteur ne dépend ni de Qt, ni de Board, ni des réglages graphiques. Les deux éditeurs ne s'importent pas mutuellement.

Réutilise les briques de réglages et `fm_theme` : aucune couleur, bordure, ombre, variante de bouton ou icône locale inventée. Applique `theme_button`, `icon_frame`, le catalogue et la liste ICÔNES des réglages, les rôles de texte et les tableaux existants. Déclare les clés dans `DEFAULT_SETTINGS`, lis les globals par `ui_state.X` et sauvegarde l'état temps réel par `save_live_state`. Respecte variantes, séparateurs et activation des lignes. Ctrl doit être enfoncé au départ d'un déplacement d'élément, y compris clip, note ou carte ; conserve l'exception des barres flottantes. Échap annule sans sortir du module. Ne modifie pas ces conventions pour simplifier une timeline.

Préserve les données, réglages, presets, documents et modifications utilisateur. N'écrase aucun source audio. N'effectue ni nettoyage destructif, migration irréversible, installation système, acceptation de licence, achat, activation de service payant, modification des permissions, commit ou push sans autorisation correspondante. Les écritures locales nécessaires au développement sont autorisées ; une dépendance, un SDK ou une destination hors périmètre autorisé exige une autorisation précise. Prépare les éléments vérifiables et continue une tâche indépendante en attendant.

Le démarrage du navigateur et des modules existants doit fonctionner sans moteur audio installé. L'intégration est différée, avec diagnostic clair et possibilité de désactiver les nouveaux modules. Une compilation native ciblée deviendra nécessaire : vérifie sa chaîne et son autorisation, sans transformer cela en build global du dépôt. N'altère pas le hook `garde_fous.py`, ne le contourne pas et ne réduis pas les tests pour obtenir un résultat vert.

## 3. Architecture commune à décider puis stabiliser

Point de départ recommandé : deux interfaces Python/PySide6, un modèle de projet commun indépendant de Qt, un service de médias/révisions commun et **un moteur natif partagé**, de préférence C++ dans un processus dédié. Confirme ce choix par un essai de faisabilité court. Une extension native en processus ou Rust est recevable si tu démontres un meilleur compromis pour ce dépôt, notamment pour ASIO/WASAPI, VST3, les éditeurs Windows, la distribution et la maintenance. N'assemble pas plusieurs langages natifs sans bénéfice démontré.

Le processus séparé isole PIPE FMZ d'une panne du moteur ; il ne rend pas automatiquement les plugins sûrs ni une licence compatible. Documente le protocole IPC versionné, les requêtes identifiées, acquittements, annulations, délais et compatibilités. Les blocs audio restent dans le moteur ; aucun transport de chaque bloc via Python, JSON ou signaux Qt. Prévois la finalisation des prises et l'arrêt propre si l'interface disparaît. Pas de service orphelin permanent.

Une seule infrastructure possède les périphériques et arbitre les clients : FM Audio, FM Music et préécoute Board. Définis document actif, transport, préécoute et priorité de capture. Naviguer vers Board ne coupe pas une prise ; préécouter ne vole pas ASIO, ne change pas la fréquence et n'ouvre pas un second moteur concurrent. Les sessions multiples gardent une politique explicite d'activation.

Évalue une courte liste, pas toutes les bibliothèques existantes : JUCE pour réduire le travail natif, si la licence retenue est autorisée ; sinon une pile ciblée d'E/S natives et de composants compatibles, en comptabilisant le travail réel d'hôte, graphe, MIDI et DSP. Une bibliothèque de lecture/capture n'est pas un DAW. N'engage pas une réécriture improvisée pour éviter un blocage de licence.

Pour chaque dépendance effectivement retenue, consigne version/tag, rôle, licence choisie, transitives, conditions de redistribution, notices, coût et autorisation. Vérifie les versions précises de JUCE, ASIO, VST3, time stretching, codecs, Qt/PySide6 et éventuels binaires FFmpeg. La licence du SDK ne permet pas de distribuer les plugins, samples, IR ou modèles d'ampli d'autrui. Verrouille les dépendances et prévois un build reproductible Windows, initialement x64 si compatible avec le dépôt.

## 4. Contrat temps réel non négociable

Le callback audio est entièrement natif : aucun Python/GIL, allocation ou libération imprévisible, mutex bloquant, attente, accès disque/réseau, log, appel Qt, scan de plugin ou destruction de graphe. Préalloue. Utilise des files bornées et des atomiques appropriées ; documente les saturations et vérifie les opérations réellement sans attente. Prépare les graphes hors temps réel, échange-les à une frontière de bloc et libère les anciens hors callback. Les changements continus sont regroupés et lissés au niveau audio ; les commandes critiques restent acquittées.

Sépare traitement audio, décodage/lecture anticipée, écriture des prises, rendu offline, analyse/cache et interface. La télémétrie est bornée, consommée à fréquence limitée ; la peinture n'interroge pas le moteur par requête bloquante. Les plugins sont scannés dans un processus isolé avec délai, cache et quarantaine. L'isolation du scan ne protège pas le traitement : définis et valide aussi la politique de panne en lecture, notamment l'isolation d'hôtes plugins et son coût de latence.

L'horloge audio est maître. Utilise des positions entières 64 bits en échantillons, une représentation musicale définie et une carte tempo/signatures ; conserve une conversion sans dérive cumulative. MIDI, automation, métronome, punch et boucles portent leurs positions et offsets dans le bloc. Aucun `QTimer` ne sert d'horloge musicale. Teste changements de tempo, seek, boucles, limites de blocs et notes à cheval sur une transition.

Conçois tôt bus, sends pré/post-fader, returns, sidechains, groupes, mono/stéréo et correspondance des canaux. Commence par un graphe acyclique ; refuse les boucles tant qu'un vrai feedback retardé n'est pas pris en charge. Prévois la compensation de latence par chemin et la déclaration de latence des plugins, y compris bus/sends. Un mode de monitoring faible latence peut contourner des traitements retardants avec indication claire ; il ne modifie pas silencieusement le mix exporté.

ASIO et WASAPI doivent devenir des backends réels : énumération, sélection persistante, ports, fréquence, taille des buffers et négociation honnête. Gère périphérique occupé, débranchement et remplacement contrôlé. Commence avec une interface duplex à horloge commune ; ne promets pas l'agrégation de cartes non synchronisées. Distingue latence déclarée, compensée et aller-retour mesurée.

Le rendu offline réutilise la sémantique du graphe temps réel. Gère plage, traînes, plugins limités au temps réel, conversion de fréquence, formats et résolution ; le dithering n'est appliqué que lorsqu'il est pertinent. Les exports écrivent de vrais fichiers vérifiés et annulables, sans écraser silencieusement un fichier existant.

## 5. Projets, bibliothèque, versions et sécurité des prises

Sépare identité de ressource, révision immuable, contenu et emplacement. Une composition épingle une révision. Le hash vérifie ou déduplique un contenu ; il ne remplace pas l'identité métier. Les projets partagent des primitives audio/MIDI et préservent les extensions propres à chaque éditeur. Définis schéma versionné, migrations testées, sauvegarde transactionnelle et refus prudent d'une version incompatible.

Le montage stocke des références, plages, gains, fondus, traitements et paramètres. L'édition d'échantillons conserve elle aussi l'original et produit une modification réversible. Undo/Redo, snapshot de sauvegarde, état du moteur et rendu doivent décrire la même révision cohérente. L'historique retient les médias nécessaires ; aucune suppression automatique des anciennes prises ou révisions encore référencées.

La bibliothèque commune conserve sources, filiation, recettes, rendus, métadonnées, tags et projets associés. Un index local peut être reconstructible à partir de manifestes portables. N'utilise pas une base active simplement copiée/synchronisée comme protocole de collaboration ; traite explicitement les conflits, fichiers incomplets et arrivées désordonnées du dossier cloud.

Workflow obligatoire : son enregistré dans FM Audio → traitement → publication v1 → insertion dans FM Music → réouverture de la source dans FM Audio → publication v2 → proposition dans FM Music → adoption ou refus explicite. L'adoption est annulable. Si durée, fréquence ou canaux changent, vérifie offsets, trims, warp, fondus et automation ; ne détruis pas l'arrangement. Board suit la même identité et peut afficher les versions pertinentes.

Les localisateurs relatifs/absolus suivent les conventions existantes. Gère volumes Windows distincts, Unicode, chemins longs, renommages, fichiers déplacés, médias absents et reliaison contrôlée. Pas de scan ou hachage global à chaque clic. Un média absent reste référencé avec diagnostic ; il ne devient pas un silence enregistré à la place de l'original. L'export portable collecte les médias sur demande explicite.

La capture écrit depuis des workers vers un stockage local fiable, hors synchronisation active lorsque possible et dans un emplacement autorisé. Prévois tampons bornés, détection d'overflow et de disque plein, blocs récupérables, journal/checkpoints, fichiers temporaires et finalisation vérifiable. Pour les prises longues, RF64 ou segmentation définie évite les limites du WAV RIFF classique. Publie vers le dossier synchronisé après finalisation. L'autosave du projet ne remplace pas la protection du flux enregistré. Après panne, récupère ce qui a réellement été écrit et annonce précisément les pertes éventuelles ; aucune promesse de zéro perte absolue.

## 6. Périmètre fonctionnel à couvrir intégralement

Transforme les groupes suivants en exigences stables et tâches suffisamment petites, avec critères observables. Aucun groupe ne peut être retiré pour déclarer la mission terminée.

**FM Audio — édition :** lecture des formats annoncés, waveform par canal, zoom jusqu'à l'échantillon, navigation et sélection précises ; découper, copier, coller, supprimer, trim, split, crop et déplacer ; fondus et crossfades ; gain, normalisation de crête, inversion de polarité ; vitesse, pitch shifting et time stretching ; montage non destructif, Undo/Redo et sauvegarde/réouverture fidèle.

**FM Audio — mixage :** pistes extensibles dans les limites mesurées, clips indépendants, alignement précis, volume, pan, mute/solo, groupes, bus, sends/returns, routing et sidechains ; mixer, faders et vu-mètres réels ; automation des paramètres, chaînes/presets, plugins, compensation de latence ; export du mix et stems avec politique explicite pour effets partagés et traînes.

**FM Audio — traitement :** EQ paramétrique, compresseur, limiteur, gate, de-esser, réverbération, delay, chorus, filtres, saturation/distorsion ; spectre, crêtes, true peak et loudness ; édition spectrale effective, réduction de bruit et restauration ; outils de mastering et chaînes sauvegardables. Chaque traitement possède paramètres documentés, tests de comportement et sauvegarde. Un spectrogramme seul n'est pas de l'édition spectrale ; un gate seul n'est pas de la restauration. Une réduction de bruit doit produire un traitement mesurable et permettre l'écoute critique de ses artefacts.

**Enregistrement commun :** mono/stéréo/multipiste, armement, sélection entrées/sorties, buffers, monitoring, mesure de latence, synchronisation des prises, métronome/précompte, overdub, loop recording, takes, comping et punch-in/out. FM Music enregistre directement avec le même moteur, sans passage obligatoire par FM Audio. Les prises restent des sources indépendantes ; le comping conserve les choix et transitions éditables.

**Guitare électrique :** signal DI brut préservé, monitoring traité distinct, pédalier configurable, overdrive/distorsion, chorus/delay/réverbération, véritable simulation d'ampli, cabinet/IR, presets et plugins ; retraitement non destructif de la DI. Une IR de cabinet n'est pas une simulation non linéaire d'ampli. Définis oversampling/anti-aliasing lorsque requis. Distingue reamping logiciel et boucle physique externe, qui demande routage et calibration propres.

**Guitare acoustique :** microphone et pickup, plusieurs sources simultanées, EQ/compression, réduction de bruit, réverbération, polarité, phase et alignement temporel ; sélection des prises. Ajoute accordeur chromatique avec référence réglable, looper et tempo. Évite le double monitoring et les boucles de retour ; les essais matériels ne doivent pas capturer des entrées ou produire un niveau élevé sans action explicite de l'utilisateur.

**FM Music — composition :** timeline musicale, tempo/signatures, pistes et clips audio/MIDI, arrangement, patterns, piano roll, notes/vélocités, contrôleurs MIDI, quantification, groove/swing, automation, boucles et sections. Les gestes modifient les données réellement jouées et exportées. La quantification et le groove restent réversibles.

**FM Music — instruments :** MIDI entrant/sortant et contrôleurs externes ; sampler avec samples, mapping, enveloppes et voix ; drum machine, synthétiseur interne réellement sonore, instruments plugins, presets ; mixage et capture communs, export audio final et échanges MIDI définis. Gère notes bloquées, all-notes-off, périphérique déconnecté et plugin absent sans substituer secrètement un autre son.

**Board :** cartes de fichiers WAV/MP3/FLAC réellement supportés, prises, samples, effets, ambiances, mixages, projets FM Audio, compositions FM Music et exports ; nom/type/durée, miniature waveform, métadonnées, version et état ; glisser-déposer, création de projet, bonne cible d'ouverture, préécoute, classement/recherche, liens avec images/vidéos/documents, versions et réparation des références. Réutilise la sélection, navigation, sérialisation, fermeture et gestion de documents existantes. Board organise et référence ; il ne devient pas un troisième éditeur audio.

## 7. Interface et Claude Design

Conçois des espaces spécialisés cohérents : édition waveform/spectrale, arrangement, mixer, prises/comping, piano roll/patterns, instruments et effets. Prévois clavier, focus, DPI multiples, redimensionnement, lisibilité et retour immédiat aux actions. Sépare modèle, commandes, présentation et apparence. Les détails techniques ne doivent pas envahir les parcours courants.

Vérifie l'accès réel à Claude Design, notamment les commandes ou intégrations disponibles dans cette installation. S'il est accessible et autorisé, utilise-le pour explorer ergonomie, disposition et composants compatibles avec `fm_theme`, puis transforme les propositions en composants PySide6. Aucun prototype HTML ne remplace l'implémentation native. Ne transmets ni dépôt complet, secrets, médias personnels ni ressources non autorisées. Si Design est indisponible, construis des maquettes fonctionnelles à partir des briques existantes et continue.

Waveforms : pyramides min/max par canal calculées en fond, caches versionnés, fenêtre PCM bornée au zoom fin, dessin limité à la zone visible. Spectrogrammes : tuiles calculées en fond. Timelines, clips, notes et mixers : indexation/virtualisation, aucun widget par échantillon ou note. Les traitements sont annulables ; un résultat obsolète ne remplace pas le document actuel. Aucun travail proportionnel à la durée totale d'un média dans peinture, déplacement de souris ou navigation.

## 8. Phases et portes d'acceptation

L'ordre ci-dessous est une base. Adapte les dépendances après audit, sans repousser indéfiniment Board, la capture ou FM Music. Une validation matérielle en attente ne bloque que les tâches qui en dépendent réellement.

| Phase | Livrable fonctionnel et preuve minimale |
|---|---|
| P0 — Pilotage et audit | Carte ciblée, périmètre intégral enregistré, contrats/décisions, licences et prérequis identifiés ; contrôleur d'autonomie testé, sans affaiblir les garde-fous. |
| P1 — Faisabilité native | Moteur chargeable indépendamment, calcul offline réel, protocole UI/service, sélection de backend ; preuve courte de lecture/capture avec dispositif de test déclaré ; essais matériels séparés. |
| P2 — Première tranche intégrée | Board référence un média, FM Audio l'ouvre, affiche sa waveform, le lit, fait une édition réversible, exporte puis sauvegarde/réouvre le projet et le Board sans perte. |
| P3 — Enregistrement fiable | Armement, prise DI, monitoring séparé, timestamps et récupération après panne contrôlée ; la capture ne dépend pas de la peinture. Matériel réel inscrit à valider. |
| P4 — Multipiste | Clips/pistes, mixer, routing/bus/sends, effets de base, automation et compensation ; tests d'impulsions, somme, Undo, export/stems et persistance. |
| P5 — Bibliothèque et FM Music initial | Deux éditeurs réels utilisant le même service ; publication v1/v2, adoption/refus/Undo et références Board ; capture directe dans FM Music. |
| P6 — Composition | Tempo/signatures, MIDI, piano roll, patterns, quantification/groove, sampler, drums et synthé ; musique réellement jouée, sauvegardée et exportée. |
| P7 — Prises et guitares | Overdub, précompte, loop/takes/comping/punch ; DI/acoustique, pédales/ampli/cabinet IR, accordeur/looper ; alignement et conservation des sources démontrés. |
| P8 — Plugins et mixage avancé | VST3 effets/instruments, états, presets, éditeurs, automation, latence et traînes ; scan/panne isolés, plugin absent et reprise traités ; tests tiers distincts. |
| P9 — Édition et DSP avancés | Pitch/time stretch, spectral éditable, restauration, tous les effets/analyse/mastering prévus ; signaux de référence, limites et écoutes humaines identifiées. |
| P10 — Robustesse professionnelle | Parcours transmodules complet, portabilité/migrations, pannes, gros projets, distribution reproductible, licences/notices, documentation et validations restantes. |

Une case de ce tableau n'est jamais une preuve en elle-même. Décompose notamment P4/P6/P7/P8/P9 pour qu'aucun effet ou comportement ne disparaisse derrière une tâche trop large. Chaque incrément livre un comportement utilisable ou une condition technique vérifiable.

## 9. Tests, mesures et définition de « terminé »

Pour chaque fonctionnalité : implémentation réelle, accès depuis l'application, erreurs/annulation, persistance, tests pertinents, absence de régression ciblée, performances applicables et documentation minimale. Un bouton décoratif, un faux moteur ou un export simulé n'obtiennent pas le statut terminé. Les doubles de test sont confinés aux tests et identifiés.

Respecte strictement AGENTS : tests écrits pour la modification et couvrant la fonction modifiée, appelés par nom ; environ 30 secondes au total par incrément. Aucun `tests/run.py`, `discover` non ciblé, `--lent`, variable de contournement ou suite globale. En Python, isolation obligatoire et nettoyage des fenêtres. Pour le natif, filtres ciblés équivalents et sorties vérifiables. Ne répète pas les mêmes vérifications sans changement ni doute nouveau.

Utilise des fixtures synthétiques : silence, impulsions, sinusoïdes, bruit déterministe. Vérifie découpe/fades, nombre d'échantillons, routage/PDC, extrêmes DSP, stabilité/NaN, limites de blocs, tempo/boucles/MIDI, comparaison offline/temps réel selon tolérances justifiées. Teste sauvegarde/réouverture/Undo, migration et médias absents. Injecte sur fixtures disque plein, écriture partielle, crash de worker/plugin, annulation, document fermé pendant tâche et registre tronqué. Les tests doivent vérifier un résultat métier, pas recopier l'implémentation.

Inscris les mesures lourdes avec leurs commandes dans `docs/agents/a_mesurer.md` pour `fluidite.bat` ; ne les exécute pas en violation des règles. Sépare validations **automatique**, **performance**, **matériel** et **humaine** : requise, en attente, réussie avec preuve, échouée ou non applicable avec motif. Une capture simulée ne valide ni ASIO ni la latence de la guitare ; une mesure prévue n'est pas une mesure passée.

Fixe un profil de référence : CPU/RAM, Windows/driver/interface, écran/DPI, fréquence/buffer, pistes, durée et plugins. Objectifs initiaux à confirmer, jamais résultats annoncés : timeline à 60 Hz avec temps de frame p95 ≤16,7 ms et p99 ≤33 ms ; aucune pause UI ≥50 ms dans le parcours mesuré ; retour visuel initial sous 100 ms pour lancement d'un travail long. Pour le callback, échéance `B/Fs` ; viser p99 de calcul ≤50 % de cette échéance, maximum mesuré inférieur à l'échéance et zéro xrun dans le scénario validé. Mesurer aussi retards d'ordonnancement et jitter. À 128 échantillons/48 kHz, l'échéance est environ 2,67 ms, pas la latence aller-retour.

Viser un monitoring aller-retour ≤10 ms sur une interface appropriée, à confirmer par boucle physique. Définir mémoire/cache bornés et scènes longues de 32 puis 64 pistes selon matériel ; endurance et sessions d'au moins 30 minutes sont des mesures différées. Aucun changement discret de profil ou de seuil pour masquer un échec. Une limite démontrée devient une décision documentée soumise à validation si elle réduit le périmètre.

## 10. Registre unique et preuves persistantes

Crée, ou réutilise s'il existe, **un seul registre métier machine-readable**, proposé `docs/agents/audio_music_state.json`. Il contient version de schéma, identifiant de mission, exigences stables, phases, tâches et dépendances, critères, chemins utiles, états d'implémentation et validations séparées, blocages, preuves et prochaine action exacte. Les tâches natives Claude sont une vue d'exécution avec correspondance d'IDs, jamais une seconde source de vérité.

États d'implémentation : `todo`, `in_progress`, `implemented`, `blocked`. Une exigence n'est `validated` que lorsque toutes ses validations requises sont satisfaites. Chaque preuve enregistre commande réellement lancée, code retour, tests exécutés, durée, environnement et empreintes des seuls fichiers/dépendances pertinents. Une modification de code, test, binaire ou configuration concernés périme la preuve. Ne hache pas le dépôt entier. Le runner produit les résultats ; n'écris pas toi-même un simple « tests_ok » comme preuve. Les validations humaines exigent une confirmation réelle.

Garde le périmètre initial stable : une division de tâche conserve l'exigence parente ; aucun retrait silencieux. Un vérificateur déterministe détecte exigences sans tâche, dépendances cycliques, faux statuts et preuves manquantes/périmées. Il calcule `continue`, `complete`, `blocked` ou `limit_reached`, en distinguant arrêt de session et achèvement du produit. Il ne prouve pas à lui seul la qualité du logiciel ; ne modifie pas ses critères pour faire passer un résultat.

Écris les décisions durables une seule fois dans la documentation du module concerné, avec liens depuis le registre. Pas de doublon de journal narratif. À chaque interruption complexe, remplace la `PASSATION` de la doc responsable par 15 lignes maximum : objectif, décisions, fichiers, tests, problèmes, prochaine action ; efface-la à la clôture. Le registre et les fichiers restent la source de vérité.

## 11. Dispositif de poursuite contrôlée

Vérifie la disponibilité réelle de `/goal`, des hooks `Stop`, `TaskCompleted`, `SessionStart`, de la reprise et des tâches natives. Prépare un contrôleur Python standard-library, proposé `tools/hooks/audio_music_guard.py`, et ses tests ciblés avant de l'activer. Préserve intégralement les hooks existants et les permissions. N'affirme pas que ce dispositif est installé avant essai.

Le contrôleur expose `context`, `stop`, `task`, `status`, `arm` et `disarm`. Les commandes d'armement/désarmement prennent un identifiant de run explicite. Une variable de lancement telle que `PIPE_AUDIO_MUSIC_RUN` identifie les sessions concernées ; les événements sont liés au `session_id` réel. Les autres conversations ne sont jamais forcées à poursuivre cette mission. Un seul coordinateur écrit le registre ; refuse un second écrivain concurrent au même run.

`Stop` lit le registre et les preuves compactes ; il ne lance ni test, build, réseau, analyse du dépôt ou sous-agent. Vise moins de 200 ms hors démarrage de Python, timeout 5 secondes ; prépare les vérifications de contenu en amont, sans hachage lourd dans le hook. Une fraîcheur non établie reste à vérifier. S'il reste une tâche indépendante autorisée, bloque l'arrêt avec une raison concise et la prochaine action. Avec le protocole JSON supporté, réponse de sortie 0 : `{"decision":"block","reason":"Tâche X réalisable ; exécuter Y puis vérifier Z."}`. Pour un arrêt légitime, laisse passer sans déclarer le produit terminé si des validations restent ouvertes. Un registre invalide produit un diagnostic et une tentative bornée de réparation, jamais une boucle infinie ni une réussite implicite.

Ne traite pas `stop_hook_active=true` comme une permission automatique de quitter : une continuation avec progrès doit pouvoir déboucher sur la tâche suivante. Inversement, conserve par run/session une empreinte du progrès utile et le nombre de répétitions. Trois tentatives sans information nouvelle sur la même tâche imposent un diagnostic, un blocage documenté et la recherche d'une tâche indépendante. Trois contrôles consécutifs sans progrès utile ni alternative autorisent l'arrêt diagnostiqué. Un horodatage, une reformulation, un appel d'outil vide ou un test identique relancé n'est pas du progrès.

Conserve les compteurs pertinents à travers les reprises ; ne remets pas artificiellement à zéro les échecs ou le budget d'un run. Un budget/délai éventuel est celui fixé par l'utilisateur, sans montant inventé. Les demandes explicites d'arrêt, limites de compte, sécurité et permissions priment. Aucune relance automatique d'un processus mort, aucun changement de permissions et aucune boucle externe qui répète « continue » indéfiniment.

`TaskCompleted` contrôle uniquement les tâches rattachées au registre : refuse une clôture sans ses preuves par sortie 2 et diagnostic sur stderr. Les critères d'une tâche documentaire diffèrent de ceux d'une fonction audio ; une sous-tâche terminée ne clôture pas son exigence parente. `SessionStart` sur démarrage/reprise/compactage injecte seulement un contexte court : mission, registre, prochaine action et blocages. Prévois un désarmement immédiat, un timeout court et des erreurs compréhensibles.

Teste avant activation : tâche réalisable empêchant Stop ; preuve valide ; preuve périmée ; matériel non testé ; `stop_hook_active` avec/sans progrès ; tâche indépendante après blocage ; registre tronqué ; session étrangère ; désarmement ; interruption explicite ; compteurs restaurés. Prévois un exercice de deux incréments démontrant la poursuite et un exercice de blocage réel démontrant l'arrêt contrôlé.

L'évaluateur `/goal` ne lit pas les fichiers : après un incrément significatif et avant tout contrôle de fin, publie dans la conversation un état compact issu du vérificateur : exigences validées/total, tâches réalisables, validations en attente, blocages, preuve récente et prochaine action. Ne lui demande pas seulement de lire le registre. Les mécanismes natifs facilitent la poursuite ; ils ne garantissent ni disponibilité illimitée, ni reprise d'un processus fermé.

## 12. Boucle de travail et conditions d'arrêt

Répète : sélectionner la prochaine tâche utile → lire uniquement son contexte → implémenter un incrément → exécuter les tests ciblés → corriger les erreurs liées → actualiser preuves/registre → publier un état bref → commencer immédiatement la tâche suivante. Ne demande pas une validation humaine à chaque phase. Résous les ambiguïtés mineures, documente-les et avance. Une tâche bloquée par licence, matériel ou autorisation ne bloque pas automatiquement les autres.

Utilise des sous-agents seulement pour des travaux réellement indépendants et rentables, avec périmètre de fichiers, contrat et livrable précis. Pas de délégation pour une petite correction, pas d'audits dupliqués, pas d'écritures concurrentes sur le registre ou les mêmes fichiers. Le coordinateur vérifie leur résultat ; leur affirmation ne remplace pas les tests.

Avant toute réponse finale, relis le registre, vérifie les preuves périmées, tests non exécutés/échoués, problèmes et dépendances. **S'il reste une tâche réalisable, commence-la au lieu de conclure.** Une fin de phase, un compte rendu intermédiaire, un MVP, une limite de contexte proche ou une quantité importante de travail accomplie ne justifient pas un arrêt volontaire. Compacte avec un état opérationnel et continue si l'environnement le permet.

Tu peux arrêter lorsque toutes les exigences et validations requises sont satisfaites ; lorsque aucune tâche indépendante ne peut progresser sans intervention ou ressource indisponible ; lorsqu'une limite technique, de compte, de permission ou une panne empêche la poursuite ; ou lorsque continuer ferait courir un risque concret aux données. Dans les trois derniers cas, indique **mission inachevée**, conserve l'état de reprise et énumère précisément ce qui manque. N'appelle jamais « terminé » un produit dont les essais matériels ou performances requis restent en attente.

À la reprise, vérifie modèle, run, objectif actif, état Git et fichiers réellement produits. Lis seulement instructions, registre, PASSATION et code de la prochaine tâche. Un outil interrompu sans résultat final n'est pas considéré réussi. Ne recommence pas l'audit complet.

Commence maintenant par l'audit ciblé et le dispositif de suivi, puis enchaîne les incréments réalisables de l'ensemble de la mission. Si l'utilisateur a explicitement demandé une séance limitée à la préparation avant absence, termine uniquement cette préparation vérifiée ; cette exception de lancement ne réduit jamais le périmètre du développement ultérieur.

---

## Annexe : dispositif de poursuite installé (préparation du 2026-11-14)

Le texte ci-dessus est le prompt maître d'Astra, copié sans modification. Cette annexe décrit ce qui est réellement installé et testé ; les décisions durables des modules iront dans `docs/agents/fm_audio.md` (à créer, tâche T-P0-02).

### Fichiers

| Fichier | Rôle |
|---|---|
| `docs/agents/audio_music_state.json` | Registre UNIQUE : 22 exigences stables (`baseline_requirements`), phases, tâches, preuves. Seule source de vérité de l'avancement. |
| `docs/agents/audio_music_confirmations.json` | Validations humain / matériel / performance, écrites SEULEMENT par le hook quand l'utilisateur tape « VALIDE R-… <type> ». Ne jamais l'éditer à la main. |
| `tools/hooks/audio_music_registry.py` | Vérificateur déterministe : exigences sans tâche, exigence retirée, cycles, faux statuts, preuves manquantes / périmées / non produites par le runner ; verdict `continue`, `complete`, `blocked`, `invalid`. |
| `tools/hooks/audio_music_guard.py` | Hooks `context`, `stop`, `task`, `prompt`, et commandes `arm`, `disarm`, `bind`, `status`, `check`, `run` (le RUNNER, seule façon d'écrire une preuve ; il refuse ce que refuse `garde_fous.py`). |
| `tests/test_audio_music_guard.py` | 15 tests : hooks lancés comme Claude Code les lance, sur des registres fictifs. |
| `.claude/settings.local.json` | Déclare les 4 hooks (non versionné ; copie de référence versionnée : `tools/hooks/audio_music.hooks.json`, à refusionner si le fichier local est perdu). `garde_fous.py` reste dans `.claude/settings.json` : les hooks des deux fichiers s'additionnent. |
| `.claude/audio_music_runs/<run>.json` | État d'un run : armé, session liée, compteurs (arrêts, blocages, sans progrès, tâches calées), historique. Non versionné. |

Écart avec la préparation d'Astra : pas de fichier `--settings` à part. L'appli de bureau ne sait pas le passer, et le charger EN PLUS de `settings.local.json` doublerait les hooks. Les hooks sont INERTES pour toute session qui n'est pas liée à un run armé (sortie immédiate, environ 0,1 s de démarrage de Python).

### Démarrer la mission (appli de bureau, recommandé)

1. Armer le run (Claude peut le faire sur demande) : `.venv\Scripts\python.exe -S tools\hooks\audio_music_guard.py arm --run-id audio-music-01`.
2. Ouvrir une NOUVELLE session Code dans le dépôt : modèle Opus 5.5, effort élevé, mode de permission Auto (sinon chaque commande attend une approbation).
3. Premier message : « Lance `.venv/Scripts/python.exe -S tools/hooks/audio_music_guard.py bind --run-id audio-music-01` et réponds PRÊT. » (la session est liée par son `CLAUDE_CODE_SESSION_ID`).
4. Deuxième message : la commande `/goal` de la section 4 du document de préparation d'Astra.

En terminal, le lancement par la CLI demande d'abord `claude /login` : la CLI autonome n'a pas de connexion valide sur ce poste (« OAuth session expired »). Le lancement passe alors par la variable `PIPE_AUDIO_MUSIC_RUN=audio-music-01`, qui lie automatiquement la session au premier hook (pas besoin de `bind`).

### Protocole de preuve

- Un incrément se prouve par `python -S tools/hooks/audio_music_guard.py run --run-id audio-music-01 --task T-… [--file F]… -- <commande de test par nom>`. La preuve enregistre la commande, le code retour, le nombre de tests, la durée, l'environnement, et l'empreinte (taille, date, sha256) des `paths` de la tâche et des `--file`.
- Une tâche passe à `implemented` seulement après une preuve réussie. Modifier ensuite un de ses fichiers la périme : le hook Stop redemande la preuve. `check --refresh` rafraîchit une preuve dont seul l'horodatage a changé (synchronisation cloud).
- `status --run-id audio-music-01` donne l'état compact à publier dans la conversation : l'évaluateur de `/goal` ne lit pas les fichiers.
- Une exigence fonctionnelle n'est validée que par au moins une tâche `code` ou `perf` prouvée, plus les validations utilisateur requises. Des tâches doc ou decision seules ne valident jamais un comportement.

### Règles du hook Stop

- Il bloque l'arrêt (`{"decision":"block"}`) tant qu'une tâche est réalisable : statut todo ou en cours, dépendances implémentées, type ni `hardware` ni `human`. Il bloque aussi pour une preuve périmée à refaire.
- Le progrès se mesure par l'empreinte du registre (statuts, motifs, preuves) plus la taille et la date des `paths` des tâches en cours. Après 3 arrêts sans progrès sur la même tâche, celle-ci est « calée » : l'agent doit documenter son blocage et passer à une tâche indépendante.
- Il laisse l'arrêt dans ces cas :
  - 3 arrêts sans progrès et aucune autre tâche, ou 6 arrêts sans progrès du tout (`limit_reached`) ;
  - registre invalide malgré 3 tentatives de réparation ;
  - verdict `blocked` : il ne reste que des validations utilisateur ou des tâches bloquées, et la mission est INACHEVÉE ;
  - verdict `complete`.
- Claude Code plafonne de lui-même à 8 relances consécutives sans appel d'outil (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`).

### Arrêter, valider, reprendre

- Arrêt demandé : taper « STOP MISSION » (ou « arrête la mission ») dans la conversation. Le hook le note, et l'agent finit proprement puis s'arrête. Ensuite : `/goal clear`, puis `disarm --run-id audio-music-01`. Reprendre exige un nouvel `arm`.
- Validation utilisateur : taper « VALIDE R-GTR-E matériel » (types : humain, matériel, performance). Le hook enregistre la confirmation ; l'agent ne peut pas l'écrire.
- Reprise après interruption (veille, quota, fermeture) : rouvrir LA MÊME session dans l'appli (même `session_id`, le but `/goal` est restauré, ses compteurs natifs repartent à zéro ; ceux du run sont conservés), vérifier `/goal`, puis dire « Reprends la mission ».
- Reprise dans une NOUVELLE conversation : `bind --run-id audio-music-01 --force` (prise de relais volontaire ; sans `--force`, un second écrivain est refusé). Puis la consigne de reprise de la section 5 d'Astra.
- Une commande interrompue n'est jamais réputée réussie. La PASSATION va dans la doc du module responsable (15 lignes, remplacée, jamais empilée).

### Essais réels réalisés (2026-11-14)

Preuves conservées dans `docs/agents/essais_audio_music/` : fichiers de run (compteurs, historique des verdicts) et registres fictifs (tâches, preuves du runner). Les deux sessions tournaient dans le dépôt, avec les vrais hooks et `garde_fous.py` actifs, sur Sonnet.
- **A, poursuite** : la consigne demandait UNE tâche. Le hook Stop a refusé l'arrêt 2 fois, la session a fait T-1, T-2 et T-3 (preuves E-0002 à E-0004), puis l'arrêt a été autorisé avec le verdict `complete`.
- **B, vrai blocage** : T-1 a été faite et prouvée. T-2 (licence à fournir, absente) est passée en `blocked` avec son motif, sans contenu inventé. Le premier arrêt a été autorisé avec le verdict `blocked`, mission inachevée.
- **Défaut révélé, puis corrigé** : le runner cherchait un exécutable relatif (`.venv/…`) dans le dossier du run. Il cherche maintenant aussi dans le dépôt (test `test_run_specific_registry_paths`). Les preuves E-0001 en échec (code 127) des deux essais en gardent la trace.
- Essai de `/goal` : à faire par l'utilisateur, car l'agent ne peut pas taper une commande `/`.

### Limites connues

- Rien ne relance un processus fermé. La veille du poste, un quota atteint, une mise à jour ou une fermeture de l'appli arrêtent la session ; seule la reprise ci-dessus la relance.
- Une demande de permission bloque une session sans surveillance : la mission tourne en mode Auto, sans élargir les permissions.
- Les confirmations utilisateur sont protégées par convention : le fichier est écrit par le hook, et la mission interdit de l'éditer. Ce n'est pas une signature cryptographique.

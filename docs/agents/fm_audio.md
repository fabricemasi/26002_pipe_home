# fm_audio, fm_music et moteur audio partagé

## Carte

| Sujet | Où |
|---|---|
| Mission, périmètre, protocole de poursuite | `docs/agents/mission_audio_music.md` (son Annexe d'abord) |
| Registre unique (exigences, tâches, preuves) | `docs/agents/audio_music_state.json` ; état : `python -S tools/hooks/audio_music_guard.py status --run-id audio-music-01` |
| Moteur natif C++ (aucune dépendance) | `fm_audio_engine/native/` : `main.cpp` (IPC, transport, capture, rendu, banc), `graph.h` (graphe, PDC, carte tempo, automation), `dsp.h` (effets), `amp.h` (ampli, cabinet IR, overdrive, FFT), `synth.h` (synthé, sampler, batterie), `wav.h` (WAV/RF64), `wasapi.h` (WASAPI + interface `AudioStream`), `teststream.h` (périphérique de TEST déclaré), `midi_io.h` (MIDI winmm), `spsc.h`, `json.h` |
| Compilation ciblée | `python fm_audio_engine/build.py` → `fm_audio_engine/bin/fmz_audio_engine.exe` (ignoré par git ; empreinte des sources : recompile seulement si une source change) |
| Client du moteur (processus unique partagé, IPC, délais, rendu offline) | `fm_audio_engine/client.py` (`shared_engine()`, `render_offline()`) |
| Modèle de projet sans Qt (pistes, clips, notes, patterns, prises, comping, groupes VCA, Undo) | `fm_audio_engine/project.py` |
| Médias (probe, cache PCM des formats compressés), pics, WAV numpy | `fm_audio_engine/media.py`, `peaks.py`, `wavio.py` |
| Édition non destructive | `fm_audio_engine/edits.py` |
| Traitements hors ligne (WSOLA, transposition, réduction de bruit, spectral, déclic) / analyse (LUFS, true peak, alignement, YIN) | `fm_audio_engine/dsp_offline.py`, `analysis.py` |
| MIDI (quantification réversible, groove, SMF) | `fm_audio_engine/midi.py` |
| Bibliothèque commune (ressources, révisions, manifestes, adoption) | `fm_audio_engine/library.py` |
| Capture : récupération des prises, latence | `fm_audio_engine/capture.py` |
| Préréglages (instruments, chaînes) | `fm_audio_engine/presets.py` (utilisateur : `data/audio_presets.json`) |
| Plugins : inventaire, scan isolé / cache / quarantaine, bibliothèque | `fm_audio_engine/plugins.py` |
| Hôte VST3 du moteur (effets, instruments, états, paramètres, éditeurs) | `fm_audio_engine/native/vst3_host.h` |
| Backend ASIO | `fm_audio_engine/native/asio_backend.h` (session : `fm_sound_ui/session.py` `device_pair`) |
| SDK tiers (hors Git) et plugins de test | `fm_audio_engine/third_party/`, `fm_audio_engine/vst3_sources.py`, `native/test_plugins/` |
| Menus « Plugins VST3 », éditeurs (Qt) | `fm_sound_ui/plugins_ui.py` |
| Briques Qt communes (session/transport, timeline, mixer, base d'éditeur) | `fm_sound_ui/` |
| FM Audio (pane, traitements en révision) | `fm_audio/pane.py`, `fm_audio/processing.py` |
| FM Music (pane, piano roll) | `fm_music/pane.py`, `fm_music/pianoroll.py` |
| Cartes audio du Board | `fm_audio/board_model.py` (sans Qt), `fm_audio/board_item.py` |
| Branchement fenêtre | `main_window/audio_module.py` (+ lignes dans `module_targets.py`, `viewer.py`, `pipeline_browser.py`, `_leave_audio` dans les autres modules) |
| Boutons FM Audio / FM Music de la barre, cadres « FM Audio » / « FM Music » (outils du transport) | `pipeline_browser.py` (`btn_audio`, `btn_music`), `main_window/audio_module.py` (`_toggle_sound`, `_SOUND_TOOLS`, `_layout_sound_buttons`), `main_window/title_bar.py` (`audio_group`, `music_group`), `main_window/chrome.py` (état, couleur) ; éditeur : `EditorPane.transportChanged`, `transport_state`, hook `navbar_frame` (doublons masqués) |
| Icônes (catalogue hors dépôt, modules `audio` rouge et `music` vert) | `preview_column.NAV_LIBRARY_ICONS` (`audio`, `music`, `sound_*`), couleur : `navtool_icon_color_audio` / `_music` (`browser_core_parts/settings.MODULE_ICON_COLOR_KEYS`), icône perso : `ui_navbar_audio`, `ui_navbar_music`, `ui_sound_*` ; recette : `F:/SYNC/Sync/IMAGES/ico/SVG/pipeline browser/documentation/outillage/dessins_son.py` |
| Réglages : onglets « FM Audio » (`fm_audio/settings.py`) et « FM Music » (`fm_music/settings.py`, défauts `fm_music/settings_defaults.py`) | projets neufs (`audio_new_sample_rate`, `music_new_*`), grille et swing (`music_grid`, `music_swing_default`), plugins (`audio_plugin_dirs`, `audio_plugin_scan_timeout`), icônes du cadre |
| Réglages par défaut | `fm_audio/settings_defaults.py` (fusionnés dans `settings_store.DEFAULT_SETTINGS`) |
| Tests (par nom) | `tests.test_audio_engine`, `_io`, `_capture`, `_dsp`, `_dsp_offline`, `_project`, `_edits`, `_media`, `_midi`, `_library`, `_presets`, `_plugins`, `_board`, `_workflow`, `_docs`, `tests.test_fm_audio_module` |
| Bancs (lancés par `fluidite.bat`) | `tools/bench_audio_engine.py`, `tools/bench_audio_ui.py` (lignes dans `a_mesurer.md`) |
## Carte d'intégration (audit du 2026-11-14)

Précédent le plus court : **fm_pdf** (`main_window/pdf_module.py`). Pas de registre unique : un module s'ajoute dans plusieurs listes.
- `<paquet>/__init__.py` minimal (`EXTENSIONS`, `is_x_file`), lu à chaque clic, sans import lourd.
- `main_window/module_targets.py` : `MODULES` (clé → libellé, nom du bouton), `OPENERS` (clé → méthode), `module_targets(path, is_dir)` (par extension), `open_in_module`.
- `main_window/<x>_module.py` : `x_target`, mixin `_install_x_hooks` (remplit `pane.HOOKS` : settings, status, open_settings, navbar_frame, fullscreen), `_open_x` (ferme les autres modules : `_close_md_editor`, `_close_board`, `_leave_font`, `_leave_agenda`, `_leave_taches`, `_close_video`, `_leave_pdf`…), `_leave_x`, `_close_x`, `_layout_x_buttons`.
- Le pane est un widget enfant de `self.scroll.viewport()` qui le recouvre ; il suit la taille par filtre d'événements sur son parent. API : `HOOKS`, signaux `closeRequested`/`stateChanged`, `open_path`, `confirm_leave`, `request_close`, `shutdown`, `apply_settings`, `view`.
- `pipeline_browser.py` : import + mixin, `IconButton`, liste de style, `titlebar.add_tools`, `closeEvent`. `main_window/chrome.py` : `_sync_mode_buttons`, `_NAV_ICON_COLORS`, `_refresh_navbar_icons`. `main_window/title_bar.py` : groupe du module. Fermeture croisée : chaque module appelle `getattr(self, "_leave_<x>", None)`.
- Board : pas de carte de fichier générique. Précédent : `fm_pdf/board_model.py` (sans Qt : type, `DEFAULTS`, `normalize_entity`, `link_values`, `resolve`) + `fm_pdf/board_item.py` (`BoardItem`, `ITEM_CLASSES[...]`, importé pour son effet de bord par `fm_board/scene.py`). Fusion des défauts dans `fm_board/model.py` (`DEFAULTS`, `normalize_item`). Glisser-déposer : `fm_board/view.py` `drop_mime` (ne crée que des images) : branche audio à ajouter. Peinture dans l'item, jamais de rendu en peinture.
- Réglages : `<paquet>/settings_defaults.py` fusionné dans `settings_store.DEFAULT_SETTINGS` ; `<paquet>/settings.py` (`CATALOG`, arbre) ; `settings_window_v2.py` (`STANDALONE_TABS`, `MODULE_SCOPES`, `MODULE_TITLES`, `TAB_LABELS`).
- Création depuis une colonne (demande utilisateur 2026-11-14) : clic droit dans le vide d'une colonne → « Créer un projet FM Audio » (`.fmaudio` vide, comme « Nouveau ») / « Créer un projet FM Music » (`.fmmusic` = `fm_music.pane.default_project`) : `column_parts/context_menu.py` → `column_parts/file_operations.py` `_create_sound_project(kind, name)` (même mécanique que `_create_board_file`). Masqué si `audio_enabled` est coupé. Test : `tests.test_fm_audio_module.ColumnCreateProjectTest`.
- Vidéo : son via LibVLC ou QtMultimedia (`fm_video/pane.py` `_setup_audio`). Coexistence : FM Audio n'ouvre pas son moteur tant que la vidéo est ouverte au premier plan ; l'ouverture d'un module ferme l'autre (règle commune), donc pas de lecture concurrente.

## Inventaire natif et licences (2026-11-14)

Poste de référence : Intel i9-9900K, 64 Go, Windows 11 Pro 26100, cartes : Realtek HD Audio, NVIDIA HD Audio, périphérique audio USB, Razer Kiyo X (micro). Aucune interface ASIO dédiée constatée.

| Élément | Version | Rôle | Licence / statut |
|---|---|---|---|
| MSVC Build Tools 2022 | 17.14.10 (cl 14.44.35207) | compilation du moteur | déjà installé, outil Microsoft |
| CMake + Ninja (fournis avec Build Tools) | intégrés | non utilisés (build direct `cl`) | — |
| SDK Windows | 10.0.26100.0 | WASAPI, MMDevice, winmm (MIDI) | déjà installé |
| Python | 3.12.3 (.venv) | interfaces | — |
| PySide6 | 6.11.2 | interfaces | LGPL, déjà dépendance |
| numpy | 2.5.3 | pics, analyse | BSD, déjà dépendance |
| PyAV | présent | décodage MP3 / FLAC / autres vers le cache PCM | BSD (+ FFmpeg LGPL embarqué), déjà dépendance |
| JUCE | — | NON retenu | AGPLv3 ou commercial : exigerait une décision de licence de l'utilisateur ; un moteur sans dépendance suffit au périmètre actuel |
| ASIO SDK (Steinberg) | 2.3.4 (2025-10-15), `ASIO-SDK_2.3.4_2025-10-15.zip` (sha256 d5ebf0c2…), steinberg.net/asiosdk | backend ASIO (`FMZ_ASIO`) | **variante GPLv3** retenue, téléchargée avec l'accord de l'utilisateur (2026-11-14). Usage personnel : rien à faire. DISTRIBUER un `fmz_audio_engine.exe` compilé avec ASIO impose le GPLv3 (sources) ou la licence propriétaire signée par Steinberg. SDK jamais versionné (`third_party/`, ignoré) ; logo ASIO non utilisé |
| VST3 SDK (Steinberg) | 3.8.1 (tag `v3.8.1_build_84` des dépôts `vst3_pluginterfaces`, `vst3_base`, `vst3_public_sdk`) | hôte de plugins (`FMZ_VST3`), plugins de test | MIT (depuis 3.8) ; nom « VST » non utilisé dans l'interface (marque) ; vstgui non téléchargé |
| Time stretching (Rubber Band, etc.) | — | non retenu | GPL / commercial ; un étirement WSOLA maison est implanté à la place |

Aucune dépendance native tierce : le moteur n'utilise que la bibliothèque standard C++20 et les API Windows. Rien à redistribuer hors de nos sources.

## Décision d'architecture (D-ARCH-01, 2026-11-14)

- **Moteur natif C++ dans un processus dédié** `fmz_audio_engine.exe`, compilé par `fm_audio_engine/build.py` (cl direct, /O2, x64). Raisons : MSVC présent, WASAPI et MIDI Windows disponibles sans dépendance ; un plantage du moteur n'emporte pas PIPE FMZ ; pas de GIL ni de Qt dans le callback ; Rust absent du poste.
- **Un seul moteur partagé** par FM Audio, FM Music et la préécoute Board : `fm_audio_engine/client.py` tient UN processus par appli (`shared_engine()`), clients identifiés ; le document actif possède le transport ; la préécoute Board n'ouvre pas de second périphérique, elle charge un graphe de préécoute sur le même moteur et se coupe si une prise est en cours.
- **Le moteur ne lit que du PCM** (WAV/RF64). Les formats compressés sont décodés par PyAV, hors temps réel, vers le cache PCM versionné de `media.py`. Le moteur ne dépend ni de Qt, ni du Board, ni des réglages.
- **Le même graphe sert au temps réel et au rendu offline** (`graph.h`, `Graph::render`) : le rendu d'export est fait par le moteur (`--render` ou commande IPC `render`), jamais par une réimplémentation Python.

### Protocole IPC v1

- Transport : stdin/stdout du processus, une ligne JSON par message (UTF-8). La fin de stdin (interface disparue) = arrêt propre : transport stoppé, prises finalisées, processus terminé. Pas de service permanent.
- Requête `{"id": n, "cmd": "...", ...}` → réponse `{"id": n, "ok": true|false, "error": "..."}`. Le client attend la réponse avec un délai (2 s par défaut, plus pour `render`) ; un délai dépassé est une erreur explicite, jamais un succès.
- `hello` → `{"protocol": 1, "engine": "<version>"}` ; un client refuse un moteur d'une autre version de protocole majeure.
- Événements non sollicités `{"event": "telemetry", ...}` (position, lecture, crêtes par nœud, réduction de gain, xruns, débordements de capture) émis par un fil dédié à 30 Hz au plus : l'interface ne questionne jamais le moteur en peignant.
- Travaux longs (`render`) : réponse immédiate `{"ok": true, "job": k}`, puis événements `progress` et `done` ; `cancel {"job": k}` annule (fichier `.part` supprimé, aucun fichier existant remplacé).
- Les blocs audio ne transitent JAMAIS par l'IPC.
- `hello` annonce `backends` (`wasapi`, `asio` si compilé) et `plugins` (`vst3` si compilé) ; ce qui manque est dans `unavailable`.
- Périphériques : `devices` liste aussi les pilotes ASIO inscrits au registre (`asio:<nom>`, `flow: duplex`, sans les charger) ; `open_device` répond `backend`.
- Plugins : `vst3_state` / `vst3_params` / `vst3_editor {open}` sur `{node, slot}` (`slot` = `fx<N>` ou `inst`) ; CLI `--scan-vst3 <module>` = scan isolé (JSON des classes).

### Temps réel

- Callback : aucun appel système bloquant, aucune allocation. Le graphe est construit par un fil de travail, publié par pointeur atomique, pris par le callback à une frontière de bloc ; l'ancien graphe est rendu au fil de travail par une file SPSC et détruit hors callback.
- Paramètres continus : messages POD dans une file SPSC bornée (1024), appliqués en début de bloc, lissés dans l'effet. Saturation : message refusé, compté et signalé à l'interface.
- Horloge : position entière 64 bits en échantillons, tenue par le callback. Tempo : carte tempo (PPQ 960), conversion tick → échantillon calculée depuis le début du segment de tempo (pas de dérive cumulative), identique en C++ et en Python (testé).

## Effets du moteur

Clés communes : `bypass`. Paramètres (dsp.h) :
- `gain` : `gain_db`, `polarity`. `eq` : 6 bandes `bN_on`, `bN_type` (0 cloche, 1 plateau bas, 2 plateau haut, 3 passe-bas, 4 passe-haut, 5 passe-bande, 6 coupe-bande), `bN_freq`, `bN_gain_db`, `bN_q`. `filter` : `type`, `freq`, `q`.
- `compressor` : `threshold_db`, `ratio`, `attack_ms`, `release_ms`, `knee_db`, `makeup_db`, `sidechain`, `mix`. `limiter` : `ceiling_db`, `release_ms`, `lookahead_ms` (latence déclarée). `gate` : `threshold_db`, `attack_ms`, `hold_ms`, `release_ms`, `range_db`, `sidechain`. `deesser` : `freq`, `threshold_db`, `ratio`, `release_ms`.
- `delay` : `time_ms`, `feedback`, `mix`, `pingpong`, `highcut`. `reverb` : `room`, `damp`, `width`, `mix`, `predelay_ms`. `chorus` : `rate_hz`, `depth_ms`, `delay_ms`, `mix`, `feedback`. `distortion` : `drive_db`, `type` (0 tanh, 1 dur, 2 asymétrique, 3 fuzz), `tone`, `mix`, `output_db`, suréchantillonnage ×4.

## Pièges rencontrés (2026-11-14)

- **Capture** : le bloc doit être annoncé au worker APRÈS l'écriture de ses données dans l'anneau et la publication de l'index d'écriture (sinon le worker lit un bloc incomplet : discontinuités dans la prise). Test : `tests.test_audio_capture` (continuité).
- **Périphérique de test** : en mode accéléré il tournait avant l'ordre de lecture ; il attend maintenant la première lecture (`hold_until_play`). Il ne valide NI un vrai matériel NI ASIO.
- **Précompte** : aucune capture pendant le précompte (la prise commence à `precount_until`).
- **Fréquence** : le graphe joue à la fréquence du périphérique ; la session et la préécoute ouvrent donc le périphérique à la fréquence du projet / du son (WASAPI partagé convertit, `AUTOCONVERTPCM`), réouverture seulement hors prise.
- **Windows** : `np.load` d'un `.npz` garde le fichier ouvert (utiliser `with`) ; un `QTimer.singleShot(0, vue.méthode)` survit à la vue : passer la vue comme contexte ; un signal émis par un fil après destruction de sa session : capturer `RuntimeError`.
- **MIDI** : la première énumération winmm peut prendre plusieurs secondes (synthé GS) : délai de 30 s pour `midi_devices`.
- **Automation des paramètres d'effet** : appliquée à la frontière de bloc (512), puis lissée 10 ms dans l'effet ; gain / pan de piste : rampe par échantillon.
- **ASIO** : un pilote ASIO est un objet COM « apartment » : tout son cycle de vie sur un fil STA dédié (le moteur est en MTA) ; `AsioDriverList` appelle `CoInitialize` elle-même ; beaucoup de pilotes exigent un HWND (`sysRef`) ; les sources du SDK se compilent SANS `/DUNICODE`. Le pilote « Realtek ASIO » du poste refuse les buffers (`ASE_InvalidMode`) tant que la sortie analogique Realtek est inactive : refus expliqué, moteur intact.
- **VST3** : sources du SDK en C++17 (C++20 : `u8string` dans `module_win32.cpp`) ; ajouter `threadchecker_win32.cpp` ; `CPluginView` ne déclare pas HWND d'elle-même (`isPlatformTypeSupported`) ; une instance temps réel est gardée entre reconstructions (`Vst3Pool`, clé `nœud#fxN`) et son éditeur est refermé AVANT `terminate`.
- **Moteur en cours d'usage** : l'appli ouverte verrouille `fmz_audio_engine.exe` ; `build.py` renomme l'ancien dans `bin/old/` (un exécutable en cours se renomme, il ne s'efface pas).
- **Shell** : PowerShell 5.1 retire les guillemets doubles des arguments passés à un exécutable natif ; les fichiers de la fenêtre sont en CRLF.

## Politiques retenues

- **Stems** : politique « bus » : chaque stem = la piste seule À TRAVERS ses bus (effets partagés inclus) ; traîne automatique (traînes déclarées des effets / instruments, 30 s au plus).
- **Sidechain** : la détection lit le signal post-fader de la source (traitée avant, ordre topologique) ; un cycle (y compris par sidechain) est refusé.
- **Plugin absent** : effet `vst3:<id>` signalé par le moteur et laissé de côté (son inchangé) ; instrument absent = piste muette signalée ; jamais substitué.
- **Plugins** : référence = `vst3:<UID>` + `path` du module + `state` (base64, recopié à chaque enregistrement : `AudioSession.capture_plugin_states`) + `p<id>` (normalisés, automatisables). Scan TOUJOURS dans un processus à part (délai 20 s, cache `plugins_vst3.json` du cache audio, quarantaine jusqu'à changement du module ou « Réessayer ») ; les menus ne lancent jamais de scan (cache seul), « Rechercher les plugins… » scanne en fond. Le rendu offline crée ses propres instances (`kOffline`). Plantage d'un plugin EN LECTURE : il emporte le processus moteur, pas PIPE FMZ (la session relance le moteur au besoin) ; pas d'hôte par plugin (coût de latence non justifié à ce stade).
- **ASIO** : duplex sur UN pilote (entrées du même pilote) ; une entrée WASAPI avec une sortie ASIO est ignorée et signalée (pas d'agrégation d'horloges) ; le pilote garde sa fréquence (pas de réouverture en boucle).
- **Révisions** : un traitement de FM Audio écrit `<nom>__r<N>.wav` à côté du projet (ou dans le cache si le projet n'est pas enregistré) ; la bibliothèque copie les fichiers publiés dans `resources/<id>/r<N>` ; une adoption ne déplace jamais un clip, elle réduit seulement la longueur à ce qui existe.
- **Board** : les cartes audio appartiennent au Board de base (`MODULE = "miro"`), ne sont jamais copiées dans les assets ; double-clic = module du fichier ; préécoute refusée pendant une prise.

## PASSATION

- Objectif : mission docs/agents/mission_audio_music.md, run `audio-music-01` (lié à la session du 2026-11-14).
- Fait : tout le code (moteur, ASIO, hôte VST3 + scan isolé + éditeurs, FM Audio, FM Music, Board, bibliothèque) ; bouton de la barre, cadre d'outils, 7 icônes de la charte, onglets de réglages (2026-11-14). Registre : 104 tâches, 95 prouvées par le runner, verdict `blocked`.
- Reste (utilisateur seulement) : 9 validations « VALIDE R-… matériel / humain / performance » (WASAPI et ASIO réels : le pilote Realtek ASIO refuse tant que la sortie analogique Realtek est inactive ; prise longue ; guitares ; clavier MIDI ; écoutes ; ergonomie) ; approbation artistique des 7 icônes (`a_approuver_utilisateur` dans le manifeste) ; bancs et tests `@lent` via `fluidite.bat`.
- Licence : moteur compilé avec ASIO = GPLv3 s'il est DISTRIBUÉ (voir « Inventaire natif et licences »).
- Rien n'est commité : point de restauration `git tag avant-mission-audio-01` ; SDK dans `fm_audio_engine/third_party/` (ignoré par Git).
- Prochaine action : relire `status`, traiter les validations et retours d'icônes donnés par l'utilisateur.

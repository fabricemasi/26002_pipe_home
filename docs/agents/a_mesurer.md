# À mesurer à temps perdu

Demande de l'utilisateur (2026-11-06) : pendant une requête, l'agent ESTIME le coût d'un changement (rien d'O(n) par
image ou par événement, ne rien refaire qui n'a pas changé) mais ne lance pas de mesure longue. Ce qui mérite une
mesure est noté ici, avec la commande qui la fait. L'utilisateur lance `fluidite.bat` (`tools/fluidite.py`) quand il
n'attend rien : chaque ligne « - [ ] … `commande` » ci-dessous est lancée et sa sortie va dans
`docs/agents/rapport_fluidite.md`. À la requête suivante, l'agent lit ce rapport, corrige en priorité ce qui dépasse
et coche la ligne (`- [x]`) ou la retire.

Format d'une ligne (la commande entre accents graves, en FIN de ligne ; `python` = le Python du projet) :

    - [ ] 2026-11-06 — Board : guides par sorte, 2 000 éléments (fm_board/scene.py `_edge_kind`) — `python tools/bench_board.py guides`

Les bancs permanents (`tools/bench_illustrator.py`, `tools/bench_photoshop.py`, `tools/probe_photoshop_latency.py`)
sont lancés à chaque passage, sans ligne ici (liste `BANCS` de `tools/fluidite.py`).

## File

- [ ] 2026-11-14 — FM Audio / FM Music dans la barre (`main_window/audio_module._layout_sound_buttons`, appelé à l'ouverture / fermeture et aux CHANGEMENTS du transport seulement, 9 boutons) : test lent `python -m unittest tests.test_fm_audio_module.NavbarAppTest` (avec `PIPELINE_TESTS_LENTS=1`, fenêtre entière) ; mesurer le clic sur le bouton FM Audio (construction du pane + cadre), cible < 100 ms de retour visuel.
- [ ] 2026-11-14 — Moteur audio (fm_audio_engine) : coût DSP du graphe par bloc de 128 à 48 kHz, 32 pistes (clip + EQ + compresseur, send réverbe, limiteur). Profil de référence : i9-9900K, 64 Go, Windows 11 26100, Realtek HD Audio. Critère p99 ≤ 50 % de 2,67 ms, max < échéance (contrôle de 4 pistes à la main : p99 70 µs) — `python tools/bench_audio_engine.py 32 8000`
- [ ] 2026-11-14 — Moteur audio, 64 pistes (même scène, même critère) — `python tools/bench_audio_engine.py 64 8000`
- [ ] 2026-11-14 — FM Audio / FM Music : timeline 60 Hz (p95 ≤ 16,7 ms, p99 ≤ 33 ms, aucune pause ≥ 50 ms), zoom et défilement d'une prise de 30 min, piano roll de 5 000 notes — `python tools/bench_audio_ui.py`
- [ ] 2026-11-14 — Moteur audio sur matériel réel : xruns, jitter du callback, latence aller-retour par boucle physique, endurance 30 min. MESURE HUMAINE (câble de bouclage, action explicite de l'utilisateur), pas de commande automatique ; résultat à confirmer par « VALIDE R-RT performance ».

- [ ] 2026-11-13 — Vectorisation d'image refaite (fm_illustrator/trace_contours.py, trace_fit.py) : 70 à 460 ms par forme de 600 px, ~0,4 s pour un « m » au Détail 1 000 (fil de fond, Échap arrête). Surveiller une image en 16 couleurs au Détail 1 500 (nombreux contours) — `python tools/bench_trace.py`
- [ ] 2026-11-13 — Icônes officielles, navigation et Board : hors écran, 30 changements de couleur CAD avec les widgets visibles, médiane ~2,2 ms ; une peinture stable ne demande aucun rendu SVG. Fenêtre complète (plateforme Windows, Board ouvert, 30 changements) : `_apply_settings` 3,4 ms, avec les peintures 7,6 ms en médiane (max 25,7), une icône refaite par changement. Confirmer sur la fenêtre complète, Board ouvert, pendant le glisser de couleur et un déplacement dans la vue — `python -m cProfile -o output/barre_modules.prof pipeline_browser.py`

- [ ] 2026-11-13 — Couleurs des modules pour les icônes (`browser_core_parts/settings.apply_module_icon_colors`, `fm_theme/icon_library.py`) : mesuré à la main 0,04 ms par `_apply_settings` sans changement de couleur, 0,03 ms par pixmap en cache, ~1 ms par changement avec 2 icônes refaites. À mesurer quand des widgets emploieront la bibliothèque : glisser la couleur d'un module (board ouvert, ~50 icônes de ce module visibles) — cProfile de `PipelineBrowser._apply_settings(changed={'board_modulebar_color_cad'})` + `processEvents()`, cible < 16 ms par cran.
- [ ] 2026-11-12 — Marge des icônes (Thème > Général, `icon_margin`, `fm_theme/icon_frame.py`) : mesuré à la main 0,41 ms par icône au 1er dessin (cache vide), 0,03 ms ensuite (0,04 sans cadre). Curseur tiré = TOUS les caches d'icônes vidés + fenêtres repeintes : ~100 icônes visibles ≈ 40 ms par cran (cible < 16 ms). Mesurer fenêtre principale + board ouvert : cProfile de `PipelineBrowser._apply_settings(changed={'icon_margin'})` + `processEvents()`. Si trop lent : appliquer la marge au RELÂCHER du curseur, ou vider les caches par lots.
- [ ] 2026-11-11 — Réglages : toggle « activer » des lignes Bordures / Border radius / Ombres / Padding / Margin (settings_window_v2 : make_field, read_spec, _flat_cells_table ; ~200 toggles de plus, lecture du champ à la construction) — construction de la fenêtre de réglages entière et de Thème, et `wired_values`, avant / après (`tools/bench_*.py` de la fenêtre de réglages, cProfile).
- [ ] 2026-11-11 — Tâches : volume 10 000 tâches / 20 listes (fm_taches/services/tasks.py, ui/pane.py, ui/tasklist.py, services/reminders.py) : ouverture du service, liste en cache / après modification, cocher, semaine et année de l'Agenda, vues intelligentes, recherche, rappels, panneau (construction, changer de liste, peinture) — à comparer à docs/agents/fm_taches.md « Mesures » — `python -m unittest discover -s tests -p test_taches_perf.py -v`
- [ ] 2026-11-07 — Agenda : barres longues fléchées (fm_agenda/ui/longbars.py, timegrid.py : chemins à la disposition, encart de survol repeint seul) — peinture de la semaine et glisser à 50 000 événements, à comparer au tableau de docs/agents/fm_agenda.md — `python -m unittest discover -s tests -p test_agenda_perf.py -v`

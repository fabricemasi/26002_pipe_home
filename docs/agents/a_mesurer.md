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

- [ ] 2026-11-11 — Tâches : volume 10 000 tâches / 20 listes (fm_taches/services/tasks.py, ui/pane.py, ui/tasklist.py, services/reminders.py) : ouverture du service, liste en cache / après modification, cocher, semaine et année de l'Agenda, vues intelligentes, recherche, rappels, panneau (construction, changer de liste, peinture) — à comparer à docs/agents/fm_taches.md « Mesures » — `python -m unittest discover -s tests -p test_taches_perf.py -v`
- [ ] 2026-11-07 — Agenda : barres longues fléchées (fm_agenda/ui/longbars.py, timegrid.py : chemins à la disposition, encart de survol repeint seul) — peinture de la semaine et glisser à 50 000 événements, à comparer au tableau de docs/agents/fm_agenda.md — `python -m unittest discover -s tests -p test_agenda_perf.py -v`

"""fm_tableur : tableur du Board (élément « sheet » du `.mro`) et mode Standard plein cadre.

Carte, choix, mesures : `docs/agents/fm_tableur.md`. Couches (chacune n'importe que les précédentes) :
SANS Qt — `refs` (références A1), `numfmt` (formats de nombres), `values` (saisie typée), `document` (modèle),
`engine` (calcul, formualizer), `commands` (annulation), `ops` (opérations), `io_native` / `io_xlsx` / `io_csv`,
`session` (document partagé) ; Qt — `render` (peinture des cellules), `grid` (grille), `widget` (classeur complet),
puis l'intégration au Board (`board_item`, `board_ui`) et le mode Standard (`standard`)."""
EXTENSIONS = (".xlsx", ".xlsm", ".csv", ".tsv")

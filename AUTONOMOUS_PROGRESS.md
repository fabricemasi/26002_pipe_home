# Suivi du développement autonome — module Photoshop (fm_photoshop)

Doc de référence : `docs/agents/fm_photoshop.md` (carte, décisions, état, mesures, PASSATION).

## Terminé (voir la doc pour le détail)
Intégration Board + Standard, calques/groupes/masques/écrêtage, brosse + retouche, sélections, réglages/filtres, transformations
numériques, texte/formes, ICC, PSD (lecture), export fond, réglages catalogue, menus contextuels, miniatures, aperçu de déplacement.

## 2e passe autonome
- [x] Cache « pivot » des réglages de calque en direct (opacité) : recomposition du calque vers le haut, tuiles en retard
  affichées en version précédente (temporaire) puis exactes. Mesure honnête : les anciens « 35 ms » étaient plafonnés par le budget
  de peinture ; le coût réel d'un cran = tuiles visibles × 5-15 ms ; une tuile par image au minimum (granularité 256²).
- [ ] Transformation libre à poignées sur l'établi
- [ ] Sélection multiple de calques (déplacer, grouper)
- [ ] Calques de réglage non destructifs
- [ ] 16 bits

## Bugs trouvés / corrigés
- Tampon QImage libéré (copie obligatoire) ; Alt de QTest tenu ; crochets non idempotents (doublons) — corrigés.

## Tests
`python tests/run.py fm_photoshop` (15 fichiers) ; `fm_board` pour les crochets.

## Blocages
Aucun.

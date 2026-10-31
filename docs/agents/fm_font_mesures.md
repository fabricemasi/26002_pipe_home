# Module typographique `fm_font/` : mesures

Partie de la doc du module ; entrée, carte et PASSATION : `docs/agents/fm_font.md`.

## Mesures (2026-10-30, refaites en fin de mission, `python -m fm_font.bench 1000`, dossier temporaire local)

| Parcours | Temps |
|---|---|
| Déplacer un pas (10 contours sélectionnés, glyphe de 400 points) | 0,06 ms |
| Instantané d'annulation / restauration du glyphe de 400 points | 0,06 / 0,10 ms |
| Créer 1000 glyphes | 20 ms |
| Enregistrer 1000 glyphes (UFO atomique) / ouvrir | 1 010 / 555 ms |
| Compiler TTF / OTF 1000 glyphes | ~2 100 ms -> 221 / 195 ms (chevauchements par skia-pathops au lieu de booleanOperations ; toujours hors du fil de l'interface) |
| Diagnostic 1000 glyphes | 330 ms -> 90 ms (sens des contours sans copie du glyphe) |
| Compatibilité de 2 masters (1000 glyphes) / interpoler un glyphe | 6 / 0,3 ms |
| Instance complète interpolée (1000 glyphes) / police variable (1000 glyphes, 2 masters) | 330 / 460 ms |
| Export depuis l'interface | dans un FIL : instantané 6,5 ms sur le fil de l'interface (`export_to(background=True)`) |

### Mesures Qt (`python -m fm_font.bench 200 --qt`, offscreen, 1200 x 900, glyphe de 400 points plein écran)

| Parcours | Avant | Après |
|---|---|---|
| Un pas de glisser (déplacer + invalider + peindre) | 73 ms | 13 ms |
| Zoom (un cran + peinture) | 39 ms | 8,5 ms |
| Pan (un pas + peinture) | 14 ms | 6 ms |
| Chemin du glyphe refait (invalidation) | 0,7 ms | 0,7 ms |
| Grille : filtrer 1000 glyphes / peindre un écran | 1 / 14 ms | |
| Aperçu : ligne de 40 glyphes / un cran de crénage | 1,1 / 1,3 ms | |
| Couteau sur le glyphe de 400 points : aperçu par mouvement (contours aplatis gardés pendant le geste) / coupe | 5,5 -> 2,3 ms / 33 ms | |
| Ouverture de l'espace de travail (fenêtre de réglages déjà chargée) | 180 ms | |

Ce qui a coûté (cProfile) : le REMPLISSAGE ANTICRÉNELÉ (28 ms, proportionnel à la surface) et le TRAIT
ANTICRÉNELÉ DE COURBES par Qt (37 ms). Remèdes : contours tracés en polylignes aplaties dans l'espace écran
(`GlyphCanvas._stroke`, 2 ms), remplissage sans anticrénelage PENDANT un geste seulement (`interacting`, net au
relâché et 160 ms après le dernier cran de molette), fond + grille + métriques en image gardée (`_background`),
nœuds regroupés par aspect (`drawLines` / `drawRects`), stylo d'1 px entier.

Piège des tests : `QTest.qWait` GARDE le verrou Python avec PySide 6.11 ; un fil de fond (compilation de
l'aperçu HarfBuzz) n'avance pas pendant l'attente. Attendre avec `time.sleep` + `processEvents`
(`PaneTest.flush`). L'appli réelle (`app.exec`) libère le verrou.

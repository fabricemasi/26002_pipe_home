# Module typographique `fm_font/` : état des fonctions

Partie de la doc du module ; entrée, carte et PASSATION : `docs/agents/fm_font.md`.

## État des fonctions

Légende : TERMINÉ (fonctionne, sauvegardé si besoin, testé) / PARTIEL / NON COMMENCÉ / BLOQUÉ.

| Fonctionnalité | Statut | Remarques |
|---|---|---|
| Modèle, projet, sauvegarde atomique, réouverture, récupération | TERMINÉ | `ProjectTest` |
| Glyphes : créer, supprimer (refus si composant), dupliquer, renommer partout, Unicode | TERMINÉ | modèle ; interface : voir plus bas |
| Bézier (modèle) | TERMINÉ | `BezierTest` (division exacte, tolérance cu2qu testée à 0,25 / 1 / 4 u) |
| Géométrie (modèle) : transformations, symétrie, booléens, chevauchements, simplification, arrondi des coordonnées, COINS ARRONDIS, alignement, mesures | TERMINÉ | `GeometryTest` ; coins arrondis entre lignes, cubiques ET quadratiques (segments raccourcis par division exacte, arc tangent ; rayon exact entre droites ; 2026-10-31 : un segment quadratique du coin passe d'abord en cubique, élévation de degré exacte, le reste du contour reste quadratique ; échec = contour intact, MÊMES objets Point ; coins repérés par objet, 4 coins en 0,4 ms) |
| Crayon, calligraphie (modèle) | TERMINÉ | pression = 3e valeur des échantillons |
| Composants, ancres, accentués, cycles (modèle) | TERMINÉ | propagation structurelle testée |
| Métriques, crénage, aide automatique (modèle) | TERMINÉ | suggestions jamais appliquées seules |
| Features : vérification, génération liga / dlig / smcp / c2sc / onum / lnum / tnum / pnum / case / salt / ssXX / frac | TERMINÉ | frac : barre, numérateurs, dénominateurs après la barre (« 12/34 » vérifié par HarfBuzz) ; exige .numr ET .dnom |
| Compilation OTF / TTF / WOFF / WOFF2, vérifiée fontTools + HarfBuzz (crénage, liga, mark, mkmk) | TERMINÉ | `CompileTest` |
| Masters, interpolation, police variable (fvar / gvar / STAT / avar, instances) | TERMINÉ | `test_fm_font_axes` (avar relue par fontTools, chasse vérifiée par HarfBuzz) |
| Import TTF / OTF / WOFF / WOFF2 / SVG, features comprises | TERMINÉ | GSUB simples / multiples / alternatives / ligatures repris en .fea, marques (MarkBase / MarkMark) en ancres ; même mise en forme HarfBuzz après réexport (testé) ; NON repris, avec message : lookups contextuels, GPOS simples / cursifs / MarkLig |
| Diagnostic trois niveaux | TERMINÉ | FontBakery installé dans `.venv` (FAIL -> avertissement, WARN -> suggestion) |
| Interface : espace de travail, pages, barre, état « modifié », fermeture prudente | TERMINÉ | `test_fm_font_pane` |
| Grille : recherche (nom, caractère, U+), filtres, manquants (création au double-clic), menus | TERMINÉ | virtualisée |
| Éditeur : canvas, zoom / pan, règles + repères, grille, métriques, rempli / contour / comparaison | TERMINÉ | `test_fm_font_canvas` |
| Outils : sélection (points, segments, contours, cadre), plume, crayon, rectangle, ellipse, polygone / étoile, calligraphie, brosse, mesure, couteau, main | TERMINÉ | gestes simulés testés ; couteau : `test_fm_font_knife` (aire conservée, « o » -> deux C) |
| Saisie numérique précise (coordonnées, chasse, approches, Unicode, nom ; métriques de famille) | TERMINÉ | tableaux des réglages |
| Aperçu : ligne, paragraphe, cascade, masters ; crénage visuel (Alt + flèches, Ctrl + glisser) ; HarfBuzz + features | TERMINÉ | compilation de fond |
| Éditeur de features : erreurs lisibles, génération, application | TERMINÉ | |
| Diagnostic (page) + FontBakery facultatif | TERMINÉ | FontBakery dans un FIL (~4,5 s ; l'interface n'attend pas), résultats dans le tableau ; vrai passage : test `--lent` |
| Masters dans l'interface : ajout (copie compatible), choix, comparaison, compatibilité | TERMINÉ | |
| Instances nommées (éditeur dans le panneau Masters ; fvar de la police variable ; exports statiques interpolés) | TERMINÉ | `InstancesTest`, `test_fm_font_axes` ; plusieurs axes (« Bold Condensed wght=700 wdth=75 ») |
| Polices couleur COLR v0 / v1 / CPAL (palette, calques en aplat ou dégradé linéaire / radial ; panneaux ; couleurs peintes dans l'aperçu et, atténuées, derrière le glyphe dans l'éditeur) | TERMINÉ | `test_fm_font_color` (tables relues par fontTools, pixels de l'aperçu) ; dégradés à deux couleurs, sans transformation ni composition (PaintTransform / PaintComposite) |
| Hinting TrueType (ttfautohint) : export TTF / WOFF2 hinté ; hinting PostScript (otfautohint) : export OTF hinté | TERMINÉ | `test_fm_font_color` (hstem / vstem, BlueValues, StdVW / StdHW relus) ; zones et fûts DÉDUITS si la famille n'en a pas (la source n'est pas modifiée) |
| Classes de crénage depuis la grille (gauche, droite, retirer) | TERMINÉ | |
| Branchement fenêtre principale (double-clic, plein cadre, modes exclusifs, fermeture) | TERMINÉ | `test_fm_font_integration` |
| Menu de colonne « Créer un projet typographique » | TERMINÉ | |
| Réglages `typo_*` (catalogue, fenêtre du module, direct) | TERMINÉ | |
| Récupération après plantage (secours du travail non enregistré, toutes les 60 s, en fond) | TERMINÉ | `test_fm_font_autosave` |
| Métriques DANS la vue : tirer la ligne de chasse / d'origine | TERMINÉ | `test_metrics_dragged_in_view` |
| Chaînes de contrôle dans l'aperçu (minuscules, capitales, chiffres, rondes, glyphe courant) | TERMINÉ | menu du mode de l'aperçu |
| Axes (plusieurs, ajout / retrait / renommage) et cartes avar : édition ; position de conception du master courant | TERMINÉ | panneau Masters, « Variation » ; un changement de carte garde la position UTILISATEUR des masters |

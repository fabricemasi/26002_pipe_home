# Module typographique `fm_font/` : décisions

Partie de la doc du module ; entrée, carte et PASSATION : `docs/agents/fm_font.md`.

## Décisions

- **Bibliothèques** (évaluées le 2026-10-30, Python 3.12 Windows, roues binaires présentes) :
  fontTools 4.66 (MIT, compilateur feaLib / varLib, cu2qu), ufoLib2 0.19 (Apache-2.0, modèle UFO 3),
  ufo2ft 3.10 (MIT, compilateur UFO -> OTF / TTF / variable, feature writers kern / mark),
  uharfbuzz 0.57 (Apache-2.0, HarfBuzz), skia-pathops 0.9 (BSD-3, booléens), brotli (MIT, WOFF2).
  FACULTATIFS (importés seulement à l'usage) : afdko 5.0 (Apache-2.0, otfautohint : hinting CFF), FontBakery 1.1
  (Apache-2.0, ~25 dépendances ; lancé par `python -m fontbakery` dans un processus à part, depuis un fil).
  ÉCARTÉS : fontmake (simple surcouche CLI d'ufo2ft), booleanOperations direct (pathops plus robuste ; ufo2ft le
  tire).
  Aucun compilateur OpenType ni moteur de mise en forme réécrit.
- **Modèle = objets ufoLib2** (UFO 3 natif) enveloppés par `FontProject` : rien à traduire à l'enregistrement,
  données inconnues préservées (lib, data/, images/ ; testé). Ouverture NON paresseuse (`lazy=False`) : la
  sauvegarde atomique renomme le dossier, un UFO paresseux relirait l'ancien.
- **Projet** : un `.ufo` (un master) ou un `.designspace` + `masters/<Famille>-<Style>.ufo`. Les opérations sur
  les glyphes (créer, supprimer, renommer…) touchent TOUS les masters (compatibilité d'interpolation).
- **Sauvegarde atomique** : UFO écrit dans `<nom>.fmf-tmp`, l'ancien renommé `<nom>.fmf-bak`, échange, copie
  supprimée ; `recover_interrupted_save` (appelé à l'ouverture) restaure ou nettoie. Renommage réessayé (Windows,
  dossier synchronisé : PermissionError brève). Fichier importé (TTF…) jamais écrasé (`project.source`, export
  refusé sur ce chemin).
- **Annulation** : une étape par geste (instantané au clic, étape au relâché) ; instantané en tuples (0,06 ms pour
  400 points), jamais de deepcopy pendant un mouvement.
- **Sens des contours** : convention PostScript / UFO (extérieur anti-horaire) ; ufo2ft inverse pour le TTF.
- **kern / mark / mkmk** : générés par ufo2ft depuis le crénage et les ancres (pas écrits dans le .fea).
- **Interpolation** : le modèle de variation de fontTools (le même que la police variable) ; un glyphe incompatible
  lève `InterpolationError` avec la raison exacte, jamais de résultat faux silencieux.
- **Coordonnées** (convention du Designspace) : min / défaut / max d'un axe en valeurs UTILISATEUR (fvar) ;
  positions des masters et des instances en valeurs de CONCEPTION ; la carte de l'axe (avar) les relie.
  L'interpolation normalise dans l'espace de conception (`axes.design_ranges`). L'éditeur des instances parle
  utilisateur ; « Position du master » parle conception. Changer une carte garde la position UTILISATEUR des
  masters (aucun refus surprise) ; on corrige ensuite leur position de conception.
- **Réglages** : préfixe `typo_` (le préfixe `font_` est déjà celui des polices de l'interface). Tolérances en
  DIXIÈMES (curseurs entiers des réglages, `scale: 10`). Appliqués en direct au module ouvert
  (`settings_link._apply_settings`, chemin rapide des clés `typo_`).
- **Accès** (2026-10-30) : double-clic sur une source (`.ufo` = DOSSIER, `.designspace`) ou une police
  (`.ttf`, `.otf`, `.woff`, `.woff2`, importée) dans une colonne (réglage `typo_open_double_click`, vrai par
  défaut) ; menu d'une colonne (zone vide) « Créer un projet typographique » (UFO vierge, puis double-clic). Pas
  d'accès depuis le Board (un projet de police n'est pas un élément de tableau blanc). Modes exclusifs : ouvrir
  l'éditeur Markdown, le board ou la vidéo ferme d'abord le module (`_leave_font`, questions si modifié) ; fermer
  l'appli aussi (`closeEvent`).
- **Ctrl + glisser** (règle de l'appli) : composants et repères se DÉPLACENT avec Ctrl ; nœuds, poignées, ancres
  et crénage à la souris dans l'aperçu (Ctrl + glisser aussi) ; les nœuds et poignées sont des gestes d'édition
  du tracé, tirés sans Ctrl (comme les poignées du CAD et la grille du Tableur).
- **Import** : une police compilée importée n'est PAS « modifiée » tant qu'on n'y touche pas (rien à perdre) ;
  « Enregistrer » demande où écrire la source ; l'export refuse le chemin d'origine.
- **Couleur** : COLR v0 / CPAL par les clés de lib d'ufo2ft (`com.github.googlei18n.ufo2ft.colorPalettes`,
  `.colorLayers`) ; un calque = un glyphe ordinaire. COLR v1 : la DESCRIPTION du dégradé (`fm_font.colorLayers`)
  fait foi ; la peinture v1 de la clé d'ufo2ft est recalculée à chaque compilation sur la boîte actuelle du
  calque (`color.compile_layers`), jamais un dégradé décalé après un redessin.
- **Secours** : `%LOCALAPPDATA%/fm_font/secours/<clé>/` (clé = empreinte du chemin ; `FM_FONT_AUTOSAVE_DIR` dans
  les tests, jamais le vrai dossier). Sur le fil de l'interface seulement l'instantané en tuples (6,5 ms pour
  1000 glyphes ; un `deepcopy` coûtait 177 ms) ; reconstruction + écriture dans un fil. `secours.json` écrit en
  dernier (sans lui, le secours n'est pas valable). Proposé à l'ouverture s'il est plus récent que le fichier ;
  supprimé après un enregistrement, une fermeture voulue ou un refus.
- **Export en fond** : la compilation (~2 s pour 1000 glyphes, surtout la suppression des chevauchements) ne
  fige jamais l'interface : instantané du projet (`autosave.snapshot`), projet INDÉPENDANT reconstruit dans le fil
  (`project_from_snapshot`), résultat dans la barre d'état. Modifier le projet pendant l'export ne change pas la
  police produite (testé).
- **Hinting** : ttfautohint (ttfautohint-py, roue Windows avec binaire) pour le TrueType ; sans « o » latin, repli
  automatique en mode symbole. CFF : otfautohint d'afdko dans le processus (`--processes 1`, jamais de pool
  de processus qui relancerait l'appli sous Windows) ; BlueValues déduites des métriques, StdVW / StdHW
  mesurés sur l, I, n, H / o, H, e (repli 8 % / 7 % du cadratin), posés le temps de la compilation seulement.

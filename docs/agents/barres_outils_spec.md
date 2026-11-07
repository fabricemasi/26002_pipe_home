# Barres d'outils flottantes et aimantées : spécification

Référence exacte : `prototype_barres_outils.html` (prototype validé par l'utilisateur). En cas de doute, le code du prototype fait foi : fonctions `computeSnap`, `measureTouch`, `dropTarget`, `onMove` / `onUp`, `renderVals`.

> **AMENDEMENT DE L'UTILISATEUR (2026-11-02, capture annotée sur la barre « Créer »), prioritaire sur le prototype :**
> - la barre est une **GRILLE de cases de la taille d'une icône** (34 px + écart 4) : une icône se pose dans **n'importe quelle
>   case libre** (y compris les cases vides à droite), un bouton à texte ou un contrôle occupe n cases de large ;
> - la barre se **redimensionne par ses bords**, toujours **accrochée à cette grille** (jamais plus petite que son contenu ni
>   que son titre ; barre clipsée : le bord qui ne touche pas la fenêtre) ; la **largeur d'un contrôle** s'accroche aussi à la
>   grille (cases entières, 120 à 520 px) ;
> - **marges égales** : à gauche, à droite et en bas (6 px), le titre en haut (ou à gauche, barre verticale) ;
> - **plus de poignée d'étages** (§ 5 supprimé) ; une barre qui pivote ou se clipse sur un bord latéral voit sa grille
>   **transposée** (3 × 2 -> 2 × 3), puis retrouve exactement sa disposition en revenant à son sens pendant le geste ;
> - pendant un déplacement d'élément : la case visée est cernée d'accent (la plus proche libre si elle est prise ; une barre
>   pleine s'agrandit d'une case pour l'accueillir) et les cases libres apparaissent en pointillés ; une case vidée reste
>   libre (la grille garde sa taille).
>
> Ce qui ne change pas : § 3 (déplacer, aimantation en direct), § 4 (coins, bordures, ombre), dépôt dans le vide, barre
> vidée supprimée, § 7, § 8 (hors largeur en cases), § 9, critères 1-5 et 7-11 (le 6 devient : redimensionnement accroché
> à la grille).
>
> **2026-11-03** : quatre contrôleurs (slider, liste déroulante, zone de saisie, toggle) au même cadre, avec leurs
> réglages propres ; deux contrôleurs qui se touchent (écart ≤ réglage, 1 px par défaut) n'ont pas d'arrondi entre eux ;
> une barre rétrécie retasse ses icônes ; les barres d'un même bord se poussent au lieu de se chevaucher.

Règle de partage du projet :
- **fm_theme** = l'apparence : variante « barre d'outils » avec ses éléments (cadre, titre, poignées, icône, slider, saisie, menu, case de dépôt, trait d'aimantation).
- **Modules** = le comportement et le contenu de leurs barres.
- Le moteur (déplacement, aimantation, étages, glisser des éléments) est générique, dans fm_theme ou un module commun que tous les modules utilisent. Aucun module ne le recode.

## 1. Modèle

- Une **barre** contient :
  - `id`, `title` ;
  - `items` : liste ordonnée d'identifiants d'éléments ;
  - `rows` : nombre d'étages, ≥ 1 ;
  - `dock` : `top`, `bottom`, `left`, `right` ou `None` ;
  - `x`, `y` : position flottante, ou position le long du bord si la barre est clipsée ;
  - `orient` : `h` ou `v`.
- **Orientation effective** : `h` si clipsée en haut ou en bas, `v` si clipsée à gauche ou à droite, sinon `orient`.
- Un **élément** a un type : `icon`, `slider`, `input` ou `select`.
  - icon : libellé, glyphe, couleur.
  - slider : min, max, pas, unité.
  - input : texte indicatif.
  - select : options.
- Les **valeurs** des contrôles et leurs **largeurs** sont rangées à part, par identifiant d'élément. Elles suivent donc l'élément quand il change de barre.
- Tout est enregistré : barres, ordre, étages, clipsage, positions, largeurs, valeurs. Une barre clipsée à droite ou en bas est positionnée par rapport à CE bord (`right: 0` / `bottom: 0`) : sa taille peut changer sans recalcul.

## 2. Taille automatique

La barre n'a jamais de taille fixe : c'est la taille de son contenu (titre + éléments + poignée d'étages).

- **Horizontale** : titre au-dessus, puis les éléments en LIGNES ; poignée d'étages en dessous.
- **Verticale** : titre à gauche, écrit de bas en haut (rotation de 180°), puis les éléments en COLONNES ; poignée à droite.
- **Répartition** : `par_étage = ceil(n / rows)`. Les éléments sont découpés dans l'ordre en morceaux de `par_étage`. Chaque morceau forme une ligne (barre horizontale) ou une colonne (barre verticale) et prend sa largeur naturelle. Les étages sont espacés de 4 px.
- **Dimensions** : icône 34 × 34, écart de 4 px entre éléments, padding de 6 px autour des éléments.
- **Titre** : 10 px, graisse 600, capitales, espacement des lettres 0,08 em, avec une poignée « ⋮⋮ » de 12 px avant le texte.

## 3. Déplacer une barre (par son titre)

- **Glisser le titre** déplace la barre. Ctrl+clic sur le titre ne déplace pas : il renomme (§ 7).
- **Aimantation EN DIRECT** : la barre affichée est TOUJOURS à sa position aimantée, pendant tout le geste, pas seulement au relâchement. Seuil `SNAP` = 24 px (réglable).
- **Calcul à chaque mouvement** (`computeSnap`) :
  1. La position brute est bornée à la fenêtre. On mesure la distance aux 4 bords. Si la plus petite est sous `SNAP`, la barre se **clipse sur ce bord** :
     - elle prend l'orientation du bord tout de suite, pendant le geste ;
     - sa position le long du bord s'aimante (seuil `SNAP`) à 0, au bout du bord, et aux deux côtés de TOUTE autre barre présente dans la bande de ce bord, qu'elle soit clipsée sur ce bord, sur un bord voisin ou flottante.
     - Pour ces calculs, la taille dans la nouvelle orientation est estimée en échangeant largeur et hauteur.
     - Un trait de 3 px de la couleur d'accent, avec une lueur, longe tout le bord concerné.
  2. Sinon, la barre est **flottante** et s'aimante (seuil `SNAP`) aux autres barres :
     - **contact** : contre le côté droit ou gauche d'une barre qui la chevauche verticalement, contre le dessous ou le dessus d'une barre qui la chevauche horizontalement ;
     - **alignement** de ses bords gauche, droit, haut et bas sur ceux des autres barres.
     - **Exception, barre clipsée** : elle n'offre que ses deux côtés le long de son bord. Sa face intérieure (celle tournée vers la fenêtre) n'est PAS aimantable, et elle n'offre aucun alignement perpendiculaire à son bord. Exemple : une barre clipsée en haut n'attire rien sous elle et rien ne s'aligne sur son bas.
     - **Contact avec une barre clipsée** : si, après aimantation, la barre touche un côté le long du bord d'une barre clipsée, elle se **clipse sur ce même bord**, collée à ce côté. Une barre ne reste jamais suspendue en l'air contre une barre clipsée.
     - **Contact avec une barre flottante** : un trait d'accent de 3 px est tracé sur la partie commune.
- **Au relâchement** : la position aimantée est posée. La barre passe au premier plan. La barre d'état affiche « « Titre » clipsée en haut / à gauche… » ou « « Titre » flottante ».
- **Double-clic sur le titre** d'une barre flottante : elle bascule entre horizontale et verticale.

## 4. Coins et bordures (mesurés après chaque mise en page : `measureTouch`)

Les rectangles réels de toutes les barres sont relevés. Tolérance : 1,5 px.

- **Coin** : rayon de 8 px (réglable). Un coin est CARRÉ si l'un de ses deux côtés est plaqué contre un bord de la fenêtre, OU si une barre voisine collée sur l'un de ses deux côtés COUVRE ce coin, c'est-à-dire qu'elle s'étend au moins jusqu'à l'extrémité de ce côté. Sinon il reste arrondi.
  - Exemple : « Vue » est plus haute que « Créer », qui lui est collée. Le coin bas droit de « Vue » reste arrondi ; les coins gauches de « Créer » sont carrés.
- **Bordure partagée** : 1 px seulement. Sur un côté commun, c'est la barre dont ce côté est le plus COURT qui rend sa bordure transparente : couleur transparente, pas d'épaisseur 0, pour que la taille ne bouge pas. La plus longue garde la sienne, continue.
  - Côtés de même longueur : c'est la barre de droite (côte à côte) ou du dessous (l'une sur l'autre) qui l'efface.
- **Ombre** : barre flottante seulement, aucune ombre quand elle est clipsée. Ombre plus forte pendant le déplacement, avec une opacité de 0,94.

## 5. Étages

- **Poignée** : bande de 8 px sur le côté INTÉRIEUR de la barre, avec une marque de 18 × 2 px (ou 2 × 18).
  - Barre clipsée en haut → poignée en bas ; en bas → en haut ; à gauche → à droite ; à droite → à gauche.
  - Barre flottante → en bas si elle est horizontale, à droite si elle est verticale.
- **Tirer la poignée** : `rows = clamp(départ + round(delta / 38), 1, nombre d'éléments)`. Le delta est inversé pour une poignée en haut ou à gauche. La barre d'état affiche « « Titre » : n étages ».
- Quand des éléments sont retirés, `rows` est ramené au nombre d'éléments au plus.

## 6. Éléments : déplacer, déposer, créer une barre

- **Prise** :
  - icône : on la tire directement ;
  - slider, saisie, menu : on les tire par leur poignée « ⋮⋮ » de 16 px à gauche. Le contrôle lui-même reste utilisable normalement.
- **Seuil** : le glisser démarre après 4 px. En dessous, un clic sur une icône la sélectionne comme outil actif : fond accent à 20 %, bordure accent.
- **Pendant le glisser** :
  - l'élément disparaît de sa barre ;
  - une vignette suit le curseur : l'icône, ou une étiquette « Type Libellé » pour un contrôle ;
  - la barre visée passe en bordure accent et montre une **case de dépôt** en pointillés accent, à la largeur de l'élément, à l'endroit d'insertion.
- **Indice d'insertion** (`dropTarget`), en ordre de lecture :
  - barre horizontale : un élément compte « avant » le curseur si `y > bas + 2`, ou si `y ≥ haut − 2` et `x > centre` ;
  - barre verticale : si `x > droite + 2`, ou si `x ≥ gauche − 2` et `y > centre`.
  - La case de dépôt n'est pas un élément : elle n'entre pas dans ce calcul.
- **Dépôt dans le vide** : une nouvelle barre flottante horizontale « Barre N » est créée sous le curseur, et la vignette affiche « + Nouvelle barre » avant le dépôt.
- **Barre vide après un retrait** : elle est supprimée.

## 7. Renommer

Ctrl+clic sur un titre ouvre une zone de saisie à sa place :
- Entrée ou clic ailleurs : valide ;
- Échap : annule ;
- texte vide : le titre ne change pas.

## 8. Contrôles

- **Cadre commun** : 34 px de haut, bordure 1 px, rayon 6, poignée de déplacement à gauche, libellé.
- **Slider** : piste extensible (40 px au moins), puis la valeur et son unité, alignées à droite, en chiffres de largeur fixe.
- **Saisie** : champ extensible (40 px au moins). Les touches tapées ne déclenchent aucun raccourci.
- **Menu déroulant** : liste extensible (50 px au moins).
- **Largeur réglable** (slider, saisie, menu) : poignée de 9 px sur le bord droit, avec un trait de 2 × 14 px. Tirer la poignée change la largeur entre 120 et 520 px. C'est la piste ou le champ qui s'étire ; libellé et valeur gardent leur taille. La largeur est enregistrée par élément, et la barre s'adapte.
- **Largeurs d'origine** : Opacité 220, Taille 214, Nom 180, Chercher 196, Fusion 170, Police 170.

## 9. Barre d'état

Chaque action affiche une ligne, par exemple :
- « Outil : … »
- « Texte → « Créer » »
- « Nouvelle barre « Barre 7 » — Ctrl+clic sur son titre pour la renommer »
- « « X » vide, supprimée »
- « Opacité : 80 % »

## 10. Critères d'acceptation (à vérifier un par un)

1. Approcher un bord à moins de 24 px : la barre s'y colle AVANT le relâchement et change d'orientation tout de suite.
2. Deux barres côte à côte n'ont qu'un filet de 1 px entre elles. Le filet restant est celui de la barre la plus haute (ou la plus large).
3. Les coins collés à un bord de la fenêtre ou couverts par une voisine sont carrés ; les autres restent arrondis.
4. Rien ne s'aimante sous une barre clipsée en haut, et rien ne s'aligne sur son bas.
5. Une barre collée au côté d'une barre clipsée en haut monte dans la rangée du haut ; elle ne flotte jamais.
6. La poignée d'étages répartit les éléments en lignes, ou en colonnes pour une barre verticale.
7. Icônes et contrôles passent d'une barre à l'autre, avec la case de dépôt au bon endroit. Un dépôt dans le vide crée une barre ; une barre vide disparaît.
8. Les sliders, saisies et menus restent utilisables, et leur largeur se règle par la poignée de droite.
9. Ctrl+clic sur un titre le renomme ; un double-clic sur une barre flottante la fait pivoter.
10. Tout est retrouvé après un redémarrage.
11. Tout est FLUIDE (règle n° 1 du projet) : aucun calcul lourd par mouvement de souris, mesures dans le rapport.

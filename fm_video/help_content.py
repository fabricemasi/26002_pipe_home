"""Base pédagogique centrale, sans calcul ni accès disque dans les interactions."""
from html import escape

SOURCES = (
    ('Couleurs et espaces perceptuels — W3C', 'https://www.w3.org/TR/2024/CRD-css-color-4-20240213/'),
    ('Espaces de référence — OpenColorIO', 'https://opencolorio.readthedocs.io/en/main/guides/authoring/authoring.html'),
)

# Définitions propres à l'application ; le contexte du signal doit rester explicite.
GLOSSARY = {
    'RGB': 'Trois composantes rouge, verte et bleue. Leurs valeurs ne définissent une couleur que si les primaires, le blanc et la fonction de transfert sont connus.',
    'HSV / HSL': 'Coordonnées de teinte et de saturation dérivées du RGB. V et L ne sont pas une luminance physique ; un changement de teinte à V constant ne conserve pas forcément la luminosité perçue.',
    'CIELAB': 'Espace perceptuel relatif à un blanc de référence : L* représente la clarté, a* et b* deux axes chromatiques. La conversion nécessite une définition du blanc et une gestion de l’adaptation chromatique.',
    'OKLab': 'Espace perceptuel à axes L, a et b. Le clustering de cette application compare les distances euclidiennes dans cet espace après décodage sRGB. Il reste une approximation de la perception.',
    'XYZ': 'Coordonnées tristimulus de colorimétrie. Y représente la luminance ou une luminance relative selon la normalisation ; x et y décrivent la chromaticité quand la somme XYZ est non nulle.',
    'Luminance': 'Grandeur liée au flux lumineux pondéré par la sensibilité visuelle photopique. Ici Y est une luminance relative calculée après décodage sRGB, sans unité absolue en cd/m².',
    'Luma Y′': 'Somme pondérée de composantes RGB déjà encodées. Le waveform BT.709 du proxy montre Y′ ; ce n’est pas le Y linéaire des statistiques.',
    'Luminosité': 'Terme d’apparence visuelle dépendant aussi du contexte d’observation. Une moyenne de pixels ne décrit pas à elle seule cette sensation.',
    'Saturation': 'Importance de la composante colorée relativement à une référence achromatique. Les définitions varient selon l’espace ; la saturation HSV et une distance dans OKLab ne sont pas interchangeables.',
    'Chrominance': 'Information de couleur distincte de la composante lumineuse dans une représentation donnée. Cb/Cr expriment des différences de composantes dans le signal vidéo encodé.',
    'Gamma': 'Paramètre d’une relation de puissance. sRGB utilise une fonction par morceaux, pas une simple puissance 2,2 sur tout le domaine.',
    'Gamut': 'Ensemble des couleurs représentables dans un espace ou par un appareil. Une couleur hors gamut n’est pas nécessairement trop lumineuse.',
    'Dynamic Range': 'Étendue entre les niveaux lumineux exploitables, souvent exprimée en stops. La profondeur de codage seule ne détermine pas la dynamique de la scène capturée.',
    'Contraste': 'Rapport ou écart entre niveaux selon la définition choisie. Le contraste global et le contraste local décrivent des propriétés différentes.',
    'Balance des blancs': 'Adaptation des composantes pour rendre neutre un éclairage de référence. Une moyenne RGB déséquilibrée peut venir des objets dans la scène, et ne prouve pas une balance incorrecte.',
    'Température de couleur': 'Description d’une chromaticité proche du lieu des corps noirs, exprimée en kelvins lorsqu’elle est définie. Le curseur de correction du module n’est pas un thermomètre de scène.',
    'Espace colorimétrique': 'Définition reliant les valeurs numériques à des couleurs : primaires, blanc, encodage et contexte doivent être précisés.',
    'Fonction de transfert': 'Relation entre valeurs de signal et lumière ou représentation de scène. Ne pas appliquer deux fois la même conversion.',
    'Scene-Referred': 'Représentation relative à la lumière de la scène. Les valeurs peuvent dépasser 1 sans être invalides ; une transformation d’affichage est nécessaire pour les observer.',
    'Display-Referred': 'Représentation liée à un rendu destiné à un affichage. Le matching actuel opère sur le proxy sRGB SDR affiché, pas sur les données linéaires de tournage.',
    'ACES': 'Système de gestion des couleurs pour la production d’images. Ses espaces de travail et ses transforms d’affichage ont des rôles différents ; choisir ACES ne dispense pas de déclarer l’entrée.',
    'OCIO': 'OpenColorIO décrit et applique des transformations entre espaces et affichages. Le module vidéo possède déjà un pipeline OCIO ; le matching SDR ne l’incorpore pas dans ses LUT.',
    'LUT 1D': 'Table de correspondance appliquée séparément aux composantes. Elle ne représente pas une transformation générale avec interactions entre canaux.',
    'LUT 3D': 'Grille RGB dont les résultats intermédiaires sont interpolés. Elle décrit une transformation globale des valeurs, pas une correction dépendant de la position ou de la scène.',
    'Tone Mapping': 'Adaptation d’une plage lumineuse à celle d’un affichage. Ce traitement est distinct d’une conversion de primaires.',
    'Gamut Mapping': 'Remappage des couleurs vers un gamut cible. Un simple écrêtage peut modifier les teintes et perdre des différences de couleur.',
    'Delta E': 'Distance de couleur définie par une formule et un espace précis. Un RMSE RGB n’est pas un Delta E ; comparer deux scènes différentes pixel à pixel n’a généralement pas de sens.',
    'Histogramme': 'Comptage des pixels par classe de valeur, sans information sur leur position. Ici les mesures utilisent un échantillon réparti du proxy ou de la région sélectionnée.',
    'Waveform': 'Répartition des niveaux en fonction de la position horizontale dans l’image. Dans ce module, Y′ BT.709 encodé est affiché pour le proxy SDR.',
    'Vectorscope': 'Distribution de chrominance. Le centre correspond aux neutres ; l’éloignement traduit une amplitude chromatique dans les coordonnées choisies, pas une saturation universelle.',
    'Lift / Gamma / Gain': 'Corrections du pied, des tons intermédiaires et du gain. L’effet dépend de l’ordre et de l’espace de travail ; les paramètres du module vidéo suivent son pipeline documenté.',
    'Log Encoding': 'Encodage non linéaire conçu notamment pour répartir une grande dynamique de scène. Une image Log demande la transformation adaptée, et non une simple augmentation du contraste.',
    'HDR / SDR': 'Contextes de restitution et d’encodage de dynamique différents. La palette et le matching de proxy sRGB SDR ne mesurent pas le signal HDR source.',
    'Clipping': 'Limitation d’une valeur à une borne. Un canal à 0 ou 255 dans un proxy ne prouve pas qu’une information a été perdue dans le fichier original.',
    'Exposition': 'En linéaire, un réglage de +1 stop multiplie les valeurs par 2. Ajouter une constante à un RGB encodé ne réalise pas la même opération.',
    'Régularisation': 'Contrainte qui pénalise les solutions instables ou excessivement éloignées d’un modèle de référence. Le matching de paire est ramené vers l’identité lorsque les données ne suffisent pas.',
    'RMSE RGB': 'Racine de la moyenne des carrés des erreurs sur les composantes RGB normalisées. Une valeur faible décrit l’erreur numérique sur les échantillons évalués ; elle ne constitue pas un score perceptuel.',
    'Interpolation LUT': 'Estimation entre les nœuds de la grille. L’export utilise et vérifie une interpolation trilinéaire ; augmenter la résolution réduit certaines erreurs au prix de fichiers plus lourds.',
    'Profil ICC': 'Description de la relation entre les valeurs d’un fichier ou d’un appareil et la colorimétrie. Le matching convertit les profils reconnus vers sRGB ; sans profil, l’hypothèse sRGB est affichée.',
}


def _entry(title,definition,purpose,reading,usage,example,relations,technical,caution):
    return dict(title=title,sections=list(zip(
        ('Définition','À quoi sert-il ?','Comment l’interpréter ?','Comment l’utiliser ?',
         'Exemple concret','Relations avec les autres outils','Explication technique','Points d’attention'),
        (definition,purpose,reading,usage,example,relations,technical,caution))))


HELP = {
    'palette': _entry('Palette chromatique / OKLab',GLOSSARY['OKLab'],
        'Résumer les familles de couleurs de l’image sélectionnée.',
        'Chaque rectangle correspond à un groupe ; le pourcentage est sa part dans l’échantillon conservé.',
        'Changer le nombre de couleurs ; trier par clarté ou proportion. Cliquer copie la valeur HEX.',
        'Comparer les verts sombres et les gris froids d’une scène de bureau.',
        'La région et les exclusions changent la palette. La pipette mesure un seul pixel.',
        'Échantillonnage borné, clustering de Lloyd en OKLab, initialisation déterministe ; couleurs représentées en RGB sRGB.',
        'Une couleur rare peut ne pas être échantillonnée. Une dominante statistique ne prouve pas une intention d’étalonnage.'),
    'histogram': _entry('Histogrammes RGB et luminance',GLOSSARY['Histogramme'],
        'Observer la distribution des niveaux et les concentrations aux extrémités.',
        'Abscisse : 0–255 pour RGB encodé ; 0–1 pour Y linéaire. Ordonnée : nombre de pixels échantillonnés par classe.',
        'Afficher les canaux voulus ; activer l’échelle logarithmique pour voir les classes peu peuplées.',
        'Un plan de nuit peut avoir beaucoup de pixels bas sans qu’il soit sous-exposé.',
        'Le waveform conserve la position horizontale, contrairement à l’histogramme.',
        '256 classes ; Y = 0,2126 R + 0,7152 G + 0,0722 B après décodage sRGB. Logarithme : log(1 + effectif).',
        'Les exclusions de palette ne changent pas cet histogramme. Les valeurs concernent le proxy, pas la latitude du capteur.'),
    'region': _entry('Pipette et région d’analyse',GLOSSARY['RGB'],
        'Isoler un détail ou une surface neutre sans modifier l’image.',
        'La pipette affiche le pixel du proxy ; le cadre indique la région analysée.',
        'Cliquer pour échantillonner ; glisser pour sélectionner ; double-cliquer pour reprendre toute l’image.',
        'Analyser un mur gris séparément d’un costume vert dominant dans le cadre.',
        'Palette, histogrammes et statistiques sont recalculés sur la région ; les scopes la suivent.',
        'Les coordonnées écran sont converties en coordonnées du proxy en tenant compte de l’ajustement à l’écran.',
        'La pipette n’accède pas aux pixels HDR d’origine. Une petite région peut ne pas représenter le plan entier.'),
    'scopes': _entry('Waveform et vectorscope',GLOSSARY['Vectorscope'],
        'Lire la structure spatiale des niveaux et la distribution chromatique.',
        'Waveform : X est la position dans la région, Y le niveau Y′. Vectorscope : Cb/Cr BT.709, neutres au centre.',
        'Activer le panneau à la demande ; les calculs s’arrêtent lorsqu’il est fermé.',
        'Repérer une dominante cyan dans les ombres et la séparation d’un visage par rapport au fond.',
        'Comparer au Y linéaire des statistiques sans confondre Y et Y′.',
        'Réutilisation du moteur de scopes vidéo ; vecteurs Cb/Cr amplifiés de 1,8 pour la lisibilité.',
        'La ligne des tons chair est un repère, pas un détecteur. Les régions transparentes ne produisent pas de scopes spatiaux.'),
    'matching': _entry('Matching source / référence',GLOSSARY['Display-Referred'],
        'Proposer un transfert global de couleur utilisable comme LUT SDR.',
        'Les erreurs RGB et la fraction hors domaine décrivent le modèle calculé ; aucun score de qualité universel n’est donné.',
        'Scènes différentes : statistiques. Paire alignée : même image avant/après, dimensions et cadrage identiques.',
        'Retrouver un look global à partir d’une image originale et de sa version étalonnée.',
        'L’intensité mélange l’identité et le résultat. La LUT est distincte de la conversion OCIO du lecteur.',
        'Transport affine de covariance régularisé ou régression polynomiale régularisée vers l’identité. Un pixel sur cinq réservé à la validation de paire.',
        'Une référence seule ne détermine pas son étalonnage. Des scènes différentes ont des objets différents : les statistiques peuvent transférer leur contenu autant que leur look.'),
    'lut': _entry('Résolution et export LUT',GLOSSARY['LUT 3D'],
        'Appliquer le modèle global à d’autres médias dans un espace compatible.',
        'N³ nœuds ; le tableau affiche sa mémoire brute. L’erreur d’interpolation est comparée au modèle sur 4096 couleurs.',
        'Choisir 17, 33, 65 ou 129 ; exporter .cube ou un preset natif ; conserver la déclaration sRGB SDR.',
        'Une LUT 33³ peut suffire à un transform lisse ; comparer son erreur avant de choisir une résolution supérieure.',
        'L’export utilise le même modèle que l’aperçu. Un preset retient ses coefficients et son intensité.',
        'Grille indexée [B,G,R], rouge le plus rapide, domaine [0,1], interpolation trilinéaire.',
        'Une LUT globale ne transporte pas de masque spatial ni de réduction de bruit. Ne pas appliquer cette LUT sRGB à du Log sans conversion appropriée.'),
    'background': _entry('Fond de visualisation', 'Gris neutre défini en RGB sRGB d’affichage.',
        'Adapter le contexte visuel autour de l’image sans changer ses pixels.',
        '25 % signifie ici RGB 64, pas 25 % de lumière linéaire.',
        'Choisir un preset ou saisir une valeur 0–255. Vidéo et Moodboard gardent des valeurs indépendantes.',
        'Un fond gris moyen aide à comparer deux images dans un contexte commun.',
        'Ce réglage ne modifie ni histogrammes ni exports du média.',
        'Seul le fond du widget est repeint ; aucune conversion ni régénération de proxy.',
        'La perception du contraste dépend du voisinage ; une image peut sembler différente alors que ses valeurs sont identiques.'),
}

HELP['saturation'] = _entry('Saturation / vibrance',GLOSSARY['Saturation'],
    'Moduler la séparation entre couleurs et neutres sans remplacer le choix du look.',
    'La valeur neutre de saturation est 1. Une vibrance différente agit de manière pondérée selon le pipeline.',
    'Procéder par petits changements, observer les tons chair et les hautes lumières ; comparer avant/après.',
    'Réduire la saturation générale d’un plan puis vérifier que les visages restent plausibles.',
    'Une modification de contraste change aussi la perception de saturation. Le vectorscope aide à lire les excursions chromatiques.',
    'Les corrections du module sont appliquées dans son espace de travail linéaire, avant la transformation d’affichage et les LUT créatives.',
    'La luminance des mélanges dépend des primaires. Les couleurs très saturées peuvent sortir du gamut cible ; la vibrance ne garantit pas la protection des tons chair.')
HELP['exposure'] = _entry('Exposition',GLOSSARY['Exposition'],
    'Déplacer globalement les valeurs de lumière dans l’espace linéaire du module.',
    '+1 stop multiplie par 2 ; −1 stop divise par 2, avant la transformation d’affichage.',
    'Comparer les détails dans les zones claires et les scopes ; utiliser avant/après.',
    'Réduire d’un stop une image linéaire avant une transformation d’affichage qui compresse les hautes lumières.',
    'Le pivot de contraste, les LUT et le tone mapping influencent ensuite l’apparence.',
    'Facteur multiplicatif 2 puissance exposition sur les composantes linéaires de scène.',
    'Ne récupère pas les détails déjà perdus dans le fichier ; un proxy SDR ne permet pas de conclure sur la dynamique HDR originale.')
HELP['ocio'] = _entry('Gestion colorimétrique / OCIO',GLOSSARY['OCIO'],
    'Relier correctement les pixels source, l’espace de travail et l’affichage.',
    'Entrée : interprétation du média ; display/view : rendu pour l’observation.',
    'Déclarer l’espace source réel, choisir une configuration puis un affichage adapté.',
    'Interpréter un EXR linéaire dans son espace puis l’observer via une vue SDR.',
    'La LUT technique peut changer l’interprétation d’entrée. La LUT créative du module agit à une autre étape.',
    'Le pipeline du lecteur sépare les transforms d’entrée, le grading et la transformation de display/view.',
    'Une mauvaise déclaration de source peut produire une image plausible mais fausse. Éviter toute double conversion ou transform d’affichage incorporée involontairement dans un look.')
HELP['grade'] = _entry('Corrections primaires / niveaux',GLOSSARY['Lift / Gamma / Gain'],
    'Ajuster les relations tonales et les composantes sans réécrire le média.',
    'Les valeurs neutres varient : gains/gamma à 1, offsets/lift à 0. Le contrôle garde sa plage numérique propre.',
    'Ajuster un contrôle à la fois ; comparer le résultat et réinitialiser si nécessaire.',
    'Une correction par canal peut neutraliser une ombre ; vérifier qu’elle ne colore pas excessivement les autres zones.',
    'Les niveaux d’entrée/sortie interviennent après l’affichage dans le pipeline ; ils ne sont pas équivalents à l’exposition linéaire.',
    'Le module applique les corrections selon l’ordre documenté dans fm_video/color.py ; les opérations ne sont pas commutatives.',
    'Les LUT et la transformation d’affichage peuvent modifier l’effet perçu. Les points noirs/blancs du proxy ne décrivent pas le gamut ou les limites de capture.')


def key_for_setting(key):
    if key.startswith('vg_'):
        name = key[3:]
        if name=='exposure':
            return 'exposure'
        if name in ('saturation','vibrance'):
            return 'saturation'
        return 'grade'
    if key.startswith('vc_'):
        return 'lut' if 'lut' in key else 'ocio'
    if key.startswith('video_help_'):
        return None
    if key.startswith('video_analysis_'):
        return 'palette'
    if key.startswith('video_match_'):
        return 'lut' if 'size' in key else 'matching'
    if key in ('video_bg_color','video_moodboard_bg_color'):
        return 'background'
    if any(key.startswith('video_'+prefix) for prefix in ('input_','display','view_','ocio_')):
        return 'ocio'
    if key.startswith('video_lut_'):
        return 'lut'
    return None


def page(key):
    if key in HELP:
        entry = HELP[key]
        return '<h2>'+escape(entry['title'])+'</h2>'+''.join(
            '<h3>'+escape(title)+'</h3><p>'+escape(text)+'</p>' for title,text in entry['sections'])
    return '<h2>'+escape(key)+'</h2><p>'+escape(GLOSSARY.get(key,''))+'</p>'

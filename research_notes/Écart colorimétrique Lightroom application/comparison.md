# Comparaison visuelle Lightroom / application

## Que montrent les captures, et quelles causes propres à l’image sont plausibles ?

### Takeaway

Les captures représentent la même photo et restent très proches structurellement, mais leur rendu n’est pas identique : après mise à la même taille, la capture de l’application a des tons moyens et des ombres plus sombres, avec une différence marquée sur la veste. Le cadrage relatif est proche, avec un léger écart de ratio d’image; ces captures seules ne permettent pas d’attribuer l’écart au fichier source, au développement Lightroom, au profil couleur ou au pipeline d’aperçu.

### Cited Findings

- Les fichiers mesurent 1411 × 940 px (capture Lightroom) et 1671 × 1111 px (capture application). Leurs ratios sont respectivement 1,5011 et 1,5041. Pour les mesures comparatives ci-dessous, la seconde capture a été redimensionnée à 1411 × 940 px avec Lanczos; cela aligne les dimensions, mais ne garantit pas un recalage géométrique pixel à pixel. [Capture Lightroom](C:/Users/fabrice/AppData/Local/Temp/codex-clipboard-d06f838a-0950-4267-a7f5-4d18087aa351.png); [capture application](C:/Users/fabrice/AppData/Local/Temp/codex-clipboard-1ae7d2ae-7ed2-4871-941a-6406a70d913c.png)
- Sur ces pixels redimensionnés, la luminance Y’ approximée par 0,2126 R + 0,7152 G + 0,0722 B a une moyenne de 77,90 dans Lightroom contre 73,80 dans l’application, et une médiane de 36,90 contre 28,24. La part des pixels sous Y’ = 20 passe de 13,60 % à 21,85 %; le 95e percentile reste presque égal (211,20 contre 211,65). Ce profil est cohérent avec des ombres plus denses dans la capture application, mais ne constitue pas une mesure colorimétrique de la photo originale.
- En zones normalisées approximatives, la neige à gauche reste proche (Y’ moyen 166,9 contre 165,3), alors que la zone centrale de la veste passe de Y’ 43,7 à 33,9 et la zone droite de la veste de 48,8 à 43,2. La moyenne RGB globale baisse de (87,6, 74,4, 84,2) à (86,5, 69,2, 82,1). Les écarts ne sont donc pas décrits par une simple hausse uniforme de luminosité dans la seconde capture.
- Après simple redimensionnement, la corrélation des luminances entre captures est de 0,990 et l’erreur absolue moyenne RGB est de 6,76 niveaux sur 255. La forte corrélation appuie l’identification de la même scène; l’erreur résiduelle combine le rendu, l’échelle, l’échantillonnage et d’éventuels petits décalages de cadrage.
- Les deux PNG déclarent le marqueur sRGB et gamma 0,45455 dans leurs métadonnées PNG; aucun profil ICC distinct n’apparaît dans les métadonnées lues. Cela décrit les captures d’écran fournies, pas nécessairement le profil de la photo source ni la gestion couleur effective des fenêtres au moment des captures.
- Le code du dépôt lit les aperçus JPEG du cache Lightroom `Previews.lrdata` et applique l’orientation enregistrée; si ce cache n’a pas encore l’aperçu, il peut décoder localement la photo et afficher ce secours avant qu’un aperçu Lightroom ne le remplace. L’origine est suivie comme `lightroom` ou `application`. [lightroom_bridge.py](F:/SYNC/Sync/PROG/26002_pipe_home/lightroom_bridge.py)
- Pour ce secours local, le code appelle le décodeur 2D de l’application; les fichiers RAW utilisent rawpy/LibRaw avec balance des blancs appareil si disponible, sinon la plus grande image JPEG intégrée au RAW. Le secours est enregistré en JPEG qualité 92. Le chemin Lightroom charge directement une image du cache, et les chemins inspectés ne font pas de conversion explicite vers un espace cible avec `convertToColorSpace`. [lightroom_bridge.py](F:/SYNC/Sync/PROG/26002_pipe_home/lightroom_bridge.py); [previews.py](F:/SYNC/Sync/PROG/26002_pipe_home/previews.py)
- Adobe indique que les aperçus du module Bibliothèque sont des JPEG 8 bits avec perte en Adobe RGB, tandis que le module Développement affiche par défaut en ProPhoto RGB; Adobe avertit que le rendu, les détails et les couleurs peuvent différer entre ces modules. Adobe indique aussi qu’au début de l’import, Lightroom peut montrer les vignettes intégrées à l’appareil, calculées à partir de ses réglages plutôt que du rendu Lightroom. [FAQ couleur Lightroom Classic](https://helpx.adobe.com/lightroom-classic/desktop/technical-support/technical-issues/miscellaneous-issues/color-faq.html); [gestion couleur Lightroom Classic](https://helpx.adobe.com/lightroom-classic/desktop/workspace/color-management.html)
- À l’export, Lightroom convertit l’image vers l’espace choisi (sRGB, Adobe RGB, ProPhoto RGB, etc.) et inscrit le profil correspondant. Qt expose des fonctions distinctes pour associer un espace à une image et pour convertir réellement les pixels vers cet espace; l’existence de profils et la façon dont ils sont lus doivent donc être vérifiées dans le chemin concret, et non supposées à partir du seul aspect visuel. [Options d’export Lightroom Classic](https://helpx.adobe.com/lightroom-classic/desktop/export-photos/export-files-disk-or-cd.html); [QImage / Qt 6](https://doc.qt.io/qt-6/qimage.html)

### Inferences

- Si la capture Lightroom est issue du module Développement et l’application affiche son aperçu cache Lightroom, une différence Bibliothèque/Développement (JPEG 8 bits Adobe RGB contre rendu ProPhoto RGB) est une explication plausible. Il faut confirmer le module Lightroom, l’origine d’aperçu active et le profil réellement présent dans chaque fichier avant de retenir cette explication.
- Si l’application affichait le secours local, l’emploi d’un JPEG intégré au RAW ou d’un développement LibRaw simplifié peut produire un rendu différent du développement non destructif de Lightroom. Si elle affichait le cache Lightroom, le niveau de la pyramide, sa compression, une orientation/correction de recadrage et la conversion couleur à l’affichage restent des pistes à vérifier.
- Le fait que la neige ait une luminance moyenne proche tandis que la veste et les tons sombres changent davantage cadre avec une différence de courbe tonale, de contraste local, de développement ou de rendu d’aperçu; les mesures ne permettent pas d’isoler laquelle.
- Les captures ne prouvent ni que les deux fenêtres affichaient le même fichier/version, ni qu’elles étaient à la même échelle de zoom ou sur le même écran/profil. La différence de dimensions des captures est compatible avec des échelles de capture différentes, tandis que le ratio légèrement différent laisse aussi ouverte une petite différence de cadrage.

### Gaps

- Il manque le fichier source original (RAW/JPEG), l’identifiant de photo et son empreinte, le crop/orientation, l’état des réglages Développement, l’indication du module Lightroom, ainsi que l’export Lightroom de référence. Sans ces éléments, on ne peut pas déterminer si l’application et Lightroom ont rendu exactement la même source et le même état de développement.
- La capture de l’application ne révèle pas si l’image était issue du cache Lightroom ou du secours local. Il faut relever `lightroom_bridge.preview_origin(path)` au moment de l’affichage et conserver le chemin, la taille, l’empreinte et le profil du proxy effectivement chargé.
- On ne peut pas reconstruire depuis ces seules captures le profil écran, le chemin de gestion couleur Windows/Qt, le zoom exact, l’interpolation ou un éventuel traitement HDR/SDR des deux fenêtres.

## Quelles preuves établiraient une parité exacte ?

### Takeaway

Une comparaison décisive doit partir du même fichier et du même état Lightroom, puis comparer des rendus exportés ou décodés dans un espace couleur défini, à dimensions et cadrage identiques. Une paire de captures d’écran, même mesurée, ne peut prouver une égalité des pixels source à cause de l’affichage, de la gestion couleur, de la mise à l’échelle et de la capture.

### Cited Findings

- Lightroom stocke les réglages comme des instructions non destructives et les applique lors de l’export; l’export inclut donc le rendu des réglages. [Édition dans le module Développement](https://helpx.adobe.com/lightroom-classic/desktop/help/applying-adjustments-develop-module-basic.html)
- L’espace couleur d’export est sélectionnable et le profil est intégré/tagué par Lightroom. Un fichier de référence exporté permet donc de fixer explicitement l’espace de comparaison, contrairement à une capture d’écran. [Options d’export Lightroom Classic](https://helpx.adobe.com/lightroom-classic/desktop/export-photos/export-files-disk-or-cd.html)
- Le dépôt offre un mécanisme de proxy Lightroom et un secours local, et expose une fonction d’origine d’aperçu. Consigner cette origine, le chemin du proxy et son empreinte permet de savoir exactement quelle ressource l’application affichait. [lightroom_bridge.py](F:/SYNC/Sync/PROG/26002_pipe_home/lightroom_bridge.py)

### Inferences

- Dossier de preuve minimal : (1) original exact et SHA-256; (2) identifiant Lightroom/catalogue, crop/orientation et paramètres Développement/XMP; (3) export Lightroom pleine résolution avec format, profondeur, espace/profil, options de redimensionnement et netteté consignés; (4) fichier exact et origine d’aperçu chargés par l’application avec dimensions, SHA-256 et métadonnées ICC; (5) version des décodeurs et réglages de conversion couleur; (6) comparaison après application d’une même conversion vers sRGB ou un autre espace convenu, avec cadrage et dimensions alignés.
- Pour vérifier l’égalité du rendu applicatif à l’export, charger cet export dans l’application sans passer par le proxy basse résolution, décoder les deux fichiers en valeurs RGB dans le même profil de travail, puis comparer les dimensions, le crop et les tableaux de pixels. Une égalité exacte exige des valeurs identiques après la même transformation; sinon, rapporter des métriques explicites (différence max, MAE/RMSE, SSIM) et les écarts tolérés. Pour vérifier le pipeline d’aperçu en particulier, comparer aussi son proxy à une référence Lightroom de même taille et même espace, car une miniature JPEG redimensionnée ne peut pas servir de preuve d’égalité pleine résolution.
- Pour une comparaison visuelle à l’écran plutôt qu’une égalité des données, afficher les mêmes rendus sur le même écran calibré, dans des applications gérant les profils, à 100 % sans zoom ni HDR, puis faire une capture native identique. Cela réduit les variables d’affichage, mais la preuve pixel la plus forte reste la comparaison des fichiers rendus avant affichage.

### Gaps

- Le niveau de tolérance définissant « parité » n’a pas été fourni : égalité RGB stricte, égalité après conversion ICC, ou ressemblance visuelle avec une tolérance. Cette décision détermine la métrique et le seuil à appliquer.
- Il manque les originaux et l’export Lightroom de référence pour exécuter cette validation. Les chiffres de ce document portent uniquement sur les deux PNG de capture et ne permettent pas d’annoncer la cause ni la parité du développement.

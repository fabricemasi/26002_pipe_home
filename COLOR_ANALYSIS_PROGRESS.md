# Analyse colorimétrique — état d'intégration

Demande de référence : document joint « PROMPT CODEX — PIPE FMZ », octobre 2026.

## Inspection de l'existant

- `video/pane.py` orchestre lecture VLC/PyAV, timeline, moodboard et corrections.
- `video/viewer.py` affiche via shader OpenGL ou repli CPU.
- `video/color.py` contient déjà le traitement OCIO, les corrections primaires et les LUT.
- `video/thumbs.py` possède les proxies persistants et un worker dédié au moodboard.
- `settings_store.py` et `settings_window_v2.py` restent le système unique des réglages.
- Les captures de référence demandent une palette horizontale et une lecture par zones tonales.
- Les trois références chatgpt.com/s ne sont pas accessibles par l'outil de consultation.

## Implémenté dans cette étape

- Fonds vidéo et moodboard indépendants : presets 0/64/128/191/10, curseur 0–255 et valeur éditable.
- Persistance par les hooks existants ; écritures différées de 300 ms. Aucun décodage au changement de fond.
- Réglage de fond moodboard ajouté aux Settings ; fond vidéo réutilise le réglage existant.
- Action contextuelle « Dominante couleur », dans une vue dédiée du même panneau.
- Retour sans reconstruire la grille : zoom, déplacement et sélection conservés.
- Image limitée à 1500 px, sans agrandissement au-delà de ses dimensions disponibles.
- Palette 2–32 couleurs (16 par défaut), classification OKLab déterministe, jusqu'à 4096 échantillons.
- Calcul hors UI, un worker maximum, requêtes en attente remplacées et résultats périmés ignorés.
- Palette ordonnée selon la clarté OKLab, proportion échantillonnée, copie HEX.
- Export réel PNG, CSS et JSON (espace et hypothèse explicités).
- Moyennes RGB et poids des ombres/tons moyens/hautes lumières selon Y linéaire Rec.709.
- Histogrammes RGB calculés dans le moteur, luminance moyenne et percentiles affichés.

L'analyse porte sur les pixels du proxy d'affichage avec hypothèse sRGB SDR. Elle ne constitue pas une mesure du signal source HDR ou de la scène. Le nombre réduit de pixels est une approximation statistique explicitée dans l'interface. Aucune identification de film ni métadonnée cinématographique n'est inventée.

## Suite nécessaire pour satisfaire tout le document

- Centraliser paramètres d'extraction, fusion perceptuelle, exclusions, ROI, pipette et masque de correspondance.
- Afficher les histogrammes calculés, intégrer scopes existants avec conventions et unités explicites.
- Gestion ICC / métadonnées HDR, gamut et comparaison entre sources avec espaces déclarés.
- Navigation temporelle par vignette, modification locale persistante, Undo/Redo et overlays de temps VFR.
- Courbes éditables, roues et secondaires supplémentaires en réutilisant `video/color.py`.
- Moteurs de matching A/B/C/D, export LUT et évaluation numérique sur images indépendantes.
- Aide Ctrl+Shift, glossaire et Settings détaillés correspondants.
- Validation native DPI, lecture longue, réseau et benchmarks complets.

Ne pas présenter l'ensemble de ces fonctions comme terminé : cette étape est l'intégration des fonds, de la vue palette et du premier moteur de mesures SDR.

## Deuxième étape — outils d'analyse

- Histogrammes RGB et Y linéaire visibles, canaux masquables, échelle logarithmique, valeurs au survol.
- Pipette RGB/HEX/HSV et région rectangulaire par glisser, double-clic pour l'image entière.
- Ordre de palette par clarté ou proportion ; exclusions des noirs/blancs limitées à la palette.
- Paramètres d'extraction exposés dans les Settings existants.
- Échantillonnage réparti sur toute l'image et sans filtrage qui invente des teintes de frontière.
- Waveform et vectorscope réutilisent `video/scopes.py`, activables à la demande seulement ; unités Y′ encodé et Cb/Cr précisées. Régions transparentes exclues des scopes spatiaux.
- Annulation coopérative dans le clustering, debounce 100 ms, arrêt au retour/changement de média.
- Correction du hook de persistance manquant : valeurs vidéo écrites dans le fichier et le preset, avec synchronisation de la fenêtre des réglages.
- La largeur d'affichage respecte aussi la largeur naturelle du média lorsque les proxies sont agrandis.

La liste de suite ci-dessus reste ouverte pour la fusion perceptuelle configurable, les masques de correspondance et les autres phases. ROI, pipette, exclusions et affichage des histogrammes sont désormais implémentés.

Validation deuxième étape : 7 tests d'analyse passent ; suite vidéo : 8 réussis et 22 ignorés pour dépendances optionnelles. Sonde Qt offscreen avec palette, histogramme et scopes : 20 rendus en 162 ms (~8,1 ms/rendu). Cette mesure ne remplace pas une validation native sur écran ni les benchmarks de lecture vidéo.

## Troisième étape — matching et export LUT SDR

- Accessible par « Matching / LUT… » dans Dominante couleur.
- Moteur indépendant `video/matching.py`, UI asynchrone `video/matching_ui.py`.
- Méthode scènes différentes : transport affine des moyennes/covariances RGB encodées sRGB, avec régularisation spectrale et gains bornés ; il s'agit d'une estimation statistique globale.
- Méthode paire alignée : régression polynomiale degré 2 régularisée vers l'identité. Dimensions identiques exigées, correspondances spatiales sous responsabilité de l'utilisateur. Un pixel sur cinq réservé à l'évaluation sur cette paire.
- Source et référence externes sélectionnables ; lecture en fond, cache des images sélectionnées, conversion ICC vers sRGB lorsque Qt possède un profil valide. Sans profil : hypothèse sRGB explicitée. Images transparentes rejetées pour ne pas fabriquer des correspondances.
- Intensité, aperçu Avant / Après, distance des moyennes ou RMSE RGB selon méthode, fraction des valeurs hors domaine avant limitation.
- Export `.cube` 17³/33³/65³/129³ dans un fichier temporaire puis remplacement atomique ; rouge le plus rapide et domaine/espaces/hypothèses inscrits dans l'en-tête.
- Validation interpolation sur 4096 échantillons via `video.color.Lut.apply_np` : RMSE et erreur maximale RGB. Ce n'est pas une garantie de fidélité à l'étalonnage original.
- Export et rechargement de presets JSON natifs avec validation de la structure et de l'espace.
- Settings existants : résolution LUT, intensité et méthode.

Validation : 5 tests matching réussis (identité, transformation connue sur nouveaux pixels, aller-retour .cube 17/33, stabilité des scènes constantes, annulation conservant le fichier existant, rejet des dimensions incompatibles et HDR). Sonde Qt offscreen : résultat worker, aperçu, export/rechargement preset, changement d'intensité. Les 7 tests d'analyse et les 8 tests vidéo exécutables passent aussi (22 tests vidéo ignorés). Les résolutions 65/129 ne font pas encore l'objet d'un test d'aller-retour fichier dans cette étape.

Restent notamment les modèles de look à référence unique/multiples, le recalage automatique, les masques de protection, matching perceptuel avancé, validation HDR/OCIO des transforms, courbes et roues complémentaires, navigation temporelle par vignette et aide pédagogique. Les outils SDR ci-dessus ne remplacent pas ces exigences.

## Quatrième étape — aide pédagogique

- Base centrale `video/help_content.py` : glossaire de plus de 35 notions et explications à huit rubriques pour palette, histogrammes, ROI/pipette, scopes, matching, LUT, fond, exposition, saturation et corrections/OCIO.
- `video/help_ui.py` : Ctrl+Shift, délai, popup défilable et positionnement borné à l'écran (cadre natif compris). F1 ouvre l'explication du contrôle ayant le focus.
- Le geste fonctionne avant ou après le survol ; relâchement, masquage du module ou fenêtre inactive ferment l'aide. Le filtre ne consomme pas Ctrl/Shift et son timer est arrêté hors du geste.
- Glossaire avec recherche sans accents, accès par bouton depuis analyse et matching. Références documentaires W3C et OpenColorIO accessibles dans le glossaire.
- Annotations partagées sur les contrôles d'analyse/matching, fonds du module, contrôles vidéo pertinents des Settings et fenêtres de corrections. Aucun parcours des 32 000 widgets pendant un survol.
- Settings > Module vidéo > Aide pédagogique : activation, délai 0–2000 ms, largeur 280–800 px. Le contenu est français ; pas encore de choix de langue ou de niveau de détail.
- Couverture partielle du cahier des charges : les outils futurs et contrôles vidéo non colorimétriques n'ont pas tous d'explication spécialisée.

Validation : 6 tests d'aide passent (survol avec touches déjà maintenues, activation/désactivation, relâchement, délai, F1, recherche, huit rubriques et bord d'écran), ainsi que 7 tests analyse et 5 matching. Suite vidéo : 8 réussis, 22 ignorés pour dépendances optionnelles. cProfile avec les réglages entièrement construits (32 157 widgets) : 10 000 événements sans geste en 48,17 ms, soit ~4,8 µs par filtre. La construction complète volontaire `eager=True` de cette sonde a duré 63 s ; ce n'est pas le délai d'ouverture différée ordinaire. Validation native multi-écrans/DPI et mesure de lecture vidéo restent à effectuer.

## Validation de cette étape

- `test_video_analysis.py` : 2 tests réussis (rouge connu, poids noir/blanc, histogramme et zones tonales).
- `test_video_module.py` : 30 tests collectés, 8 réussis, 22 ignorés pour dépendances optionnelles indisponibles.
- Sonde Qt offscreen : fonds indépendants, traitement asynchrone et réception de la palette rouge vérifiés.
- Sonde cProfile, SettingsWindowV2(eager=True), 32 077 widgets : 100 changements de fond en 3,72 ms (temps UI, hors peinture écran).
- Compilation Python des modules modifiés réussie.
- Le contrôle global `git diff --check` relève des espaces de fin de ligne et CRLF dans de nombreux changements préexistants ; ces fichiers n'ont pas été reformattés.

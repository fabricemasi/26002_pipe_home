# Pipeline d'aperçus et Lightroom

## Carte : fonctionnalité → fichiers (découpage du 2026-10-28)

`previews.py` reste la façade de lecture / d’appel (`previews.X`, imports historiques).
Le code vit dans `preview_services/`, paquet de services communs de fm_browser.
Il ne dépend ni de la fenêtre principale ni des modules de réglages métier.

| Fonctionnalité | Fichiers dans `preview_services/` |
|---|---|
| Attributs cachés Windows | `filesystem.py` |
| Dates mémorisées, chemins distants, contexte `memory_only` | `mtime.py` |
| Recadrage et mise à l’échelle | `pixmaps.py` |
| Icônes des logiciels et de l’interface | `icons.py` |
| Caches mémoire, échecs de recherche, indicateur de présence de PNG | `memory.py` |
| Signatures, index disque, protection, turntables et nettoyage des caches | `cache.py` |
| Lecture des profils, snapshot et fond du rendu | `profiles.py` |
| Journal quotidien HTML et tableau des rendus | `render_log.py` |
| Dépendances optionnelles numpy / rawpy / OpenEXR | `optional.py` |
| Détection de Blender | `executables.py` |
| Rendu Blender EEVEE et script embarqué | `blender.py` |
| Lecture OBJ et rastérisation de secours | `obj.py` |
| Alembic, Maya, Houdini : décodeurs, détection des outils, scripts | `alembic.py`, `maya.py`, `houdini.py` |
| PDF et Illustrator | `pdf.py` |
| Images 2D, PSD, TX, EXR, HDR, RAW, LUT et dispatch des formats statiques | `images.py` |
| Image extraite d’une vidéo | `video.py` |
| DWG / DXF, vignette intégrée et conversion ODA | `dwg.py` |
| Polices, brosses Photoshop | `font.py`, `abr.py` |
| Lecture des aperçus, workers et files de décodage | `runtime.py` |
| Scan en fond et ordonnanceur d’inactivité | `scheduler.py` |

### Dépendances et état partagé

- Couches sans cycle : outils de base → décodeurs / profils / journal → cache disque
  → lecture et workers (`runtime`) → ordonnanceur (`scheduler`).
- Le dispatch 2D et les LUT restent ensemble dans `images.py` : une LUT utilise elle-même
  le dispatch pour son image de test. Leurs caches sont dans la couche inférieure `memory.py`.
- Blender ne dépend pas du rasteriseur OBJ : sa détection est isolée dans `executables.py`.
  OBJ et Alembic peuvent ainsi utiliser Blender sans créer de cycle.
- État RÉAFFECTÉ : profils et lot automatique dans `profiles.py` ; sélection LUT dans `images.py` ;
  `_PREVIEW_CACHE_HAS_PNG` dans `memory.py` ; protection dans `cache.py`.
  Tous les autres modules lisent / écrivent `module.X`, jamais une copie importée.
  La façade lit ces états par `__getattr__` pour ne pas figer leur valeur.
- Les chemins reposant sur `__file__` remontent désormais de DEUX niveaux vers la racine.
  Les scripts embarqués Blender / Maya / Houdini sont conservés sans changement.
- Patches des tests : viser le module effectivement appelé (`preview_services.cache`,
  `runtime`, `video`, etc.). Les appels directs de Lightroom, de la visionneuse et des tâches automatiques
  à la façade restent patchés dans `previews` ; ne pas déplacer ces patches à l’aveugle.

### Vérifications du découpage

Référence AVANT modification, hors sandbox Windows (`python tests/run.py apercus`) :
seulement deux FAIL préexistants dans `test_render_log.RenderLogTest` :
`test_one_row_per_render_and_details` et `test_requested_columns_and_render_metadata`
(attendent 8 colonnes, le tableau en possède déjà 9). Ne pas les corriger dans ce chantier.
Le premier lancement sandboxé ajoutait des accès refusés artificiels (Alembic, Lightroom,
journal et reprise turntable) et immobilisait le board : comparer les suites hors sandbox.

Contrôles structurels : 123 fonctions / classes comparées par AST après normalisation des
références et chemins ; imports dans trois ordres, y compris sans numpy / rawpy / OpenEXR.
`test_previews_modules.py` vérifie la propagation des profils rechargés et l’invalidation LUT
entre fichiers. Sonde du chemin de repeinture en cache (5 × 10 000 appels, `cProfile` séparé) :
médiane ≈ 48 µs avant, ≈ 49 µs après ; aucun nouveau décodage ou scan ajouté.

Validation finale : `python -m pyflakes` sur tous les fichiers Python touchés,
sans nouvelle alerte ni nom indéfini (imports inutilisés des tests déjà présents).
`python tests/run.py apercus` : 16 fichiers, mêmes deux FAIL initiaux ; nouveaux tests OK.
`python tests/run.py --tout` : 79 fichiers, 32 FAIL / ERROR contre 32 avant,
aucun nouveau. Un plantage natif de fin de processus (`0xC0000409`, déjà décrit dans la
passation) après les 7 tests vidéo OK : relance ciblée de `test_video_analysis.py`, 7/7 OK,
sortie 0. Fenêtre principale construite, affichée puis fermée hors écran avec état utilisateur
isolé. Tests lents sautés.

**Tests du module** : `python tests/run.py apercus` — rapides seulement ; ajouter `--lent` pour les tests lents (Blender, fenêtre entière…) avant un commit qui touche leur zone.

### Pipeline d'aperçus
Aperçus asynchrones : `_PreviewDecodeManager` / `_PreviewDecodeTask` (QRunnable), `_IdlePreviewScheduler` (rendu en tâche de fond quand l'appli est inactive). Cache disque dans `data/.pipeline_preview_cache/` (clé = chemin + mtime ; métadonnées, nettoyage des caches périmés). Ce dossier compte des dizaines de milliers d'entrées : JAMAIS de `glob` / `iterdir` dessus (~100 ms de Python chacun, GIL tenu par tranches ; un aperçu absent en déclenchait jusqu'à une dizaine — cause principale des saccades de la lecture vidéo et des lenteurs des colonnes pendant le calcul des aperçus d'un dossier) : index des noms `previews._CACHE_INDEX` (`with_prefix`, `with_digest`, `has_png`, lu une fois, relu si le dossier a changé — au plus toutes les 30 s ; nos écritures / suppressions le tiennent à jour : `added` / `removed`). Ménage complet (`sweep_preview_cache`, ~35 s de calcul pour ~10 000 fiches, plantait sur un « accès refusé ») : au plus une fois par jour (`sweep_preview_cache_if_due`, `.last_sweep`), en fond, en rendant la main à chaque fiche ; renommage des anciens noms (`migrate_cache_names`) aussi en fond. Décodeurs par format : OBJ (numpy/QPainter ou Blender EEVEE), Alembic `.abc` et `.blend` (Blender), `.ma` (mayapy), scènes Houdini `.hip`/`.hiplc`/`.hipnc` (hython, `_render_hip_wireframe` : `_HIP_EXPORT_SCRIPT` exporte la géométrie AFFICHÉE de /obj à l'image courante — jamais les objets masqués, trop longs à cuire — en Alembic, ou en OBJ écrit en Python pour les `.hipnc`, qui n'ont pas le droit d'exporter en Alembic ; puis même rendu Blender que les autres fichiers 3D ; test `tests/test_hip_preview.py`), PSD, EXR/HDR/TX (OpenEXR / oiiotool), vidéo, DWG (ezdxf + ODA File Converter ; sans ODA ou si la conversion échoue : vignette BMP/PNG intégrée au DWG par AutoCAD, `_decode_dwg_thumbnail`, test `tests/test_dwg_thumbnail.py`), DXF (dessin vectoriel direct par ezdxf, `_render_dxf_file`, aussi utilisé pour les DWG convertis ; image cadrée sur le plan), brosses Photoshop `.abr` (planche des pointes, parseur maison : versions 1/2 et 6/7/9/10, ordre et pointes rondes calculées lus dans la section `desc`, `_abr_brushes` ; test `tests/test_abr_preview.py`), Illustrator `.ai` (rendu PDF de la 1re planche via QtPdf, planches feuilletables dans l'inspecteur ; sans contenu PDF — page d'avertissement d'Adobe détectée par `ai_has_pdf_content` — ou `.ai` PostScript : vignette JPEG XMP `xmpGImg:image` ; test `tests/test_ai_preview.py`). Les rendus Blender/Maya sont des **scripts Python embarqués dans des chaînes** exécutés en sous-processus (voir `_render_wireframe_eevee`, `_render_ma_wireframe`) — ce code s'exécute dans l'interpréteur de Blender/Maya, pas dans l'appli. Les profils de rendu (low/high…, turntable) viennent de `files/parametres rendus.txt` (`_load_render_profiles`) ; journal de rendu quotidien `pipeline_preview_render_<date>.html` / `.log`.
Les fichiers du cache ont un nom explicite `<set>__<fichier>__<code16>_<mtime>.png` (set = jusqu'à 3 dossiers sous la racine, voir `_cache_label`) ; turntables `<set>__<fichier>__turntable_<code16>`. `migrate_cache_names()` (appelée par `main()`) renomme les anciens noms opaques.

**SUSPENDU à la demande de l'utilisateur (système complet à repenser avec lui)** : `AUTO_RENDER_ENABLED = False` (le balayage d'inactivité `_IdlePreviewScheduler` ne démarre plus et ne rend plus rien : ni fichiers 3D, ni aperçus périmés ; les rendus lancés à la main depuis le menu restent). Ne pas le rallumer sans qu'il le demande. Le cache disque des aperçus d'images 2D et de vidéos (`IMAGE_DISK_CACHE_ENABLED`) est REMIS (demande de l'utilisateur : les originaux ne doivent jamais être relus à chaque démarrage). Images 2D / vidéos décodées dans leur propre file `_IMAGE_DECODE_POOL` (jusqu'à 4 à la fois, dernières demandées d'abord, jamais derrière un rendu Blender/Maya, qui restent sur `_PREVIEW_DECODE_POOL`). `files/parametres rendus.txt` n'est lu QU'AU LANCEMENT D'UN RENDU (`_reload_render_profiles`, rendu manuel ou lot automatique) — jamais pour afficher une image 2D ou un rendu 3D déjà fait : entre deux rendus, les clés de cache 3D utilisent les profils du dernier rendu, gardés dans `data/render_profiles_snapshot.json` (relu au démarrage, ignoré par git). Idem `config.VIDEO_PLAYBACK_ENABLED = False` (lecture des vidéos en boucle dans l'inspecteur coupée, trop gourmande : l'inspecteur montre l'image fixe tirée de la vidéo, `_decode_video_frame`, comme les vignettes).

Outils externes détectés dynamiquement : `BLENDER_EXECUTABLE`, `MAYA_PYTHON_EXECUTABLE`/`MAYA_LOCATION`, `HOUDINI_HYTHON`/`HFS` (sinon le Houdini le plus récent sous `Side Effects Software`), `ODA_FILE_CONVERTER`, `oiiotool` dans le PATH. Tous optionnels : l'appli doit rester fonctionnelle sans (fichiers simplement sans aperçu).

`tools/` : scripts autonomes de conversion/validation Alembic (`convert_legacy_alembic.py`, `validate_alembic_blender.py`).

## `lightroom_bridge.py`

- `lightroom_bridge.py` : dossiers associés à un catalogue Lightroom Classic (`.pipeline_lightroom.json`, catalogue lu en lecture seule ; module SDK `plugins/PipelineLightroom.lrplugin` pour attributs, ouverture, rendus). APERÇUS (demande de l'utilisateur) : proxy des colonnes / inspecteur / diapositives = niveau de la pyramide `<catalogue> Previews.lrdata` (rendu AVEC les réglages de Développement) le plus petit d'au moins `PROXY_SIDE` (640) px, sinon le JPEG rendu par le module SDK, sinon le proxy créé par l'appli (`proxy_file`) ; image EN FOCUS = le plus grand aperçu développé (pyramide standard / 1:1 ou rendu SDK) d'au moins `LARGE_MIN` px, JAMAIS le petit proxy, sinon l'original (`large_file`). Sources affichées : lignes « Source du proxy » / « Source de l'aperçu plein écran » du tableau de l'inspecteur (lues en fond, `request_sources` → `sources_ready`) et du panneau « Paramètres de l'image » de la visionneuse (`focus.image_sources`) ; Maj + survol d'une diapositive (planche, pellicule) = encart « Source du proxy » (`focus.ProxySourceTip`, encart `_WidthBadge` des réglages). PIÈGE : `previews.db` est en mode journal ; un `previews.db-journal` présent fait échouer toute lecture `mode=ro` (« readonly database ») — repli `immutable=1` (`_open_previews_db`), connexions gardées par fil (`_previews_conn` ; rouvrir coûtait 40-200 ms par photo sur le disque des photos). Jamais de lecture du catalogue / de previews.db sur le fil de l'interface (`FocusImageLoader.natural_size` rend None pour une photo Lightroom). Tests `tests/test_lightroom_sources.py`, `tests/test_lightroom_preview_fallback.py`.

"""Constantes et chemins partages (extensions, dossiers de donnees, listes d'omission)."""

import threading
from pathlib import Path


# Dependances optionnelles (voir requirements.txt) : import protege pour
# qu'une install sans ces paquets perde juste les apercus concernes, sans
# empecher l'appli de demarrer. numpy sert au rasteriseur des .obj
# (voir _rasterize_obj_numpy) ET, avec OpenEXR, au decodage des .exr (voir
# _decode_exr_image) — verifie separement, un .obj lisse ne doit pas
# dependre de la presence d'OpenEXR.
try:
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False
try:
    _OPENEXR_AVAILABLE = _NUMPY_AVAILABLE
except ImportError:
    _OPENEXR_AVAILABLE = False



# ==========================================================================
# Configuration
# ==========================================================================

ROOT = Path(r"F:\PIPELINE")

COLUMN_LABELS = ["Type", "Projets", "Sous-projet", "Logiciels", "Contenu"]

# Repli des colonnes "de set" (voir Column.set_collapsed/PipelineBrowser.
# _apply_project_columns_collapsed) : une fois la chaine de navigation
# COMPLETEMENT settee jusqu'au repertoire de travail (voir
# _chain_expected_total, N colonnes reelles quelconques — Type/Projets/
# Sous-projet en legacy, ou N niveaux configures, voir load_project_
# columns), ces colonnes perdent leur utilite immediate (le contexte est
# fixe) et peuvent se replier en bandeau etroit, avec une icone pour les
# redeplier a la demande (voir PipelineBrowser._sync_collapse_state) — pas
# de liste de TITRES fixe (voir Column.collapsible, base sur group_kind) :
# generalise a N'IMPORTE QUEL nombre d'etapes, voir la remarque de
# l'utilisateur, "si un projet est sur une base 3 etapes, 3 colonnes
# devront se rabattre, si c'est une base 4, 4 colonnes ... en fait c'est
# toutes les colonnes avant les colonnes de focus". Reglable (voir
# app_style.auto_collapse_set_columns/General > Application, "un toggle
# qui permet ou pas de rabattre les colonnes de set").

# Dossiers dont le contenu est remonte dans la colonne du parent.
FLATTEN_FOLDERS = {"WORK"}

HIDDEN_PREFIXES = (".", "$", "~")

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico",
}

# Fichiers 3D dont on peut generer un apercu (voir _decode_obj_image) : pas
# une vraie image, mais traites comme tel partout ailleurs (meme ligne-carte,
# meme cache disque) via PREVIEWABLE_EXTENSIONS.
OBJ_EXTENSIONS = {".obj"}
ABC_EXTENSIONS = {".abc"}
BLEND_EXTENSIONS = {".blend"}
MAYA_SCENE_EXTENSIONS = {".ma", ".mb"}
FBX_EXTENSIONS = {".fbx"}
DWG_EXTENSIONS = {".dwg"}
RENDERABLE_3D_EXTENSIONS = (
    OBJ_EXTENSIONS | ABC_EXTENSIONS | BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS
)
_DWG_RENDER_LOCK = threading.Lock()

# Fichiers Photoshop : Qt ne sait pas les decoder (absent de
# QImageReader.supportedImageFormats), mais Photoshop y embarque presque
# toujours une vignette JPEG prete a l'emploi (voir _decode_psd_thumbnail) —
# bien plus simple/rapide qu'une vraie composition des calques, qui serait
# hors de portee ici.
PSD_EXTENSIONS = {".psd", ".psb"}

# Rendus HDR .exr (voir _decode_exr_image) : necessite le paquet OpenEXR
# (voir _OPENEXR_AVAILABLE) ; sans lui, ces fichiers restent sans apercu,
# comme avant.
EXR_EXTENSIONS = {".exr"}

# Textures Arnold/OpenImageIO : conversion vers une vignette PNG via oiiotool.
TX_EXTENSIONS = {".tx"}

# HDRI Radiance (voir _decode_hdr_image) : format RGBE documente/stable,
# parseur maison (juste numpy, AUCUNE dependance externe contrairement a
# .exr/OpenEXR) — voir la remarque de l'utilisateur, "possible de faire
# les apercus des hdri ?".
HDR_EXTENSIONS = {".hdr"}

# Videos : une frame extraite via QtMultimedia (voir _decode_video_frame),
# module fourni avec PySide6 (ffmpeg embarque, aucune dependance externe).
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v"}

PREVIEWABLE_EXTENSIONS = (
    IMAGE_EXTENSIONS | OBJ_EXTENSIONS | ABC_EXTENSIONS | BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS | DWG_EXTENSIONS | PSD_EXTENSIONS | EXR_EXTENSIONS | HDR_EXTENSIONS | TX_EXTENSIONS | VIDEO_EXTENSIONS
)
TWO_D_IMAGE_EXTENSIONS = (
    IMAGE_EXTENSIONS | PSD_EXTENSIONS | EXR_EXTENSIONS | HDR_EXTENSIONS | TX_EXTENSIONS | DWG_EXTENSIONS
)

_MANUAL_3D_PREVIEW_REQUESTS: set[str] = set()
_MANUAL_3D_PREVIEW_MODE: dict[str, str] = {}
_STALE_PREVIEW_PATHS: set[str] = set()

# Fichiers texte/code dont le contenu (debut) s'affiche dans l'inspecteur
# (voir DetailPanel.show_path) : contrairement a IMAGE_EXTENSIONS/
# OBJ_EXTENSIONS/ABC_EXTENSIONS, jamais utilise pour les cartes-vignette des colonnes (un
# extrait de texte reduit a la taille d'une icone serait illisible) — texte
# brut affiche en clair uniquement dans le panneau de droite.
TEXT_PREVIEW_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".xml", ".yaml", ".yml", ".ini",
    ".cfg", ".conf", ".log", ".csv", ".tsv", ".py", ".js", ".ts", ".html",
    ".css", ".sh", ".bat", ".ps1", ".nk", ".mel",
}
TEXT_PREVIEW_MAX_BYTES = 4000    # lu depuis le disque, avant decodage/troncature
TEXT_PREVIEW_MAX_LINES = 40
TEXT_PREVIEW_PANEL_HEIGHT = 220   # hauteur fixe du panneau de texte dans l'inspecteur (voir DetailPanel)
PUR_PREVIEW_EXTENSIONS = {".pur"}
PUR_MAX_EMBEDDED_IMAGES = 3000
_PUR_IMAGE_INDEX_CACHE: dict[str, tuple[float, list[tuple[int, int, str]]]] = {}

# Reglable depuis la fenetre de parametres : affiche les fichiers image, dans
# n'importe quelle colonne classique, avec exactement le meme style de ligne
# que les vignettes de projet (vignette carree a gauche + nom/metadonnee a
# droite), plutot que le marqueur habituel. Pas de menu "changer l'image"
# pour ces lignes : l'image EST le fichier.
SHOW_FILE_IMAGE_PREVIEWS = True

PREVIEW_MIN_HEIGHT = 104   # hauteur de la vignette sans image (ou image tres petite)
PREVIEW_MAX_HEIGHT = 1200  # affichage natif des apercus OBJ/ABC en 1200 x 1200 px

# Vignettes de dossier (colonnes "Projets" et "Sous-projet") : image
# personnalisee stockee a la racine du dossier, sinon image par defaut
# generique.
THUMBNAIL_COLUMN_LABELS = {"Projets", "Sous-projet"}
THUMBNAIL_FILENAME = ".thumbnail.png"
THUMBNAIL_MAX_DIM = 1024   # taille max (px) a laquelle une vignette perso est enregistree
PROJECT_ROW_HEIGHT = 64    # hauteur de ligne (vignette carree + texte a droite)

# Logos de logiciel (colonne "Logiciels") : badge colore genere a la volee
# (pas de fichier image) par defaut, identifie par le nom du dossier (HOUDINI,
# MAYA...). Peut etre remplace par une image perso via le clic droit ; cette
# icone perso est alors globale au logiciel (pas au projet), stockee a cote
# du script puisqu'elle ne depend pas de la racine du pipeline consultee.
SOFTWARE_COLUMN_LABEL = "Logiciels"
# 16 (valeur d'origine) etait bien EN DESSOUS de la hauteur de ligne
# reelle (24-40px selon les reglages) : software_icon_pixmap mettait donc
# en cache un bitmap de 16x16, ensuite AGRANDI par _paint_row_image pour
# remplir la ligne — un agrandissement, jamais net (voir la remarque de
# l'utilisateur, "je veux que toutes les icones soient parfaitement
# redimensionnables sans pixelisation"). 128 : large marge au-dessus de
# toute hauteur de ligne realiste, pour que la mise a l'echelle EFFECTIVE
# (dans _paint_row_image) soit TOUJOURS un RETRECISSEMENT — voir
# _smooth_scale_down, jamais floue/pixelisee dans ce sens.
SOFTWARE_ICON_SIZE = 128
DATA_DIR = Path(__file__).resolve().parent / "data"
CUSTOM_SOFTWARE_ICON_DIR = DATA_DIR / "software_icons"
ICONS_DIR = Path(__file__).resolve().parent / "icons"
CUSTOM_SOFTWARE_ICON_MAX_DIM = 128

_FILE_ATTRIBUTE_HIDDEN = 0x2


GLOBAL_OMIT_FILE_NAMES: set[str] = set()
GLOBAL_OMIT_FILE_EXTENSIONS: set[str] = set()
GLOBAL_OMIT_DIR_NAMES: set[str] = set()

STEP_BADGE_SIZE = 18
STEP_BADGE_MARGIN = 4

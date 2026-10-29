"""Réglages du module vidéo : lignes de la fenêtre « Réglages : Vidéo » (groupes `CATALOG["Vidéo : …"]`) et leur
arbre (`VIDEO_TREE`). Données seulement (aucun widget) : la fenêtre générique `settings_window_v2.SettingsWindowV2(
module="video")` les construit. Défauts : `settings_defaults.py`. Carte : docs/agents/fm_video.md."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec, _gabarit_extra, _shadow_spec
from fm_video.settings_defaults import VIDEO_DEFAULTS


# ==========================================================================
# Onglet « Module vidéo » (paquet fm_video/) : réglages GÉNÉRAUX du lecteur (affichage, informations en surimpression,
# lecture, timeline, couleur / OCIO, LUT, performances, export). Défauts = fm_video/settings_defaults.py ; appliqués
# en direct (chemin rapide de `PipelineBrowser._apply_settings`, clés `video_`). Clic droit sur un titre de l'onglet
# = « Restaurer les valeurs d'origine ».
# ==========================================================================
VIDEO_TAB = "Module vidéo"
_VIDEO_CORNERS = (("top_right", "Haut droite"), ("top_left", "Haut gauche"), ("bottom_right", "Bas droite"),
                  ("bottom_left", "Bas gauche"))


def _vd(key: str):
    return VIDEO_DEFAULTS[key]


def _v_slider(key, label, low, high, unit="px", **params) -> Spec:
    return Spec(key, label, "slider", _vd(key), {"min": low, "max": high, "unit": unit, **params})


def _v_choice(key, label, choices, **params) -> Spec:
    return Spec(key, label, "choice", _vd(key), {"choices": choices, **params})


def _v_bool(key, label, **params) -> Spec:
    return Spec(key, label, "bool", _vd(key), params)


def _v_color(key, label) -> Spec:
    return Spec(key, label, "color_app", _vd(key), {"title": label})


def _ocio_choices(kind: str):
    """Espaces / displays / views de la configuration OCIO réglée (lus à la construction de la section)."""
    def choices():
        try:
            from settings_store import load_settings
            from fm_video import color as vcolor
            config = vcolor.load_config(load_settings().get("video_ocio_config", ""))
            if kind == "space":
                names = vcolor.colorspace_names(config)
            elif kind == "display":
                names = list(config.getDisplays())
            else:
                names = sorted({v for d in config.getDisplays() for v in config.getViews(d)})
            return tuple((n, n) for n in names)
        except Exception:                                    # noqa: BLE001 - OCIO absent : la valeur seule
            return ()
    return choices


_FPS_CHOICES = (("23.976", "23,976"), ("24", "24"), ("25", "25"), ("29.97", "29,97"), ("30", "30"), ("48", "48"),
                ("50", "50"), ("59.94", "59,94"), ("60", "60"), ("120", "120"))
CATALOG["Vidéo : Ouverture"] = [
    _v_bool("video_open_videos", "Double-clic sur une vidéo : Module vidéo"),
    _v_bool("video_open_sequences", "Double-clic sur une image EXR / TIFF / DPX numérotée : sa séquence"),
    _v_bool("video_detect_sequences", "Détecter les séquences d'images"),
]
CATALOG["Vidéo : Affichage"] = [
    _v_color("video_bg_color", "Couleur de fond"),
    _v_choice("video_default_zoom", "Zoom initial",
              (("smart", "Ajustement intelligent (réduite si plus grande que la zone, sinon 100 %)"),
               ("fit", "Toujours ajuster à la zone"), ("100", "Toujours 100 % (pixels réels)"),
               ("last", "Restaurer le dernier zoom"))),
    _v_slider("video_fit_margin", "Marge de l'ajustement", 0, 200),
    _v_bool("video_wheel_zoom", "Zoom à la molette (autour du curseur)"),
    _v_slider("video_zoom_step", "Incrément de zoom (par cran)", 2, 100, "%"),
    _v_choice("video_interpolation", "Interpolation d'affichage",
              (("auto", "Auto (lissé, pixels nets au-delà de 150 %)"), ("linear", "Lissé"), ("nearest", "Pixels nets"))),
    _v_bool("video_mipmaps", "Réduction lissée sous 50 % (mipmaps)"),
    _v_choice("video_pan", "Déplacement de l'image zoomée", (("bounded", "Borné (l'image couvre la zone)"),
                                                            ("free", "Libre"))),
    _v_bool("video_checker", "Damier derrière la transparence"),
    _v_slider("video_checker_size", "Taille des cases du damier", 2, 64),
    _v_color("video_checker_a", "Damier : couleur 1"),
    _v_color("video_checker_b", "Damier : couleur 2"),
    _v_color("video_controls_bg", "Contrôles : fond"),
    _v_color("video_controls_color", "Contrôles : icônes et textes"),
    _v_slider("video_controls_height", "Contrôles : hauteur", 22, 60),
    _v_bool("video_fullscreen_autohide", "Plein écran : contrôles masqués (montrés au mouvement)"),
    _v_bool("video_fullscreen_info", "Plein écran : garder les informations"),
    # Cadre de l'image : autour du rectangle VISIBLE de la vidéo, dessiné par le GPU (coût nul en lecture).
    Spec("video_frame_border_enabled", "Bordures de la vidéo", "sides_thick", False,
         {"colors_key": "video_frame_border", "thickness_key": "video_frame_border_thickness", "range": (0, 40)},
         extra_keys=("video_frame_border", "video_frame_border_thickness")),
    Spec("video_frame_radius", "Border radius de la vidéo", "corners", 0, {"max": 200}),
    _shadow_spec("video_frame_shadow", "Ombres de la vidéo"),
    _v_slider("video_frame_shadow_offset_x", "Ombre : décalage horizontal", -100, 100),
    _v_slider("video_frame_shadow_offset_y", "Ombre : décalage vertical", -100, 100),
    _v_slider("video_frame_shadow_spread", "Ombre : extension", 0, 100),
]
CATALOG["Vidéo : Informations"] = [
    _v_bool("video_info_enabled", "Afficher à l'ouverture (touche I)"),
    _v_slider("video_info_opacity", "Opacité du fond", 0, 100, "%"),
    _v_color("video_info_bg", "Couleur du fond"),
    Spec("video_info_font_family", "Police", "font_gabarit", "",
         {"prefix": "video_info", "size": (6, 40), "size_default": 12, "color_default": "#e8e8e8",
          "color_title": "Texte des informations", "only": ("family", "bold", "size", "color")},
         extra_keys=_gabarit_extra("video_info", only=("bold", "size", "color"))),
    _v_color("video_info_label_color", "Couleur des libellés"),
    _v_color("video_info_title_color", "Couleur des catégories"),
    _v_choice("video_info_corner", "Position", _VIDEO_CORNERS),
    _v_slider("video_info_margin_x", "Marge horizontale", 0, 400),
    _v_slider("video_info_margin_y", "Marge verticale", 0, 400),
    _v_slider("video_info_padding", "Padding", 0, 60),
    _v_slider("video_info_line_spacing", "Espacement des lignes", 0, 30),
    _v_slider("video_info_radius", "Border radius", 0, 40),
    _v_slider("video_info_width", "Largeur (0 = selon le contenu)", 0, 1200),
    _v_bool("video_info_titles", "Afficher les catégories"),
    _v_bool("video_info_compact", "Affichage compact"),
    _v_bool("video_info_temporary", "Affichage temporaire"),
    _v_slider("video_info_timeout", "Délai de masquage", 1, 30, "s",
              active_when=("video_info_temporary", True)),
    _v_bool("video_info_media", "Catégorie Média (nom, codec, durée, timecode…)"),
    _v_bool("video_info_image", "Catégorie Image (résolution, ratio, profondeur, alpha…)"),
    _v_bool("video_info_playback", "Catégorie Lecture (FPS, position, état)"),
    _v_bool("video_info_display", "Catégorie Affichage (zoom, OCIO, LUT, corrections)"),
    _v_bool("video_info_pixel", "Catégorie Pixel (valeurs sous le curseur)"),
]
CATALOG["Vidéo : Lecture"] = [
    _v_choice("video_sequence_fps", "FPS des séquences d'images", _FPS_CHOICES),
    _v_bool("video_autoplay", "Lecture automatique à l'ouverture"),
    _v_choice("video_engine", "Moteur de lecture des vidéos",
              (("vlc", "LibVLC (moteur de VLC : décodage matériel, son, réseau)"),
               ("pyav", "PyAV (ancien moteur, sans VLC)"))),
    _v_slider("video_cache_local_ms", "Cache de lecture : fichiers locaux", 100, 10000, "ms",
              active_when=("video_engine", "vlc")),
    _v_slider("video_cache_network_ms", "Cache de lecture : fichiers réseau", 100, 20000, "ms",
              active_when=("video_engine", "vlc")),
    _v_bool("video_loop", "Boucle"),
    _v_choice("video_end_behavior", "Fin du média (boucle coupée)",
              (("stop", "S'arrêter sur la dernière image"), ("rewind", "Revenir au début"))),
    _v_slider("video_volume", "Volume par défaut", 0, 100, "%"),
    _v_choice("video_priority", "Priorité de lecture (moteur PyAV, séquences)",
              (("smooth", "Fluidité (images sautées si le décodage ne suit pas)"),
               ("exact", "Précision (chaque image montrée, la lecture ralentit)"))),
    _v_choice("video_missing", "Images manquantes d'une séquence",
              (("black", "Image noire"), ("hold", "Garder la précédente"), ("card", "Carte « manquante »"))),
    _v_slider("video_prefetch_ahead", "Préchargement avant", 0, 240, "img"),
    _v_slider("video_prefetch_behind", "Préchargement arrière", 0, 120, "img"),
    _v_bool("video_reset_position", "Ouvrir sur la première image (sinon : dernière position de la session)"),
    Spec("video_key_in", "Raccourci : point IN", "shortcut", "Shift+I"),
    Spec("video_key_out", "Raccourci : point OUT", "shortcut", "Shift+O"),
    Spec("video_key_clear", "Raccourci : effacer IN / OUT", "shortcut", "Shift+X"),
]
CATALOG["Vidéo : Timeline"] = [
    _v_slider("video_timeline_height", "Hauteur", 30, 140),
    _v_slider("video_timeline_tick", "Taille des graduations", 2, 30),
    _v_slider("video_timeline_density", "Écart mini entre graduations", 30, 300),
    _v_choice("video_time_display", "Unité de timeline par défaut",
              (("frames", "Images"), ("seconds", "Secondes"), ("timecode", "Timecode"),
               ("both", "Images + timecode"))),
    _v_slider("video_timeline_zoom_step", "Sensibilité du zoom", 2, 100, "%"),
    _v_bool("video_timeline_zoom_cursor", "Zoom autour du curseur"),
    _v_bool("video_timeline_cache", "Montrer les images en cache"),
    _v_bool("video_timeline_thumbs", "Bande des miniatures (images lues au clic du bouton « Miniatures »)"),
    _v_slider("video_timeline_thumb_height", "Hauteur des miniatures par défaut (aussi : tirer le bord haut de la bande)",
              16, 240, reset=40),
    _v_color("video_timeline_playhead", "Couleur de la tête de lecture"),
    _v_color("video_timeline_selection", "Couleur de la sélection"),
    _v_color("video_timeline_in", "Couleur du point IN"),
    _v_color("video_timeline_out", "Couleur du point OUT"),
    _v_color("video_timeline_bg", "Couleur de fond"),
    _v_color("video_timeline_ruler", "Couleur de la règle"),
    _v_color("video_timeline_text", "Couleur des graduations"),
]
CATALOG["Vidéo : Moodboard"] = [
    _v_choice("video_match_lut_size", "Matching : résolution LUT", ((17,"17³"),(33,"33³"),(65,"65³"),(129,"129³"))),
    _v_slider("video_match_intensity", "Matching : intensité", 0, 100, "%"),
    _v_choice("video_match_method", "Matching : méthode", ((0,"Scènes différentes"),(1,"Paire alignée"))),
    _v_slider("video_analysis_colors", "Analyse : nombre de couleurs", 2, 32, ""),
    _v_bool("video_analysis_exclude_black", "Palette : exclure les noirs profonds"),
    _v_bool("video_analysis_exclude_white", "Palette : exclure les blancs extrêmes"),
    _v_color("video_moodboard_bg_color", "Couleur de fond du moodboard"),
    _v_slider("video_moodboard_proxy_width", "Largeur des images proxy", 128, 7680, "px"),
]
CATALOG["Vidéo : Aide pédagogique"] = [
    _v_bool("video_help_enabled", "Aide détaillée Ctrl + Shift"),
    _v_slider("video_help_delay", "Délai d’apparition", 0, 2000, "ms"),
    _v_slider("video_help_width", "Largeur des explications", 280, 800, "px"),
]
CATALOG["Vidéo : Infos dans images"] = [
    _v_choice("video_mood_info_format", "Format temporel", (("clock","HH:MM:SS.mmm"),("seconds","Secondes"),("frames","Frames"))),
    _v_choice("video_mood_info_position", "Position", (("top_right","Haut droite"),("top_left","Haut gauche"),("bottom_right","Bas droite"),("bottom_left","Bas gauche"))),
    _v_slider("video_mood_info_margin_x", "Marge horizontale", 0, 40, "px"),
    _v_slider("video_mood_info_margin_y", "Marge verticale", 0, 40, "px"),
    _v_bool("video_mood_info_enabled", "Informations temporelles (touche I)"),
    _v_bool("video_mood_info_timestamp", "Timestamp de l’image"),
    _v_bool("video_mood_info_interval", "Intervalle jusqu’à l’image suivante"),
    _v_slider("video_mood_info_font_size", "Taille du texte", 6, 36, "px"),
    _v_color("video_mood_info_color", "Couleur du texte"),
    _v_color("video_mood_info_bg", "Couleur du fond"),
    _v_slider("video_mood_info_opacity", "Opacité du fond", 0, 100, "%"),
    _v_slider("video_mood_info_radius", "Border radius", 0, 20, "px"),
    _v_slider("video_mood_info_padding", "Padding", 0, 20, "px"),
]
CATALOG["Vidéo : Couleur"] = [
    Spec("video_ocio_config", "Configuration OCIO (vide = $OCIO, sinon ACES CG intégrée)", "text", ""),
    _v_choice("video_display", "Display", _ocio_choices("display")),
    _v_choice("video_view_video", "View des vidéos", _ocio_choices("view")),
    _v_choice("video_view_image", "View des images (EXR, TIFF…)", _ocio_choices("view")),
    _v_choice("video_input_video", "Espace d'entrée : vidéos", _ocio_choices("space")),
    _v_choice("video_input_exr", "Espace d'entrée : EXR / HDR", _ocio_choices("space")),
    _v_choice("video_input_float", "Espace d'entrée : autres images flottantes (TIFF 32 bits…)",
              _ocio_choices("space")),
    _v_choice("video_input_int", "Espace d'entrée : images entières (PNG, JPEG, TIFF 8 / 16 bits, DPX)",
              _ocio_choices("space")),
    _v_choice("video_alpha_mode", "Alpha", (("auto", "Auto (EXR / DPX prémultipliés, autres droits)"),
                                            ("premult", "Prémultiplié"), ("straight", "Droit"), ("ignore", "Ignorer"))),
    _v_choice("video_channel", "Canal affiché par défaut", (("rgb", "RVB"), ("r", "Rouge"), ("g", "Vert"),
                                                          ("b", "Bleu"), ("a", "Alpha"), ("luma", "Luminance"))),
    _v_bool("video_clipping", "Signaler l'écrêtage (> 1 magenta, < 0 bleu)"),
    _v_choice("video_grade_on_change", "Corrections au changement de média",
              (("keep", "Gardées"), ("reset", "Remises à zéro"))),
]
CATALOG["Vidéo : LUT"] = [
    Spec("video_lut_dir", "Bibliothèque de LUT (dossier)", "text", ""),
    Spec("video_lut_default", "LUT par défaut (chemin d'un .cube)", "text", ""),
    _v_bool("video_lut_auto", "Appliquer la LUT par défaut à l'ouverture"),
    _v_slider("video_lut_mix", "Intensité par défaut", 0, 100, "%"),
    _v_choice("video_lut_position", "Position dans le pipeline",
              (("display", "Créative : après l'affichage (LUT Rec.709 / sRGB)"),
               ("source", "Technique : sur le fichier, avant l'espace d'entrée (LUT Log -> Rec.709)"))),
]
CATALOG["Vidéo : Performances"] = [
    _v_slider("video_cache_mb", "RAM maximale du cache d'images", 256, 32768, "Mo"),
    _v_slider("video_workers", "Fils de lecture des séquences", 1, 16, ""),
    _v_choice("video_backend", "Affichage", (("auto", "Auto (OpenGL si possible)"), ("opengl", "OpenGL (GPU)"),
                                             ("cpu", "CPU (repli, lent)"))),
    _v_bool("video_diagnostics", "Diagnostic : cache et moteur dans les informations"),
]
CATALOG["Vidéo : Export"] = [
    _v_choice("video_export_format", "Format par défaut", (("mp4", "MP4"), ("mov", "MOV"), ("mkv", "MKV"),
                                                         ("webm", "WEBM"), ("exr", "Séquence EXR"),
                                                         ("tiff", "Séquence TIFF"), ("png", "Séquence PNG"),
                                                         ("dpx", "Séquence DPX"))),
    _v_choice("video_export_codec", "Codec par défaut", (("h264", "H.264"), ("h265", "H.265 / HEVC"),
                                                       ("prores", "ProRes"), ("dnxhr", "DNxHR"), ("av1", "AV1"),
                                                       ("vp9", "VP9"))),
    _v_slider("video_export_crf", "Qualité (CRF, plus bas = meilleur)", 0, 51, ""),
    _v_choice("video_export_preset", "Preset d'encodage", tuple((p, p) for p in (
        "ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"))),
    Spec("video_export_dir", "Dossier de sortie (vide = celui du média)", "text", ""),
    _v_choice("video_export_color", "Contenu exporté par défaut",
              (("display", "Tel qu'affiché (corrections, LUT, affichage)"),
               ("working", "Linéaire corrigé (EXR : espace de travail)"), ("data", "Données source (sans rien)"))),
    _v_bool("video_export_lut", "Inclure la LUT"),
    _v_choice("video_export_fps_mode", "Changement de FPS",
              (("resample", "Rééchantillonner (durée gardée)"), ("reinterpret", "Réinterpréter (durée changée)"),
               ("interpolate", "Images intermédiaires (durée gardée)"))),
    _v_choice("video_export_interp", "Méthode d'interpolation",
              (("minterpolate", "Flux optique (FFmpeg)"), ("blend", "Fondu (FFmpeg)"), ("rife", "IA : RIFE"))),
    Spec("video_rife_path", "rife-ncnn-vulkan.exe (vide = cherché dans le PATH)", "text", ""),
    _v_bool("video_export_audio", "Audio"),
    _v_choice("video_export_depth", "Profondeur des séquences", (("half", "EXR half / 16 bits"),
                                                               ("float", "EXR float / 32 bits"),
                                                               ("16", "16 bits entiers"), ("8", "8 bits"))),
    _v_choice("video_export_numbering", "Numérotation des séquences",
              (("source", "Celle de la source"), ("1", "À partir de 1"), ("1001", "À partir de 1001"))),
    _v_bool("video_export_overwrite", "Écraser les fichiers existants"),
]


# Onglet « Module vidéo » (voir CATALOG["Vidéo : …"]).
VIDEO_TREE = (
    Node("Ouverture", "Vidéo : Ouverture"),
    Node("Affichage", "Vidéo : Affichage"),
    Node("Informations en surimpression", "Vidéo : Informations"),
    Node("Lecture", "Vidéo : Lecture"),
    Node("Timeline", "Vidéo : Timeline"),
    Node("Moodboard", "Vidéo : Moodboard",children=(Node("Infos dans images","Vidéo : Infos dans images"),)),
    Node("Aide pédagogique", "Vidéo : Aide pédagogique"),
    Node("Couleur (OCIO, EXR / TIFF, vidéo)", "Vidéo : Couleur"),
    Node("LUT", "Vidéo : LUT"),
    Node("Performances", "Vidéo : Performances"),
    Node("Export et interpolation", "Vidéo : Export"),
)

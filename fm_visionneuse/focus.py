"""Etat « focus » : se concentrer sur UN objet precis (aujourd'hui l'apercu image/
turntable de l'inspecteur ; plus tard texte, informations...). Ce module recevra
tout ce qui releve de cet etat ; il vient apres browser_core dans l'ordre de
dependance.

Visionneuse (colonnes masquees, image seule au centre) : l'image glisse d'un fichier a l'autre
sur un RUBAN (la suivante arrive du cote ou l'on va, la precedente s'efface en reculant), se
zoome autour du curseur, et une PELLICULE de vignettes la suit en bas ; les images sont decodees
en fond, voisines prechargees (FocusImageLoader) : rien de lourd sur le fil de l'interface.

FAÇADE de compatibilité (2026-10-28) : le code est découpé en sous-modules du paquet (carte :
docs/agents/fm_visionneuse.md). Lire / appeler par `focus.X` reste possible ; pour PATCHER un nom ou
RÉAFFECTER une variable de module, viser le sous-module qui le définit (ex. `gallery.SHOW_KEYWORDS`)."""
from .loader import (  # noqa: F401
    DISPLAY_NAMES, FocusImageLoader, _DecodeSignals, _DecodeTask, _pixmap_size, _quarter_turn, _scaled_about,
    display_name, fit_rect,
)
from .film_cache import (  # noqa: F401
    FILM_SCALE_BUDGET, FILM_THUMB_DIR, FILM_THUMB_MAX, PROXY_MARGIN, _CELLS, _CELLS_MAX, _FILM, _FILM_FAILED, _FILM_MAX,
    _FILM_PENDING, _FILM_POOL, _FILM_SIGNALS, _FilmSignals, _FilmTask, _MARKED, _PROXIES, _PROXIES_BUDGET,
    _ProxySignals, _ProxyTask, _SCALE_DEADLINE, _THUMBS, _THUMBS_MAX, _drop_proxy, _film_base, _film_look_signature,
    _film_order, _film_source, _has_transparency, _on_film_done, _proxy_bytes, _store_proxy, thumbnail,
)
from .film_look import (  # noqa: F401
    _FILM_SIDES, _PROXY_SOURCES, _film_inner, _film_look, _gallery_mark_on_sub_cells, _gallery_mark_radius,
    _paint_color_mark, _paint_film_box, _paint_gallery_mark, film_text_ratio, placeholder_pixmap,
)
from .overlay import (  # noqa: F401
    FocusOverlay,
)
from .filmstrip import (  # noqa: F401
    FocusFilmstrip, ProxySourceTip,
)
from .attributes_ui import (  # noqa: F401
    FileAttributesEditor, KeywordsWindow, _ColorLabels, _StarRating, _StatusFlags, filter_colors,
)
from .gallery_paint import (  # noqa: F401
    COLOR_SLOTS, SHOW_KEYWORDS, _FLAG_PIXMAPS, _GalleryDelegate, _backdrop, _flag_pixmap, _gallery_look,
    _paint_attr_controls, _paint_attrs, _paint_flag, _paint_gallery_text_override, _paint_star, _star_polygon, attr_gap,
    attr_hit, attr_inset, attr_layout, attr_unit,
)
from .gallery import (  # noqa: F401
    FocusGallery,
)
from .info import (  # noqa: F401
    _EXIF_ORIENTATION, _InfoSignals, _InfoTask, _PIL_MODES, _PNG_COLOR, _clean, _exif_rows, _gps_degrees, _num,
    _png_header, _size_text, image_info, image_sources,
)
from .info_panel import (  # noqa: F401
    FocusInfoPanel,
)
from .filter_ui import (  # noqa: F401
    FilterChips, _filter_window_menu_extra, _install_filter_menu, filter_row_look, filter_window,
)

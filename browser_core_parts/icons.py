"""Icônes des logiciels, vignettes de dossier et caches associés. Carte : docs/agents/colonnes.md."""

from pathlib import Path
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygon
from app_style import C, custom_softwares, removed_softwares, font
from config import ICONS_DIR, THUMBNAIL_FILENAME
from previews import cached_mtime as _previews_mtime
from previews import SOFTWARE_ICONS, UI_ICON_FILE_DEFAULT, UI_ICON_FOLDER_DEFAULT, UI_ICON_PIN_ACTIVE, UI_ICON_PIN_INACTIVE, _FALLBACK_SOFTWARE_BADGE_PALETTE, _bounded_cache_set, _contain_square, _software_icon_cache, custom_software_icon_path, custom_ui_icon_pixmap
from . import scan as _scan

def _fallback_software_badge_style(key: str) -> tuple[str, str, str]:
    """Couleur/lettres d'un logiciel AJOUTE par l'utilisateur (voir
    software_icon_key/app_style.custom_softwares) : pas de charte connue
    comme SOFTWARE_ICONS, mais un badge STABLE (meme cle -> toujours la
    meme couleur/les memes lettres) plutot qu'un rendu incoherent."""
    label_source = next((e["label"] for e in custom_softwares() if e["key"] == key), key)
    bg, fg = _FALLBACK_SOFTWARE_BADGE_PALETTE[sum(ord(c) for c in key) % len(_FALLBACK_SOFTWARE_BADGE_PALETTE)]
    letters = "".join(ch for ch in label_source if ch.isalnum())[:2].upper() or "?"
    return bg, fg, letters

def _generate_software_badge(key: str, size: int) -> QPixmap:
    entry = SOFTWARE_ICONS.get(key)
    bg, fg, label = entry if entry is not None else _fallback_software_badge_style(key)
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(bg))
    radius = max(2, round(size * 0.22))
    painter.drawRoundedRect(0, 0, size, size, radius, radius)
    painter.setFont(font(max(8, round(size * 0.44)), 700))
    painter.setPen(QColor(fg))
    painter.drawText(QRect(0, 0, size, size), Qt.AlignCenter, label)
    painter.end()
    return pix

def software_choices() -> list[tuple[str, str, str]]:
    """Logiciels de la liste des reglages (General > ICONES > Logiciels), dans son ordre : ceux
    d'origine (SOFTWARE_ICONS) moins ceux retires, puis ceux ajoutes. (cle, libelle, nom de dossier) ;
    dossier en minuscules comme ceux du pipeline (softs\\houdini), reconnu par software_icon_key."""
    removed = removed_softwares()
    choices = [(key, key.capitalize(), key.lower()) for key in sorted(SOFTWARE_ICONS) if key not in removed]
    for entry in custom_softwares():
        if entry["key"] not in SOFTWARE_ICONS:
            label = (entry.get("label") or entry["key"]).strip()
            choices.append((entry["key"], label, label.lower()))
    return choices

def software_icon_pixmap(key: str, size: int) -> QPixmap:
    """Icone perso (voir custom_software_icon_path) si elle existe, sinon
    badge genere pour le logiciel `key` (voir SOFTWARE_ICONS)."""
    custom = custom_software_icon_path(key)
    mtime = _previews_mtime(custom)

    cache_key = (key, size)
    cached = _software_icon_cache.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]

    pix = None
    if mtime is not None:
        loaded = QPixmap(str(custom))
        if not loaded.isNull():
            pix = _contain_square(loaded, size)
    if pix is None:
        pix = _generate_software_badge(key, size)

    _software_icon_cache[cache_key] = (mtime, pix)
    return pix

def _row_icon_pixmap(is_dir: bool, icon_key: str | None, size: int) -> QPixmap | None:
    """Icone de gauche pour UNE ligne (voir _paint_unified_row) : celle du
    logiciel reconnu si `icon_key` en a un ; sinon, le REPLI par defaut
    dossier/fichier choisi dans Settings > ICONES > General (voir
    UI_ICON_FOLDER_DEFAULT/UI_ICON_FILE_DEFAULT) si l'utilisateur en a
    choisi un ; sinon None (comportement inchange : aucune icone)."""
    if icon_key is not None:
        return software_icon_pixmap(icon_key, size)
    return custom_ui_icon_pixmap(UI_ICON_FOLDER_DEFAULT if is_dir else UI_ICON_FILE_DEFAULT, size)

_PIN_ICON_CACHE: dict[tuple[bool, int], QPixmap] = {}

def _pin_icon_pixmap(active: bool, size: int) -> QPixmap:
    """Icone punaise d'en-tete de colonne (voir Column._toggle_pin, la
    remarque de l'utilisateur, "je viens de te coller deux icones ...
    punaise_01.png [par defaut] / punaise_02.png [actif]") — chargee une
    fois depuis icons/, puis mise a l'echelle en carre CONTENU (voir
    _contain_square/_smooth_scale_down, memes raisons que software_icon_
    pixmap : source haute resolution, jamais pixelisee en la retrecissant
    vers la petite taille d'en-tete)."""
    custom = custom_ui_icon_pixmap(UI_ICON_PIN_ACTIVE if active else UI_ICON_PIN_INACTIVE, size)
    if custom is not None:
        return custom
    key = (active, size)
    cached = _PIN_ICON_CACHE.get(key)
    if cached is not None:
        return cached
    src = QPixmap(str(ICONS_DIR / ("punaise_02.png" if active else "punaise_01.png")))
    pix = _contain_square(src, size) if not src.isNull() else QPixmap()
    _PIN_ICON_CACHE[key] = pix
    return pix

def project_thumbnail_path(directory: Path) -> Path:
    """Emplacement de la vignette perso d'un dossier de projet (fichier
    cache, jamais liste par list_entries puisqu'il commence par un point)."""
    return directory / THUMBNAIL_FILENAME

_project_thumbnail_cache: dict[str, tuple[float | None, QPixmap]] = {}

def has_project_thumbnail(path: Path) -> bool:
    """Le dossier `path` a une vignette perso (date memorisee un instant, voir cached_mtime)."""
    return _previews_mtime(project_thumbnail_path(path)) is not None

def project_thumbnail_pixmap(path: Path) -> QPixmap:
    """Vignette perso de `path` (voir project_thumbnail_path), ou image par
    defaut generique si aucune n'a ete choisie. Mise en cache par date de
    modification (cache borne, voir _bounded_cache_set) — seule source pour
    ces vignettes : ProjectTileDelegate (colonnes) et l'apercu empile de la
    premiere colonne s'y refere tous deux, plutot que de garder chacun leur
    propre copie en memoire du meme fichier."""
    thumb = project_thumbnail_path(path)
    mtime = _previews_mtime(thumb)
    key = str(path)
    cached = _project_thumbnail_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    if _scan._remote_gui(thumb) and mtime is not None:
        from previews import file_image_pixmap
        pix = file_image_pixmap(thumb, asynchronous=True)
        if pix is None:
            return default_thumbnail()   # ne pas mémoriser ce repli pendant le décodage
        _bounded_cache_set(_project_thumbnail_cache, key, (mtime, pix))
        return pix
    pix = QPixmap(str(thumb)) if mtime is not None else QPixmap()
    if pix.isNull():
        pix = default_thumbnail()
    _bounded_cache_set(_project_thumbnail_cache, key, (mtime, pix))
    return pix

_default_thumbnail: QPixmap | None = None

def default_thumbnail() -> QPixmap:
    """Image generique (montagne + soleil) utilisee tant qu'aucune vignette
    perso n'a ete choisie pour un projet. Generee une seule fois."""
    global _default_thumbnail
    if _default_thumbnail is not None:
        return _default_thumbnail

    size = 480
    pix = QPixmap(size, size)
    pix.fill(QColor(C["well"]))

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)

    margin = round(size * 0.26)
    frame = pix.rect().adjusted(margin, margin, -margin, -margin)

    pen = QPen(QColor(C["mark_dir_bd"]))
    pen.setWidth(round(size * 0.014))
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(frame, 8, 8)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(C["mark_dir_bd"]))

    sun_r = round(frame.width() * 0.11)
    sun_c = QPoint(frame.left() + round(frame.width() * 0.27), frame.top() + round(frame.height() * 0.3))
    painter.drawEllipse(sun_c, sun_r, sun_r)

    poly = QPolygon([
        QPoint(frame.left() + round(frame.width() * 0.04), frame.bottom() - round(frame.height() * 0.1)),
        QPoint(frame.left() + round(frame.width() * 0.38), frame.top() + round(frame.height() * 0.38)),
        QPoint(frame.left() + round(frame.width() * 0.58), frame.bottom() - round(frame.height() * 0.28)),
        QPoint(frame.left() + round(frame.width() * 0.74), frame.top() + round(frame.height() * 0.56)),
        QPoint(frame.right() - round(frame.width() * 0.04), frame.bottom() - round(frame.height() * 0.1)),
    ])
    painter.drawPolygon(poly)
    painter.end()

    _default_thumbnail = pix
    return pix

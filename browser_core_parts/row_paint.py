"""Rôles, peinture des lignes, images et badges. Carte : docs/agents/colonnes.md."""

import json
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from app_style import C, font, role_font, resolve_color_ref, column_style_for
import ui_state
from previews import _smooth_scale_down
from settings_widgets import _paint_bordered_rect, _radius_any, _radius_dict, _rounded_rect_path, paint_shadow, shadow_look
from . import dimensions as _dimensions

# Reglable en direct (voir apply_all_settings/STEP_BADGE_STYLE, Settings >
# Colonnes > Projets > Colonnes > "Icone de niveaux") — ces 2 constantes ne
# restent que comme les toutes PREMIERES valeurs par defaut (avant le tout
# premier apply_all_settings au demarrage, voir main()).



def _step_badge_color(n: int | str) -> str:
    """Couleur du badge numerote (voir ProjectTileDelegate.paint) selon le
    nombre d'etapes `n` (project_step_count) — une des 5 couleurs reglables
    (STEP_BADGE_STYLE["colors"], Settings > Colonnes > Projets > Colonnes >
    "Icone de niveaux", "couleur fond base 2 a 6") : n est BORNE a [2, 6],
    2 pour tout n <= 2, 6 pour tout n >= 6 (chaine plus longue que prevu
    par les 5 couleurs — reutilise la derniere plutot que planter).
    `n == "N"` (voir project_step_count, toggle "set" desactive dans
    ColumnConfigDialog) : 6e couleur DEDIEE (STEP_BADGE_STYLE["colors"]
    ["N"]), jamais confondue avec la base 2 — voir la remarque de
    l'utilisateur, "quand set est desactive je veux que l'indicateur de
    base affiche N ... rajoute cette option pour le choix de la couleur
    dans les settings".
    resolve_color_ref (PAS la valeur brute) : ce champ (_AppOrCustomColorField,
    voir sa docstring) peut valoir soit un hex direct, soit une reference
    "@<slot>" a une pastille semantique de l'appli — SANS cette resolution,
    une couleur "app" choisie ici produisait un QColor invalide (chaine
    "@accent" telle quelle, jamais un hex) — voir la remarque de
    l'utilisateur, "il y a des bugs avec les couleurs appli, ca ne
    fonctionne pas"."""
    key = "N" if n == "N" else max(2, min(6, n))
    return resolve_color_ref(ui_state.STEP_BADGE_STYLE["colors"][key])

def _step_badge_text_color(n: int | str) -> str:
    """Couleur du TEXTE du badge — une PAR base (2 a 6, PAS une seule
    globale) — voir STEP_BADGE_STYLE["text_colors"], Settings > Colonnes >
    Projets > Colonnes > "Icone de niveaux", carre du HAUT de chaque paire
    — voir la remarque de l'utilisateur, "la couleur du haut est pour le
    texte (pour chacune des bases) et la couleur du bas est pour le
    fond". MEME bornage/MEME resolution/MEME cas "N" que _step_badge_color."""
    key = "N" if n == "N" else max(2, min(6, n))
    return resolve_color_ref(ui_state.STEP_BADGE_STYLE["text_colors"][key])

def _row_preview_left_x(row_rect: QRect, style: dict) -> int:
    """Bord GAUCHE du slot ou l'apercu se dessine sur cette ligne (voir
    _paint_unified_row, "apercu ... ANCRE sur le bord DROIT de la zone de
    selection") — calcul PARTAGE avec le hit-test du badge numerote (voir
    _step_badge_rect/Column.eventFilter), pour rester synchronises SANS
    dupliquer la formule."""
    pad = style.get("item_selection_padding") or {}
    sel_left = row_rect.left() + max(0, int(pad.get("left", 0)))
    sel_width = row_rect.width() - max(0, int(pad.get("left", 0))) - max(0, int(pad.get("right", 0)))
    img_size = row_rect.height() - max(0, int(pad.get("top", 0))) - max(0, int(pad.get("bottom", 0)))
    if img_size <= 0:
        img_size = 14
    img_ratio = float(style.get("item_image_ratio", 1.0) or 1.0)
    img_width = max(1, round(img_size * img_ratio))
    if sel_width > 0:
        return sel_left + sel_width - img_width
    return row_rect.right() - img_width

def _step_badge_rect(row_rect: QRect, preview_left: int | None = None) -> QRect:
    """Rect du badge numerote — voir ProjectTileDelegate.paint/Column.
    eventFilter, fonction PARTAGEE entre le dessin et le hit-test du clic,
    pour rester synchronisees. `preview_left` (voir _row_preview_left_x) :
    juste AVANT (a gauche de) l'apercu de la ligne, PAS par-dessus (voir la
    remarque de l'utilisateur, "j'aimerai que la petite icone de levels
    soit avant l'apercu et pas a l'interieur") — repli sur l'ancien
    comportement (haut-droite de row_rect) si aucun apercu n'est fourni
    (ne devrait plus arriver en pratique, "Projets" en a toujours un, voir
    project_thumbnail_pixmap)."""
    width = ui_state.STEP_BADGE_STYLE["width"]
    height = ui_state.STEP_BADGE_STYLE["height"]
    offset_x = ui_state.STEP_BADGE_STYLE["offset_x"]
    offset_y = ui_state.STEP_BADGE_STYLE["offset_y"]
    if preview_left is not None:
        x = preview_left - offset_x - width
        y = row_rect.top() + (row_rect.height() - height) // 2 + offset_y
    else:
        x = row_rect.right() - width - offset_x
        y = row_rect.top() + offset_x + offset_y
    return QRect(x, y, width, height)

# ==========================================================================
# Rendu des lignes
# ==========================================================================

ROLE_PATH = Qt.UserRole

ROLE_ISDIR = Qt.UserRole + 1

ROLE_META = Qt.UserRole + 2

# Annotation "(projet)"/"(<nom du sous-projet>)" a cote du nom, dans les
# colonnes IN/OVER/OUT du groupe (voir Column.__init__ source_labels,
# PipelineBrowser.update_preview_stack, _paint_unified_row) — None (partout
# ailleurs) = pas d'annotation, comportement INCHANGE — voir la remarque de
# l'utilisateur, "je veux une anotation a cote du nom du repertoire ...
# s'il vient de projet ou de sous projet".
ROLE_SOURCE_LABEL = Qt.UserRole + 3

# Position (2 = Type, 3 = Projets, 4 = Sous-projet, 5+ = niveaux configures
# suivants) de la colonne "de set" SOURCE d'une ligne fusionnee IN/OVER/OUT
# (voir Column.refresh, PipelineBrowser.update_preview_stack) — reutilise
# TEL QUEL le meme palier de couleur que le badge numerote (voir
# _step_badge_color/STEP_BADGE_STYLE, Settings > Colonnes > Projets >
# Colonnes > "Icone de niveaux") pour colorer l'etiquette d'origine
# differemment selon l'etape source — voir la remarque de l'utilisateur,
# "les couleurs des indications doivent changer selon les etapes". None
# (partout ailleurs) = couleur fixe inchangee.
ROLE_SOURCE_STEP = Qt.UserRole + 4

# Vrai pour une ligne "raccourci" (voir load_shortcuts/Column.refresh,
# Column._on_context_menu "Ajouter un raccourci") : un dossier situe
# AILLEURS sur le disque, affiche comme s'il etait physiquement dans CE
# dossier — voir _resolve_shortcut_font_color/SHORTCUT_TEXT_STYLE (police/
# couleur dediees, Settings > RACCOURCI) pour le distinguer visuellement,
# et le menu contextuel reduit ("Retirer le raccourci" au lieu de
# Renommer/Supprimer, qui agirait par erreur sur la VRAIE cible).
ROLE_IS_SHORTCUT = Qt.UserRole + 5

ROLE_LIGHTROOM_SHORTCUT = Qt.UserRole + 95

ROLE_MEDIA_COUNTS = Qt.UserRole + 96

# Espace (px) au-dessus d'une ligne, choisi par clic droit > « Ajouter une espace au-dessus » ; retenu
# dans le .pipeline_layout.json du dossier de la ligne (`item_spaces`, cle = son nom). Les delegues
# l'ajoutent a la hauteur et dessinent la ligne en dessous.
ROLE_SPACE_ABOVE = Qt.UserRole + 6

# Titre pose DANS l'espace au-dessus d'une ligne (clic droit > « Ajouter un titre au-dessus ») :
# {"text": str, "style": {cles title_font_* / title_padding}} ; retenu comme l'espace (`item_titles`).
ROLE_TITLE_ABOVE = Qt.UserRole + 7

# Espace (px) EN DESSOUS d'une ligne (clic droit > « Ajouter une espace en dessous ») : meme principe
# que ROLE_SPACE_ABOVE (`item_spaces_below`) ; ajoute a la hauteur, la ligne dessinee au-dessus.
ROLE_SPACE_BELOW = Qt.UserRole + 8

# Clic droit > « Positionner au bas de la colonne » : les lignes marquees (`item_bottom`, liste de
# cles) sont rangees apres les autres, empilees contre le bas de la colonne. ROLE_BOTTOM_GAP = vide
# (px) pose au-dessus de la PREMIERE d'entre elles pour les pousser en bas, recalcule a chaque
# changement de hauteur (Column.sync_bottom_gap) ; ajoute par les delegues avant l'espace au-dessus.
ROLE_PIN_BOTTOM = Qt.UserRole + 9

ROLE_BOTTOM_GAP = Qt.UserRole + 10

# Style d'un titre de ligne (fenetre flottante « Style du titre » : Police | Padding). Memes cles
# que la ligne police / padding de la fenetre de reglages (prefixe `title`).
ITEM_TITLE_DEFAULT_STYLE = {
    "title_font_family": "", "title_font_bold": True, "title_font_italic": False, "title_font_size": 10,
    "title_font_smoothing_enabled": False, "title_font_smoothing": "current", "title_font_color": "#9aa1a7",
    "title_padding": {"left": 8, "top": 2, "right": 8, "bottom": 2}, "title_padding_linked": False,
}

def item_title_style(style: dict | None) -> dict:
    merged = json.loads(json.dumps(ITEM_TITLE_DEFAULT_STYLE))
    merged.update(style or {})
    return merged

def item_title_font(style: dict):
    from PySide6.QtGui import QFont
    style = item_title_style(style)
    qfont = QFont(style["title_font_family"] or QApplication.font().family())
    qfont.setPixelSize(max(4, int(style["title_font_size"])))
    qfont.setBold(bool(style["title_font_bold"]))
    qfont.setItalic(bool(style["title_font_italic"]))
    if style["title_font_smoothing_enabled"] and style["title_font_smoothing"] == "none":
        qfont.setStyleStrategy(QFont.NoAntialias)
    return qfont

def item_title_min_height(style: dict | None = None) -> int:
    """Hauteur d'espace necessaire pour un titre : une ligne de texte + padding haut et bas."""
    from PySide6.QtGui import QFontMetrics
    style = item_title_style(style)
    pad = style["title_padding"] or {}
    return QFontMetrics(item_title_font(style)).height() + int(pad.get("top", 0)) + int(pad.get("bottom", 0))

def paint_item_title(painter: QPainter, rect: QRect, title: dict | None) -> None:
    """Titre d'une ligne, dans `rect` (l'espace au-dessus de la ligne) : cale en bas a gauche, dans
    son padding, coupe par des points de suspension s'il est trop long."""
    if not title or not title.get("text") or rect.height() <= 0:
        return
    style = item_title_style(title.get("style"))
    pad = style["title_padding"] or {}
    text_rect = rect.adjusted(int(pad.get("left", 0)), int(pad.get("top", 0)),
                              -int(pad.get("right", 0)), -int(pad.get("bottom", 0)))
    qfont = item_title_font(style)
    painter.save()
    painter.setClipRect(rect)
    painter.setFont(qfont)
    painter.setPen(QColor(resolve_color_ref(style["title_font_color"], "#9aa1a7")))
    from PySide6.QtGui import QFontMetrics
    text = QFontMetrics(qfont).elidedText(str(title["text"]), Qt.ElideRight, max(0, text_rect.width()))
    painter.drawText(text_rect, int(Qt.AlignLeft | Qt.AlignBottom | Qt.TextSingleLine), text)
    painter.restore()

def _paint_row_border(painter: QPainter, rect, option, style: dict):
    """Filet horizontal ENTRE les lignes (voir DEFAULT_SETTINGS.
    item_row_border_*/settings_window._ITEM_TEXT_FIELD_SPECS/_RowBorderField)
    — partage par toutes les colonnes (voir _paint_unified_row) pour eviter
    de dupliquer ce calcul —
    voir la remarque de l'utilisateur, "place ensuite cette meme section
    dans les onglets projets et sous projets pour y controler les colonnes
    respectives".

    A APPELER AVANT la selection (pas apres) : celle-ci, peinte par
    l'appelant juste apres, doit pouvoir RECOUVRIR le filet la ou elle
    deborde dessus — sinon le filet tranchait visiblement le bas du
    rectangle de selection des que le padding de selection ou l'espacement
    entre lignes etait faible (voir la remarque de l'utilisateur, capture a
    l'appui, "c'est comme si la bordure etait posee sur la derniere ligne
    de la selection")."""
    if not style.get("item_row_border_enabled"):
        return
    thickness = max(1, int(style.get("item_row_border_thickness", 1)))
    border_color = resolve_color_ref(style.get("item_row_border_color", "@ligne"))
    # Centre dans l'ESPACEMENT entre 2 lignes (voir ROW_SPACING), pas colle
    # au bas de CETTE ligne : `rect` exclut deja cet espacement (voir
    # l'appel du delegate, option.rect.adjusted(0, 0, 0, -spacing)) —
    # `option.rect`, lui, le comprend encore, d'ou le milieu entre les 2
    # pour rester centre meme si l'espacement change (voir la remarque de
    # l'utilisateur, "je veux que cette bordure soit exactement au milieu
    # de deux lignes, meme quand on augmente l'espacement"). fillRect (PAS
    # drawLine+QPen) avec l'antialiasing coupe : un filet de 1px trace au
    # pinceau sur une coordonnee entiere se retrouve sinon reparti sur 2
    # lignes de pixels a 50% de couverture chacune (lissage) —
    # visuellement 2px flous au lieu d'1px net (voir la remarque de
    # l'utilisateur, "en realite elle en fait deux"). Entiers UNIQUEMENT
    # (PAS de round() sur un flottant) : un arrondi pouvait retomber pile
    # sur rect.bottom() (dernier pixel du CONTENU de la ligne, PAS
    # l'espacement) des que gap+epaisseur donnait une somme impaire (ex.
    # espacement=1/epaisseur=1). Reste sous rect.bottom() (borne bas
    # comprise) tant que l'espacement est suffisant ; ne deborde vers LE
    # HAUT de CETTE ligne que si l'epaisseur choisie depasse l'espacement
    # disponible — jamais vers le bas dans la ligne SUIVANTE (qui se
    # repeindrait par-dessus, rendant le filet invisible a chaque frame).
    gap_top = rect.bottom() + 1
    gap_h = max(0, option.rect.bottom() - rect.bottom())
    if thickness <= gap_h:
        top = gap_top + (gap_h - thickness) // 2
    else:
        top = gap_top + gap_h - thickness
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.fillRect(QRect(rect.left(), top, rect.width(), thickness), QColor(border_color))
    painter.restore()

_IMAGE_MASK_CACHE: dict[tuple, QPixmap] = {}

_IMAGE_MASK_CACHE_MAX = 128

def _rounded_mask_pixmap(width: int, height: int, radius: dict) -> QPixmap:
    """Masque (blanc opaque a l'interieur, transparent au coin arrondi)
    sur-echantillonne 8x pour _paint_row_image, mis en CACHE par (taille,
    rayon) — CONTENU-INDEPENDANT (contrairement au composite final, qui
    depend de l'image affichee et reste recalcule a chaque ligne) : evite
    de re-rasteriser le meme contour antialiase a CHAQUE ligne et a CHAQUE
    frame de scroll — voir la remarque de l'utilisateur, "il y a des
    ralentissements dans les animations, optimise un maximum"."""
    radius_key = tuple(sorted(radius.items()))
    key = (width, height, radius_key)
    cached = _IMAGE_MASK_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_IMAGE_MASK_CACHE) >= _IMAGE_MASK_CACHE_MAX:
        _IMAGE_MASK_CACHE.clear()
    SS = 8
    big = QSize(width * SS, height * SS)
    big_rect = QRect(0, 0, big.width(), big.height())
    big_radius = {k: v * SS for k, v in radius.items()}
    mask = QPixmap(big)
    mask.fill(Qt.transparent)
    mkp = QPainter(mask)
    mkp.setRenderHint(QPainter.Antialiasing, True)
    mkp.setPen(Qt.NoPen)
    mkp.setBrush(Qt.white)
    mkp.drawPath(_rounded_rect_path(big_rect, big_radius))
    mkp.end()
    _IMAGE_MASK_CACHE[key] = mask
    return mask

_ROW_IMAGE_CACHE: dict = {}

_ROW_IMAGE_CACHE_MAX = 600

def _row_image_pixmap(pixmap: QPixmap, phys_w: int, phys_h: int, radius: dict, dpr: float) -> QPixmap:
    """Vignette de ligne prete a peindre (voir _paint_row_image, qui la garde en cache) : recadree
    en « cover », coins arrondis antialiases, a la taille PHYSIQUE `phys_w` x `phys_h`."""
    if _radius_any(radius):
        # Masque construit a la main (REMPLISSAGE antialiase + composition
        # DestinationIn), PAS un setClipPath direct : le moteur RASTER de
        # Qt ne produit pas un clip vraiment antialiase. Sur-echantillonne
        # 8x (PAS 1 seule passe) : a un PETIT rayon, un chemin rasterise
        # directement a la resolution finale laissait un arrondi en
        # escalier (chaque pixel de coin couvert a 0% ou 100%, jamais entre
        # les deux) — voir la remarque de l'utilisateur, "l'antialiasing
        # est affreux" puis "peux tu ameliorer encore plus l'antialiasing"
        # (4x -> 8x). MEME facteur que le trait de bordure dans
        # _paint_bordered_rect. `radius` mis a l'echelle par dpr AVANT
        # de rejoindre le masque (PAS le rayon "logique" brut) : sinon les
        # coins paraitraient proportionnellement plus petits que prevu des
        # que dpr > 1 (le masque, lui, grandit avec phys_w/phys_h, le
        # rayon doit suivre pour rester visuellement identique).
        #
        # Le masque passe par un PIXMAP intermediaire (dessine ENTIEREMENT
        # par-dessus l'image avec drawPixmap), PAS par un fillPath direct
        # en DestinationIn : cette composition ne s'applique qu'aux pixels
        # que la primitive source TOUCHE reellement — un fillPath ne touche
        # que l'INTERIEUR du chemin, les coins (hors chemin) n'etaient donc
        # jamais composes et gardaient l'image intacte, laissant un carre
        # parfait malgre le rayon demande — voir la remarque de
        # l'utilisateur, capture a l'appui, "l'image doit avoir un coin
        # arrondi, le meme que la bordure". Un drawPixmap, lui, couvre TOUT
        # le rectangle : les coins du masque (transparents) y remettent
        # bien l'alpha a 0.
        #
        # `hires_cropped` recadre/reduit DIRECTEMENT `pixmap` (la source
        # ORIGINALE, haute resolution) a la taille SUR-ECHANTILLONNEE du
        # masque — PAS un recadrage prealable a la taille FINALE (phys_w/
        # phys_h) suivi d'un agrandissement 8x pour rejoindre le masque :
        # cet aller-retour (retrecir PUIS agrandir PUIS retrecir a nouveau)
        # perdait du detail a chaque etape — voir la remarque de
        # l'utilisateur, "je trouve les icones encore tres floues".
        radius_dpr = {k: v * dpr for k, v in radius.items()}
        mask = _rounded_mask_pixmap(phys_w, phys_h, radius_dpr)
        big = mask.size()
        hires = _smooth_scale_down(pixmap, big, Qt.KeepAspectRatioByExpanding)
        hsx = max(0, (hires.width() - big.width()) // 2)
        hsy = max(0, (hires.height() - big.height()) // 2)
        hires_cropped = hires.copy(hsx, hsy, min(big.width(), hires.width()), min(big.height(), hires.height()))

        masked = QPixmap(big)
        masked.fill(Qt.transparent)
        mp = QPainter(masked)
        mp.setRenderHint(QPainter.Antialiasing, True)
        mp.setRenderHint(QPainter.SmoothPixmapTransform, True)
        mp.drawPixmap(QRect(0, 0, big.width(), big.height()), hires_cropped)
        mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mp.drawPixmap(0, 0, mask)
        mp.end()

        masked = _smooth_scale_down(masked, QSize(phys_w, phys_h), Qt.IgnoreAspectRatio)
        masked.setDevicePixelRatio(dpr)
        return masked
    else:
        cropped = _smooth_scale_down(pixmap, QSize(phys_w, phys_h), Qt.KeepAspectRatioByExpanding)
        sx = max(0, (cropped.width() - phys_w) // 2)
        sy = max(0, (cropped.height() - phys_h) // 2)
        cropped = cropped.copy(sx, sy, min(phys_w, cropped.width()), min(phys_h, cropped.height()))
        cropped.setDevicePixelRatio(dpr)
        return cropped

def _paint_row_image(
    painter: QPainter, slot_rect: QRect, pixmap: QPixmap, style: dict,
    base_pad: int = 0,
):
    """Recadre/peint `pixmap` en "cover" dans `slot_rect`, avec le padding/
    bordure/rayon regles dans Colonnes > ... > Image (voir DEFAULT_SETTINGS.
    item_image_*/settings_window._section_headers) — partage par toutes les
    colonnes (apercu personnalise sur "Type", vignette Projets/Sous-projet/
    Logiciels/Contenu, voir _paint_unified_row) —
    voir la remarque de l'utilisateur, "les parametres images ... sont pour
    controler les apercus que l'on trouve sur les differentes lignes".

    `item_image_radius` est un reglage INDEPENDANT (defaut 0 = carre),
    JAMAIS remplace par un rayon "herite" d'ailleurs (colonne/selection) —
    un essai precedent faisait heriter le rayon de la boite de selection
    tant qu'item_image_radius valait 0, mais rendait alors un 0 EXPLICITE
    indiscernable d'un rayon "pas encore regle" : le coin restait
    visiblement arrondi meme regle a 0 — voir la remarque de l'utilisateur,
    capture a l'appui, "si je met une valeur de 0 a l'arrondi, les coins
    ne sont pas vraiment carre". `base_pad` (additif, jamais ambigu) reste
    le seul reglage "herite" — l'ancien padding fixe par colonne
    (col_img_pad, Projets/Sous-projet/Logiciels/Contenu)."""
    pad = style.get("item_image_padding") or {}
    left = base_pad + max(0, int(pad.get("left", 0)))
    top_p = base_pad + max(0, int(pad.get("top", 0)))
    right = base_pad + max(0, int(pad.get("right", 0)))
    bottom = base_pad + max(0, int(pad.get("bottom", 0)))
    img_rect = QRect(
        slot_rect.left() + left, slot_rect.top() + top_p,
        slot_rect.width() - left - right, slot_rect.height() - top_p - bottom,
    )
    if img_rect.width() <= 0 or img_rect.height() <= 0:
        return

    radius = _radius_dict(style.get("item_image_radius") or 0)

    # Taille PHYSIQUE reelle (devicePixelRatio), pas seulement LOGIQUE —
    # voir la remarque de l'utilisateur, "je trouve les icones encore tres
    # floues" : sur un ecran mis a l'echelle (>100%, tres courant), un
    # pixmap cree a EXACTEMENT la taille logique du slot (devicePixelRatio
    # implicite 1.0) est ensuite lui-meme RE-agrandi par Qt au moment de
    # le peindre dans ce MEME rect logique sur un peripherique physique
    # plus dense — un flou invisible cote algorithme de mise a l'echelle
    # (deja bon, voir _smooth_scale_down), uniquement du a ce DERNIER saut
    # (le pixmap final n'annonce jamais sa vraie densite a Qt)."""
    device = painter.device()
    dpr = (device.devicePixelRatioF() if device is not None else 1.0) or 1.0
    phys_w = max(1, round(img_rect.width() * dpr))
    phys_h = max(1, round(img_rect.height() * dpr))

    # Vignette FINALE (recadree, arrondie, a la taille physique) gardee en cache : la recalculer a
    # chaque repeinture (reductions successives + masque sur-echantillonne 8x) coutait l'essentiel
    # d'une repeinture des colonnes (~40 ms sur 100) et faisait ramer toute la navigation, chaque
    # clic declenchant des captures (fondus). Cle = contenu du pixmap (cacheKey) + taille + rayon.
    cache_key = (pixmap.cacheKey(), phys_w, phys_h, tuple(sorted(radius.items())), dpr)
    final = _ROW_IMAGE_CACHE.get(cache_key)
    if final is None:
        final = _row_image_pixmap(pixmap, phys_w, phys_h, radius, dpr)
        if len(_ROW_IMAGE_CACHE) >= _ROW_IMAGE_CACHE_MAX:
            _ROW_IMAGE_CACHE.clear()
        _ROW_IMAGE_CACHE[cache_key] = final
    # Ombres (Colonnes > Lignes > Apercu, ou l'onglet de la colonne) : sous la vignette, dans le padding.
    shadow = shadow_look(style, "item_image_shadow", resolve_color_ref)
    if shadow is not None:
        paint_shadow(painter, img_rect, radius, shadow)
    if _radius_any(radius):
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawPixmap(img_rect, final)

    border_enabled = dict(style.get("item_image_border_enabled") or {})
    if any(border_enabled.values()):
        thickness = max(1, int(style.get("item_image_border_thickness", 1)))
        border_colors = {k: resolve_color_ref(v) for k, v in (style.get("item_image_border") or {}).items()}
        painter.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
        _paint_bordered_rect(painter, img_rect, radius, border_enabled, thickness, border_colors, None)
        painter.setRenderHint(QPainter.Antialiasing, False)

def _resolve_font_family(label: str, size: int, weight: int = 400, fallback_role: str = "folders") -> str:
    """Resout un libelle de police stocke (voir item_font_family/
    _ITEM_FONT_LABEL_TO_ROLE) vers un nom de police REEL : "police du
    soft" (role, voir Polices principales) ou nom de police systeme
    litteral — meme logique que _resolve_row_font_color ci-dessous,
    partagee ici pour Colonnes > Apercu > Zone titre (Titre/Apercu des
    dossiers) — voir la remarque de l'utilisateur, "je veux le choix de
    la police (titre + apercu des dossiers) (choix entre polices appli ou
    polices systeme)"."""
    role = _dimensions._ITEM_FONT_LABEL_TO_ROLE.get(label)
    if role is not None:
        return role_font(role, size, weight).family()
    return label or role_font(fallback_role, size, weight).family()

def _resolve_row_font_color(title: str):
    """Police/couleur EFFECTIVES du texte d'une ligne, pour LE style de
    `title` (general ou surcharge, voir app_style.column_style_for) —
    UNIQUE source pour toutes les colonnes (Type/Projets/Sous-projet/
    Logiciels/Contenu, voir RowDelegate/ProjectTileDelegate.refresh_fonts)
    depuis que leur rendu est partage (voir _paint_unified_row) — voir la
    remarque de l'utilisateur, "je veux que tu reformate toutes les autres
    colonnes exactement de la meme maniere que la colonne type"."""
    s = column_style_for(title)
    family = (s.get("item_font_family") or "").strip()
    size = max(1, int(s.get("item_font_size") or 10))
    resolved_family = _resolve_font_family(family, size, 400)
    smoothing = s.get("item_antialias_override") if s.get("item_antialias_override_enabled") else "current"
    # Gras (voir Colonnes > Texte > Police, toggle "Gras" — DEFAULT_
    # SETTINGS.item_font_bold) : voir la remarque de l'utilisateur, "pour
    # les polices ... j'aimerais rajouter une option pour mettre le texte
    # en gras (toggle)".
    weight = 600 if s.get("item_font_bold") else 400
    italic = bool(s.get("item_font_italic", False))
    row_font = font(size, weight=weight, family=resolved_family, smoothing=smoothing, italic=italic)
    row_color = resolve_color_ref(s.get("item_color") or C["text"])
    return row_font, row_color

def _resolve_shortcut_font_color():
    """Police/couleur EFFECTIVES d'une ligne "raccourci" (voir
    ROLE_IS_SHORTCUT/SHORTCUT_TEXT_STYLE, Settings > RACCOURCI) — GENERALE
    (pas par colonne, contrairement a _resolve_row_font_color : un
    raccourci doit se reperer de la MEME facon partout)."""
    family = (ui_state.SHORTCUT_TEXT_STYLE.get("font_family") or "").strip()
    size = max(1, int(ui_state.SHORTCUT_TEXT_STYLE.get("font_size") or 11))
    resolved_family = _resolve_font_family(family, size, 400)
    weight = 600 if ui_state.SHORTCUT_TEXT_STYLE.get("font_bold") else 400
    italic = bool(ui_state.SHORTCUT_TEXT_STYLE.get("font_italic", False))
    smoothing = (
        ui_state.SHORTCUT_TEXT_STYLE.get("font_smoothing", "current")
        if ui_state.SHORTCUT_TEXT_STYLE.get("font_smoothing_enabled") else "current")
    row_font = font(size, weight=weight, family=resolved_family, smoothing=smoothing, italic=italic)
    row_color = resolve_color_ref(ui_state.SHORTCUT_TEXT_STYLE.get("color") or C["text"])
    return row_font, row_color

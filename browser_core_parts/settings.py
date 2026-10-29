"""Application des réglages et indicateurs de redimensionnement. Carte : docs/agents/colonnes.md."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLabel, QWidget
from app_style import COLUMN_TYPE_OVERRIDE_KEYS, INSPECTOR_TITLE, PREVIEW_STACK_TITLE, set_custom_softwares, set_removed_softwares, font, set_auto_collapse_set_columns, set_button_frame, set_button_radius, set_control_look, set_color, set_column_gap, set_columns_resizable, set_header_style, set_input_frame, set_input_radius, set_role_font, set_table_radius, set_ui_scale, resolve_color_ref, set_general_column_style, set_column_style
import ui_state
from config import GLOBAL_OMIT_DIR_NAMES, GLOBAL_OMIT_FILE_EXTENSIONS, GLOBAL_OMIT_FILE_NAMES
from settings_store import _coerce_side_enabled, _load_presets, _save_presets, _sync_slider_style, load_settings, save_settings
from settings_widgets import _radius_dict, ShadowUnderlay, shadow_look
from . import dimensions as _dimensions
from . import row_paint as _row_paint
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from column import Column

def _resize_width_indicator(win: QWidget, key: str = "default") -> QLabel:
    """Badge flottant affichant la largeur/hauteur (px) pendant le
    redimensionnement d'une colonne ou du panneau de details (voir
    Column.resize_*/height_resize_*/DetailPanel mousePressEvent/
    mouseMoveEvent/mouseReleaseEvent). UN badge PAR `key`, stocke sur `win`
    (dict `_resize_width_labels`) — la plupart des redimensionnements
    n'utilisent QUE la cle par defaut (un seul actif a la fois, jamais
    besoin de plus d'un badge) ; la SEULE exception est le glisser d'un
    bord de colonne du groupe IN/OVER/OUT/LOGICIELS, qui bouge 2 colonnes a
    la fois (voir PipelineBrowser._on_group_height_resize_begin/
    _on_group_height_resized, cle "group_below" EN PLUS de la cle par
    defaut pour la colonne du dessus) — voir la remarque de l'utilisateur,
    "je veux le cadre de mesure de la hauteur pour les deux colonnes
    concernees par le redimensionnement"."""
    labels = getattr(win, "_resize_width_labels", None)
    if labels is None:
        labels = {}
        win._resize_width_labels = labels
    label = labels.get(key)
    if label is None:
        label = QLabel(win)
        label.setObjectName("ResizeWidthIndicator")
        # Sinon ce badge, place tout pres du bord glisse, peut lui-meme
        # recevoir les evenements souris et bloquer le redimensionnement en
        # cours.
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        labels[key] = label
    return label

def _refresh_resize_width_style(label: QLabel) -> None:
    """Reapplique police/couleur de fond/bordure/rayon du cadre de
    redimensionnement DEPUIS RESIZE_BADGE_STYLE (voir apply_all_settings,
    General > Colonnes > "Cadre de redimensionnement") — rejoue a CHAQUE
    affichage (pas seulement a la creation du badge, voir
    _resize_width_indicator) : ce badge est cree UNE FOIS puis reutilise
    pour toute la duree de vie de la fenetre, sans ca un reglage change en
    cours de session (previsualisation en direct) resterait fige sur le
    style d'a la creation."""
    s = ui_state.RESIZE_BADGE_STYLE
    # Police (voir _resolve_font_family, MEME resolution "police du soft"
    # (role)/"police systeme" que les autres sections — voir la remarque de
    # l'utilisateur, "pour la police, je veux comme les autres section le
    # choix entre les police appli et systeme") : "" (auto, jamais touche)
    # garde le comportement D'AVANT ce reglage — la police MONO de l'appli
    # (mono_family()), PAS une resolution par role (_resolve_font_family
    # n'a aucun repli "mono", seulement des roles a chasse variable).
    family_label = s.get("font_family") or ""
    size = int(s.get("font_size", 11))
    weight = 600 if s.get("font_bold", True) else 400
    italic = bool(s.get("font_italic", False))
    smoothing = s.get("font_smoothing", "current") if s.get("font_smoothing_enabled") else "current"
    if family_label:
        resolved_family = _row_paint._resolve_font_family(family_label, size, weight)
        label.setFont(font(size, weight, family=resolved_family, smoothing=smoothing, italic=italic))
    else:
        label.setFont(font(size, weight, mono=True, smoothing=smoothing, italic=italic))
    text_color = resolve_color_ref(s.get("text_color", "#d6d9dc"))
    bg = resolve_color_ref(s.get("bg_color", "#202326"))
    thickness = max(0, int(s.get("border_thickness", 1)))
    enabled = s.get("border_enabled") or {}
    colors = s.get("border") or {}
    radius = s.get("border_radius") or {}
    sides = []
    for side in ("top", "right", "bottom", "left"):
        side_thickness = thickness if enabled.get(side, True) else 0
        side_color = resolve_color_ref(colors.get(side, "@border2"))
        sides.append(f"border-{side}: {side_thickness}px solid {side_color};")
    corners = []
    for css_corner, key_corner in (
        ("top-left", "top_left"), ("top-right", "top_right"),
        ("bottom-right", "bottom_right"), ("bottom-left", "bottom_left"),
    ):
        corners.append(f"border-{css_corner}-radius: {max(0, int(radius.get(key_corner, 4)))}px;")
    label.setStyleSheet(
        f"#ResizeWidthIndicator {{ background: {bg}; color: {text_color}; padding: 6px;"
        f" {' '.join(sides)} {' '.join(corners)} }}"
    )

def _show_resize_width(widget: QWidget, width: int, key: str = "default") -> None:
    """Affiche/deplace le badge de largeur pres du coin ANCRE (voir
    RESIZE_BADGE_STYLE["position"], General > Colonnes > "Cadre de
    redimensionnement" des reglages — bas-droit par defaut, comportement
    INCHANGE) de `widget` (le bord qu'on est en train de glisser, ou sa
    voisine — voir `key`) — voir _resize_width_indicator. Ancre au coin
    choisi du fond de `widget`, cadre INSERE de offset_x/offset_y px (voir
    RESIZE_BADGE_STYLE, sliders "H"/"V" sur la ligne "Position" des
    reglages — 8/8 par defaut, comportement INCHANGE) — voir la remarque de
    l'utilisateur, "distance entre le bas du fond de la colonne et le bas
    du cadre de dimension [ET] le cote droit du fond de la colonne et le
    cote droit du cadre de dimension doivent etre de 8px" puis "sous
    position je veux egalement deux sliders (sur la mm ligne) pour la
    position H et la position V"."""
    win = widget.window()
    label = _resize_width_indicator(win, key)
    label.setText(str(width))
    _refresh_resize_width_style(label)
    label.adjustSize()
    position = ui_state.RESIZE_BADGE_STYLE.get("position", "bottom_right")
    offset_x = int(ui_state.RESIZE_BADGE_STYLE.get("offset_x", 8))
    offset_y = int(ui_state.RESIZE_BADGE_STYLE.get("offset_y", 8))
    anchor_x = 0 if position.endswith("left") else widget.width()
    anchor_y = 0 if position.startswith("top") else widget.height()
    anchor = widget.mapToGlobal(QPoint(anchor_x, anchor_y))
    local = win.mapFromGlobal(anchor)
    label_x = local.x() + offset_x if position.endswith("left") \
        else local.x() - label.width() - offset_x
    label_y = local.y() + offset_y if position.startswith("top") \
        else local.y() - label.height() - offset_y
    label.move(label_x, label_y)
    label.show()
    label.raise_()

def _hide_resize_width(widget: QWidget, key: str = "default") -> None:
    labels = getattr(widget.window(), "_resize_width_labels", None)
    if labels is not None and key in labels:
        labels[key].hide()

def _show_row_resize_indicator(column: "Column", row_index: int, height: int) -> None:
    """MEME badge que _show_resize_width (voir _resize_width_indicator/
    RESIZE_BADGE_STYLE pour l'habillage : police/couleur/fond/bordure
    restent les memes reglages), mais ancre juste SOUS `row_index` (voir
    Column.row_resize_begin) plutot que sous le coin de la colonne entiere
    — voir la remarque de l'utilisateur, "je veux que la position de
    l'indicateur de hauteur soit juste au dessous de la ligne que l'on
    redimensionne". `key="row_height"` DEDIE (jamais "default", partage
    par le redimensionnement de LARGEUR/hauteur de groupe) : ce glisser
    peut survenir alors qu'un AUTRE indicateur est deja affiche ailleurs
    sur la meme fenetre (peu probable mais gratuit a eviter)."""
    win = column.window()
    label = _resize_width_indicator(win, "row_height")
    label.setText(str(height))
    _refresh_resize_width_style(label)
    label.adjustSize()
    row_rect = None
    if row_index >= 0:
        index = column.list.model().index(row_index, 0)
        if index.isValid():
            row_rect = column.list.visualRect(index)
    viewport = column.list.viewport()
    if row_rect is not None:
        anchor_local = QPoint(row_rect.center().x(), row_rect.bottom())
    else:
        anchor_local = QPoint(viewport.width() // 2, 0)
    anchor_global = viewport.mapToGlobal(anchor_local)
    local = win.mapFromGlobal(anchor_global)
    label.move(local.x() - label.width() // 2, local.y() + 4)
    label.show()
    label.raise_()

def _live_dialog_values(win) -> dict | None:
    """Valeurs EN COURS (apercu non enregistre) de la fenetre de reglages ouverte (`_settings_dialog_v2`),
    ou None si elle n'est pas visible."""
    dialog = getattr(win, "_settings_dialog_v2", None)
    try:
        return dialog.current_values() if dialog is not None and dialog.isVisible() else None
    except RuntimeError:
        return None

def _persist_row_height(win, title: str, new_height: int) -> None:
    """Enregistre `new_height` comme hauteur de ligne EFFECTIVE de `title`
    sur le disque (voir Column.row_resize_end) — memes cles que la fenetre
    de parametres (settings_window._build_column_override_page) : "Type"
    garde ses cles historiques, "Projets"/"Sous-projet" les nouvelles cles
    imbriquees par titre (voir _override_store cote settings_window) — pour
    qu'un redimensionnement a la souris se retrouve, actif, la prochaine
    fois que Colonnes > (Type/Projets/Sous-projets) est ouvert. Ctrl+glisser
    est desormais possible sur TOUTE colonne (voir _in_row_resize_zone, la
    remarque de l'utilisateur, "doit etre sur toutes les colonnes") — mais
    "Logiciels"/"Contenu" (et toute colonne de chaine CONFIGUREE qui retombe
    dans ce meme bucket, voir _col_key, ex. "test1") n'ont PAS d'onglet de
    surcharge PAR TITRE dedie (voir apply_all_settings, "suivent directement
    la valeur GENERALE") : le SEUL reglage qui pilote reellement leur
    hauteur est le defaut GENERAL "item_row_height", c'est donc lui qu'il
    faut ecrire pour que ce glisser survive a un redemarrage — memes effet
    que le slider General > Colonnes > "Hauteur de la ligne"""
    def _apply_height_override(target: dict) -> None:
        if title == "Type":
            target.setdefault("column_type_overrides", {})["item_row_height"] = new_height
            target.setdefault("column_type_override_enabled", {})["item_row_height"] = True
        elif title in ("Projets", "Sous-projet", PREVIEW_STACK_TITLE):
            target.setdefault("column_overrides_by_title", {}).setdefault(title, {})["item_row_height"] = new_height
            target.setdefault("column_override_enabled_by_title", {}).setdefault(title, {})["item_row_height"] = True
        else:
            target["item_row_height"] = new_height

    settings = load_settings()
    _apply_height_override(settings)
    save_settings(settings)

    # Applique en LIVE depuis la vue COURANTE de la fenetre de parametres
    # si elle est ouverte (dialog._current_values()) plutot que `settings`
    # ci-dessus, qui vient d'etre RELU du disque et ne contient PAS
    # d'eventuels reglages en cours de previsualisation mais pas encore
    # enregistres (ex. "Espacement entre les lignes" juste ajuste au
    # slider, general) — les reappliquer ici aurait silencieusement ecrase
    # cette previsualisation, et ce pour LES 5 COLONNES A LA FOIS puisque
    # apply_all_settings en recalcule le spacing a partir du MEME dict —
    # voir la remarque de l'utilisateur, "apres un redimensionnement les
    # espacements entre les lignes ne sont plus respecte, et ca concerne
    # toutes les colonnes". La hauteur est re-appliquee explicitement sur
    # CETTE vue aussi (_apply_height_override).
    live_settings = _live_dialog_values(win)
    if live_settings is not None:
        _apply_height_override(live_settings)
    apply_all_settings(live_settings if live_settings is not None else settings)

def _sync_default_preset_override(settings: dict, apply_override) -> None:
    """Reapplique `apply_override` (MEME callable que celui deja utilise sur
    `settings`) au preset "par defaut" ACTIF (settings["default_preset"],
    voir General > Application) — sans ca, une largeur "auto-enregistree"
    (voir _persist_column_width/_persist_detail_panel_width) etait
    silencieusement ECRASEE par la valeur PERIMEE de ce preset des le
    PROCHAIN chargement (voir settings_window.load_settings, qui fusionne
    TOUJOURS le preset par defaut PAR-DESSUS pipeline_settings.json), tant
    qu'un preset par defaut restait configure — voir la remarque de
    l'utilisateur, "la largeur de la colonne inspecteur ne s'enregistre
    toujours pas automatiquement". No-op si aucun preset par defaut n'est
    configure, ou s'il a depuis ete supprime/renomme (repli SILENCIEUX,
    meme convention que load_settings)."""
    from settings_store import preset_in_use
    default_preset = preset_in_use(settings)      # le preset ACTIF (a l'ecran), defaut au lancement
    if not default_preset:
        return
    presets = _load_presets()
    preset = presets.get(default_preset)
    if preset is None:
        return
    apply_override(preset)
    _save_presets(presets)

def _persist_column_width(win, title: str, new_width: int) -> None:
    """Analogue de _persist_row_height, mais pour la LARGEUR — reservee aux
    colonnes qui n'ont pas (ou plus) besoin de punaise pour s'enregistrer :
    Type (jamais de bouton punaise, voir Column.__init__) et Focus/
    PREVIEW_STACK_TITLE (colonnes empilees Projets/Sous-projet de
    l'apercu, voir PreviewColumn — aucune notion de dossier UNIQUE a
    associer, donc pas de mecanisme .pipeline_layout.json possible pour
    elles) — voir la remarque de l'utilisateur, "les seules colonnes dont
    les parametres sont enregistrees automatiquement sont : colonne type,
    colonnes focus, colonne inspecteur"."""
    def _apply_width_override(target: dict) -> None:
        if title == "Type":
            target.setdefault("column_type_overrides", {})["item_column_width"] = new_width
            target.setdefault("column_type_override_enabled", {})["item_column_width"] = True
        elif title in ("Projets", "Sous-projet", PREVIEW_STACK_TITLE):
            target.setdefault("column_overrides_by_title", {}).setdefault(title, {})["item_column_width"] = new_width
            target.setdefault("column_override_enabled_by_title", {}).setdefault(title, {})["item_column_width"] = True
        else:
            target["item_column_width"] = new_width

    settings = load_settings()
    _apply_width_override(settings)
    save_settings(settings)
    _sync_default_preset_override(settings, _apply_width_override)

    live_settings = _live_dialog_values(win)
    if live_settings is not None:
        _apply_width_override(live_settings)
    apply_all_settings(live_settings if live_settings is not None else settings)

def _persist_detail_panel_width(win, new_width: int) -> None:
    """Analogue de _persist_column_width, mais pour l'Inspecteur (voir
    DetailPanel.mouseReleaseEvent) — une seule cle GENERALE PLATE
    ("detail_panel_width", pas de branchement par titre : cette colonne
    n'a ni punaise ni onglet de surcharge dedie, une seule instance existe
    dans toute l'appli) — voir la remarque de l'utilisateur, "la largeur
    de la colonne inspecteur ... doivent etre enregistrees
    automatiquement"."""
    settings = load_settings()
    settings["detail_panel_width"] = new_width
    save_settings(settings)
    _sync_default_preset_override(settings, lambda target: target.__setitem__("detail_panel_width", new_width))

    live_settings = _live_dialog_values(win)
    if live_settings is not None:
        live_settings["detail_panel_width"] = new_width
    apply_all_settings(live_settings if live_settings is not None else settings)

        # PAS de update_preview_stack() ici : le seul appelant
        # (_apply_settings) vient deja d'en faire un via refresh_all_columns
        # / reload juste avant — le rejouer ici doublerait pour rien le
        # travail (stat + chargement des vignettes) a chaque rafraichissement.


def _register_settings_hooks() -> None:
    """Fonctions d'apercu des LUT proposees aux reglages (voir settings_lut)."""
    import previews as _pv
    from settings_store import HOOKS
    HOOKS["lut_image_kind"] = _pv.lut_image_kind
    HOOKS["lut_curve_choices"] = _pv.lut_curve_choices
    HOOKS["lut_test_image"] = _pv.lut_test_image_for

def apply_all_settings(settings: dict) -> None:
    """Point d'entree unique qui recopie un dict de reglages (voir
    settings_window.DEFAULT_SETTINGS) dans les globals/tokens qu'ils
    pilotent : geometrie par colonne, apercu empile, fenetre, boutons,
    entete de colonne, echelle generale, couleurs et roles typographiques.
    N'a aucun effet visible tant qu'aucun refresh (refresh_all_columns,
    refresh_colors, refresh_chrome_fonts...) n'est rejoue par-dessus —
    voir PipelineBrowser._apply_settings et main() pour ces deux appelants."""

    import previews as _pv
    ui_state.APPLIED_SETTINGS = settings
    _register_settings_hooks()
    _pv.set_lut_test_images(
        settings.get("lut_test_images"), settings.get("lut_default_image"), settings.get("lut_image_curves"))

    omit_names = settings.get("application_omit_file_names") or []
    omit_dirs = settings.get("application_omit_dir_names") or []
    omit_extensions = settings.get("application_omit_extensions") or []
    if isinstance(omit_names, str):
        omit_names = omit_names.replace(";", ",").split(",")
    if isinstance(omit_dirs, str):
        omit_dirs = omit_dirs.replace(";", ",").split(",")
    if isinstance(omit_extensions, str):
        omit_extensions = omit_extensions.replace(";", ",").split(",")
    legacy_extensions = [part for value in omit_extensions
                         for part in str(value).replace(",", " ").replace(";", " ").split()]
    GLOBAL_OMIT_DIR_NAMES.clear()
    GLOBAL_OMIT_DIR_NAMES.update({
        str(value).strip().casefold() for value in omit_dirs if str(value).strip()
    })
    GLOBAL_OMIT_FILE_NAMES.clear()
    GLOBAL_OMIT_FILE_NAMES.update({
        str(value).strip().casefold()
        for value in omit_names
        if str(value).strip() and not str(value).strip().startswith("*.")
    })
    GLOBAL_OMIT_FILE_EXTENSIONS.clear()
    GLOBAL_OMIT_FILE_EXTENSIONS.update({
        str(value).strip().casefold().removeprefix("*.").lstrip(".")
        for value in [*legacy_extensions, *(name for name in omit_names if str(name).strip().startswith("*."))]
        if str(value).strip().lstrip("*.")
    })

    # Entete de colonne : padding droit des icones + police/gras/couleur/
    # hauteur du titre (voir Column.refresh_header, app_style.COLUMN_FRAME_
    # KEYS/column_style_for — desormais des cles GENERALES comme le reste
    # de cette liste, overridables PAR TITRE, PAS un dict a part) — voir la
    # remarque de l'utilisateur, "ajoute un slider pour le padding droit
    # des icones ... choix de la police + gras/regular + couleur" puis
    # "mets a jour egalement les colonnes overidees ... avec tous les
    # nouveaux parametres de general".

    # Icone de niveaux (badge numerote, colonne "Projets" — voir
    # _step_badge_rect/_paint_unified_row, Settings > Colonnes > Projets >
    # Colonnes > "Icone de niveaux") — voir la remarque de l'utilisateur,
    # "j'aimerais pouvoir controler l'aspect de cette petite icone".
    ui_state.STEP_BADGE_STYLE = {
        "width": int(settings.get("step_badge_width", 18)),
        "height": int(settings.get("step_badge_height", 18)),
        "border_enabled": _coerce_side_enabled(settings.get("step_badge_border_enabled", False)),
        "border": settings.get("step_badge_border") or {},
        "border_thickness": int(settings.get("step_badge_border_thickness", 1)),
        "radius": _radius_dict(settings.get("step_badge_radius", 9)),
        "colors": {
            2: settings.get("step_badge_color_base2", "#5c6368"),
            3: settings.get("step_badge_color_base3", "#5c6368"),
            4: settings.get("step_badge_color_base4", "#3f6f9f"),
            5: settings.get("step_badge_color_base5", "#3f6f9f"),
            6: settings.get("step_badge_color_base6", "#d9822b"),
            "N": settings.get("step_badge_color_basen", "#5c6368"),
        },
        "text_colors": {
            2: settings.get("step_badge_text_color_base2", "#eef2f5"),
            3: settings.get("step_badge_text_color_base3", "#eef2f5"),
            4: settings.get("step_badge_text_color_base4", "#eef2f5"),
            5: settings.get("step_badge_text_color_base5", "#eef2f5"),
            6: settings.get("step_badge_text_color_base6", "#eef2f5"),
            "N": settings.get("step_badge_text_color_basen", "#eef2f5"),
        },
        "offset_x": int(settings.get("step_badge_offset_x", 4)),
        "offset_y": int(settings.get("step_badge_offset_y", 0)),
        "font_family": settings.get("step_badge_font_family", ""),
        "font_bold": bool(settings.get("step_badge_font_bold", True)),
        "font_smoothing_enabled": bool(settings.get("step_badge_font_smoothing_enabled", False)),
        "font_smoothing": settings.get("step_badge_font_smoothing", "current"),
        "border_smoothing": bool(settings.get("step_badge_border_smoothing", True)),
    }

    ui_state.COLLAPSE_TOGGLE_MODE = settings.get("collapse_toggle_mode", "chevrons")

    # Raccourcis (voir ROLE_IS_SHORTCUT, Settings > RACCOURCI) — General >
    # RACCOURCI > "Police".
    ui_state.SHORTCUT_TEXT_STYLE = {
        "font_family": settings.get("shortcut_font_family", ""),
        "font_bold": bool(settings.get("shortcut_font_bold", False)),
        "font_italic": bool(settings.get("shortcut_font_italic", False)),
        "color": settings.get("shortcut_color", "#8fb4d5"),
        "font_size": int(settings.get("shortcut_font_size", 11)),
        "font_smoothing_enabled": bool(settings.get("shortcut_font_smoothing_enabled", False)),
        "font_smoothing": settings.get("shortcut_font_smoothing", "current"),
    }
    ui_state.DETAIL_PANEL_WIDTH = int(settings.get("detail_panel_width", 300))

    # Habillage des sliders peints a la main (voir settings_window.
    # _MiniSlider/_SLIDER_STYLE/_sync_slider_style, General > Geometrie >
    # Slider "Rail"/"Selecteur") : auparavant synchronise UNIQUEMENT depuis
    # SettingsWindow.__init__/_apply_slider_style, jamais depuis ce point
    # d'entree central — un _MiniSlider construit AILLEURS (voir Column.
    # _add_context_slider, menu contextuel) AVANT la toute premiere
    # ouverture de la fenetre de parametres dans la session gardait donc
    # les couleurs par defaut codees en dur, jamais celles enregistrees —
    # voir la remarque de l'utilisateur, "les sliders des menus contextuels
    # n'ont pas le style defini dans les settings".
    _sync_slider_style(settings)

    ui_state.RESIZE_BADGE_STYLE = {
        "position": settings.get("resize_badge_position", "bottom_right"),
        "offset_x": int(settings.get("resize_badge_offset_x", 8)),
        "offset_y": int(settings.get("resize_badge_offset_y", 8)),
        "font_family": settings.get("resize_badge_font_family", ""),
        "font_bold": bool(settings.get("resize_badge_font_bold", True)),
        "font_italic": bool(settings.get("resize_badge_font_italic", False)),
        "font_size": int(settings.get("resize_badge_font_size", 11)),
        "font_smoothing_enabled": bool(settings.get("resize_badge_font_smoothing_enabled", False)),
        "font_smoothing": settings.get("resize_badge_font_smoothing", "current"),
        "text_color": settings.get("resize_badge_text_color", "#d6d9dc"),
        "bg_color": settings.get("resize_badge_bg_color", "#202326"),
        "border_enabled": _coerce_side_enabled(settings.get("resize_badge_border_enabled", True)),
        "border": settings.get("resize_badge_border") or {},
        "border_thickness": int(settings.get("resize_badge_border_thickness", 1)),
        "border_radius": _radius_dict(settings.get("resize_badge_border_radius", 4)),
    }

    for title, conf in settings.get("columns", {}).items():
        if title not in _dimensions.COLUMN_SETTINGS:
            continue
        _dimensions.COLUMN_SETTINGS[title].update({
            "width": conf.get("width", _dimensions.COLUMN_SETTINGS[title]["width"]),
            "height": conf.get("height", _dimensions.COLUMN_SETTINGS[title]["height"]),
            "spacing": conf.get("spacing", _dimensions.COLUMN_SETTINGS[title]["spacing"]),
        })
        if "img_pad" in conf:
            _dimensions.COLUMN_SETTINGS[title]["img_pad"] = conf["img_pad"]
        if "img_radius" in conf:
            _dimensions.COLUMN_SETTINGS[title]["img_radius"] = conf["img_radius"]
        if "plain_height" in conf:
            _dimensions.COLUMN_SETTINGS[title]["plain_height"] = conf["plain_height"]
    # "Sous-projet" peut suivre les valeurs de "Projets" (voir les toggles
    # de liaison dans la fenetre de parametres) : resolu ici, une fois pour
    # toutes, plutot qu'a chaque ligne dessinee.
    sous = settings.get("columns", {}).get("Sous-projet", {})
    if sous.get("img_pad_link", True):
        _dimensions.COLUMN_SETTINGS["Sous-projet"]["img_pad"] = _dimensions.COLUMN_SETTINGS["Projets"]["img_pad"]
    if sous.get("img_radius_link", True):
        _dimensions.COLUMN_SETTINGS["Sous-projet"]["img_radius"] = _dimensions.COLUMN_SETTINGS["Projets"]["img_radius"]

    # dicts (4 cotes / 4 coins INDEPENDANTS, voir _SquarePreviewImage._
    # refresh) — voir la remarque de l'utilisateur, "controle des paddings
    # sur les 4 cotes comme partout ailleurs ... pareil pour les coins
    # arrondis".
    ui_state.PREVIEW_IMAGE_PAD = settings.get("preview_padding") or {}
    ui_state.PREVIEW_IMAGE_RADIUS = settings.get("preview_radius") or {}
    ui_state.PREVIEW_IMAGE_SHADOW = shadow_look(settings, "preview_shadow", resolve_color_ref)
    ui_state.ITEM_EXT_COLOR = (resolve_color_ref(settings.get("item_ext_color") or "#8a9097")
                               if settings.get("item_ext_color_enabled") else None)
    ShadowUnderlay.refresh_all()             # ombres posees sous des widgets (image Focus, tableaux)

    ui_state.HEADER_HEIGHT = settings.get("header_height", ui_state.HEADER_HEIGHT)
    ui_state.HEADER_PADDING = settings.get("header_padding", ui_state.HEADER_PADDING)
    ui_state.WINDOW_RADIUS = settings.get("window_radius", ui_state.WINDOW_RADIUS)
    ui_state.BUTTON_RADIUS = settings.get("button_radius", ui_state.BUTTON_RADIUS)
    set_button_radius(ui_state.BUTTON_RADIUS)
    set_button_frame(settings.get("button_frame", True))
    set_input_frame(settings.get("input_frame", True))
    set_input_radius(settings.get("input_radius", 0))
    set_control_look(settings)
    from settings_theme import apply_input_look
    apply_input_look(settings)                   # zones de saisie des fenetres de reglages
    set_table_radius(settings.get("table_radius", 0))
    set_columns_resizable(settings.get("columns_resizable", True))
    set_auto_collapse_set_columns(settings.get("auto_collapse_set_columns", True))
    set_custom_softwares(settings.get("custom_softwares", []))
    set_removed_softwares(settings.get("removed_softwares", []))
    set_column_gap(settings.get("column_gap", 0))
    set_header_style(
        settings.get("header_color", "skinN1"),
        settings.get("header_radius", 0),
        # header_border_enabled (nouveau nom) ; header_edges (ancien nom,
        # meme format dict {cote: bool}) en repli pour les presets deja
        # sauvegardes avant ce renommage — voir la remarque de
        # l'utilisateur, "renomme le parametre 'cadre des entetes' ->
        # 'Bordure'".
        settings.get("header_border_enabled") or settings.get("header_edges")
        or {"top": False, "right": False, "bottom": True, "left": False},
        settings.get("header_border") or {},
        settings.get("header_border_thickness", 1),
    )
    set_ui_scale(settings.get("ui_scale", 100))

    for key, hexval in (settings.get("colors") or {}).items():
        set_color(key, hexval)

    # Style de colonne GENERAL (voir app_style.set_general_column_style) :
    # applique tel quel a TOUTE colonne sans surcharge active (Logiciels/
    # Contenu, ou Type/Projets/Sous-projet tant qu'aucune ligne de leur
    # onglet dedie n'est activee, voir plus bas) — TOUTES les cles de
    # COLUMN_TYPE_OVERRIDE_KEYS (cadre + texte/selection/image), pas
    # seulement le cadre : depuis que le rendu des lignes est PARTAGE par
    # toutes les colonnes (voir _paint_unified_row), Logiciels/Contenu ont
    # eux aussi besoin de item_selection_*/item_image_* pour suivre les
    # reglages generaux — voir la remarque de l'utilisateur, "le padding et
    # les coins arrondis des autres colonnes que type ne fonctionnent
    # pas". APRES la boucle set_color() ci-dessus, dont depend
    # resolve_color_ref (les couleurs "@<slot>" se resolvent contre la
    # palette live, pas l'ancienne).
    set_general_column_style({key: settings.get(key) for key in COLUMN_TYPE_OVERRIDE_KEYS})

    # Style EFFECTIF de chaque colonne : le style GENERAL, sauf la largeur et la hauteur de ligne de
    # Type / Projets / Sous-projet / Focus, enregistrees par le glisser des bordures
    # (_persist_column_width / _persist_row_height) dans `column_type_overrides` (Type) et
    # `column_overrides_by_title` (les autres), avec leur interrupteur `*_enabled`. Plus aucun onglet de
    # surcharge dans les reglages : seules ces deux cles sont lues.
    overrides_by_title = settings.get("column_overrides_by_title") or {}
    enabled_by_title = settings.get("column_override_enabled_by_title") or {}
    for real_title in ("Type", "Projets", "Sous-projet", "Logiciels", "IN", "OVER", "OUT", INSPECTOR_TITLE,
                       PREVIEW_STACK_TITLE):
        if real_title == "Type":
            overrides = settings.get("column_type_overrides") or {}
            override_enabled = settings.get("column_type_override_enabled") or {}
        else:
            overrides = overrides_by_title.get(real_title) or {}
            override_enabled = enabled_by_title.get(real_title) or {}
        col_style = {key: settings.get(key) for key in COLUMN_TYPE_OVERRIDE_KEYS}
        for key in ("item_column_width", "item_row_height"):
            if override_enabled.get(key) and key in overrides:
                col_style[key] = overrides[key]
        if real_title == PREVIEW_STACK_TITLE:
            # Colonne Focus (colonne fantome de l'apercu) : entete masque et fond @skinN1 (anciennes
            # surcharges de l'onglet Focus, codees en dur), ratio de son image = `preview_image_ratio`.
            col_style["header_visible"] = False
            col_style["column_bg_color"] = "@skinN1"
            col_style["item_image_ratio"] = settings.get("preview_image_ratio", 1.0)
        set_column_style(real_title, col_style)
        # sizeHint (RowDelegate / ProjectTileDelegate) lit COLUMN_SETTINGS[titre] : hauteur, espacement
        # et largeur EFFECTIFS y sont recopies. Inspecteur et Focus n'y sont pas (pas des colonnes a lignes).
        if real_title in _dimensions.COLUMN_SETTINGS:
            if col_style.get("item_row_height") is not None:
                _dimensions.COLUMN_SETTINGS[real_title]["height"] = int(col_style["item_row_height"])
            _dimensions.COLUMN_SETTINGS[real_title]["spacing"] = max(0, int(col_style.get("item_row_spacing") or 0))
            if col_style.get("item_column_width") is not None:
                _dimensions.COLUMN_SETTINGS[real_title]["width"] = int(col_style["item_column_width"])

    # "Contenu" n'a pas d'onglet de surcharge dedie (voir settings_window.
    # _build_columns_page) : suit directement la valeur GENERALE, jamais
    # une surcharge PAR TITRE — c'est le SEUL bucket restant dans ce cas
    # ("Logiciels"/"IN"/"OVER"/"OUT" ont desormais leur propre onglet, voir
    # la boucle ci-dessus) : c'est le bucket GENERIQUE partage par tout
    # contenu ouvert au-dela d'une chaine (configuree ou legacy), un nom de
    # dossier quelconque, jamais un concept fixe a surcharger individuellement.
    if "Contenu" in _dimensions.COLUMN_SETTINGS:
        if settings.get("item_row_height") is not None:
            _dimensions.COLUMN_SETTINGS["Contenu"]["height"] = int(settings.get("item_row_height"))
        _dimensions.COLUMN_SETTINGS["Contenu"]["spacing"] = max(0, int(settings.get("item_row_spacing") or 0))
        if settings.get("item_column_width") is not None:
            _dimensions.COLUMN_SETTINGS["Contenu"]["width"] = int(settings.get("item_column_width"))

    header_family = (settings.get("header_font_family") or "").strip()
    if header_family:
        conf = dict(settings.get("font_colhead") or {})
        conf["family"] = header_family
        settings = dict(settings)
        settings["font_colhead"] = conf

    for role, key in (
        ("app", "font_main"),
        ("titles", "font_titles"),
        ("folders", "font_folders"),
        ("files", "font_files"),
        ("buttons", "font_buttons"),
        ("colhead", "font_colhead"),
        ("info", "font_info"),
        ("info2", "font_info2"),
        ("code", "font_code"),
    ):
        conf = settings.get(key) or {}
        set_role_font(
            role, conf.get("family", ""), conf.get("size", 12), conf.get("bold", False),
            conf.get("smoothing", "current"), conf.get("color", ""), conf.get("custom", False),
        )

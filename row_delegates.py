from pathlib import Path
from PySide6.QtCore import (
    QRect, QSize, Qt,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
)
from app_style import (
    C,
    _hex_to_rgb,
    font,
    role_color,
    role_font,
    resolve_color_ref,
    column_style_for,
)
import ui_state
from config import (
    PREVIEWABLE_EXTENSIONS,
    SHOW_FILE_IMAGE_PREVIEWS,
    SOFTWARE_ICON_SIZE,
)
from previews import (
    UI_ICON_SHORTCUT,
    custom_ui_icon_pixmap,
    file_image_pixmap,
    software_icon_key,
)
from settings_widgets import (
    _paint_bordered_rect,
    _radius_any,
    _radius_dict,
)
from browser_core import (
    ROLE_ISDIR,
    ROLE_IS_SHORTCUT,
    ROLE_PATH,
    ROLE_SOURCE_LABEL,
    ROLE_SOURCE_STEP,
    _paint_row_border,
    _paint_row_image,
    _resolve_font_family,
    _resolve_row_font_color,
    _resolve_shortcut_font_color,
    _row_icon_pixmap,
    _step_badge_color,
    _step_badge_rect,
    _step_badge_text_color,
    col_spacing,
    load_project_columns,
    project_step_count,
    project_thumbnail_path,
    project_thumbnail_pixmap,
)


class RowDelegate(QStyledItemDelegate):
    """Icone/image + nom, rendu UNIQUE partage par toutes les colonnes SAUF
    Projets/Sous-projet (voir ProjectTileDelegate) — voir _paint_unified_row.
    L'image affichee (voir paint) est resolue par colonne : apercu
    personnalise (colonne "Type"), icone logiciel reconnu (colonne
    "Logiciels"), ou apercu du fichier lui-meme si previsualisable (voir
    SHOW_FILE_IMAGE_PREVIEWS) — sinon l'icone toggle (voir item_icon_enabled)."""

    def __init__(self, column):
        super().__init__(column)
        self.column = column
        self.refresh_fonts()

    def refresh_fonts(self):
        """Relit la police/couleur EFFECTIVES du texte (voir
        _resolve_row_font_color, General ou surcharge par colonne) : appele
        a la creation, et de nouveau si l'utilisateur change les parametres
        de typographie sans reconstruire la colonne (previsualisation en
        direct)."""
        self.type_font, self.type_color = _resolve_row_font_color(self.column.style_title)

    def _has_preview(self, index) -> bool:
        """Version bon marche de _image_pixmap : dit si CETTE ligne
        affichera un apercu, sans decoder/charger l'image elle-meme (juste
        le type ISDIR et l'extension, deja en memoire dans le modele).
        Utilisee par sizeHint (voir plus bas) — y appeler _image_pixmap
        directement forcerait Qt (listes a tailles non uniformes, voir
        Column.__init__) a decoder TOUTES les images d'un dossier des son
        ouverture pour calculer la mise en page, plutot que paresseusement
        au dessin des seules lignes visibles (voir paint) : exactement le
        ralentissement observe a l'ouverture d'un gros dossier de
        references."""
        if not SHOW_FILE_IMAGE_PREVIEWS or bool(index.data(ROLE_ISDIR)):
            return False
        path_str = index.data(ROLE_PATH)
        return bool(path_str) and Path(path_str).suffix.lower() in PREVIEWABLE_EXTENSIONS

    def _image_pixmap(self, index) -> QPixmap | None:
        if not self._has_preview(index):
            return None
        return file_image_pixmap(Path(index.data(ROLE_PATH)), asynchronous=True)

    def sizeHint(self, option, index) -> QSize:
        # L'espacement est ajoute a la hauteur ici, puis retranche au dessin
        # (voir paint) : c'est ce reste, non peint, qui forme l'espace exact
        # entre deux lignes (voir la remarque sur QListView.setSpacing plus
        # haut dans Column.__init__). Hauteur UNIFORME (col_row_height,
        # PAS col_plain_height selon presence d'apercu) : comme la colonne
        # "Type", toutes les lignes d'une meme colonne partagent desormais
        # la MEME hauteur, avec ou sans image — voir la remarque de
        # l'utilisateur, "reformate toutes les autres colonnes exactement
        # de la meme maniere que la colonne type".
        title = self.column.style_title
        return QSize(self.column.width(), self.column.effective_row_height() + col_spacing(title))

    def paint(self, painter: QPainter, option, index):
        # Rendu UNIQUE, PARTAGE par toutes les colonnes (voir
        # _paint_unified_row) — seule la RESOLUTION de l'image affichee
        # differe encore par colonne : apercu personnalise (voir Column.
        # _on_context_menu) sur "Type", icone logiciel reconnu ou apercu de
        # fichier (deja existants, REUTILISES tels quels) sur les autres —
        # voir la remarque de l'utilisateur, "je veux que tu reformate
        # toutes les autres colonnes exactement de la meme maniere que la
        # colonne type ... si une colonne a deja des images, reutilises
        # les".
        title = self.column.style_title
        spacing = col_spacing(title)
        rect = option.rect.adjusted(0, 0, 0, -spacing)
        is_dir = bool(index.data(ROLE_ISDIR))
        path_str = index.data(ROLE_PATH)

        # Icone de logiciel (voir software_icon_key/SOFTWARE_ICONS/
        # settings_window._section_logiciels) : DISTINCTE d'un apercu (voir
        # ci-dessous) — voir la remarque de l'utilisateur, "tous les
        # dossiers qui ont le nom d'un logiciel doivent avoir son icone, je
        # veux que tu fasses la distinction entre une icone et un apercu".
        # Reconnue pour TOUT dossier dont le NOM correspond a un logiciel
        # (connu ou ajoute), dans N'IMPORTE QUELLE colonne — plus seulement
        # "Logiciels" comme avant. DISTINCTE d'un apercu (voir plus bas) —
        # les DEUX peuvent coexister sur la meme ligne (voir la remarque de
        # l'utilisateur, "les apercus a droite et les icones a gauche,
        # comme ca il n'y aura plus d'ambiguite" — voir _paint_unified_row).
        is_shortcut = bool(index.data(ROLE_IS_SHORTCUT))
        icon_key = software_icon_key(index.data(Qt.DisplayRole) or "") if is_dir else None
        icon_pixmap = _row_icon_pixmap(is_dir, icon_key, SOFTWARE_ICON_SIZE)
        if is_shortcut:
            # Icone DEDIEE (Settings > ICONES > General > "Raccourcis") si
            # l'utilisateur en a choisi une, prioritaire sur l'icone
            # logiciel/le repli dossier — voir la remarque de l'utilisateur,
            # "dans les icones merci de rajouter une ligne raccourcis".
            shortcut_icon = custom_ui_icon_pixmap(UI_ICON_SHORTCUT, SOFTWARE_ICON_SIZE)
            if shortcut_icon is not None:
                icon_pixmap = shortcut_icon

        # Apercu personnalise (voir Column._on_context_menu, "Ajouter un
        # apercu.../Capturer une zone d'ecran...") : deja generalise a
        # N'IMPORTE QUELLE colonne/ligne dossier cote menu (voir sa
        # remarque, "n'importe quelle ligne de n'importe quelle colonne"),
        # y compris une colonne de chaine CONFIGUREE (voir load_project_
        # columns/on_selected, ex. "test1"/"test2") — teste ici pour TOUT
        # titre, pas seulement "Type" comme avant, sinon une capture prise
        # sur une de ces colonnes ne s'affichait jamais (project_thumbnail_
        # path existait bien sur le disque, mais RowDelegate.paint ne le
        # consultait que sur "Type").
        preview_pixmap = None
        if path_str and is_dir and project_thumbnail_path(Path(path_str)).is_file():
            preview_pixmap = project_thumbnail_pixmap(Path(path_str))
        elif title != "Type":
            preview_pixmap = self._image_pixmap(index)

        # Police/couleur DEDIEES pour un raccourci (voir SHORTCUT_TEXT_
        # STYLE, Settings > RACCOURCI) — GENERALE, pas par colonne : un
        # raccourci doit se reperer de la MEME facon partout.
        row_font, row_color = _resolve_shortcut_font_color() if is_shortcut else (self.type_font, self.type_color)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        _paint_unified_row(
            painter, rect, option, column_style_for(title),
            index.data(Qt.DisplayRole), icon_pixmap, preview_pixmap, row_font, row_color,
            self.column.is_active, annotation=index.data(ROLE_SOURCE_LABEL),
            annotation_step=index.data(ROLE_SOURCE_STEP),
            icon_visible_override=self.column._show_icon_override,
            preview_visible_override=self.column._show_preview_override,
            icon_size_override=self.column._icon_size_override,
            icon_padding_left_override=self.column._icon_padding_left_override,
            text_padding_left_override=self.column._text_padding_left_override,
        )
        painter.restore()

def _paint_unified_row(
    painter: QPainter, rect, option, style: dict, name: str,
    icon_pixmap: QPixmap | None, preview_pixmap: QPixmap | None,
    text_font, text_color: str, active: bool, annotation: str | None = None,
    step_badge: int | str | None = None, annotation_step: int | None = None,
    icon_visible_override: bool | None = None, preview_visible_override: bool | None = None,
    icon_size_override: int | None = None, icon_padding_left_override: int | None = None,
    text_padding_left_override: int | None = None,
):
    """Ligne UNIQUE, PARTAGEE par toutes les colonnes (Type/Projets/Sous-
    projet/Logiciels/Contenu) : icone toggle optionnelle, icone de
    logiciel/apercu personnalise (ou les DEUX a la fois) + nom + pastille
    de selection — voir la remarque de l'utilisateur, "je veux que tu
    reformate toutes les autres colonnes exactement de la meme maniere que
    la colonne type ... si une colonne a deja des images, reutilises les".
    `icon_pixmap`/`preview_pixmap` : DISTINCTS (voir la remarque de
    l'utilisateur, "je veux que desormais nous distinguions icone et
    apercu ... les apercus a droite et les icones a gauche, comme ca il
    n'y aura plus d'ambiguite") — une icone IDENTIFIE ce qu'est le dossier
    (logiciel reconnu, voir software_icon_key), toujours ANCREE a GAUCHE,
    comme avant ; un apercu est une simple DECORATION facultative (vignette
    de projet, capture d'ecran...), desormais ANCRE a DROITE — les DEUX
    peuvent coexister sur la MEME ligne (voir RowDelegate.paint/
    ProjectTileDelegate.paint, qui les resolvent independamment). Chacun
    est deja RESOLU par l'appelant (chaque colonne garde sa propre
    logique de choix d'image, voir RowDelegate.paint/ProjectTileDelegate.
    `annotation` (voir ROLE_SOURCE_LABEL, RowDelegate.paint) : texte
    "(projet)"/"(<nom du sous-projet>)" affiche APRES le nom, police/
    couleur DIFFERENTES (role "info", comme le compteur d'en-tete) — voir
    la remarque de l'utilisateur, "je veux une anotation a cote du nom du
    repertoire ... entre parentheses (d'une police et couleur
    differente)".
    paint) ; None affiche l'icone toggle (si activee) ou rien.
    `step_badge` (voir project_step_count/_step_badge_color/_step_badge_rect,
    ProjectTileDelegate.paint) : nombre affiche dans un badge rond en haut a
    droite de `rect` (colonne "Projets" uniquement) ; None = pas de badge."""
    s = style
    selected = bool(option.state & QStyle.State_Selected)
    hovered = bool(option.state & QStyle.State_MouseOver)

    # C["void"] (Skin - niveau 2), PAS C["row_idle"] : meme couleur que
    # le fond de la colonne SOUS l'entete (voir column_frame_qss, bg_hex
    # passe C["void"] aussi) — une ligne NON selectionnee doit se fondre
    # avec l'espace vide de la colonne, pas trancher avec sa propre
    # teinte — voir la remarque de l'utilisateur, "je veux que la
    # couleur sous l'entete/sous les textes non selectionnes soient
    # Skin - niveau 2".
    painter.fillRect(rect, QColor(C["void"]))

    # Filet horizontal ENTRE les lignes — AVANT la selection (pas apres) :
    # voir sa docstring.
    _paint_row_border(painter, rect, option, s)

    icon_enabled = bool(s.get("item_icon_enabled", True))
    # "Padding gauche du texte" (menu contextuel, voir Column._on_context_
    # menu/_text_padding_left_override) : surcharge PAR COLONNE de item_
    # text_padding — voir la remarque de l'utilisateur, "je veux que le
    # padding left ... du texte de chaque ligne soit modifiable dans le
    # menu contextuel".
    text_padding = max(0, text_padding_left_override if text_padding_left_override is not None
                       else int(s.get("item_text_padding", 8)))
    # Menu contextuel "Afficher l'icone"/"Afficher l'apercu" (voir Column.
    # _on_context_menu/_show_icon_override/_show_preview_override) : None
    # (repli) = comportement INCHANGE, sinon force explicitement visible/
    # masque pour CETTE colonne — voir la remarque de l'utilisateur,
    # "ajoute une option 'afficher l'apercu' avec un toggle, une autre
    # 'afficher l'icone' avec un toggle".
    icon_visible = True if icon_visible_override is None else icon_visible_override
    preview_visible = True if preview_visible_override is None else preview_visible_override
    has_icon = icon_pixmap is not None and icon_visible
    has_preview = preview_pixmap is not None and preview_visible

    if selected:
        state = "focus" if active else "unfocus"
        sel_color = s.get("item_selection_focus_color", C["accent"]) if active \
            else s.get("item_selection_unfocus_color", C["sel_idle"])
    elif hovered:
        state = "hover"
        sel_color = s.get("item_hover_color", C["hover"])
    else:
        # Boite "non selectionnee" (voir DEFAULT_SETTINGS.
        # item_idle_color) : MEME forme (padding/bordure/rayon) que les
        # autres etats — voir la remarque de l'utilisateur, "ajoute une
        # couleur (sous couleur de survol) qui represente la couleur
        # non selectionnee ... un fond sur les items non selectionnes,
        # de la meme forme que les divers selections". resolve_color_ref
        # (PAS s.get(...) direct) : _AppOrCustomColorField (contrairement
        # a Focus/Hors focus/Survol, restes en _ColorField) peut stocker
        # une reference "@slot", pas seulement un hex direct.
        state = "idle"
        sel_color = resolve_color_ref(s.get("item_idle_color"), C["row_idle"])

    if sel_color:
        # Forme (padding/bordure/rayon/bord de colonne) : "focus" reste la
        # BASE (cles item_selection_* historiques, inchangees) — les 3
        # autres etats (unfocus/hover/idle) EN HERITENT SAUF override
        # explicite (un toggle par parametre, voir Settings > General >
        # Colonnes > Selection > Non focus/Survol/Non selectionne) — voir
        # la remarque de l'utilisateur, "non focus survol et non
        # selectionne sont des clones des focus (sauf la couleur) donc
        # mets leur des toggles d'override".
        def _shape(value_key: str, base_key: str, default, toggle_suffix: str | None = None):
            if state == "focus":
                return s.get(base_key, default)
            toggle_suffix = toggle_suffix or value_key
            if s.get(f"item_selection_{state}_{toggle_suffix}_override"):
                return s.get(f"item_selection_{state}_{value_key}", default)
            return s.get(base_key, default)

        pad = _shape("padding", "item_selection_padding", {}) or {}
        pad_left = max(0, int(pad.get("left", 0)))
        pad_right = max(0, int(pad.get("right", 0)))
        pad_top = max(0, int(pad.get("top", 0)))
        pad_bottom = max(0, int(pad.get("bottom", 0)))
        # Reduit PROPORTIONNELLEMENT (jamais coupe a 0 net) si la somme
        # depasse la dimension disponible : un padding General reglé pour
        # des lignes HAUTES (Projets/Sous-projet, ~58px) pouvait a lui
        # seul depasser la hauteur des lignes bien plus COURTES (Logiciels/
        # Contenu/IN/OVER/OUT, ~25-30px), rendant sel_rect degenere
        # (largeur/hauteur <= 0) — la boite de selection (et donc sa
        # couleur) disparaissait alors SILENCIEUSEMENT (voir le test
        # `sel_rect.width() > 0 and sel_rect.height() > 0` plus bas), MEME
        # avec une couleur parfaitement valide — voir la remarque de
        # l'utilisateur, "pour les colonnes logiciels in over et out, la
        # couleur des selections ne se fait pas ... sa couleur ne devient
        # pas celle definie dans les settings".
        if pad_top + pad_bottom >= rect.height():
            total = pad_top + pad_bottom
            budget = max(0, rect.height() - 1)
            scale = budget / total if total > 0 else 0
            pad_top = int(pad_top * scale)
            pad_bottom = int(pad_bottom * scale)
        if pad_left + pad_right >= rect.width():
            total = pad_left + pad_right
            budget = max(0, rect.width() - 1)
            scale = budget / total if total > 0 else 0
            pad_left = int(pad_left * scale)
            pad_right = int(pad_right * scale)
        sel_rect = QRect(
            rect.left() + pad_left, rect.top() + pad_top,
            rect.width() - pad_left - pad_right, rect.height() - pad_top - pad_bottom,
        )
        border_enabled = dict(_shape(
            "border_enabled", "item_selection_border_enabled", {}, toggle_suffix="border") or {})
        border_colors = {
            k: resolve_color_ref(v) for k, v in (
                _shape("border", "item_selection_border", {}, toggle_suffix="border") or {}
            ).items()
        }
        edge_border = bool(_shape("edge_border", "item_selection_edge_border", True))
        for side, side_pad in (("left", pad_left), ("right", pad_right)):
            flush = side_pad <= 0
            if flush and not edge_border:
                border_enabled[side] = False
        radius = _radius_dict(_shape("radius", "item_selection_radius", 0))
        if sel_rect.width() > 0 and sel_rect.height() > 0:
            painter.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
            _paint_bordered_rect(painter, sel_rect, radius, border_enabled, 1, border_colors, sel_color)
            painter.setRenderHint(QPainter.Antialiasing, False)

    # Ancre du contenu (icone/image/texte) : le bord GAUCHE du cadre de
    # selection (sel_rect, TOUJOURS defini ici puisque sel_color l'est
    # desormais dans les 3 etats, voir plus haut), PAS le bord de la
    # colonne — voir la remarque de l'utilisateur, "quand on a une ligne
    # sans apercu, le padding du texte ne doit pas etre entre le texte et
    # le bord de la colonne, mais entre le texte et le bord du cadre de
    # selection, donc si le padding change, ca doit etre pris en compte
    # dans le calcul". Repli sur le bord de la colonne UNIQUEMENT si le
    # cadre de selection est degenere (padding superieur a la largeur/
    # hauteur de la ligne).
    icon_x = sel_rect.left() + text_padding if sel_rect.width() > 0 else rect.left() + text_padding
    text_x = icon_x

    # Icone (gauche) / apercu (droite) EN PREMIER PLAN (voir la remarque de
    # l'utilisateur, "l'image d'apercu est dessous les zones de selection
    # ... mets les en premier plan") : dessines APRES la boite de
    # selection/idle ci-dessus, jamais recouverts par son remplissage
    # opaque. Les DEUX peuvent coexister sur la meme ligne (voir la
    # docstring de cette fonction, "je veux que desormais nous
    # distinguions icone et apercu ... les apercus a droite et les icones
    # a gauche") — chacun garde la MEME hauteur que la zone de selection,
    # MEME ratio (item_image_ratio) — seule leur ANCRE horizontale differe.
    img_size = sel_rect.height() if sel_rect.height() > 0 else 14
    # item_image_ratio (largeur/hauteur, voir Colonnes > ... > Image) :
    # 1.0 = carre (comportement INCHANGE par defaut) — plus grand, plus
    # l'image est allongee HORIZONTALEMENT (largeur > hauteur) — voir la
    # remarque de l'utilisateur, "je veux une section ratio, qui
    # correspond au ratio entre la hauteur et la largeur. Plus le chiffre
    # est grand et plus l'image est allongee horizontalement". La HAUTEUR
    # reste toujours celle de la zone de selection (voir plus haut) ;
    # seule la LARGEUR en depend.
    img_ratio = float(s.get("item_image_ratio", 1.0) or 1.0)
    img_width = max(1, round(img_size * img_ratio))
    img_y = sel_rect.top() if sel_rect.height() > 0 else rect.center().y() - 7
    img_pad = s.get("item_image_padding") or {}
    text_right_limit = rect.right() - text_padding

    if has_icon:
        # Hauteur = celle de la zone de selection, collee sur son bord
        # GAUCHE — voir la remarque de l'utilisateur, "la hauteur de
        # l'image soit de la meme hauteur que les zones de selection ...
        # collee sur le bord gauche des zones de selection" — PAS le
        # carre 14x14 fixe de l'icone toggle (elle, inchangee, voir le
        # "elif" plus bas).
        # Padding gauche DEDIE a l'icone (item_icon_padding_left, General >
        # Colonnes > Texte, MEME esprit que le padding du texte) : decale
        # l'icone SEULE, sans toucher au texte ni a l'apercu — voir la
        # remarque de l'utilisateur, "comme les textes j'aimerais que tu
        # ajoutes un padding left sur les icones pour chaque lignes".
        icon_left_pad = max(0, icon_padding_left_override if icon_padding_left_override is not None
                            else int(s.get("item_icon_padding_left", 0) or 0))
        icon_img_x = (sel_rect.left() if sel_rect.width() > 0 else icon_x) + icon_left_pad
        # Taille de l'icone INDEPENDANTE de l'apercu (item_icon_size,
        # General > Colonnes > Texte > "Taille de l'icone par defaut") : 0
        # (repli) = comportement INCHANGE, la meme hauteur que la zone de
        # selection (img_size, comme l'apercu) — une valeur positive fixe
        # la taille de l'icone independamment de la hauteur de ligne,
        # centree verticalement dans l'espace qu'elle occuperait sinon —
        # voir la remarque de l'utilisateur, "ajoute une ligne dans les
        # settings ... taille de l'icone par defaut".
        icon_box_size = max(1, icon_size_override or int(s.get("item_icon_size") or 0) or img_size)
        icon_box_width = max(1, round(icon_box_size * img_ratio))
        icon_img_y = img_y + (img_size - icon_box_size) // 2
        # Padding/bordure/rayon (voir Colonnes > ... > Image, DEFAULT_
        # SETTINGS.item_image_*) — voir la remarque de l'utilisateur,
        # "les parametres images ... sont pour controler les apercus
        # que l'on trouve sur les differentes lignes". item_image_radius
        # est un reglage INDEPENDANT du rayon de selection (0 = carre).
        _paint_row_image(painter, QRect(icon_img_x, icon_img_y, icon_box_width, icon_box_size), icon_pixmap, s)
        # Distance texte<->icone PILOTEE par "Padding du texte" (item_
        # text_padding), PAS un ecart fixe — voir la remarque de
        # l'utilisateur, "je veux que le padding du texte ... controle
        # ... la distance entre le texte et l'image quand il y a un
        # apercu". Mesuree depuis le bord REEL de l'image (le carre
        # visible, retreci par son propre padding, voir _paint_row_image/
        # item_image_padding), PAS depuis le bord du slot qui la
        # contient : sinon le padding de l'image s'ajouterait EN PLUS
        # du padding du texte au lieu d'etre pris en compte dedans —
        # voir la remarque de l'utilisateur, "attention a bien prendre
        # en compte le bord de l'image, c'est a dire que si l'image a
        # elle-meme un padding, ca doit etre pris en compte dans la
        # distance totale".
        img_right_pad = max(0, int(img_pad.get("right", 0)))
        text_x = icon_img_x + icon_box_width - img_right_pad + text_padding
    elif icon_enabled and icon_visible:
        box_y = rect.center().y() - 14 // 2
        painter.setPen(QPen(QColor(role_color("dim", C["label"])), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(icon_x, box_y, 14 - 1, 14 - 1)
        text_x = icon_x + 14 + 8

    preview_img_x = None
    if has_preview:
        # MEME principe que l'icone, mais ANCRE sur le bord DROIT de la
        # zone de selection (QRect.right() = left+width-1, voir Qt) —
        # jamais lie a la presence/absence d'une icone a gauche.
        preview_img_x = (sel_rect.right() - img_width + 1) if sel_rect.width() > 0 else (rect.right() - img_width)
        _paint_row_image(painter, QRect(preview_img_x, img_y, img_width, img_size), preview_pixmap, s)
        img_left_pad = max(0, int(img_pad.get("left", 0)))
        text_right_limit = preview_img_x + img_left_pad - text_padding

    # Badge numerote (voir plus bas) : calcule ICI (avant text_rect) des
    # que l'apercu est connu — voir la remarque de l'utilisateur, "je
    # veux que la petite icone de levels soit AVANT l'apercu et pas a
    # l'interieur" : desormais sa propre plage, entre le texte et
    # l'apercu, retranchee de text_right_limit comme l'apercu lui-meme
    # (sinon un nom long pourrait passer PAR-DESSOUS le badge).
    badge_rect = None
    if step_badge is not None:
        badge_rect = _step_badge_rect(rect, preview_img_x)
        text_right_limit = min(text_right_limit, badge_rect.left() - text_padding)

    final_text_color = C["accent_text"] if (selected and active) else text_color
    text_rect = QRect(text_x, rect.top(), max(0, text_right_limit - text_x), rect.height())
    if annotation:
        # Largeur de l'annotation d'ABORD (police "info", voir sa remarque
        # de tete) : le nom n'a droit qu'au RESTE de text_rect, elide en
        # consequence — sinon un nom long masquerait completement une
        # annotation qui tiendrait pourtant a cote.
        ann_text = f" ({annotation})"
        ann_font = role_font("info", 10, 400)
        painter.setFont(ann_font)
        ann_width = painter.fontMetrics().horizontalAdvance(ann_text)

        painter.setFont(text_font)
        painter.setPen(QColor(final_text_color))
        name_width = max(0, text_rect.width() - ann_width)
        elided_name = painter.fontMetrics().elidedText(name, Qt.ElideMiddle, name_width)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_name)

        name_actual_width = painter.fontMetrics().horizontalAdvance(elided_name)
        ann_rect = QRect(
            text_rect.left() + name_actual_width, text_rect.top(),
            max(0, text_rect.width() - name_actual_width), text_rect.height())
        if ann_rect.width() > 0:
            painter.setFont(ann_font)
            # Couleur par etape (voir ROLE_SOURCE_STEP/_step_badge_color,
            # Settings > Colonnes > Projets > Colonnes > "Icone de
            # niveaux") si connue, sinon la couleur fixe d'origine (voir la
            # remarque de l'utilisateur, "les couleurs des indications
            # doivent changer selon les etapes").
            ann_color = _step_badge_color(annotation_step) if annotation_step is not None else role_color("info", C["dim"])
            painter.setPen(QColor(ann_color))
            elided_ann = painter.fontMetrics().elidedText(ann_text, Qt.ElideRight, ann_rect.width())
            painter.drawText(ann_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_ann)
    else:
        painter.setFont(text_font)
        painter.setPen(QColor(final_text_color))
        elided = painter.fontMetrics().elidedText(name, Qt.ElideMiddle, max(0, text_rect.width()))
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided)

    if badge_rect is not None:
        # Style REGLABLE (voir apply_all_settings/STEP_BADGE_STYLE, Settings
        # > Colonnes > Projets > Colonnes > "Icone de niveaux") — largeur/
        # hauteur/bordure/rayon/couleur, MEME technique que n'importe quel
        # autre rectangle borde-arrondi de l'appli (_paint_bordered_rect),
        # plutot qu'un simple cercle fixe comme avant.
        badge_style = ui_state.STEP_BADGE_STYLE
        badge_border_colors = {
            k: resolve_color_ref(v) for k, v in (badge_style.get("border") or {}).items()
        }
        # Lissage (antialiasing) du TRAIT de bordure — DESACTIVABLE (voir
        # Settings > Colonnes > Projets > Colonnes > "Icone de niveaux" >
        # "Lissage de la bordure"), contrairement au reste — voir la
        # remarque de l'utilisateur, "lissage des bordures" -> "antialiasing
        # du contour de la bordure".
        painter.setRenderHint(QPainter.Antialiasing, bool(badge_style.get("border_smoothing", True)))
        _paint_bordered_rect(
            painter, badge_rect, badge_style["radius"], badge_style.get("border_enabled") or {},
            max(1, int(badge_style.get("border_thickness", 1))), badge_border_colors,
            _step_badge_color(step_badge),
        )
        painter.setRenderHint(QPainter.Antialiasing, False)
        # Police/gras/lissage du numero (voir Settings > ... > "Icone de
        # niveaux" > "Police / gras / lissage du numero") — couleur PAR
        # BASE (_step_badge_text_color), PAS un champ separe (voir la
        # remarque de l'utilisateur, "enleve la couleur dans la ligne
        # texte ... la couleur du haut est pour le texte").
        badge_font_weight = 700 if badge_style.get("font_bold", True) else 400
        badge_font_family = _resolve_font_family(
            (badge_style.get("font_family") or "").strip(), 10, badge_font_weight, fallback_role="info")
        badge_smoothing = (
            badge_style.get("font_smoothing", "current")
            if badge_style.get("font_smoothing_enabled") else "current")
        painter.setPen(QColor(_step_badge_text_color(step_badge)))
        painter.setFont(font(10, badge_font_weight, family=badge_font_family, smoothing=badge_smoothing))
        painter.drawText(badge_rect, Qt.AlignCenter, str(step_badge))

class ProjectTileDelegate(QStyledItemDelegate):
    """Colonnes "Projets"/"Sous-projet" : meme rendu PARTAGE que RowDelegate
    (voir _paint_unified_row), avec la vignette de projet (perso si
    presente, voir project_thumbnail_path, sinon image par defaut
    generique) comme image."""

    def __init__(self, column):
        super().__init__(column)
        self.column = column
        self.refresh_fonts()

    def refresh_fonts(self):
        self.font_name, self.color_name = _resolve_row_font_color(self.column.style_title)

    def sizeHint(self, option, index) -> QSize:
        # L'espacement est ajoute ici, retranche au dessin (voir paint) :
        # voir la remarque sur QListView.setSpacing dans Column.__init__.
        title = self.column.style_title
        return QSize(self.column.width(), self.column.effective_row_height() + col_spacing(title))

    def paint(self, painter: QPainter, option, index):
        # Rendu UNIQUE, PARTAGE avec RowDelegate (voir _paint_unified_row) —
        # voir la remarque de l'utilisateur, "je veux que tu reformate
        # toutes les autres colonnes exactement de la meme maniere que la
        # colonne type ... si une colonne a deja des images, reutilises
        # les" : la vignette de projet (project_thumbnail_pixmap, perso ou
        # generique par defaut, cache module-level partage — voir plus
        # haut) est REUTILISEE telle quelle, seule la mise en page/le style
        # autour changent.
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        path = Path(index.data(ROLE_PATH))
        title = self.column.style_title
        rect = option.rect.adjusted(0, 0, 0, -col_spacing(title))
        step_badge = None
        if title == "Projets" and bool(index.data(ROLE_ISDIR)):
            step_badge = project_step_count(load_project_columns(path))
        # Icone de logiciel (voir RowDelegate.paint, MEME regle "tous les
        # dossiers qui ont le nom d'un logiciel", meme si un Projet/Sous-
        # projet nomme comme un logiciel reste rare en pratique) — la
        # vignette de projet (project_thumbnail_pixmap, perso ou generique
        # par defaut) est elle un APERCU (voir _paint_unified_row) :
        # DISTINCTS, la premiere a gauche, le second desormais a droite.
        is_dir_entry = bool(index.data(ROLE_ISDIR))
        icon_key = software_icon_key(path.name) if is_dir_entry else None
        icon_pixmap = _row_icon_pixmap(is_dir_entry, icon_key, SOFTWARE_ICON_SIZE)
        is_shortcut = bool(index.data(ROLE_IS_SHORTCUT))
        if is_shortcut:
            shortcut_icon = custom_ui_icon_pixmap(UI_ICON_SHORTCUT, SOFTWARE_ICON_SIZE)
            if shortcut_icon is not None:
                icon_pixmap = shortcut_icon
        row_font, row_color = _resolve_shortcut_font_color() if is_shortcut else (self.font_name, self.color_name)
        _paint_unified_row(
            painter, rect, option, column_style_for(title),
            path.name, icon_pixmap, project_thumbnail_pixmap(path), row_font, row_color,
            self.column.is_active, step_badge=step_badge,
            icon_visible_override=self.column._show_icon_override,
            preview_visible_override=self.column._show_preview_override,
            icon_size_override=self.column._icon_size_override,
            icon_padding_left_override=self.column._icon_padding_left_override,
            text_padding_left_override=self.column._text_padding_left_override,
        )
        painter.restore()

def _square_checkbox_qss(muted: bool = False) -> str:
    """Habillage QSS partage par toutes les cases a cocher de
    ColumnConfigDialog (case CARREE petite + coche, pas le rendu natif de
    l'OS) — reproduit la maquette fournie par l'utilisateur, "change
    l'interface de la fenetre scrupuleusement comme celle en piece
    jointe" : le fonctionnement (isChecked/setChecked/toggled, deja
    utilise partout ci-dessous) reste EXACTEMENT celui d'un QCheckBox
    normal, seul l'indicateur est restyle via QSS (::indicator).

    `muted=True` (voir "Focus"/"In / Over / Out", toggles secondaires a
    cote de "Set") : texte NORMAL (pas seulement `:disabled`) attenue —
    voir la remarque de l'utilisateur, "le texte de focus et in over out
    doit etre vraiment moins perceptible"."""
    # 0.30 (pas 0.55) : voir la remarque de l'utilisateur, "le texte de
    # focus et in over out doit etre vraiment moins perceptible (plus de
    # transparence, laisse 30%)".
    text_color = f"rgba({', '.join(str(c) for c in _hex_to_rgb(C['text']))}, 0.30)" if muted else C['text']
    return (
        f"QCheckBox {{ color: {text_color}; spacing: 8px; background: transparent; }}"
        f"QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 2px; "
        f"border: 1px solid {C['border']}; background: {C['well']}; }}"
        f"QCheckBox::indicator:hover {{ border: 1px solid {C['accent']}; }}"
        f"QCheckBox::indicator:checked {{ background: {C['accent']}; border: 1px solid {C['accent']}; }}"
        # Grise (voir setEnabled(False), la remarque de l'utilisateur,
        # "quand set est desactive, desactive automatiquement focus, in
        # over et out, et grise les") : les couleurs ci-dessus etant fixes
        # (QSS EXPLICITE, pas le rendu natif de l'OS), Qt ne les assombrit
        # PAS automatiquement a l'etat desactive sans ces regles ":disabled"
        # dediees. rgba (alpha ~0.5 sur la couleur NORMALE, pas C['dim']
        # directement) : un simple saut vers C['dim'] (bien plus sombre que
        # le texte normal) rendait le grisage trop marque — voir la remarque
        # de l'utilisateur, "le grise de desactivation doit etre moins
        # perceptible".
        f"QCheckBox:disabled {{ color: rgba({', '.join(str(c) for c in _hex_to_rgb(C['text']))}, 0.45); }}"
        f"QCheckBox::indicator:disabled {{ "
        f"border: 1px solid rgba({', '.join(str(c) for c in _hex_to_rgb(C['border']))}, 0.6); "
        f"background: {C['well']}; }}"
    )

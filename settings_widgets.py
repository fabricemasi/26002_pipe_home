from PySide6.QtCore import (
    QEasingCurve, QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDoubleValidator,
    QFont,
    QGuiApplication,
    QIntValidator,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    SEMANTIC_COLOR_SLOTS,
    _hex_to_alpha,
    _hex_to_rgb,
    apply_dwm_frame,
    get_input_radius,
    installed_font_families,
    ITEM_FONT_ROLE_LABELS,
)
from settings_theme import (  # noqa: F401 (reexportes)
    _input_radius, _qfont, _register_input, _register_radius, _set_button_radius, _set_input_radius,
    _set_text_role, _text_label,
)
from settings_store import (
    M,
    _CORNERS,
    _SLIDER_STYLE,
    _coerce_corner_radius,
    _coerce_side_enabled,
    _resolve_color_value,
)


# ==========================================================================
# Petits widgets reproduisant les controles de la maquette.
# ==========================================================================


class _Btn(QPushButton):
    """Bouton rectangulaire plat. Son arrondi suit TOUJOURS Geometrie >
    Boutons > Coins arrondis (inscription automatique, voir
    settings_theme._register_radius) : ne jamais le fixer a la main."""

    def __init__(self, text: str, bg: str, border: str, fg: str, hover: str,
                 height: int = 24, weight: int = 500, padding: str = "0 11px", align_left: bool = False,
                 parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(height)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(_qfont(11, weight))
        self._bg, self._border, self._fg, self._hover, self._padding = bg, border, fg, hover, padding
        self._align_left = align_left
        # Rayon : Geometrie > Boutons > Coins arrondis, suivi en direct (voir settings_theme).
        self._radius = _register_radius(self, "button")
        self._refresh_style()

    def _refresh_style(self):
        border_rule = f"border: 1px solid {self._border};" if self._border else "border: none;"
        self.setStyleSheet(
            f"QPushButton {{ background: {self._bg}; {border_rule} border-radius: {self._radius}px; "
            f"color: {self._fg}; padding: {self._padding}; }}"
            f"QPushButton:hover {{ background: {self._hover}; }}"
            + ("QPushButton { text-align: left; }" if self._align_left else "")
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_style()

class _MiniSlider(QWidget):
    """Slider peint a la main : rail + curseur ("selecteur"), habillage
    entierement lu depuis _SLIDER_STYLE (voir Geometrie > Slider) plutot que
    fige en dur — voir apply_style, a rappeler sur toute instance deja
    construite quand ce reglage change."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, width: int = 170, parent=None):
        super().__init__(parent)
        self._min, self._max = minimum, maximum
        self._value = max(minimum, min(maximum, value))
        self._width = width
        self._grab_offset = 0
        self.setCursor(Qt.ArrowCursor)
        self._apply_size()

    def _apply_size(self):
        # +8 : meme marge verticale que l'ancien fixe (14 + 8 = 22) —
        # garde le curseur/le rail respirer plutot que toucher les bords
        # haut/bas du widget quel que soit thumb_h/track_h.
        h = max(_SLIDER_STYLE["thumb_h"], _SLIDER_STYLE["track_h"]) + 8
        self.setFixedSize(self._width, h)

    def apply_style(self):
        """A rappeler sur toute instance deja construite quand Geometrie >
        Slider change (voir SettingsWindow._apply_slider_style) : thumb_h/
        track_h influent sur la hauteur meme du widget, pas seulement sa
        peinture — un simple update() ne suffirait pas pour ces deux-la."""
        self._apply_size()
        self.update()

    def value(self) -> int:
        return self._value

    def setValue(self, value: int):
        value = max(self._min, min(self._max, value))
        if value != self._value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)

    def _pct(self) -> float:
        span = self._max - self._min
        return 0.0 if span <= 0 else (self._value - self._min) / span

    def _set_from_x(self, x: int):
        pct = max(0.0, min(1.0, x / max(1, self.width())))
        self.setValue(round(self._min + pct * (self._max - self._min)))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            x = event.position().toPoint().x()
            # Clic SUR le curseur : on le saisit la ou il est (pas de saut
            # vers le pointeur) ; ailleurs, il vient sous le pointeur.
            thumb_w = _SLIDER_STYLE["thumb_w"]
            knob_center = round(self._pct() * self.width())
            self._grab_offset = x - knob_center if abs(x - knob_center) <= thumb_w // 2 + 2 else 0
            self._set_from_x(x - self._grab_offset)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._set_from_x(event.position().toPoint().x() - self._grab_offset)

    def _paint_bordered(self, p: QPainter, rect: QRect, radius, border_on,
                         border_colors: dict, fill_layers):
        """Peint `rect` (rail ou selecteur) avec, cote par cote actif, une
        bordure 1px MITREE (diagonales depuis le centre vers chaque coin,
        comme un cadre photo) plutot que 4 bandes droites independantes —
        celles-ci restaient bien 4 couleurs differentes sur un rectangle
        (radius=0) mais DISPARAISSAIENT pres des coins des que radius>0 (la
        bande, toujours large d'1 PIXEL en ligne droite, sort du contour
        arrondi qui se retrecit vers le coin — voir la remarque de
        l'utilisateur, capture a l'appui, "quelque chose de bizarre avec
        les bordures des rails"). Le miter, lui, reste une bordure
        CONTINUE quel que soit le rayon : chaque cote occupe le triangle
        entre ses 2 coins et le centre du rectangle, intersecte avec
        l'anneau exterieur-moins-interieur (les 2 chemins arrondis) —
        exactement comme les 4 cotes d'un cadre a coins coupes a 45°.

        `border_on` : bool (tous les cotes pareil, retro-compatible) OU
        dict {"top": bool, ...} — un cote DESACTIVE (voir _SideColorsField,
        la remarque de l'utilisateur "un toggle par cote") ne consomme plus
        d'epaisseur de CE cote (inset ASYMETRIQUE), le remplissage s'etend
        alors jusqu'a ce bord tout en restant en retrait des autres, actifs.
        `fill_layers` (callable prenant `p, inner_rect`) peint l'interieur —
        `inner_rect` deja calcule en tenant compte de cet inset asymetrique,
        rempli JUSQU'AU bord de chaque cote sans bordure active."""
        if rect.width() <= 0 or rect.height() <= 0:
            return
        if isinstance(border_on, dict):
            sides_on = {k: bool(border_on.get(k, False)) for k in ("top", "right", "bottom", "left")}
        else:
            v = bool(border_on)
            sides_on = {k: v for k in ("top", "right", "bottom", "left")}
        any_on = any(sides_on.values())
        t = {k: (1 if sides_on[k] else 0) for k in sides_on}
        inner_rect = QRect(
            rect.left() + t["left"], rect.top() + t["top"],
            rect.width() - t["left"] - t["right"], rect.height() - t["top"] - t["bottom"],
        )
        has_inner = inner_rect.width() > 0 and inner_rect.height() > 0
        p.save()
        p.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
        if any_on:
            outer_path = _rounded_rect_path(rect, radius)
            inner_radius = _radius_shrink(radius, 1)
            # QRectF(rect), PAS rect.right()/rect.bottom() : ces 2 methodes
            # de QRect sont INCLUSIVES (topLeft + taille - 1, la convention
            # "dernier pixel valide" de QRect), alors que addRoundedRect
            # travaille en coordonnees CONTINUES (QRectF, right/bottom =
            # topLeft + taille, sans le -1) — un ecart d'1px entre les coins
            # du triangle mitre et le contour arrondi reel, qui faisait
            # disparaitre ou deformer 1 ou plusieurs cotes selon le rayon/la
            # hauteur (voir la remarque de l'utilisateur, capture a l'appui,
            # "je suis sense avoir les 4 bordures").
            ring = outer_path.subtracted(_rounded_rect_path(inner_rect, inner_radius)) if has_inner else outer_path
            rf = QRectF(rect)
            center = rf.center()
            corners = {
                "top": (QPointF(rf.left(), rf.top()), QPointF(rf.right(), rf.top())),
                "right": (QPointF(rf.right(), rf.top()), QPointF(rf.right(), rf.bottom())),
                "bottom": (QPointF(rf.right(), rf.bottom()), QPointF(rf.left(), rf.bottom())),
                "left": (QPointF(rf.left(), rf.bottom()), QPointF(rf.left(), rf.top())),
            }
            p.setPen(Qt.NoPen)
            # Voir _paint_bordered_rect (meme technique/meme raison) : chaque
            # coin allonge de EPS UNIQUEMENT du cote ou le voisin de ce coin
            # est desactive (le vrai trou) — jamais quand les 2 cotes d'un
            # coin sont actifs. Et meme dans ce cas (2 cotes actifs), 2
            # morceaux de meme couleur sont ACCUMULES puis peints en UNE
            # seule fois (united()) plutot que separement, pour ne pas
            # laisser de lisere fantome sur la diagonale du miter (2 formes
            # anti-aliasees peintes separement ne se recouvrent jamais
            # exactement pixel pour pixel).
            EPS = 0.75
            order = ("top", "right", "bottom", "left")
            color_paths: dict[str, QPainterPath] = {}
            for i, side in enumerate(order):
                if not sides_on[side]:
                    continue
                p1, p2 = corners[side]
                neighbor_p1 = order[i - 1]
                neighbor_p2 = order[(i + 1) % 4]
                dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
                length = (dx * dx + dy * dy) ** 0.5
                ux, uy = (dx / length, dy / length) if length > 0 else (0.0, 0.0)
                p1e = QPointF(p1.x() - ux * EPS, p1.y() - uy * EPS) if not sides_on[neighbor_p1] else p1
                p2e = QPointF(p2.x() + ux * EPS, p2.y() + uy * EPS) if not sides_on[neighbor_p2] else p2
                wedge = QPainterPath()
                wedge.moveTo(p1e)
                wedge.lineTo(p2e)
                wedge.lineTo(center)
                wedge.closeSubpath()
                # Voir _paint_bordered_rect (meme technique/meme raison) :
                # coin ou le voisin est desactive -> unir avec le quadrant
                # COMPLET (pas juste la moitie triangulaire) pour ne pas
                # laisser un triangle de l'anneau non couvert (visible
                # surtout sur une bordure fine et un rectangle allonge).
                if not sides_on[neighbor_p1]:
                    wedge = wedge.united(_quadrant_path(p1, center))
                if not sides_on[neighbor_p2]:
                    wedge = wedge.united(_quadrant_path(p2, center))
                piece = ring.intersected(wedge)
                color = border_colors[side]
                color_paths[color] = color_paths[color].united(piece) if color in color_paths else piece
            for color, path in color_paths.items():
                p.setBrush(QColor(color))
                p.drawPath(path)
        if has_inner:
            # Bordure desactivee : le rayon doit quand meme s'appliquer au
            # remplissage, sur le rect COMPLET (pas d'inset ni de rayon
            # reduit puisqu'il n'y a pas de bordure a loger) — voir la
            # remarque de l'utilisateur, "le rayon des angles ne fonctionne
            # pas du tout quand les bordures sont desactivees" : cette
            # branche ne posait auparavant AUCUN clip, laissant le
            # remplissage carre quel que soit le rayon choisi.
            clip_radius = _radius_shrink(radius, 1) if any_on else radius
            if _radius_any(clip_radius):
                p.setClipPath(_rounded_rect_path(inner_rect, clip_radius))
            fill_layers(p, inner_rect)
        p.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        mid_y = self.height() // 2

        # -- rail : voir _paint_bordered — bordure INDEPENDANTE par cote
        # (voir la remarque de l'utilisateur, "4 couleurs comme la bordure
        # du selecteur") puis remplissage deja-parcouru/a-parcourir.
        track_h = _SLIDER_STYLE["track_h"]
        track_rect = QRect(0, mid_y - track_h // 2, self.width(), track_h)
        # track_h > 2 : rail trop fin pour loger meme 1px de bordure sur
        # chaque cote (voir l'ancien code, meme garde-fou) — tous les cotes
        # forces a "off" dans ce cas, quel que soit le reglage par cote.
        if track_h > 2:
            track_border_on = dict(_SLIDER_STYLE["track_border_enabled"])
        else:
            track_border_on = {k: False for k in ("top", "right", "bottom", "left")}

        def _fill_track(p, inner):
            p.fillRect(inner, QColor(_SLIDER_STYLE["track_empty"]))
            fill_w = round(self._pct() * inner.width())
            if fill_w > 0:
                p.fillRect(inner.x(), inner.y(), fill_w, inner.height(), QColor(_SLIDER_STYLE["track_fill"]))

        self._paint_bordered(
            p, track_rect, _SLIDER_STYLE["track_radius"], track_border_on,
            {side: _SLIDER_STYLE[f"track_border_{side}"] for side in ("top", "right", "bottom", "left")},
            _fill_track,
        )

        # -- selecteur : meme principe, une couleur de bordure par cote
        # (voir la remarque de l'utilisateur, "1 couleur pour chaque cote").
        thumb_w, thumb_h = _SLIDER_STYLE["thumb_w"], _SLIDER_STYLE["thumb_h"]
        fill_w = round(self._pct() * self.width())
        knob_x = max(0, min(self.width() - thumb_w, fill_w - thumb_w // 2))
        thumb_rect = QRect(knob_x, mid_y - thumb_h // 2, thumb_w, thumb_h)
        thumb_border_on = _SLIDER_STYLE["thumb_border_enabled"]

        def _fill_thumb(p, inner):
            p.fillRect(inner, QColor(_SLIDER_STYLE["thumb_color"]))

        self._paint_bordered(
            p, thumb_rect, _SLIDER_STYLE["thumb_radius"], thumb_border_on,
            {side: _SLIDER_STYLE[f"thumb_border_{side}"] for side in ("top", "right", "bottom", "left")},
            _fill_thumb,
        )
        p.end()

class _SliderField(QWidget):
    """Slider + boite de lecture/saisie numerique a droite (unite comprise)."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, unit: str = "px",
                 slider_width: int = 170, box_width: int = 68, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.slider = _MiniSlider(minimum, maximum, value, slider_width)
        self._radius = _input_radius()
        _register_input(self)
        self.box = box = QWidget()
        box.setObjectName("SliderValueBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setFixedSize(box_width, 25)
        self._refresh_box_style()
        box_l = QHBoxLayout(box)
        box_l.setContentsMargins(7, 0, 7, 0)
        box_l.setSpacing(4)
        self._min, self._max = minimum, maximum
        self.value_label = QLineEdit(str(value))
        self.value_label.setFont(_qfont(11, 400, mono=True))
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setFrame(False)
        self.value_label.setValidator(QIntValidator(self.value_label))
        self.value_label.setStyleSheet(f"background: transparent; border: none; padding: 0; color: {M['value_text']};")
        self.value_label.editingFinished.connect(self._on_text_edited)
        unit_label = QLabel(unit)
        _set_text_role(unit_label, "unit")
        box_l.addWidget(self.value_label, 1)
        box_l.addWidget(unit_label)
        layout.addWidget(self.slider)
        layout.addWidget(box)
        self.slider.valueChanged.connect(self._on_change)

    def _refresh_box_style(self):
        self.box.setStyleSheet(
            f"#SliderValueBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; }}"
        )

    def setRadius(self, radius: int):
        """Suit le slider Geometrie > Zones de saisie > Coins arrondis —
        cette boite a le meme habillage qu'une zone de saisie normale (voir
        SettingsWindow._apply_dropdown_radius, qui l'appelle sur TOUS les
        _SliderField de la fenetre, elle-meme comprise)."""
        self._radius = max(0, int(radius))
        self._refresh_box_style()

    def _on_change(self, value: int):
        self.value_label.setText(str(value))
        self.valueChanged.emit(value)

    def _on_text_edited(self):
        text = self.value_label.text().strip()
        try:
            value = max(self._min, min(self._max, int(text)))
        except ValueError:
            value = self.slider.value()
        self.slider.setValue(value)
        self.value_label.setText(str(self.slider.value()))

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int):
        self.slider.setValue(value)

class _RatioSliderField(QWidget):
    """Comme _SliderField, mais pour un ratio largeur/hauteur affiche
    "1/<valeur decimale>" (voir Colonnes > Lignes > Apercu > Ratio, remarque
    de l'utilisateur : "avant l'invite place le texte '1/' ... dans
    l'invite on entre la valeur de largeur (par exemple 2.35) ce qui fait un
    ratio de 1 pour 2.35"). Stockage INCHANGE (pourcentage entier, 100 = 1.0,
    voir item_image_ratio) — seul l'AFFICHAGE devient decimal (value_pct/100,
    2 decimales), la granularite du slider (pas de 1%) suffit deja pour 2
    decimales."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value_pct: int,
                 slider_width: int = 170, box_width: int = 68, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        prefix = QLabel("1/")
        _set_text_role(prefix, "unit_large")
        layout.addWidget(prefix)
        self.slider = _MiniSlider(minimum, maximum, value_pct, slider_width)
        self._radius = _input_radius()
        _register_input(self)
        self._min, self._max = minimum, maximum
        self.box = box = QWidget()
        box.setObjectName("SliderValueBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setFixedSize(box_width, 25)
        self._refresh_box_style()
        box_l = QHBoxLayout(box)
        box_l.setContentsMargins(7, 0, 7, 0)
        box_l.setSpacing(4)
        self.value_label = QLineEdit(self._format(value_pct))
        self.value_label.setFont(_qfont(11, 400, mono=True))
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setFrame(False)
        self.value_label.setValidator(QDoubleValidator(0.01, 99.99, 2, self.value_label))
        self.value_label.setStyleSheet(f"background: transparent; border: none; padding: 0; color: {M['value_text']};")
        self.value_label.editingFinished.connect(self._on_text_edited)
        box_l.addWidget(self.value_label, 1)
        layout.addWidget(self.slider)
        layout.addWidget(box)
        self.slider.valueChanged.connect(self._on_change)

    @staticmethod
    def _format(value_pct: int) -> str:
        return f"{value_pct / 100:.2f}"

    def _refresh_box_style(self):
        self.box.setStyleSheet(
            f"#SliderValueBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; }}"
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_box_style()

    def _on_change(self, value_pct: int):
        self.value_label.setText(self._format(value_pct))
        self.valueChanged.emit(value_pct)

    def _on_text_edited(self):
        text = self.value_label.text().strip().replace(",", ".")
        try:
            value_pct = max(self._min, min(self._max, round(float(text) * 100)))
        except ValueError:
            value_pct = self.slider.value()
        self.slider.setValue(value_pct)
        self.value_label.setText(self._format(self.slider.value()))

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value_pct: int):
        self.slider.setValue(value_pct)
        self.value_label.setText(self._format(value_pct))

class _SteppedSliderField(QWidget):
    """Slider a positions FIXES (voir _MiniSlider, deja entier par nature —
    aucune valeur intermediaire possible) affichant un LIBELLE a cote plutot
    qu'un nombre dans une boite de saisie — utilise pour Lissage (voir la
    remarque de l'utilisateur : "slider 3 points (crante)" plutot qu'un
    menu deroulant, puisque le lissage n'a de toute facon que ces quelques
    niveaux reels cote Qt/Windows, voir app_style.font()). PAS de boite
    "zone de saisie" (fond/bordure) autour du libelle — voir la remarque de
    l'utilisateur, capture a l'appui : ce texte n'est ni cliquable ni
    editable, l'habiller comme un champ suggerait le contraire ; un simple
    texte informatif, comme la colonne Apercu du meme tableau."""

    changed = Signal(int)

    def __init__(self, labels: list[str], value: int, slider_width: int = 170, box_width: int = 90, parent=None):
        super().__init__(parent)
        self._labels = labels
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # 18 (pas 10 comme _SliderField) : slider tres court (20px, voir la
        # remarque de l'utilisateur) donc slider+libelle se retrouvaient
        # colles l'un a l'autre avec le meme espacement qu'un _SliderField
        # normal (dont le slider fait 5x plus large) — voir la remarque de
        # l'utilisateur, capture a l'appui ("zone rognee, infos entassees").
        layout.setSpacing(18)
        self.slider = _MiniSlider(0, len(labels) - 1, value, slider_width)
        self.value_label = QLabel(labels[value])
        _set_text_role(self.value_label, "value_muted")
        self.value_label.setFixedWidth(box_width)
        layout.addWidget(self.slider)
        layout.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._on_change)

    def _on_change(self, value: int):
        self.value_label.setText(self._labels[value])
        self.changed.emit(value)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int):
        value = max(0, min(len(self._labels) - 1, value))
        self.slider.setValue(value)
        self.value_label.setText(self._labels[value])

_ITEM_FONT_SMOOTHING_STEPS = ("none", "previous", "current")

class _OverrideSmoothingField(QWidget):
    """Slider Lissage a 3 crans (MEME widget/mecanique que Polices
    principales > Lissage, voir _SteppedSliderField/_SMOOTHING_STEPS) —
    pour Colonnes > Texte > Lissage. Le toggle "Forcer" a ete SUPPRIME (voir
    la remarque de l'utilisateur, "il y a deux toggle pour le lissage,
    supprime le premier qui ne sert a rien, et ne garde que celui a 3
    positions") : le lissage choisi ici s'applique desormais TOUJOURS
    (isChecked() renvoie donc toujours True, conserve seulement pour ne pas
    casser les appelants qui persistent encore une cle "..._enabled").
    Libelles des 3 crans : "0"/"1"/"2" (pas les noms descriptifs Fin/Moyen/
    Brut) — voir la remarque de l'utilisateur. Titre "niveau de lissage"
    centre AU-DESSUS du slider (voir la remarque de l'utilisateur, "place
    un nouveau texte juste au dessus du toggle bien centre")."""

    changed = Signal()

    def __init__(self, enabled: bool, smoothing: str, parent=None, show_title: bool = True):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        if show_title:   # sans titre quand une entete de colonne le porte deja
            title = QLabel("niveau de lissage")
            _set_text_role(title, "mini_label")
            title.setAlignment(Qt.AlignHCenter)
            outer.addWidget(title)
        step = _ITEM_FONT_SMOOTHING_STEPS.index(smoothing) if smoothing in _ITEM_FONT_SMOOTHING_STEPS else 2
        self.slider = _SteppedSliderField(["0", "1", "2"], step, slider_width=20, box_width=24)
        outer.addWidget(self.slider, 0, Qt.AlignHCenter)
        self.slider.changed.connect(lambda _s: self.changed.emit())

    def isChecked(self) -> bool:
        return True

    def smoothingValue(self) -> str:
        return _ITEM_FONT_SMOOTHING_STEPS[self.slider.value()]

    def setValue(self, enabled: bool, smoothing: str):
        step = _ITEM_FONT_SMOOTHING_STEPS.index(smoothing) if smoothing in _ITEM_FONT_SMOOTHING_STEPS else 2
        self.slider.setValue(step)

class _RowBorderField(QWidget):
    """Toggle + couleur + epaisseur du filet ENTRE les lignes d'une colonne,
    TOUS LES TROIS DANS LA MEME ligne (meme principe que
    _OverrideSmoothingField juste au-dessus, toggle + champ) — voir la
    remarque de l'utilisateur, "rassemble bordure couleur et epaisseur
    dans une seule ligne" (au lieu de 3 lignes separees). Toggle SANS
    libelle "actif"/"sans" (voir la remarque de l'utilisateur, "pas besoin
    de mettre actif") ; couleur et epaisseur se grisent (voir _set_dimmed)
    quand il est desactive (voir la meme remarque, "grise les autres
    options quand le toggle est desactive"). _AppOrCustomColorField (PAS
    _ColorField), meme raison que item_color_field : choix entre couleurs
    soft de l'appli et couleur personnalisee."""

    changed = Signal()

    def __init__(self, enabled: bool, color: str, thickness: int, colors: dict,
                 thickness_range: tuple[int, int] = (0, 8), title: str = "Couleur de bordure", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.toggle = _Toggle(bool(enabled), style_override="toggle1", show_label=False)
        layout.addWidget(self.toggle)
        self.color_field = _AppOrCustomColorField(color, colors, swatch_size=24, title=title)
        layout.addWidget(self.color_field)
        self.thickness_field = _SliderField(
            thickness_range[0], thickness_range[1], int(thickness), slider_width=140, box_width=54)
        layout.addWidget(self.thickness_field)
        layout.addStretch(1)
        self.toggle.toggled.connect(self._on_toggle)
        self.color_field.changed.connect(lambda _v: self.changed.emit())
        self.thickness_field.valueChanged.connect(lambda _v: self.changed.emit())
        self._refresh_enabled()

    def _on_toggle(self, _checked: bool):
        self._refresh_enabled()
        self.changed.emit()

    def _refresh_enabled(self):
        on = self.toggle.isChecked()
        _set_dimmed(self.color_field, not on)
        _set_dimmed(self.thickness_field, not on)

    def enabledValue(self) -> bool:
        return self.toggle.isChecked()

    def colorValue(self) -> str:
        return self.color_field.value()

    def thicknessValue(self) -> int:
        return self.thickness_field.value()

    def setValue(self, enabled: bool, color: str, thickness: int):
        self.toggle.setChecked(bool(enabled))
        self.color_field.setValue(color)
        self.thickness_field.setValue(int(thickness))
        self._refresh_enabled()

    def refresh_colors(self, colors: dict):
        self.color_field.refresh_colors(colors)

class _SelectField(QPushButton):
    """Bouton "select" (valeur + chevron), ouvre un QMenu. Cette boite a
    exactement le meme habillage (fond/bordure) qu'une zone de saisie
    normale (QLineEdit) \u2014 voir setRadius : elle suit donc en direct le
    reglage Geometrie > Zones de saisie > Coins arrondis, au meme titre que
    les vrais champs de texte (voir SettingsWindow._apply_field_radius)."""

    changed = Signal(str)

    def __init__(self, options: list[str], current: str, width: int = 200, parent=None):
        super().__init__(parent)
        self._options = options
        self._value = current if current in options else options[0]
        self._radius = _input_radius()
        _register_input(self)
        self.setFixedSize(width, 25)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(_qfont(11, 400))
        self._refresh_style()
        self.clicked.connect(self._open_menu)
        self._sync_text()

    def _refresh_style(self):
        self.setStyleSheet(
            f"QPushButton {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; "
            f"color: {M['value_fg']}; text-align: left; padding: 0 8px; }}"
            f"QPushButton:hover {{ border-color: {M['field_border_hover']}; }}"
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_style()

    def _sync_text(self):
        self.setText(self._value + "  \u25be")

    def _open_menu(self):
        menu = QMenu(self)
        menu.setFont(_qfont(11, 400))
        menu.setStyleSheet(
            f"QMenu {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 5px 16px; color: {M['value_fg']}; }}"
            f"QMenu::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
        )
        for opt in self._options:
            action = menu.addAction(opt)
            action.triggered.connect(lambda _checked=False, o=opt: self._select(o))
        menu.exec(self.mapToGlobal(QPoint(0, self.height())))

    def _select(self, opt: str):
        if opt != self._value:
            self._value = opt
            self._sync_text()
            self.changed.emit(opt)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        if value in self._options and value != self._value:
            self._value = value
            self._sync_text()

    def setOptions(self, options: list[str]):
        """Remplace la liste d'options EN PLACE (voir _open_menu, qui lit
        `self._options` a chaque ouverture — pas besoin de reconstruire le
        widget) : utilise par SettingsWindow._refresh_default_preset_
        options pour que "Preset par defaut" reste a jour des qu'un preset
        est cree/supprime/renomme, MEME fenetre encore ouverte — voir la
        remarque de l'utilisateur sur la refonte des presets."""
        self._options = list(options)
        if self._value not in self._options and self._options:
            self._value = self._options[0]
            self._sync_text()

class _FontSelectField(_SelectField):
    """Variante de _SelectField pour choisir une police : vraie liste
    deroulante (scroll natif, molette comprise) ou chaque nom de police est
    rendu DANS cette police — voir la meme classe dans l'ancienne fenetre,
    logique inchangee."""

    def __init__(self, options: list[str], current: str, width: int = 200,
                 auto_label: str | None = None, parent=None):
        self._auto_label = auto_label
        super().__init__(options, current, width, parent)

    def _display_label(self, opt: str) -> str:
        if opt == "Systeme" and self._auto_label:
            return self._auto_label
        return opt

    def _sync_text(self):
        self.setText(self._display_label(self._value) + "  \u25be")

    def _open_menu(self):
        popup = QWidget(self, Qt.Popup)
        popup.setObjectName("FontPopup")
        popup.setAttribute(Qt.WA_StyledBackground, True)
        popup.setStyleSheet(
            f"#FontPopup {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; }}"
        )
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        listw = QListWidget(popup)
        listw.setFrameShape(QFrame.NoFrame)
        listw.setUniformItemSizes(True)
        listw.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            f"QListWidget::item {{ padding: 6px 12px; color: {M['value_fg']}; }}"
            f"QListWidget::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
            f"QListWidget::item:hover:!selected {{ background: {M['close_hover_bg']}; }}"
        )
        current_item = None
        for opt in self._options:
            if opt == self._auto_label and opt != self._value:
                continue
            item = QListWidgetItem(self._display_label(opt))
            item.setData(Qt.UserRole, opt)
            item.setFont(_qfont(12, 400) if opt == "Systeme" else QFont(opt, 12))
            listw.addItem(item)
            if opt == self._value:
                current_item = item
        listw.itemClicked.connect(lambda item: self._pick_from_popup(item.data(Qt.UserRole), popup))

        layout.addWidget(listw)
        popup.setFixedWidth(max(self.width(), 240))
        popup.setFixedHeight(320)
        popup.move(self.mapToGlobal(QPoint(0, self.height())))
        popup.show()
        if current_item is not None:
            listw.setCurrentItem(current_item)
            listw.scrollToItem(current_item)
        listw.setFocus()

    def _pick_from_popup(self, opt: str, popup: QWidget):
        popup.close()
        self._select(opt)

class _DualFontSelectField(QWidget):
    """Colonnes > Texte > Police : DEUX listes deroulantes cote a cote au
    lieu d'une seule liste combinee — "polices du soft" (les 5 roles DEJA
    regles dans Polices principales, voir ITEM_FONT_ROLE_LABELS) et
    "polices systeme" (toutes les polices installees, + "Systeme" = auto,
    voir _FontSelectField) — chacune precedee d'un toggle EXCLUSIF (une
    seule active a la fois, l'autre liste grisee, voir _set_dimmed) — voir
    la remarque de l'utilisateur, "je veux avoir le choix entre les
    polices du soft et les polices systeme ... avec devant chacune un
    toggle pour le choix. La liste non selectionnee sera grisee".

    Valeur (voir value()/setValue()) INCHANGEE par rapport a l'ancienne
    liste unique (retro-compatible avec les presets existants) : le
    libelle "police du soft" choisi tel quel, OU "Systeme"/un nom de
    police reel pour le cote systeme — c'est SEULEMENT la PRESENTATION qui
    change ici, pas le format stocke."""

    changed = Signal()

    def __init__(self, value: str, width: int = 150, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # MEME systeme que le gabarit "couleur" compact (voir
        # _CompactAppOrCustomColorField et la remarque de l'utilisateur,
        # "c'est possible de faire la mm chose pour le choix des polices ?")
        # : un toggle "app"/"sys" de PART ET D'AUTRE, libelle CENTRE
        # au-dessus de chacun, et UN SEUL menu deroulant central (au lieu de
        # 2 cote a cote, l'un grise) dont la liste d'options BASCULE selon
        # le mode actif (voir _refresh_options) — memes valeurs stockees
        # qu'avant (retro-compatible).
        self._soft_options = list(ITEM_FONT_ROLE_LABELS.values())
        self._system_options = ["Systeme"] + installed_font_families()
        is_soft = value in self._soft_options

        # "app" a GAUCHE de son toggle, tres rapproches.
        app_box = QWidget()
        app_box.setStyleSheet("background: transparent;")
        app_box_l = QHBoxLayout(app_box)
        app_box_l.setContentsMargins(0, 0, 0, 0)
        app_box_l.setSpacing(3)
        app_label = QLabel("app")
        _set_text_role(app_label, "mini_label")
        app_label.setContentsMargins(0, 0, 0, 3)   # remonte le texte : aligne avec le centre du toggle
        app_box_l.addWidget(app_label)
        self.soft_toggle = _Toggle(is_soft, show_label=False)
        app_box_l.addWidget(self.soft_toggle)
        layout.addWidget(app_box)

        self.field = _FontSelectField(
            self._soft_options if is_soft else self._system_options,
            value if is_soft else (value or "Systeme"), width=width, auto_label="Systeme")
        layout.addWidget(self.field)

        # "sys" a DROITE de son toggle, tres rapproches.
        sys_box = QWidget()
        sys_box.setStyleSheet("background: transparent;")
        sys_box_l = QHBoxLayout(sys_box)
        sys_box_l.setContentsMargins(0, 0, 0, 0)
        sys_box_l.setSpacing(3)
        self.system_toggle = _Toggle(not is_soft, show_label=False)
        sys_box_l.addWidget(self.system_toggle)
        sys_label = QLabel("sys")
        _set_text_role(sys_label, "mini_label")
        sys_label.setContentsMargins(0, 0, 0, 3)   # remonte le texte : aligne avec le centre du toggle
        sys_box_l.addWidget(sys_label)
        layout.addWidget(sys_box)

        # Derniere valeur connue de CHAQUE cote (voir _refresh_options) :
        # rebasculer vers "app" doit retrouver le dernier role choisi, pas
        # toujours retomber sur le 1er de la liste.
        self._last_soft = value if is_soft else self._soft_options[0]
        self._last_system = value if not is_soft else "Systeme"

        self.soft_toggle.toggled.connect(self._on_soft_toggled)
        self.system_toggle.toggled.connect(self._on_system_toggled)
        self.field.changed.connect(self._on_field_changed)

    def _on_field_changed(self, value: str):
        if self.soft_toggle.isChecked():
            self._last_soft = value
        else:
            self._last_system = value
        self.changed.emit()

    def _refresh_options(self):
        if self.soft_toggle.isChecked():
            self.field.setOptions(self._soft_options)
            self.field.setValue(self._last_soft)
        else:
            self.field.setOptions(self._system_options)
            self.field.setValue(self._last_system)

    def _on_soft_toggled(self, checked: bool):
        if checked:
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(False)
            self.system_toggle.blockSignals(False)
        elif not self.system_toggle.isChecked():
            # Au moins l'un des 2 doit rester actif — sans ca, decocher le
            # seul toggle actif ne selectionnerait plus AUCUNE police.
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(True)
            self.system_toggle.blockSignals(False)
        self._refresh_options()
        self.changed.emit()

    def _on_system_toggled(self, checked: bool):
        if checked:
            self.soft_toggle.blockSignals(True)
            self.soft_toggle.setChecked(False)
            self.soft_toggle.blockSignals(False)
        elif not self.soft_toggle.isChecked():
            self.soft_toggle.blockSignals(True)
            self.soft_toggle.setChecked(True)
            self.soft_toggle.blockSignals(False)
        self._refresh_options()
        self.changed.emit()

    def value(self) -> str:
        return self.field.value()

    def setValue(self, value: str):
        is_soft = value in self._soft_options
        for toggle, checked in ((self.soft_toggle, is_soft), (self.system_toggle, not is_soft)):
            toggle.blockSignals(True)
            toggle.setChecked(checked)
            toggle.blockSignals(False)
        if is_soft:
            self._last_soft = value
        else:
            self._last_system = value or "Systeme"
        self._refresh_options()

    def setRadius(self, radius: int):
        self.field.setRadius(radius)

# Style visuel de TOUS les _Toggle de cette fenetre (voir Toggles > Style,
# SettingsWindow._section_toggles) — "toggle1" (cadre RECTANGLE, coche
# calee en haut a droite a distance egale du bord en horizontale qu'en
# verticale) ou "toggle2" (cadre CARRE, coche PARFAITEMENT centree) — voir
# la remarque de l'utilisateur, capture annotee a l'appui (mockup corrige
# des 2 styles, "je me suis trompe, j'ai modifie les types"). Chaque style
# a son propre jeu de reglages COMPLET (_TOGGLE1_STYLE/_TOGGLE2_STYLE,
# toujours tenus a jour tous les deux — seul _TOGGLE_STYLE choisit lequel
# est REELLEMENT dessine) ; _TOGGLE_STYLE change une fois, s'applique a
# tous les toggles deja construits (voir SettingsWindow._on_toggle_style_
# changed, qui rappelle .apply_style() sur chacun), meme principe que
# _SLIDER_STYLE.
_TOGGLE_STYLE = "toggle1"

_ALL_SIDES_ON = {"top": True, "right": True, "bottom": True, "left": True}

_TOGGLE_SHAPE_DEFAULTS = {
    "outer_w": 29, "outer_h": 14,
    # dict {cote: bool}, pas un bool unique (voir _coerce_side_enabled/la
    # remarque de l'utilisateur, "un toggle par cote") — reecrase de toute
    # facon par _sync_toggle_shape_style avant le 1er rendu, valeur de
    # depart seulement.
    "outer_border_enabled": dict(_ALL_SIDES_ON), "outer_border_thickness": 1,
    "outer_border_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "outer_border_top": "#2e343a", "outer_border_right": "#2e343a",
    "outer_border_bottom": "#2e343a", "outer_border_left": "#2e343a",
    "outer_bg": "#141618",
    # Fond a l'etat ON (voir _paint_toggle_shape, qui interpole entre
    # outer_bg -> outer_bg_on selon `progress` pendant l'animation) — voir
    # la remarque de l'utilisateur, "dans les toggles, j'aimerais que la
    # couleur de fond differe entre l'etat on et l'etat off".
    "outer_bg_on": "#3f6f9f",
    "coche_w": 11, "coche_h": 11,
    # Marge (px, "x" sur le schema de l'utilisateur) entre le bord du cadre
    # et la coche — reglable (voir Toggles > Coche > Distance du bord),
    # PAR STYLE (chacun le sien). Sert de marge HAUTE et BASSE (voir
    # _sync_toggle_shape_style, qui EN DEDUIT coche_h — la hauteur de la
    # coche est LIEE a celle du cadre, voir la remarque de l'utilisateur)
    # et, pour "toggle1", de marge DROITE aussi (voir _paint_toggle_shape).
    "coche_margin": 4,
    "coche_border_enabled": dict(_ALL_SIDES_ON), "coche_border_thickness": 1,
    "coche_border_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "coche_border_top": "#2e343a", "coche_border_right": "#2e343a",
    "coche_border_bottom": "#2e343a", "coche_border_left": "#2e343a",
    "coche_color": "#3f6f9f",
    # Habillage de la coche : rien, un texte ou une icone dessines DANS la coche.
    "skin": "none", "text": "",
    "text_font": {"family": "", "bold": True, "italic": False, "size": 10, "smoothing": "current",
                  "color": "#ffffff"},
    "icon": "", "icon_color": "#ffffff",
}

_TOGGLE1_STYLE = dict(_TOGGLE_SHAPE_DEFAULTS)

_TOGGLE2_STYLE = dict(_TOGGLE_SHAPE_DEFAULTS)

_TOGGLE2_STYLE.update({"outer_w": 22, "outer_h": 22})

# Registre des styles : toggle1, toggle2 et ceux que l'utilisateur ajoute (toggle3...).
_TOGGLE_STYLES: dict[str, dict] = {"toggle1": _TOGGLE1_STYLE, "toggle2": _TOGGLE2_STYLE}
_TOGGLE_STYLE_NAMES: dict[str, str] = {"toggle1": "Toggle 1", "toggle2": "Toggle 2"}

def _toggle_style_dict(key: str) -> dict:
    """Reglages d'un style (cree a la demande, a partir des valeurs par defaut)."""
    style = _TOGGLE_STYLES.get(key)
    if style is None:
        import copy
        style = _TOGGLE_STYLES[key] = copy.deepcopy(_TOGGLE_SHAPE_DEFAULTS)
    return style

def _active_toggle_style() -> dict:
    return _toggle_style_dict(_TOGGLE_STYLE)

def _sync_toggle_shape_style(target: dict, settings: dict, prefix: str) -> None:
    """Recopie les reglages `{prefix}_*` de `settings` dans `target`
    (_TOGGLE1_STYLE ou _TOGGLE2_STYLE) — voir _sync_toggle_style, qui
    l'appelle pour chacun des 2 styles a chaque changement."""
    target["outer_w"] = max(4, int(settings.get(f"{prefix}_outer_width", target["outer_w"])))
    target["outer_h"] = max(4, int(settings.get(f"{prefix}_outer_height", target["outer_h"])))
    target["outer_border_enabled"] = _coerce_side_enabled(settings.get(f"{prefix}_outer_border_enabled", True))
    target["outer_border_thickness"] = max(0, int(settings.get(f"{prefix}_outer_border_thickness", 1)))
    target["outer_border_radius"] = _coerce_corner_radius(settings.get(f"{prefix}_outer_border_radius", 0))
    # _resolve_color_value : outer_border/coche_border (voir _AppOrCustom
    # ColorField, bordures Toggles/Sliders) peuvent contenir un hex direct
    # OU une reference "@<slot>" a une pastille semantique — cette derniere
    # doit etre resolue en hex REEL avant de finir ici, seule forme que
    # _paint_bordered_rect (QColor(...)) sait interpreter.
    colors = settings.get("colors") or {}
    outer_border = settings.get(f"{prefix}_outer_border") or {}
    for side in ("top", "right", "bottom", "left"):
        target[f"outer_border_{side}"] = _resolve_color_value(
            outer_border.get(side, target[f"outer_border_{side}"]), colors)
    target["outer_bg"] = settings.get(f"{prefix}_outer_bg", target["outer_bg"])
    target["outer_bg_on"] = settings.get(f"{prefix}_outer_bg_on", target["outer_bg_on"])
    target["coche_w"] = max(2, int(settings.get(f"{prefix}_coche_width", target["coche_w"])))
    target["coche_margin"] = max(0, int(settings.get(f"{prefix}_coche_margin", target["coche_margin"])))
    # coche_h LIEE a outer_h (voir la remarque de l'utilisateur), pas un
    # reglage independant — marge haute ET basse egales a x (coche_margin),
    # ce qui centre aussi verticalement la coche (equivalent, voir
    # _paint_toggle_shape).
    target["coche_h"] = max(2, target["outer_h"] - 2 * target["coche_margin"])
    target["coche_border_enabled"] = _coerce_side_enabled(settings.get(f"{prefix}_coche_border_enabled", True))
    target["coche_border_thickness"] = max(0, int(settings.get(f"{prefix}_coche_border_thickness", 1)))
    target["coche_border_radius"] = _coerce_corner_radius(settings.get(f"{prefix}_coche_border_radius", 0))
    coche_border = settings.get(f"{prefix}_coche_border") or {}
    for side in ("top", "right", "bottom", "left"):
        target[f"coche_border_{side}"] = _resolve_color_value(
            coche_border.get(side, target[f"coche_border_{side}"]), colors)
    target["coche_color"] = settings.get(f"{prefix}_coche_color", target["coche_color"])
    target["skin"] = settings.get(f"{prefix}_coche_skin", "none")
    target["text"] = str(settings.get(f"{prefix}_coche_text", ""))
    smoothing_on = bool(settings.get(f"{prefix}_coche_text_font_smoothing_enabled", False))
    target["text_font"] = {
        "family": settings.get(f"{prefix}_coche_text_font_family", "") or "",
        "bold": bool(settings.get(f"{prefix}_coche_text_font_bold", True)),
        "italic": bool(settings.get(f"{prefix}_coche_text_font_italic", False)),
        "size": max(4, int(settings.get(f"{prefix}_coche_text_font_size", 10))),
        "smoothing": settings.get(f"{prefix}_coche_text_font_smoothing", "current") if smoothing_on else "current",
        "color": _resolve_color_value(settings.get(f"{prefix}_coche_text_font_color", "#ffffff"), colors),
    }
    target["icon"] = str(settings.get(f"{prefix}_coche_icon", "") or "")
    target["icon_color"] = _resolve_color_value(settings.get(f"{prefix}_coche_icon_color", "#ffffff"), colors)

def _sync_toggle_style(settings: dict) -> None:
    global _TOGGLE_STYLE
    for custom in settings.get("toggle_custom_styles") or []:
        _toggle_style_dict(custom["key"])
        _TOGGLE_STYLE_NAMES[custom["key"]] = custom.get("name") or custom["key"]
    style = settings.get("toggle_style", "toggle1")
    _TOGGLE_STYLE = style if style in _TOGGLE_STYLES else "toggle1"
    for key, target in list(_TOGGLE_STYLES.items()):
        _sync_toggle_shape_style(target, settings, key)

def _radius_dict(radius) -> dict:
    """Normalise `radius` (int uniforme OU dict {"top_left": int, ...}) en
    dict complet sur les 4 coins — voir _rounded_rect_path/_paint_bordered_
    rect et la remarque de l'utilisateur, "si deux colonnes sont cote a
    cote ... le rayon contre l'autre colonne doit etre a zero" (rayon
    INDEPENDANT par coin, voir _ColumnPreview.paintEvent)."""
    if isinstance(radius, dict):
        return {k: max(0, int(radius.get(k, 0))) for k in _CORNERS}
    r = max(0, int(radius))
    return {k: r for k in _CORNERS}

def _radius_shrink(radius, amount: int):
    """`radius` (int ou dict) retranche de `amount` sur chaque coin, jamais
    sous 0 — repasse a un int simple si les 4 coins retombent egaux (evite
    de trainer un dict la ou un simple radius suffit)."""
    shrunk = {k: max(0, v - amount) for k, v in _radius_dict(radius).items()}
    values = set(shrunk.values())
    return values.pop() if len(values) == 1 else shrunk

def _radius_any(radius) -> bool:
    return any(v > 0 for v in _radius_dict(radius).values())

def _rounded_rect_path(rect: QRect, radius) -> QPainterPath:
    """Chemin rectangle arrondi — `radius` : int (rayon UNIFORME, retro-
    compatible) OU dict {"top_left": int, "top_right": int, "bottom_right":
    int, "bottom_left": int} pour un rayon INDEPENDANT par coin (voir
    _radius_dict/la remarque de l'utilisateur ci-dessus)."""
    if isinstance(radius, dict):
        d = _radius_dict(radius)
        if len(set(d.values())) == 1:
            radius = next(iter(d.values()))
        else:
            r = QRectF(rect)
            tl = min(d["top_left"], r.width() / 2, r.height() / 2)
            tr = min(d["top_right"], r.width() / 2, r.height() / 2)
            br = min(d["bottom_right"], r.width() / 2, r.height() / 2)
            bl = min(d["bottom_left"], r.width() / 2, r.height() / 2)
            path = QPainterPath()
            path.moveTo(r.left() + tl, r.top())
            path.lineTo(r.right() - tr, r.top())
            if tr > 0:
                path.arcTo(r.right() - 2 * tr, r.top(), 2 * tr, 2 * tr, 90, -90)
            path.lineTo(r.right(), r.bottom() - br)
            if br > 0:
                path.arcTo(r.right() - 2 * br, r.bottom() - 2 * br, 2 * br, 2 * br, 0, -90)
            path.lineTo(r.left() + bl, r.bottom())
            if bl > 0:
                path.arcTo(r.left(), r.bottom() - 2 * bl, 2 * bl, 2 * bl, -90, -90)
            path.lineTo(r.left(), r.top() + tl)
            if tl > 0:
                path.arcTo(r.left(), r.top(), 2 * tl, 2 * tl, 180, -90)
            path.closeSubpath()
            return path
    path = QPainterPath()
    if radius > 0:
        path.addRoundedRect(QRectF(rect), radius, radius)
    else:
        path.addRect(QRectF(rect))
    return path

def _quadrant_path(corner: QPointF, center: QPointF) -> QPainterPath:
    """Rectangle AXE-ALIGNE plein entre `corner` (un coin du rect) et
    `center` (son centre) — le quadrant COMPLET de ce coin, pas juste sa
    moitie triangulaire (voir _paint_bordered_rect/_MiniSlider._paint_
    bordered, la diagonale-vers-le-centre d'un wedge ne couvre QUE sa
    moitie du carre de coin ; quand le cote voisin est desactive, cette
    moitie manquante de l'anneau ne revient a personne)."""
    path = QPainterPath()
    path.addRect(QRectF(corner, center).normalized())
    return path

_RING_PIXMAP_CACHE: dict[tuple, tuple[QPixmap, int]] = {}

_RING_PIXMAP_CACHE_MAX = 256

def _ring_pixmap(width: int, height: int, radius, thickness: int, color: str) -> tuple[QPixmap, int]:
    """Anneau (bordure uniforme, voir _paint_bordered_rect, cas RAPIDE)
    sur-echantillonne 8x puis mis a l'echelle, mis en CACHE par (taille,
    rayon, epaisseur, couleur) — sa geometrie ne depend QUE de ca, jamais
    de la position a l'ecran : memes reglages -> MEME pixmap, reutilise
    tel quel sur toutes les lignes d'une liste ET sur chaque frame
    (~60fps) d'une animation de toggle, au lieu d'etre reconstruit (2
    QPainter + 1 QPixmap alloues) a CHAQUE paintEvent — voir la remarque
    de l'utilisateur, "il y a des ralentissements dans les animations,
    optimise un maximum"."""
    radius_key = tuple(sorted(radius.items())) if isinstance(radius, dict) else radius
    key = (width, height, radius_key, thickness, color)
    cached = _RING_PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_RING_PIXMAP_CACHE) >= _RING_PIXMAP_CACHE_MAX:
        _RING_PIXMAP_CACHE.clear()
    ss = 8
    pad = max(1, int(thickness))
    rect = QRect(0, 0, width, height)
    inner_rect = QRect(thickness, thickness, width - 2 * thickness, height - 2 * thickness)
    has_inner = inner_rect.width() > 0 and inner_rect.height() > 0
    pixmap = QPixmap(max(1, round((width + 2 * pad) * ss)), max(1, round((height + 2 * pad) * ss)))
    pixmap.fill(Qt.transparent)
    sp = QPainter(pixmap)
    sp.setRenderHint(QPainter.Antialiasing, True)
    sp.scale(ss, ss)
    sp.translate(pad, pad)
    outer = _rounded_rect_path(rect, radius)
    inner = _rounded_rect_path(inner_rect, _radius_shrink(radius, thickness)) if has_inner else QPainterPath()
    ring_shape = outer.subtracted(inner) if has_inner else outer
    sp.setPen(Qt.NoPen)
    sp.setBrush(QColor(color))
    sp.drawPath(ring_shape)
    sp.end()
    pixmap.setDevicePixelRatio(ss)
    result = (pixmap, pad)
    _RING_PIXMAP_CACHE[key] = result
    return result

def _paint_bordered_rect(p: QPainter, rect: QRect, radius: int, border_on, thickness: int,
                          border_colors: dict, fill_color: str | None):
    """Peint un rectangle avec bordure MITREE par cote (voir _MiniSlider.
    _paint_bordered, meme technique — diagonales depuis le centre vers
    chaque coin, continue quel que soit le rayon) generalisee ici a une
    EPAISSEUR de bordure variable (les sliders restent a 1px fixe, les
    toggles l'exposent en reglage, voir Toggles > Cadre/Coche > Epaisseur
    de bordure) + remplissage (`fill_color`, ou aucun si None — la coche a
    l'etat OFF, "creuse").

    `border_on` : bool (tous les cotes pareil, retro-compatible) OU dict
    {"top": bool, ...} — un cote DESACTIVE (voir _SideColorsField, la
    remarque de l'utilisateur "au lieu d'avoir un seul toggle pour activer
    les bordures, je veux un toggle par cote") ne consomme plus d'epaisseur
    de CE cote : le remplissage s'etend alors jusqu'a ce bord, tout en
    restant en retrait des autres cotes toujours actifs (inset ASYMETRIQUE,
    pas juste un on/off global comme avant).

    `radius` : int (rayon uniforme, retro-compatible) OU dict {"top_left":
    int, ...} — un rayon INDEPENDANT par coin (voir _rounded_rect_path/la
    remarque de l'utilisateur, "si deux colonnes sont cote a cote ... le
    rayon contre l'autre colonne doit etre a zero", voir _ColumnPreview)."""
    if rect.width() <= 0 or rect.height() <= 0:
        return
    if isinstance(border_on, dict):
        sides_on = {k: bool(border_on.get(k, False)) for k in ("top", "right", "bottom", "left")}
    else:
        v = bool(border_on)
        sides_on = {k: v for k in ("top", "right", "bottom", "left")}
    thickness = max(0, int(thickness))
    t = {k: (thickness if sides_on[k] else 0) for k in sides_on}
    any_on = thickness > 0 and any(sides_on.values())
    inner_rect = QRect(
        rect.left() + t["left"], rect.top() + t["top"],
        rect.width() - t["left"] - t["right"], rect.height() - t["top"] - t["bottom"],
    )
    has_inner = inner_rect.width() > 0 and inner_rect.height() > 0
    p.save()
    p.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
    # Cas RAPIDE, cote uniforme (voir plus bas, MEME resultat GEOMETRIQUE que
    # la decoupe MITREE ci-dessous, mais peint en UN SEUL drawPath via un
    # QPen — pas de sous-remplissage manuel/union de wedges) : tous les
    # cotes actifs, meme couleur — de tres loin le cas le plus courant
    # (Colonnes > Bordure "liee", Toggles/Sliders...). A un PETIT rayon
    # (proche de l'epaisseur, ex. rayon 5 / epaisseur 1) le sous-remplissage
    # par wedges (outer moins inner, coupe en 4 coins puis reunis) laissait
    # un arc visiblement plus FONCE/moins sature que les segments droits —
    # voir la remarque de l'utilisateur, "les arrondis apparaissent... plus
    # sombre que la bordure elle-meme" : l'anneau y est si fin (1px de
    # rayon entre le cercle interieur et exterieur) que chaque triangle-
    # wedge, rasterise et rempli INDEPENDAMMENT avant sa reunion, y perd de
    # la couverture sous-pixel — un trait STROKE (QPen, le rasteriseur de
    # contour dedie de Qt, concu pour garder une epaisseur visuelle
    # CONSTANTE tout le long d'un chemin, virages compris) rend cette meme
    # geometrie sans ce sous-remplissage.
    ring_painted = False
    if any_on and all(sides_on.values()) and thickness > 0:
        uniform_colors = {border_colors[s] for s in ("top", "right", "bottom", "left")}
        if len(uniform_colors) == 1:
            # Degenere si l'epaisseur mange tout le rectangle (voir
            # _ring_pixmap, inner_rect y deviendrait <= 0 des 2 cotes a la
            # fois) — meme garde que l'ancien centerline_rect.width() > 0,
            # sans construire de QRectF juste pour ce test.
            if rect.width() - thickness > 0 and rect.height() - thickness > 0:
                # Anneau sur-echantillonne 8x (voir _ring_pixmap, cache par
                # taille/rayon/epaisseur/couleur — sa geometrie ne depend
                # QUE de ca) : a UNE seule passe d'antialiasing, un trait de
                # 1px sur un PETIT rayon (proche de l'epaisseur) ne couvre
                # par endroits qu'une fraction du pixel le long de la
                # diagonale — lu par l'oeil comme un arc plus terne que les
                # segments droits (voir la remarque de l'utilisateur, "je
                # veux que le lissage de l'arrondi soit parfait" / "il faut
                # que l'epaisseur de la bordure soit a 1px", contrainte
                # fixe). Le REMPLISSAGE d'un anneau (outer moins inner) sur-
                # echantillonne resout ca sans ce sous-remplissage — voir la
                # remarque de l'utilisateur, "essaye de trouver un autre
                # algorithme... celui-ci est vraiment pas beau".
                pixmap, pad = _ring_pixmap(
                    rect.width(), rect.height(), radius, thickness, next(iter(uniform_colors)))
                # SmoothPixmapTransform EXPLICITE sur `p` : sans lui, la
                # mise a l'echelle 8x -> 1x de ce drawPixmap (via le simple
                # ecart de devicePixelRatio entre le pixmap et `p`) retombe
                # sur un plus-proche-voisin BLOCS, pas un filtrage lisse —
                # annulant tout le benefice du sur-echantillonnage (voir la
                # remarque de l'utilisateur, capture a l'appui, "il n'est
                # pas antialiase la ?").
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                p.drawPixmap(QPointF(rect.left() - pad, rect.top() - pad), pixmap)
                ring_painted = True   # deja peint : saute le sous-remplissage MITRE ci-dessous
                # any_on RESTE True (pas touche) : le remplissage plus bas
                # (fill_color) doit continuer a cibler inner_rect, PAS le
                # rect ENTIER, sinon il repeindrait PAR-DESSUS l'anneau
                # qu'on vient de tracer (voir la remarque de l'utilisateur,
                # "les arrondis... plus sombre" — 1er essai de ce correctif,
                # qui mettait any_on a False ici, recouvrait justement le
                # trait par le fond).
    if any_on and not ring_painted:
        outer_path = _rounded_rect_path(rect, radius)
        inner_radius = _radius_shrink(radius, thickness)
        ring = outer_path.subtracted(_rounded_rect_path(inner_rect, inner_radius)) if has_inner else outer_path
        rf = QRectF(rect)
        center = rf.center()
        corners = {
            "top": (QPointF(rf.left(), rf.top()), QPointF(rf.right(), rf.top())),
            "right": (QPointF(rf.right(), rf.top()), QPointF(rf.right(), rf.bottom())),
            "bottom": (QPointF(rf.right(), rf.bottom()), QPointF(rf.left(), rf.bottom())),
            "left": (QPointF(rf.left(), rf.bottom()), QPointF(rf.left(), rf.top())),
        }
        p.setPen(Qt.NoPen)
        # Chaque coin (p1/p2) ALLONGE de EPS le long de son propre cote,
        # au-dela du coin REEL du rectangle — sans ca, 2 coins ENTRE UN
        # COTE ACTIF ET UN COTE DESACTIVE (voir _SideColorsField, un
        # interrupteur PAR cote) se rejoignaient exactement sur la
        # diagonale-vers-le-centre du cote actif, et l'antialiasing y
        # laissait un mini-vide (le "coin" pile a la frontiere entre 2
        # coins ne revient VRAIMENT a aucun des 2 triangles) — voir la
        # remarque de l'utilisateur, capture annotee a l'appui, "la ligne
        # ne forme pas" (le filet restait ouvert a chaque coin plutot que
        # de former un rectangle ferme).
        #
        # Cette rallonge ne doit s'appliquer QUE du cote ou le VOISIN de ce
        # coin est desactive (le vrai trou) — PAS quand les 2 cotes d'un
        # coin sont actifs : la, le triangle du voisin recouvre alors ce
        # meme demi-pixel en double, et sur un rayon arrondi (zone deja
        # anti-aliasee) ce double-recouvrement se voit comme un lisere plus
        # sature / une sorte dedgrade au lieu d'un bord net (voir la
        # remarque de l'utilisateur, "il y a encore comme une sorte de
        # degrade, je ne veux pas ca"). Donc rallonge SEULEMENT au coin ou
        # le voisin est off ; coin exact (sans rallonge) si le voisin est on
        # — le miter diagonal s'y ferme deja parfaitement, sans besoin de
        # fudge.
        # Meme 2 cotes ACTIFS de la MEME couleur (le cas le plus courant —
        # bordure uniforme) laissaient un lisere fantome pile sur la
        # diagonale du miter : 2 formes anti-aliasees peintes separement,
        # bord a bord, ne se recouvrent JAMAIS parfaitement pixel pour pixel
        # (chaque drawPath calcule sa propre att'nuation en bord de forme) —
        # visible surtout sur un coin arrondi (voir la remarque de
        # l'utilisateur, "il y a encore comme une sorte de degrade"). Fix :
        # au lieu de dessiner chaque cote separement, on ACCUMULE les
        # morceaux par couleur (united()) et on ne peint qu'UNE fois par
        # couleur — un seul drawPath = une seule frontiere anti-aliasee,
        # plus de couture interne (que les 2 cotes soient adjacents ou non,
        # united() sur des morceaux disjoints ne change rien au rendu).
        EPS = 0.75
        order = ("top", "right", "bottom", "left")
        color_paths: dict[str, QPainterPath] = {}
        for i, side in enumerate(order):
            if not sides_on[side]:
                continue
            p1, p2 = corners[side]
            neighbor_p1 = order[i - 1]
            neighbor_p2 = order[(i + 1) % 4]
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
            length = (dx * dx + dy * dy) ** 0.5
            ux, uy = (dx / length, dy / length) if length > 0 else (0.0, 0.0)
            p1e = QPointF(p1.x() - ux * EPS, p1.y() - uy * EPS) if not sides_on[neighbor_p1] else p1
            p2e = QPointF(p2.x() + ux * EPS, p2.y() + uy * EPS) if not sides_on[neighbor_p2] else p2
            wedge = QPainterPath()
            wedge.moveTo(p1e)
            wedge.lineTo(p2e)
            wedge.lineTo(center)
            wedge.closeSubpath()
            # Coin ou le voisin est desactive : la diagonale-vers-le-centre
            # ne couvre que LA MOITIE du carre de ce coin (l'autre moitie
            # appartenait au triangle du voisin, qui n'existe plus) — plus
            # le rectangle est fin/allonge, plus cette diagonale rase le
            # bord et laisse un triangle de l'anneau non couvert PRES du
            # coin (personne ne le reclame) — voir la remarque de
            # l'utilisateur, capture a l'appui, "la bordure de la selection
            # ne continue pas de maniere constante jusqu'au bord de la
            # colonne". Fix : unir le wedge avec le rectangle ENTIER coin<->
            # centre (le quadrant complet, pas juste sa moitie triangulaire)
            # — recouvre alors aussi la moitie qui revenait au voisin,
            # sans effet de bord (intersecte avec `ring` de toute facon).
            if not sides_on[neighbor_p1]:
                wedge = wedge.united(_quadrant_path(p1, center))
            if not sides_on[neighbor_p2]:
                wedge = wedge.united(_quadrant_path(p2, center))
            piece = ring.intersected(wedge)
            color = border_colors[side]
            color_paths[color] = color_paths[color].united(piece) if color in color_paths else piece
        for color, path in color_paths.items():
            p.setBrush(QColor(color))
            p.drawPath(path)
    if fill_color is not None:
        target_rect = inner_rect if any_on else rect
        if target_rect.width() > 0 and target_rect.height() > 0:
            clip_radius = _radius_shrink(radius, thickness) if any_on else radius
            if _radius_any(clip_radius):
                p.setClipPath(_rounded_rect_path(target_rect, clip_radius))
            p.fillRect(target_rect, QColor(fill_color))
    p.restore()

def _blend_hex(off_hex: str, on_hex: str, t: float) -> str:
    """Interpole lineairement 2 couleurs hex ("#rrggbb") selon `t`
    (0.0 = `off_hex`, 1.0 = `on_hex`) — utilise par _paint_toggle_shape
    pour animer le FOND du cadre en meme temps que la coche (voir
    _Toggle._progress), plutot qu'un changement brusque a mi-course."""
    t = max(0.0, min(1.0, t))
    off_c, on_c = QColor(off_hex), QColor(on_hex)
    r = round(off_c.red() + (on_c.red() - off_c.red()) * t)
    g = round(off_c.green() + (on_c.green() - off_c.green()) * t)
    b = round(off_c.blue() + (on_c.blue() - off_c.blue()) * t)
    return QColor(r, g, b).name()

def _paint_toggle_shape(p: QPainter, x: int, y: int, style_key: str, style: dict, checked: bool,
                         progress: float | None = None):
    """Dessine le cadre EXTERIEUR + la coche INTERIEURE d'un toggle a la
    position (x, y), selon `style` (voir _TOGGLE1_STYLE/_TOGGLE2_STYLE) —
    factorise entre _Toggle.paintEvent (style COURANT de la fenetre, voir
    _TOGGLE_STYLE) et _ToggleShapePreview (apercu de CHAQUE style, voir
    Toggles > Style, toujours a l'etat FIXE ON/OFF — jamais anime).

    `progress` (0.0 = OFF, 1.0 = ON) anime la TRANSITION entre les 2 etats
    (voir _Toggle, qui glisse cette valeur de 0 a 1 ou l'inverse au clic —
    voir la remarque de l'utilisateur, "une animation quand le toggle
    passe de l'etat on a l'etat off et vice versa") ; None (les 2 apercus
    statiques ci-dessus) retombe sur l'etat fixe de `checked` (0.0 ou 1.0).

    Les 2 styles se comportent tres differemment entre ON et OFF (voir la
    remarque de l'utilisateur, corrigeant un malentendu precedent) :
    - "toggle1" : GLISSIERE classique — la coche garde TOUJOURS le meme
      style (bordure/couleur/taille inchangees), seule sa POSITION change,
      caleé a droite (ON) ou a gauche (OFF), avec la meme marge des 2
      cotes (voir Toggles > Coche > Distance du bord) — animee ici par un
      simple LERP de sa position x entre les 2 bornes.
    - "toggle2" : la coche reste centree mais DISPARAIT completement a
      l'etat OFF (rien de dessine, pas meme un contour) — ne s'affiche
      qu'a l'etat ON — animee ici par un FONDU (opacite = progress)."""
    if progress is None:
        progress = 1.0 if checked else 0.0
    outer_rect = QRect(x, y, style["outer_w"], style["outer_h"])
    outer_colors = {side: style[f"outer_border_{side}"] for side in ("top", "right", "bottom", "left")}
    outer_bg = _blend_hex(style["outer_bg"], style["outer_bg_on"], progress)
    _paint_bordered_rect(p, outer_rect, style["outer_border_radius"], style["outer_border_enabled"],
                          style["outer_border_thickness"], outer_colors, outer_bg)
    margin = style["coche_margin"]
    # coche_h est deduite de outer_h en retirant 2x la marge (voir
    # _sync_toggle_shape_style), donc marge haute = marge basse = margin,
    # ce qui centre deja la coche verticalement — vrai pour les 2 styles,
    # quel que soit l'etat.
    cy = y + margin
    if style_key == "toggle2":
        if progress <= 0.0:
            return   # coche invisible a l'etat OFF (rien a peindre)
        cx = x + (style["outer_w"] - style["coche_w"]) // 2
    else:
        off_x = margin
        on_x = max(0, style["outer_w"] - margin - style["coche_w"])
        cx = x + round(off_x + (on_x - off_x) * progress)
    coche_rect = QRect(cx, cy, style["coche_w"], style["coche_h"])
    coche_colors = {side: style[f"coche_border_{side}"] for side in ("top", "right", "bottom", "left")}
    if style_key == "toggle2" and progress < 1.0:
        p.save()
        p.setOpacity(p.opacity() * progress)
        _paint_bordered_rect(p, coche_rect, style["coche_border_radius"], style["coche_border_enabled"],
                              style["coche_border_thickness"], coche_colors, style["coche_color"])
        _paint_coche_skin(p, coche_rect, style)
        p.restore()
    else:
        _paint_bordered_rect(p, coche_rect, style["coche_border_radius"], style["coche_border_enabled"],
                              style["coche_border_thickness"], coche_colors, style["coche_color"])
        _paint_coche_skin(p, coche_rect, style)

_TOGGLE_ICON_CACHE: dict = {}

def _toggle_icon_pixmap(name: str, size: int, color: str) -> QPixmap | None:
    """Icone de icons/ pour l'habillage d'une coche : un SVG est recolore (trace uni, rendu comme
    un masque), un PNG garde ses couleurs. Cache par (nom, taille, couleur)."""
    key = (name, size, color)
    if key in _TOGGLE_ICON_CACHE:
        return _TOGGLE_ICON_CACHE[key]
    from settings_store import _ICONS_DIR
    path = _ICONS_DIR / name
    pix = None
    if path.is_file() and size > 0:
        scale = 4
        if path.suffix.lower() == ".svg":
            from PySide6.QtSvg import QSvgRenderer
            pix = QPixmap(size * scale, size * scale)
            pix.fill(Qt.transparent)
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.Antialiasing, True)
            QSvgRenderer(str(path)).render(painter)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(pix.rect(), QColor(color))
            painter.end()
        else:
            source = QPixmap(str(path))
            if not source.isNull():
                pix = source.scaled(size * scale, size * scale, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if pix is not None:
            pix.setDevicePixelRatio(scale)
    _TOGGLE_ICON_CACHE[key] = pix
    return pix

def _paint_coche_skin(p: QPainter, rect: QRect, style: dict) -> None:
    """Texte ou icone dessine au centre de la coche (voir Toggles > Coche > Habillage)."""
    skin = style.get("skin", "none")
    if skin == "text" and style.get("text"):
        spec = style["text_font"]
        font = QFont(spec["family"] or "Segoe UI")
        font.setPixelSize(spec["size"])
        font.setBold(spec["bold"])
        font.setItalic(spec["italic"])
        if spec["smoothing"] == "none":
            font.setStyleStrategy(QFont.NoAntialias)
        p.save()
        p.setFont(font)
        p.setPen(QColor(spec["color"]))
        p.drawText(rect, Qt.AlignCenter, style["text"])
        p.restore()
    elif skin == "icon" and style.get("icon"):
        size = max(1, min(rect.width(), rect.height()) - 2)
        pix = _toggle_icon_pixmap(style["icon"], size, style["icon_color"])
        if pix is not None:
            logical = pix.deviceIndependentSize()
            p.drawPixmap(round(rect.center().x() - logical.width() / 2 + 0.5),
                         round(rect.center().y() - logical.height() / 2 + 0.5), pix)

class _Toggle(QWidget):
    """Interrupteur peint a la main selon le style COURANT (voir
    _TOGGLE_STYLE/_paint_toggle_shape — cadre + coche, entierement
    reglables, voir Toggles > Style) + libelle d'etat a droite — utilise
    pour les cadres actif/sans de la page Geometrie, et pour tout autre
    reglage on/off de cette fenetre.

    La transition ON<->OFF est ANIMEE (voir _progress/_anim ci-dessous,
    et _paint_toggle_shape qui sait desormais peindre un etat
    INTERMEDIAIRE) — voir la remarque de l'utilisateur, "une animation
    quand le toggle passe de l'etat on a l'etat off et vice versa"."""

    _ANIM_MS = 140

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, on_label="actif", off_label="sans", parent=None,
                 style_override: str | None = None, show_label: bool = True):
        super().__init__(parent)
        self._checked = checked
        # _progress (0.0 = OFF, 1.0 = ON) est ce que peint REELLEMENT
        # paintEvent — _checked est l'etat final CIBLE (deja a jour des le
        # clic, voir setChecked : le libelle texte, lui, bascule tout de
        # suite plutot que de tenter un fondu croise entre 2 mots) ; SEUL
        # _progress glisse progressivement de l'un a l'autre pendant
        # l'animation.
        self._progress = 1.0 if checked else 0.0
        self._on_label, self._off_label = on_label, off_label
        # `style_override` ("toggle1"/"toggle2"/None) : ignore le style
        # COURANT de la fenetre (_TOGGLE_STYLE) et fige celui-ci a la place
        # — voir la remarque de l'utilisateur, "je veux overider le style
        # du toggle ici pour le toggle 2" (les interrupteurs par cote des
        # reglages de bordure, voir _SideColorsField, doivent toujours
        # avoir l'apparence "toggle2" quel que soit le style choisi dans
        # Toggles > Style). `show_label` False : masque "actif"/"sans" a
        # cote du cadre — voir la remarque de l'utilisateur, "ne mets pas
        # l'annotation actif a cote du toggle, uniquement le toggle en lui
        # meme" (memes interrupteurs par cote).
        self._style_override = style_override
        self._show_label = show_label
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self._ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_value)
        self.apply_style()

    def _on_anim_value(self, value):
        self._progress = float(value)
        self.update()

    def _style_key(self) -> str:
        return self._style_override or _TOGGLE_STYLE

    def _style(self) -> dict:
        if self._style_override:
            return _toggle_style_dict(self._style_override)
        return _active_toggle_style()

    def apply_style(self):
        """Rejoue le style COURANT (voir _TOGGLE_STYLE), OU celui fige par
        `style_override` (voir __init__) — a rappeler sur toute instance
        deja construite quand ce reglage change (voir SettingsWindow.
        _on_toggle_style_changed) : necessaire, pas un simple repaint,
        puisque la taille meme du cadre (outer_w/outer_h) peut avoir
        change."""
        style = self._style()
        self._outer_w = style["outer_w"]
        h = max(25, style["outer_h"] + 8)
        # Pas de place reservee au libelle (+9+40) si `show_label` est
        # False (voir __init__) : juste le cadre, une petite marge (6px,
        # meme valeur que le 1er terme de "9" ci-dessous arrondi) pour ne
        # pas coller le cadre au bord du widget.
        w = max(30, style["outer_w"]) + (9 + 40 if self._show_label else 6)
        self.setFixedSize(w, h)
        self.update()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if checked == self._checked:
            return
        self._checked = checked
        # Pas de garde sur self.isVisible() : la plupart des toggles vivent
        # dans une section REPLIEE par defaut (voir _Section), donc
        # invisibles la plupart du temps sans etre pour autant "avant le
        # premier affichage" — anime dans tous les cas (l'animation, ~140ms,
        # est de toute facon terminee bien avant qu'on deplie la section
        # pour la voir)."""
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()
        self.toggled.emit(checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        style = self._style()
        y = (self.height() - style["outer_h"]) // 2
        # x=0 quand un libelle suit a droite (voir apply_style, largeur du
        # widget = cadre + marge fixe reservee au texte) ; SANS libelle, le
        # cadre est plus etroit que le widget (voir apply_style, marge de
        # 6px) et doit alors etre CENTRE horizontalement dans ce widget —
        # sinon il apparait decale par rapport a la pastille de couleur/au
        # texte G/H/B/D juste en dessous (voir _SideColorsField, meme
        # colonne alignee au centre) — voir la remarque de l'utilisateur,
        # "le toggle n'est pas centre avec le carre de couleur".
        x = 0 if self._show_label else max(0, (self.width() - style["outer_w"]) // 2)
        _paint_toggle_shape(p, x, y, self._style_key(), style, self._checked, progress=self._progress)
        if self._show_label:
            p.setFont(_qfont(10, 400, mono=True))
            # Couleur du libelle interpolee sur _progress (pas juste
            # _checked) : suit le meme fondu que la coche plutot que de
            # sauter net des le debut du glisser.
            on_color, off_color = QColor(M["toggle_on_fg"]), QColor(M["toggle_off_fg"])
            t = self._progress
            label_color = QColor(
                round(off_color.red() + (on_color.red() - off_color.red()) * t),
                round(off_color.green() + (on_color.green() - off_color.green()) * t),
                round(off_color.blue() + (on_color.blue() - off_color.blue()) * t),
            )
            p.setPen(label_color)
            label_x = self._outer_w + 9
            p.drawText(label_x, 0, 40, self.height(), Qt.AlignVCenter | Qt.AlignLeft,
                       self._on_label if self._checked else self._off_label)
        p.end()

class _ToggleShapePreview(QWidget):
    """Apercu ON+OFF cote a cote pour un style ("toggle1"/"toggle2") — LIT
    en direct _TOGGLE1_STYLE/_TOGGLE2_STYLE (voir refresh, rappele par
    SettingsWindow._on_toggle_style_changed a chaque reglage touche dans
    les tableaux Cadre/Coche ci-dessous) : pas un simple apercu fige, il
    suit les 2 tableaux en temps reel. Pur apercu, non interactif — le
    choix du style se fait en cliquant la carte englobante (voir
    _ToggleStyleCard)."""

    _GAP = 16
    _PAD = 6

    def __init__(self, style_key: str, parent=None):
        super().__init__(parent)
        self._style_key = style_key
        self._slot_w = 40
        self.refresh()

    def _style(self) -> dict:
        return _toggle_style_dict(self._style_key)

    def sizeHint(self):
        # setFixedSize() pose deja minimumSize()/maximumSize(), mais PAS
        # sizeHint() (QWidget la laisse invalide par defaut, voir sa doc) —
        # un ancetre cache puis reaffiche (voir _Section.set_collapsed)
        # peut alors re-figer un layout base sur cette taille invalide
        # avant que minimumSize() ne soit reconsideree, laissant cet apercu
        # ecrase a une hauteur minuscule (voir la remarque de l'utilisateur,
        # capture a l'appui : carte de style quasi vide).
        return self.size()

    def refresh(self):
        style = self._style()
        self._slot_w = max(style["outer_w"], style["coche_w"]) + self._PAD * 2
        h = max(style["outer_h"], 18) + self._PAD * 2 + 16
        self.setFixedSize(self._slot_w * 2 + self._GAP, h)
        self.updateGeometry()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        style = self._style()
        y = self._PAD
        x0 = (self._slot_w - style["outer_w"]) // 2
        x1 = self._slot_w + self._GAP + (self._slot_w - style["outer_w"]) // 2
        _paint_toggle_shape(p, x0, y, self._style_key, style, True)
        _paint_toggle_shape(p, x1, y, self._style_key, style, False)
        p.setFont(_qfont(8, 600, mono=True, tracking=0.4))
        p.setPen(QColor(M["unit"]))
        label_y = y + style["outer_h"] + 4
        p.drawText(0, label_y, self._slot_w, 14, Qt.AlignHCenter, "ON")
        p.drawText(self._slot_w + self._GAP, label_y, self._slot_w, 14, Qt.AlignHCenter, "OFF")
        p.end()

class _ToggleStyleCard(QWidget):
    """Une carte cliquable du selecteur de style (voir _ToggleStylePicker) :
    libelle + apercu ON/OFF en direct (voir _ToggleShapePreview) — bordure
    accentuee quand selectionnee, meme logique que les autres "cartes"
    cliquables de cette fenetre (voir _PresetListRow)."""

    clicked = Signal()

    def __init__(self, style_key: str, label: str, parent=None):
        super().__init__(parent)
        self._selected = False
        self.setObjectName("ToggleStyleCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)
        title = QLabel(label)
        _set_text_role(title, "card_title")
        title.setAlignment(Qt.AlignHCenter)
        layout.addWidget(title, 0, Qt.AlignHCenter)
        self.preview = _ToggleShapePreview(style_key)
        layout.addWidget(self.preview, 0, Qt.AlignHCenter)
        self._refresh_style()

    def _refresh_style(self):
        border = M["accent"] if self._selected else M["field_border"]
        bg = M["btn_hover"] if self._selected else M["field_bg"]
        self.setStyleSheet(f"#ToggleStyleCard {{ background: {bg}; border: 1px solid {border}; border-radius: 4px; }}")

    def setSelected(self, selected: bool):
        if selected != self._selected:
            self._selected = selected
            self._refresh_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

class _ToggleStylePicker(QWidget):
    """Choix du style visuel de TOUS les toggles de cette fenetre (voir
    _Toggle/_TOGGLE_STYLE) — 2 cartes cliquables (Toggle 1/Toggle 2),
    chacune avec son propre apercu ON/OFF en direct — voir la remarque de
    l'utilisateur, capture annotee a l'appui (mockup corrige des 2
    styles)."""

    changed = Signal(str)

    def __init__(self, value: str, parent=None):
        super().__init__(parent)
        # Les cartes viennent du registre : toggle1, toggle2 et les styles ajoutes par l'utilisateur.
        self._value = value if value in _TOGGLE_STYLES else "toggle1"
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(14)
        self._cards: dict[str, _ToggleStyleCard] = {}
        for key in list(_TOGGLE_STYLES):
            self.addOption(key, _TOGGLE_STYLE_NAMES.get(key, key))

    def addOption(self, key: str, label: str):
        """Ajoute une carte (nouveau style de toggle)."""
        if key in self._cards:
            return
        card = _ToggleStyleCard(key, label)
        card.setSelected(key == self._value)
        card.clicked.connect(lambda _checked=False, k=key: self._select(k))
        self._cards[key] = card
        self._layout.addWidget(card)

    def _select(self, key: str):
        if key != self._value:
            self._value = key
            for k, card in self._cards.items():
                card.setSelected(k == key)
            self.changed.emit(key)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        if value in self._cards and value != self._value:
            self._select(value)

    def refreshPreviews(self):
        """Rappele quand les tableaux Cadre/Coche changent (voir
        SettingsWindow._on_toggle_style_changed) : les apercus de CETTE
        carte lisent _TOGGLE1_STYLE/_TOGGLE2_STYLE en direct, ils ont juste
        besoin d'un repaint (+ recalcul de taille, voir _ToggleShapePreview.
        refresh)."""
        for card in self._cards.values():
            card.preview.refresh()

class _CornerPositionCard(QWidget):
    """Une carte cliquable du selecteur de position (voir
    _CornerPositionField) — MEME logique que _ToggleStyleCard (bordure
    accentuee quand selectionnee), mais SANS apercu graphique : juste le
    libelle abrege (BD/BG/HD/HG)."""

    clicked = Signal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._selected = False
        self.setObjectName("CornerPositionCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(52, 36)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(label)
        _set_text_role(title, "card_title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title, 0, Qt.AlignCenter)
        self._refresh_style()

    def _refresh_style(self):
        border = M["accent"] if self._selected else M["field_border"]
        bg = M["btn_hover"] if self._selected else M["field_bg"]
        self.setStyleSheet(
            f"#CornerPositionCard {{ background: {bg}; border: 1px solid {border}; border-radius: 4px; }}")

    def setSelected(self, selected: bool):
        if selected != self._selected:
            self._selected = selected
            self._refresh_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

class _CornerPositionField(QWidget):
    """Choix du coin d'ancrage du cadre de redimensionnement (voir
    pipeline_browser._show_resize_width) : 4 cartes cliquables (Bas-Droite/
    Bas-Gauche/Haut-Droite/Haut-Gauche), disposees en grille 2x2 refletant
    la position REELLE de chaque coin — MEME principe que _ToggleStylePicker
    (une seule active a la fois) — voir la remarque de l'utilisateur, "je
    veux que dans general/colonnes/ tu crees une sous section cadre de
    redimensionnement avec comme parametres : ligne 1 : position (toggles)
    BD BG HD HG"."""

    changed = Signal(str)

    _OPTIONS = [
        ("top_left", "HG", 0, 0), ("top_right", "HD", 0, 1),
        ("bottom_left", "BG", 1, 0), ("bottom_right", "BD", 1, 1),
    ]

    def __init__(self, value: str, parent=None):
        super().__init__(parent)
        valid = {key for key, *_ in self._OPTIONS}
        self._value = value if value in valid else "bottom_right"
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._cards: dict[str, _CornerPositionCard] = {}
        for key, label, row, col in self._OPTIONS:
            card = _CornerPositionCard(label)
            card.setSelected(key == self._value)
            card.clicked.connect(lambda _checked=False, k=key: self._select(k))
            self._cards[key] = card
            layout.addWidget(card, row, col)

    def _select(self, key: str):
        if key != self._value:
            self._value = key
            for k, card in self._cards.items():
                card.setSelected(k == key)
            self.changed.emit(key)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        if value in self._cards and value != self._value:
            self._select(value)

class _ResizeBadgePositionField(QWidget):
    """Ligne "Position" complete du cadre de redimensionnement (voir
    Cadre de redimensionnement > Position) : le coin d'ancrage (voir
    _CornerPositionField) SUIVI, SUR LA MEME LIGNE, de 2 sliders "H"/"V" —
    le decalage (px) applique depuis ce coin, horizontal puis vertical —
    voir la remarque de l'utilisateur, "sous position je veux egalement
    deux sliders (sur la mm ligne) pour la position H et la position V".
    UN SEUL widget (comme _RowBorderField/_ToggleSideColorsField ailleurs
    dans cette fenetre) pour que _build_flat_table lui reserve UNE SEULE
    ligne malgre ses 3 sous-champs."""

    changed = Signal()

    def __init__(self, position: str, offset_x: int, offset_y: int, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.corner_field = _CornerPositionField(position)
        layout.addWidget(self.corner_field)

        def labeled_slider(text: str, value: int) -> tuple[QLabel, _SliderField]:
            label = QLabel(text)
            _set_text_role(label, "card_title")
            slider = _SliderField(0, 64, value, slider_width=90, box_width=48)
            return label, slider

        h_label, self.offset_x_field = labeled_slider("H", offset_x)
        v_label, self.offset_y_field = labeled_slider("V", offset_y)
        for w in (h_label, self.offset_x_field, v_label, self.offset_y_field):
            layout.addWidget(w, 0, Qt.AlignVCenter)
        layout.addStretch(1)

        self.corner_field.changed.connect(lambda _v: self.changed.emit())
        self.offset_x_field.valueChanged.connect(lambda _v: self.changed.emit())
        self.offset_y_field.valueChanged.connect(lambda _v: self.changed.emit())

    def position(self) -> str:
        return self.corner_field.value()

    def offsetX(self) -> int:
        return self.offset_x_field.value()

    def offsetY(self) -> int:
        return self.offset_y_field.value()

    def setValue(self, position: str, offset_x: int, offset_y: int):
        self.corner_field.setValue(position)
        self.offset_x_field.setValue(offset_x)
        self.offset_y_field.setValue(offset_y)

# ==========================================================================
# Selecteur de couleur maison (remplace QColorDialog, dont l'habillage
# systeme jurait avec le reste de l'appli — voir la remarque de
# l'utilisateur, maquette html fournie a l'appui) : carre saturation/
# luminosite + 3 sliders TSL + 3 sliders RVB, tous synchronises sur une
# seule verite (self._h/_s/_v), plus palette de l'appli (C) et couleurs
# recentes. colorChanged emet a CHAQUE mouvement (glisser un slider, le
# carre...), pas seulement a la validation : c'est ce qui permet a
# _ColorField de repercuter le changement en direct sur la fenetre
# principale, exactement comme le faisait deja QColorDialog en connectant
# son propre currentColorChanged — voir _ColorField._pick.
# ==========================================================================

def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if h < 60:
        r, g, b = c, x, 0.0
    elif h < 120:
        r, g, b = x, c, 0.0
    elif h < 180:
        r, g, b = 0.0, c, x
    elif h < 240:
        r, g, b = 0.0, x, c
    elif h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (
        max(0, min(255, round((r + m) * 255))),
        max(0, min(255, round((g + m) * 255))),
        max(0, min(255, round((b + m) * 255))),
    )

def _rgb_to_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(c))) for c in rgb))

def _with_alpha(hexval: str, alpha: int) -> str:
    """Prefixe `hexval` ("#rrggbb") du canal alpha (0-255, voir
    app_style._hex_to_alpha) SEULEMENT si < 255 (opaque reste "#rrggbb",
    format INCHANGE — retro-compatible avec les presets/settings.json
    existants, jamais transparents jusqu'ici) — voir la remarque de
    l'utilisateur, "un parametre de transparence des couleurs dans le
    selecteur". QColor/le QSS de Qt lisent nativement ce format
    "#aarrggbb" (verifie directement), aucune autre conversion requise
    cote rendu."""
    alpha = max(0, min(255, int(alpha)))
    if alpha >= 255:
        return hexval
    return f"#{alpha:02x}{hexval.lstrip('#')}"

def _rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    rf, gf, bf = r / 255, g / 255, b / 255
    mx, mn = max(rf, gf, bf), min(rf, gf, bf)
    d = mx - mn
    if d == 0:
        h = 0.0
    elif mx == rf:
        h = 60 * (((gf - bf) / d) % 6)
    elif mx == gf:
        h = 60 * ((bf - rf) / d + 2)
    else:
        h = 60 * ((rf - gf) / d + 4)
    return h % 360, (d / mx if mx else 0.0), mx

def _hex_to_hsv(hexval: str) -> tuple[float, float, float]:
    return _rgb_to_hsv(*_hex_to_rgb(hexval))

class _SVPad(QWidget):
    """Carre saturation/luminosite peint a la main : fond = degrade blanc
    -> teinte pure (horizontal) par-dessus degrade transparent -> noir
    (vertical), curseur rond a la position (s, v) courante."""

    changed = Signal(float, float)   # (s, v), chacun 0..1

    def __init__(self, width: int = 276, height: int = 160, parent=None):
        super().__init__(parent)
        self._hue = 0.0
        self._s = 0.0
        self._v = 0.0
        self.setFixedSize(width, height)
        self.setCursor(Qt.CrossCursor)

    def setHue(self, hue: float):
        if hue != self._hue:
            self._hue = hue
            self.update()

    def setSV(self, s: float, v: float):
        s = max(0.0, min(1.0, s))
        v = max(0.0, min(1.0, v))
        if (s, v) != (self._s, self._v):
            self._s, self._v = s, v
            self.update()

    def _emit_from_pos(self, pos):
        w, h = max(1, self.width() - 1), max(1, self.height() - 1)
        s = max(0.0, min(1.0, pos.x() / w))
        v = 1.0 - max(0.0, min(1.0, pos.y() / h))
        self._s, self._v = s, v
        self.update()
        self.changed.emit(s, v)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._emit_from_pos(event.position().toPoint())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._emit_from_pos(event.position().toPoint())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        pure = QColor(*_hsv_to_rgb(self._hue, 1.0, 1.0))
        p.fillRect(rect, pure)
        sat_grad = QLinearGradient(rect.topLeft(), rect.topRight())
        sat_grad.setColorAt(0, QColor(255, 255, 255, 255))
        sat_grad.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(rect, sat_grad)
        val_grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        val_grad.setColorAt(0, QColor(0, 0, 0, 0))
        val_grad.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(rect, val_grad)
        p.setRenderHint(QPainter.Antialiasing, True)
        x = int(self._s * (self.width() - 1))
        y = int((1 - self._v) * (self.height() - 1))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPoint(x, y), 6, 6)
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.drawEllipse(QPoint(x, y), 7, 7)
        p.end()

class _GradientSlider(QWidget):
    """Slider horizontal peint a la main, degrade fourni par l'appelant
    (voir setStops) — utilise pour les 6 lignes TSL/RVB du selecteur de
    couleur : le degrade de chaque slider montre le resultat du
    deplacement AVANT de le faire (voir _ColorPickerPopup._refresh_all,
    qui recalcule ces degrades a chaque changement, meme sur un AUTRE
    slider — ex : le degrade "Saturation" depend de la Luminosite
    courante)."""

    changed = Signal(float)   # 0..1

    def __init__(self, width: int = 140, height: int = 13, parent=None, checkerboard: bool = False):
        super().__init__(parent)
        self._frac = 0.0
        self._stops: list[tuple[float, QColor]] = [(0.0, QColor("#000000")), (1.0, QColor("#ffffff"))]
        # `checkerboard` (voir _ColorPickerPopup, ligne Alpha UNIQUEMENT —
        # toutes les autres restent opaques, comportement INCHANGE) : voir
        # _paint_checkerboard, MEME raison qu'ailleurs — un degrade allant
        # jusqu'a transparent se lirait mal sans lui.
        self._checkerboard = checkerboard
        # Largeur MINIMALE, pas fixe : ce slider est ajoute avec un facteur
        # d'etirement (voir _make_row, row.addWidget(slider, 1)) pour
        # occuper l'espace restant de la ligne — un setFixedSize figeait sa
        # largeur a `width` quoi qu'il arrive, ce qui neutralisait cet
        # etirement et pouvait meme faire deborder la ligne (ex. largeur de
        # boite de valeur/espacement augmentes plus tard, voir la remarque
        # de l'utilisateur sur l'espace slider/boite) au lieu de simplement
        # se retrecir pour laisser la place. La hauteur, elle, reste fixe
        # (barre fine, jamais besoin de grandir verticalement).
        self.setMinimumWidth(min(width, 60))
        self.setFixedHeight(height)
        self.setCursor(Qt.CrossCursor)

    def setStops(self, stops):
        self._stops = [(pos, QColor(hexval)) for pos, hexval in stops]
        self.update()

    def setFraction(self, frac: float):
        frac = max(0.0, min(1.0, frac))
        if frac != self._frac:
            self._frac = frac
            self.update()

    def _emit_from_x(self, x: int):
        w = max(1, self.width() - 1)
        frac = max(0.0, min(1.0, x / w))
        self._frac = frac
        self.update()
        self.changed.emit(frac)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._emit_from_x(int(event.position().x()))

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._emit_from_x(int(event.position().x()))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        if self._checkerboard:
            _paint_checkerboard(p, rect)
        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        for pos, color in self._stops:
            grad.setColorAt(pos, color)
        p.fillRect(rect, grad)
        p.setPen(QPen(QColor(M["swatch_border"]), 1))
        p.drawRect(rect.adjusted(0, 0, -1, -1))
        x = int(self._frac * max(0, self.width() - 3))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawRect(x, -3, 3, self.height() + 6)
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(x, -3, 3, self.height() + 6)
        p.end()

class _PickerCloseButton(QPushButton):
    """Petit bouton "X" peint a la main — meme raison que _HamburgerButton
    (glyphe unicode non fiable a cette taille selon la police systeme)."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(self._color), 1.3))
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        s = min(w, h) * 0.22
        painter.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
        painter.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))
        painter.end()

class _PipetteButton(QPushButton):
    """Petit bouton pipette peint a la main — meme raison que
    _PickerCloseButton (glyphe unicode non fiable selon la police
    systeme) : capture d'une couleur n'importe ou a l'ecran."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(self._color), 1.3))
        w, h = self.width(), self.height()
        # corps du compte-gouttes : trait diagonal + pointe, incline a 45°
        x1, y1 = w * 0.28, h * 0.72
        x2, y2 = w * 0.68, h * 0.32
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        painter.drawEllipse(QPointF(x2, y2), 2.2, 2.2)
        painter.drawLine(QPointF(w * 0.22, h * 0.78), QPointF(w * 0.32, h * 0.68))
        painter.end()

class _PipetteAreaButton(QPushButton):
    """Variante "zone" du bouton pipette — glyphe rectangle en pointilles,
    pour la difference de la pipette point (_PipetteButton)."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(self._color), 1.3, Qt.DashLine)
        painter.setPen(pen)
        w, h = self.width(), self.height()
        rect = QRect(int(w * 0.22), int(h * 0.28), int(w * 0.56), int(h * 0.44))
        painter.drawRect(rect)
        painter.end()

def _grab_virtual_desktop() -> tuple[QPixmap, QPoint]:
    """Capture tous les ecrans en un seul pixmap, recale sur l'origine du
    bureau virtuel (qui peut etre negative si un moniteur est place a
    gauche/au-dessus du principal). Retourne (pixmap, origine)."""
    screens = QGuiApplication.screens()
    geo = QRect()
    for screen in screens:
        geo = geo.united(screen.geometry())
    origin = geo.topLeft()
    pixmap = QPixmap(geo.size())
    pixmap.fill(Qt.black)
    painter = QPainter(pixmap)
    for screen in screens:
        shot = screen.grabWindow(0)
        shot.setDevicePixelRatio(1.0)
        painter.drawPixmap(screen.geometry().translated(-origin), shot)
    painter.end()
    return pixmap, origin

def _make_pipette_cursor() -> QCursor:
    """Curseur "compte-gouttes" — remplace le curseur systeme le temps de
    la capture (voir la demande : le curseur doit rester ce glyphe jusqu'a
    la selection, pas juste une croix generique)."""
    size = 28
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    tip = QPointF(5, 23)
    tail = QPointF(19, 9)
    pen_outline = QPen(QColor("#000000"), 4.2)
    pen_outline.setCapStyle(Qt.RoundCap)
    p.setPen(pen_outline)
    p.drawLine(tip, tail)
    pen_fill = QPen(QColor("#ffffff"), 2.2)
    pen_fill.setCapStyle(Qt.RoundCap)
    p.setPen(pen_fill)
    p.drawLine(tip, tail)
    p.setPen(QPen(QColor("#000000"), 1))
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(tip, 2.6, 2.6)
    p.end()
    return QCursor(pm, int(tip.x()), int(tip.y()))

class _ScreenCaptureOverlay(QWidget):
    """Base commune aux deux pipettes : fenetre plein "bureau virtuel"
    (tous les moniteurs) affichant une copie figee de l'ecran, sur
    laquelle vient se dessiner l'interaction propre a chaque sous-classe
    (point ou rectangle). Echap annule toujours."""

    picked = Signal(str)
    cancelled = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self._resolved = False
        self._pixmap, self._origin = _grab_virtual_desktop()
        self._image = self._pixmap.toImage()
        self.setGeometry(QRect(self._origin, self._pixmap.size()))

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pixmap)
        self._paint_overlay(p)
        p.end()

    def _paint_overlay(self, painter: QPainter):
        pass

    def _color_at(self, pos: QPoint):
        x, y = pos.x(), pos.y()
        if 0 <= x < self._image.width() and 0 <= y < self._image.height():
            return QColor(self._image.pixel(x, y))
        return None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._finish(None)
        else:
            super().keyPressEvent(event)

    def _finish(self, hexval):
        if self._resolved:
            return
        self._resolved = True
        if hexval is not None:
            self.picked.emit(hexval)
        else:
            self.cancelled.emit()
        self.close()

class _EyedropperOverlay(_ScreenCaptureOverlay):
    """Pipette "point" — capture la couleur du pixel sous le curseur.
    Le curseur systeme prend la forme d'un compte-gouttes et le garde
    jusqu'au clic (voir _make_pipette_cursor) ; une pastille flottante
    affiche le hex du pixel survole, en plus du curseur, pour lire la
    valeur avant de valider. Clic gauche valide, tout autre bouton ou
    Echap annule."""

    def __init__(self):
        super().__init__()
        self.setCursor(_make_pipette_cursor())
        self._last_hex = "#000000"
        self._preview = QLabel(self)
        self._preview.setFont(_qfont(10, 600, mono=True))
        self._preview.hide()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        color = self._color_at(pos)
        if color is not None:
            self._last_hex = color.name()
            fg = "#000000" if color.lightness() > 128 else "#ffffff"
            self._preview.setText(f"  {self._last_hex}  ")
            self._preview.setStyleSheet(
                f"background: {self._last_hex}; color: {fg}; border: 1px solid #000000; padding: 2px;"
            )
            self._preview.adjustSize()
            self._preview.move(pos.x() + 18, pos.y() + 22)
            self._preview.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            color = self._color_at(event.position().toPoint())
            self._finish(color.name() if color is not None else self._last_hex)
        else:
            self._finish(None)

class _AreaEyedropperOverlay(_ScreenCaptureOverlay):
    """Pipette "zone" — on glisse un rectangle, la couleur retenue est la
    moyenne des pixels de la selection (sous-echantillonnee sur une
    grille 32x32 pour rester instantanee meme sur une grande zone).
    Clic-glisser puis relacher valide ; Echap ou clic droit annule."""

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.CrossCursor)
        self._dragging = False
        self._start = QPoint()
        self._current_rect = QRect()
        self._last_hex = "#000000"
        self._preview = QLabel(self)
        self._preview.setFont(_qfont(10, 600, mono=True))
        self._preview.hide()

    def _average_color(self, rect: QRect) -> QColor:
        rect = rect.intersected(self._image.rect())
        if rect.width() <= 0 or rect.height() <= 0:
            return QColor(self._last_hex)
        sample = self._image.copy(rect).scaled(
            32, 32, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        r = g = b = n = 0
        for y in range(sample.height()):
            for x in range(sample.width()):
                c = sample.pixelColor(x, y)
                r += c.red()
                g += c.green()
                b += c.blue()
                n += 1
        if n == 0:
            return QColor(self._last_hex)
        return QColor(r // n, g // n, b // n)

    def _update_preview(self, pos: QPoint):
        color = self._average_color(self._current_rect)
        self._last_hex = color.name()
        fg = "#000000" if color.lightness() > 128 else "#ffffff"
        self._preview.setText(f"  {self._last_hex}  moyenne  ")
        self._preview.setStyleSheet(
            f"background: {self._last_hex}; color: {fg}; border: 1px solid #000000; padding: 2px;"
        )
        self._preview.adjustSize()
        self._preview.move(pos.x() + 18, pos.y() + 22)
        self._preview.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._start = event.position().toPoint()
            self._current_rect = QRect(self._start, self._start)
            self.update()
        else:
            self._finish(None)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._dragging:
            self._current_rect = QRect(self._start, pos).normalized()
            self._update_preview(pos)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            color = self._average_color(self._current_rect)
            self._finish(color.name())

    def _paint_overlay(self, painter: QPainter):
        if self._current_rect.isNull() or self._current_rect.isEmpty():
            return
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawRect(self._current_rect)

def _paint_checkerboard(p: QPainter, rect: QRect, tile: int = 6):
    """Damier 2 tons (voir _ColorSwatchButton) — convention standard pour
    representer une transparence dans un apercu de couleur (Photoshop et
    consorts) : sans lui, une couleur partiellement transparente se
    fondrait juste avec le fond du panneau derriere la pastille, illisible
    — voir la remarque de l'utilisateur, "un parametre de transparence des
    couleurs dans le selecteur"."""
    light, dark = QColor("#4a4d51"), QColor("#34363a")
    y = rect.top()
    row = 0
    while y < rect.bottom():
        h = min(tile, rect.bottom() - y)
        x = rect.left()
        col = 0
        while x < rect.right():
            w = min(tile, rect.right() - x)
            p.fillRect(QRect(x, y, w, h), light if (row + col) % 2 == 0 else dark)
            x += tile
            col += 1
        y += tile
        row += 1

class _ColorSwatchButton(QPushButton):
    """Pastille de couleur cliquable, fond peint A LA MAIN (damier si
    alpha < 255, puis la couleur par-dessus avec son alpha REEL, puis la
    bordure) — remplace l'ancien "QPushButton { background: <hex>; }" en
    QSS (voir _ColorField/_AppOrCustomColorField, qui l'utilisaient
    toutes les deux) : un simple fond QSS composerait bien la
    transparence, mais SANS damier dessous, la rendant illisible/confondue
    avec une couleur opaque proche — voir la remarque de l'utilisateur, "un
    parametre de transparence des couleurs dans le selecteur"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hex = "#000000"
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.setAttribute(Qt.WA_Hover, True)

    def setColorHex(self, hexval: str):
        self._hex = hexval or "#000000"
        self.update()

    def event(self, e):
        # WA_Hover (pas juste underMouse() dans paintEvent) : force un
        # repaint AU survol/depart, sinon la bordure "hover" (voir
        # paintEvent) ne se met a jour qu'au prochain repaint declenche par
        # autre chose (deja constate sur d'autres boutons customs de cette
        # fenetre).
        if e.type() in (QEvent.Enter, QEvent.Leave):
            self.update()
        return super().event(e)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 2, 2)
        p.save()
        p.setClipPath(path)
        color = QColor(self._hex)
        if color.alpha() < 255:
            _paint_checkerboard(p, self.rect())
        p.fillRect(self.rect(), color)
        p.restore()
        border_color = M["swatch_border_hover"] if self.underMouse() else M["swatch_border"]
        p.setPen(QPen(QColor(border_color), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.end()

class _PopupHeader(QWidget):
    """En-tete du popup couleur — glissable : le popup n'a pas d'autre
    barre de titre ni de bord redimensionnable, et s'ouvre toujours a une
    position fixe pres de la pastille cliquee (voir show_near), qui peut
    geneur (ex. juste au-dessus d'une zone de l'ecran qu'on veut piocher a
    la pipette). Cliquer-glisser n'importe ou sur ce bandeau (hors les
    boutons pipette/fermer, qui recoivent et consomment deja leurs propres
    clics avant que head en soit informe) deplace tout le popup."""

    def __init__(self, popup: QWidget, parent=None):
        super().__init__(parent)
        self._popup = popup
        self._drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._popup.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self._popup.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

class _ColorPickerPopup(QWidget):
    """Selecteur de couleur maison — remplace QColorDialog. colorChanged
    emet a chaque mouvement (previsualisation en direct sur la fenetre
    principale, voir _ColorField._pick) ; committed seulement a la
    validation (Valider, ou un clic en dehors du popup — voir closeEvent),
    qui fige aussi la couleur dans les "Recentes" ; cancelled restaure la
    valeur de depart (bouton Annuler ou croix, jamais un simple clic
    dehors — voir la meme remarque)."""

    colorChanged = Signal(str)
    committed = Signal(str)
    cancelled = Signal()

    # Bornes du glisser sur le bord droit (voir mousePressEvent) : 300 =
    # largeur d'origine (avant setFixedWidth), 640 = large sans depasser
    # demesurement un ecran modeste.
    _MIN_WIDTH = 300
    _MAX_WIDTH = 640
    _RESIZE_MARGIN = 6

    def __init__(self, initial_hex: str, title: str, parent=None):
        super().__init__(parent, Qt.Popup)
        self._before = initial_hex
        self._resolved = False
        self._h, self._s, self._v = _hex_to_hsv(initial_hex)
        # Alpha (0-255, voir app_style._hex_to_alpha/Colonnes > ... > la
        # remarque de l'utilisateur, "un parametre de transparence des
        # couleurs dans le selecteur") — 255 (opaque) pour tout hex a 6
        # chiffres, comportement INCHANGE tant que non personnalise.
        self._a = _hex_to_alpha(initial_hex)
        # Meme rayon que les vraies zones de saisie de l'appli principale
        # (voir get_input_radius) — calcule ici, AVANT _make_row (boites de
        # valeur TSL/RVB) ET la boite HEX/le bloc avant-apres plus bas, qui
        # en ont tous besoin.
        self._input_radius = get_input_radius()

        self.setObjectName("ColorPicker")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#ColorPicker {{ background: {M['panel_bg']}; border: 1px solid {M['panel_border']}; }}"
        )
        # Largeur MINIMALE (plus fixe) : le bord droit devient une poignee
        # de redimensionnement (voir mousePressEvent/mouseMoveEvent/
        # resizeEvent plus bas) — l'utilisateur peut elargir le popup pour
        # des sliders TSL/RVB plus longs, donc un controle plus precis (voir
        # sa remarque). show_near() rappelle adjustSize() a chaque ouverture,
        # qui revient a cette largeur par defaut (pas de memorisation d'une
        # largeur choisie d'une ouverture a l'autre, hors scope de la
        # demande).
        self.setMinimumWidth(self._MIN_WIDTH)
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0
        self.setMouseTracking(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # -- en-tete --
        head = _PopupHeader(self)
        head.setFixedHeight(28)
        head.setStyleSheet(f"background: {M['btn_hover']}; border-bottom: 2px solid {M['accent']};")
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(10, 0, 8, 0)
        head_l.setSpacing(8)
        tag = QLabel("COULEUR")
        _set_text_role(tag, "tag_accent")
        head_l.addWidget(tag)
        title_label = QLabel(title)
        _set_text_role(title_label, "card_title")
        title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        head_l.addWidget(title_label, 1)
        pipette_btn = _PipetteButton(M["label_dim"])
        pipette_btn.setFixedSize(16, 16)
        pipette_btn.setCursor(Qt.ArrowCursor)
        pipette_btn.setFlat(True)
        pipette_btn.setToolTip("Piocher une couleur a l'ecran")
        pipette_btn.clicked.connect(lambda: self._on_pipette(_EyedropperOverlay))
        head_l.addWidget(pipette_btn)
        pipette_area_btn = _PipetteAreaButton(M["label_dim"])
        pipette_area_btn.setFixedSize(16, 16)
        pipette_area_btn.setCursor(Qt.ArrowCursor)
        pipette_area_btn.setFlat(True)
        pipette_area_btn.setToolTip("Piocher la couleur moyenne d'une zone de l'ecran")
        pipette_area_btn.clicked.connect(lambda: self._on_pipette(_AreaEyedropperOverlay))
        head_l.addWidget(pipette_area_btn)
        close_btn = _PickerCloseButton(M["label_dim"])
        close_btn.setFixedSize(16, 16)
        close_btn.setCursor(Qt.ArrowCursor)
        close_btn.setFlat(True)
        close_btn.clicked.connect(self._on_cancel)
        head_l.addWidget(close_btn)
        outer.addWidget(head)

        # -- corps --
        body = QVBoxLayout()
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(12)

        self.pad = _SVPad(width=276)
        self.pad.changed.connect(self._on_sv)
        body.addWidget(self.pad)

        hsl_row = QVBoxLayout()
        hsl_row.setSpacing(8)
        self._hsl_rows = []
        for i, (label, unit) in enumerate((("Teinte", "°"), ("Saturation", "%"), ("Luminosite", "%"))):
            row, slider, val_label = self._make_row(label, unit)
            slider.changed.connect(lambda f, idx=i: self._on_hsl(idx, f))
            self._hsl_rows.append((slider, val_label))
            hsl_row.addLayout(row)
        body.addLayout(hsl_row)

        body.addWidget(self._divider())

        body.addWidget(self._tag_label("COMPOSANTES RVB"))
        rgb_col = QVBoxLayout()
        rgb_col.setSpacing(8)
        self._rgb_rows = []
        for i, label in enumerate(("Rouge", "Vert", "Bleu")):
            row, slider, val_label = self._make_row(label, "")
            slider.changed.connect(lambda f, idx=i: self._on_rgb(idx, f))
            self._rgb_rows.append((slider, val_label))
            rgb_col.addLayout(row)
        body.addLayout(rgb_col)

        body.addWidget(self._divider())

        # -- Alpha (transparence, voir la remarque de l'utilisateur, "un
        # parametre de transparence des couleurs dans le selecteur") —
        # MEME ligne/MEME slider que Teinte/Saturation/... (_make_row/
        # _GradientSlider), degrade transparent -> couleur pleine pour
        # visualiser l'effet, damier dessous (voir _paint_checkerboard)
        # pour que la moitie transparente du degrade reste lisible.
        body.addWidget(self._tag_label("TRANSPARENCE"))
        alpha_row, alpha_slider, alpha_val = self._make_row("Alpha", "%", checkerboard=True)
        alpha_slider.changed.connect(self._on_alpha)
        self._alpha_slider, self._alpha_val = alpha_slider, alpha_val
        body.addLayout(alpha_row)

        body.addWidget(self._divider())

        # -- avant/apres + hex --
        # Habille "comme un tableau" (voir la remarque de l'utilisateur,
        # capture annotee a l'appui) : memes primitives _TableFrame/
        # _restyle_table_row que les VRAIS tableaux de cette fenetre
        # (Polices/Entetes/Geometrie) — cadre exterieur a filet unique,
        # coins arrondis PORTES par les lignes elles-memes (ici "avant" en
        # haut, "apres" en bas, exactement comme la premiere/derniere ligne
        # d'un tableau sans entete — voir la table Entetes), et un seul
        # filet 1px entre les deux lignes (le border-top que
        # _restyle_table_row ajoute deja automatiquement pour toute ligne
        # non "first").
        hex_row = QHBoxLayout()
        hex_row.setSpacing(9)
        stacked, stacked_l = _table_frame()
        stacked.setFixedSize(58, 34)
        stacked.setRadius(self._input_radius)
        self._before_swatch = QWidget()
        self._before_swatch.setObjectName("TableRow")
        self._before_swatch.setAttribute(Qt.WA_StyledBackground, True)
        self._after_swatch = QWidget()
        self._after_swatch.setObjectName("TableRow")
        self._after_swatch.setAttribute(Qt.WA_StyledBackground, True)
        stacked_l.addWidget(self._before_swatch, 1)
        stacked_l.addWidget(self._after_swatch, 1)
        hex_row.addWidget(stacked)

        hex_box = QWidget()
        hex_box.setFixedHeight(34)
        hex_box.setObjectName("HexBox")
        hex_box.setAttribute(Qt.WA_StyledBackground, True)
        hex_box.setStyleSheet(
            f"#HexBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._input_radius}px; }}"
        )
        hex_l = QHBoxLayout(hex_box)
        hex_l.setContentsMargins(9, 0, 9, 0)
        hex_l.setSpacing(9)
        hex_tag = QLabel("HEX")
        _set_text_role(hex_tag, "hex_tag")
        hex_l.addWidget(hex_tag)
        self.hex_edit = QLineEdit()
        self.hex_edit.setFont(_qfont(13, 400, mono=True))
        self.hex_edit.setFrame(False)
        # setFrame(False) desactive seulement le cadre NATIF Qt — le QSS
        # global de l'appli (QLineEdit { border: ... }) continue de
        # s'appliquer par-dessus tant que "border" n'est pas explicitement
        # ecrase ici, d'ou ce filet visible autour du champ hex en plus de
        # celui de HexBox qui l'entoure deja — voir la remarque de
        # l'utilisateur, capture annotee a l'appui ("pas de bordure").
        self.hex_edit.setStyleSheet(f"background: transparent; border: none; color: {M['value_fg']};")
        self.hex_edit.editingFinished.connect(self._on_hex_edited)
        hex_l.addWidget(self.hex_edit, 1)
        hex_row.addWidget(hex_box, 1)
        body.addLayout(hex_row)

        outer.addLayout(body)

        # -- bas --
        foot = QWidget()
        foot.setFixedHeight(40)
        foot.setStyleSheet(f"background: {M['toolbar_bg']}; border-top: 1px solid {M['panel_border']};")
        foot_l = QHBoxLayout(foot)
        foot_l.setContentsMargins(12, 0, 12, 0)
        foot_l.setSpacing(6)
        reset_btn = _Btn("Reinitialiser", "transparent", M["btn_border"], M["reset_fg"], M["btn_bg"],
                          height=25, padding="0 10px")
        reset_btn.clicked.connect(self._on_reset)
        foot_l.addWidget(reset_btn)
        foot_l.addStretch(1)
        cancel_btn = _Btn("Annuler", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        cancel_btn.clicked.connect(self._on_cancel)
        foot_l.addWidget(cancel_btn)
        # Pas de bordure (voir la remarque de l'utilisateur, capture
        # annotee a l'appui, "supprime bordure") — fond plein uniquement,
        # comme un bouton primaire de l'appli principale.
        ok_btn = _Btn("Valider", M["accent"], "", M["accent_fg"], M["accent_hover"],
                      height=25, weight=600, padding="0 14px")
        ok_btn.clicked.connect(self._on_commit)
        foot_l.addWidget(ok_btn)
        outer.addWidget(foot)

        self._refresh_all()

    # -- construction --

    def _tag_label(self, text: str) -> QLabel:
        label = QLabel(text)
        _set_text_role(label, "tag")
        return label

    def _divider(self) -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {M['edge_off']};")
        return line

    def _make_row(self, label: str, unit: str, checkerboard: bool = False):
        row = QHBoxLayout()
        row.setSpacing(9)
        name = QLabel(label)
        name.setFixedWidth(70)
        _set_text_role(name, "inline_label")
        row.addWidget(name)
        slider = _GradientSlider(checkerboard=checkerboard)
        row.addWidget(slider, 1)
        # Espace visible avant la boite de valeur (en plus des 9px de
        # row.setSpacing deja appliques) : le curseur du slider pouvait
        # quasiment toucher la boite en fin de course — voir la remarque
        # de l'utilisateur, capture annotee a l'appui ("reduire la zone de
        # saisie pour avoir un espace"). Boite retrecie (60, pas 64) pour
        # compenser et garder le popup a la meme largeur totale.
        row.addSpacing(10)
        box = QWidget()
        box.setFixedSize(60, 22)
        box.setObjectName("ValBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        # C'est une zone de saisie comme les autres : meme rayon que hex_box
        # (self._input_radius) — voir la remarque de l'utilisateur, capture
        # annotee a l'appui ("zone de saisie donc arrondie les angles").
        box.setStyleSheet(
            f"#ValBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._input_radius}px; }}"
        )
        box_l = QHBoxLayout(box)
        box_l.setContentsMargins(9, 0, 9, 0)
        box_l.setSpacing(2)
        val_label = QLabel("0")
        _set_text_role(val_label, "value_mono")
        val_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        box_l.addWidget(val_label, 1)
        if unit:
            unit_label = QLabel(unit)
            _set_text_role(unit_label, "unit")
            box_l.addWidget(unit_label)
        row.addWidget(box)
        return row, slider, val_label

    # -- etat --

    def _current_hex(self) -> str:
        return _with_alpha(_rgb_to_hex(_hsv_to_rgb(self._h, self._s, self._v)), self._a)

    def _refresh_all(self):
        rgb = _hsv_to_rgb(self._h, self._s, self._v)
        hexval = _rgb_to_hex(rgb)
        # hexval_a (PAS hexval) : c'est CETTE valeur, alpha inclus, qui
        # sort du popup (apercu apres/hex_edit/signal emis) — voir
        # _current_hex, MEME regle (opaque reste "#rrggbb").
        hexval_a = _with_alpha(hexval, self._a)
        self.pad.setHue(self._h)
        self.pad.setSV(self._s, self._v)

        hue_slider, hue_val = self._hsl_rows[0]
        hue_slider.setStops([
            (0.0, "#ff0000"), (1 / 6, "#ffff00"), (2 / 6, "#00ff00"),
            (3 / 6, "#00ffff"), (4 / 6, "#0000ff"), (5 / 6, "#ff00ff"), (1.0, "#ff0000"),
        ])
        hue_slider.setFraction(self._h / 360)
        hue_val.setText(str(round(self._h)))

        sat_slider, sat_val = self._hsl_rows[1]
        sat_slider.setStops([
            (0.0, _rgb_to_hex(_hsv_to_rgb(self._h, 0.0, self._v))),
            (1.0, _rgb_to_hex(_hsv_to_rgb(self._h, 1.0, self._v))),
        ])
        sat_slider.setFraction(self._s)
        sat_val.setText(str(round(self._s * 100)))

        lum_slider, lum_val = self._hsl_rows[2]
        lum_slider.setStops([(0.0, "#000000"), (1.0, _rgb_to_hex(_hsv_to_rgb(self._h, self._s, 1.0)))])
        lum_slider.setFraction(self._v)
        lum_val.setText(str(round(self._v * 100)))

        for i, (slider, val_label) in enumerate(self._rgb_rows):
            lo, hi = list(rgb), list(rgb)
            lo[i], hi[i] = 0, 255
            slider.setStops([(0.0, _rgb_to_hex(lo)), (1.0, _rgb_to_hex(hi))])
            slider.setFraction(rgb[i] / 255)
            val_label.setText(str(rgb[i]))

        # Degrade transparent (alpha 0) -> couleur PLEINE (alpha 255) de la
        # teinte COURANTE — MEME hexval (opaque) que les stops RVB
        # ci-dessus, juste rejoue avec chaque alpha via _with_alpha.
        self._alpha_slider.setStops([(0.0, _with_alpha(hexval, 0)), (1.0, _with_alpha(hexval, 255))])
        self._alpha_slider.setFraction(self._a / 255)
        self._alpha_val.setText(str(round(self._a / 255 * 100)))

        # Habille comme les 2 lignes d'un vrai tableau sans entete de cette
        # fenetre (voir _restyle_table_row/la table Entetes, meme
        # technique) : "avant" = premiere ligne (porte le rayon HAUT du
        # cadre), "apres" = derniere ligne (porte le rayon BAS, et le seul
        # filet horizontal separant les deux, ajoute automatiquement par
        # _restyle_table_row pour toute ligne non "first") — voir la
        # remarque de l'utilisateur, capture annotee a l'appui ("comme un
        # tableau").
        _restyle_table_row(self._before_swatch, self._before, first=True, top_radius=self._input_radius)
        _restyle_table_row(self._after_swatch, hexval_a, first=False, bottom_radius=self._input_radius)
        if self.hex_edit.text().lower() != hexval_a:
            cursor = self.hex_edit.cursorPosition()
            self.hex_edit.setText(hexval_a)
            self.hex_edit.setCursorPosition(min(cursor, len(hexval_a)))

        self.colorChanged.emit(hexval_a)

    # -- interactions --

    def _on_sv(self, s: float, v: float):
        self._s, self._v = s, v
        self._refresh_all()

    def _on_hsl(self, idx: int, frac: float):
        if idx == 0:
            self._h = frac * 360
        elif idx == 1:
            self._s = frac
        else:
            self._v = frac
        self._refresh_all()

    def _on_rgb(self, idx: int, frac: float):
        rgb = list(_hsv_to_rgb(self._h, self._s, self._v))
        rgb[idx] = round(frac * 255)
        self._h, self._s, self._v = _rgb_to_hsv(*rgb)
        self._refresh_all()

    def _on_alpha(self, frac: float):
        self._a = round(max(0.0, min(1.0, frac)) * 255)
        self._refresh_all()

    def _on_hex_edited(self):
        text = self.hex_edit.text().strip()
        if not text.startswith("#"):
            text = "#" + text
        # 7 chiffres ("#rrggbb", opaque) OU 9 ("#aarrggbb", voir _with_
        # alpha/app_style._hex_to_alpha) — voir la remarque de
        # l'utilisateur, "un parametre de transparence des couleurs dans
        # le selecteur".
        if len(text) in (7, 9):
            try:
                int(text[1:], 16)
            except ValueError:
                pass
            else:
                self._h, self._s, self._v = _hex_to_hsv(text)
                self._a = _hex_to_alpha(text)
        self._refresh_all()

    def _on_reset(self):
        self._h, self._s, self._v = _hex_to_hsv(self._before)
        self._a = _hex_to_alpha(self._before)
        self._refresh_all()

    def _on_pipette(self, overlay_cls):
        # Le popup reste ouvert mais s'efface le temps de la capture, pour
        # ne pas se piocher lui-meme comme couleur. _pipette_active evite
        # que ce hide() soit interprete comme une validation par
        # hideEvent (voir sa remarque : hide() = clic dehors = commit).
        self._pipette_active = True
        self.hide()
        # Ce popup est une fenetre Qt.Popup : elle detient un grab souris
        # implicite tant qu'elle est visible. hide() le relache, mais Qt
        # ne finalise cette liberation qu'au retour dans la boucle
        # d'evenements — creer/afficher l'overlay de capture (qui doit
        # lui-meme recevoir les clics) DANS ce meme cycle d'evenement (le
        # slot du clic sur le bouton pipette) le fait echouer silencieuse-
        # ment : l'overlay s'affiche mais ne recoit rien. D'ou ce
        # singleShot(0, ...), qui reporte sa creation au prochain passage
        # de la boucle, une fois le grab du popup vraiment libere.
        QTimer.singleShot(0, lambda: self._launch_pipette(overlay_cls))

    def _launch_pipette(self, overlay_cls):
        overlay = overlay_cls()
        self._active_overlay = overlay   # garde une reference forte (sinon GC Python possible)
        overlay.picked.connect(self._on_pipette_picked)
        overlay.cancelled.connect(self._on_pipette_cancelled)
        overlay.destroyed.connect(lambda *_: self._show_after_pipette())
        overlay.show()
        overlay.raise_()
        overlay.activateWindow()
        overlay.setFocus(Qt.ActiveWindowFocusReason)

    def _show_after_pipette(self):
        self._active_overlay = None
        self._pipette_active = False
        if not self._resolved:
            self.show()

    def _on_pipette_picked(self, hexval: str):
        self._h, self._s, self._v = _hex_to_hsv(hexval)
        self._refresh_all()

    def _on_pipette_cancelled(self):
        pass

    def _on_cancel(self):
        if self._resolved:
            return
        self._resolved = True
        self.cancelled.emit()
        self.close()

    def _on_commit(self):
        if self._resolved:
            return
        self._resolved = True
        hexval = self._current_hex()
        self.committed.emit(hexval)
        self.close()

    def hideEvent(self, event):
        # Un clic EN DEHORS du popup ferme un widget Qt.Popup directement
        # via hide() (pas close()/closeEvent — verifie sur ce Qt : le
        # gestionnaire de popups de Qt appelle QWidget::hide() en
        # interne), d'ou hideEvent plutot que closeEvent ici — ce cas vaut
        # validation de la couleur affichee, plus intuitif qu'une
        # annulation silencieuse pendant qu'on ajustait un slider (voir la
        # remarque de tete de classe). _resolved evite un double signal
        # quand Valider/Annuler vient d'etre clique juste avant (close()
        # declenche aussi hide()) — et gere donc les DEUX chemins de
        # fermeture avec cette seule methode.
        if not self._resolved and not getattr(self, "_pipette_active", False):
            self._resolved = True
            hexval = self._current_hex()
            self.committed.emit(hexval)
        super().hideEvent(event)

    # -- redimensionnement (bord droit) --

    def _on_resize_edge(self, pos) -> bool:
        return self.width() - self._RESIZE_MARGIN <= pos.x() <= self.width()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_resize_edge(event.position().toPoint()):
            self._resizing = True
            self._resize_start_x = event.globalPosition().toPoint().x()
            self._resize_start_width = self.width()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            delta = event.globalPosition().toPoint().x() - self._resize_start_x
            new_width = max(self._MIN_WIDTH, min(self._MAX_WIDTH, self._resize_start_width + delta))
            self.resize(new_width, self.height())
            event.accept()
            return
        cursor = Qt.SizeHorCursor if self._on_resize_edge(event.position().toPoint()) else Qt.ArrowCursor
        self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Le carre SV et les sliders TSL/RVB (voir _make_row, stretch=1)
        # suivent la nouvelle largeur ; la hauteur du carre reste fixe (pas
        # demandee par l'utilisateur, seule la precision HORIZONTALE des
        # sliders est en jeu).
        if hasattr(self, "pad"):
            self.pad.setFixedWidth(max(1, self.width() - 24))

    def show_near(self, widget: QWidget):
        self.adjustSize()
        pos = widget.mapToGlobal(QPoint(0, widget.height() + 4))
        screen = QApplication.screenAt(widget.mapToGlobal(QPoint(0, 0))) or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            pos.setX(max(avail.left(), min(pos.x(), avail.right() - self.width())))
            pos.setY(max(avail.top(), min(pos.y(), avail.bottom() - self.height())))
        self.move(pos)
        self.show()
        # Sans ca, sur Windows 11 le compositeur DWM impose son propre
        # arrondi par defaut a CETTE fenetre (frameless de premier niveau,
        # voir Qt.Popup ci-dessus) par-dessus le perimetre bien carre (0px)
        # deja peint cote QSS — et pas force ment de facon uniforme sur les
        # 4 coins (constate : parfois un seul coin visiblement arrondi,
        # voir la remarque de l'utilisateur, capture annotee a l'appui,
        # "pourquoi souvent tu mets des bordures juste sur 1 coin"). Meme
        # correctif que SettingsWindow._apply_panel_radius : redemander
        # explicitement DONOTROUND cote DWM (winId() n'existe qu'apres
        # show(), d'ou l'appel ICI et pas dans __init__).
        apply_dwm_frame(self, 0, M["panel_border"])

def _apply_stylesheet_cached(widget: QWidget, stylesheet: str) -> None:
    """Remplace un setStyleSheet direct : n'appelle rien si le CSS calcule
    est identique au dernier applique a CE widget. Qt ne fait pas ce
    filtrage lui-meme (un setStyleSheet(memes_octets) redeclenche quand
    meme tout le recalcul de style, y compris en cascade sur les
    descendants d'un widget qui en a beaucoup, mesure a plusieurs ms meme
    pour un tableau de taille moyenne — voir _PanelFrame, meme constat en
    pire pour la fenetre entiere). Utile partout ou une valeur reglable
    (rayon, couleur de tableau...) est reappliquee en boucle a chaque
    glisser d'un slider de couleur (voir SettingsWindow._refresh_dynamic_
    colors) alors qu'elle n'a en realite pas change : la plupart des
    tableaux/lignes stylises ici ne dependent PAS de la couleur en cours
    d'edition — voir la remarque de l'utilisateur sur la latence."""
    if getattr(widget, "_cached_stylesheet", None) == stylesheet:
        return
    widget._cached_stylesheet = stylesheet
    widget.setStyleSheet(stylesheet)

# Opacite d'un widget/champ INACTIF (voir _set_dimmed) — auparavant 0.35
# (voir _CellPaddingField/_CornerRadiusField.setLinked, seuls endroits a
# deja utiliser ce mecanisme) : encore trop percu comme "actif" — voir la
# remarque de l'utilisateur, "je veux que les parametres inactifs (grise)
# soit encore moins perceptibles ... generalise ca pour tous les elements
# inactif/grise".
_DIMMED_OPACITY = 0.2

def _set_dimmed(widget: QWidget, dimmed: bool) -> None:
    """setEnabled(not dimmed) + un QGraphicsOpacityEffect a _DIMMED_OPACITY
    (PAS le simple estompage :disabled de Qt, trop discret sur des widgets
    peints a la main comme _MiniSlider/_Toggle/les pastilles de couleur,
    qui ne suivent de toute facon PAS QPalette) — MEME technique deja
    utilisee par _CellPaddingField/_CornerRadiusField.setLinked, desormais
    GENERALISEE a tout champ/bouton "grise" de cette fenetre (le bouton "Copier" retire depuis, voir _build_linked_sides_toggle,
    pastilles de _SideColorsField, sliders d'_OverrideSmoothingField...) —
    voir la remarque de l'utilisateur ci-dessus. Reutilise le graphics
    effect deja pose sur ce widget s'il y en a un (evite d'en empiler un
    nouveau a chaque appel)."""
    widget.setEnabled(not dimmed)
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(_DIMMED_OPACITY if dimmed else 1.0)

# Dimensions enregistrees des tableaux : {cle (voir _TableFrame.dimsKey): {"width": int, "cols": [..]}}.
_TABLE_DIMS: dict = {}

def _set_table_dims(dims: dict) -> None:
    _TABLE_DIMS.clear()
    _TABLE_DIMS.update(dims or {})

class _TableEdgeGrip(QWidget):
    """Poignee invisible sur la bordure droite d'un tableau : glisser change
    la largeur du tableau (curseur de redimensionnement au survol)."""

    WIDTH = 6

    def __init__(self, frame: "_TableFrame"):
        super().__init__(frame)
        self._frame = frame
        self._start_x = 0
        self._start_w = 0
        self._dragging = False
        self.setCursor(Qt.SizeHorCursor)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._start_x = event.globalPosition().toPoint().x()
            self._start_w = self._frame.width()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        frame = self._frame
        parent = frame.parentWidget()
        avail = (parent.contentsRect().right() + 1 - frame.x()) if parent is not None else 4000
        width = self._start_w + event.globalPosition().toPoint().x() - self._start_x
        width = max(frame.minimumSizeHint().width(), min(width, avail))
        frame.setTableWidth(0 if width >= avail - 2 else width)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()

class _TableFrame(QWidget):
    """Cadre exterieur complet (perimetre 1px) d'un tableau — entete et
    lignes empilees a l'interieur, separees seulement par un filet
    horizontal (voir _table_header/_table_row), jamais par des boites
    individuelles : un tableau bien "ferme" (un seul rectangle), pas une
    pile de rectangles accoles (voir la remarque de l'utilisateur, capture
    a l'appui — les tableaux Polices/Geometrie avaient chacun leur propre
    filet gauche/droite/bas, un empilement qui pouvait paraitre "ouvert").

    Suit en direct le slider Geometrie > Tableaux > Coins arrondis (voir
    setRadius), mais UNIQUEMENT pour son propre filet 1px : l'entete et les
    lignes a l'interieur gardent chacune leur propre fond plein (couleurs
    alternees, WA_StyledBackground) que ce border-radius ne touche jamais
    (un border-radius QSS n'arrondit que le PROPRE fond/bordure du widget,
    jamais celui de ses enfants). Une premiere version decoupait tout le
    contenu au masque (QRegion/setMask) pour compenser — mais un masque est
    un decoupage BINAIRE, non anti-aliase : le filet du cadre (lui bien
    arrondi en douceur par le QSS) se retrouvait recoupe au pixel pres par
    ce masque grossier, d'ou des bordures qui ne suivaient plus vraiment la
    courbe (voir la remarque de l'utilisateur, capture a l'appui). Corrige
    en arrondissant plutot CHAQUE piece a l'endroit exact ou elle touche un
    coin (les coins hauts de l'entete/de la premiere ligne si l'entete est
    absente, les coins bas de la derniere ligne — voir
    SettingsWindow._apply_table_radius et ses homologues par tableau), qui
    reste un rendu QSS natif, donc aussi lisse que le filet du cadre."""

    # Une dimension du tableau a change (largeur du tableau, d'une colonne, d'une
    # cellule...) : la fenetre qui le souhaite enregistre alors tout de suite.
    dimsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TableFrame")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._radius = 0
        # Bordure (voir setBorder/Tableaux > Bordure) : valeurs de depart
        # identiques a l'ancien "1px solid" fixe code en dur ici, pour ne
        # rien changer visuellement tant que SettingsWindow._apply_table_
        # border n'a pas encore rejoue les reglages reels (1er appel, meme
        # convention que _ColumnPreview._border_enabled/_border_colors).
        self._border_enabled = {k: True for k in ("top", "right", "bottom", "left")}
        self._border_colors = {k: M["panel_border"] for k in ("top", "right", "bottom", "left")}
        self._border_thickness = 1
        self._dims_applied = False
        self._grip = _TableEdgeGrip(self)
        self._refresh_style()

    # -- Largeur du tableau (bordure droite agrippable) + dimensions enregistrees --

    def setWidthResizable(self, enabled: bool):
        self._grip.setVisible(bool(enabled))

    def tableWidth(self) -> int:
        """Largeur imposee (0 = pleine largeur disponible)."""
        w = self.maximumWidth()
        return 0 if w >= 16777215 else w

    def setTableWidth(self, width: int):
        width = int(width) if width and int(width) > 0 else 0
        self.setMaximumWidth(width or 16777215)
        self._align_left(bool(width))
        self.updateGeometry()
        self.dimsChanged.emit()

    def sizeHint(self):
        hint = super().sizeHint()
        width = self.tableWidth()
        if width:
            hint.setWidth(width)
        return hint

    def _align_left(self, on: bool):
        """Un tableau plus etroit que sa zone se colle a GAUCHE (au niveau du
        titre de sa section) au lieu d'etre centre par le layout."""
        flags = Qt.AlignLeft if on else Qt.Alignment()

        def apply(layout) -> bool:
            if layout is None:
                return False
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget() is self:
                    item.setAlignment(flags)
                    return True
                if apply(item.layout()):
                    return True
            return False

        parent = self.parentWidget()
        if parent is not None:
            apply(parent.layout())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._grip.setGeometry(self.width() - _TableEdgeGrip.WIDTH, 0, _TableEdgeGrip.WIDTH, self.height())
        self._grip.raise_()

    def dimsKey(self) -> str:
        """Cle stable : titres des sections ancetres + rang parmi les tableaux de la section."""
        titles = []
        node = self.parentWidget()
        owner = None
        while node is not None:
            title = getattr(node, "_title_text", None)
            if title:
                titles.append(title)
                owner = owner or node
            node = node.parentWidget()
        rank = 0
        if owner is not None:
            frames = [f for f in owner.findChildren(_TableFrame)]
            rank = frames.index(self) if self in frames else 0
        return "/".join(reversed(titles)) + f"#{rank}"

    def _dims_children(self):
        head, resizer = None, None
        for child in self.findChildren(QWidget):
            if head is None and hasattr(child, "setColumnWidths"):
                head = child
            if resizer is None and getattr(child, "_flat_resizer", None) is not None:
                resizer = child._flat_resizer
        return head, resizer

    def collectDims(self) -> dict:
        head, resizer = self._dims_children()
        dims: dict = {"width": self.tableWidth()}
        if head is not None:
            dims["cols"] = head.columnWidths()
        elif resizer is not None:
            dims["cols"] = [resizer.width()]
        extra = getattr(self, "_extra_dims", None)     # tableaux a cellules : justifications, cellules divisees
        if extra is not None:
            dims.update(extra.collect())
        return dims

    def applyDims(self, dims: dict):
        head, resizer = self._dims_children()
        cols = dims.get("cols") or []
        if head is not None and cols:
            head.setColumnWidths(cols)
        elif resizer is not None and cols:
            resizer.setWidth(int(cols[0]))
        extra = getattr(self, "_extra_dims", None)
        if extra is not None:
            extra.apply(dims)
        self.setTableWidth(int(dims.get("width", 0) or 0))

    def showEvent(self, event):
        super().showEvent(event)
        if not self._dims_applied:
            self._dims_applied = True
            dims = _TABLE_DIMS.get(self.dimsKey())
            if dims:
                self.applyDims(dims)
            # Branche APRES la restauration (elle ne doit pas se reenregistrer) : une
            # colonne tiree a la main previent la fenetre.
            head, resizer = self._dims_children()
            if head is not None:
                head.resized.connect(lambda *_a: self.dimsChanged.emit())
            elif resizer is not None:
                resizer.resized.connect(lambda *_a: self.dimsChanged.emit())

    def _refresh_style(self):
        t = self._border_thickness

        def edge(side: str) -> str:
            # "0px solid transparent", PAS "none" — meme raison que
            # column_frame_qss/header_qss : "none" ferait deborder le fond
            # carre au coin arrondi, la ou une bordure a epaisseur nulle
            # (mais toujours "solid") reste correctement decoupee par le
            # border-radius du meme cote.
            if t <= 0 or not self._border_enabled.get(side, True):
                return "0px solid transparent"
            return f"{t}px solid {self._border_colors.get(side, M['panel_border'])}"

        _apply_stylesheet_cached(
            self,
            f"#TableFrame {{ border-top: {edge('top')}; border-right: {edge('right')}; "
            f"border-bottom: {edge('bottom')}; border-left: {edge('left')}; "
            f"border-radius: {self._radius}px; }}"
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_style()

    def setBorder(self, enabled: dict, colors: dict, thickness: int):
        """Tableaux > Bordure (voir _ToggleSideColorsField, MEME widget que
        Toggles > Cadre/Coche > Bordure et Colonnes > Bordure) — voir la
        remarque de l'utilisateur, "ajoute dans la section tableau un
        parametre bordure comme celui des toggles"."""
        self._border_enabled = {k: bool(enabled.get(k, True)) for k in ("top", "right", "bottom", "left")}
        self._border_colors = {k: colors.get(k) or M["panel_border"] for k in ("top", "right", "bottom", "left")}
        self._border_thickness = max(0, int(thickness))
        self._refresh_style()

def _table_frame() -> tuple[QWidget, QVBoxLayout]:
    frame = _TableFrame()
    layout = QVBoxLayout(frame)
    # Marge de 1px (= l'epaisseur du filet de #TableFrame), PAS 0 : a marge
    # nulle, l'entete/les lignes (chacun avec son propre fond peint via
    # WA_StyledBackground) recouvrent exactement le filet du cadre et le
    # rendent invisible — meme bug, meme correctif que #Panel dans
    # SettingsWindow.__init__ (voir la remarque de l'utilisateur, capture
    # a l'appui : le cadre etait bel et bien absent a l'ecran).
    layout.setContentsMargins(1, 1, 1, 1)
    layout.setSpacing(0)
    return frame, layout

# Bordures interieures des tableaux (voir SettingsWindow, Tableaux > Bordure
# interieure H/V) : lues par _restyle_table_row/_restyle_table_head (H) et par
# _TableRow/_ResizableTableHeader.paintEvent (V).
_TABLE_INNER_BORDER: dict = {
    "h": {"enabled": True, "color": "", "thickness": 1},
    "v": {"enabled": False, "color": "", "thickness": 1},
}

def _set_table_inner_border(h: tuple, v: tuple) -> None:
    """h, v : (actif, couleur hex, epaisseur)."""
    for key, (enabled, color, thickness) in (("h", h), ("v", v)):
        _TABLE_INNER_BORDER[key] = {"enabled": bool(enabled), "color": color, "thickness": max(0, int(thickness))}

def _inner_h_edge() -> str:
    """Filet horizontal interieur en QSS ("0px solid transparent" plutot que
    "none", meme raison que _TableFrame._refresh_style)."""
    h = _TABLE_INNER_BORDER["h"]
    if h["thickness"] <= 0 or not h["enabled"]:
        return "0px solid transparent"
    return f"{h['thickness']}px solid {h['color'] or M['panel_border']}"

def _paint_inner_vlines(widget: QWidget, xs: list[int]) -> None:
    """Filets verticaux interieurs de `widget` aux abscisses `xs` (bords
    gauches des cellules, hors premiere colonne : jamais ceux des extremites)."""
    v = _TABLE_INNER_BORDER["v"]
    if not v["enabled"] or v["thickness"] <= 0 or not xs:
        return
    p = QPainter(widget)
    color = QColor(v["color"] or M["panel_border"])
    for x in xs:
        p.fillRect(x - v["thickness"] // 2, 0, v["thickness"], widget.height(), color)
    p.end()

class _TableRow(QWidget):
    """Ligne de tableau : fond/filets H en QSS (voir _restyle_table_row), filets
    V peints ici entre ses cellules (widgets nommes "TableCell", voir
    _table_cell) ou a `_v_boundary()` (tableaux libelle/controle)."""

    def event(self, event):
        handled = super().event(event)
        # Les filets V sont peints a la position des cellules : apres un
        # redimensionnement de colonne, le layout deplace les cellules APRES
        # coup, et Qt ne repeint que leurs propres rectangles (jamais le filet,
        # dans l'espacement entre deux). On repeint donc toute la ligne une fois
        # le layout passe (le layout a deja traite LayoutRequest ici).
        if event.type() in (QEvent.LayoutRequest, QEvent.Resize):
            self.update()
        return handled

    def paintEvent(self, event):
        super().paintEvent(event)
        head = getattr(self, "_sel_head", None)
        if head is not None and head._selected:
            p = QPainter(self)
            for i, (left, edge) in enumerate(head._column_spans()):
                if i in head._selected:
                    p.fillRect(left, 0, edge - left, self.height(), QColor(95, 155, 208, 40))
            p.end()
        boundary = getattr(self, "_v_boundary", None)
        if boundary is not None:
            xs = [boundary()]
        else:
            cells = sorted((c for c in self.children()
                            if isinstance(c, QWidget) and c.objectName() == "TableCell"),
                           key=lambda c: c.x())
            xs = [c.x() for c in cells[1:]]
        _paint_inner_vlines(self, xs)

def _restyle_table_row(row: QWidget, bg: str, first: bool, top_radius: int = 0, bottom_radius: int = 0):
    """(Re)applique le fond/filet/coins d'une ligne de donnees. `top_radius`
    n'est utile que pour la toute premiere ligne d'un tableau SANS entete
    (elle touche alors elle-meme le coin haut du cadre — voir la table
    Entetes) ; `bottom_radius` seulement pour la toute derniere ligne (elle
    touche toujours le coin bas du cadre, entete ou pas) — voir
    SettingsWindow._apply_table_radius et homologues, qui recalculent ces
    deux valeurs a chaque cran du slider Geometrie > Tableaux."""
    border = "" if first else f"border-top: {_inner_h_edge()};"
    _apply_stylesheet_cached(
        row,
        f"#TableRow {{ background: {bg}; {border} "
        f"border-top-left-radius: {top_radius}px; border-top-right-radius: {top_radius}px; "
        f"border-bottom-left-radius: {bottom_radius}px; border-bottom-right-radius: {bottom_radius}px; }}",
    )

# ==========================================================================
# Section "Entetes" — hauteur / couleur (choisie parmi les 8 pastilles
# semantiques) / rayon des angles / cadre par cote.
# ==========================================================================

_SLOT_LABELS = {slot: label for slot, _real, label in SEMANTIC_COLOR_SLOTS}

class _AppOrCustomColorField(QWidget):
    """GABARIT "couleur" (voir la remarque de l'utilisateur, "TOUTES LES
    LIGNES COULEUR ... Toggles pour choix de couleur Appli ou couleur
    personnalisee. les textes des toggles doivent etre devant les toggles
    correspondant et etre 'Couleur application' et 'Couleur systeme' ...
    les items de la liste deroulante des couleurs applications devront
    etre dans l'ordre alphabetique") — MEME mecanique exclusive que
    _DualFontSelectField (app/systeme) transposee aux couleurs : toggle
    "Couleur application" + liste deroulante des pastilles semantiques
    (SEMANTIC_COLOR_SLOTS, triees par LABEL alphabetique pour l'affichage
    seulement — la liste partagee elle-meme reste dans son ordre de
    lecture 2 colonnes, voir sa remarque de tete dans app_style.py) OU
    toggle "Couleur systeme" + pastille cliquable ouvrant le popup HSL/RVB/
    hex habituel (_ColorPickerPopup) — utilisee par _SideColorsField
    (bordures de Toggles/Sliders).

    Valeur stockee (voir value()/setValue()) : une chaine hex "#rrggbb"
    (couleur personnalisee) OU "@<slot>" (reference a une pastille
    semantique) — format INCHANGE, retro-compatible avec les presets
    existants."""

    changed = Signal(str)

    def __init__(self, value: str, colors: dict, swatch_size: int = 20, title: str = "Couleur", parent=None):
        super().__init__(parent)
        self._value = value
        self._colors = colors
        self._title = title
        self._before_pick = value
        self._popup: _ColorPickerPopup | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._slot_options = sorted(SEMANTIC_COLOR_SLOTS, key=lambda t: t[2])
        self._slot_to_label = {slot: label for slot, _real, label in self._slot_options}
        self._label_to_slot = {label: slot for slot, _real, label in self._slot_options}
        labels = [label for _slot, _real, label in self._slot_options]

        is_slot = value.startswith("@")

        app_label = QLabel("Couleur application")
        _set_text_role(app_label, "choice_label")
        layout.addWidget(app_label)
        self.app_toggle = _Toggle(is_slot, show_label=False)
        layout.addWidget(self.app_toggle)
        current_label = self._slot_to_label.get(value[1:], labels[0]) if is_slot else labels[0]
        self.app_field = _SelectField(labels, current_label, width=170)
        layout.addWidget(self.app_field)

        system_label = QLabel("Couleur systeme")
        _set_text_role(system_label, "choice_label")
        layout.addWidget(system_label)
        self.system_toggle = _Toggle(not is_slot, show_label=False)
        layout.addWidget(self.system_toggle)
        self.swatch = _ColorSwatchButton()
        self.swatch.setFixedSize(swatch_size, swatch_size)
        self.swatch.clicked.connect(self._open_custom_picker)
        layout.addWidget(self.swatch)

        self.app_toggle.toggled.connect(self._on_app_toggled)
        self.system_toggle.toggled.connect(self._on_system_toggled)
        self.app_field.changed.connect(self._on_app_field_changed)
        self._refresh_dim()
        self._refresh()

    def _is_slot(self) -> bool:
        return self._value.startswith("@")

    def _resolved_hex(self) -> str:
        return _resolve_color_value(self._value, self._colors)

    def _refresh(self):
        hexval = self._resolved_hex()
        self.swatch.setColorHex(hexval)
        self.swatch.setToolTip(_SLOT_LABELS.get(self._value[1:], hexval) if self._is_slot() else hexval)

    def _refresh_dim(self):
        _set_dimmed(self.app_field, not self.app_toggle.isChecked())
        _set_dimmed(self.swatch, not self.system_toggle.isChecked())

    def _on_app_toggled(self, checked: bool):
        if checked:
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(False)
            self.system_toggle.blockSignals(False)
        elif not self.system_toggle.isChecked():
            # Au moins l'un des 2 doit rester actif (voir _DualFontSelectField,
            # MEME raison).
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(True)
            self.system_toggle.blockSignals(False)
        self._refresh_dim()
        if checked:
            self._select_slot(self._label_to_slot[self.app_field.value()])
        else:
            self.changed.emit(self._value)

    def _on_system_toggled(self, checked: bool):
        if checked:
            self.app_toggle.blockSignals(True)
            self.app_toggle.setChecked(False)
            self.app_toggle.blockSignals(False)
            if self._is_slot():
                # Bascule vers "Couleur systeme" : fige la couleur RESOLUE
                # courante comme point de depart personnalise (sinon la
                # valeur stockee resterait une reference "@slot" alors que
                # le toggle affiche desormais "systeme" — etat incoherent).
                self._value = self._resolved_hex()
                self._refresh()
        elif not self.app_toggle.isChecked():
            self.app_toggle.blockSignals(True)
            self.app_toggle.setChecked(True)
            self.app_toggle.blockSignals(False)
        self._refresh_dim()
        self.changed.emit(self._value)

    def _on_app_field_changed(self, label: str):
        if self.app_toggle.isChecked():
            self._select_slot(self._label_to_slot[label])

    def _select_slot(self, slot: str):
        self._value = f"@{slot}"
        self._refresh()
        self.changed.emit(self._value)

    def _open_custom_picker(self):
        if not self.system_toggle.isChecked():
            return
        self._before_pick = self._value
        popup = _ColorPickerPopup(self._resolved_hex(), self._title, self)
        self._popup = popup
        popup.colorChanged.connect(self._apply_custom_live)
        popup.committed.connect(self._apply_custom_live)
        popup.cancelled.connect(lambda: self._apply_custom_live(self._before_pick))
        popup.show_near(self.swatch)

    def _apply_custom_live(self, value: str):
        self._value = value
        self._refresh()
        self.changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        self._value = value
        is_slot = value.startswith("@")
        self.app_toggle.blockSignals(True)
        self.system_toggle.blockSignals(True)
        self.app_toggle.setChecked(is_slot)
        self.system_toggle.setChecked(not is_slot)
        self.app_toggle.blockSignals(False)
        self.system_toggle.blockSignals(False)
        if is_slot and value[1:] in self._slot_to_label:
            self.app_field.setValue(self._slot_to_label[value[1:]])
        self._refresh_dim()
        self._refresh()

    def refresh_colors(self, colors: dict):
        """A appeler quand la page Couleurs change (voir SettingsWindow.
        _on_colors_changed) : une pastille en mode "App" (voir _is_slot)
        doit suivre EN DIRECT la couleur reelle de sa pastille semantique."""
        self._colors = colors
        self._refresh()

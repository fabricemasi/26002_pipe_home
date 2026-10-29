"""Méthodes de colonne : habillage, en-tête et sélection."""

from pathlib import Path
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMessageBox, QPushButton
from app_style import font, scaled, resolve_color_ref, column_frame_style, column_header_qss, column_padding_for, column_style_for
import ui_state
from previews import software_icon_key
from settings_widgets import Menu, _radius_dict, _radius_shrink
from browser_core import ROLE_ISDIR, ROLE_PATH, _pin_icon_pixmap, _resolve_font_family, _update_layout_setting, col_width, load_layout_settings, save_layout_settings, software_choices, software_icon_pixmap
from capture_widgets import _column_suppress_left
from .shared import opens_in_viewer


class ColumnAppearanceMixin:
    def relayout(self, do_layout: bool = True):
        """Reapplique la mise en page (tailles de ligne) apres un changement
        de reglage purement cosmetique (police, hauteur de ligne...), SANS
        retourner sur le disque : le contenu deja charge (noms, tailles,
        vignettes) reste valable, seul son rendu change. Utilise par
        PipelineBrowser.refresh_all_columns(rescan=False), notamment pendant
        la previsualisation en direct de la fenetre de parametres, ou un
        column.refresh() complet (rescan du dossier, y compris le comptage
        recursif des colonnes a vignettes) serait rejoue a chaque cran de
        slider pour rien.

        `do_layout=False` (voir PipelineBrowser._apply_settings, qui compare
        col_row_height()/col_spacing() avant/apres apply_all_settings) saute
        le doItemsLayout() — le SEUL poste vraiment couteux ici (recalcule le
        sizeHint() de CHAQUE ligne visible) — quand ce cran de slider n'a
        PAS touche a la hauteur/l'espacement des lignes de CETTE colonne
        (couleur, bordure, rayon, padding de selection...)."""
        if do_layout:
            self.list.doItemsLayout()
            self.sync_bottom_gap()
    def refresh_colors(self):
        """Reapplique les couleurs (voir C, mutable via app_style.set_color)
        aux qss fixes une fois pour toutes a la construction — necessaire
        car un changement de couleur depuis la fenetre de parametres ne
        retouche pas les widgets deja construits (voir la remarque sur
        set_color dans app_style.py)."""
        # Style APPLIQUE POUR DE VRAI a TOUTE colonne desormais (voir
        # app_style.column_header_qss/column_frame_qss — le style general
        # Colonnes/Entetes, "Type" seule pouvant le SURCHARGER depuis
        # Colonnes > Type, voir SettingsWindow._build_column_type_page),
        # pas seulement l'apercu de la fenetre de parametres comme avant —
        # voir la remarque de l'utilisateur, "je veux que tu en fasse de
        # meme pour toute les colonnes de l'appli. les settings doivent
        # refletter a 100% ce qui se passe dans l'appli".
        self.header_fill.setStyleSheet(column_header_qss("ColumnHeader", self.style_title))
        frame = column_frame_style(self.style_title, self._suppress_left())
        # scaled() ICI, sur le MEME dict que celui repasse tel quel au
        # masque (voir _update_card_mask, qui relit self.card._radius
        # plutot que de recalculer independamment) : sans ca, peinture et
        # masque pouvaient utiliser 2 rayons LEGEREMENT differents des que
        # l'echelle d'interface (Application > Scale) n'est pas 100%.
        scaled_radius = {k: scaled(v, 0) for k, v in frame["radius"].items()}
        # scaled() sur l'epaisseur AUSSI (pas seulement le rayon ci-dessus) :
        # refresh_header reserve deja scaled(border_thickness) comme marge
        # pour cette bordure — la peindre ICI avec l'epaisseur BRUTE (non
        # scaled) desaccordait les deux des que l'echelle d'interface
        # (Application > Scale) n'est pas 100%, laissant un filet trop fin/
        # epais par rapport a la marge qui lui est reservee.
        self.card.setFrameStyle(
            frame["bg"], scaled_radius, frame["enabled"], frame["colors"], scaled(frame["thickness"], 0))
        self._update_card_mask()
        # PAS de reapplication de self.title_label ici (BUG corrige, voir la
        # remarque de l'utilisateur, "le titre dans l'entete ne fonctionne
        # pas dans les settings") : cette ligne existait AVANT le systeme de
        # surcharge par titre (header_font_color/family/bold/italic/taille,
        # voir refresh_header ci-dessous) et l'ecrasait INCONDITIONNELLEMENT
        # avec la couleur GENERIQUE role_color('colhead', ...) — refresh_
        # colors() est TOUJOURS appelee APRES refresh_header() (voir
        # PipelineBrowser._apply_settings/add_column/Column.__init__), donc
        # toute surcharge de "Couleur du titre" pour CETTE colonne (Colonnes
        # > Type/Projets/.../Logiciels/IN/OVER/OUT/Inspecteur) etait
        # silencieusement annulee des le refresh SUIVANT. refresh_header()
        # gere deja CE style correctement (voir sa remarque de tete, `s =
        # column_style_for(self.style_title)`), y compris le cas SANS
        # surcharge (repli sur la valeur GENERALE de "header_font_color",
        # deja identique par defaut a l'ancienne couleur fixe ici) : rien
        # d'autre a faire.

    def _suppress_left(self) -> bool:
        """Voir _column_suppress_left (module-level, factorisee pour etre
        partagee avec PreviewColumn)."""
        return _column_suppress_left(self, self.style_title)
    def refresh_header(self):
        """Reapplique hauteur/padding/police de l'entete (voir HEADER_HEIGHT/
        HEADER_PADDING, role 'colhead') — reglable en direct depuis
        Parametres > Entetes. HEADER_PADDING est la marge de header (voir
        __init__) : l'espace entre le fond colore (header_fill) et les
        bords de la colonne, pas la marge du texte a l'interieur du fond.

        Style EFFECTIF de CETTE colonne (voir app_style.column_style_for —
        general, ou surcharge Colonnes > Type pour "Type") plutot que les
        globals HEADER_HEIGHT/HEADER_PADDING partages a l'ancienne."""
        s = column_style_for(self.style_title)
        self.header.setVisible(bool(s.get("header_visible", True)))
        height = int(s.get("header_height", ui_state.HEADER_HEIGHT))
        padding = int(s.get("header_padding", ui_state.HEADER_PADDING))
        self.header.setFixedHeight(scaled(height))
        pad = scaled(padding, 0)   # 0 = valeur reglee valide (voir scaled)
        self.header.layout().setContentsMargins(pad, pad, pad, pad)
        # Police/gras/couleur/hauteur du titre (voir COLUMN_FRAME_KEYS/
        # app_style.column_style_for, Settings > General > Colonnes >
        # Entetes — OU sa surcharge Colonnes > Type/Projets/Sous-projets,
        # voir la remarque de l'utilisateur, "mets a jour egalement les
        # colonnes overidees ... avec tous les nouveaux parametres de
        # general") — "" (Systeme, aucune surcharge choisie) retombe
        # EXACTEMENT sur le role "colhead" d'origine (_resolve_font_family,
        # fallback_role) : comportement INCHANGE tant que l'utilisateur ne
        # personnalise pas.
        title_weight = 700 if s.get("header_font_bold", True) else 500
        title_size = int(s.get("header_font_size", 10))
        title_italic = bool(s.get("header_font_italic", False))
        title_smoothing = (
            s.get("header_font_antialias_override", "current")
            if s.get("header_font_antialias_override_enabled") else "current")
        title_family = _resolve_font_family(
            (s.get("header_font_family") or "").strip(), title_size, title_weight, fallback_role="colhead")
        self.title_label.setFont(font(
            title_size, title_weight, tracking=0.9, caps=True, family=title_family,
            smoothing=title_smoothing, italic=title_italic))
        self.title_label.setStyleSheet(
            f"color: {resolve_color_ref(s.get('header_font_color', '#9aa1a7'))}; background: transparent;")
        # Padding droit des icones (voir __init__, bouton punaise) :
        # marge droite DIRECTEMENT pilotee par ce reglage (PAS 10 + la
        # valeur — voir la remarque de l'utilisateur, "je veux que la
        # valeur 0 soit tres collee contre le bord de la colonne") —
        # seulement si une icone existe reellement sur cette colonne
        # (jamais "Type"/les colonnes Focus, voir __init__).
        if self._pin_btn is not None:
            self.header_fill.layout().setContentsMargins(
                10, 0, int(s.get("header_icon_right_padding", 0)), 0)
        # Espace avant le 1er item (voir __init__/self.header_gap_spacer,
        # Colonnes > Texte) : cle "item_*", donc seulement definie pour
        # "Type" (voir app_style.column_style_for) — 0 pour toute autre
        # colonne, comme avant ce reglage.
        self.header_gap_spacer.setFixedHeight(scaled(int(s.get("item_header_gap", 0) or 0), 0))
        # Bordure du CADRE : reserve, sur CHAQUE cote EFFECTIVEMENT peint
        # (voir column_frame_qss/_suppress_left — meme regle ICI pour le
        # cote gauche), la meme epaisseur que celle reellement dessinee la
        # — sinon le contenu (liste/entete, colle a self.card sans marge)
        # recouvrirait le filet, cote par cote — voir _TableFrame dans
        # settings_window.py, meme necessite/meme raison, deja documentee
        # la-bas. 1er essai : UNE seule marge, a droite (l'ancien filet
        # unique code en dur) — insuffisant des que les 4 cotes peuvent
        # etre actives independamment, voir la remarque de l'utilisateur,
        # "quand je met une valeur de padding, il n'y a pas de bordure sur
        # tous les cotes de la colonne" (le filet HAUT/GAUCHE/BAS restait
        # bien peint par la QSS, mais aussitot recouvert par l'entete/la
        # liste, qui n'en reservaient pas la place).
        border_thickness = max(0, int(s.get("column_border_thickness", 1)))
        enabled = s.get("column_border_enabled") or {}
        suppress_left = self._suppress_left()

        def reserve(side_enabled: bool) -> int:
            return border_thickness if side_enabled else 0

        self._column_layout.setContentsMargins(
            scaled(reserve(bool(enabled.get("left", True)) and not suppress_left), 0),
            scaled(reserve(bool(enabled.get("top", True))), 0),
            scaled(reserve(bool(enabled.get("right", True))), 0),
            scaled(reserve(bool(enabled.get("bottom", True))), 0),
        )
        # Padding de la colonne, PAR COTE (voir settings_window.
        # _ColumnPreview.setPadding/Colonnes > Colonnes > Padding) : fait
        # RETRECIR self.card (fond + bordure) de ce nombre de px sur chaque
        # cote choisi, PAS un simple retrait de son contenu — voir la
        # remarque de l'utilisateur, "je veux que le fond de la colonne se
        # replie". Cote GAUCHE mis a 0 si cette colonne est COLLEE a une
        # voisine (meme regle que _suppress_left pour la bordure) : sinon
        # l'ecart VISIBLE entre 2 colonnes collees cumulait le padding
        # DROIT de celle de gauche ET le padding GAUCHE de celle de
        # droite — le double de la valeur reglee — voir la remarque de
        # l'utilisateur, "la distance entre 2 colonnes doit etre la valeur
        # du padding et non celle du padding*2".
        col_pad = dict(column_padding_for(self.style_title))
        if self._suppress_left():
            col_pad["left"] = 0
        self._outer_layout.setContentsMargins(
            scaled(col_pad["left"], 0), scaled(col_pad["top"], 0),
            scaled(col_pad["right"], 0), scaled(col_pad["bottom"], 0),
        )
        self._update_card_mask()
    def _open_software_menu(self) -> None:
        """Bouton « + » de l'entete de LOGICIELS : un logiciel par ligne (liste des reglages,
        `software_choices`), ceux qui ont deja leur dossier ici grises ; le choix cree le dossier
        (« houdini »…) dans le dossier liste par la colonne et le selectionne."""
        existing = set()
        try:
            for entry in self.directory.iterdir():
                if entry.is_dir():
                    key = software_icon_key(entry.name)
                    if key is not None:
                        existing.add(key)
        except OSError:
            pass
        menu = Menu(self)
        menu.setFont(font(11, 400))
        for key, label, folder in software_choices():
            action = menu.addAction(QIcon(software_icon_pixmap(key, 16)), label)
            if key in existing:
                action.setEnabled(False)
                action.setText(f"{label}  (deja present)")
            action.setData(folder)
        if menu.isEmpty():
            menu.addAction("Aucun logiciel dans les reglages").setEnabled(False)
        button = self._software_btn
        chosen = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if chosen is not None and chosen.data():
            self._create_software_folder(chosen.data())
    def _create_software_folder(self, name: str) -> None:
        new_path = self.directory / name
        try:
            new_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Ajouter un logiciel", f"Impossible de creer le dossier :\n{exc}")
            return
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break
    def set_launcher(self, key: str | None, on_click=None) -> None:
        """Bouton a l'icone du logiciel `key` a cote de la punaise (colonnes ouvertes sous un dossier de
        logiciel du groupe LOGICIELS, voir PipelineBrowser._sync_software_buttons) : clic = `on_click()`,
        le logiciel s'ouvre dans le dossier de cette colonne. None = bouton retire."""
        if key is None:
            if self._launch_btn is not None:
                self._launch_btn.hide()
            self._launch_key = None
            return
        if self._launch_btn is None:
            btn = QPushButton()
            btn.setFlat(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setFixedSize(18, 18)
            btn.setIconSize(QSize(14, 14))
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; padding: 0; }"
                "QPushButton:hover { background: rgba(255,255,255,0.12); border-radius: 3px; }"
            )
            btn.clicked.connect(lambda: self._launch_click() if self._launch_click is not None else None)
            index = self._header_layout.indexOf(self._pin_btn) if self._pin_btn is not None else -1
            if index < 0:
                self._header_layout.addWidget(btn)
            else:
                self._header_layout.insertWidget(index, btn)
            self._launch_btn = btn
        self._launch_click = on_click
        if key != self._launch_key:
            self._launch_btn.setIcon(QIcon(software_icon_pixmap(key, 14)))
            self._launch_btn.setToolTip(f"Ouvrir {key.capitalize()} dans ce dossier ({self.directory.name})")
            self._launch_key = key
        self._launch_btn.show()
    def _refresh_pin_icon(self):
        """Applique l'icone punaise (01 par defaut, 02 si active, voir
        _toggle_pin/_pin_icon_pixmap) — no-op sur "Type" (pas de bouton,
        voir __init__)."""
        if self._pin_btn is not None:
            self._pin_btn.setIcon(QIcon(_pin_icon_pixmap(self._pin_active, 14)))
    def reload_pin_state(self, data=None):
        """Preset change : les valeurs de punaise sont celles du NOUVEAU preset (demande de l'utilisateur,
        voir browser_core.PIN_LAYOUT_KEYS) — relues et appliquees sur place (memes regles que __init__)."""
        data = load_layout_settings(self.directory) if data is None else data
        self._pin_active = bool(data.get("pinned", False))
        self._pin_column_width = data.get("pinned_column_width") if self._pin_active else None
        self._pin_row_height = data.get("pinned_row_height") if self._pin_active else None
        raw_height = data.get("row_height") if self._pin_active else None
        self._folder_row_height = int(raw_height) if isinstance(raw_height, (int, float)) else None
        self._show_icon_override = self._show_preview_override = None
        self._icon_size_override = self._icon_padding_left_override = self._text_padding_left_override = None
        if self._pin_active or self.style_title == "Type":
            if isinstance(data.get("show_icon"), bool):
                self._show_icon_override = data["show_icon"]
            if isinstance(data.get("show_preview"), bool):
                self._show_preview_override = data["show_preview"]
            for key, attr in (("icon_size", "_icon_size_override"),
                              ("icon_padding_left", "_icon_padding_left_override"),
                              ("text_padding_left", "_text_padding_left_override")):
                if isinstance(data.get(key), (int, float)):
                    setattr(self, attr, int(data[key]))
        self._refresh_pin_icon()
        self.setFixedWidth(0 if self.collapsed else self._pin_column_width or self._user_width or col_width(self.style_title))
        self.list.doItemsLayout()
        self.list.viewport().update()
    def _toggle_pin(self):
        """Punaise d'en-tete — voir __init__/effective_row_height, la
        remarque de l'utilisateur, "punaise_02.png lorsque l'on clique
        dessus, les valeurs de dimensions de colonnes et de lignes sont
        alors overridees par les valeurs du json se trouvant a la base du
        repertoire en cours ... lorsque l'on rappuie sur cette icone,
        l'icone redevient punaise_01.png et prend en compte les valeurs
        par defaut des settings". Desactiver NE SUPPRIME PAS les valeurs
        enregistrees (juste `pinned: False`) : rappuyer plus tard restaure
        exactement la largeur/hauteur figees precedemment, sans avoir a
        redimensionner de nouveau a la main."""
        if self._pin_active:
            self._pin_active = False
            self._pin_column_width = None
            self._pin_row_height = None
            _update_layout_setting(self.directory, "pinned", False)
        else:
            self._pin_active = True
            self._pin_column_width = self.width()
            self._pin_row_height = self.effective_row_height()
            data = load_layout_settings(self.directory)
            data["pinned"] = True
            data["pinned_column_width"] = self._pin_column_width
            data["pinned_row_height"] = self._pin_row_height
            save_layout_settings(self.directory, data)
        self._refresh_pin_icon()
        self.setFixedWidth(self._pin_column_width or self._user_width or col_width(self.style_title))
        self.list.doItemsLayout()
        if self._on_resize is not None:
            # Colonne du groupe : les voisines suivent la largeur (commune).
            self._on_resize(self.width())
    def _update_card_mask(self):
        """Decoupe VRAIMENT self.card (fond + TOUS ses enfants — entete ET
        liste) a la silhouette EXACTE de son rayon d'angle — voir la
        remarque de l'utilisateur, capture a l'appui, "le fond et l'entete
        passent toujours devant la bordure de la colonne" : reserver une
        marge DROITE (voir refresh_header) ne protege que les segments
        DROITS des bords, jamais la zone COURBE d'un coin — l'entete
        (coins hauts) ET la liste (coins bas, ses propres lignes restant
        toujours des rectangles PLEINS, sans rayon) y debordaient donc
        encore des que column_border_radius > 0. Qt ne clippe jamais
        automatiquement des enfants au rayon QSS de leur parent — voir
        _TableFrame dans settings_window.py, qui avait DEJA essaye puis
        ABANDONNE un masque pour cette meme raison : un decoupage BINAIRE,
        non anti-aliase, degrade le rendu du coin arrondi lui-meme. Ce
        compromis reste neanmoins prefere ICI (une seule silhouette
        exterieure, generalement grande, contre de nombreux petits coins de
        ligne pour _TableFrame) plutot que de laisser la bordure invisible
        — voir la meme remarque de l'utilisateur, qui persiste malgre 2
        correctifs precedents (reserve de marge, "0px solid transparent")
        insuffisants a eux seuls."""
        # self.card._radius (deja SCALE, voir refresh_colors) — PAS
        # recalcule independamment ici : garantit le MEME rayon que celui
        # reellement peint (voir _ColumnCard.paintEvent/la docstring de
        # cette classe), plutot que 2 sources qui pourraient diverger.
        # activate() FORCE la resolution immediate du layout (largeur/
        # hauteur de self.card) : setContentsMargins()/setFixedWidth()
        # n'appliquent la nouvelle geometrie qu'au PROCHAIN cycle de
        # peinture (activation PARESSEUSE de Qt) — sans ce forçage,
        # self.card.rect() ci-dessous pouvait encore renvoyer l'ANCIENNE
        # taille au moment ou le masque est calcule, produisant un masque
        # decale/trop grand par rapport a ce qui est reellement peint —
        # voir la remarque de l'utilisateur, capture a l'appui, "les
        # arrondis ne sont pas du tout recouvert par la bordure".
        self._outer_layout.activate()
        radius = _radius_dict(self.card._radius)
        self._card_effect.setRadius(radius)
        # Desactive CE decoupage-ci des qu'une bordure existe (thickness>0) :
        # dans ce cas, _ColumnCard.paintEvent peint DEJA fond+bordure
        # exactement dans le silhouette voulu (voir _paint_bordered_rect,
        # qui a son PROPRE antialiasing sur le trait), et self._content est
        # DEJA reduit plus etroit par _content_effect ci-dessous (donc
        # jamais debordant) — ce masque-ci n'a plus RIEN a proteger, il ne
        # fait plus que reappliquer une 2e passe d'antialiasing PAR-DESSUS
        # celle, deja correcte, du trait — exactement au MEME rayon, donc
        # sur les MEMES pixels de transition : les 2 alphas partiels se
        # MULTIPLIENT plutot que de s'additionner, ce qui faisait carrement
        # disparaitre la bordure dans la courbe — voir la remarque de
        # l'utilisateur, capture a l'appui, "la bordure disparait
        # completement dans l'arrondi de l'angle". Reste ACTIF quand il n'y
        # a PAS de bordure (thickness<=0) : LA, _content_effect est lui-meme
        # desactive (voir plus bas) et ce masque-ci redevient le SEUL a
        # empecher l'entete/la liste (coins carres) de deborder du fond
        # arrondi.
        self._card_effect.setEnabled(self.card._thickness <= 0)
        # self._content (entete+liste) : decoupe a un rayon RETRECI de
        # l'epaisseur de bordure REELLEMENT peinte (self.card._thickness,
        # deja scaled — voir refresh_colors) — MEME formule que le clip du
        # FOND dans _paint_bordered_rect (_radius_shrink(radius, thickness))
        # — pour rester en retrait de l'anneau de la bordure jusque dans
        # les coins, pas seulement le long des segments droits (voir
        # reserve()/la docstring de self._content ci-dessus)."""
        # +1px de MARGE SUPPLEMENTAIRE (au-dela du strict inner_radius
        # geometrique) : self._content (coins CARRES, jamais son propre
        # rayon — voir column_header_qss, "le rognage visuel est deja
        # garanti par ce decoupage") est un ENFANT peint PAR-DESSUS
        # self.card (Z-order Qt normal) — a epaisseur de bordure FAIBLE
        # (1px), le bord antialiase de CE decoupage (inner_radius) et celui,
        # deja antialiase, du trait de bordure (juste 1px plus loin, a
        # `radius`) tombent quasiment sur LES MEMES pixels : le contenu,
        # AU-DESSUS, y "mangeait" alors la bordure au lieu de s'arreter
        # juste avant elle — voir la remarque de l'utilisateur, capture a
        # l'appui, "la bordure disparait completement dans l'arrondi de
        # l'angle". Cette marge laisse un peu d'air entre les 2 contours
        # pour que la bordure garde une zone a elle, sans concurrence.
        inner_radius = _radius_shrink(radius, self.card._thickness + 1)
        self._content_effect.setRadius(_radius_dict(inner_radius))
        # Desactive ce 2e decoupage des qu'il n'a plus rien a proteger
        # (aucune bordure reellement peinte, thickness<=0) : inner_radius
        # egale alors radius au chiffre pres, donc self._content (deja a
        # l'interieur du silhouette de self.card, qui l'enveloppe ET tous
        # ses enfants dans SA PROPRE passe d'antialiasing via _card_effect)
        # n'a plus besoin d'etre roule une 2e fois — un 2e QGraphicsEffect,
        # rasterise dans SA PROPRE pixmap hors-ecran independante, ne
        # retombe JAMAIS EXACTEMENT sur les memes pixels que le 1er (chaque
        # passe d'antialiasing calcule sa propre couverture sous-pixel) :
        # 2 arrondis quasi identiques mais jamais superposables au pixel
        # pres laissaient un lisere visible a chaque coin — voir la
        # remarque de l'utilisateur, "je veux que le lissage de l'arrondi
        # soit parfait ce qui est loin d'etre le cas". Toujours REACTIVE
        # des qu'une bordure existe a nouveau (thickness>0) : LA, le rayon
        # interieur retrecit vraiment et reste indispensable (voir la
        # docstring de self._content plus haut, "l'entete/la liste
        # recouvrait le trace courbe de la bordure a chaque coin").
        self._content_effect.setEnabled(self.card._thickness > 0)
    def current_path(self) -> Path | None:
        item = self.list.currentItem()
        return Path(item.data(ROLE_PATH)) if item else None
    def reselect_current(self):
        """Rejoue la selection de la ligne courante (voir FileListWidget.
        mouseReleaseEvent) : ferme les colonnes a droite et reaffiche son contenu."""
        item = self.list.currentItem()
        if item is not None:
            self.selected.emit(self, Path(item.data(ROLE_PATH)))
    def _on_current_changed(self, item, _previous):
        self.selected.emit(self, Path(item.data(ROLE_PATH)) if item else None)
    def _on_double_clicked(self, item):
        path = Path(item.data(ROLE_PATH))
        # S'ouvrent dans la visionneuse de l'appli, pas dans le logiciel par defaut de Windows (le menu
        # « Ouvrir » le garde) : les images, les planches PureRef, et tout fichier qui a un apercu.
        if not item.data(ROLE_ISDIR) and opens_in_viewer(path):
            self.view_requested.emit(path)
            return
        if item.data(ROLE_ISDIR):
            # Un dossier s'ouvre dans la visionneuse (demande de l'utilisateur) ; sans photo a montrer,
            # PipelineBrowser le laisse a l'explorateur comme avant.
            self.folder_view_requested.emit(path)
            return
        self.activated.emit(path)
    def preview_source(self, path: Path):
        """(pixmap, QRect GLOBAL) de l'apercu tel que la ligne de `path` l'affiche (dernier dessin ;
        image entiere ajustee dans sa case), ou None : depart du vol vers la visionneuse."""
        found = (getattr(self, "_preview_slots", None) or {}).get(str(path))
        if found is None:
            return None
        slot, pixmap = found
        if pixmap is None or pixmap.isNull() or not self.list.viewport().rect().intersects(slot):
            return None
        dpr = pixmap.devicePixelRatio() or 1.0
        size = QSize(round(pixmap.width() / dpr), round(pixmap.height() / dpr))
        size.scale(slot.size(), Qt.KeepAspectRatio)
        rect = QRect(0, 0, size.width(), size.height())
        rect.moveCenter(slot.center())
        return pixmap, QRect(self.list.viewport().mapToGlobal(rect.topLeft()), rect.size())

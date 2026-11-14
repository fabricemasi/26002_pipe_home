"""Éditeur PDF plein cadre (Qt) : recouvre la zone des colonnes (comme fm_font) ou le Board (module « PDF » de la
barre des modules). Barre du haut (fichier, édition, vue, recherche, outils), barre de l'outil choisi
(Conception, Commentaires, Pages, Protéger), panneaux à gauche (pages, signets, champs, commentaires, infos),
propriétés à droite (conception), bandeau d'information (XFA, contenu actif, actions bloquées), barre d'état.

Le module n'importe RIEN de la fenêtre principale : elle pose `HOOKS`."""
from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QScrollArea, QSplitter, QStackedWidget, QVBoxLayout, QWidget

from . import native, ui_kit
from .designer import DesignController
from .panels import InfoPanel, ListPanel, OutlinePanel, ThumbsPanel
from .session import PdfSession
from .settings_defaults import PDF_DEFAULTS
from .view import MODE_LABELS, PdfView
from .worker import PRIO_BACKGROUND, PRIO_SAVE

HOOKS: dict = {
    "settings": lambda: {},                 # réglages appliqués (dict complet de l'appli)
    "status": lambda text: None,            # barre d'état de la fenêtre
    "open_settings": None,                  # fenêtre « Réglages : PDF »
    "navbar_frame": False,                  # vrai : enregistrer / annuler / rétablir / fermer sont dans le cadre « PDF »
    "fullscreen": None,                     # f(bool) : plein écran de la fenêtre
}
FILE_FILTER = "Documents PDF (*.pdf);;Tous les fichiers (*)"
TOOLS = (("fill", "Remplir", "Lire, sélectionner du texte et remplir les formulaires (champs accessibles au clavier)"),
         ("hand", "Main", "Déplacer la page (Espace ou bouton du milieu : main temporaire)"),
         ("content", "Contenu", "Modifier le contenu : textes, images, formes de la page (objets réels)"),
         ("design", "Conception", "Concevoir un formulaire : placer et configurer des champs AcroForm"),
         ("comment", "Commentaires", "Surligner, annoter, dessiner, tamponner"),
         ("pages", "Pages", "Organiser les pages : insérer, supprimer, pivoter, extraire, fusionner…"),
         ("protect", "Protéger", "Caviarder, chiffrer, retirer les métadonnées, signer"))
FIELD_KINDS = (("text", "Texte"), ("multiline", "Multiligne"), ("number", "Nombre"), ("date", "Date"),
               ("checkbox", "Case"), ("radio", "Radio"), ("combo", "Liste déroulante"), ("list", "Liste"),
               ("button", "Bouton"), ("signature", "Signature"))


def _settings() -> dict:
    s = dict(PDF_DEFAULTS)
    try:
        s.update({k: v for k, v in (HOOKS["settings"]() or {}).items() if k.startswith("pdf_") or k == "colors"})
    except Exception:                                      # noqa: BLE001 - réglages illisibles : défauts
        pass
    return s


class PdfPane(QWidget):
    closeRequested = Signal()
    stateChanged = Signal()                  # modifié / annuler / rétablir (cadre « PDF » de la barre)
    documentChanged = Signal(str)            # chemin du document ouvert

    def __init__(self, parent=None, settings: dict | None = None):
        super().__init__(parent)
        from fm_theme.tokens import M
        self.settings = settings or _settings()
        self._seed_look()
        self.setObjectName("PdfPane")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#PdfPane {{ background: {M.get('panel_bg', '#16181a')}; }}")
        self.session = PdfSession(self)
        self.session.options["javascript"] = bool(self.settings.get("pdf_javascript", True))
        self.session.ask_handler = self._script_question
        self.view = PdfView(self.session, self.settings, self)
        self.designer = DesignController(self)
        self.annot = None                    # outil Commentaires (annot_tools.py), créé au premier usage
        self.content = None                  # outil Contenu (edit_tools.py), créé au premier usage
        self.mode = "fill"
        self._search = {"query": "", "pages": {}, "order": [], "pos": -1, "running": None}
        self._recovery = QTimer(self)
        self._recovery.timeout.connect(self.session.write_recovery)
        self._build()
        self._connect()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)

    def _seed_look(self) -> None:
        try:
            import settings_window_v2 as v2
            from settings_store import load_settings
            v2.seed_window_look(load_settings())
        except Exception:                                  # noqa: BLE001 - seul : défauts des briques
            pass

    # -- construction --

    def _build(self) -> None:
        B = ui_kit.button
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(8, 4, 8, 2)
        top.setSpacing(2)
        self.title = ui_kit.label("", "value")
        top.addWidget(self.title, 1)
        self.b_open = B("Ouvrir…", "Ouvrir un PDF (Ctrl+O)", self.open_dialog)
        self.b_new = B("Nouveau", "Document vierge (A4) pour concevoir un formulaire", self.new_document)
        self.b_save = B("Enregistrer", "Enregistrer (Ctrl+S)", self.save)
        self.b_save_as = B("Enregistrer sous…", "Enregistrer une copie ailleurs (Ctrl+Maj+S)", self.save_as_dialog)
        self.b_print = B("Imprimer…", "Imprimer (Ctrl+P)", self.print_dialog)
        self.b_export = B("Exporter…", "Exporter : images, texte, PDF optimisé, pages, PDF aplati", self.export_menu)
        self.b_undo = B("Annuler", "Annuler (Ctrl+Z)", self.undo)
        self.b_redo = B("Rétablir", "Rétablir (Ctrl+Y)", self.redo)
        for b in (self.b_open, self.b_new, self.b_save, self.b_save_as, self.b_print, self.b_export):
            top.addWidget(b)
        top.addSpacing(8)
        top.addWidget(self.b_undo)
        top.addWidget(self.b_redo)
        top.addSpacing(8)
        self.b_zoom_out = B("−", "Zoom arrière (Ctrl + −)", lambda: self.view.zoom_by(0.8))
        self.zoom_field = ui_kit.text_field("100 %", 64)
        self.zoom_field.setToolTip("Zoom (saisir un pourcentage)")
        self.zoom_field.editingFinished.connect(self._zoom_typed)
        self.b_zoom_in = B("+", "Zoom avant (Ctrl + +)", lambda: self.view.zoom_by(1.25))
        self.b_fit_w = B("Largeur", "Ajuster à la largeur", self.view.fit_width)
        self.b_fit_p = B("Page", "Ajuster à la page (Ctrl+0)", self.view.fit_page)
        self.b_actual = B("100 %", "Taille réelle", self.view.actual_size)
        self.b_mode = B(MODE_LABELS[self.view.mode], "Mode d'affichage", self.mode_menu)
        self.b_rotate = B("↻", "Faire pivoter la vue (Ctrl+Maj++)", lambda: self.view.rotate_view(1))
        self.b_read = B("Lecture", "Mode lecture : panneaux masqués (F11 : plein écran)", self.toggle_reading,
                        checkable=True)
        for b in (self.b_zoom_out, self.zoom_field, self.b_zoom_in, self.b_fit_w, self.b_fit_p, self.b_actual,
                  self.b_mode, self.b_rotate, self.b_read):
            top.addWidget(b)
        top.addSpacing(8)
        self.page_field = ui_kit.text_field("", 46)
        self.page_field.setToolTip("Aller à la page (numéro ou étiquette)")
        self.page_field.editingFinished.connect(self._page_typed)
        self.page_total = ui_kit.label("/ 0", "value_muted")
        top.addWidget(self.page_field)
        top.addWidget(self.page_total)
        top.addSpacing(8)
        self.search_field = ui_kit.text_field("", 170, "Rechercher (Ctrl+F)")
        self.search_field.returnPressed.connect(lambda: self.search_next(1))
        self.b_prev = B("◀", "Résultat précédent (Maj+F3)", lambda: self.search_next(-1))
        self.b_next = B("▶", "Résultat suivant (F3)", lambda: self.search_next(1))
        self.b_case = B("Aa", "Respecter la casse", self._search_options_changed, checkable=True)
        self.b_word = B("Mot", "Mot entier", self._search_options_changed, checkable=True)
        self.b_accent = B("é=e", "Ignorer les accents", self._search_options_changed, checkable=True)
        self.search_count = ui_kit.label("", "value_muted")
        for b in (self.search_field, self.b_prev, self.b_next, self.b_case, self.b_word, self.b_accent,
                  self.search_count):
            top.addWidget(b)
        top.addSpacing(8)
        self.b_settings = None
        if HOOKS.get("open_settings"):
            self.b_settings = B("Réglages", "Réglages du module PDF", lambda: HOOKS["open_settings"]())
            top.addWidget(self.b_settings)
        self.b_close = B("Fermer", "Fermer l'éditeur PDF", self.request_close)
        top.addWidget(self.b_close)
        if HOOKS.get("navbar_frame"):                     # déjà dans le cadre « PDF » de la barre
            for b in (self.b_save, self.b_undo, self.b_redo, self.b_settings, self.b_close):
                if b is not None:
                    b.hide()
        root.addLayout(top)

        tools = QHBoxLayout()
        tools.setContentsMargins(8, 0, 8, 2)
        tools.setSpacing(2)
        self.tool_buttons = {}
        for key, text, tip in TOOLS:
            b = B(text, tip, lambda k=key: self.set_mode(k), checkable=True)
            self.tool_buttons[key] = b
            tools.addWidget(b)
        tools.addSpacing(12)
        self.context_bar = QStackedWidget()
        self.context_bar.setFixedHeight(28)
        self.context_pages = {}
        for key, builder in (("fill", self._bar_fill), ("hand", self._bar_fill), ("content", self._bar_content),
                             ("design", self._bar_design),
                             ("comment", self._bar_comment), ("pages", self._bar_pages),
                             ("protect", self._bar_protect)):
            w = builder()
            self.context_pages[key] = w
            self.context_bar.addWidget(w)
        tools.addWidget(self.context_bar, 1)
        root.addLayout(tools)

        self.banner = QWidget()
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(10, 3, 10, 3)
        self.banner_text = ui_kit.label("", "value")
        self.banner_text.setWordWrap(True)
        bl.addWidget(self.banner_text, 1)
        self.banner_action = B("", "", None)
        self.banner_action.hide()
        bl.addWidget(self.banner_action)
        self.banner_close = B("×", "Masquer", lambda: self.banner.hide())
        bl.addWidget(self.banner_close)
        self.banner.setStyleSheet("background: rgba(255, 196, 0, 40);")
        self.banner.hide()
        root.addWidget(self.banner)

        self.split = QSplitter(Qt.Horizontal, self)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(4, 2, 0, 2)
        tabs = QHBoxLayout()
        tabs.setSpacing(1)
        self.left_tabs = {}
        self.left_stack = QStackedWidget()
        self.thumbs = ThumbsPanel(self.session)
        self.outline = OutlinePanel()
        self.fields_panel = ListPanel("Aucun champ AcroForm (formulaire XFA : champs gérés par le formulaire).")
        self.comments_panel = ListPanel("Aucun commentaire.")
        self.info_panel = InfoPanel()
        for name, widget in (("Pages", self.thumbs), ("Signets", self.outline), ("Champs", self.fields_panel),
                             ("Commentaires", self.comments_panel), ("Infos", self.info_panel)):
            b = B(name, "Panneau « %s »" % name, lambda n=name: self.show_left(n), checkable=True)
            tabs.addWidget(b)
            self.left_tabs[name] = (b, widget)
            if name == "Infos":
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QScrollArea.NoFrame)
                scroll.setWidget(widget)
                widget = scroll
            self.left_stack.addWidget(widget)
        tabs.addStretch(1)
        ll.addLayout(tabs)
        ll.addWidget(self.left_stack, 1)
        self.left = left
        self.split.addWidget(left)
        self.split.addWidget(self.view)
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QScrollArea.NoFrame)
        right.setWidget(self.designer.panel)
        self.right = right
        self.split.addWidget(right)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([210, 900, 320])
        right.hide()
        root.addWidget(self.split, 1)
        self.status_label = ui_kit.label("", "value_muted")
        self.status_label.setContentsMargins(10, 2, 10, 4)
        root.addWidget(self.status_label)
        self.show_left(self.settings.get("pdf_left_panel", "Pages"))
        if not self.settings.get("pdf_show_thumbnails", True):
            self.left.hide()
        self._sync_tools()
        for keys, slot in (("Ctrl+O", self.open_dialog), ("Ctrl+S", self.save), ("Ctrl+Shift+S", self.save_as_dialog),
                           ("Ctrl+P", self.print_dialog), ("Ctrl+F", self._focus_search),
                           ("F3", lambda: self.search_next(1)), ("Shift+F3", lambda: self.search_next(-1)),
                           ("F11", self.toggle_fullscreen), ("Ctrl+Shift+=", lambda: self.view.rotate_view(1)),
                           ("Ctrl+Shift+-", lambda: self.view.rotate_view(-1)), ("Ctrl+L", self.toggle_reading)):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    def _row(self, buttons) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        for b in buttons:
            lay.addWidget(b) if b is not None else lay.addSpacing(10)
        lay.addStretch(1)
        return w

    def _bar_fill(self) -> QWidget:
        B = ui_kit.button
        self.b_highlight = B("Surbrillance des champs", "Fond coloré des champs interactifs",
                             self._toggle_highlight, checkable=True)
        self.b_highlight.setChecked(bool(self.settings.get("pdf_forms_highlight", True)))
        self.b_required = B("Champs obligatoires vides…", "Lister les champs obligatoires non remplis",
                            self.check_required)
        self.b_select_all = B("Tout sélectionner", "Sélectionner le texte de la page", self.view.select_all_text)
        self.b_copy = B("Copier", "Copier le texte sélectionné (Ctrl+C)", self.view.copy_selection)
        self.b_ocr = B("OCR…", "Reconnaissance de texte des pages numérisées", self.ocr_dialog)
        return self._row([self.b_highlight, self.b_required, None, self.b_select_all, self.b_copy, None, self.b_ocr])

    def _bar_content(self) -> QWidget:
        B = ui_kit.button
        c = lambda: self._ensure_content()
        return self._row([B("Texte", "Ajouter du texte (tracer sa zone)", lambda: c().set_add("text")),
                          B("Image…", "Ajouter une image", lambda: c().set_add("image")),
                          B("Rectangle", "Ajouter un rectangle", lambda: c().set_add("rect")),
                          B("Ellipse", "Ajouter une ellipse", lambda: c().set_add("ellipse")),
                          B("Ligne", "Ajouter une ligne", lambda: c().set_add("line")),
                          None, B("Modifier le texte…", "Texte de l'objet choisi (ou double-clic)",
                                  lambda: c().edit_text() if c().overlay.selected else None),
                          B("Taille…", "Taille du texte choisi", lambda: c().font_size()),
                          B("Couleur…", "Couleur de remplissage / du texte", lambda: c().color("fill")),
                          B("Contour…", "Couleur du contour", lambda: c().color("stroke")),
                          B("Premier plan", "Au-dessus des autres objets", lambda: c().restack("front")),
                          B("Arrière-plan", "Sous les autres objets", lambda: c().restack("back")),
                          B("Supprimer", "Supprimer l'objet choisi (Suppr)",
                            lambda: c().delete() if c().overlay.selected else None)])

    def _ensure_content(self):
        if self.content is None:
            from .edit_tools import ContentController
            self.content = ContentController(self)
        return self.content

    def _bar_design(self) -> QWidget:
        B = ui_kit.button
        self.kind_buttons = {}
        row = []
        for kind, text in FIELD_KINDS:
            b = B(text, "Placer un champ « %s » (glisser un rectangle ; Maj : garder l'outil)" % text,
                  lambda k=kind: self.designer.set_place_kind(None if self.designer.overlay.place_kind == k else k),
                  checkable=True)
            self.kind_buttons[kind] = b
            if kind == "text":
                from fm_theme import icon_library
                b.setIcon(icon_library.icone_cadree("modules/pdf/champ_formulaire_03", 16, self.devicePixelRatioF(),
                                                    style=icon_library.MONOCHROME,
                                                    teinte=b.palette().buttonText().color()))
                b.setMinimumWidth(b.sizeHint().width())
            row.append(b)
        row.append(None)
        self.b_tab_order = B("Ordre de tabulation", "Cliquez les champs dans l'ordre de tabulation voulu",
                             lambda: self.designer.set_tab_mode(not self.designer.overlay.tab_mode), checkable=True)
        row.append(self.b_tab_order)
        row.append(B("Tester", "Passer en Remplissage pour tester le formulaire", lambda: self.set_mode("fill")))
        return self._row(row)

    def _bar_comment(self) -> QWidget:
        B = ui_kit.button
        from .annots import KINDS
        self.annot_buttons = {}
        row = []
        for kind in ("highlight", "underline", "strikeout", "note", "freetext", "ink", "line", "arrow", "rect",
                     "circle", "stamp", "check", "cross"):
            b = B(KINDS[kind], "Outil « %s »" % KINDS[kind], lambda k=kind: self._annot_tool(k), checkable=True)
            self.annot_buttons[kind] = b
            row.append(b)
        row.append(None)
        row.append(B("Couleur…", "Couleur des nouveaux commentaires", self._annot_color_menu))
        return self._row(row)

    def _bar_pages(self) -> QWidget:
        B = ui_kit.button
        from . import page_actions as pa
        return self._row([B("Insérer une page vierge", "Après la page choisie", lambda: pa.insert_blank(self)),
                          B("Insérer un PDF…", "Pages d'un autre document après la page choisie",
                            lambda: pa.insert_file(self)),
                          B("Dupliquer", "Dupliquer les pages choisies", lambda: pa.duplicate(self)),
                          B("Supprimer", "Supprimer les pages choisies", lambda: pa.delete(self)),
                          B("↺", "Pivoter à gauche", lambda: pa.rotate(self, -1)),
                          B("↻", "Pivoter à droite", lambda: pa.rotate(self, 1)),
                          None, B("Extraire…", "Enregistrer les pages choisies dans un nouveau PDF",
                                  lambda: pa.extract(self)),
                          B("Diviser…", "Découper le document", lambda: pa.split(self)),
                          B("Fusionner…", "Ajouter d'autres PDF à la fin", lambda: pa.merge(self)),
                          None, B("Recadrer…", "Recadrer les pages choisies", lambda: pa.crop(self)),
                          B("Numéros…", "Numéroter les pages", lambda: pa.numbers(self)),
                          B("En-tête / pied…", "Ajouter un en-tête et un pied de page", lambda: pa.header_footer(self)),
                          B("Filigrane…", "Ajouter un filigrane", lambda: pa.watermark(self))])

    def _bar_protect(self) -> QWidget:
        B = ui_kit.button
        from . import protect_actions as sa
        return self._row([B("Caviarder une zone", "Tracer les zones à SUPPRIMER définitivement",
                            lambda: sa.redact_tool(self), checkable=True),
                          B("Caviarder la recherche", "Caviarder toutes les occurrences recherchées",
                            lambda: sa.redact_search(self)),
                          B("Appliquer le caviardage", "Supprimer réellement le contenu sous les zones",
                            lambda: sa.apply_redactions(self)),
                          None, B("Chiffrer…", "Mot de passe et permissions à l'enregistrement",
                                  lambda: sa.encrypt(self)),
                          B("Retirer le chiffrement", "Enregistrer sans mot de passe", lambda: sa.decrypt(self)),
                          B("Retirer les métadonnées", "Effacer auteur, logiciel, dates, XMP",
                            lambda: sa.strip_metadata(self)),
                          None, B("Signature visuelle…", "Image ou texte de signature (NON cryptographique)",
                                  lambda: sa.visual_signature(self)),
                          B("Signer numériquement…", "Signature cryptographique (certificat PKCS#12)",
                            lambda: sa.digital_signature(self)),
                          B("Vérifier les signatures", "Validité cryptographique et modifications après signature",
                            lambda: sa.verify_signatures(self))])

    def _connect(self) -> None:
        s = self.session
        s.opened.connect(self._on_opened)
        s.reloaded.connect(self._on_reloaded)
        s.failed.connect(self._on_failed)
        s.stateChanged.connect(self._on_state)
        s.saved.connect(lambda text: self.status(text))
        s.saveFailed.connect(self._on_save_failed)
        s.conflict.connect(self._on_conflict)
        s.blocked.connect(self._on_blocked)
        s.message.connect(self.status)
        v = self.view
        v.pageChanged.connect(self._on_page)
        v.zoomChanged.connect(lambda z: self.zoom_field.setText("%d %%" % round(z * 100)))
        v.linkRequested.connect(self._open_link)
        v.contextMenuAt.connect(self._view_menu)
        self.thumbs.pageActivated.connect(lambda i: v.go_to_page(i))
        self.thumbs.movePages.connect(lambda pages, to: __import__("fm_pdf.page_actions", fromlist=["x"]).move(
            self, pages, to))
        self.thumbs.contextRequested.connect(self._thumbs_menu)
        self.outline.pageActivated.connect(lambda i: v.go_to_page(i))
        self.fields_panel.activated.connect(self._go_to_field)
        self.comments_panel.activated.connect(self._go_to_comment)
        self.comments_panel.contextRequested.connect(self._comment_menu)

    # -- document --

    def open_path(self, path, password: str | None = None) -> bool:
        path = pathlib.Path(path)
        if not path.is_file():
            self.status("Fichier introuvable : %s" % path)
            return False
        from . import fileio
        recovery = fileio.pending_recovery(path)
        if recovery is not None and ui_kit.confirm(
                self, "Récupération", "Une copie de secours plus récente que « %s » existe (incident pendant une "
                "modification). L'ouvrir ? (l'original n'est pas touché tant que vous n'enregistrez pas)" % path.name,
                "Ouvrir la copie"):
            data = fileio.read_file(recovery)
            self.session.open_bytes(data, path, password)
        else:
            self.session.open_path(path, password)
        self.title.setText(path.name + " — ouverture…")
        self.status("Ouverture de %s…" % path)
        return True

    def open_bytes(self, data: bytes, path=None) -> None:
        self.session.open_bytes(data, path)

    def new_document(self) -> None:
        if not self.confirm_leave():
            return
        from . import acroform
        self.session.path = None
        self.session.open_bytes(acroform.new_blank_document(), None)
        self.set_mode("design")

    def open_dialog(self) -> None:
        if not self.confirm_leave():
            return
        start = str(self.session.path.parent) if self.session.path else ""
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un PDF", start, FILE_FILTER)
        if path:
            self.open_path(path)

    def _on_opened(self, info: dict) -> None:
        name = self.session.path.name if self.session.path else "Sans titre"
        self.title.setText(name)
        self.page_total.setText("/ %d" % info.get("page_count", 0))
        self.view.fit = self.settings.get("pdf_default_fit") or None
        if not self.view.fit:
            self.view.set_zoom(float(self.settings.get("pdf_default_zoom", 100)) / 100.0)
        self._populate(info)
        self._show_document_banner(info)
        self.status("%s : %d page(s), ouvert en %.0f ms%s" % (
            name, info.get("page_count", 0), info.get("open_ms", 0),
            (" (XFA : %.0f ms)" % info.get("xfa_ms", 0)) if info.get("xfa_loaded") else ""))
        self._apply_highlight()
        delay = int(self.settings.get("pdf_autosave_recovery_s", 60))
        if delay > 0:
            self._recovery.start(delay * 1000)
        self.documentChanged.emit(str(self.session.path or ""))
        self._sync_tools()

    def _on_reloaded(self, info: dict) -> None:
        self.page_total.setText("/ %d" % info.get("page_count", 0))
        self._populate(info)

    def _populate(self, info: dict) -> None:
        self.thumbs.set_document(info)
        self.info_panel.set_info(info, native.info())
        fields = info.get("fields", [])
        self.fields_panel.set_items([("%s%s — %s (p. %d)%s" % ("* " if f["flags"] & 2 else "", f["name"],
                                                               f["type_name"], f["page"] + 1,
                                                               (" = " + f["value"]) if f["value"] else ""),
                                      f.get("tooltip", ""), f) for f in fields])
        self.session.run(lambda doc: doc.outline(), PRIO_BACKGROUND,
                         lambda tree, err: self.outline.set_outline(tree if err is None else []))
        self.refresh_comments()

    def refresh_comments(self) -> None:
        from . import annots

        def job(doc):
            if doc.is_xfa:
                return []
            return annots.list_all(doc.data)

        def done(items, error):
            if error is not None:
                items = []
            self.comments_panel.set_items([("p. %d — %s%s%s" % (a["page"] + 1, a["label"],
                                                              (" — " + a["author"]) if a["author"] else "",
                                                              (" : " + a["contents"][:60]) if a["contents"] else ""),
                                            a["contents"], a) for a in items])
        self.session.run(job, PRIO_BACKGROUND, done)

    def _on_failed(self, message: str, needs_password: bool) -> None:
        if needs_password and self.session.path is not None:
            pw = ui_kit.ask_text(self, "Document protégé", "« %s » demande un mot de passe." %
                                 self.session.path.name, password=True, action="Ouvrir")
            if pw:
                self.session.open_path(self.session.path, pw)
                return
        self.title.setText("Ouverture impossible")
        self.status("Ouverture impossible : %s" % message)
        self._banner("Ce fichier n'a pas pu être ouvert : %s" % message)

    def _show_document_banner(self, info: dict) -> None:
        notes = []
        if info.get("is_xfa"):
            if info.get("xfa_loaded"):
                notes.append("Formulaire XFA %s chargé par le moteur XFA (scripts exécutés localement, réseau et "
                             "fichiers bloqués). Remplissage au clavier ; enregistrement en mise à jour incrémentale."
                             % ("dynamique" if info.get("form_kind") == "xfa_dynamique" else "statique"))
            else:
                notes.append("Ce document est un formulaire XFA mais le moteur XFA n'est pas installé : seule sa page "
                             "de substitution (« Please wait… ») peut s'afficher. L'original n'est pas modifié.")
                self._banner(" ".join(notes), "Installer le moteur XFA", self._install_xfa_engine)
                return
        active = info.get("active", {})
        if self.settings.get("pdf_warn_active_content", True) and (active.get("javascript") or active.get("attachments")):
            parts = []
            if active.get("javascript"):
                parts.append("%d script(s)" % active["javascript"])
            if active.get("attachments"):
                parts.append("%d pièce(s) jointe(s)" % active["attachments"])
            notes.append("Contenu actif : %s. Les scripts ne peuvent ni accéder au réseau ni aux fichiers." %
                         ", ".join(parts))
        if info.get("security", {}).get("encrypted"):
            notes.append("Document chiffré (permissions : voir Infos).")
        if notes:
            self._banner(" ".join(notes))
        else:
            self.banner.hide()

    def _banner(self, text: str, action: str = "", slot=None) -> None:
        self.banner_text.setText(text)
        if action and slot:
            self.banner_action.setText(action)
            try:
                self.banner_action.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.banner_action.clicked.connect(slot)
            self.banner_action.setMinimumWidth(self.banner_action.sizeHint().width())
            self.banner_action.show()
        else:
            self.banner_action.hide()
        self.banner.show()

    def _install_xfa_engine(self) -> None:
        if not ui_kit.confirm(self, "Moteur XFA", "Télécharger le moteur PDFium V8 + XFA (~13 Mo, pdfium-binaries, "
                              "empreinte vérifiée) ? Il sera utilisé au prochain démarrage de l'appli.", "Télécharger"):
            return
        import subprocess
        import sys
        tool = pathlib.Path(__file__).resolve().parent.parent / "tools" / "install_pdfium_xfa.py"
        subprocess.Popen([sys.executable, str(tool)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.status("Téléchargement du moteur XFA lancé ; redémarrez l'appli ensuite.")

    # -- état, enregistrement --

    def _on_state(self) -> None:
        s = self.session
        self.b_undo.setEnabled(s.can_undo())
        self.b_redo.setEnabled(s.can_redo())
        self.b_undo.setToolTip("Annuler : %s (Ctrl+Z)" % s.undo_label() if s.can_undo() else "Annuler")
        self.b_redo.setToolTip("Rétablir : %s (Ctrl+Y)" % s.redo_label() if s.can_redo() else "Rétablir")
        name = s.path.name if s.path else "Sans titre"
        self.title.setText(name + (" — modifié" if s.dirty else ""))
        HOOKS["status"]("PDF : " + ("modifié" if s.dirty else "enregistré"))
        self.stateChanged.emit()

    def undo(self) -> None:
        if self.view.form_focus:
            self.session.run(lambda doc: doc.form_undo(doc.current_page), PRIO_SAVE)
        else:
            self.session.undo()

    def redo(self) -> None:
        if self.view.form_focus:
            self.session.run(lambda doc: doc.form_undo(doc.current_page, True), PRIO_SAVE)
        else:
            self.session.redo()

    def _save_mode(self):
        mode = self.settings.get("pdf_save_mode", "auto")
        return None if mode == "auto" else (mode == "incremental")

    def save(self, callback=None) -> None:
        if self.session.path is None:
            self.save_as_dialog(callback)
            return
        self.status("Enregistrement…")
        self.session.save(incremental=self._save_mode(), callback=callback)

    def save_as_dialog(self, callback=None) -> None:
        start = str(self.session.path) if self.session.path else "formulaire.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer le PDF", start, FILE_FILTER)
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            self.session.save(path, incremental=False if self.session.path is None else self._save_mode(),
                              force=True, callback=callback)

    def _on_save_failed(self, message: str) -> None:
        self.status("Enregistrement impossible : %s" % message)
        if ui_kit.confirm(self, "Enregistrement impossible", "%s\n\nEnregistrer ailleurs ?" % message,
                          "Enregistrer sous…"):
            self.save_as_dialog()

    def _on_conflict(self, path: str) -> None:
        choice = ui_kit.choose(self, "Fichier modifié ailleurs",
                               "« %s » a été modifié par un autre logiciel depuis son ouverture." %
                               pathlib.Path(path).name,
                               [("mine", "Garder ma version"), ("save_as", "Enregistrer sous…"),
                                ("reload", "Recharger (perdre mes changements)")])
        if choice == "mine":
            self.session.save(incremental=self._save_mode(), force=True)
        elif choice == "save_as":
            self.save_as_dialog()
        elif choice == "reload":
            self.session.open_path(self.session.path)

    def confirm_leave(self) -> bool:
        """Document modifié : enregistrer / fermer sans enregistrer / annuler. False = annulé."""
        if not self.session.dirty:
            return True
        name = self.session.path.name if self.session.path else "Sans titre"
        choice = ui_kit.choose(self, "Document modifié", "« %s » a des modifications non enregistrées." % name,
                               [("save", "Enregistrer"), ("discard", "Ne pas enregistrer")])
        if choice == "discard":
            if self.session.path is not None:
                from . import fileio
                fileio.drop_recovery(self.session.path)
            return True
        if choice == "save":
            done = []
            self.save(callback=lambda ok: done.append(ok))
            from PySide6.QtWidgets import QApplication
            import time
            end = time.perf_counter() + 120
            while not done and time.perf_counter() < end:
                QApplication.processEvents()
                time.sleep(0.005)
            return bool(done and done[0])
        return False

    def request_close(self) -> None:
        if self.confirm_leave():
            self.closeRequested.emit()

    def shutdown(self) -> None:
        """Fermeture : document fermé dans le moteur, tâches en attente annulées, images libérées (tuiles,
        miniatures : sinon ~20 Mo restaient par éditeur fermé, mesuré)."""
        self._recovery.stop()
        self.view.set_overlay(None)
        for job in list(self.view._pending.values()) + list(self.view._thumb_jobs.values()) +                 list(self.thumbs._jobs.values()):
            job.cancel()
        self.view._pending.clear()
        self.view.cache.clear()
        self.view.thumbs.clear()
        self.thumbs._thumbs.clear()
        self.session.close()

    # -- outils --

    def set_mode(self, mode: str) -> None:
        info = self.session.info
        if mode == "design" and info.get("is_xfa"):
            self.status("Formulaire XFA : sa conception se fait dans un concepteur XFA (Adobe Designer) ; ici, "
                        "remplissage seulement. Pour un nouveau formulaire : Nouveau (AcroForm).")
            mode = "fill"
        if mode in ("comment", "pages", "protect", "content") and info.get("is_xfa") and mode != "protect":
            self.status("Formulaire XFA : pages et commentaires sont gérés par le formulaire lui-même.")
            mode = "fill"
        self.mode = mode
        self.designer.set_active(mode == "design")
        if self.content is not None or mode == "content":
            self._ensure_content().set_active(mode == "content")
        if mode != "comment" and self.annot is not None:
            self.annot.set_tool(None)
        if mode != "protect":
            from . import protect_actions
            protect_actions.leave(self)
        self.view.set_tool("hand" if mode == "hand" else "select")
        self.right.setVisible(mode == "design")
        self.context_bar.setCurrentWidget(self.context_pages.get(mode, self.context_pages["fill"]))
        self._sync_tools()

    def _sync_tools(self) -> None:
        for key, b in self.tool_buttons.items():
            b.setChecked(key == self.mode)

    def sync_design_tools(self, kind) -> None:
        for k, b in self.kind_buttons.items():
            b.setChecked(k == kind)

    def sync_tab_button(self, on: bool) -> None:
        self.b_tab_order.setChecked(on)

    def show_properties(self) -> None:
        self.right.show()

    def show_left(self, name: str) -> None:
        if name not in self.left_tabs:
            name = "Pages"
        for key, (b, w) in self.left_tabs.items():
            b.setChecked(key == name)
        index = list(self.left_tabs).index(name)
        self.left_stack.setCurrentIndex(index)
        self.left.show()

    def toggle_reading(self) -> None:
        on = self.left.isVisible() or self.context_bar.isVisible()
        for w in (self.left, self.context_bar):
            w.setVisible(not on)
        for b in self.tool_buttons.values():
            b.setVisible(not on)
        self.b_read.setChecked(on)

    def toggle_fullscreen(self) -> None:
        fn = HOOKS.get("fullscreen")
        if fn:
            fn(None)

    def _toggle_highlight(self) -> None:
        self.settings["pdf_forms_highlight"] = self.b_highlight.isChecked()
        self._apply_highlight()

    def _apply_highlight(self) -> None:
        on = bool(self.settings.get("pdf_forms_highlight", True))
        color = self.settings.get("pdf_forms_highlight_color", "#dde4ff").lstrip("#")
        rgb = int(color, 16) if len(color) == 6 else 0xDDE4FF
        alpha = int(self.settings.get("pdf_forms_highlight_alpha", 100)) if on else 0

        def job(doc):
            if doc.form:
                doc.c.FPDF_SetFormFieldHighlightColor(doc.form, 0, ((rgb & 0xFF) << 16) | (rgb & 0xFF00) | (rgb >> 16))
                doc.c.FPDF_SetFormFieldHighlightAlpha(doc.form, alpha)
                doc.revision += 1
            return True
        self.session.run(job, PRIO_SAVE, lambda *_a: [self.view.invalidate_page(i) for i in
                                                      range(self.view.page_count())])

    def check_required(self) -> None:
        def job(doc):
            return [f for f in doc.fields() if f["flags"] & 2 and not f["value"] and not f.get("checked")]

        def done(missing, error):
            if error is not None:
                self.status(str(error))
            elif not missing:
                self.status("Tous les champs obligatoires sont remplis." if self.session.info.get("fields") else
                            "Aucun champ AcroForm (formulaire XFA : le formulaire signale lui-même ses champs).")
            else:
                ui_kit.confirm(self, "Champs obligatoires", "%d champ(s) obligatoire(s) vide(s) :" % len(missing),
                               "OK", items=["p. %d — %s" % (f["page"] + 1, f["tooltip"] or f["name"]) for f in missing])
                first = missing[0]
                self.view.ensure_visible(first["page"], first["rect"])
        self.session.run(job, PRIO_SAVE, done)

    # -- navigation, recherche --

    def _on_page(self, i: int) -> None:
        labels = self.session.info.get("labels") or []
        self.page_field.setText(labels[i] if i < len(labels) and labels[i] else str(i + 1))
        self.thumbs.set_current(i)

    def _page_typed(self) -> None:
        text = self.page_field.text().strip()
        labels = self.session.info.get("labels") or []
        if text in labels:
            self.view.go_to_page(labels.index(text))
            return
        try:
            self.view.go_to_page(int(text) - 1)
        except ValueError:
            self._on_page(self.view.current)

    def _zoom_typed(self) -> None:
        try:
            value = float(self.zoom_field.text().replace("%", "").replace(",", ".").strip())
            self.view.set_zoom(value / 100.0)
        except ValueError:
            self.zoom_field.setText("%d %%" % round(self.view.zoom * 100))

    def mode_menu(self) -> None:
        m = ui_kit.menu(self)
        for key, text in MODE_LABELS.items():
            a = m.addAction(text)
            a.setCheckable(True)
            a.setChecked(key == self.view.mode)
            a.triggered.connect(lambda _c=False, k=key: (self.view.set_mode(k), self.b_mode.setText(MODE_LABELS[k])))
        m.exec(self.b_mode.mapToGlobal(self.b_mode.rect().bottomLeft()))

    def _focus_search(self) -> None:
        self.search_field.setFocus()
        self.search_field.selectAll()

    def _search_options_changed(self) -> None:
        self._search["query"] = None
        self.search_next(1)

    def search_next(self, step: int) -> None:
        query = self.search_field.text()
        if not query:
            self.view.clear_search()
            self.search_count.setText("")
            return
        if query != self._search["query"]:
            self._start_search(query)
            return
        order = self._search["order"]
        if not order:
            return
        self._search["pos"] = (self._search["pos"] + step) % len(order)
        page, index = order[self._search["pos"]]
        self.view.show_hit(page, index)
        self.search_count.setText("%d / %d" % (self._search["pos"] + 1, len(order)))

    def _start_search(self, query: str) -> None:
        """Recherche page par page EN FOND (priorité « fond ») ; les résultats arrivent au fil de l'eau, la page
        courante d'abord."""
        old = self._search.get("running")
        if old:
            for job in old:
                job.cancel()
        self.view.clear_search()
        opts = dict(match_case=self.b_case.isChecked(), whole_word=self.b_word.isChecked(),
                    ignore_accents=self.b_accent.isChecked())
        self._search = {"query": query, "pages": {}, "order": [], "pos": -1, "running": []}
        n = self.view.page_count()
        start = self.view.current
        pages = [(start + k) % n for k in range(n)]
        if self.session.info.get("is_xfa"):
            self.search_count.setText("XFA : pas de couche texte")
            return
        self.search_count.setText("…")
        jobs = self._search["running"]
        state = self._search

        def found(page, hits, error):
            if state is not self._search or error is not None:
                return
            state["pages"][page] = hits
            self.view.set_search_hits(page, hits)
            state["order"] = [(p, k) for p in sorted(state["pages"]) for k in range(len(state["pages"][p]))]
            if state["pos"] < 0 and state["order"]:
                first = next(((p, k) for p, k in state["order"] if p >= start), state["order"][0])
                state["pos"] = state["order"].index(first)
                self.view.show_hit(*first)
            total = len(state["order"])
            done = len(state["pages"]) == n
            self.search_count.setText(("%d / %d" % (state["pos"] + 1, total) if total else "0") + ("" if done else "…"))
        for page in pages:
            jobs.append(self.session.run(lambda doc, p=page: doc.search(p, query, **opts), PRIO_BACKGROUND + 1,
                                         lambda hits, err, p=page: found(p, hits, err)))

    def _go_to_field(self, field) -> None:
        if field:
            self.view.ensure_visible(field["page"], field.get("rect", (0, 0, 10, 10)))

    def _go_to_comment(self, item) -> None:
        if item:
            self.view.ensure_visible(item["page"], item["rect"])

    def _comment_menu(self, global_pos, item) -> None:
        from . import annots
        m = ui_kit.menu(self)
        a = m.addAction("Supprimer ce commentaire")
        a.triggered.connect(lambda: self.session.edit("Supprimer un commentaire",
                                                      lambda data: annots.delete(data, [(item["page"], item["xref"])]),
                                                      lambda *_a: self.refresh_comments()))
        m.exec(global_pos)

    def _open_link(self, uri: str) -> None:
        url = QUrl(uri)
        if url.scheme().lower() not in ("http", "https", "mailto"):
            self.status("Lien refusé (type « %s » non autorisé) : %s" % (url.scheme() or "fichier", uri))
            return
        if self.settings.get("pdf_confirm_links", True) and not ui_kit.confirm(
                self, "Lien externe", "Le document veut ouvrir :\n%s" % uri, "Ouvrir"):
            return
        QDesktopServices.openUrl(url)

    def _on_blocked(self, what: str) -> None:
        self.info_panel.add_blocked(what)
        self.status("Bloqué (sécurité) : %s" % what)

    def _script_question(self, kind, title_text, message, extra):
        """Alerte / question d'un script du document (fil de l'interface)."""
        if kind == "alert":
            if self.settings.get("pdf_js_alerts", True):
                ui_kit.confirm(self, title_text or "Message du document", message, "OK")
            return 1
        return ui_kit.ask_text(self, title_text or "Question du document", message, default=str(extra or ""))

    def _view_menu(self, global_pos, page, x, y) -> None:
        m = ui_kit.menu(self)
        sel = self.view.selection is not None
        a = m.addAction("Copier")
        a.setEnabled(sel)
        a.triggered.connect(self.view.copy_selection)
        if sel and not self.session.info.get("is_xfa"):
            for kind, text in (("highlight", "Surligner"), ("underline", "Souligner"), ("strikeout", "Barrer")):
                a = m.addAction(text)
                a.triggered.connect(lambda _c=False, k=kind: self._markup_selection(k))
        m.addSeparator()
        m.addAction("Ajuster à la largeur").triggered.connect(self.view.fit_width)
        m.addAction("Ajuster à la page").triggered.connect(self.view.fit_page)
        m.addAction("Faire pivoter la vue").triggered.connect(lambda: self.view.rotate_view(1))
        m.exec(global_pos)

    def _thumbs_menu(self, global_pos, pages) -> None:
        from . import page_actions as pa
        m = ui_kit.menu(self)
        for text, fn in (("Pivoter à droite", lambda: pa.rotate(self, 1, pages)),
                         ("Pivoter à gauche", lambda: pa.rotate(self, -1, pages)),
                         ("Dupliquer", lambda: pa.duplicate(self, pages)),
                         ("Supprimer", lambda: pa.delete(self, pages)),
                         ("Extraire…", lambda: pa.extract(self, pages)),
                         ("Insérer une page vierge après", lambda: pa.insert_blank(self, pages[-1] + 1)),
                         ("Insérer un PDF après…", lambda: pa.insert_file(self, pages[-1] + 1))):
            m.addAction(text).triggered.connect(fn)
        m.exec(global_pos)

    # -- commentaires --

    def _ensure_annot(self):
        if self.annot is None:
            from .annot_tools import AnnotController
            self.annot = AnnotController(self)
        return self.annot

    def _annot_tool(self, kind) -> None:
        ctl = self._ensure_annot()
        ctl.set_tool(None if ctl.tool == kind else kind)

    def sync_annot_tools(self, kind) -> None:
        for k, b in self.annot_buttons.items():
            b.setChecked(k == kind)

    def _annot_color_menu(self) -> None:
        self._ensure_annot().color_menu(self.sender())

    def _markup_selection(self, kind) -> None:
        self._ensure_annot().markup_selection(kind)

    # -- impression, export, OCR --

    def print_dialog(self) -> None:
        from . import printing
        printing.print_dialog(self)

    def export_menu(self) -> None:
        from . import exporting
        exporting.export_menu(self, self.b_export)

    def ocr_dialog(self) -> None:
        from . import ocr_actions
        ocr_actions.ocr_dialog(self)

    # -- divers --

    def status(self, text: str) -> None:
        self.status_label.setText(text)
        HOOKS["status"](text)

    def apply_settings(self, settings: dict) -> None:
        """Réglages appliqués à chaud (seulement ce qui a changé)."""
        new = dict(PDF_DEFAULTS)
        new.update({k: v for k, v in settings.items() if k.startswith("pdf_")})
        changed = {k for k in new if new.get(k) != self.settings.get(k)}
        self.settings.update(new)
        self.view.settings.update(new)
        if "pdf_view_background" in changed:
            from PySide6.QtGui import QColor
            self.view._bg = QColor(new["pdf_view_background"])
            self.view.viewport().update()
        if "pdf_cache_mb" in changed:
            self.view.cache.budget = int(new["pdf_cache_mb"]) * 1024 * 1024
            self.view.cache.trim()
        if changed & {"pdf_forms_highlight", "pdf_forms_highlight_color", "pdf_forms_highlight_alpha"}:
            self.b_highlight.setChecked(bool(new["pdf_forms_highlight"]))
            self._apply_highlight()

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.parent() and event.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:                  # Échap ne ferme JAMAIS le module (règle de l'appli)
            if self.mode in ("design", "comment", "content"):
                self.set_mode("fill")
            event.accept()
            return
        super().keyPressEvent(event)

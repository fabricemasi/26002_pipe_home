from pathlib import Path
from PySide6.QtCore import (
    Qt, Signal,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    C,
    apply_dwm_frame,
    font,
    resize_hit_test,
    start_native_move,
)
import ui_state
from browser_core import (
    DEFAULT_WORK_DIR_TYPE,
    WORK_DIR_TYPES,
    save_project_columns,
)
from row_delegates import (
    _square_checkbox_qss,
)


class _StepperField(QWidget):
    """Compteur "Nombre de colonnes" (ColumnConfigDialog) : boite en
    lecture + 2 petits boutons empiles ▲/▼, EXACTEMENT la maquette fournie
    par l'utilisateur (remplace le QSpinBox natif, dont le style de l'OS
    ne pouvait pas rendre cette disposition) — expose la MEME API minimale
    (value/setValue/valueChanged) qu'un QSpinBox, seuls les appelants
    utilises ci-dessous (voir _rebuild_blocks, ColumnConfigDialog.__init__)."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, parent=None):
        super().__init__(parent)
        self._min, self._max = minimum, maximum
        self._value = max(minimum, min(maximum, value))
        self.setFixedSize(70, 26)
        self.setStyleSheet(
            f"background: {C['well']}; border: 1px solid {C['border']}; border-radius: 4px;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.value_label = QLabel(str(self._value))
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFont(font(12, 400, mono=True))
        self.value_label.setStyleSheet(f"color: {C['text']}; background: transparent; border: none;")
        layout.addWidget(self.value_label, 1)

        btns = QWidget(self)
        btns.setFixedWidth(18)
        btns.setStyleSheet(f"background: transparent; border-left: 1px solid {C['border']};")
        btns_l = QVBoxLayout(btns)
        btns_l.setContentsMargins(0, 0, 0, 0)
        btns_l.setSpacing(0)
        up_btn = QPushButton("▲")
        down_btn = QPushButton("▼")
        for b, cb in ((up_btn, self._increment), (down_btn, self._decrement)):
            b.setFixedHeight(12)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {C['label']}; "
                f"border: none; font-size: 7px; padding: 0; }}"
                f"QPushButton:hover {{ color: {C['text']}; background: {C['hover']}; }}"
            )
            b.clicked.connect(cb)
            btns_l.addWidget(b)
        layout.addWidget(btns)

    def _increment(self):
        self.setValue(self._value + 1)

    def _decrement(self):
        self.setValue(self._value - 1)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int):
        value = max(self._min, min(self._max, value))
        if value != self._value:
            self._value = value
            self.value_label.setText(str(value))
            self.valueChanged.emit(value)

class _OmitListField(QWidget):
    """Petite liste "a omettre" (repertoires/fichiers) reutilisable dans
    ColumnConfigDialog : QListWidget + boutons +/- (ajout via
    QInputDialog.getText, meme pattern que Column._create_folder)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.list = QListWidget(self)
        self.list.setFixedHeight(96)
        self.list.setStyleSheet(
            f"QListWidget {{ background: {C['well']}; color: {C['text']}; "
            f"border: 1px solid {C['border']}; border-radius: 0px; }}"
            f"QListWidget::item {{ padding: 2px 4px; }}"
            f"QListWidget::item:selected {{ background: {C['sel_idle']}; }}"
        )
        layout.addWidget(self.list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        add_btn = QPushButton("+")
        remove_btn = QPushButton("-")
        for b in (add_btn, remove_btn):
            b.setFixedSize(24, 20)
            # Police EXPLICITE (voir la remarque de l'utilisateur,
            # "ajoute + et - sur les boutons" — les glyphes restaient
            # quasi invisibles, herites d'une police par defaut trop
            # discrete pour une si petite case) : grasse, bien plus
            # grande que le texte courant, pour que +/- restent lisibles
            # a cette taille de bouton.
            b.setFont(font(13, 700))
            b.setStyleSheet(
                f"QPushButton {{ background: {C['btn']}; color: {C['text']}; "
                f"border: 1px solid {C['btn_border']}; border-radius: 3px; padding: 0px; }}"
                f"QPushButton:hover {{ background: {C['btn_hover']}; }}"
            )
        add_btn.clicked.connect(self._add)
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _add(self):
        name, ok = QInputDialog.getText(self, "Ajouter", "Nom a omettre :")
        name = name.strip()
        if ok and name:
            self.list.addItem(name)

    def _remove_selected(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def values(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def set_values(self, values) -> None:
        self.list.clear()
        self.list.addItems([str(v) for v in (values or [])])

class _ColumnConfigBlock(QWidget):
    """Une CARTE "Colonne N" dans ColumnConfigDialog (largeur fixe, alignee
    a cote des autres dans une rangee defilante horizontalement) : nom +
    afficher repertoires/fichiers + listes a omettre + toggle Focus
    (independant par colonne, voir la remarque de l'utilisateur, "un
    toggle Focus independant par colonne") — reproduit la maquette fournie
    par l'utilisateur, "change l'interface de la fenetre scrupuleusement
    comme celle en piece jointe"."""

    CARD_WIDTH = 308

    def __init__(self, index: int, data: dict, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.CARD_WIDTH)
        self.setObjectName("ColCard")
        self.setStyleSheet(
            f"#ColCard {{ background: {C['chrome']}; border: 1px solid {C['border_soft']}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        name_row = QHBoxLayout()
        name_row.setSpacing(9)
        label = QLabel(f"Nom colonne {index + 3}")
        label.setFont(font(11, 400))
        label.setStyleSheet(f"color: {C['label']}; background: transparent;")
        name_row.addWidget(label)
        self.name_edit = QLineEdit(data.get("name", ""))
        self.name_edit.setStyleSheet(
            f"QLineEdit {{ background: {C['well']}; color: {C['text']}; "
            f"border: 1px solid {C['border']}; border-radius: 0px; padding: 3px 8px; }}"
        )
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        self.show_dirs_check = QCheckBox("Afficher les repertoires")
        self.show_files_check = QCheckBox("Afficher les fichiers")
        self.show_dirs_check.setChecked(bool(data.get("show_dirs", True)))
        self.show_files_check.setChecked(bool(data.get("show_files", False)))
        for cb in (self.show_dirs_check, self.show_files_check):
            cb.setStyleSheet(_square_checkbox_qss())
            layout.addWidget(cb)

        omit_row = QHBoxLayout()
        omit_row.setSpacing(10)
        dirs_col = QVBoxLayout()
        dirs_col.setSpacing(5)
        dirs_label = QLabel("Repertoires a omettre")
        dirs_label.setFont(font(9, 600, tracking=0.07))
        dirs_label.setStyleSheet(f"color: {C['label']}; background: transparent;")
        dirs_col.addWidget(dirs_label)
        self.omit_dirs = _OmitListField(self)
        self.omit_dirs.set_values(data.get("omit_dirs"))
        dirs_col.addWidget(self.omit_dirs)
        files_col = QVBoxLayout()
        files_col.setSpacing(5)
        files_label = QLabel("Fichiers a omettre")
        files_label.setFont(font(9, 600, tracking=0.07))
        files_label.setStyleSheet(f"color: {C['label']}; background: transparent;")
        files_col.addWidget(files_label)
        self.omit_files = _OmitListField(self)
        self.omit_files.set_values(data.get("omit_files"))
        files_col.addWidget(self.omit_files)
        omit_row.addLayout(dirs_col)
        omit_row.addLayout(files_col)
        layout.addLayout(omit_row)

        # Toggle "Focus" PAR COLONNE SUPPRIME (voir la remarque de
        # l'utilisateur, "supprime le toggle focus ... celui qui indique
        # coche focus le contenu du repertoire" — redondant/confus a cote
        # du toggle MAITRE "Focus" de ColumnConfigDialog, qui masque ou
        # affiche TOUTE la colonne fantome des vignettes). La valeur
        # persistee garde simplement celle DEJA enregistree pour ce niveau
        # (`_coerce_project_column`, repli `True` pour un bloc SANS config
        # anterieure — voir _rebuild_blocks) — plus aucun moyen de la
        # changer depuis cette fenetre, mais un fichier existant qui avait
        # deliberement "focus": False pour un niveau garde ce choix.
        self._focus_value = bool(data.get("focus", True))

    def data(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "show_dirs": self.show_dirs_check.isChecked(),
            "show_files": self.show_files_check.isChecked(),
            "omit_dirs": self.omit_dirs.values(),
            "omit_files": self.omit_files.values(),
            "focus": self._focus_value,
        }

class ColumnConfigDialog(QDialog):
    """Fenetre de configuration de la chaine de navigation d'UN projet (voir
    le badge numerote cliquable, Column._open_column_config) — reproduit la
    maquette fournie par l'utilisateur : nombre de colonnes, blocs "Colonne
    N" dynamiques (nom, afficher repertoires/fichiers, a omettre, Focus
    independant), puis un bloc "Repertoire de travail" (type/afficher/
    omettre, sans Focus — voir WORK_DIR_TYPES). Enregistrer ecrit le fichier
    de config DANS LE DOSSIER DU PROJET (voir save_project_columns, choix de
    l'utilisateur "dans le dossier du projet ... voyage avec le projet")."""

    # MIN_STEPS = 2 (Type+Projets seuls, AUCUN niveau intermediaire — voir
    # load_project_columns, "columns": [] est desormais une config VALIDE)
    # — voir la remarque de l'utilisateur, "peux-tu faire en sorte de
    # pouvoir setter en base 2 ?".
    MIN_STEPS = 2
    MAX_STEPS = 12

    def __init__(self, project_path: Path, config: dict | None, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        # Plus large qu'avant (etait 460x560) : les colonnes configurees se
        # rangent desormais cote a cote (voir _blocks_container, cartes de
        # largeur fixe) au lieu d'etre empilees verticalement — reproduit
        # la maquette fournie par l'utilisateur, "change l'interface de la
        # fenetre scrupuleusement comme celle en piece jointe".
        self.resize(980, 850)
        # Redimensionnable par les bords (voir nativeEvent/showEvent
        # ci-dessous, meme mecanisme que PipelineBrowser/SettingsWindow) —
        # voir la remarque de l'utilisateur, "fait la fenetre configuration
        # redimensionnable".
        self.setMinimumSize(760, 480)

        self._blocks: list[dict] = []
        if config is not None:
            for col in config["columns"]:
                self._blocks.append(dict(col))
            self._work_dir = dict(config["work_dir"])
            self._set_enabled = bool(config.get("set_enabled", True))
            self._focus_enabled = bool(config.get("focus_enabled", True))
            self._in_over_out_enabled = bool(config.get("in_over_out_enabled", True))
        else:
            self._blocks = [{
                "name": "Sous-projet", "show_dirs": True, "show_files": False,
                "omit_dirs": [], "omit_files": [], "focus": True,
            }]
            self._work_dir = {
                # "show_files": True (PAS False) : voir la remarque de
                # l'utilisateur, "active par defaut les fichiers dans
                # repertoire de travail" — repli SEULEMENT pour un NOUVEAU
                # projet (config is None) ; un projet DEJA configure garde
                # sa propre valeur enregistree, jamais reecrasee ici.
                "type": DEFAULT_WORK_DIR_TYPE, "show_dirs": True, "show_files": True,
                "omit_dirs": [], "omit_files": [],
            }
            self._set_enabled = True
            self._focus_enabled = True
            self._in_over_out_enabled = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        panel = QFrame(self)
        panel.setObjectName("ConfigPanel")
        panel.setStyleSheet(
            f"#ConfigPanel {{ background: {C['window']}; "
            f"border: 1px solid {C['border']}; border-radius: {ui_state.WINDOW_RADIUS}px; }}"
        )
        outer.addWidget(panel)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        head = QWidget(panel)
        head.setFixedHeight(34)
        head.setStyleSheet(f"background: {C['chrome']}; border-top-left-radius: {ui_state.WINDOW_RADIUS}px; "
                            f"border-top-right-radius: {ui_state.WINDOW_RADIUS}px;")
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(12, 0, 8, 0)
        title_label = QLabel(f"Configuration - {project_path.name}")
        title_label.setFont(font(11, 600))
        title_label.setStyleSheet(f"color: {C['text']}; background: transparent;")
        head_l.addWidget(title_label, 1)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        # Police EXPLICITE (voir _OmitListField, MEME correctif/MEME
        # raison — le glyphe restait quasi invisible sans elle, voir la
        # remarque de l'utilisateur, "je ne vois pas le x").
        close_btn.setFont(font(12, 700))
        close_btn.setStyleSheet(
            f"QPushButton {{ color: {C['label']}; background: transparent; border: none; padding: 0px; }}"
            f"QPushButton:hover {{ background: {C['hover']}; color: {C['text']}; }}"
        )
        close_btn.clicked.connect(self.reject)
        head_l.addWidget(close_btn)
        head.mousePressEvent = self._head_mouse_press
        panel_layout.addWidget(head)

        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(14, 12, 14, 12)
        self._body_layout.setSpacing(8)
        scroll.setWidget(body)
        panel_layout.addWidget(scroll, 1)

        spin_row = QHBoxLayout()
        spin_row.setSpacing(14)
        spin_label = QLabel("Nombre de colonnes")
        spin_label.setFont(font(12, 400))
        spin_label.setStyleSheet(f"color: {C['text']}; background: transparent;")
        spin_row.addWidget(spin_label)
        self.spin = _StepperField(self.MIN_STEPS, self.MAX_STEPS, 2 + len(self._blocks), self)
        self.spin.valueChanged.connect(self._on_spin_changed)
        spin_row.addWidget(self.spin)
        spin_hint = QLabel("2 premieres colonnes figees — Type puis Projet")
        spin_hint.setFont(font(9, 400))
        spin_hint.setStyleSheet(f"color: {C['dim']}; background: transparent;")
        spin_row.addWidget(spin_hint)
        spin_row.addStretch(1)
        self._body_layout.addLayout(spin_row)

        # Toggles maitres (voir la remarque de l'utilisateur, "j'aimerai
        # ajouter trois toggles ... set / focus / logiciels" puis "in over
        # et out") — a 0 : "set" saute directement de Projets a la colonne
        # apres le groupe IN/OVER/OUT/LOGICIELS (aucun niveau intermediaire
        # configure ci-dessous n'est alors utilise, quel que soit leur
        # nombre) ; "focus" masque la colonne Focus (vignettes) ; "in/over/
        # out" masque ces 3 colonnes du groupe (LOGICIELS reste). Toggle
        # "logiciels" SUPPRIME (voir la remarque de l'utilisateur, "supprime
        # le toggle logiciels") — desormais toujours affichee.
        toggles_row = QHBoxLayout()
        toggles_row.setSpacing(18)
        self.set_check = QCheckBox("Set")
        self.set_check.setChecked(self._set_enabled)
        self.set_check.setStyleSheet(_square_checkbox_qss())
        toggles_row.addWidget(self.set_check)
        self.focus_check_master = QCheckBox("Focus")
        self.focus_check_master.setChecked(self._focus_enabled)
        self.focus_check_master.setStyleSheet(_square_checkbox_qss(muted=True))
        toggles_row.addWidget(self.focus_check_master)
        self.in_over_out_check = QCheckBox("In / Over / Out")
        self.in_over_out_check.setChecked(self._in_over_out_enabled)
        self.in_over_out_check.setStyleSheet(_square_checkbox_qss(muted=True))
        toggles_row.addWidget(self.in_over_out_check)
        toggles_row.addStretch(1)
        self._body_layout.addLayout(toggles_row)

        # "Set" a 0 : "Focus"/"In / Over / Out" perdent tout sens (rien
        # avant lequel se distinguer, voir _chain_expected_total) —
        # decoches et desactives AUTOMATIQUEMENT, grises tant que "Set"
        # reste desactive — voir la remarque de l'utilisateur, "quand set
        # est desactive, desactive automatiquement focus, in over et out,
        # et grise les".
        def _on_set_toggled(checked: bool):
            if not checked:
                self.focus_check_master.setChecked(False)
                self.in_over_out_check.setChecked(False)
            self.focus_check_master.setEnabled(checked)
            self.in_over_out_check.setEnabled(checked)

        self.set_check.toggled.connect(_on_set_toggled)
        _on_set_toggled(self.set_check.isChecked())

        # "Colonne 1 - Type"/"Colonne 2 - Projet" : rangee label + boite
        # valeur (figee, italique) + note, comme les 2 premieres colonnes
        # FIXES de la maquette fournie par l'utilisateur.
        for fixed_index, fixed_label, fixed_value, fixed_note in (
            (1, "Type", project_path.parent.name, "Fixe — determine par le dossier racine"),
            (2, "Projet", project_path.name, "Fixe — determine par la selection en cours"),
        ):
            fixed_row = QHBoxLayout()
            fixed_row.setSpacing(14)
            name_lbl = QLabel(f"Colonne {fixed_index} — {fixed_label}")
            name_lbl.setFont(font(12, 400))
            name_lbl.setFixedWidth(150)
            name_lbl.setStyleSheet(f"color: {C['text']}; background: transparent;")
            fixed_row.addWidget(name_lbl)
            value_box = QLabel(fixed_value)
            value_box.setFont(font(11, 400, mono=True))
            value_box.setStyleSheet(
                f"background: {C['chrome']}; color: {C['label']}; font-style: italic; "
                f"border: 1px solid {C['border_soft']}; padding: 0 9px;"
            )
            value_box.setFixedHeight(25)
            fixed_row.addWidget(value_box)
            note_lbl = QLabel(fixed_note)
            note_lbl.setFont(font(9, 400))
            note_lbl.setStyleSheet(f"color: {C['dim']}; background: transparent;")
            fixed_row.addWidget(note_lbl)
            fixed_row.addStretch(1)
            self._body_layout.addLayout(fixed_row)

        # Cartes "Colonne N" cote a cote (voir _ColumnConfigBlock, largeur
        # fixe) dans leur PROPRE zone de defilement HORIZONTALE, imbriquee
        # dans la zone de defilement verticale du dialogue — reproduit la
        # rangee de cartes de la maquette fournie par l'utilisateur.
        blocks_scroll = QScrollArea(body)
        blocks_scroll.setWidgetResizable(True)
        blocks_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        blocks_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        blocks_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        blocks_host = QWidget()
        blocks_host.setStyleSheet("background: transparent;")
        self._blocks_container = QHBoxLayout(blocks_host)
        self._blocks_container.setContentsMargins(0, 0, 0, 0)
        self._blocks_container.setSpacing(16)
        blocks_scroll.setWidget(blocks_host)
        self._body_layout.addWidget(blocks_scroll)
        self._block_widgets: list[_ColumnConfigBlock] = []
        self._rebuild_blocks()

        self._body_layout.addStretch(1)

        # "Repertoire de travail" BLOQUEE en bas, HORS de la zone
        # deroulante (voir `scroll`/`self._body_layout` ci-dessus) — ajoutee
        # a `panel_layout` directement, entre `scroll` et `btn_row` (voir
        # plus bas) : reste TOUJOURS visible, quelle que soit la position
        # de defilement du reste du contenu — voir la remarque de
        # l'utilisateur, "je veux que la partie repertoire de travail soit
        # bloquee en bas vers les boutons".
        work_section = QWidget(panel)
        work_section.setStyleSheet("background: transparent;")
        work_layout = QVBoxLayout(work_section)
        work_layout.setContentsMargins(14, 10, 14, 0)
        work_layout.setSpacing(8)

        line = QFrame(work_section)
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background: {C['border_soft']}; border: none;")
        line.setFixedHeight(1)
        work_layout.addWidget(line)

        work_label = QLabel("REPERTOIRE DE TRAVAIL")
        work_label.setFont(font(10, 600, tracking=0.16))
        work_label.setStyleSheet(f"color: {C['accent']}; background: transparent;")
        work_layout.addWidget(work_label)

        type_row = QHBoxLayout()
        type_row.setSpacing(14)
        type_lbl = QLabel("Type")
        type_lbl.setFont(font(12, 400))
        type_lbl.setFixedWidth(60)
        type_lbl.setStyleSheet(f"color: {C['text']}; background: transparent;")
        type_row.addWidget(type_lbl)
        self.work_type_combo = QComboBox()
        self.work_type_combo.setFixedHeight(26)
        self.work_type_combo.setStyleSheet(
            f"QComboBox {{ background: {C['well']}; color: {C['text']}; font-style: italic; "
            f"border: 1px solid {C['border']}; border-radius: 0px; padding: 3px 8px; }}"
            f"QComboBox:hover {{ border: 1px solid {C['accent']}; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
        )
        for key, info in WORK_DIR_TYPES.items():
            self.work_type_combo.addItem(info["label"], key)
        idx = self.work_type_combo.findData(self._work_dir.get("type", DEFAULT_WORK_DIR_TYPE))
        self.work_type_combo.setCurrentIndex(max(0, idx))
        type_row.addWidget(self.work_type_combo)
        type_row.addStretch(1)
        work_layout.addLayout(type_row)

        self.work_show_dirs_check = QCheckBox("Afficher les repertoires")
        self.work_show_files_check = QCheckBox("Afficher les fichiers")
        self.work_show_dirs_check.setChecked(bool(self._work_dir.get("show_dirs", True)))
        # "Afficher les fichiers" active par defaut ICI aussi (repli True,
        # PAS False) — voir la remarque de l'utilisateur, "afficher les
        # fichiers doit etre active par defaut dans cette section" : filet
        # de securite en plus du defaut deja pose sur `self._work_dir`
        # (config is None, voir plus haut) — reste vrai meme si `self.
        # _work_dir` provenait d'un fichier plus ancien sans cette cle.
        self.work_show_files_check.setChecked(bool(self._work_dir.get("show_files", True)))
        for cb in (self.work_show_dirs_check, self.work_show_files_check):
            cb.setStyleSheet(_square_checkbox_qss())
            work_layout.addWidget(cb)

        work_omit_row = QHBoxLayout()
        work_omit_row.setSpacing(10)
        work_dirs_col = QVBoxLayout()
        work_dirs_col.setSpacing(5)
        work_dirs_label = QLabel("Repertoires a omettre")
        work_dirs_label.setFont(font(9, 600, tracking=0.07))
        work_dirs_label.setStyleSheet(f"color: {C['label']}; background: transparent;")
        work_dirs_col.addWidget(work_dirs_label)
        self.work_omit_dirs = _OmitListField(self)
        self.work_omit_dirs.set_values(self._work_dir.get("omit_dirs"))
        work_dirs_col.addWidget(self.work_omit_dirs)
        work_files_col = QVBoxLayout()
        work_files_col.setSpacing(5)
        work_files_label = QLabel("Fichiers a omettre")
        work_files_label.setFont(font(9, 600, tracking=0.07))
        work_files_label.setStyleSheet(f"color: {C['label']}; background: transparent;")
        work_files_col.addWidget(work_files_label)
        self.work_omit_files = _OmitListField(self)
        self.work_omit_files.set_values(self._work_dir.get("omit_files"))
        work_files_col.addWidget(self.work_omit_files)
        work_omit_row.addLayout(work_dirs_col)
        work_omit_row.addLayout(work_files_col)
        work_layout.addLayout(work_omit_row)

        work_note = QLabel("Le repertoire de travail peut aussi omettre certains repertoires ou fichiers.")
        work_note.setFont(font(9, 400))
        work_note.setStyleSheet(f"color: {C['dim']}; background: transparent;")
        work_layout.addWidget(work_note)

        panel_layout.addWidget(work_section)

        # Petit espace ENTRE les 2 boutons (pas colles l'un a l'autre),
        # tous 2 groupes a droite — voir la remarque de l'utilisateur,
        # "quand je disait separes, je voulais dire un petit espace"
        # (corrige un 1er essai qui les avait envoyes aux 2 extremites).
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(14, 10, 14, 10)
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Annuler")
        save_btn = QPushButton("Enregistrer")
        for b in (cancel_btn, save_btn):
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; "
            f"border: 1px solid {C['btn_border']}; border-radius: 4px; padding: 4px 14px; }}"
            f"QPushButton:hover {{ background: {C['btn_hover']}; }}"
        )
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {C['accent']}; color: {C['accent_text']}; "
            f"border: none; border-radius: 4px; padding: 4px 14px; }}"
            f"QPushButton:hover {{ background: {C['accent']}; }}"
        )
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        panel_layout.addLayout(btn_row)

    def _head_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            start_native_move(self)
            event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        apply_dwm_frame(self, ui_state.WINDOW_RADIUS, C["border"], resizable=True)

    _RESIZE_BORDER = 6

    def nativeEvent(self, eventType, message):
        """Redimensionnement par les bords (voir PipelineBrowser.nativeEvent/
        app_style.resize_hit_test, meme mecanisme) — necessite resizable=True
        dans showEvent ci-dessus (pose WS_THICKFRAME cote Windows)."""
        if eventType == b"windows_generic_MSG":
            result = resize_hit_test(self, message, self._RESIZE_BORDER)
            if result is not None:
                return result
        return super().nativeEvent(eventType, message)

    def _current_block_values(self) -> list[dict]:
        return [b.data() for b in self._block_widgets]

    def _rebuild_blocks(self):
        # Conserve les valeurs deja saisies, MEME celles temporairement
        # masquees par un aller-retour du spinner (ex. 5 -> 4 -> 5) : ne met
        # a jour QUE le prefixe actuellement visible de self._blocks (voir
        # la remarque de tete, "conserver les valeurs deja saisies") — les
        # entrees au-dela restent intactes tant qu'on ne les tronque pas
        # explicitement (jamais ici : seule la SAUVEGARDE ne retient que le
        # prefixe VISIBLE, voir _on_save/_current_block_values).
        if self._block_widgets:
            current = self._current_block_values()
            self._blocks[:len(current)] = current
        while self._blocks_container.count():
            item = self._blocks_container.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._block_widgets = []
        wanted = self.spin.value() - 2
        while len(self._blocks) < wanted:
            # Nom par defaut NON VIDE (voir la remarque de l'utilisateur,
            # "quand je passe d'une base 3 a 4, ca ne fonctionne pas, il
            # refuse d'augmenter la base") : un bloc cree avec un nom VIDE
            # se faisait discretement ELIMINER a l'enregistrement (voir
            # _on_save, `if c["name"]`) des que l'utilisateur oubliait de
            # le renommer avant de cliquer Enregistrer — le "nombre de
            # colonnes" retombait alors silencieusement a sa valeur
            # d'avant, donnant l'impression que le spinner "refusait"
            # d'augmenter la base alors qu'il l'augmentait bien, seule la
            # SAUVEGARDE perdait le nouveau niveau sans nom.
            # focus=True (pas False) : voir la remarque de l'utilisateur,
            # "pour les colonnes focus, je veux qu'il y ait toutes les
            # etapes du set entier ... si le projet est un projet base 4,
            # il doit y avoir 3 colonnes empilees, pour un projet base 5,
            # 4 colonnes empilees" — un niveau nouvellement ajoute (en
            # augmentant le spinner) participe donc desormais a la pile
            # Focus PAR DEFAUT, comme le tout premier niveau ("Sous-
            # projet") l'a toujours fait ; l'utilisateur reste libre de
            # decocher "Focus" ligne par ligne s'il veut en exclure un.
            self._blocks.append({
                "name": f"Colonne {len(self._blocks) + 3}", "show_dirs": True, "show_files": False,
                "omit_dirs": [], "omit_files": [], "focus": True,
            })
        for i, data in enumerate(self._blocks[:wanted]):
            block = _ColumnConfigBlock(i, data, self)
            self._blocks_container.addWidget(block)
            self._block_widgets.append(block)
        # Etirement final (voir la rangee HORIZONTALE de cartes ci-dessus,
        # __init__) : sans lui, peu de cartes s'etalaient toutes seules
        # sur toute la largeur au lieu de rester tassees a gauche comme
        # dans la maquette fournie par l'utilisateur.
        self._blocks_container.addStretch(1)

    def _on_spin_changed(self, _value):
        self._rebuild_blocks()

    def _on_save(self):
        columns = self._current_block_values()
        # Refuse (au lieu d'eliminer silencieusement, voir _rebuild_blocks
        # pour le detail du bug que ca causait) des qu'UN SEUL bloc visible
        # n'a pas de nom — jamais un filtre `if c["name"]` muet : perdre un
        # niveau sans que l'utilisateur le sache est exactement ce qui
        # donnait l'impression que "ca refuse d'augmenter la base". PAS de
        # `not columns` ici (contrairement a avant) : une liste VIDE est
        # desormais une configuration VALIDE ("base 2" — MIN_STEPS=2, voir
        # sa remarque, Type+Projets seuls) — voir la remarque de
        # l'utilisateur, "peux-tu faire en sorte de pouvoir setter en base
        # 2".
        if any(not c["name"] for c in columns):
            QMessageBox.warning(self, "Configuration", "Chaque colonne doit avoir un nom.")
            return
        work_dir = {
            "type": self.work_type_combo.currentData() or DEFAULT_WORK_DIR_TYPE,
            "show_dirs": self.work_show_dirs_check.isChecked(),
            "show_files": self.work_show_files_check.isChecked(),
            "omit_dirs": self.work_omit_dirs.values(),
            "omit_files": self.work_omit_files.values(),
        }
        # try/except (voir la remarque de l'utilisateur, "quand j'essaie
        # d'enregistrer une modification ... il ne se passe rien") : une
        # ecriture qui echoue (fichier verrouille par un autre programme,
        # droits insuffisants...) ne doit plus jamais se solder par une
        # exception NON rattrapee dans ce slot Qt — le dialogue restait
        # ouvert SANS aucun message, cause exacte de "ca ne prend pas en
        # compte les modifs" deja rencontree une fois (voir save_project_
        # columns/_clear_hidden, corrige separement pour le cas HIDDEN sur
        # Windows) : desormais un message explicite plutot qu'un silence.
        try:
            save_project_columns(self.project_path, {
                "columns": columns, "work_dir": work_dir,
                "set_enabled": self.set_check.isChecked(),
                "focus_enabled": self.focus_check_master.isChecked(),
                "in_over_out_enabled": self.in_over_out_check.isChecked(),
            })
        except OSError as exc:
            QMessageBox.warning(
                self, "Configuration", f"Impossible d'enregistrer la configuration :\n{exc}")
            return
        self.accept()

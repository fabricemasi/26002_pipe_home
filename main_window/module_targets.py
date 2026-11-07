"""Modules capables d'ouvrir un fichier : UNE table pour les menus contextuels (colonnes, groupe IN / OVER / OUT /
LOGICIELS, pellicule, planche, image du focus) et les boutons de mode de la barre de navigation, dégrisés sur un
fichier compatible (demande de l'utilisateur : un fichier compatible avec plusieurs modules les propose tous)."""

from pathlib import Path

from PySide6.QtCore import QTimer

from browser_core import entry_is_dir

# Clé -> (ligne du menu contextuel, bouton de la barre). Ordre = ordre des lignes du menu.
MODULES = {
    "viewer": ("Ouvrir dans la visionneuse", "btn_viewer"),
    "md": ("Ouvrir dans l'éditeur de texte", "btn_text_editor"),
    "board": ("Ouvrir dans le board", "btn_board"),
    "cad": ("Ouvrir dans le module CAD", "btn_board"),
    "sheet": ("Ouvrir dans le tableur", "btn_board"),
    "video": ("Ouvrir dans le module vidéo", "btn_video"),
    "font": ("Ouvrir dans le module typographique", "btn_font"),
    "pdf": ("Ouvrir dans l'éditeur PDF", "btn_pdf"),
}
# Clé -> méthode de PipelineBrowser qui ouvre le fichier dans le module.
OPENERS = {"md": "_open_md_editor", "board": "_open_board", "cad": "_open_cad_drawing", "sheet": "_open_spreadsheet",
           "video": "_open_video", "font": "_open_font", "pdf": "_open_pdf"}
SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm", ".csv", ".tsv")


def click_target(path) -> str | None:
    """Module ouvert par un SIMPLE clic sur le fichier `path` (demande de l'utilisateur, 2026-11-03) : « viewer »
    (image : visionneuse en focus), « md » (texte / code : module Markdown), « font » (police : module typographique),
    sinon None. Extensions seules (aucun accès disque)."""
    from config import EXR_EXTENSIONS, HDR_EXTENSIONS, IMAGE_EXTENSIONS, PSD_EXTENSIONS, RAW_EXTENSIONS, TX_EXTENSIONS
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS | EXR_EXTENSIONS | HDR_EXTENSIONS | PSD_EXTENSIONS | RAW_EXTENSIONS | TX_EXTENSIONS:
        return "viewer"
    import fm_markdown
    if fm_markdown.is_text_file(path):
        return "md"
    from .font_module import font_target
    if suffix != ".ufo" and font_target(path, False):
        return "font"
    return None


def module_targets(path, is_dir: bool) -> list:
    """Clés des modules (hors visionneuse) qui savent ouvrir `path`, dans l'ordre de MODULES. Extensions seules :
    aucun accès disque (appelé à chaque clic de sélection, ~35 µs)."""
    if path is None:
        return []
    path = Path(path)
    keys = []
    if not is_dir:
        import fm_board
        import fm_markdown
        import fm_video
        if fm_markdown.is_text_file(path):
            keys.append("md")
        suffix = path.suffix.lower()
        if fm_board.is_board_file(path):
            keys.append("board")
        elif fm_board.is_cad_drawing(path):
            keys.append("cad")
        elif suffix in SPREADSHEET_SUFFIXES:
            keys.append("sheet")
        if fm_video.is_media_file(path):
            keys.append("video")
    from .font_module import font_target
    if font_target(path, is_dir):
        keys.append("font")
    from .pdf_module import pdf_target
    if pdf_target(path, is_dir):
        keys.append("pdf")
    return keys


class ModuleTargetsMixin:
    """Méthodes de PipelineBrowser : ouvrir le fichier choisi (colonnes ou visionneuse) dans un module."""

    def _module_path(self) -> tuple:
        """(colonne, chemin, dossier ?) que les boutons de mode ouvriraient : l'image en cours quand la visionneuse
        est ouverte (focus ou planche : ses fichiers ne sont jamais des dossiers), sinon le choix le plus profond
        des colonnes (`_selected_path`)."""
        if getattr(self, "_project_columns_hidden", False):
            paths, index = getattr(self, "_viewer_paths", []), getattr(self, "_viewer_index", -1)
            if 0 <= index < len(paths):
                return None, Path(paths[index]), False
            return None, None, False
        column, path = self._selected_path()
        return column, path, path is not None and entry_is_dir(path)

    def _module_keys(self) -> set:
        """Modules qui savent ouvrir le fichier de `_module_path`, visionneuse comprise (fichier qu'elle sait montrer :
        image, PureRef, fichier dont l'aperçu existe ; jamais un dossier ni un fichier sans aperçu)."""
        _column, path, is_dir = self._module_path()
        keys = set(module_targets(path, is_dir))
        if path is not None and not is_dir:
            from column_parts.shared import opens_in_viewer
            if opens_in_viewer(Path(path)):
                keys.add("viewer")
        return keys

    def open_in_module(self, key: str, path, column=None):
        """Ouvre `path` dans le module `key` (voir MODULES). Visionneuse ouverte : elle se referme d'abord (les
        modules recouvrent les colonnes, modes exclusifs)."""
        path = Path(path)
        if key == "viewer":
            self._view_in_viewer(path, column)
            return
        if self._project_columns_hidden:
            self._set_columns_hidden(False, animate=False)
        getattr(self, OPENERS[key])(path)
        self._sync_mode_buttons()

    def on_file_clicked(self, column, path):
        """Simple clic (relâché sans glisser, sans touche) sur un fichier d'une colonne : image = visionneuse en focus
        sur elle, texte / code = module Markdown, police = module typographique, À CÔTÉ des colonnes (elles restent :
        `main_window/side_module.py`) ; le double-clic les passe en plein ; le bouton « précédent » de la souris, ou un
        clic sur un dossier / un autre fichier, les referme."""
        if path is None or getattr(self, "_project_columns_hidden", False):
            return
        key = click_target(path)
        if key is None or entry_is_dir(path):
            if self._side_module_open():
                QTimer.singleShot(0, self._close_side_modules)
            return
        QTimer.singleShot(0, lambda: self._open_side(key, path, column))

    def _open_selected_in(self, keys: tuple):
        """Bouton de mode de la barre (module fermé) : le fichier choisi s'ouvre dans le premier module de `keys`
        qui le sait (bouton « Board » : board, CAD ou tableur)."""
        column, path, is_dir = self._module_path()
        found = module_targets(path, is_dir)
        key = next((k for k in keys if k in found), None)
        if key is not None:
            self.open_in_module(key, path, column)

    def add_module_actions(self, menu, path, is_dir: bool, viewer: bool = False) -> dict:
        """Lignes « Ouvrir dans … » des modules compatibles avec `path`, ajoutées à `menu` ; `viewer` : la
        visionneuse aussi (colonnes, fichier qu'elle sait montrer). Renvoie {action: clé}."""
        keys = module_targets(path, is_dir)
        if viewer and not is_dir:
            from column_parts.shared import opens_in_viewer
            if opens_in_viewer(Path(path)):
                keys.insert(0, "viewer")
        return {menu.addAction(MODULES[key][0]): key for key in keys}

    def run_module_action(self, chosen, actions: dict, path, column=None) -> bool:
        """Ligne choisie parmi `actions` (add_module_actions) : le module s'ouvre APRÈS la fermeture du menu."""
        key = actions.get(chosen)
        if key is None:
            return False
        QTimer.singleShot(0, lambda: self.open_in_module(key, path, column))
        return True

    def _focus_menu(self, global_pos):
        """Clic droit sur l'image du focus : modules qui savent ouvrir l'image en cours."""
        from settings_widgets import Menu
        _column, path, is_dir = self._module_path()
        if path is None:
            return
        menu = Menu(self)
        actions = self.add_module_actions(menu, path, is_dir)
        if not actions:
            menu.addAction("Aucun module pour ce fichier").setEnabled(False)
        self.run_module_action(menu.exec(global_pos), actions, path)

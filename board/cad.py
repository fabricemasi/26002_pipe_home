"""Module CAD du board (MRO) : point d'entree et CONTROLEUR. Dessin technique 2D a la maniere d'AutoCAD,
DANS la page MRO (le board) : les entites sont des elements du board, sur sa page, a ses coordonnees, suivent
son zoom et son deplacement, sont enregistrees / annulees / copiees avec lui.

Fichiers du module (chaque couche n'importe que les precedentes) :
- `cad_geometry` : geometrie pure, conversions document <-> scene (Y vers le haut <-> vers le bas) ;
- `cad_model`    : donnees (calques dans `page["cad"]`, entites `cad_line`, heritage ByLayer) ;
- `cad_input`    : grammaire des saisies (absolu, @relatif, @polaire, distance directe, options, accrochages) ;
- `cad_snap`     : moteur d'accrochage (OSNAP, ORTHO, polaire, suivi d'accrochage, grille) ;
- `cad_items`    : rendu des entites dans la scene du board (`CadLineItem`) ;
- `cad_commands` : commandes interactives (LIGNE, DEPLACER, COPIER, EFFACER, poignees) et leur registre ;
- `cad_overlay`  : rendu temporaire par-dessus la page (elastique, marqueurs, guides, saisie dynamique) ;
- `cad`          : ce controleur (activation, souris, clavier, selection, invites, reglages, historique) ;
- `cad_ui`       : barre d'outils CAD (en haut), barre de commande (en bas), proprietes, calques, accrochages.

Activation : bouton CAD de la barre d'outils du board (`BoardPane.toggle_cad`). Mode actif : la vue du board
confie la souris (bouton gauche, droit) et le clavier au controleur ; la molette, le bouton du milieu et
Espace tenu deplacent / zooment toujours la page. Mode inactif : le board est inchange, les entites CAD
restent visibles (et se deplacent / suppriment comme les autres elements).

Clavier (mode CAD, focus dans la page) : la frappe va a la barre de commande (comme AutoCAD) ; Entree / Espace
= valider (Espace TAPE ; tenu + souris = deplacer la page) ; Echap = annuler ; Tab = champ suivant de la saisie
dynamique / accrochage suivant / completion ; Haut / Bas = saisies precedentes ; F2 historique, F3 OSNAP, F7
grille, F8 ORTHO, F9 accrochage a la grille, F10 polaire, F11 suivi d'accrochage, F12 saisie dynamique ;
Ctrl+1 proprietes ; Suppr = effacer la selection ; Ctrl+Z / Ctrl+Y = annuler / retablir (pendant LIGNE :
l'option annUler). Maj + clic droit = accrochage ponctuel ; clic droit = Entree pendant une commande, menu
sinon. Les touches ne sont jamais prises quand un champ de saisie a le focus."""
from __future__ import annotations

import copy
import math
import os
import sys
import time

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPen
from PySide6.QtWidgets import QApplication

from . import cad_aliases, cad_commands, cad_geometry as geo, cad_input, cad_model, cad_shapes, cad_snap, model
from .cad_items import CadLayer, CadLineItem, unit_of
from .cad_overlay import CadOverlay, native_cursor

DEFAULT_ON = {"board_cad_lineweights"}                # bascules allumees tant qu'aucun reglage n'est enregistre


TOGGLES = {  # nom -> (cle de reglage, libelle, touche) ; « grid » : la grille du board (reglage de la page)
    "osnap": ("board_cad_osnap", "OSNAP", "F3"),
    "grid": (None, "GRILLE", "F7"),
    "ortho": ("board_cad_ortho", "ORTHO", "F8"),
    "grid_snap": ("board_cad_grid_snap", "RESOL", "F9"),
    "polar": ("board_cad_polar", "POLAIRE", "F10"),
    "otrack": ("board_cad_otrack", "OTRACK", "F11"),
    "dyn": ("board_cad_dyn", "DYN", "F12"),
    "lineweight": ("board_cad_lineweights", "ÉPAIS.", "LWT"),
}
FKEYS = {Qt.Key_F3: "osnap", Qt.Key_F7: "grid", Qt.Key_F8: "ortho", Qt.Key_F9: "grid_snap",
         Qt.Key_F10: "polar", Qt.Key_F11: "otrack", Qt.Key_F12: "dyn"}
DEFAULTS = {"board_cad_osnap": True, "board_cad_ortho": False,
            "board_cad_grid_snap": False, "board_cad_polar": False, "board_cad_otrack": False,
            "board_cad_dyn": True}
# Proprietes recopiees par la pipette (MATCHPROP).
MATCHED = ("layer", "color", "lineweight", "linetype", "ltscale", "end1", "end2", "inner", "distribute", "resize")
CLICK_PX = 4                      # en deca : un clic (au-dela : un glisser)

# Journal des evenements souris du CAD (diagnostic des clics perdus) : PIPELINE_CAD_MOUSE_LOG=1.
MOUSE_LOG = bool(os.environ.get("PIPELINE_CAD_MOUSE_LOG"))


def _write_log(line: str):
    print(line, file=sys.stderr, flush=True)


class CadController(QObject):
    stateChanged = Signal()               # bascules, invite, historique : interface a jour
    selectionChanged = Signal()

    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.view = pane.view
        self.scene = pane.scene
        self.active = False
        self.settings: dict = {}
        self.engine = cad_snap.SnapEngine(self._source)
        self._index = geo.GridIndex()               # recherche localisee (voir _source)
        self._index_epoch = 0
        self._index_built = None
        self.command = None
        self.last_command = None
        self.last_point = None
        self.last_line_end = None
        self.buffer = ""
        self.history: list[tuple[str, str]] = []
        self.recall: list[str] = []
        self._recall_at = None
        self.override = None
        self.cycle = 0
        self._cycle_key = None
        self.cursor_view: QPointF | None = None
        self.cursor_doc = None
        self.res = None
        self.hover_item = None
        self.hover_grip = None
        self.hover_snap = None                 # hors commande : point caracteristique approche (aimant)
        self.window = None
        self.lasso = None
        self._press = None
        self._press_double = False             # appui venu d'un double-clic (voir mouse_double_click)
        self.last_pick_doc = None              # point (document) du dernier clic de choix d'objet (chanfrein…)
        self.last_pick_shift = False           # ce clic avait Maj (AJUSTER : Maj + clic = prolonger)
        # Valeurs des outils gardees d'une utilisation a l'autre (comme AutoCAD) : distance de decalage, distances /
        # angle / methode du chanfrein, rayon du raccord, mode Ajuster.
        self.tool_memory = {"offset": None, "chamfer_d1": 0.0, "chamfer_d2": 0.0, "chamfer_angle": 45.0,
                            "chamfer_method": "distance", "trim": True, "fillet_radius": 0.0}
        self._grip_press = None
        self._pick: list = []
        self._highlighted: list = []
        self._space_pending = False
        self._space_used = False
        self.lock_angle = None
        self.lock_distance = None
        self.lock_x = None
        self.lock_y = None
        self.dyn_field = 0
        self.look = {}
        self._override_sig = ()
        self._cursor_key = None
        self._cursor_blank_ok = False
        self._cross = None
        self.overlay = CadOverlay(self.view, self)
        self.overlay.hide()
        self._acquire_timer = QTimer(self)
        self._acquire_timer.setSingleShot(True)
        self._acquire_timer.timeout.connect(self._acquire_tick)
        self.view.zoomChanged.connect(self._view_changed)
        self.view.horizontalScrollBar().valueChanged.connect(self._view_changed)
        self.view.verticalScrollBar().valueChanged.connect(self._view_changed)
        self.scene.changed.connect(self._scene_changed)
        self.scene.pageChanged.connect(self._page_overrides_changed)
        self.scene.selectionChanged.connect(self._on_selection)
        from . import cad_ui
        self.ui = cad_ui.CadChrome(pane, self)
        self.overlay.attach_gpu(getattr(self.view, "gpu", None))     # rendu GPU deja allume (cad_gpu)
        self.apply_settings(pane._settings)

    # ------------------------------------------------------------------ reglages
    def apply_settings(self, settings: dict):
        self.settings = dict(settings or {})
        g = self.setting
        self.engine.settings = cad_snap.SnapSettings.from_settings({**DEFAULTS, **self.settings})
        from app_style import resolve_color_ref
        accent = getattr(self.scene, "accent", model.MIRO_ACCENT)
        self.look = {
            "accent": accent, "marker": resolve_color_ref(g("board_cad_marker_color"), "#ff7a00"),
            "marker_px": max(4, int(g("board_cad_marker_size") or 12)),
            "marker_width": max(1, min(3, int(g("board_cad_marker_thickness") or 2))),
            "show_markers": bool(g("board_cad_markers", True)), "tooltips": bool(g("board_cad_tooltips", True)),
            "magnet": bool(g("board_cad_magnet", True)),
            "grip_px": max(4, int(g("board_cad_grip_size") or 8)),
            "pickbox_px": max(2, int(g("board_cad_pickbox") or 5)),
            "crosshair": bool(g("board_cad_crosshair", True)),
            "crosshair_px": max(8, int(g("board_cad_crosshair_size") or 40)),
            "crosshair_full": bool(g("board_cad_crosshair_full", False)),
            "memory": bool(g("board_cad_crosshair_memory", True)),
            "cursor": "#1a1a1a", "rubber": "#1a1a1a",
            "ghost": resolve_color_ref(g("board_cad_ghost_color"), "#5f6b78"),
            "track": resolve_color_ref(g("board_cad_track_color"), "#18a058"),
            "grip_color": resolve_color_ref(g("board_cad_grip_color"), "#2f6bff"),
            "grip_border": resolve_color_ref(g("board_cad_grip_border_color"), "#ffffff"),
            "precision": max(0, min(8, int(g("board_cad_precision", 4) or 0))),
            "sel_window": self._frame_look("board_cad_window", 0),
            "sel_crossing": self._frame_look("board_cad_crossing", 1),
            **self._tip_colors(),
        }
        if self.scene.background.lightness() < 110:
            self.look.update(cursor="#e8eaec", rubber="#e8eaec")
        if not g("board_cad_crosshair_auto_color", True):
            self.look["cursor"] = resolve_color_ref(g("board_cad_crosshair_color"), self.look["cursor"])
        self._override_sig = self._crosshair_overrides()
        dense = max(1.0, float(g("board_cad_dense_px", 4) or 4))
        restyle = dense != getattr(self.scene, "cad_dense_px", None)
        self.scene.cad_grip_px = self.look["grip_px"]
        self.scene.cad_grip_color = self.look["grip_color"]
        self.scene.cad_grip_border = self.look["grip_border"]
        self.scene.cad_dense_px = dense
        self.scene.cad_antialiasing = bool(g("board_cad_antialiasing", True))
        self.scene.cad_crisp = bool(g("board_cad_crisp_lines", True))
        weights = bool(g("board_cad_lineweights", True))
        if weights != getattr(self.scene, "cad_lineweights", True):
            self.scene.cad_lineweights = weights            # affichage : epaisseurs reelles ou simples lignes
            self.scene.cad_style_changed()
            self.touch_index()                              # emprises (demi-epaisseur) refaites
            restyle = True
        try:
            samples = int(g("board_cad_aa_samples", "8"))
        except (TypeError, ValueError):
            samples = 8
        try:
            soft = float(g("board_cad_aa_filter", 75))
        except (TypeError, ValueError):
            soft = 75.0
        if soft != getattr(self.scene, "cad_filter", None):
            self.scene.cad_filter = max(50.0, min(200.0, soft))
            gpu = getattr(self.view, "gpu", None)
            if gpu is not None:
                gpu.request()
        if samples != getattr(self.scene, "cad_samples", None):
            self.scene.cad_samples = max(1, samples)
            gpu = getattr(self.view, "gpu", None)
            if gpu is not None:
                gpu.request()
        self.scene.cad_linear_blend = bool(g("board_cad_linear_blend", True))
        if restyle:
            CadLayer.of(self.scene).restyle()
        self.scene.update()
        ui = getattr(self, "ui", None)
        if ui is not None:
            ui.apply_bar_look()                             # fond des barres du CAD (reglage)
        self._cursor_key = None                             # couleur / taille du reticule : curseur refait
        self.refresh()

    def _crosshair_overrides(self) -> tuple:
        own = cad_model.drawing_overrides(self.cad_page())
        return tuple(sorted((k, repr(v)) for k, v in own.items() if k in cad_model.CROSSHAIR_KEYS))

    def _page_overrides_changed(self):
        """Reglages du dessin : le reticule remplace par ce dessin est relu."""
        if self._crosshair_overrides() != self._override_sig:
            self.apply_settings(self.settings)

    def _frame_look(self, prefix: str, crossing: int) -> dict:
        """Cadre de selection (Reglages > Module CAD > Selection) : fenetre (`board_cad_window_*`) ou capture
        (`board_cad_crossing_*`) ; une cle absente garde l'ancien dessin (`cad_overlay.DEFAULT_FRAMES`)."""
        from app_style import resolve_color_ref
        from .cad_overlay import DEFAULT_FRAMES
        base = DEFAULT_FRAMES[crossing]
        g = self.setting
        sides = g(f"{prefix}_border_enabled")
        colors = g(f"{prefix}_border")
        radius = g(f"{prefix}_radius")
        sides = ({k: bool(sides.get(k, True)) for k in base["sides"]} if isinstance(sides, dict)
                 else {k: bool(sides) for k in base["sides"]} if sides is not None else dict(base["sides"]))
        colors = {k: resolve_color_ref((colors or {}).get(k) if isinstance(colors, dict) else colors, base["colors"][k])
                  for k in base["colors"]}
        if isinstance(radius, dict):
            radius = {k: int(radius.get(k, 0) or 0) for k in base["radius"]}
        else:
            radius = {k: int(radius or 0) for k in base["radius"]}
        try:
            scale = float(g(f"{prefix}_line_scale", base["scale"]))
        except (TypeError, ValueError):
            scale = base["scale"]
        line = g(f"{prefix}_line", base["line"])
        return {"bg": resolve_color_ref(g(f"{prefix}_bg"), base["bg"]), "sides": sides, "colors": colors,
                "thickness": max(1, int(g(f"{prefix}_border_thickness", 1) or 1)), "radius": radius,
                "line": line if line in ("solid", "dash", "dot") else base["line"], "scale": max(10.0, scale)}

    @staticmethod
    def _tip_colors() -> dict:
        """Infobulles et champs de la saisie dynamique : couleurs des panneaux de l'appli (theme courant), texte
        garanti lisible sur leur fond."""
        from settings_menu import readable_on
        from settings_store import M
        back = QColor(M["panel_bg"])
        ink = QColor(M["value_fg"])
        field = QColor.fromRgbF(back.redF() + (ink.redF() - back.redF()) * 0.14,
                                back.greenF() + (ink.greenF() - back.greenF()) * 0.14,
                                back.blueF() + (ink.blueF() - back.blueF()) * 0.14)
        tip_bg = "#f0" + back.name()[1:]
        return {"tip_bg": tip_bg, "tip_fg": readable_on(ink.name(), back.name(), 4.5),
                "tip_border": M["panel_border"], "field_bg": "#f0" + field.name()[1:]}

    def setting(self, key, default=None):
        if key in cad_model.CROSSHAIR_KEYS:                 # reticule : ce dessin peut le remplacer
            own = cad_model.drawing_overrides(self.cad_page()).get(key)
            if own is not None:
                return own
        if key in self.settings:
            return self.settings[key]
        if key in DEFAULTS:
            return DEFAULTS[key]
        return default

    def toggle(self, name: str, value: bool | None = None):
        """Bascule d'un mode (F3, F7-F12, boutons de precision) : appliquee tout de suite, ENREGISTREE dans
        les reglages de l'appli. ORTHO et suivi polaire s'excluent (comme AutoCAD)."""
        key, label, fkey = TOGGLES[name]
        if key is None:                                 # F7 : la grille UNIQUE du board (reglage de la page)
            on = (not self.grid_on()) if value is None else bool(value)
            if on != self.grid_on():
                self.pane.toggle_grid()
            self.message(f"<{label} {'activée' if on else 'désactivée'}>")
            self.stateChanged.emit()
            return
        on = (not bool(self.setting(key, key in DEFAULT_ON))) if value is None else bool(value)
        changes = {key: on}
        if on and name == "ortho":
            changes["board_cad_polar"] = False
        elif on and name == "polar":
            changes["board_cad_ortho"] = False
        for k, v in changes.items():
            self._write_setting(k, v)
        self.message(f"<{label} {'activé' if on else 'désactivé'}>")
        self.apply_settings(self.settings)

    def grid_on(self) -> bool:
        return bool(self.scene.page.get("grid", True))

    def mode_on(self, name: str) -> bool:
        """Etat d'une bascule (boutons de precision)."""
        key = TOGGLES[name][0]
        return self.grid_on() if key is None else bool(self.setting(key, key in DEFAULT_ON))

    # -- unite de mesure : la geometrie est en unites du board, ce qui est saisi / affiche dans l'unite du dessin --
    def unit(self) -> float:
        """Unites du board par unite de mesure du dessin (la sienne, sinon Reglages > Module CAD > Unites)."""
        return unit_of(self.scene, self.cad_page())

    def unit_symbol(self) -> str:
        return cad_model.UNITS[cad_model.drawing_unit(self.cad_page(), self.scene.cad_unit)][1]

    def precision(self) -> int:
        """Decimales affichees : celles du dessin, sinon celles des reglages."""
        own = cad_model.drawing_overrides(self.cad_page()).get("board_cad_precision")
        return max(0, min(8, int(own))) if isinstance(own, (int, float)) else self.look.get("precision", 4)

    def fmt(self, value: float) -> str:
        """Longueur (unites du board) affichee dans l'unite du dessin."""
        return cad_input.format_number(value / self.unit(), self.precision())

    def fmt_point(self, p) -> str:
        k = self.unit()
        return cad_input.format_point((p[0] / k, p[1] / k), self.precision())

    def _write_setting(self, key, value):
        self.settings[key] = value
        self.pane._settings[key] = value
        from . import ui as board_ui
        writer = board_ui.SETTING_WRITER
        if writer is not None:
            try:
                writer(key, value)
            except Exception:                           # noqa: BLE001 - la session garde la valeur
                pass

    # ------------------------------------------------------------------ activation
    def activate(self):
        if self.active:
            return
        cad_aliases.refresh()                      # fichier .pgp modifie depuis : relu
        self.active = True
        self.view.finish_text_edit()
        for item in self.scene.selectedItems():
            if not getattr(item, "CAD", False):
                item.setSelected(False)
        self.overlay.setGeometry(self.view.viewport().rect())
        if self.overlay.gpu is None:
            self.overlay.show()
            self.overlay.raise_()
        self.apply_settings(self.pane._settings)
        self.ui.show()
        self._sync_cursor()
        self.view.setFocus()
        if not self.history:
            self.message("Mode CAD. Tapez une commande (LIGNE, DEPLACER, COPIER, EFFACER, CALQUE…) ou AIDE.")
        self.stateChanged.emit()

    def deactivate(self):
        if not self.active:
            return
        self.end_command()
        self.window = None
        self.lasso = None
        self._press = None
        self.active = False
        self.overlay.hide()
        self.overlay.invalidate()
        if self.overlay.gpu is not None:
            self.overlay.gpu.request()                      # retire l'apercu et le reticule peints
        self.ui.hide()
        self.scene.update()
        self.view._sync_cursor()
        self.stateChanged.emit()

    def _sync_cursor(self):
        """Curseur de la vue en mode CAD. Le reticule est le CURSEUR DU SYSTEME (Windows le deplace sans
        attendre l'appli : aucune trainee) ; il n'est peint par l'overlay que pour l'aimant (cale sur le point
        d'accrochage, immobile tant qu'il y reste) ou s'il est trop grand pour un curseur."""
        if not self.active:
            return
        self._cursor_key = None
        self._apply_cursor()                # pan compris : le reticule reste sous le pointeur (demande de l'utilisateur)

    def _cursor_plan(self) -> tuple:
        """(curseur du systeme ou None, reticule peint par l'overlay ?)."""
        look = self.look
        if not look.get("crosshair", True):
            if self._cross is None:
                self._cross = QCursor(Qt.CrossCursor)
            return self._cross, False
        prompt = self.prompt()
        point_prompt = prompt is not None and prompt.kind == "point"
        res = self.res
        if look.get("magnet") and point_prompt and res is not None and res.kind == "osnap":
            return None, True                               # aimant : sur les objets, jamais sur la grille
        if self.box_only():
            native = native_cursor(0, look["pickbox_px"], look["cursor"], self.view.viewport().devicePixelRatioF(),
                                   self.memory_color())
            return native, native is None
        if look.get("crosshair_full"):
            return None, True                               # bras jusqu'aux bords : aucun curseur du systeme
        if self.selecting_area():
            # Fenetre de selection / trace en cours : le reticule est peint DANS LA MEME IMAGE que le cadre (signale :
            # « latence entre le curseur et le cadre de selection » — le curseur du systeme avance, le cadre suit
            # une image plus tard ; peints ensemble, ils ne se decalent jamais).
            return None, True
        if look.get("magnet") and prompt is None and self.hover_snap is not None:
            return None, True
        ratio = self.view.viewport().devicePixelRatioF()
        box = 0 if point_prompt or self.selecting_area() else look["pickbox_px"]
        native = native_cursor(look["crosshair_px"], box, look["cursor"], ratio, self.memory_color())
        return native, native is None

    def box_only(self) -> bool:
        """Commande de MODIFICATION en cours (AJUSTER, DECALER, DEPLACER…) : le reticule n'est plus que le petit carre
        de selection, sans bras, jusqu'a la fin de la commande (demande de l'utilisateur)."""
        return self.command is not None and getattr(self.command, "MODIFY", False)

    def selecting_area(self) -> bool:
        """Une fenetre de selection ou un trace a main levee est en cours : le carre central du reticule disparait
        (demande de l'utilisateur), les bras restent."""
        return self.window is not None or self.lasso is not None

    def shift_held(self) -> bool:
        return bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)

    def memory_color(self) -> str | None:
        """Pipette en cours avec un objet source : sa couleur (indicateur « des proprietes sont en memoire » sur le
        reticule), sinon None."""
        source = getattr(self.command, "source", None) if self.command is not None else None
        if source is None or not self.look.get("memory", True) or source.scene() is not self.scene:
            return None
        color = source.props()["color"]
        return color if isinstance(color, str) and QColor(color).isValid() else "#808080"

    def _apply_cursor(self):
        if self.cursor_view is None:
            return
        native, painted = self._cursor_plan()
        if native is None:
            if not painted or self._cursor_key == "blank":
                return
            if (self.look.get("magnet") or self.selecting_area()) and not self._cursor_blank_ok:
                return                                      # cache apres la 1re peinture du reticule (aimant, cadre)
            key = "blank"
            self.view.viewport().setCursor(Qt.BlankCursor)
        else:
            key = id(native)
            if key != self._cursor_key:
                self.view.viewport().setCursor(native)
        self._cursor_key = key
        self._cursor_blank_ok = False

    def painted_cursor_shown(self):
        """L'overlay vient de peindre le reticule : le curseur du systeme peut disparaitre (jamais d'image sans
        reticule entre les deux)."""
        if self._cursor_key != "blank":
            self._cursor_blank_ok = True
            self._apply_cursor()

    # ------------------------------------------------------------------ conversions
    def view_to_doc(self, pos) -> tuple:
        scene_point = self.view.viewportTransform().inverted()[0].map(QPointF(pos))
        return geo.to_doc(scene_point.x(), scene_point.y())

    def doc_to_view(self, p) -> QPointF:
        x, y = geo.to_scene(p)
        return self.view.viewportTransform().map(QPointF(x, y))

    def scale(self) -> float:
        return max(1e-9, float(self.view.zoom()))

    def _scene_rect(self, rect) -> QRectF:
        xmin, ymin, xmax, ymax = rect
        return QRectF(xmin, -ymax, xmax - xmin, ymax - ymin)

    def touch_index(self, *_args):
        """Index des accrochages a reconstruire en entier a la prochaine recherche (les ajouts, retraits et
        deplacements ordinaires sont suivis un par un : `_source`)."""
        self._index_epoch += 1

    @staticmethod
    def _index_box(item) -> tuple:
        if item.CURVED:
            x0, y0, x1, y1 = item.doc_bounds()
        else:
            a, b = item.points()
            x0, y0, x1, y1 = min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])
        half = float(item.props()["lineweight"]) / 2.0
        return x0 - half, y0 - half, x1 + half, y1 + half

    def tess_tol(self) -> float:
        """Finesse des apercus de courbes (fantomes, survol) : un demi-pixel d'ecran, en unites du document."""
        return 0.5 / self.scale()

    def _source(self, rect):
        """Entites CAD visibles dont l'emprise (geometrie + demi-epaisseur) touche `rect` (document). Index en
        grille propre au CAD : l'index BSP de la scene ne sert a rien ici (scene du board de 10^6 unites de cote :
        ses cellules contiennent tout — mesure, 3 000 lignes : 3,5 ms par requete, chaque emprise relue). Tenu a
        jour LIGNE PAR LIGNE (journal `CadLayer.changed`) : le reconstruire a chaque ligne tracee figeait le
        premier mouvement qui suivait (~200 ms a 10 000 lignes)."""
        layer = CadLayer.of(self.scene)
        if self._index_built != self._index_epoch or self._index.needs_rebuild():
            layer.take_changes()
            self._index.build([(item, self._index_box(item)) for item in self.cad_items()])
            self._index_built = self._index_epoch
        else:
            for item in layer.take_changes():
                if self._alive(item):
                    self._index.insert(item, self._index_box(item))
                else:
                    self._index.remove(item)
        found = []
        for item in self._index.query(rect):
            if self._alive(item):
                if item.isVisible():
                    found.append(item)
            else:
                self._index.remove(item)                    # supprimee (objet C++ detruit) : jamais plus proposee
        return found

    def _alive(self, item) -> bool:
        """L'entite est dans la scene du board (et son objet C++ existe encore : une entite supprimee puis detruite
        par `deleteLater` leve `RuntimeError` — l'index en gardait une trace et plus rien n'etait selectionnable dans
        sa zone, signale)."""
        try:
            return item.scene() is self.scene
        except RuntimeError:
            return False

    def cad_items(self) -> list:
        """Entites CAD de la page (lignes, arcs, cercles, polylignes : toutes heritent de CadLineItem)."""
        return [i for i in self.scene.board_items() if isinstance(i, CadLineItem)]

    def cad_page(self) -> dict:
        return cad_model.page_cad(self.scene.page)

    # ------------------------------------------------------------------ invites / historique
    def prompt(self) -> cad_commands.Prompt | None:
        if self.command is not None and not self.command.finished:
            return self.command.prompt()
        return None

    def prompt_line(self) -> str:
        prompt = self.prompt()
        return prompt.line() if prompt is not None else "Commande :"

    def message(self, text: str, error: bool = False):
        self.history.append((text, "error" if error else "info"))
        del self.history[:-400]
        self.stateChanged.emit()

    def echo(self, text: str):
        self.history.append((f"{self.prompt_line()} {text}".rstrip(), "echo"))
        del self.history[:-400]

    def help(self):
        names = [f"{e.name} ({', '.join(e.aliases[:3])}) — {e.label}" for e in cad_commands.REGISTRY if e.available]
        self.message("Commandes disponibles :\n  " + "\n  ".join(names))
        planned = [e.name for e in cad_commands.REGISTRY if e.planned]
        self.message("Prévues (pas encore disponibles) : " + ", ".join(planned))

    # ------------------------------------------------------------------ commandes
    def run(self, name: str, echo: bool = True):
        """Lance une commande par son nom ou alias (barre d'outils, barre de commande, raccourci : meme
        chemin)."""
        entry = cad_commands.lookup(name)
        if echo:
            self.echo(name.upper())
        if entry is None:
            self.message(f"Commande inconnue « {name} ». Tapez AIDE pour la liste.", error=True)
            return
        if not entry.available:
            self.message(f"« {entry.name} » ({entry.label}) : prévue en {entry.planned}, pas encore disponible.",
                         error=True)
            return
        if not self.active:
            self.activate()
        # Fenetre de selection en attente de son 2e coin (clic dans le vide) : abandonnee. Gardee, elle survivait a la
        # commande et le clic suivant sur la ligne tout juste tracee la refermait au lieu de selectionner (bug signale :
        # « parfois une ligne creee est impossible a selectionner »).
        self.window = None
        self.lasso = None
        if isinstance(entry.factory, type):
            self.end_command()
            self.command = entry.factory(self)
            self.last_command = entry.name
            self._reset_point_state()
            self.command.start()
            self._after_step()
        else:
            entry.factory(self)
            self.refresh()

    def end_command(self):
        """Termine la commande en cours (Echap, autre commande, annuler, fermeture) : ce qu'elle a deja cree
        est GARDE et entre dans l'annulation (comme AutoCAD)."""
        command, self.command = self.command, None
        if command is not None and not command.finished:
            command.cancel()
        self.window = None
        self.lasso = None
        self._end_selection_prompt()
        self.highlight([])
        self.engine.reset_tracking()
        self._reset_point_state()
        self.scene.cad_show_grips = True
        if command is not None:
            self.stateChanged.emit()

    def _after_step(self):
        command = self.command
        if command is not None and command.finished:
            self.command = None
            self.window = None
            self.lasso = None
            self.highlight([])
            self.engine.reset_tracking()
            self._end_selection_prompt()
            self.scene.cad_show_grips = True
            self._reset_point_state()
        elif command is not None:
            self.scene.cad_show_grips = False
        self.refresh()
        self.stateChanged.emit()

    def _reset_point_state(self):
        self.lock_angle = self.lock_distance = self.lock_x = self.lock_y = None
        self.dyn_field = 0
        self.override = None
        self.cycle = 0

    # -- services rendus aux commandes --
    def selection(self) -> list:
        return [i for i in self.scene.selectedItems() if isinstance(i, CadLineItem) and i.isVisible()]

    def editable(self, items) -> list:
        out = [i for i in items if not i.locked()]
        skipped = len(items) - len(out)
        if skipped:
            self.message(f"{skipped} objet(s) sur un calque verrouillé (ou verrouillé) : ignoré(s).", error=True)
        return out

    def begin_object_selection(self):
        self._pick = []
        self.scene.clearSelection()

    def _end_selection_prompt(self):
        if self._pick:
            self._pick = []
            self.scene.clearSelection()

    def highlight(self, items):
        self._highlighted = list(items)
        self.overlay.update()

    def create_line(self, a, b):
        cad = self.cad_page()
        layer = cad_model.layer_by_id(cad, cad["current"])
        data = model.new_item("cad_line", **cad_model.new_line_values(cad, a, b))
        data["z"] = self.scene.next_z()
        item = self.scene._add(data)
        if layer is not None and not layer["visible"]:
            self.message(f"Le calque courant « {layer['name']} » est masqué : la ligne est créée mais invisible.",
                         error=True)
        return item

    def create_entity(self, kind: str, geometry: dict, source=None):
        """Entite neuve (arc, cercle, polyligne, ligne) : proprietes COURANTES, ou celles de `source` (memes calque,
        couleur, terminaisons…) ; pas encore dans l'annulation (`commit_created`)."""
        if source is not None:
            data = source.to_dict()
            for key in cad_shapes.GEOMETRY_KEYS.get(source.kind, ()):
                data.pop(key, None)
            data.update(id=model.new_id(), type=kind, locked=False, z=self.scene.next_z(), **copy.deepcopy(geometry))
        else:
            data = model.new_item(kind, **cad_model.new_entity_values(self.cad_page(), **geometry))
            data["z"] = self.scene.next_z()
        return self.scene._add(data)

    def hatch_tol(self) -> float:
        """Finesse du decoupage des courbes pour les zones a hachurer (unites du document)."""
        return 0.05

    def hatch_segments(self) -> list:
        """Trace de toutes les entites visibles (courbes decoupees) : ce qui delimite les zones a hachurer. Ni les
        hachures ni les cotations n'en font partie."""
        out = []
        for item in self.cad_items():
            if getattr(item, "AREA", False) or item.kind in ("cad_dim", "cad_text") or not item.isVisible():
                continue
            out.extend(cad_shapes.display_segments(item.prims(), self.hatch_tol()))
        return out

    def send_to_back(self, item):
        """Sous tous les autres elements du board (une hachure ne cache jamais les traits qu'elle remplit)."""
        low = min([i.zValue() for i in self.scene.board_items() if i is not item] or [0.0])
        item.setZValue(low - 1.0)

    def dim_style(self) -> dict:
        """Style des cotations creees maintenant (Reglages > Module CAD > Cotations), en unites du board : valeurs en
        unites de mesure du dessin x echelle ; copie dans chaque cotation (le changer ne touche pas les existantes)."""
        k = self.unit() * float(self.setting("board_cad_dim_scale", 100) or 100) / 100.0

        def value(key, default):
            return float(self.setting(key, default) or 0) / 100.0 * k
        return {"dim_text": max(1e-6, value("board_cad_dim_text", 250)), "dim_arrow": value("board_cad_dim_arrow", 250),
                "dim_gap": value("board_cad_dim_gap", 100), "dim_over": value("board_cad_dim_over", 125),
                "dim_arrow_kind": str(self.setting("board_cad_dim_arrow_kind", "triangle") or "triangle"),
                "dim_dec": int(self.setting("board_cad_dim_decimals", 2) or 0), "dim_unit": self.unit()}

    def text_style(self) -> dict:
        """Style des textes crees maintenant (Reglages > Module CAD > Textes) : hauteur en unites du board (valeur en
        centiemes de l'unite de mesure du dessin), police, justifications TEXTE / MTEXTE, interligne."""
        from . import cad_text
        height = float(self.setting("board_cad_text_height", 250) or 250) / 100.0 * self.unit()
        justify = str(self.setting("board_cad_text_justify", "L") or "L")
        mjustify = str(self.setting("board_cad_mtext_justify", "TL") or "TL")
        return {"height": max(1e-6, height), "font": str(self.setting("board_cad_text_font", "") or cad_text.DEFAULT_FONT),
                "justify": justify if justify in cad_text.JUSTIFY else "L",
                "mjustify": mjustify if mjustify in cad_text.JUSTIFY else "TL",
                "spacing": max(0.25, float(self.setting("board_cad_text_spacing", 100) or 100) / 100.0)}

    def set_entity_values(self, item, values: dict):
        """Champs d'une entite changes TOUT DE SUITE, hors annulation (saisie d'un texte en cours : voir
        `push_change`)."""
        data = item.to_dict()
        data.update(copy.deepcopy(values))
        item.apply(data)
        self.overlay.update()

    def snapshot_items(self, items) -> dict:
        return self.scene.snapshot([i.item_id for i in items])

    def push_change(self, before: dict, items, text: str):
        """Etape d'annulation : de `before` (`snapshot_items`) a l'etat present des elements."""
        self.scene.push(before, self.scene.snapshot([i.item_id for i in items]), text)

    def create_copies(self, pairs) -> list:
        """Copies [(element source, champs geometriques)] : memes proprietes que la source."""
        return [self.create_entity(source.kind, geometry, source) for source, geometry in pairs]

    def create_segments(self, segments) -> list:
        """Copies [(a, b, element source)] (lignes) : memes proprietes que la source, non encore dans l'annulation."""
        return self.create_copies([(source, {"p1": [a[0], a[1]], "p2": [b[0], b[1]]}) for a, b, source in segments])

    def copy_items(self, items, delta) -> list:
        return self.create_copies([(item, cad_shapes.translated(item.kind, item.geometry(), delta)) for item in items])

    def remove_uncommitted(self, item):
        self.scene._remove(item.item_id)

    def commit_created(self, items, text: str, select: bool = False):
        ids = [i.item_id for i in items if self.scene.item(i.item_id) is not None]
        if not ids:
            return
        self.scene.push({i: None for i in ids}, self.scene.snapshot(ids), text)
        if select:
            self.scene.clearSelection()
            for item_id in ids:
                self.scene.item(item_id).setSelected(True)

    def translate(self, items, delta, text: str):
        self.scene.change_items(items, lambda item: item.data.update(
            cad_shapes.translated(item.kind, item.data, delta)), text)

    def apply_edit(self, changes, created, text: str, deleted=()) -> list:
        """Modification d'outil en UNE etape d'annulation : `changes` = [(element, champs geometriques)],
        `created` = [(type, champs geometriques, element source des proprietes ou None)]. Rend les elements crees."""
        scene = self.scene
        scene.commit_live()
        changes = [(i, g) for i, g in changes if not i.locked()]
        before = scene.snapshot([i.item_id for i, _g in changes])
        for item, geometry in changes:
            item.data = item.to_dict()
            item.data.update(copy.deepcopy(geometry))
            item.apply(item.data)
        gone = [i for i in deleted if not i.locked()]
        before.update(scene.snapshot([i.item_id for i in gone]))
        made = [self.create_entity(kind, geometry, source) for kind, geometry, source in created]
        for item in gone:                                   # supprimees dans la MEME etape d'annulation
            scene._remove(item.item_id)
        before.update({i.item_id: None for i in made})
        scene.push(before, scene.snapshot(list(before)), text)
        return made

    def set_geometry(self, changes, text: str):
        """[(element, champs geometriques)] : une etape d'annulation."""
        targets = {id(i): g for i, g in changes}
        self.scene.change_items([i for i, _g in changes], lambda item: item.data.update(
            copy.deepcopy(targets[id(item)])), text)

    def set_segments(self, segments, text: str):
        targets = {id(i): (a, b) for i, a, b in segments}

        def change(item):
            a, b = targets[id(item)]
            item.data["p1"], item.data["p2"] = [a[0], a[1]], [b[0], b[1]]
        self.scene.change_items([i for i, _a, _b in segments], change, text)

    def match_properties(self, source, targets) -> int:
        """Pipette : proprietes de `source` (telles qu'enregistrees : overrides et « ByLayer » / « selon le type »)
        recopiees sur `targets` modifiables ; une etape d'annulation. Rend le nombre d'objets modifies."""
        targets = self.editable(targets)
        if not targets:
            return 0
        values = {key: copy.deepcopy(source.data.get(key, cad_model.LINE_DEFAULTS[key])) for key in MATCHED}
        self.scene.change_items(targets, lambda item: item.data.update(copy.deepcopy(values)), "Pipette")
        return len(targets)

    def delete(self, items):
        items = self.editable(items)
        if not items:
            return
        count = len(items)
        self.scene.delete_items(items)
        self.message(f"{count} objet(s) effacé(s).")

    # -- commandes immediates --
    def open_layers(self):
        self.ui.open_layers()

    def regen(self):
        """REGEN : tout est redessine (images gardees jetees)."""
        self.scene.cad_style_changed()
        self.scene.update()
        self.view.viewport().update()
        self.message("Affichage régénéré.")

    def toggle_properties(self):
        self.ui.toggle_properties()

    def export_file(self, suffix: str):
        self.pane.export_cad(suffix=suffix)

    def open_snap_settings(self):
        self.ui.open_snap_settings()

    def undo(self):
        command = self.command
        if command is not None and not command.finished and any(
                k == "undo" for k, _l, _w in (command.prompt().options or [])):
            self.echo("U")
            command.keyword("undo")
            self._after_step()
            return
        self.pane.undo()
        self.refresh()

    def redo(self):
        self.pane.redo()
        self.refresh()

    def before_history(self):
        """Annuler / retablir du board : la commande en cours est terminee avant (rien d'incoherent)."""
        if self.command is not None:
            self.end_command()
        self.window = None
        self.lasso = None
        self._press = None

    # ------------------------------------------------------------------ saisie
    def submit(self, text: str | None = None):
        """Entree / Espace / clic droit : la saisie en cours (ou rien) est donnee a l'invite."""
        text = self.buffer if text is None else text
        self.buffer = ""
        self._recall_at = None
        stripped = text.strip()
        if stripped:
            self.recall.append(stripped)
            del self.recall[:-100]
        prompt = self.prompt()
        if prompt is None:
            if not stripped:
                if self.last_command:
                    self.run(self.last_command)
                else:
                    self.refresh()
                return
            self.run(stripped)
            return
        if prompt.kind == "text":
            self.echo(text.replace("\n", " ¶ "))
            self.command.text(text)
        elif prompt.kind == "select":
            self._submit_select(stripped, prompt)
        elif prompt.kind == "point":
            self._submit_point_text(stripped, prompt)
        else:
            self.echo(stripped)
            self.command.enter()
        self._after_step()

    def _submit_select(self, text, prompt):
        self.echo(text)
        word = text.upper()
        if not text:
            items = list(self._pick)
            self._pick = []
            self.scene.clearSelection()
            self.command.selection_done(items)
        elif any(word in [w.upper() for w in words] for _k, _l, words in prompt.options):
            key = next(k for k, _l, words in prompt.options if word in [w.upper() for w in words])
            self.command.keyword(key)
        elif word in ("TOUT", "ALL", "TO"):
            for item in self.cad_items():
                if item.isVisible() and item not in self._pick:
                    self._pick.append(item)
                    item.setSelected(True)
            self.message(f"{len(self._pick)} objet(s) choisi(s).")
        else:
            self.message(f"« {text} » : choisissez des objets (clic, fenêtre) ou TOUT ; Entrée pour terminer.",
                         error=True)

    def _dyn_fields_active(self, prompt) -> bool:
        return (bool(self.setting("board_cad_dyn")) and prompt is not None and prompt.kind == "point"
                and (self.buffer.strip() == "" or cad_input.parse_number(self.buffer) is not None))

    def _submit_point_text(self, text, prompt):
        base = prompt.base
        command = self.command
        dyn = bool(self.setting("board_cad_dyn"))
        number = cad_input.parse_number(text)
        k = self.unit()                                 # saisie dans l'unite du dessin -> unites du board
        length = number * k if number is not None else None
        if prompt.value and number is not None:
            # Invite de VALEUR (distance, rayon, angle) : le nombre tape est la valeur (longueur dans l'unite du
            # dessin, angle en degres) ; deux points cliques donnent aussi une distance.
            self.echo(text)
            command.value(length if prompt.value == "length" else number)
            return
        # Saisie dynamique : valeurs verrouillees (Tab) + champ actif.
        if dyn and (number is not None or not text) and (
                self.lock_distance is not None or self.lock_angle is not None
                or self.lock_x is not None or self.lock_y is not None):
            if base is None:
                x = self.lock_x if self.lock_x is not None else (length if self.dyn_field == 0 else None)
                y = self.lock_y if self.lock_y is not None else (length if self.dyn_field == 1 else None)
                if x is None or y is None:
                    self.message("Saisie dynamique : donnez X puis Tab, puis Y.", error=True)
                    return
                self.echo(f"{x / k:g},{y / k:g}")
                self._give_point((x, y))
                return
            dist = self.lock_distance if self.lock_distance is not None else (length if self.dyn_field == 0 else None)
            angle = self.lock_angle if self.lock_angle is not None else (number if self.dyn_field == 1 else None)
            if dist is not None and angle is not None:
                self.echo(f"@{dist / k:g}<{angle:g}")
                self._give_point(geo.polar(base, dist, angle))
                return
            if dist is not None:
                self._direct_distance(dist, base, text)
                return
            if angle is not None:
                self.lock_angle = angle % 360.0
                self.message(f"Angle imposé : {cad_input.format_angle(angle)}")
                return
        last = self.last_point if base is None else base
        result = cad_input.parse(text, None if last is None else (last[0] / k, last[1] / k),
                                 dynamic=dyn and base is not None, options=prompt.options)
        if result[0] == "point":
            result = ("point", (result[1][0] * k, result[1][1] * k))
        elif result[0] == "distance":
            result = ("distance", result[1] * k)
        kind = result[0]
        if kind == "empty":
            self.echo("")
            command.enter()
        elif kind == "keyword":
            self.echo(text)
            command.keyword(result[1])
        elif kind == "osnap":
            self.echo(text)
            self.override = result[1]
            label = cad_snap.LABELS.get(result[1], result[1])
            self.message(f"Accrochage ponctuel : {label} (point suivant).")
            return
        elif kind == "angle":
            self.echo(text)
            self.lock_angle = result[1]
            self.message(f"Angle imposé : {cad_input.format_angle(result[1])}")
            return
        elif kind == "distance":
            if base is None:
                self.echo(text)
                self.message("Point ou option attendu (une distance seule demande un point de base).", error=True)
                return
            self._direct_distance(result[1], base, text)
        elif kind == "point":
            self.echo(text)
            self._give_point(result[1])
        else:
            self.echo(text)
            self.message(result[1], error=True)

    def _direct_distance(self, dist, base, text):
        """Distance directe : dans la direction de l'angle impose, sinon de l'elastique (curseur resolu :
        ORTHO, polaire, suivi compris)."""
        if self.lock_angle is not None:
            angle = self.lock_angle
        elif self.res is not None and self.res.angle is not None and self.res.kind in ("polar", "ortho", "track", "locked"):
            angle = self.res.angle
        else:
            target = self.res.point if self.res is not None else self.cursor_doc
            if target is None or geo.distance(base, target) <= geo.EPS:
                self.echo(text)
                self.message("Direction inconnue : placez le curseur dans la direction voulue.", error=True)
                return
            angle = geo.angle_deg(base, target)
        self.echo(text)
        self._give_point(geo.polar(base, dist, angle))

    def _give_point(self, p):
        command = self.command
        if command is None:
            return
        p = (geo.clean(p[0]), geo.clean(p[1]))
        self.last_point = p
        command.point(p)
        self._reset_point_state()

    # ------------------------------------------------------------------ souris
    def _log_mouse(self, kind: str, event):
        """Une ligne par evenement : sorte, bouton, position, invite, fenetre en attente, commande (MOUSE_LOG)."""
        prompt = self.prompt()
        pos = event.position()
        _write_log(f"[cad souris] {kind} t={time.perf_counter():.3f} bouton={int(event.button().value)} "
                   f"pos=({pos.x():.0f},{pos.y():.0f}) invite={prompt.kind if prompt else '-'} "
                   f"fenetre={'oui' if self.window is not None else 'non'} "
                   f"commande={self.command.NAME if self.command is not None else '-'} "
                   f"appui={'oui' if self._press is not None else 'non'}")

    def mouse_press(self, event, log: bool = True) -> bool:
        if MOUSE_LOG and log:
            self._log_mouse("appui", event)
        pos = event.position()
        self._move_cursor(pos)
        button = event.button()
        if button == Qt.RightButton:
            if event.modifiers() & Qt.ShiftModifier:
                self.ui.osnap_menu(event.globalPosition().toPoint())
            elif self.command is not None:
                self.submit()
            else:
                self.ui.context_menu(event.globalPosition().toPoint())
            return True
        if button != Qt.LeftButton:
            return False
        prompt = self.prompt()
        if prompt is not None and prompt.kind == "text":
            raw, self.buffer = self.buffer, ""
            point = self.res.point if self.res is not None else self.view_to_doc(pos)
            self.command.click((float(point[0]), float(point[1])), raw)
            self._after_step()
            return True
        if prompt is not None and prompt.kind == "point":
            if self.res is not None:
                text = self.fmt_point(self.res.point)
                self.history.append((f"{self.prompt_line()} {text}", "echo"))
                self._give_point(self.res.point)
                self._after_step()
            return True
        if prompt is None and self.hover_grip is not None:
            self._start_grip(self.hover_grip, pos)
            return True
        self._press = (pos, self.view_to_doc(pos), event.modifiers())
        if self.window is not None:
            self._finish_window(self.view_to_doc(pos), event.modifiers())
            self._press = None
        return True

    def mouse_move(self, event) -> bool:
        self._move_cursor(event.position())
        if self.lasso is not None:
            last = self.doc_to_view(self.lasso[-1])
            if (event.position() - last).manhattanLength() >= 2:
                self.lasso.append(self.cursor_doc)
        elif self._press is not None and self.window is None:
            start_view = self._press[0]
            if (event.position() - start_view).manhattanLength() > CLICK_PX:
                prompt = self.prompt()
                if (prompt is not None and prompt.kind == "select" and self.command is not None
                        and getattr(self.command, "wants_path", lambda: False)()):
                    self.lasso = [self._press[1], self.cursor_doc]      # AJUSTER : trace a main levee
                else:
                    # Comme un clic dans le vide (demande de l'utilisateur) : la fenetre reste ouverte au
                    # relachement, seul un 2e clic la ferme — jamais de fenetre « tiree » qui se ferme en lachant.
                    self.window = {"start": self._press[1]}
                self._apply_cursor()                # carre central cache pendant la selection
        self.overlay.track()                    # seule la zone qui change est repeinte
        return True

    def mouse_release(self, event) -> bool:
        if MOUSE_LOG:
            self._log_mouse("relache", event)
        if event.button() == Qt.RightButton:
            return True
        press, self._press = self._press, None
        double, self._press_double = self._press_double, False
        grip_press = self._grip_press
        if grip_press is not None:
            self._grip_press = None
            if (event.position() - grip_press).manhattanLength() > CLICK_PX and self.command is not None \
                    and self.res is not None:
                self._give_point(self.res.point)            # poignee tiree : relachee = point
                self._after_step()
            return True
        if press is None:
            return True
        pos, doc, mods = press
        self.last_pick_doc = doc
        self.last_pick_shift = bool(mods & Qt.ShiftModifier)
        if self.lasso is not None:
            points, self.lasso = self.lasso + [self.view_to_doc(event.position())], None
            if self.command is not None and hasattr(self.command, "path_done"):
                self.command.path_done(points)
                self._after_step()
            self._apply_cursor()
            self.overlay.update()
            return True
        if (event.position() - pos).manhattanLength() <= CLICK_PX:
            prompt = self.prompt()
            shift = bool(mods & Qt.ShiftModifier)
            if double and prompt is None:
                # Vrai double-clic sur un objet : le plus proche (pas de cycle entre objets superposes), proprietes.
                item = self.pick(pos)
                if item is not None and item.kind == "cad_text" and not item.locked():
                    self._select([item], Qt.NoModifier)
                    self.run("TEXTEDIT")                     # comme AutoCAD : double-clic = modifier le texte
                elif item is not None:
                    self._select([item], Qt.NoModifier)
                    self.ui.show_properties()
                else:
                    self.window = {"start": doc}
                self.overlay.update()
                return True
            if prompt is not None and prompt.kind == "select":
                item = self.pick(pos) if shift else self.pick_next(pos, list(self._pick))
            elif mods & (Qt.ShiftModifier | Qt.ControlModifier) or self.setting("board_cad_pickadd", False):
                item = self.pick(pos)                       # bascule / ajout : toujours la plus proche
            else:
                item = self.pick_next(pos, self.selection(), cycle=True)
            if item is not None:
                self._select([item], mods)
            elif (prompt is not None and prompt.kind == "select" and self.command is not None
                  and getattr(self.command, "empty_click", lambda _d: False)(doc)):
                self._after_step()                          # AJUSTER : trajet de deux points ou capture
            else:
                self.window = {"start": doc}  # clic dans le vide : fenetre, 2e clic
            self._apply_cursor()
        self.overlay.update()
        return True

    def mouse_double_click(self, event) -> bool:
        """Deux clics rapides et proches : Qt remplace le 2e APPUI par ce double-clic. Il compte TOUJOURS comme un
        appui (cause du « un clic sur deux est ignore » : hors invite de point il etait jete, sa relache aussi —
        2e coin d'une fenetre, 2e objet choisi, 2e clic de selection perdus). Hors commande, sur un objet, la relache
        qui suit ouvre en plus ses proprietes (`_press_double`)."""
        if MOUSE_LOG:
            self._log_mouse("double", event)
        if event.button() == Qt.LeftButton:
            prompt = self.prompt()
            closes_window = self.window is not None
            handled = self.mouse_press(event, log=False)
            # Le 1er clic dans le vide a ouvert une fenetre que ce 2e clic vient de fermer : pas de double-clic.
            self._press_double = (self._press is not None and prompt is None and not closes_window)
            return handled
        return True

    def leave(self):
        self.cursor_view = None
        self.overlay.track()

    def _move_cursor(self, pos):
        self.cursor_view = QPointF(pos)
        self.cursor_doc = self.view_to_doc(pos)
        self._resolve()
        self._apply_cursor()

    def _resolve(self):
        prompt = self.prompt()
        self.hover_item = None
        self.hover_grip = None
        self.hover_snap = None
        if self.cursor_doc is None:
            self.res = None
            return
        if prompt is not None and prompt.kind == "point":
            base = prompt.base
            lock_angle, lock_dist = self.lock_angle, self.lock_distance
            self.engine.settings.grid_spacing = self.scene.grid_step()     # RESOL : le niveau de grille affiche
            origin = self.scene.grid_origin()
            self.engine.settings.grid_origin = (origin[0], -origin[1])        # document : Y vers le haut
            res = self.engine.resolve(self.cursor_doc, self.scale(), base, self.override, self.cycle,
                                      lock_angle, lock_dist)
            if base is None and (self.lock_x is not None or self.lock_y is not None):
                x = self.lock_x if self.lock_x is not None else res.point[0]
                y = self.lock_y if self.lock_y is not None else res.point[1]
                res = cad_snap.Resolution((x, y), "locked")
            key = tuple((c.mode, round(c.point[0], 6), round(c.point[1], 6)) for c in res.candidates)
            if key != self._cycle_key:
                self._cycle_key = key
                if self.cycle:
                    self.cycle = 0
                    res = self.engine.resolve(self.cursor_doc, self.scale(), base, self.override, 0,
                                              lock_angle, lock_dist)
            self.res = res
            if self.engine.note_hover(res.candidate):
                self._resolve()
                return
            if res.candidate is not None:
                self._acquire_timer.start(int(cad_snap.ACQUIRE_S * 1000) + 40)
            return
        self.res = None
        if self.window is None and self.command is None:
            self.hover_grip = self.grip_at(self.cursor_view)
            if self.hover_grip is not None and self.hover_grip[0].kind == "cad_line" and self.engine.settings.osnap:   # l'aimant : poignees de LIGNES seulement
                # Tant que la poignee est saisissable, le reticule reste aimante sur elle (demande de l'utilisateur :
                # sinon il se decrochait en entrant dans la poignee d'une ligne selectionnee, qui passe avant l'aimant).
                item, name, point = self.hover_grip
                point = tuple(point)
                spot = self.doc_to_view(point)
                gap = math.hypot(spot.x() - self.cursor_view.x(), spot.y() - self.cursor_view.y())
                mode = {"mid": "mid", "center": "cen"}.get(name, "qua" if name.startswith("q") else "end")
                candidate = cad_snap.Candidate(mode, point, gap, item)
                self.hover_snap = cad_snap.Resolution(point, "osnap", candidate, [candidate], label=candidate.label)
        if self.hover_grip is None and self.window is None:
            self.hover_item = self.pick(self.cursor_view)
            if self.command is None and self.engine.settings.osnap:
                # Hors commande aussi, le reticule s'aimante au point caracteristique approche (demande de
                # l'utilisateur) : marqueur + aimant seulement ; le clic garde la selection a la place de la souris.
                # Le 1er candidat AIMANTE (pas le 1er tout court) : a une extremite commune, le point de la ligne
                # non selectionnee passait devant (doublon retire) et l'aimant ne prenait plus que dans la zone de la
                # poignee (6 px au lieu de 10 : signale « la distance de detection est fausse sur un des 3 points »).
                found = self.engine.candidates(self.cursor_doc, self.scale(), None, keep=self._magnetic)
                candidate = next((c for c in found if self._magnetic(c)), None)
                if candidate is not None:
                    self.hover_snap = cad_snap.Resolution(candidate.point, "osnap", candidate, [candidate],
                                                          list(candidate.guides), candidate.label)

    def _acquire_tick(self):
        if self.res is not None and self.res.candidate is not None and self.engine.note_hover(self.res.candidate):
            self._resolve()
            self.overlay.update()

    def refresh(self):
        """Etat ou invite change : point resolu et apercu refaits (sans mouvement de souris)."""
        if self.cursor_view is not None and self.active:
            self._resolve()
            self._apply_cursor()
        self.overlay.update()

    def _view_changed(self, *_args):
        try:
            self.overlay.invalidate()
            if self.active and self.cursor_view is not None:
                self.cursor_doc = self.view_to_doc(self.cursor_view)
                self._resolve()
                self.overlay.update()
        except RuntimeError:
            pass                                            # panneau en cours de destruction

    def _scene_changed(self, _rects=None):
        self.overlay.invalidate()

    def _on_selection(self):
        self.overlay.invalidate()
        self.selectionChanged.emit()

    # -- selection --
    def pick_all(self, view_pos) -> list:
        """Toutes les entites sous le curseur (distance a l'axe <= boite de selection en pixels d'ecran + demi-epaisseur),
        de la plus proche a la plus eloignee ; a distance egale (lignes superposees), la plus haute dans l'empilement
        d'abord. Fiable sur les traits tres fins."""
        if view_pos is None:
            return []
        doc = self.view_to_doc(view_pos)
        reach = self.look.get("pickbox_px", 5) / self.scale()
        found = []
        for item in self._source((doc[0] - reach - 1, doc[1] - reach - 1, doc[0] + reach + 1, doc[1] + reach + 1)):
            item._reach = reach
            d = item.distance_to(doc) - float(item.props()["lineweight"]) / 2.0
            if d <= reach:
                found.append((round(d, 9), -item.zValue(), item))
        found.sort(key=lambda entry: entry[:2])
        return [entry[2] for entry in found]

    def pick(self, view_pos) -> CadLineItem | None:
        """Entite la plus proche du curseur (la plus haute si des lignes sont superposees)."""
        found = self.pick_all(view_pos)
        return found[0] if found else None

    def pick_next(self, view_pos, taken, cycle: bool = False) -> CadLineItem | None:
        """Entite a choisir par un clic. `cycle` : lignes superposees, des clics successifs au meme endroit passent de
        l'une a l'autre (celle qui suit la ligne deja selectionnee, puis on recommence). Sinon la 1re sous le curseur
        qui n'est pas dans `taken` (« Choix des objets » : chaque clic en ajoute une), a defaut la 1re."""
        found = self.pick_all(view_pos)
        if not found:
            return None
        if cycle:
            at = [i for i, item in enumerate(found) if item in taken]
            return found[(at[-1] + 1) % len(found)] if at else found[0]
        for item in found:
            if item not in taken:
                return item
        return found[0]

    @staticmethod
    def _magnetic(candidate) -> bool:
        """Hors commande, le reticule ne s'aimante que sur les POIGNEES des lignes (extremites, milieu) : ni cercle, ni arc,
        ni polyligne, ni cotation, et seulement ceux d'une ligne SELECTIONNEE (sa poignee est visible : demande de l'utilisateur) ; pendant une commande, tous les accrochages restent."""
        entity = candidate.entity
        return (getattr(entity, "kind", None) == "cad_line" and candidate.mode in ("end", "mid")
                and entity.isSelected())                       # l'aimant vise la POIGNEE : visible seulement si la ligne est selectionnee

    def grip_at(self, view_pos):
        if view_pos is None:
            return None
        half = self.look.get("grip_px", 8) / 2.0 + 2
        for item in self.selection():
            if item.locked():
                continue
            for name, point in item.grips():
                c = self.doc_to_view(point)
                if abs(c.x() - view_pos.x()) <= half and abs(c.y() - view_pos.y()) <= half:
                    return item, name, point
        return None

    def _select(self, items, mods, window: bool = False):
        """Selection (sans commande) : clic = remplace, Maj / Ctrl + clic = ajoute ou retire ; fenetre avec
        Maj / Ctrl = ajoute. Reglage « ajouter sans touche » (PICKADD d'AutoCAD) : clic = ajoute, Maj = retire.
        A l'invite « Choix des objets » : clic = ajoute, Maj + clic = retire (comme AutoCAD)."""
        prompt = self.prompt()
        shift = bool(mods & Qt.ShiftModifier)
        modifier = bool(mods & (Qt.ShiftModifier | Qt.ControlModifier))
        if prompt is not None and prompt.kind == "select" and getattr(self.command, "IMMEDIATE_PICK", False):
            self.command.picked(list(items))                # pipette, decaler, chanfrein… : le choix agit tout de suite
            self._after_step()                              # (la commande a pu se terminer)
            return
        if prompt is not None and prompt.kind == "select":
            for item in items:
                if shift and item in self._pick:
                    self._pick.remove(item)
                    item.setSelected(False)
                elif not shift and item not in self._pick:
                    self._pick.append(item)
                    item.setSelected(True)
            self.message(f"{len(self._pick)} objet(s) choisi(s).")
            self.refresh()
            return
        if self.setting("board_cad_pickadd", False):
            for item in items:
                item.setSelected(not shift)
        elif not modifier:
            self.scene.clearSelection()
            for item in items:
                item.setSelected(True)
        else:
            for item in items:
                item.setSelected(True if window else not item.isSelected())
        self.refresh()

    def _finish_window(self, end_doc, mods):
        window, self.window = self.window, None
        if window is None:
            return
        self._apply_cursor()                                # le carre central revient
        start = window["start"]
        a, b = self.doc_to_view(start), self.doc_to_view(end_doc)
        if abs(a.x() - b.x()) < 2 and abs(a.y() - b.y()) < 2:
            if self.prompt() is None and not mods & (Qt.ShiftModifier | Qt.ControlModifier):
                self.scene.clearSelection()
            self.refresh()
            return
        crossing = b.x() < a.x()                            # droite -> gauche : capture
        rect = geo.normalized_rect(start, end_doc)
        found = []
        tol = self.tess_tol()
        for item in self._source(rect):
            if item.CURVED:
                primitives = getattr(item, "select_prims", item.prims)()
                inside = (cad_shapes.touches_rect(primitives, rect, tol) if crossing
                          else cad_shapes.in_rect(primitives, rect, tol))
            else:
                p, q = item.points()
                inside = geo.segment_intersects_rect(p, q, rect) if crossing else geo.segment_in_rect(p, q, rect)
            if inside:
                found.append(item)
        if found:
            self._select(found, mods, window=True)
        elif self.prompt() is None and not mods & (Qt.ShiftModifier | Qt.ControlModifier):
            self.scene.clearSelection()
        self.refresh()

    def select_all(self):
        prompt = self.prompt()
        if prompt is not None and prompt.kind == "select":
            self._submit_select("TOUT", prompt)
            return
        self.scene.clearSelection()
        for item in self.cad_items():
            if item.isVisible():
                item.setSelected(True)
        self.refresh()

    def _start_grip(self, grip, pos):
        item, name, point = grip
        selected = [i for i in self.selection() if not i.locked()]
        grips = []
        for other in selected:                              # toutes les poignees au meme point deviennent chaudes
            for other_name, other_point in other.grips():
                if geo.distance(other_point, point) <= 1e-9 * max(1.0, abs(point[0]) + abs(point[1])):
                    grips.append((other, other_name))
        mode = "move" if cad_shapes.move_grip_names(item.kind, [name]) else "stretch"
        self.end_command()
        self.command = cad_commands.GripCommand(self, grips, point, mode)
        self.last_point = point
        self._grip_press = QPointF(pos)
        self._after_step()

    # ------------------------------------------------------------------ clavier
    CLAIMED = {Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Space,
               Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
               Qt.Key_F2, *FKEYS}

    def claims(self, event) -> bool:
        """ShortcutOverride : les touches du mode CAD ne partent pas vers les raccourcis de la fenetre."""
        mods = event.modifiers() & ~Qt.KeypadModifier
        if event.key() in self.CLAIMED and not mods & (Qt.ControlModifier | Qt.AltModifier):
            return True
        if mods & Qt.ControlModifier and event.key() in (Qt.Key_1, Qt.Key_Z, Qt.Key_Y, Qt.Key_A):
            return True
        if self.text_prompt() and mods & Qt.ControlModifier and event.key() in (
                Qt.Key_V, Qt.Key_Return, Qt.Key_Enter, Qt.Key_C, Qt.Key_X, Qt.Key_D):
            return True                                     # saisie d'un texte : coller, Ctrl+Entree
        text = event.text()
        return bool(text) and text.isprintable() and not mods & (Qt.ControlModifier | Qt.AltModifier)

    def key_press(self, event) -> bool:
        key = event.key()
        mods = event.modifiers() & ~Qt.KeypadModifier
        ctrl = bool(mods & Qt.ControlModifier)
        if self.text_prompt() and key not in FKEYS and key != Qt.Key_F2 and not (ctrl and key in (Qt.Key_Z, Qt.Key_Y)):
            return self._text_key(event, key, mods)
        if key in FKEYS and not ctrl:
            self.toggle(FKEYS[key])
            return True
        if key == Qt.Key_F2:
            self.ui.toggle_history()
            return True
        if ctrl and key == Qt.Key_1:
            self.toggle_properties()
            return True
        if ctrl and key == Qt.Key_Z and not mods & Qt.ShiftModifier:
            self.undo()
            return True
        if ctrl and (key == Qt.Key_Y or (key == Qt.Key_Z and mods & Qt.ShiftModifier)):
            self.before_history()
            self.redo()
            return True
        if ctrl and key == Qt.Key_A:
            self.select_all()
            return True
        if ctrl or mods & Qt.AltModifier:
            if ctrl and key in (Qt.Key_C, Qt.Key_X, Qt.Key_V, Qt.Key_D) and self.command is not None:
                return True                                 # pas de presse-papiers au milieu d'une commande
            return False
        if key == Qt.Key_Escape:
            self.escape()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.submit()
            return True
        if key == Qt.Key_Space:
            if event.isAutoRepeat():
                return True
            if self.buffer.strip():
                self.submit()
            else:
                self._space_pending = True
                self._space_used = False
                self.view._space = True
            return True
        if key in (Qt.Key_Tab, Qt.Key_Backtab):
            self.tab(back=key == Qt.Key_Backtab or bool(mods & Qt.ShiftModifier))
            return True
        if key == Qt.Key_Backspace:
            if self.buffer:
                self.set_buffer(self.buffer[:-1])
            return True
        if key == Qt.Key_Delete:
            if self.command is None and not self.buffer:
                self.delete(self.selection())
            return True
        if key in (Qt.Key_Up, Qt.Key_Down):
            self.recall_input(-1 if key == Qt.Key_Up else 1)
            return True
        if key in (Qt.Key_Left, Qt.Key_Right):
            return True
        text = event.text()
        if text and text.isprintable():
            self.set_buffer(self.buffer + text)
            return True
        return False

    def key_release(self, event) -> bool:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat() and self._space_pending:
            self._space_pending = False
            self.view._space = False
            used, self._space_used = self._space_used, False
            if not used and self.view._pan is None:
                self.submit()                               # Espace tape = Entree
            self._sync_cursor()
            return True
        return False

    def note_pan(self):
        self._space_used = True

    def pan_moved(self, pos, scrolled: bool):
        """Deplacement du board en cours : le reticule, l'accrochage, la saisie dynamique et les coordonnees restent
        SOUS le pointeur (demande de l'utilisateur : ils restaient figes a leur ancienne place). La vue a deja bouge
        (`scrolled`) : `_view_changed` a relu le point du document depuis cette position ; sinon (bord du board),
        simple mouvement."""
        if not self.active:
            return
        if scrolled:
            self._apply_cursor()
            return
        self._move_cursor(pos)
        self.overlay.track()

    def set_buffer(self, text: str):
        self.buffer = text
        self._recall_at = None
        if self.text_prompt():
            self.command.typed(text)
        self.refresh()
        self.stateChanged.emit()

    def text_prompt(self) -> bool:
        """Saisie d'un texte en cours (TEXTE, MTEXTE, modification) : la frappe va au texte, espaces compris."""
        prompt = self.prompt()
        return prompt is not None and prompt.kind == "text"

    def _text_key(self, event, key, mods) -> bool:
        """Touches pendant la saisie d'un texte : Entree = ligne / paragraphe (Ctrl+Entree = fin d'un texte
        multiligne), Espace = espace, Retour arriere, Ctrl+V = coller, Echap = terminer."""
        ctrl = bool(mods & Qt.ControlModifier)
        if key == Qt.Key_Escape:
            self.escape()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if getattr(self.command, "MULTILINE", False) and not ctrl:
                self.set_buffer(self.buffer + "\n")
            else:
                self.submit()
            return True
        if ctrl and key == Qt.Key_V:
            pasted = QApplication.clipboard().text().replace("\r\n", "\n").replace("\r", "\n")
            if not getattr(self.command, "MULTILINE", False):
                pasted = pasted.replace("\n", " ")
            self.set_buffer(self.buffer + pasted.replace("\t", " "))
            return True
        if key == Qt.Key_Backspace:
            if self.buffer:
                self.set_buffer(self.buffer[:-1])
            return True
        if ctrl or mods & Qt.AltModifier:
            return ctrl and key in (Qt.Key_A, Qt.Key_C, Qt.Key_X, Qt.Key_D)
        text = event.text()
        if text and text.isprintable():
            self.set_buffer(self.buffer + text)
        return True

    def escape(self):
        if self.text_prompt():
            self.buffer = ""
            self.echo("*Fin*")
            self.end_command()
            self.refresh()
            return
        if self.buffer:
            self.set_buffer("")
            return
        if self.window is not None or self.lasso is not None:
            self.window = None
            self.lasso = None
            self._apply_cursor()
            self.overlay.update()
            return
        if self.command is not None:
            self.echo("*Annuler*")
            self.end_command()
            self.refresh()
            return
        if self.lock_angle is not None or self.override is not None:
            self._reset_point_state()
            self.refresh()
            return
        if self.selection():
            self.scene.clearSelection()
            self.refresh()

    def tab(self, back: bool = False):
        prompt = self.prompt()
        text = self.buffer.strip()
        if text and any(c.isalpha() for c in text):
            matches = cad_commands.completions(text) if prompt is None else []
            if matches:
                self.set_buffer(matches[0][1].name)
            return
        if prompt is not None and prompt.kind == "point" and bool(self.setting("board_cad_dyn")) and text:
            value = cad_input.parse_number(text)
            if value is None:
                return
            length = value * self.unit()                # unite du dessin -> unites du board
            if prompt.base is None:
                if self.dyn_field == 0:
                    self.lock_x = length
                else:
                    self.lock_y = length
            elif self.dyn_field == 0:
                self.lock_distance = length
            else:
                self.lock_angle = value % 360.0
            self.dyn_field = 1 - self.dyn_field
            self.set_buffer("")
            return
        if self.res is not None and len(self.res.candidates) > 1:
            self.cycle = (self.cycle + (-1 if back else 1)) % len(self.res.candidates)
            self.refresh()
            return
        if prompt is not None and prompt.kind == "point" and bool(self.setting("board_cad_dyn")):
            self.dyn_field = 1 - self.dyn_field
            self.refresh()

    def recall_input(self, step: int):
        if not self.recall:
            return
        if self._recall_at is None:
            self._recall_at = len(self.recall)
        self._recall_at = max(0, min(len(self.recall), self._recall_at + step))
        text = self.recall[self._recall_at] if self._recall_at < len(self.recall) else ""
        keep = self._recall_at
        self.set_buffer(text)
        self._recall_at = keep

    # ------------------------------------------------------------------ rendu temporaire
    def overlay_state(self) -> dict | None:
        if not self.active:
            return None
        look = self.look
        state = {"look": look, "cursor": self.cursor_view}
        prompt = self.prompt()
        res = self.res
        point_prompt = prompt is not None and prompt.kind == "point"
        state["box_only"] = self.box_only()
        # Reticule aimante sur une poignee : son contour tient lieu de boite (la boite par-dessus, d'une autre couleur
        # et d'un pixel plus petite, brouillait le contour : signale « pas opaque sur les coins »).
        on_grip = self.hover_grip is not None and self.hover_snap is not None and look["magnet"]
        state["pickbox"] = state["box_only"] or (not point_prompt and not self.selecting_area() and not on_grip)
        if on_grip:
            ratio = self.view.viewport().devicePixelRatioF() or 1.0
            state["grip_gap"] = (max(3, round(look["grip_px"] * ratio)) | 1) // 2    # demi-cote (pixels physiques)
        state["paint_cursor"] = self.cursor_view is not None and self._cursor_plan()[1]
        state["memory"] = self.memory_color()
        highlights = []
        tol = self.tess_tol()
        if self.hover_item is not None and not self.hover_item.isSelected():
            highlights += [(seg, look["accent"]) for seg in self.hover_item.outline(tol)]
        for item in self._highlighted:
            if item.scene() is self.scene:
                highlights += [(seg, look["ghost"]) for seg in item.outline(tol)]
        state["highlights"] = highlights
        if point_prompt and res is not None and self.command is not None:
            state["preview"] = self.command.preview(res.point)
            state["ghosts"] = self.command.ghosts(res.point)
            state["guides"] = list(res.guides)
            if res.candidate is not None and look["show_markers"]:
                state["marker"] = (res.candidate.mode, res.candidate.point)
            if look["magnet"] and res.kind == "osnap" and self.cursor_view:
                state["cursor"] = self.doc_to_view(res.point)       # reticule aimante (peint, immobile)
            if res.kind == "grid" and look["show_markers"]:
                step = self.engine.settings.grid_spacing * self.scale()
                state["grid_snap"] = (res.point, step)       # croisement de grille vise (RESOL)
            tips = []
            if look["tooltips"] and res.label:
                label = res.label
                if res.candidate is not None and len(res.candidates) > 1:
                    label += f"  ({self.cycle % len(res.candidates) + 1}/{len(res.candidates)} — Tab)"
                if res.kind in ("polar", "track") and prompt.base is not None:
                    d = geo.distance(prompt.base, res.point)
                    label += f" : {self.fmt(d)} < " \
                             f"{cad_input.format_angle(geo.angle_deg(prompt.base, res.point), 1)}"
                tips.append(label)
            if self.override is not None:
                tips.append(f"Ponctuel : {cad_snap.LABELS.get(self.override, self.override)}")
            state["tooltip"] = "\n".join(tips)
            if bool(self.setting("board_cad_dyn")):
                state["dyn"] = self._dyn_state(prompt, res)
            if self.engine.settings.otrack or "ext" in self.engine.settings.modes:
                state["acquired"] = [a.point for a in self.engine.acquired]
        if prompt is not None and prompt.kind == "text" and self.command is not None:
            state["ghosts"] = self.command.ghosts(self.cursor_doc)
        if (prompt is not None and prompt.kind == "select" and self.cursor_doc is not None
                and hasattr(self.command, "hover_ghosts")):
            # Apercu au survol d'un objet a choisir (decalage, chanfrein, raccord : ce que donnera le clic).
            state["ghosts"] = self.command.hover_ghosts(self.hover_item, self.cursor_doc)
        if self.lasso is not None and self.cursor_doc is not None:
            state["path"] = self.lasso + [self.cursor_doc]
            if hasattr(self.command, "path_ghosts"):
                state["ghosts"] = self.command.path_ghosts(state["path"])
        if self.window is not None and self.cursor_doc is not None:
            start = self.window["start"]
            crossing = self.doc_to_view(self.cursor_doc).x() < self.doc_to_view(start).x()
            # Coin mobile = le point ECRAN du reticule tel quel (pas d'aller-retour document -> ecran : 64,9999 au
            # lieu de 65 tombait sur le pixel voisin du reticule, signale « le cadre est un peu a cote »).
            state["window"] = (start, self.cursor_doc, crossing, self.cursor_view)
        snap = self.hover_snap if prompt is None else None
        if snap is not None:
            if look["show_markers"]:
                state["marker"] = (snap.candidate.mode, snap.candidate.point)
            if look["magnet"] and self.cursor_view:
                state["cursor"] = self.doc_to_view(snap.point)      # reticule aimante, hors commande aussi
            if look["tooltips"] and snap.label and not self.buffer:
                state["tooltip"] = snap.label
        grips = []
        if self.hover_grip is not None:
            grips.append((self.hover_grip[2], "#18a058"))
        if isinstance(self.command, cad_commands.GripCommand):
            grips.append((self.command.base, "#e0242c"))
        state["grips"] = grips
        if prompt is None and self.buffer and look["tooltips"]:
            matches = cad_commands.completions(self.buffer)
            if matches:
                state["tooltip"] = "\n".join(f"{e.name} — {e.label}" for _w, e in matches[:5])
        return state

    def _dyn_state(self, prompt, res) -> dict:
        p = self.precision()
        k = self.unit()
        typed = self.buffer
        numeric = typed.strip() == "" or cad_input.parse_number(typed) is not None
        fields = []
        if prompt.base is None:
            values = [("X", self.lock_x, res.point[0]), ("Y", self.lock_y, res.point[1])]
        else:
            dist = geo.distance(prompt.base, res.point)
            angle = geo.angle_deg(prompt.base, res.point) if dist > geo.EPS else 0.0
            values = [("Distance", self.lock_distance, dist), ("Angle", self.lock_angle, angle)]
        for index, (label, locked, live) in enumerate(values):
            active = index == self.dyn_field
            if active and typed and numeric:
                text = typed
            elif locked is not None:
                text = cad_input.format_number(locked if label == "Angle" else locked / k, p)
            else:
                text = (cad_input.format_number(live, p) + "°") if label == "Angle" else \
                    cad_input.format_number(live / k, p)
            fields.append((label, text, active and numeric, locked is not None))
        out = {"fields": fields, "prompt": prompt.line()}
        if typed and not numeric:
            out["fields"] = [("", typed, True, False)]
        return out

    # ------------------------------------------------------------------ calques (page « cad »)
    def set_cad(self, cad: dict, text: str):
        """Nouvel etat des calques (UNE etape d'annulation ; `cad` est une copie, jamais l'original)."""
        self.scene.set_page({"cad": cad_model.copy_cad(cad)}, record=True, text=text)

    def set_cad_and_items(self, cad: dict, changes: dict, text: str):
        """Calques ET entites en une etape (suppression d'un calque : ses objets passent sur un autre)."""
        from .scene import PAGE
        self.scene.commit_live()
        ids = [i.item_id for i in changes]
        before = self.scene.snapshot([PAGE] + ids)
        self.scene.set_page({"cad": cad_model.copy_cad(cad)}, record=False)
        for item, values in changes.items():
            item.data = item.to_dict()
            item.data.update(values)
            item.apply(item.data)
        self.scene.push(before, self.scene.snapshot([PAGE] + ids), text)

    def change_entities(self, items, values: dict, text: str):
        items = self.editable(items)
        if not items:
            return

        def change(item):
            for key, value in values.items():
                item.data[key] = dict(value) if isinstance(value, dict) else value
        self.scene.change_items(items, change, text)

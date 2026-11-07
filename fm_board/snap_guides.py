"""Habillage des GUIDES D'ALIGNEMENT du magnetisme (Reglages > Module MRO > Magnetisme, une ligne par sorte ; demande
de l'utilisateur 2026-11-06 : « differencier les alignements des bords de documents de ceux des objets internes aux
documents », pour chacun : guide d'alignement affiche ou non, couleur du guide, type de ligne pris dans le module CAD
et echelle de ce type ; le toggle « Guides d'alignement » du tableau reste le MAITRE de tous les guides).

Deux sortes d'aimantation (`KINDS`) :
- « documents » : bords et centres d'un DOCUMENT — elements du board entre eux (scene du board : tableur, PDF,
  Photoshop, plan de travail d'Illustrator, page de Design...), page d'un design et ses reperes (Design), plan de
  travail (Illustrator) ;
- « inner » : OBJETS INTERNES a un document — objets d'une page de Design (et espacements egaux), objets
  d'Illustrator ; dans la scene du board, un document aligne sur un trace d'Illustrator ou un element d'une page
  (`snap_inner()` de l'element vrai).

Chaque sorte : affichee ou non (`board_snap_<sorte>_guides`, ET le maitre `board_snap_guides`), couleur, type de ligne (cle de `fm_cad.cad_model.LINETYPES`, ceux de Reglages > Module CAD > Types de
ligne), echelle (motif du type en PIXELS D'ECRAN x echelle ; reglage en dixiemes). `apply_settings` (appele par
`BoardPane.apply_settings`, chemin rapide des reglages `board_`, APRES `cad_model.set_linetypes`) ne refait les
stylos que si quelque chose a change ; `pen(kind)` rend un stylo COSMETIQUE tout fait (1 px a tout zoom, tirets
cales sur l'ecran : le trace tirete du moteur raster, rogne a l'ecran) : rien a calculer pendant un geste.
`GuideLine` = une `QLineF` qui porte sa sorte (les listes de guides restent des listes de lignes)."""
from __future__ import annotations

from PySide6.QtCore import QLineF, Qt
from PySide6.QtGui import QColor, QPen

from fm_cad import cad_model

from .settings_defaults import BOARD_DEFAULTS

DOCUMENTS, INNER, FRAME = "documents", "inner", "frame"
KINDS = (DOCUMENTS, INNER, FRAME)
# FRAME : le CADRE d'un élément redimensionné aimanté aux bords de SON document (PDF : bas d'une page, largeur du
# contenu ; `snap_document_sizes` de l'élément, `BoardScene.snap_resize` ; demande de l'utilisateur 2026-11-06).
PREFIXES = {DOCUMENTS: "board_snap_doc_", INNER: "board_snap_inner_", FRAME: "board_snap_frame_"}
SCALE_STEP = 10.0                       # echelle enregistree en dixiemes (curseur `scale` 10 : 20 = 2,0)

_STATE: dict = {}                       # sorte -> (affichee, couleur, motif du type de ligne, echelle) appliques
_PENS: dict = {}                        # sorte -> QPen cosmetique
_HIDDEN: set = set()                    # sortes dont les guides ne sont pas traces (toggle de la ligne ou maitre)


class GuideLine(QLineF):
    """Ligne de guide qui porte sa sorte d'aimantation (`kind`)."""

    def __init__(self, *args, kind: str = DOCUMENTS):
        super().__init__(*args)
        self.kind = kind


def kind_of(line) -> str:
    return getattr(line, "kind", DOCUMENTS)


def _color(value, default: str) -> str:
    if isinstance(value, str) and value.startswith("@"):            # couleur de l'appli (« @skinN2/75 ») : resolue
        try:
            from app_style import resolve_color_ref
            value = resolve_color_ref(value, default)
        except Exception:                                           # noqa: BLE001 - reference inconnue : defaut
            value = default
    return value if isinstance(value, str) and QColor(value).isValid() else default


def _scale(value, default) -> float:
    try:
        return max(0.1, float(value) / SCALE_STEP)
    except (TypeError, ValueError):
        return float(default) / SCALE_STEP


def qt_dashes(pattern, scale: float) -> list[float] | None:
    """Motif d'un type de ligne du CAD (> 0 trait, < 0 espace, 0 point ; voir `cad_geometry.dash_intervals`) en
    motif de `QPen.setDashPattern` (trait, espace, trait... en largeurs de stylo, ici des pixels) a l'echelle
    `scale` : 1 px au moins par trait (un point = 1 px) et par espace ; deux morceaux de meme sorte qui se suivent
    sont fondus ; le motif commence par un trait et compte un nombre pair de morceaux (boucle). None = continu."""
    runs: list[list] = []
    for value in pattern or ():
        on = float(value) >= 0
        length = max(1.0, abs(float(value)) * scale)
        if runs and runs[-1][0] == on:
            runs[-1][1] += length
        else:
            runs.append([on, length])
    if not any(on for on, _l in runs) or all(on for on, _l in runs):
        return None
    if not runs[0][0]:                                  # commence par un espace : il passe en fin de boucle
        runs.append(runs.pop(0))
        if runs[-1][0] == runs[-2][0]:
            runs[-2][1] += runs.pop()[1]
    if len(runs) % 2:                                   # commence et finit par un trait : ils se suivent en boucle
        runs[0][1] += runs.pop()[1]
    return [length for _on, length in runs]


def _make_pen(color: str, dashes) -> QPen:
    pen = QPen(QColor(color), 1)
    pen.setCosmetic(True)
    pen.setCapStyle(Qt.FlatCap)                         # tirets a leur longueur exacte (carre : +1 px par bout)
    if dashes:
        pen.setDashPattern(dashes)
    return pen


def apply_settings(settings: dict | None) -> bool:
    """Recopie les reglages `board_snap_doc_*` / `board_snap_inner_*` (et le maitre `board_snap_guides`) ; vrai si
    un guide a change d'aspect (y compris le motif d'un type de ligne du CAD modifie dans ses reglages)."""
    get = (settings or {}).get
    master = bool(get("board_snap_guides", BOARD_DEFAULTS["board_snap_guides"]))
    state = {}
    for kind, prefix in PREFIXES.items():
        shown = master and bool(get(prefix + "guides", BOARD_DEFAULTS[prefix + "guides"]))
        color = _color(get(prefix + "color"), BOARD_DEFAULTS[prefix + "color"])
        key = get(prefix + "linetype", BOARD_DEFAULTS[prefix + "linetype"])
        pattern = tuple((cad_model.LINETYPES.get(key) if isinstance(key, str) else None) or ("", ()))[1]
        state[kind] = (shown, color, tuple(pattern), _scale(get(prefix + "ltscale", BOARD_DEFAULTS[prefix + "ltscale"]),
                                                     BOARD_DEFAULTS[prefix + "ltscale"]))
    if state == _STATE:
        return False
    _STATE.clear()
    _STATE.update(state)
    _PENS.clear()
    _PENS.update({kind: _make_pen(color, qt_dashes(pattern, scale))
                  for kind, (_shown, color, pattern, scale) in state.items()})
    _HIDDEN.clear()
    _HIDDEN.update(kind for kind, (shown, *_rest) in state.items() if not shown)
    return True


def shown(kind: str = DOCUMENTS) -> bool:
    """Vrai si les guides de cette sorte sont traces (toggle de sa ligne et maitre « Guides d'alignement »)."""
    if not _PENS:
        apply_settings(None)
    return kind not in _HIDDEN


def pen(kind: str = DOCUMENTS) -> QPen:
    """Stylo du guide de cette sorte (le meme objet tant que les reglages ne changent pas : ne pas le modifier)."""
    found = _PENS.get(kind)
    if found is None:
        if not _PENS:
            apply_settings(None)
        found = _PENS.get(kind) or _PENS[DOCUMENTS]
    return found


def draw(painter, lines) -> None:
    """Trace des guides, chacun avec le stylo de sa sorte (un changement de stylo seulement quand la sorte change) ;
    ceux d'une sorte masquee ne sont pas traces (l'aimantation, elle, reste)."""
    if not _PENS:
        apply_settings(None)
    current = None
    for line in lines:
        kind = kind_of(line)
        if kind in _HIDDEN:
            continue
        if kind != current:
            painter.setPen(pen(kind))
            current = kind
        painter.drawLine(line)

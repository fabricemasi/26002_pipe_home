"""Bibliothèque d'icônes SVG (flat monochrome / flat couleur) et couleur dynamique des modules.

Source : la bibliothèque d'iconographie (dossier hors dépôt : `flat monochrome/`, `flat couleur/`,
`documentation/manifest_icons.json`, `documentation/modules.json`), donnée par `configure(racine)`. Rien n'est lu
avant la première icône demandée.

Couleur des modules (règle 1 du Design System) : en Flat Couleur, les emblèmes et les outils d'un module prennent la
couleur que l'appli lui donne dans ses réglages, poussée ici par `set_module_colors({module: "#RRGGBB" | None})`
(None = couleur de référence de la bibliothèque). Les SVG maîtres ne sont jamais réécrits : leurs couleurs de RÔLE
(dominante de référence du module et ses deux tons dérivés, `icon_colors.derive`) sont remplacées en mémoire, sur les
SEULS attributs `fill` / `stroke` dont la valeur est exactement une de ces couleurs (aucun remplacement de texte dans
le document). Monochrome : jamais touché. Icônes générales : jamais recolorées, sauf contexte explicite
(`contexte="cad"`) et jamais pour un accent sémantique (rouge, vert, jaune : erreur, validation, marqueur).
Moteur SVG de Qt 6.11 vérifié : `var()` CSS non interprété (noir), `currentColor` limité à UNE couleur : d'où la
substitution d'attributs.

Caches : octets et SVG recolorés par (icône, style, couleurs) ; pixmaps en LRU borné en octets. Un changement de
couleur ne purge QUE les entrées du module changé et prévient les abonnés (`on_change(f)`, `f(modules: set)`) une
fois ; un changement sans effet ne fait rien. Docs : docs/agents/fm_theme.md, « Icônes de la bibliothèque »."""
import json
import math
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

from . import icon_colors

STYLES = ("flat monochrome", "flat couleur")
MONOCHROME = STYLES[0]
COULEUR = STYLES[1]
SEMANTIQUES = ("rouge", "vert", "jaune")          # jamais recolorés (erreur, validation, marqueur)
GENERAL = "general"
BUDGET_PIXMAPS = 32 * 1024 * 1024                 # octets
_SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", _SVG_NS)

_root: Path | None = None
_manifest: dict | None = None
_index: dict = {}                 # id_logique -> entrée du manifeste
_accents: dict = {}               # module -> couleur de référence (#RRGGBB)
_couleurs: dict = {}              # module -> rôles dérivés de la couleur de l'utilisateur
_brut: dict = {}                  # chemin -> octets du SVG maître
_svg: OrderedDict = OrderedDict() # (id, style, correspondance) -> octets recolorés
_pix: OrderedDict = OrderedDict() # (module, id, style, correspondance, taille, dpr) -> QPixmap
_cadres: OrderedDict = OrderedDict()
_cadres_octets = 0
_pix_octets = 0
_listeners: list = []


def configure(root) -> None:
    """Racine de la bibliothèque ; sans effet si elle ne change pas (sinon tous les caches sont vidés)."""
    global _root, _manifest
    root = Path(root) if root else None
    if root == _root:
        return
    _root, _manifest = root, None
    _index.clear()
    _accents.clear()
    _brut.clear()
    _vider()


def _vider(modules: set | None = None) -> None:
    global _pix_octets, _cadres_octets
    for cache in (_svg, _pix):
        for key in [k for k in cache if modules is None or k[0] in modules]:
            value = cache.pop(key)
            if cache is _pix:
                _pix_octets -= value.width() * value.height() * 4
    for key in [k for k in _cadres if modules is None or k[0] in modules]:
        image = _cadres.pop(key)
        if image is not None:
            _cadres_octets -= image.width() * image.height() * 4


def _charger() -> dict:
    global _manifest
    if _manifest is None:
        if _root is None:
            raise RuntimeError("bibliothèque d'icônes non configurée (fm_theme.icon_library.configure)")
        doc = _root / "documentation"
        manifeste = json.loads((doc / "manifest_icons.json").read_text(encoding="utf-8"))
        palette = manifeste["palette"]
        modules = json.loads((doc / "modules.json").read_text(encoding="utf-8")).get("modules", {})
        index = {e["id_logique"]: e for e in manifeste["icones"]}
        _accents.update({m: palette[d["accent"]] for m, d in modules.items() if d.get("accent") in palette})
        _index.update(index)
        _manifest = manifeste
    return _manifest


def entree(id_logique: str) -> dict:
    _charger()
    return _index[id_logique]


def chemin(id_logique: str, style: str = COULEUR, propositions: bool = False) -> Path | None:
    """Fichier SVG d'une icône ; une proposition (non approuvée) seulement si `propositions`."""
    e = entree(id_logique)
    if e["disponibilite"].get(style):
        # Rangement du 13 novembre 2026 : `chemins` par style (icones/module <id>/<nom>_<nn>_m|c.svg, archives/...) ;
        # ancienne disposition <style>/<fichier> si le manifeste ne le donne pas.
        if "chemins" in e:
            return _root / e["chemins"][style]
        return _root / style / e["fichier"]
    if propositions and e.get("proposition", {}).get(style):
        return _root / e["proposition"][style]
    return None


# --- couleurs -------------------------------------------------------------------------------------------------

def set_module_colors(colors: dict) -> set:
    """Couleurs des modules ({module: couleur | None}) ; rend les modules réellement changés (purgés, notifiés)."""
    changed = set()
    for module, value in colors.items():
        hex_color = icon_colors.normaliser(value)
        roles = icon_colors.derive(hex_color) if hex_color else None
        if _couleurs.get(module) != roles:
            if roles is None:
                _couleurs.pop(module, None)
            else:
                _couleurs[module] = roles
            changed.add(module)
    if changed:
        _vider(changed)
        for listener in list(_listeners):
            try:
                listener(set(changed))
            except Exception:                         # noqa: BLE001 - un abonné ne bloque pas les autres
                pass
    return changed


class _Tous(frozenset):
    """Contient tout : abonnés prévenus pour TOUTES les icônes (style de l'interface changé)."""

    def __contains__(self, _item):
        return True


TOUS = _Tous()
_style_interface = COULEUR      # Thème > Général > « Style des icônes » (`icon_library_style`, demande 2026-11-13)
_encre = "#C4CACF"              # Thème > Général > « Couleur des icônes » (`navtool_icon_base_color`)


def set_interface_style(style, encre=None) -> bool:
    """Style des icônes du catalogue dans l'interface (flat couleur / flat monochrome) et couleur des icônes sans
    couleur propre (menus, lignes) ; vrai si l'un a changé : abonnés prévenus avec TOUS (chaque widget refait son
    image ; les rendus des deux styles restent en cache)."""
    global _style_interface, _encre
    style = MONOCHROME if style in (MONOCHROME, "monochrome") else COULEUR
    encre = encre or _encre
    if (style, encre) == (_style_interface, _encre):
        return False
    _style_interface, _encre = style, encre
    for listener in list(_listeners):
        try:
            listener(TOUS)
        except Exception:                             # noqa: BLE001 - un abonné ne bloque pas les autres
            pass
    return True


def interface_monochrome() -> bool:
    return _style_interface == MONOCHROME


def encre_defaut() -> str:
    """Teinte des icônes monochromes qui n'ont pas de couleur de glyphe propre (menus, lignes des colonnes)."""
    return _encre


def style_affiche(normal: bool = True) -> str:
    """Style d'une icône : celui de l'interface à l'état normal ; grisée ou teintée, toujours le monochrome. En
    monochrome, l'appelant donne la teinte (la couleur de son glyphe) : les SVG monochromes sont blancs."""
    return _style_interface if normal else MONOCHROME


def module_roles(module: str) -> dict:
    """Rôles affichés pour un module : ceux de sa couleur, sinon ceux de sa référence."""
    _charger()
    if module in _couleurs:
        return dict(_couleurs[module])
    ref = _accents.get(module)
    return icon_colors.derive(ref) if ref else {}


def on_change(listener) -> None:
    """`listener(modules: set)` après un changement de couleur de module (rafraîchir ses icônes)."""
    if listener not in _listeners:
        _listeners.append(listener)


def remove_listener(listener) -> None:
    if listener in _listeners:
        _listeners.remove(listener)


def _famille(reference: str, cible: dict) -> tuple:
    """Correspondance (couleur de rôle de référence -> couleur affichée), triée pour servir de clé de cache."""
    ref = icon_colors.derive(reference)
    return tuple(sorted((ref[r], cible[r]) for r in icon_colors.ROLES if ref[r] != cible[r]))


def correspondance(id_logique: str, style: str = COULEUR, contexte: str | None = None, raw: bytes | None = None) -> tuple:
    """Couleurs à remplacer pour afficher cette icône (vide = le fichier tel quel)."""
    if style != COULEUR:
        return ()
    e = entree(id_logique)
    module = e.get("module") or GENERAL
    if module != GENERAL:
        cible = _couleurs.get(module)
        ref = _accents.get(module)
        return _famille(ref, cible) if cible and ref else ()
    cible = _couleurs.get(contexte) if contexte else None
    if not cible:
        return ()
    palette = _charger()["palette"]
    accent = _accent_unique(raw, palette)
    if accent is None or any(palette.get(s) == accent for s in SEMANTIQUES):
        return ()
    return _famille(accent, cible)


def _accent_unique(raw: bytes | None, palette: dict) -> str | None:
    if raw is None:
        return None
    neutres = {palette.get("neutre"), palette.get("encre"), "#FFFFFF"}    # gris clair, encre, blanc : fixes
    used = {icon_colors.normaliser(v) for el in ET.fromstring(raw).iter() for a in ("fill", "stroke")
            if (v := el.get(a)) and v != "none"} - neutres - {None}
    return used.pop() if len(used) == 1 else None


def recolorer(raw: bytes, mapping) -> bytes:
    """SVG dont les attributs `fill` / `stroke` égaux à une clé de `mapping` prennent sa valeur ; rien d'autre."""
    table = {icon_colors.normaliser(k): v for k, v in dict(mapping).items()}
    if not table:
        return raw
    xml = ET.fromstring(raw)
    for el in xml.iter():
        for attr in ("fill", "stroke"):
            value = icon_colors.normaliser(el.get(attr))
            if value in table:
                el.set(attr, table[value])
    return ET.tostring(xml, encoding="utf-8")


# --- SVG et pixmaps -------------------------------------------------------------------------------------------

def _octets(path: Path) -> bytes:
    raw = _brut.get(path)
    if raw is None:
        raw = _brut[path] = path.read_bytes()
    return raw


def svg_bytes(id_logique: str, style: str = COULEUR, contexte: str | None = None,
              propositions: bool = False) -> bytes | None:
    path = chemin(id_logique, style, propositions)
    if path is None:
        return None
    raw = _octets(path)
    mapping = correspondance(id_logique, style, contexte, raw)
    module = entree(id_logique).get("module") or GENERAL
    return _svg_recolore(raw, module if module != GENERAL else contexte, id_logique, style, mapping)


def _svg_recolore(raw, module, id_logique, style, mapping):
    if not mapping:
        return raw
    key = (module, id_logique, style, mapping)
    out = _svg.get(key)
    if out is None:
        out = _svg[key] = recolorer(raw, mapping)
        if len(_svg) > 512:
            _svg.popitem(last=False)
    return out


def pixmap(id_logique: str, taille: int, dpr: float = 1.0, style: str = COULEUR, contexte: str | None = None,
           propositions: bool = False, *, couleur_module=None):
    """QPixmap de l'icône à `taille` px logiques (rendue à taille physique, `devicePixelRatio` posé) ; None si absente."""
    global _pix_octets
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    path = chemin(id_logique, style, propositions)
    if path is None:
        return None
    module = entree(id_logique).get("module") or GENERAL
    raw = _octets(path)
    mapping = correspondance(id_logique, style, contexte, raw)
    if couleur_module and style == COULEUR and module in _accents:
        couleur = icon_colors.normaliser(couleur_module)
        if couleur:
            mapping = () if couleur == "#FFFFFF" else _famille(_accents[module], icon_colors.derive(couleur))
    module_cache = module if module != GENERAL else contexte
    key = (module_cache, id_logique, style, mapping, int(taille), round(dpr, 3))
    pix = _pix.get(key)
    if pix is not None:
        _pix.move_to_end(key)
        return pix
    side = max(1, math.ceil(taille * dpr))
    renderer = QSvgRenderer(QByteArray(_svg_recolore(raw, module_cache, id_logique, style, mapping)))
    if not renderer.isValid():
        return None
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    pix.setDevicePixelRatio(dpr)
    _pix[key] = pix
    _pix_octets += side * side * 4
    while _pix_octets > BUDGET_PIXMAPS and len(_pix) > 1:
        _, old = _pix.popitem(last=False)
        _pix_octets -= old.width() * old.height() * 4
    return pix


def icon(id_logique: str, taille: int, dpr: float = 1.0, style: str = COULEUR, contexte: str | None = None):
    """QIcon de l'icône (pixmap Normal ; les états viennent de fm_theme) ; None si absente."""
    from PySide6.QtGui import QIcon
    pix = pixmap(id_logique, taille, dpr, style, contexte)
    return QIcon(pix) if pix is not None else None


def icone_cadree(id_logique, taille, dpr=1.0, *, style=COULEUR, teinte=None):
    from PySide6.QtGui import QIcon

    image = pixmap_cadre(id_logique, taille, dpr, style=style, teinte=teinte)
    return QIcon(image) if image is not None else QIcon()


def pixmap_cadre(id_logique, taille, dpr=1.0, *, style=COULEUR, teinte=None, couleur_module=None):
    """Rendu cadré partagé. Une bibliothèque indisponible laisse le widget dessiner son secours."""
    global _cadres_octets
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QPainter
    from . import icon_frame

    # Les identifiants du catalogue commencent par « modules/<module>/ » ou « general/ ».
    domaine, module, *_ = id_logique.split("/")
    couleur = QColor(teinte) if teinte is not None else None
    key = (module if domaine == "modules" else GENERAL, id_logique, taille, dpr, style,
           couleur.rgba() if couleur is not None else None, couleur_module, icon_frame.margin())
    if key in _cadres:
        _cadres.move_to_end(key)
        return _cadres[key]
    try:
        image = pixmap(id_logique, taille, dpr, style, couleur_module=couleur_module)
    except (OSError, KeyError, RuntimeError, ValueError, ET.ParseError):
        image = None
    if image is not None:
        image = icon_frame.frame_pixmap(image)
        if couleur is not None:
            peintre = QPainter(image)
            peintre.setCompositionMode(QPainter.CompositionMode_SourceIn)
            peintre.fillRect(QRectF(0, 0, *image.deviceIndependentSize().toTuple()), couleur)
            peintre.end()
    octets = image.width() * image.height() * 4 if image is not None else 0
    budget = BUDGET_PIXMAPS // 4
    if octets <= budget:
        _cadres[key] = image
        _cadres_octets += octets
        while len(_cadres) > 128 or _cadres_octets > budget:
            _, ancienne = _cadres.popitem(last=False)
            if ancienne is not None:
                _cadres_octets -= ancienne.width() * ancienne.height() * 4
    return image


def peindre(painter, rect, id_logique, *, style=COULEUR, teinte=None, couleur_module=None):
    """Peint une icône centrée à la densité du périphérique et indique si elle est disponible."""
    from PySide6.QtCore import QRectF

    taille = max(1, round(min(rect.width(), rect.height())))
    image = pixmap_cadre(id_logique, taille, painter.device().devicePixelRatioF(), style=style,
                         teinte=teinte, couleur_module=couleur_module)
    if image is None:
        return False
    cible = QRectF(0, 0, *image.deviceIndependentSize().toTuple())
    cible.moveCenter(rect.center())
    painter.drawPixmap(cible, image, QRectF(image.rect()))
    return True


def stats() -> dict:
    return {"svg": len(_svg), "pixmaps": len(_pix), "octets": _pix_octets, "modules": sorted(_couleurs)}

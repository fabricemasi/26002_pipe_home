"""Diagnostic d'un document (SANS Qt) : ce qui est anormal, coûteux ou perdu, en phrases lisibles. Niveaux : « erreur »
(ressource manquante…), « avertissement » (calque vide, hors cadre, très gros), « info » (taille mémoire, profil)."""
from __future__ import annotations

from . import color
from .planes import rect_intersect

BIG_PLANE_PIXELS = 50_000_000


def diagnose(doc, session=None) -> list:
    out: list[tuple[str, str]] = []
    if session is not None and session.error:
        out.append(("erreur", session.error))
    layers = list(doc.walk())
    rasters = [l for l in layers if not l.is_group()]
    out.append(("info", f"{doc.width} × {doc.height} px, {doc.dpi:g} ppp, {len(rasters)} calque(s) de pixels, "
                        f"{len(layers) - len(rasters)} groupe(s), {doc.nbytes() / 1e6:.1f} Mo de pixels."))
    out.append(("info", "Profil : " + (color.describe(doc.icc_profile) if doc.icc_profile else "aucun (sRVB supposé)")
                + " ; précision : 8 bits par canal."))
    siblings_of = {}
    for lst in _lists(doc):
        for i, layer in enumerate(lst):
            siblings_of[id(layer)] = (lst, i)
    for layer in rasters:
        if layer.pix.data is None and not layer.source:
            out.append(("avertissement", f"Le calque « {layer.name} » est vide."))
        elif layer.pix.data is not None:
            rect = layer.pix.rect()
            if rect_intersect(rect, doc.rect()) is None:
                out.append(("avertissement", f"Le calque « {layer.name} » est entièrement hors du document."))
            if layer.pix.data.shape[0] * layer.pix.data.shape[1] > BIG_PLANE_PIXELS:
                out.append(("avertissement", f"Le calque « {layer.name} » est très grand ({layer.pix.data.shape[1]} × "
                                             f"{layer.pix.data.shape[0]}) : rogner le document libère de la mémoire."))
        if layer.source and layer.pix.data is None:
            out.append(("avertissement", f"Le calque de {layer.source.get('kind')} « {layer.name} » n'a aucun rendu."))
        if layer.mask is not None and not layer.mask.enabled:
            out.append(("info", f"Le masque de « {layer.name} » est désactivé."))
    for layer in layers:
        lst, i = siblings_of.get(id(layer), (None, 0))
        if layer.clip and i == 0:
            out.append(("avertissement", f"Le calque « {layer.name} » est écrêté mais n'a aucun calque de base dessous."))
        if layer.extra.get("blend_unknown"):
            out.append(("avertissement", f"Le calque « {layer.name} » utilise le mode de fusion « "
                                         f"{layer.extra['blend_unknown']} » inconnu de cette version (rendu en normal)."))
    hidden = sum(1 for l in layers if not l.visible)
    if hidden:
        out.append(("info", f"{hidden} calque(s) masqué(s)."))
    if session is not None:
        out.append(("info", f"Historique : {len(session.history.done)} étape(s) annulable(s), "
                            f"{sum(c.nbytes() for c in session.history.done) / 1e6:.1f} Mo."))
    return out


def _lists(doc):
    yield doc.layers
    for layer in doc.walk():
        if layer.children:
            yield layer.children


def report(doc, session=None) -> str:
    return "\n".join(f"[{level}] {text}" for level, text in diagnose(doc, session))

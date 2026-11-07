"""Correction, après l'enregistrement par PDFium, des paquets XFA qu'il a réécrits (sans Qt).

PDFium réécrit TOUJOURS les paquets `datasets` et `form` d'un document XFA qu'il enregistre
(`SaveXFADocumentData`), avec le défaut décrit dans `xfa_packets.py`. On compare chaque paquet du fichier produit à
celui du fichier OUVERT (`original_packets`) : différent = réécrit par PDFium = réparé, puis remplacé par une mise à
jour incrémentale (`incremental.replace_streams`, octets précédents intacts). Identique = laissé tel quel.
"""
from __future__ import annotations

import io

from . import incremental
from . import xfa_packets

REPAIRED = ("datasets", "form")


def packet_streams(data: bytes) -> dict[str, tuple[tuple[int, int], bytes]]:
    """{nom: ((num, gen), contenu décodé)} des paquets XFA rangés en tableau dans /AcroForm /XFA."""
    import pikepdf

    out = {}
    with pikepdf.open(io.BytesIO(data)) as pdf:
        acro = pdf.Root.get("/AcroForm")
        xfa = acro.get("/XFA") if acro is not None else None
        if not isinstance(xfa, pikepdf.Array):
            return out
        items = list(xfa)
        for i in range(0, len(items) - 1, 2):
            name, stream = items[i], items[i + 1]
            if isinstance(name, pikepdf.String) and isinstance(stream, pikepdf.Stream):
                out[str(name)] = (stream.objgen, stream.read_bytes())
    return out


def repair(saved: bytes, original_packets: dict[str, bytes]) -> tuple[bytes, list[str]]:
    """(octets corrigés, noms des paquets réparés). `original_packets` : {nom: contenu} du fichier ouvert."""
    found = packet_streams(saved)
    replacements = {}
    names = []
    for name in REPAIRED:
        if name not in found:
            continue
        objgen, content = found[name]
        if content == original_packets.get(name):
            continue                                     # pas réécrit par PDFium
        fixed = xfa_packets.undo_pdfium_newlines(content)
        if fixed != content:
            replacements[objgen] = fixed
            names.append(name)
    if not replacements:
        return saved, []
    return incremental.replace_streams(saved, replacements), names

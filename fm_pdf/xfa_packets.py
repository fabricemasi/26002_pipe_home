"""Paquets XFA (sans Qt) : lecture et RÉPARATION de ce que PDFium écrit à l'enregistrement.

DÉFAUT DE PDFium (chromium/8076, vérifié dans ses sources) : ses deux écrivains XML ajoutent un saut de ligne après
chaque balise, y compris À L'INTÉRIEUR des valeurs :
- `CFX_XMLElement::Save` (paquet `datasets`, texte riche) : « <nom attrs>\\n », « <nom attrs />\\n », « </nom>\\n » ;
  rien après « ]]> » (CDATA) ; « <?xml …?>\\n » ;
- `RegenerateFormFile_Changed` (paquet `form`, xfa_utils.cpp) : « <nom attrs>\\n » + enfants + « </nom>\\n »,
  « <nom attrs/>\\n », SAUF le cas des listes en texte/XML : « <Corps xmlns="">\\n » puis « <value>texte</value>\\n »
  (aucun saut de ligne après « <value> »).
Rouvert tel quel, chaque valeur commence par « \\n » : listes affichant leur valeur brute (« 01 » au lieu de
« English »), dates rejetées par leur motif, légendes décalées d'une ligne (mesuré sur l'IMM 1344 d'IRCC).

`undo_pdfium_newlines` est l'INVERSE EXACT de ces règles : il retire un seul « \\n » après chaque balise que PDFium
a terminée par « \\n ». Un « > » ne peut apparaître hors balise que dans un CDATA (PDFium échappe « > » partout
ailleurs : `EncodeEntities`, `ExportEncodeContent`, `ExportEncodeAttribute`). Les espaces d'origine (indentation des
listes de valeurs, par ex.) sont des nœuds texte écrits APRÈS ce « \\n » : ils sont gardés.
"""
from __future__ import annotations

import re

# Balise, commentaire, instruction ou CDATA (le CDATA est sauté en entier : il peut contenir « > »).
_MARKUP = re.compile(rb"<!\[CDATA\[.*?\]\]>|<!--.*?-->|<\?.*?\?>|<[^>]*>", re.S)
_EMPTY_NS = re.compile(rb"""\sxmlns\s*=\s*(""|'')""")


def undo_pdfium_newlines(xml: bytes) -> bytes:
    """Retire le « \\n » que PDFium ajoute après chaque balise (voir l'en-tête du module)."""
    out = bytearray()
    pos = 0
    n = len(xml)
    stack: list[tuple[bytes, bool]] = []          # (nom, corps de liste texte/XML : xmlns="")
    for m in _MARKUP.finditer(xml):
        out += xml[pos:m.start()]
        tok = m.group(0)
        out += tok
        end = m.end()
        strip = True
        if tok.startswith(b"<![CDATA["):
            strip = False
        elif tok.startswith(b"</"):
            if stack:
                stack.pop()
        elif tok.startswith((b"<?", b"<!--")):
            pass
        else:
            name = re.match(rb"<\s*([^\s/>]+)", tok)
            name = name.group(1) if name else b""
            self_closing = tok.endswith(b"/>")
            in_list_body = bool(stack) and stack[-1][1]
            if name == b"value" and in_list_body and not self_closing:
                strip = False                         # « <value>texte</value> » : rien après « <value> »
            if not self_closing:
                stack.append((name, bool(_EMPTY_NS.search(tok))))
        if strip and end < n and xml[end:end + 1] == b"\n":
            end += 1
        pos = end
    out += xml[pos:]
    return bytes(out)


def looks_pdfium_written(xml: bytes) -> bool:
    """Vrai si le paquet porte la signature de l'écrivain de PDFium (une balise suivie de « \\n » puis d'un
    texte non blanc dans une valeur : « <text>\\nabc » ou « <Nom>\\nabc</Nom> »)."""
    return re.search(rb"<[A-Za-z_][^<>/]*>\n[^\s<]", xml) is not None


def canonical(xml: bytes):
    """Arbre comparable (balise, attributs triés, texte, enfants) : pour les tests et le diagnostic."""
    import xml.etree.ElementTree as ET

    def walk(e):
        return (e.tag, tuple(sorted(e.attrib.items())), e.text or "", tuple(walk(k) for k in e), e.tail or "")
    return walk(ET.fromstring(xml))

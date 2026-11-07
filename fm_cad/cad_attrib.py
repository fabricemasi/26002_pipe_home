"""ATTRIBUTS de bloc du CAD (ATTDEF / ATTEDIT, comme AutoCAD) : logique PURE (aucun Qt).

- Definition d'attribut : un texte (`cad_text`) dont le champ `attdef` = {"tag" (etiquette, en capitales), "prompt"
  (question posee a l'insertion), "default" (valeur par defaut), "invisible", "constant" (valeur fixe, jamais
  demandee)}. Hors d'un bloc il affiche son etiquette (comme AutoCAD) ; dans un bloc il affiche la VALEUR de la
  reference.
- Valeurs : champ `attribs` de la reference (`cad_insert`) = {etiquette: valeur} ; etiquette absente = valeur par
  defaut ; valeur vide = rien d'affiche.
"""
from __future__ import annotations

MAX_TAG = 255
FORBIDDEN = " !\"'<>/\\:;?*|,=`"                 # pas d'espace ni de ces caracteres dans une etiquette (AutoCAD)


def clean_tag(tag) -> str:
    text = str(tag or "").strip().upper()
    for ch in FORBIDDEN:
        text = text.replace(ch, "_" if ch == " " else "")
    return text[:MAX_TAG]


def clean_attdef(value) -> dict:
    """Champ `attdef` valide ({} = texte ordinaire)."""
    if not isinstance(value, dict):
        return {}
    tag = clean_tag(value.get("tag"))
    if not tag:
        return {}
    return {"tag": tag, "prompt": str(value.get("prompt") or tag), "default": str(value.get("default") or ""),
            "invisible": bool(value.get("invisible", False)), "constant": bool(value.get("constant", False))}


def clean_attribs(value) -> dict:
    """Champ `attribs` valide d'une reference : {etiquette: valeur} (chaines)."""
    if not isinstance(value, dict):
        return {}
    out = {}
    for tag, text in value.items():
        tag = clean_tag(tag)
        if tag:
            out[tag] = "" if text is None else str(text)
    return out


def is_attdef(entity: dict) -> bool:
    return entity.get("type", "cad_text") == "cad_text" and bool(clean_attdef(entity.get("attdef")))


def attdefs(definition: dict | None) -> list:
    """Definitions d'attributs (champs `attdef` nettoyes) d'un bloc, dans l'ordre du bloc, sans doublon d'etiquette."""
    out, seen = [], set()
    for entity in (definition or {}).get("items") or []:
        if entity.get("type") != "cad_text":
            continue
        found = clean_attdef(entity.get("attdef"))
        if found and found["tag"] not in seen:
            seen.add(found["tag"])
            out.append(found)
    return out


def asked(definition: dict | None) -> list:
    """Attributs a demander a l'insertion (non constants)."""
    return [a for a in attdefs(definition) if not a["constant"]]


def value_of(attdef: dict, insert: dict) -> str:
    """Valeur affichee d'un attribut par la reference `insert` (constante : toujours la valeur par defaut)."""
    found = clean_attdef(attdef)
    if not found:
        return ""
    if found["constant"]:
        return found["default"]
    values = clean_attribs(insert.get("attribs"))
    return values.get(found["tag"], found["default"])


def shown(entity: dict, insert: dict) -> dict | None:
    """Texte d'une definition d'attribut tel que la reference le montre (None = invisible ou vide)."""
    found = clean_attdef(entity.get("attdef"))
    if found["invisible"]:
        return None
    text = value_of(found, insert)
    if not text.strip():
        return None
    out = dict(entity)
    out["text"] = text
    return out


def values_for(definition: dict | None, given: dict) -> dict:
    """Valeurs d'une reference neuve : celles donnees, sinon les valeurs par defaut (constantes exclues)."""
    given = clean_attribs(given)
    return {a["tag"]: given.get(a["tag"], a["default"]) for a in asked(definition)}

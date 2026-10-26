"""Echanges avec Miro SANS reseau : lire / ecrire les donnees au format de l'API REST v2 de Miro (JSON).

Ce que Miro permet reellement (etude d'octobre 2026, sources dans AGENTS.md) :
- sauvegarde `.rtb` : format PROPRIETAIRE non documente, relu seulement par Miro (proprietaires de boards
  d'equipes payantes) : ni lu ni ecrit ici, faute de specification et de fichier d'essai ;
- exports PNG / PDF / CSV de Miro : rendus aplatis (ou textes seuls), pas des objets editables ;
- API REST v2 (`GET /v2/boards/{id}/items`, jeton OAuth `boards:read`, reseau) : post-it, formes, textes,
  images (par URL), cadres, cartes, documents, integrations, connecteurs (`/connectors`) ; PAS les dessins a
  main levee, ni les commentaires.

`import_api_json` lit un fichier JSON enregistre depuis cette API (reponse(s) de `/items` et `/connectors`,
une liste d'objets, ou `{"data": [...]}`), sans rien telecharger : les images y sont des URL, elles deviennent
des emplacements « image introuvable » (URL gardee dans `source_url`). `export_api_json` ecrit l'inverse : les
corps des requetes de creation de l'API pour chaque element (a envoyer par un outil separe, non fourni). Les deux
rendent un COMPTE RENDU : conserve / transforme / ignore."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from . import model

STICKY_NAMES = {"gray": "#f5f6f8", "light_yellow": "#fff9b1", "yellow": "#f5d128", "orange": "#ff9d48",
                "light_green": "#d5f692", "green": "#c9df56", "dark_green": "#93d275", "cyan": "#67c6c0",
                "light_pink": "#ffcee0", "pink": "#ea94bb", "violet": "#c6a2d2", "red": "#f0939d",
                "light_blue": "#a6ccf5", "blue": "#6cd8fa", "dark_blue": "#9ea9ff", "black": "#000000"}
SHAPES_FROM_MIRO = {"rectangle": "rect", "square": "rect", "round_rectangle": "round", "circle": "ellipse",
                    "triangle": "triangle", "rhombus": "diamond", "parallelogram": "parallelogram",
                    "trapezoid": "trapezoid", "pentagon": "pentagon", "hexagon": "hexagon", "octagon": "octagon",
                    "wedge_round_rectangle_callout": "callout", "star": "star",
                    "flow_chart_predefined_process": "predefined_process", "cloud": "cloud", "cross": "cross",
                    "can": "can", "right_arrow": "right_arrow", "left_arrow": "left_arrow",
                    "left_right_arrow": "left_right_arrow", "left_brace": "left_brace",
                    "right_brace": "right_brace"}
SHAPES_TO_MIRO = {v: k for k, v in SHAPES_FROM_MIRO.items() if k != "square"}
CONNECTOR_SHAPES = {"straight": "straight", "elbowed": "elbow", "curved": "curved"}
STROKE_STYLES = {"normal": "solid", "dashed": "dashed", "dotted": "dotted"}
ALIGN_V = {"top": "top", "middle": "middle", "bottom": "bottom"}
# Pointes (noms de l'API Miro : startStrokeCap / endStrokeCap ; non teste contre l'API reelle).
CAPS_FROM_MIRO = {"none": "none", "stealth": "filled", "arrow": "open", "filled_triangle": "filled",
                  "triangle": "filled", "filled_oval": "circle", "oval": "circle_open", "filled_diamond": "diamond",
                  "diamond": "diamond_open", "rounded_stealth": "filled", "erd_one": "open", "erd_many": "open"}
CAPS_TO_MIRO = {"none": "none", "open": "arrow", "filled": "stealth", "circle": "filled_oval",
                "circle_open": "oval", "diamond": "filled_diamond", "diamond_open": "diamond"}


def html_to_text(content) -> str:
    if not isinstance(content, str):
        return ""
    text = re.sub(r"<br\s*/?>", "\n", content, flags=re.I)
    text = re.sub(r"</p\s*>\s*<p[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def text_to_html(text: str) -> str:
    return "".join(f"<p>{html.escape(line)}</p>" for line in (text or "").split("\n")) or "<p></p>"


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _color(value, default: str) -> str:
    if isinstance(value, str) and re.match(r"^#[0-9a-fA-F]{6}$", value):
        return value.lower()
    if isinstance(value, str) and value in STICKY_NAMES:
        return STICKY_NAMES[value]
    return default


def _collect(raw) -> list[dict]:
    """Objets de l'API dans un JSON : liste, `{"data": [...]}`, plusieurs pages, ou `{"items":..., "connectors":...}`."""
    out = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and ("data" in entry and isinstance(entry["data"], list)):
                out += _collect(entry)
            elif isinstance(entry, dict):
                out.append(entry)
    elif isinstance(raw, dict):
        for key in ("data", "items", "connectors"):
            if isinstance(raw.get(key), list):
                out += _collect(raw[key])
        if not out and "type" in raw:
            out.append(raw)
    return out


def import_api_json(path) -> tuple[list[dict], dict]:
    """Elements `.mro` + compte rendu {"kept": {type: n}, "changed": [textes], "ignored": {type: n}}."""
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    objects = _collect(raw)
    report = {"kept": {}, "changed": [], "ignored": {}}
    by_id = {str(o.get("id")): o for o in objects if o.get("id") is not None}
    ids = {key: model.new_id() for key in by_id}
    items = []

    def count(bucket, kind):
        report[bucket][kind] = report[bucket].get(kind, 0) + 1

    def top_left(obj):
        geometry = obj.get("geometry") or {}
        position = obj.get("position") or {}
        w, h = _num(geometry.get("width"), 200.0), _num(geometry.get("height"), 0.0)
        x, y = _num(position.get("x")), _num(position.get("y"))
        parent = obj.get("parent") or {}
        if position.get("relativeTo") == "parent_top_left" and str(parent.get("id")) in by_id:
            frame = by_id[str(parent.get("id"))]
            fx, fy, _fw, _fh = top_left(frame)
            x, y = x + fx, y + fy
        if position.get("origin", "center") == "center":
            x, y = x - w / 2, y - (h or w) / 2
        return x, y, w, h

    for obj in objects:
        kind = obj.get("type")
        data = obj.get("data") or {}
        style = obj.get("style") or {}
        if kind == "connector" or ("startItem" in obj and "endItem" in obj):
            continue
        x, y, w, h = top_left(obj)
        rotation = _num((obj.get("geometry") or {}).get("rotation"))
        new_id = ids.get(str(obj.get("id")), model.new_id())
        if kind == "sticky_note":
            item = model.new_item("sticky", id=new_id, x=x, y=y, w=w, h=h or w,
                                  text=html_to_text(data.get("content")),
                                  color=_color(style.get("fillColor"), model.MIRO_STICKY),
                                  align=style.get("textAlign", "center") if style.get("textAlign") in
                                  ("left", "center", "right") else "center",
                                  valign=ALIGN_V.get(style.get("textAlignVertical"), "middle"))
            if rotation:
                report["changed"].append("rotation d'un post-it ignorée")
        elif kind == "shape":
            shape = SHAPES_FROM_MIRO.get(data.get("shape"))
            if shape is None:
                report["changed"].append(f"forme « {data.get('shape')} » remplacée par un rectangle")
                shape = "rect"
            item = model.new_item(
                "shape", id=new_id, x=x, y=y, w=w, h=h or w, rotation=rotation, shape=shape,
                text=html_to_text(data.get("content")), fill=_color(style.get("fillColor"), "#ffffff"),
                fill_opacity=_num(style.get("fillOpacity"), 1.0 if style.get("fillColor") else 0.0),
                stroke=_color(style.get("borderColor"), model.MIRO_INK),
                stroke_width=_num(style.get("borderWidth"), 2.0),
                stroke_opacity=_num(style.get("borderOpacity"), 1.0),
                stroke_style=STROKE_STYLES.get(style.get("borderStyle"), "solid"),
                text_color=_color(style.get("color"), model.MIRO_INK),
                font_size=int(_num(style.get("fontSize"), 14)),
                align=style.get("textAlign") if style.get("textAlign") in ("left", "center", "right") else "center",
                valign=ALIGN_V.get(style.get("textAlignVertical"), "middle"))
            if shape == "round":
                item["radius"] = round(min(item["w"], item["h"]) * 0.18, 2)
            if style.get("fontFamily"):
                report["changed"].append(f"police « {style.get('fontFamily')} » : la plus proche installée")
                item["font_family"] = str(style["fontFamily"]).replace("_", " ").title()
        elif kind == "text":
            item = model.new_item("text", id=new_id, x=x, y=y, w=w, rotation=rotation,
                                  text=html_to_text(data.get("content")),
                                  text_color=_color(style.get("color"), model.MIRO_INK),
                                  font_size=int(_num(style.get("fontSize"), 24)),
                                  align=style.get("textAlign") if style.get("textAlign") in
                                  ("left", "center", "right") else "left")
        elif kind == "frame":
            item = model.new_item("frame", id=new_id, x=x, y=y, w=w, h=h or w, title=str(data.get("title") or ""),
                                  fill=_color(style.get("fillColor"), "#ffffff"))
        elif kind == "image":
            item = model.new_item("image", id=new_id, x=x, y=y, w=w, h=h or w, asset="",
                                  source_url=str(data.get("imageUrl") or ""))
            report["changed"].append("image : URL gardée, non téléchargée (aucun accès réseau)")
        elif kind in ("card", "app_card", "document", "embed"):
            title = html_to_text(data.get("title") or data.get("description") or kind)
            item = model.new_item("shape", id=new_id, x=x, y=y, w=w, h=h or 120.0, shape="round",
                                  radius=12.0, fill="#ffffff", fill_opacity=1.0, text=title,
                                  link=str(data.get("url") or data.get("documentUrl") or ""))
            report["changed"].append(f"{kind} converti en forme avec texte")
        else:
            count("ignored", str(kind))
            continue
        if kind != "frame":
            item["miro_id"] = str(obj.get("id"))
        items.append(item)
        count("kept", str(kind))

    for obj in objects:
        if not (obj.get("type") == "connector" or ("startItem" in obj and "endItem" in obj)):
            continue
        start = ids.get(str((obj.get("startItem") or {}).get("id")))
        end = ids.get(str((obj.get("endItem") or {}).get("id")))
        if start is None or end is None:
            count("ignored", "connector (extrémité absente)")
            continue
        style = obj.get("style") or {}
        caps = (style.get("startStrokeCap"), style.get("endStrokeCap"))
        items.append(model.new_item(
            "connector", src={"item": start}, dst={"item": end},
            style=CONNECTOR_SHAPES.get(obj.get("shape"), "straight"),
            color=_color(style.get("strokeColor"), model.MIRO_INK), width=_num(style.get("strokeWidth"), 2.0),
            stroke_style=STROKE_STYLES.get(style.get("strokeStyle"), "solid"),
            start_cap=CAPS_FROM_MIRO.get(caps[0] or "none", "filled"),
            end_cap=CAPS_FROM_MIRO.get(caps[1] or "stealth", "filled"),
            arrow_start=caps[0] not in (None, "none"), arrow_end=caps[1] not in ("none",)))
        count("kept", "connector")
        if obj.get("captions"):
            report["changed"].append("légende de connecteur ignorée")
    return items, report


def _nearest_sticky_name(color: str) -> str:
    target = color.lstrip("#")
    try:
        r, g, b = int(target[0:2], 16), int(target[2:4], 16), int(target[4:6], 16)
    except (ValueError, IndexError):
        return "light_yellow"

    def dist(hexval):
        h = hexval.lstrip("#")
        return (int(h[0:2], 16) - r) ** 2 + (int(h[2:4], 16) - g) ** 2 + (int(h[4:6], 16) - b) ** 2
    return min(STICKY_NAMES, key=lambda name: dist(STICKY_NAMES[name]))


def export_api_json(board_data: dict) -> tuple[dict, dict]:
    """Corps des requetes de creation de l'API REST v2 de Miro pour chaque element (position au centre,
    relative au centre du canvas) + compte rendu. Les connecteurs referencent les `local_id` des elements :
    l'outil qui envoie les requetes doit les remplacer par les identifiants que Miro rend."""
    report = {"kept": {}, "changed": [], "ignored": {}}
    requests = []

    def count(bucket, kind):
        report[bucket][kind] = report[bucket].get(kind, 0) + 1

    for item in board_data.get("items", []):
        kind = item.get("type")
        w, h = float(item.get("w", 0.0)), float(item.get("h", 0.0))
        position = {"x": round(float(item.get("x", 0.0)) + w / 2, 2), "y": round(float(item.get("y", 0.0)) + h / 2, 2),
                    "origin": "center"}
        geometry = {"width": round(w, 2)}
        if kind == "sticky":
            name = _nearest_sticky_name(item.get("color", model.MIRO_STICKY))
            if STICKY_NAMES[name] != str(item.get("color", "")).lower():
                report["changed"].append(f"couleur de post-it {item.get('color')} -> {name} (palette Miro)")
            body = {"data": {"content": text_to_html(item.get("text", "")), "shape": "square"},
                    "style": {"fillColor": name, "textAlign": item.get("align", "center"),
                              "textAlignVertical": item.get("valign", "middle")},
                    "position": position, "geometry": geometry}
            endpoint = "sticky_notes"
        elif kind == "shape":
            body = {"data": {"content": text_to_html(item.get("text", "")),
                             "shape": SHAPES_TO_MIRO.get(item.get("shape"), "rectangle")},
                    "style": {"fillColor": item.get("fill", "#ffffff"),
                              "fillOpacity": str(item.get("fill_opacity", 0.0)),
                              "borderColor": item.get("stroke", model.MIRO_INK),
                              "borderWidth": str(item.get("stroke_width", 2.0)),
                              "borderOpacity": str(item.get("stroke_opacity", 1.0)),
                              "borderStyle": {"solid": "normal"}.get(item.get("stroke_style"), item.get("stroke_style")),
                              "color": item.get("text_color", model.MIRO_INK),
                              "fontSize": str(item.get("font_size", 14)),
                              "textAlign": item.get("align", "center"),
                              "textAlignVertical": item.get("valign", "middle")},
                    "position": position, "geometry": dict(geometry, height=round(h, 2),
                                                           rotation=item.get("rotation", 0.0))}
            if item.get("shape") in ("rect", "round") and item.get("radius"):
                report["changed"].append("arrondi des angles réglé : non transmis (absent de l'API)")
            endpoint = "shapes"
        elif kind == "text":
            body = {"data": {"content": text_to_html(item.get("text", ""))},
                    "style": {"color": item.get("text_color", model.MIRO_INK), "fontSize": str(item.get("font_size", 24)),
                              "textAlign": item.get("align", "left")},
                    "position": position, "geometry": dict(geometry, rotation=item.get("rotation", 0.0))}
            endpoint = "texts"
        elif kind == "frame":
            body = {"data": {"title": item.get("title", ""), "format": "custom", "type": "freeform"},
                    "style": {"fillColor": item.get("fill", "#ffffff")},
                    "position": position, "geometry": dict(geometry, height=round(h, 2))}
            endpoint = "frames"
        elif kind == "connector":
            src, dst = item.get("src") or {}, item.get("dst") or {}
            if not (src.get("item") and dst.get("item")):
                count("ignored", "connector libre (l'API exige deux éléments)")
                continue
            body = {"startItem": {"id": src["item"]}, "endItem": {"id": dst["item"]},
                    "shape": {"elbow": "elbowed"}.get(item.get("style"), item.get("style", "straight")),
                    "style": {"strokeColor": item.get("color", model.MIRO_INK), "strokeWidth": str(item.get("width", 2.0)),
                              "strokeStyle": {"solid": "normal"}.get(item.get("stroke_style"), item.get("stroke_style")),
                              "startStrokeCap": CAPS_TO_MIRO.get(item.get("start_cap") or
                                                                 ("filled" if item.get("arrow_start") else "none")),
                              "endStrokeCap": CAPS_TO_MIRO.get(item.get("end_cap") or
                                                               ("filled" if item.get("arrow_end", True) else "none"))}}
            endpoint = "connectors"
        else:
            count("ignored", {"ink": "dessin à main levée (absent de l'API)", "comment": "commentaire (absent de l'API)",
                              "image": "image (envoi de fichier non géré)",
                              "cad_line": "ligne CAD (absente de l'API)"}.get(kind, str(kind)))
            continue
        requests.append({"endpoint": f"/v2/boards/{{board_id}}/{endpoint}", "local_id": item.get("id"), "body": body})
        count("kept", kind)
    return {"format": "miro-api-v2-requests", "requests": requests}, report


def describe(report: dict) -> str:
    """Compte rendu lisible (francais)."""
    lines = []
    if report["kept"]:
        lines.append("Conservés : " + ", ".join(f"{n} {k}" for k, n in sorted(report["kept"].items())))
    if report["changed"]:
        seen = []
        for text in report["changed"]:
            if text not in seen:
                seen.append(text)
        lines.append("Transformés : " + " ; ".join(f"{t} (×{report['changed'].count(t)})" for t in seen))
    if report["ignored"]:
        lines.append("Ignorés : " + ", ".join(f"{n} {k}" for k, n in sorted(report["ignored"].items())))
    return "\n".join(lines) or "Rien à importer."

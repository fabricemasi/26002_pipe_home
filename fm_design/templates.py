"""Modèles de conception LOCAUX (créés pour PIPE FMZ, aucune ressource de Canva) : chaque modèle = format de page,
fond et éléments (coordonnées de page). Appliqué sur une page vide (redimensionnée) ou sur une nouvelle page.
Polices : celles de Windows (une police absente est remplacée à l'affichage, gardée dans le fichier)."""
from __future__ import annotations

from . import design_model as dm


def _text(x, y, w, text, size, **style):
    return {"type": dm.TEXT, "x": x, "y": y, "w": w, "h": size * 1.3, "text": text, "font_size": float(size),
            **style}


def _shape(x, y, w, h, shape="rect", **style):
    return {"type": dm.SHAPE, "x": x, "y": y, "w": w, "h": h, "shape": shape, **style}


def _shadow(blur=24.0, dy=10.0, alpha="66"):
    return {"enabled": True, "color": f"#{alpha}000000", "dx": 0.0, "dy": dy, "blur": blur}


TEMPLATES = [
    {"key": "event", "name": "Annonce d'événement", "w": 1080, "h": 1080,
     "page": {"bg_type": "linear", "background": "#5e17eb", "bg2": "#ff66c4", "bg_angle": 120.0},
     "items": [
         _shape(720, -140, 520, 520, "ellipse", fill="#ffffff", opacity=0.12),
         _shape(-160, 760, 460, 460, "ellipse", fill="#ffde59", opacity=0.9),
         _text(90, 120, 900, "SOIRÉE", 150, font_family="Arial Black", color="#ffffff", bold=True,
               letter_spacing=40.0, line_height=1.0),
         _text(90, 360, 900, "Portes ouvertes du studio", 64, font_family="Segoe UI", color="#ffffff"),
         _shape(90, 490, 220, 8, fill="#ffde59"),
         _text(90, 540, 900, "Vendredi 14 novembre · 19 h", 44, font_family="Segoe UI", color="#ffffff",
               bold=True),
         _text(90, 620, 800, "Projections, démonstrations et rencontres avec l'équipe.", 34,
               font_family="Segoe UI", color="#f3e8ff", line_height=1.35),
     ]},
    {"key": "quote", "name": "Citation", "w": 1080, "h": 1080,
     "page": {"background": "#111111"},
     "items": [
         _text(120, 120, 300, "“", 320, font_family="Georgia", color="#ffbd59", bold=True),
         _text(120, 380, 840, "Le détail fait la perfection, et la perfection n'est pas un détail.", 64,
               font_family="Georgia", color="#ffffff", italic=True, line_height=1.25),
         _shape(120, 760, 120, 6, fill="#ffbd59"),
         _text(120, 800, 840, "Proverbe d'atelier", 36, font_family="Segoe UI", color="#bfbfbf",
               uppercase=True, letter_spacing=120.0),
     ]},
    {"key": "slide", "name": "Présentation — titre", "w": 1920, "h": 1080,
     "page": {"background": "#f7f5f2"},
     "items": [
         _shape(0, 0, 720, 1080, fill_type="linear", fill="#004aad", fill2="#5ce1e6", gradient_angle=60.0),
         _shape(560, 380, 320, 320, "ellipse", fill="#ffde59", shadow=_shadow()),
         _text(980, 330, 840, "Revue de projet", 110, font_family="Segoe UI", color="#1a1a1a", bold=True),
         _text(980, 500, 840, "Point d'étape · équipe production", 46, font_family="Segoe UI", color="#545454"),
         _shape(980, 600, 160, 10, fill="#004aad"),
         _text(980, 900, 840, "Octobre 2026", 32, font_family="Segoe UI", color="#737373"),
     ]},
    {"key": "story", "name": "Story promotionnelle", "w": 1080, "h": 1920,
     "page": {"bg_type": "radial", "background": "#ff914d", "bg2": "#ff3131"},
     "items": [
         _text(90, 260, 900, "-30 %", 260, font_family="Arial Black", color="#ffffff", bold=True,
               align="center", shadow=_shadow(30, 12, "55")),
         _text(90, 640, 900, "sur toute la collection", 64, font_family="Segoe UI", color="#ffffff",
               align="center"),
         _shape(290, 1480, 500, 130, "round", radius=65.0, fill="#ffffff", shadow=_shadow()),
         _text(290, 1515, 500, "J'en profite", 48, font_family="Segoe UI", color="#ff3131", bold=True,
               align="center"),
     ]},
    {"key": "poster", "name": "Affiche minimaliste (A4)", "w": dm.FORMAT_SIZES["a4"][0], "h": dm.FORMAT_SIZES["a4"][1],
     "page": {"background": "#fdfbf7"},
     "items": [
         _shape(80, 80, 634, 634, "ellipse", fill="#ff5757"),
         _shape(300, 300, 340, 340, "triangle", fill="#1a1a1a", opacity=0.92),
         _text(80, 780, 634, "FORMES", 120, font_family="Arial Black", color="#1a1a1a", bold=True,
               letter_spacing=20.0),
         _text(80, 930, 634, "Exposition · Galerie du port · 12–28 mars", 26, font_family="Segoe UI",
               color="#545454"),
     ]},
    {"key": "card", "name": "Carte de visite", "w": dm.FORMAT_SIZES["card"][0], "h": dm.FORMAT_SIZES["card"][1],
     "page": {"background": "#ffffff"},
     "items": [
         _shape(0, 0, 14, dm.FORMAT_SIZES["card"][1], fill="#8c52ff"),
         _text(40, 40, 260, "Camille Martin", 26, font_family="Segoe UI", color="#1a1a1a", bold=True),
         _text(40, 78, 260, "Directrice artistique", 15, font_family="Segoe UI", color="#8c52ff"),
         _text(40, 135, 260, "camille@studio.example\n+33 6 00 00 00 00", 12, font_family="Segoe UI",
               color="#545454", line_height=1.4),
     ]},
    {"key": "thumb", "name": "Miniature vidéo", "w": 1280, "h": 720,
     "page": {"bg_type": "linear", "background": "#0cc0df", "bg2": "#004aad", "bg_angle": 90.0},
     "items": [
         _shape(760, 80, 440, 560, "round", radius=30.0, fill="#ffffff", opacity=0.18),
         _text(70, 170, 700, "5 ASTUCES", 120, font_family="Impact", color="#ffde59",
               shadow=_shadow(10, 8, "aa")),
         _text(70, 330, 700, "pour des rendus plus rapides", 60, font_family="Segoe UI", color="#ffffff",
               bold=True, line_height=1.1, shadow=_shadow(10, 6, "88")),
     ]},
    {"key": "banner", "name": "Bannière", "w": 1500, "h": 500,
     "page": {"background": "#1a1a1a"},
     "items": [
         _shape(1100, -100, 600, 700, "ellipse", fill_type="radial", fill="#cb6ce6", fill2="#1a1a1a"),
         _text(80, 150, 1000, "Studio de création", 90, font_family="Segoe UI", color="#ffffff", bold=True),
         _text(80, 280, 1000, "Animation · Effets visuels · Design", 40, font_family="Segoe UI", color="#cb6ce6"),
     ]},
]


def by_key(key: str) -> dict | None:
    return next((t for t in TEMPLATES if t["key"] == key), None)


def element_dicts(template: dict) -> list[dict]:
    """Éléments du modèle prêts à insérer (z dans l'ordre de la liste)."""
    out = []
    for n, raw in enumerate(template["items"]):
        data = dict(raw)
        data["z"] = float(n + 1)
        data["id"] = f"tpl{n}"
        out.append(data)
    return out

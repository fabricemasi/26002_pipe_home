"""Profils de rendu et snapshot du dernier rendu.

Carte et pièges : docs/agents/apercus.md.
"""

import json
import os
import re
from pathlib import Path
from PySide6.QtGui import QColor, QImage, QPainter
from config import DATA_DIR

# Apercu des fichiers .obj : projection orthographique fixe et wireframe
# opaque, sans remplissage, shader ni occlusion ambiante. L'image est mise
# en cache comme les autres apercus apres sa premiere generation.
OBJ_PREVIEW_MAX_TRIANGLES = 150_000   # au-dela, le maillage est tronque (vignette, pas un rendu final)

OBJ_PREVIEW_RENDER_EDGES = 20_000

# Resolution dediee, plus grande que FILE_IMAGE_CACHE_MAX_DIM (640, pense
# pour des photos deja haute def qu'on reduit) : un .obj est genere par
# nos soins a une taille fixe, donc c'est SA resolution native qui
# determine la nettete a l'agrandissement (Inspecteur elargi, HiDPI...),
# pas un simple redimensionnement d'un fichier source. Supersamplee en
# interne (voir _rasterize_obj_numpy) pour lisser aussi le contour. Une
# sortie 1800 px garde les details fins lorsque l'inspecteur est agrandi.
OBJ_PREVIEW_DIM = 1105

# Multiplicateur de l'epaisseur du wireframe. La valeur 1.0 reproduit
# exactement le calcul historique (environ 1.8 px dans l'image finale).
RENDER_PARAMETERS_PATH = Path(__file__).resolve().parent.parent / "files" / "parametres rendus.txt"

def _render_value(text: str):
    text = text.strip()
    lowered = text.casefold()
    if lowered in {"oui", "yes", "true", "on"}:
        return True
    if lowered in {"non", "no", "false", "off"}:
        return False
    # Les chemins et couleurs ne doivent jamais passer par l'extraction
    # numerique ci-dessous : un template comme *_01.blend deviendrait sinon
    # simplement l'entier 1.
    if text.startswith("#") or "\\" in text or "/" in text:
        return text
    if text.startswith("(") and text.endswith(")"):
        parts = [part.strip().replace(",", ".") for part in text[1:-1].split(",")]
        try:
            return tuple(float(part) for part in parts)
        except ValueError:
            pass
    match = re.fullmatch(r"\(?\s*([-+]?\d+(?:[.,]\d+)?)\s*,\s*([-+]?\d+(?:[.,]\d+)?)\s*,\s*([-+]?\d+(?:[.,]\d+)?)(?:\s*,\s*([-+]?\d+(?:[.,]\d+)?))?\s*\)?", text)
    if match:
        values = [float(part.replace(",", ".")) for part in match.groups() if part is not None]
        return tuple(values)
    match = re.search(r"([-+]?\d+(?:[.,]\d+)?)\s*[×x]\s*([-+]?\d+(?:[.,]\d+)?)", text, re.I)
    if match:
        return tuple(int(float(part.replace(",", "."))) for part in match.groups())
    match = re.search(r"([-+]?\d+(?:[.,]\d+)?)", text)
    if match:
        number = float(match.group(1).replace(",", "."))
        return int(number) if number.is_integer() else number
    return text

def _load_render_profiles() -> dict[str, dict[str, object]]:
    """Lit les profils LOW POLY et HIGH POLY depuis le fichier texte."""
    profiles: dict[str, dict[str, object]] = {}
    current: dict[str, object] | None = None
    key_map = {
        "fichier blender": "template",
        "vue": "view",
        "eclairage": "lighting",
        "eclairage scene": "lighting_scene",
        "eclairage hdri": "lighting_hdri_enabled",
        "force de l'hdri": "lighting_hdri_strength",
        # Les anciens settings utilisaient "Fond de l'image HDRI" pour le
        # chemin. Les nouveaux distinguent le chemin et l'affichage du fond.
        "path de l'image hdri": "lighting_hdri",
        "fond de l'image hdri": "lighting_hdri_background",
        "shader": "shader_name",
        "afficher l'image hdri dans le fond du rendu": "lighting_hdri_background",
        "facteur d'intensite de l'eclairage hdri": "lighting_hdri_strength",
        "facteur d'intensite des lights presentes dans la scene": "lighting_scene_strength",
        "shadows": "shadows",
        "shadows au sol": "ground_shadows",
        "wireframe": "wireframe",
        "subdivision": "subdivisions",
        "subdivisions": "subdivisions",
        "recalculer les normales": "recalculate_normals",
        "recalcul des normales": "recalculate_normals",
        "recalculer normales": "recalculate_normals",
        "epaisseur du wireframe": "wireframe_thickness",
        "shade": "shade",
        "couleur de base": "base_color",
        "couleur du wireframe": "wire_color",
        "couleur du fond": "background_color",
        "metallic": "metallic",
        "roughness": "roughness",
        "coat weight": "coat_weight",
        "coat roughness": "coat_roughness",
        "alpha": "alpha",
        "ambiant occlusion": "ambient_occlusion",
        "force ambiant occlusion": "ambient_occlusion_strength",
        "rendu": "engine",
        "resolution de sortie": "resolution",
        "format": "format",
        "transparence du fond": "film_transparent",
    }
    try:
        lines = RENDER_PARAMETERS_PATH.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return profiles
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        # Le fichier peut etre ecrit comme une liste Markdown. Retirer les
        # tirets de presentation, mais conserver le contenu de la ligne.
        while line.startswith("-"):
            line = line[1:].strip()
        if not line:
            continue
        if line.endswith(":") and ":" not in line[:-1]:
            name = line[:-1].strip().upper()
            if name in {"LOW POLY", "HIGH POLY"}:
                current = profiles.setdefault(name, {})
            else:
                current = None
            continue
        if current is None or ":" not in line:
            continue
        label, value = line.split(":", 1)
        if label.strip().casefold() == "notes":
            current = None
            continue
        # Nouveau format : "LIGHTING : parametre : valeur". Le premier
        # libelle est une categorie, le second est le vrai parametre.
        category = label.strip().casefold()
        if category == "shader":
            shader_match = re.search(r'["\u201c](.*?)["\u201d]', value)
            current["shader_name"] = (shader_match.group(1) if shader_match else value).strip()
            continue
        if category in {"lighting", "shadows", "wireframe", "ambiant occlusion", "camera"} and ":" in value:
            label, value = value.split(":", 1)
        normalized = label.strip().casefold().replace("é", "e").replace("è", "e").replace("ê", "e")
        normalized = normalized.replace("à", "a").replace("û", "u").replace("’", "'")
        key = key_map.get(normalized)
        if key:
            if key == "background_color" and value.strip().casefold().startswith("a appliquer:"):
                value = value.split(":", 1)[1].strip()
            parsed_value = _render_value(value)
            if key == "lighting_hdri_enabled" and isinstance(parsed_value, str):
                # Compatibilite avec l'ancienne forme ou le chemin etait
                # directement ecrit sur la ligne "Eclairage hdri".
                current["lighting_hdri"] = parsed_value
                current[key] = True
            elif key == "lighting_hdri_background" and isinstance(parsed_value, str):
                # Compatibilite avec l'ancien libelle qui portait directement
                # le chemin HDRI. Avec le nouveau format, cette ligne est un
                # simple oui/non et le chemin vient de "Path de l'image HDRI".
                current["lighting_hdri"] = parsed_value
            else:
                current[key] = parsed_value
            if key == "lighting_hdri" and str(parsed_value).strip():
                # Le format actuel active implicitement l'HDRI dès qu'un
                # chemin est fourni; l'ancien format pouvait encore fournir
                # un champ explicite "Eclairage hdri : non".
                current.setdefault("lighting_hdri_enabled", True)
        elif normalized == "camera":
            clips = re.findall(r"[-+]?\d+(?:[.,]\d+)?", value)
            if len(clips) >= 2:
                current["clip_near"] = float(clips[0].replace(",", "."))
                current["clip_far"] = float(clips[1].replace(",", "."))
        else:
            current.setdefault("unrecognized", []).append(label.strip())
    return profiles

# Profils de rendu : `parametres rendus.txt` n'est lu QUE pour lancer un rendu (manuel ou lot
# automatique, _reload_render_profiles) — jamais pour afficher une image 2D ou un rendu 3D deja
# fait. Entre deux rendus, les cles de cache 3D se calculent avec les profils du DERNIER rendu,
# gardes dans RENDER_PROFILES_SNAPSHOT (relu au demarrage ; le fichier texte seulement s'il manque).
RENDER_PROFILES_SNAPSHOT = DATA_DIR / "render_profiles_snapshot.json"

def _write_profiles_snapshot(profiles: dict) -> None:
    try:
        temp = RENDER_PROFILES_SNAPSHOT.with_suffix(".json.tmp")
        temp.write_text(json.dumps(profiles, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(temp, RENDER_PROFILES_SNAPSHOT)
    except OSError:
        pass

def _initial_render_profiles() -> dict[str, dict[str, object]]:
    try:
        profiles = json.loads(RENDER_PROFILES_SNAPSHOT.read_text(encoding="utf-8"))
        if isinstance(profiles, dict):
            return profiles
    except (OSError, ValueError):
        pass
    profiles = _load_render_profiles()
    if profiles:
        _write_profiles_snapshot(profiles)
    return profiles

_RENDER_PROFILES = _initial_render_profiles()

_AUTOMATIC_RENDER_PROFILE: dict[str, object] | None = None

_AUTOMATIC_RENDER_PROFILES: dict[str, dict[str, object]] | None = None

def _reload_render_profiles() -> None:
    """Relit `parametres rendus.txt` : uniquement au lancement d'un rendu."""
    global _RENDER_PROFILES
    _RENDER_PROFILES = _load_render_profiles()
    _write_profiles_snapshot(_RENDER_PROFILES)

def _begin_automatic_render_batch() -> None:
    global _AUTOMATIC_RENDER_PROFILE, _AUTOMATIC_RENDER_PROFILES
    _reload_render_profiles()
    _AUTOMATIC_RENDER_PROFILES = json.loads(json.dumps(_RENDER_PROFILES))
    _AUTOMATIC_RENDER_PROFILE = _render_profile(
        "low", _AUTOMATIC_RENDER_PROFILES.get("LOW POLY", {})
    )

def _render_profile(render_mode: str, profile_override: dict[str, object] | None = None) -> dict[str, object]:
    profile = dict(profile_override or _RENDER_PROFILES.get("HIGH POLY" if render_mode == "high" else "LOW POLY", {}))
    profile.setdefault("template", "scene pour appercu.blend")
    profile.setdefault("lighting_scene", True)
    profile.setdefault("lighting_scene_strength", 1.0)
    profile.setdefault("lighting_hdri", "")
    profile.setdefault("lighting_hdri_enabled", False)
    profile.setdefault("lighting_hdri_strength", 1.0)
    profile.setdefault("shader_name", "")
    profile.setdefault("wireframe", render_mode != "high")
    profile.setdefault("wireframe_thickness", 1.0)
    profile.setdefault("subdivisions", 0)
    profile.setdefault("recalculate_normals", False)
    profile.setdefault("shadows", render_mode == "high")
    profile.setdefault("ground_shadows", render_mode == "high")
    profile.setdefault("shade", "smooth" if render_mode == "high" else "flat")
    profile.setdefault("base_color", (0.48, 0.50, 0.53))
    profile.setdefault("wire_color", (0.0, 0.0, 0.0, 1.0))
    profile.setdefault("metallic", 0.0)
    profile.setdefault("roughness", 1.0)
    profile.setdefault("coat_weight", 0.0)
    profile.setdefault("coat_roughness", 0.0)
    profile.setdefault("alpha", 1.0)
    profile.setdefault("ambient_occlusion", False)
    profile.setdefault("ambient_occlusion_strength", 1.0)
    profile.setdefault("clip_near", 0.1)
    profile.setdefault("clip_far", 1000.0)
    profile.setdefault("engine", "eevee")
    profile.setdefault("resolution", (1000, 1000))
    profile.setdefault("format", "png")
    profile.setdefault("background_color", "#3a3a3a")
    profile.setdefault("film_transparent", True)
    return profile

def _apply_render_background(image: QImage, profile: dict[str, object]) -> QImage:
    """Compose un rendu detoure sur le fond configure dans le profil.

    Blender rend toujours avec un canal alpha (meme quand le resultat final
    doit etre opaque). Cela evite que le fond du template ou l'HDRI ne soit
    "brule" dans les contours avant la composition finale.
    """
    if bool(profile.get("film_transparent", True)):
        return image
    background = QColor(str(profile.get("background_color", "#3a3a3a")).strip())
    if not background.isValid():
        background = QColor("#3a3a3a")
    background.setAlpha(255)
    composed = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
    composed.fill(background)
    painter = QPainter(composed)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.drawImage(0, 0, image)
    painter.end()
    return composed

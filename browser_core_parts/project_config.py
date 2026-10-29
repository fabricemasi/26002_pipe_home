"""Configurations de projet, disposition, punaise et raccourcis. Carte : docs/agents/colonnes.md."""

import json
from pathlib import Path
import ui_state
from config import SOFTWARE_COLUMN_LABEL
from previews import _clear_hidden, _set_hidden
from . import scan as _scan
from . import status as _status

# ==========================================================================
# Chaine de navigation configurable PAR PROJET (voir ColumnConfigDialog) —
# voir la remarque de l'utilisateur, "j'aimerai que cette configuration
# change, mais suivant les besoins de l'utilisateur ... cette icone doit
# etre cliquable et faire apparaitre une fenetre qui permettra de determiner
# le nombres de colonnes a deployer". Stockee DANS le dossier du projet
# (voyage avec lui, meme esprit que THUMBNAIL_FILENAME/project_thumbnail_
# path juste au-dessus) — un projet SANS ce fichier (cas le plus courant,
# tant que l'utilisateur n'a jamais ouvert cette fenetre) garde EXACTEMENT
# la chaine fixe Type/Projets/Sous-projet/Logiciels d'aujourd'hui (voir
# PipelineBrowser.on_selected, branche `if config is None`).
# ==========================================================================

PROJECT_COLUMNS_FILENAME = ".pipeline_columns.json"

# Modele de configuration pose a la racine d'une liste de projets (par
# exemple la cible d'un raccourci « PROG »). Les projets DIRECTEMENT dans
# cette racine qui n'ont pas encore leur propre fichier l'heritent : un
# nouveau dossier est donc configure des sa premiere ouverture, sans que
# l'application ait a creer un fichier dans chaque projet. Une configuration
# propre au projet garde toujours la priorite.
PROJECT_COLUMNS_DEFAULTS_FILENAME = ".pipeline_project_defaults.json"

# "Type" du repertoire de travail final (voir ColumnConfigDialog, menu
# deroulant "Repertoire de travail > Type") : cle -> nom de DOSSIER fixe
# recherche (voir _named_subdir), libelle du menu deroulant ("label"),
# intitule affiche en entete de la colonne du groupe ("display", INCHANGE
# entre les 2 types — c'est la meme colonne conceptuelle, seule son
# APPARENCE change), et cle de STYLE ("style_title", voir column_style_for)
# qui pilote reellement hauteur de ligne/police/couleurs/bordures/padding —
# voir la remarque de l'utilisateur, "je veux avoir le choix entre deux
# types : logiciels ... et standard ... elle doit avoir le meme
# comportement que les colonnes standards que l'on trouve apres" :
# "standard" reutilise donc la cle "Contenu", DEJA partagee par IN/OVER/OUT
# (voir add_group_column plus bas) et desactive only_recognized_software
# (icones/filtre "logiciel reconnu", propre au type "logiciel").
WORK_DIR_TYPES: dict[str, dict] = {
    "logiciel": {
        "folder_name": _status.SOFTS_FOLDER_NAME, "label": "Logiciels",
        "display": SOFTWARE_COLUMN_LABEL, "style_title": SOFTWARE_COLUMN_LABEL,
        "only_recognized_software": True,
    },
    "standard": {
        "folder_name": _status.SOFTS_FOLDER_NAME, "label": "Standard",
        "display": SOFTWARE_COLUMN_LABEL, "style_title": "Contenu",
        "only_recognized_software": False,
        # En-tete DYNAMIQUE (voir update_preview_stack, "display" ci-dessus
        # ignore alors) : reprend le nom de la selection de la colonne
        # PRECEDENTE (terminal_path), exactement comme une colonne "de set"
        # normale (voir add_column/display_title) — voir la remarque de
        # l'utilisateur, "quand la colonne logiciels n'est pas formatee
        # comme logiciel, je veux qu'elle ait le nom de la selection de la
        # colonne precedente".
        "display_from_selection": True,
    },
}

DEFAULT_WORK_DIR_TYPE = "logiciel"

def _project_columns_path(project_dir: Path) -> Path:
    return project_dir / PROJECT_COLUMNS_FILENAME

def _project_columns_defaults_path(project_dir: Path) -> Path:
    """Modele des projets enfants directs de ``project_dir``."""
    return project_dir / PROJECT_COLUMNS_DEFAULTS_FILENAME

def _coerce_project_column(raw: dict) -> dict:
    """Normalise UN niveau de la chaine configuree (voir load_project_
    columns) — repli sur des valeurs sures pour toute cle manquante/mal
    typee dans un JSON ecrit a la main ou corrompu, plutot que de faire
    planter toute la navigation pour un seul projet mal configure."""
    name = str(raw.get("name") or "").strip()
    return {
        "name": name,
        "show_dirs": bool(raw.get("show_dirs", True)),
        "show_files": bool(raw.get("show_files", False)),
        "omit_dirs": [str(v) for v in (raw.get("omit_dirs") or []) if str(v).strip()],
        "omit_files": [str(v) for v in (raw.get("omit_files") or []) if str(v).strip()],
        "focus": bool(raw.get("focus", False)),
    }

def _coerce_work_dir(raw: dict) -> dict:
    work_type = raw.get("type")
    if work_type not in WORK_DIR_TYPES:
        work_type = DEFAULT_WORK_DIR_TYPE
    return {
        "type": work_type,
        "show_dirs": bool(raw.get("show_dirs", True)),
        "show_files": bool(raw.get("show_files", False)),
        "omit_dirs": [str(v) for v in (raw.get("omit_dirs") or []) if str(v).strip()],
        "omit_files": [str(v) for v in (raw.get("omit_files") or []) if str(v).strip()],
    }

_PROJECT_COLUMNS_CACHE: dict[Path, tuple[int | None, int | None, tuple | None, dict | None]] = {}

_PROJECT_LIGHTROOM_CACHE: dict[Path, tuple[Path, int, int | None] | None] = {}

def _lightroom_set_defaults(project_dir: Path) -> tuple | None:
    """Reglages de set hérités du dossier Lightroom associé le plus proche."""
    cached = _PROJECT_LIGHTROOM_CACHE.get(project_dir, ...)
    if cached is not ...:
        if cached is None:
            return None
        marker, marker_mtime, generation = cached
        state = _scan.config_state(marker)
        if state is not None and state[0] == marker_mtime:
            return (str(marker), marker_mtime, generation)
    current = project_dir
    while True:
        marker = current / ".pipeline_lightroom.json"
        try:
            state = _scan.config_state(marker)
            text = _scan.read_config_text(marker) if state is not None else None
            raw = json.loads(text) if text is not None else None
            if isinstance(raw, dict) and raw.get("catalog"):
                generation = raw.get("set_defaults_at_ns")
                try:
                    generation = int(generation) if generation is not None else None
                except (TypeError, ValueError):
                    generation = None
                _PROJECT_LIGHTROOM_CACHE[project_dir] = (marker, state[0], generation)
                return (str(marker), state[0], generation)
        except (OSError, ValueError):
            pass
        parent = current.parent
        if parent == current:
            _PROJECT_LIGHTROOM_CACHE[project_dir] = None
            return None
        current = parent

def invalidate_project_columns_cache() -> None:
    """Invalide les configs et associations Lightroom mémorisées après un lien."""
    _PROJECT_COLUMNS_CACHE.clear()
    _PROJECT_LIGHTROOM_CACHE.clear()
    _scan.forget_all_config()

def _lightroom_default_project_config() -> dict:
    return {
        "columns": [],
        "work_dir": {
            "type": "standard", "show_dirs": True, "show_files": True,
            "omit_dirs": [], "omit_files": [],
        },
        "set_enabled": False,
        "focus_enabled": False,
        "in_over_out_enabled": False,
    }

def _read_project_columns(path: Path) -> dict | None:
    """Lit et normalise un fichier de configuration de projet."""
    try:
        text = _scan.read_config_text(path)
        raw = json.loads(text) if text is not None else None
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    columns = [_coerce_project_column(c) for c in (raw.get("columns") or []) if isinstance(c, dict)]
    return {
        "columns": [c for c in columns if c["name"]],
        "work_dir": _coerce_work_dir(raw.get("work_dir") or {}),
        "set_enabled": bool(raw.get("set_enabled", True)),
        "focus_enabled": bool(raw.get("focus_enabled", True)),
        "in_over_out_enabled": bool(raw.get("in_over_out_enabled", True)),
    }

def load_project_columns(project_dir: Path) -> dict | None:
    """Configuration de chaine de navigation propre a `project_dir` (voir
    PROJECT_COLUMNS_FILENAME) — None si le fichier est absent/illisible/
    invalide (repli SILENCIEUX sur la chaine legacy fixe, voir on_selected :
    un JSON corrompu ne doit jamais empecher de naviguer, juste ignorer la
    personnalisation) : `{"columns": [{"name","show_dirs","show_files",
    "omit_dirs","omit_files","focus"}, ...], "work_dir": {"type",
    "show_dirs","show_files","omit_dirs","omit_files"}}`. Chaque niveau de
    "columns" ne garde jamais un `name` vide (voir _coerce_project_column) —
    un niveau sans nom n'aurait aucun dossier fixe a chercher. "columns"
    VIDE est desormais une configuration VALIDE (voir ColumnConfigDialog.
    MIN_STEPS, "base 2" : Type+Projets, directement suivis du repertoire de
    travail, aucun niveau intermediaire) — voir la remarque de
    l'utilisateur, "peux-tu faire en sorte de pouvoir setter en base 2" :
    distinct d'un fichier ABSENT/invalide (repli sur la chaine legacy a 3
    etapes), un fichier valide avec "columns": [] doit rester tel quel,
    PAS retomber sur le repli legacy.

    Cache par mtime (voir _PROJECT_COLUMNS_CACHE, meme principe que
    software_icon_pixmap) : appelee a CHAQUE peinture d'une ligne "Projets"
    (voir ProjectTileDelegate.paint, step_badge) — sans cache, un
    Ctrl+glisser de redimensionnement de ligne (jusqu'a ~60 relayouts/s,
    voir _throttled_layout) relisait ce fichier ET reparsait son JSON a
    CHAQUE ligne visible ET a CHAQUE frame, d'ou la lenteur constatee par
    l'utilisateur specifiquement sur cette colonne, "quand je veux
    redimensionner les lignes ... il y a de grosses lenteurs"."""
    path = _project_columns_path(project_dir)
    defaults_path = _project_columns_defaults_path(project_dir.parent)
    state = _scan.config_state(path)
    mtime = state[0] if state is not None else None
    state = _scan.config_state(defaults_path)
    defaults_mtime = state[0] if state is not None else None
    lightroom_defaults = _lightroom_set_defaults(project_dir)
    cached = _PROJECT_COLUMNS_CACHE.get(project_dir)
    if (cached is not None and cached[0] == mtime and cached[1] == defaults_mtime
            and cached[2] == lightroom_defaults):
        return cached[3]
    result: dict | None = None
    generation = lightroom_defaults[2] if lightroom_defaults is not None else None
    use_lightroom_defaults = lightroom_defaults is not None and (
        mtime is None or (generation is not None and mtime <= generation)
    )
    if use_lightroom_defaults:
        result = _lightroom_default_project_config()
    elif mtime is not None:
        result = _read_project_columns(path)
    # Un modele n'est consulte QUE lorsqu'il n'y a pas de configuration
    # propre : les reglages explicites d'un projet restent independants.
    elif defaults_mtime is not None:
        result = _read_project_columns(defaults_path)
    _PROJECT_COLUMNS_CACHE[project_dir] = (mtime, defaults_mtime, lightroom_defaults, result)
    return result

def save_project_columns_defaults(project_root: Path, config: dict) -> None:
    """Enregistre le modele herite par les futurs projets de ``project_root``."""
    path = _project_columns_defaults_path(project_root)
    payload = {
        "columns": [_coerce_project_column(c) for c in config.get("columns", [])],
        "work_dir": _coerce_work_dir(config.get("work_dir") or {}),
        "set_enabled": bool(config.get("set_enabled", True)),
        "focus_enabled": bool(config.get("focus_enabled", True)),
        "in_over_out_enabled": bool(config.get("in_over_out_enabled", True)),
    }
    _clear_hidden(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _set_hidden(path)
    _scan.forget_config(path)
    _PROJECT_COLUMNS_CACHE.clear()

def save_project_columns(project_dir: Path, config: dict) -> None:
    """Ecrit `config` (MEME forme que load_project_columns) dans le dossier
    du projet — voir ColumnConfigDialog._on_save. `_set_hidden` (deja
    utilise pour .thumbnail.png/.pipeline_preview_cache) : cache le fichier
    a l'explorateur Windows, meme convention que le reste des fichiers
    internes de l'appli poses directement dans un dossier de projet.
    `_clear_hidden` AVANT d'ecrire (voir sa remarque de tete) : ce fichier a
    deja pu etre cache par un PRECEDENT appel — sans ca, toute MODIFICATION
    d'une configuration existante echouait silencieusement (PermissionError
    non rattrapee)."""
    path = _project_columns_path(project_dir)
    payload = {
        "columns": [_coerce_project_column(c) for c in config.get("columns", [])],
        "work_dir": _coerce_work_dir(config.get("work_dir") or {}),
        "set_enabled": bool(config.get("set_enabled", True)),
        "focus_enabled": bool(config.get("focus_enabled", True)),
        "in_over_out_enabled": bool(config.get("in_over_out_enabled", True)),
    }
    _clear_hidden(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _set_hidden(path)
    # Purge le cache (voir load_project_columns) : une resolution de mtime
    # au-dela de la seconde (courante sur certains systemes de fichiers)
    # pourrait sinon renvoyer encore l'ANCIENNE config juste apres cet
    # enregistrement.
    _PROJECT_COLUMNS_CACHE.pop(project_dir, None)
    _scan.forget_config(path)

def project_step_count(config: dict | None) -> int | str:
    """Nombre d'etapes necessaires pour etre "bien sette" dans l'espace de
    travail d'un projet (voir le badge numerote, ProjectTileDelegate.paint)
    — Type + Projets (2, TOUJOURS presents) + le nombre de niveaux
    configures avant le repertoire de travail ; 3 (comportement D'AVANT ce
    reglage — Type/Projets/Sous-projet) si aucune configuration — voir la
    remarque de l'utilisateur, "actuellement l'icone devrait comporter le
    chiffre 3"."""
    if config is None:
        return 3
    if not config.get("set_enabled", True):
        # "N" (PAS 2, voir _step_badge_color/_step_badge_text_color) : sans
        # "set", ce projet n'a plus de nombre d'etapes a proprement parler
        # (aucune limite de profondeur, voir _chain_expected_total/
        # on_selected) — voir la remarque de l'utilisateur, "quand set est
        # desactive je veux que l'indicateur de base affiche N".
        return "N"
    return 2 + len(config["columns"])

# ==========================================================================
# Reglages de MISE EN PAGE propres a UN dossier (hauteur de ligne d'une
# colonne, hauteur des colonnes du groupe IN/OVER/OUT/LOGICIELS) — meme
# convention que .pipeline_columns.json/.thumbnail.png (fichier CACHE pose
# DANS le dossier concerne, voir _set_hidden) : voir la remarque de
# l'utilisateur, "le dimensionnement en hauteur des colonnes de focus doit
# etre enregistre en temps reel et ce dependant du [sous-]dossier ... d'un
# sous dossier a l'autre, les dimensionnements seront differents ...
# exactement pareil pour la hauteur des lignes de dossier et de fichier de
# l'ensemble de l'appli ... des fichiers de settings qui enregistrent ces
# modifs directement sur les emplacements des dossiers". Remplace, pour la
# hauteur de ligne, l'ancien reglage UNIQUEMENT GLOBAL (COLUMN_SETTINGS/
# _col_key, par bucket de style partage entre TOUTES les colonnes de ce
# style) par un reglage PAR DOSSIER REELLEMENT AFFICHE (voir Column.
# directory) — le bucket de style reste le repli par defaut tant qu'aucun
# dossier n'a encore ete ajuste a la main.
# ==========================================================================

LAYOUT_SETTINGS_FILENAME = ".pipeline_layout.json"

def _layout_settings_path(directory: Path) -> Path:
    return directory / LAYOUT_SETTINGS_FILENAME

# Valeurs de la PUNAISE d'une colonne (punaise, largeur, hauteur de ligne, options du menu contextuel
# retenues avec elle) : propres au PRESET EN COURS (demande de l'utilisateur), rangees dans le fichier sous
# `by_preset` -> {nom du preset ("" = aucun): {cle: valeur}}. Les autres cles (ordre, espaces, titres...)
# restent communes. Ces fonctions donnent / prennent la VUE du preset en cours : les appelants n'ont rien
# a savoir.
PIN_LAYOUT_KEYS = ("pinned", "pinned_column_width", "pinned_row_height", "row_height", "show_icon",
                   "show_preview", "icon_size", "icon_padding_left", "text_padding_left")

_BY_PRESET = "by_preset"

def _layout_preset() -> str:
    from settings_store import preset_in_use
    return preset_in_use(ui_state.APPLIED_SETTINGS or {})

def _read_layout_raw(directory: Path) -> dict:
    path = _layout_settings_path(directory)
    try:
        text = _scan.read_config_text(path)
        raw = json.loads(text) if text is not None else {}
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}

def load_layout_settings(directory: Path, *, migrate: bool = True) -> dict:
    """Reglages de mise en page de `directory` — {} si le fichier est
    absent/illisible/invalide (repli SILENCIEUX sur les valeurs par
    defaut, meme esprit que load_project_columns : jamais bloquant).
    Valeurs de punaise : celles du preset en cours (voir PIN_LAYOUT_KEYS) ; les anciennes, communes a
    tous (d'avant les presets), reviennent au premier preset qui les lit et lui sont attribuees."""
    raw = _read_layout_raw(directory)
    view = {k: v for k, v in raw.items() if k not in PIN_LAYOUT_KEYS and k != _BY_PRESET}
    by_preset = raw.get(_BY_PRESET) if isinstance(raw.get(_BY_PRESET), dict) else {}
    preset = _layout_preset()
    own = by_preset.get(preset)
    legacy = {k: raw[k] for k in PIN_LAYOUT_KEYS if k in raw}
    if not isinstance(own, dict):
        own = legacy if legacy and not by_preset else {}
        if own and migrate:
            save_layout_settings(directory, {**view, **own})     # attribuees au preset en cours
    view.update(own)
    return view

def save_layout_settings(directory: Path, data: dict) -> None:
    """Ecrit `data` (dict complet) dans le dossier — voir _update_layout_
    setting pour ne modifier qu'UNE cle. `_clear_hidden` AVANT d'ecrire
    (voir sa remarque de tete, meme piege Windows deja rencontre avec
    save_project_columns) : ce fichier a deja pu etre cache par un
    PRECEDENT appel."""
    path = _layout_settings_path(directory)
    raw = _read_layout_raw(directory)
    by_preset = raw.get(_BY_PRESET) if isinstance(raw.get(_BY_PRESET), dict) else {}
    out = {k: v for k, v in data.items() if k not in PIN_LAYOUT_KEYS and k != _BY_PRESET}
    pins = {k: data[k] for k in PIN_LAYOUT_KEYS if k in data}
    by_preset = dict(by_preset)
    if pins:
        by_preset[_layout_preset()] = pins
    else:
        by_preset.pop(_layout_preset(), None)
    if by_preset:
        out[_BY_PRESET] = by_preset
    _clear_hidden(path)
    try:
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        _scan.forget_config(path)
        return
    _set_hidden(path)
    _scan.forget_config(path)

def _update_layout_setting(directory: Path, key: str, value) -> None:
    """Modifie UNE seule cle des reglages de mise en page de `directory`,
    en conservant les autres (voir save_layout_settings) — appelee a
    CHAQUE relachement de glisser (voir Column.row_resize_end/
    PipelineBrowser._on_group_height_resize_end), jamais pendant le
    glisser lui-meme (memes bornes que _persist_row_height, deja
    limitees au relachement pour ne pas ecrire sur le disque a CHAQUE
    mouvement de souris)."""
    data = load_layout_settings(directory)
    data[key] = value
    save_layout_settings(directory, data)

# Raccourcis (voir Column._on_context_menu "Ajouter un raccourci", refresh()) :
# un dossier situe AILLEURS sur le disque, affiche comme s'il etait
# physiquement dans CE dossier — enregistres dans un fichier cache PROPRE A
# CE DOSSIER (meme convention que .pipeline_layout.json/la punaise), pas dans
# un reglage GENERAL : si le dossier racine change, un raccourci pose ICI ne
# doit jamais se retrouver, par erreur, dans une colonne d'un tout AUTRE
# projet — voir la remarque de l'utilisateur, "de maniere a ce que si on
# change le root, le raccourci ne se retrouve pas dans une colonne malgre
# lui".
SHORTCUTS_FILENAME = ".pipeline_shortcuts.json"

def _shortcuts_path(directory: Path) -> Path:
    return directory / SHORTCUTS_FILENAME

def load_shortcuts(directory: Path) -> list[dict]:
    """Raccourcis de `directory` — [] si le fichier est absent/illisible/
    invalide (repli SILENCIEUX, meme convention que load_layout_settings)."""
    try:
        text = _scan.read_config_text(_shortcuts_path(directory))
        raw = json.loads(text) if text is not None else []
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict) and e.get("target")]

def save_shortcuts(directory: Path, shortcuts: list[dict]) -> None:
    path = _shortcuts_path(directory)
    _clear_hidden(path)
    try:
        path.write_text(json.dumps(shortcuts, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        _scan.forget_config(path)
        return
    _set_hidden(path)
    _scan.forget_config(path)

def add_shortcut(directory: Path, target: Path) -> None:
    shortcuts = load_shortcuts(directory)
    target_str = str(target)
    if any(s.get("target") == target_str for s in shortcuts):
        return
    shortcuts.append({"target": target_str})
    save_shortcuts(directory, shortcuts)

def remove_shortcut(directory: Path, target: Path) -> None:
    shortcuts = load_shortcuts(directory)
    target_str = str(target)
    filtered = [s for s in shortcuts if s.get("target") != target_str]
    if len(filtered) != len(shortcuts):
        save_shortcuts(directory, filtered)

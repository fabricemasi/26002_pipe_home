"""Points de branchement de fm_theme : ce que l'appli hôte fournit (fm_theme n'importe jamais l'appli).

- `default_settings() -> dict`, `load_settings() -> dict`, `save_settings(dict)` : réglages de l'appli
  (défauts, lecture, écriture). Sans appli : défauts vides, lecture vide, écriture ignorée.
- `ui_icon(nom, taille) -> QPixmap | None` : icône d'interface choisie par l'utilisateur (nom : « settings_gear »),
  None pour garder le dessin par défaut.

Une clé absente : comportement par défaut de fm_theme. Aucun import ici (chargé par tout le monde)."""
from typing import Any

HOOKS: dict[str, Any] = {}


def default_settings() -> dict:
    """Défauts des réglages de l'appli hôte (dict partagé : ne pas le modifier)."""
    hook = HOOKS.get("default_settings")
    return hook() if hook is not None else {}


def load_settings() -> dict:
    """Réglages courants de l'appli hôte."""
    hook = HOOKS.get("load_settings")
    return hook() if hook is not None else {}


def save_settings(settings: dict) -> None:
    """Enregistre les réglages de l'appli hôte."""
    hook = HOOKS.get("save_settings")
    if hook is not None:
        hook(settings)


def ui_icon(name: str, size: int):
    """Icône d'interface fournie par l'appli hôte, ou None."""
    hook = HOOKS.get("ui_icon")
    return hook(name, size) if hook is not None else None

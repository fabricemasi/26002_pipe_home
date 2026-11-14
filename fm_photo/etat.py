"""État photographique NON DESTRUCTIF d'une photo : versions, opérations ordonnées, historique, stockage (sans Qt).

L'original n'est jamais modifié. L'état est un dictionnaire JSON (les clés INCONNUES sont gardées telles quelles à
la lecture comme à l'écriture) :

    {"schema": 1, "courante": "v1", "identite": {"lightroom_uuid": "", "empreinte": ""},
     "versions": [{"id": "v1", "nom": "Version 1", "moteur": "0.1.0",
                   "operations": [{"op": "exposition", "version": 1, "actif": true, "params": {"ev": 0.5}}]}]}

- une VERSION (copie virtuelle) = la suite ordonnée de ses opérations ; l'ordre est celui du calcul ;
- chaque opération porte la version de son algorithme (`version`) et chaque version celle du moteur qui l'a
  écrite : un algorithme modifié garde son ancienne version disponible ou fournit une migration, jamais de
  changement silencieux d'un ancien rendu ;
- les fonctions de modification RENVOIENT un nouvel état (l'ancien reste intact) : Undo / Redo = `Historique`.

Stockage : un fichier caché par dossier, `.pipeline_photo.json` ({nom de fichier: état}), comme les attributs
(`fm_visionneuse/file_attributes.py`), y compris dans un dossier associé à Lightroom : c'est l'état PROPRE à
PIPE FMZ, il n'écrit rien dans le catalogue ni dans un XMP. Écriture atomique ; un fichier d'un schéma plus récent
n'est jamais réécrit ; une migration garde l'ancien fichier en `.pipeline_photo.json.v<schéma>.bak`."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from pathlib import Path

SCHEMA = 1
MOTEUR = "0.1.0"
FICHIER = ".pipeline_photo.json"

# schéma d'origine -> fonction(état) -> état au schéma suivant. Vide tant que SCHEMA == 1.
MIGRATIONS: dict = {}


class EtatTropRecent(ValueError):
    """Écrit par une version plus récente de l'appli : lu tel quel par personne, réécrit par personne."""


def nouvel_etat() -> dict:
    return {"schema": SCHEMA, "courante": "v1", "identite": {},
            "versions": [{"id": "v1", "nom": "Version 1", "moteur": MOTEUR, "operations": []}]}


def migrer(etat: dict) -> dict:
    """État amené au schéma courant (copie) ; `EtatTropRecent` s'il vient du futur."""
    schema = int(etat.get("schema", 1))
    if schema > SCHEMA:
        raise EtatTropRecent(f"schéma {schema} > {SCHEMA}")
    etat = copy.deepcopy(etat)
    while schema < SCHEMA:
        etat = MIGRATIONS[schema](etat)
        schema += 1
        etat["schema"] = schema
    return etat


def version(etat: dict, ident: str | None = None) -> dict:
    """La version demandée (la courante par défaut) ; `KeyError` si elle n'existe pas."""
    ident = ident or etat.get("courante")
    for candidate in etat.get("versions", []):
        if candidate.get("id") == ident:
            return candidate
    raise KeyError(ident)


def operations(etat: dict, ident: str | None = None) -> list:
    return version(etat, ident).get("operations", [])


def definir_operation(etat: dict, op: str, params: dict, *, version_op: int = 1, actif: bool = True,
                      ident: str | None = None) -> dict:
    """Nouvel état où l'opération `op` de la version a ces paramètres (ajoutée EN FIN de chaîne si absente :
    la place dans la chaîne est celle de la première pose, `deplacer_operation` la change)."""
    etat = copy.deepcopy(etat)
    cible = version(etat, ident)
    cible["moteur"] = MOTEUR
    for entree in cible.setdefault("operations", []):
        if entree.get("op") == op:
            entree.update({"version": version_op, "actif": actif, "params": dict(params)})
            return etat
    cible["operations"].append({"op": op, "version": version_op, "actif": actif, "params": dict(params)})
    return etat


def retirer_operation(etat: dict, op: str, ident: str | None = None) -> dict:
    etat = copy.deepcopy(etat)
    cible = version(etat, ident)
    cible["operations"] = [entree for entree in cible.get("operations", []) if entree.get("op") != op]
    return etat


def deplacer_operation(etat: dict, op: str, rang: int, ident: str | None = None) -> dict:
    etat = copy.deepcopy(etat)
    suite = version(etat, ident).setdefault("operations", [])
    for index, entree in enumerate(suite):
        if entree.get("op") == op:
            suite.insert(max(0, min(rang, len(suite) - 1)), suite.pop(index))
            break
    return etat


def copie_virtuelle(etat: dict, nom: str = "", source: str | None = None) -> dict:
    """Nouvel état avec une version de plus, copie de `source` (la courante), qui devient la courante."""
    etat = copy.deepcopy(etat)
    modele = copy.deepcopy(version(etat, source))
    pris = {candidate.get("id") for candidate in etat["versions"]}
    numero = len(etat["versions"]) + 1
    while f"v{numero}" in pris:
        numero += 1
    modele.update({"id": f"v{numero}", "nom": nom or f"Version {numero}"})
    etat["versions"].append(modele)
    etat["courante"] = modele["id"]
    return etat


def choisir_version(etat: dict, ident: str) -> dict:
    version(etat, ident)
    etat = copy.deepcopy(etat)
    etat["courante"] = ident
    return etat


def signature(suite: list) -> str:
    """Empreinte stable de ce qu'une suite d'opérations CALCULE (clé des caches de rendu) : opérations actives,
    dans l'ordre, avec la version de leur algorithme. Deux états au même rendu ont la même signature."""
    actives = [{"op": entree.get("op"), "version": entree.get("version", 1), "params": entree.get("params", {})}
               for entree in suite if entree.get("actif", True)]
    texte = json.dumps(actives, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha1(texte.encode("ascii")).hexdigest()


class Historique:
    """Undo / Redo d'un état : pile bornée d'états (immuables par convention)."""

    def __init__(self, etat: dict, limite: int = 200):
        self._etats, self._rang, self._limite = [etat], 0, limite

    @property
    def etat(self) -> dict:
        return self._etats[self._rang]

    def poser(self, etat: dict) -> None:
        if etat == self.etat:
            return
        del self._etats[self._rang + 1:]
        self._etats.append(etat)
        if len(self._etats) > self._limite:
            del self._etats[0]
        self._rang = len(self._etats) - 1

    def annuler(self) -> dict:
        self._rang = max(0, self._rang - 1)
        return self.etat

    def retablir(self) -> dict:
        self._rang = min(len(self._etats) - 1, self._rang + 1)
        return self.etat

    def peut_annuler(self) -> bool:
        return self._rang > 0

    def peut_retablir(self) -> bool:
        return self._rang < len(self._etats) - 1


# --- stockage par dossier -----------------------------------------------------------------------------------

_verrou = threading.Lock()
_dossiers: dict[str, tuple[tuple, dict]] = {}      # dossier -> (date et taille du fichier, contenu)


def _fichier(photo: Path) -> Path:
    return Path(photo).parent / FICHIER


def _timbre(fichier: Path):
    try:
        info = fichier.stat()
        return info.st_mtime_ns, info.st_size
    except OSError:
        return None


def _lire_dossier(fichier: Path) -> dict:
    cle = os.path.normcase(str(fichier))
    timbre = _timbre(fichier)
    with _verrou:
        connu = _dossiers.get(cle)
        if connu is not None and connu[0] == timbre:
            return connu[1]
    contenu = {}
    if timbre is not None:
        try:
            lu = json.loads(fichier.read_text(encoding="utf-8"))
            if isinstance(lu, dict):
                contenu = lu
        except (OSError, ValueError):
            contenu = {}
    with _verrou:
        _dossiers[cle] = (timbre, contenu)
    return contenu


def lire(photo: Path) -> dict | None:
    """État enregistré de cette photo (au schéma courant), ou None. Accès disque : hors du fil de l'interface
    quand le dossier n'est pas encore en mémoire. `EtatTropRecent` si le fichier vient d'une appli plus récente."""
    brut = _lire_dossier(_fichier(photo)).get(Path(photo).name)
    return migrer(brut) if isinstance(brut, dict) else None


def _cacher(fichier: Path, cache: bool) -> None:
    if os.name != "nt":
        return
    import ctypes
    attributs = ctypes.windll.kernel32.GetFileAttributesW(str(fichier))
    if attributs == -1:
        return
    voulu = attributs | 2 if cache else attributs & ~2
    if voulu != attributs:
        ctypes.windll.kernel32.SetFileAttributesW(str(fichier), voulu)


def ecrire(photo: Path, etat: dict | None) -> None:
    """Enregistre (ou retire, `None`) l'état de cette photo ; les états des autres photos et leurs clés
    inconnues sont gardés ; rien n'est écrit si un état du dossier vient d'un schéma plus récent."""
    fichier = _fichier(photo)
    contenu = dict(_lire_dossier(fichier))
    anciens = sorted({int(valeur.get("schema", 1)) for valeur in contenu.values() if isinstance(valeur, dict)})
    if anciens and anciens[-1] > SCHEMA:
        raise EtatTropRecent(f"{fichier} : schéma {anciens[-1]} > {SCHEMA}")
    if anciens and anciens[0] < SCHEMA and fichier.is_file():
        sauvegarde = fichier.with_name(f"{FICHIER}.v{anciens[0]}.bak")
        if not sauvegarde.exists():
            sauvegarde.write_bytes(fichier.read_bytes())
    if etat is None:
        contenu.pop(Path(photo).name, None)
    else:
        contenu[Path(photo).name] = etat
    if not contenu:
        fichier.unlink(missing_ok=True)
    else:
        temporaire = fichier.with_name(FICHIER + ".tmp")
        temporaire.write_text(json.dumps(contenu, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        if fichier.exists():
            _cacher(fichier, False)        # os.replace échoue sur un fichier caché sous Windows
        os.replace(temporaire, fichier)
        _cacher(fichier, True)
    with _verrou:
        _dossiers.pop(os.path.normcase(str(fichier)), None)

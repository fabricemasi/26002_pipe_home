"""Chargement du moteur natif PDFium (sans Qt).

Deux bibliothèques possibles, choisies UNE fois par processus :
- `fm_pdf/native/pdfium.dll` : build pdfium-binaries « V8 » (JavaScript + XFA), version épinglée
  `PINNED_BUILD` (même révision que les bindings ctypes de pypdfium2, générés pour cette version) ;
- à défaut, la DLL standard livrée par pypdfium2 (sans XFA ni JavaScript).

Les bindings ctypes de pypdfium2 (`pypdfium2_raw/bindings.py`, générés par ctypesgen) sont RÉUTILISÉS : leur
chargeur cherche `./pdfium.dll` à côté de `__file__` ; on exécute donc leur source dans un module dont
`__file__` pointe dans le dossier de la DLL choisie. On n'importe JAMAIS `pypdfium2` lui-même ici : son import
initialise sa propre DLL sur le fil courant (or PDFium doit être initialisé et utilisé sur UN seul fil, celui du
moteur, `worker.py`).
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import types

NATIVE_DIR = pathlib.Path(__file__).resolve().parent / "native"
PINNED_BUILD = 8076                     # chromium/8076 = pypdfium2 5.14.0
PINNED_SHA256 = "E7B054AD439290A0145299F777315597C0C0CA57D75768F4705E129D038057B4"   # pdfium-v8-win-x64.tgz
PINNED_URL = ("https://github.com/bblanchon/pdfium-binaries/releases/download/chromium/%d/pdfium-v8-win-x64.tgz"
              % PINNED_BUILD)

_STATE: dict = {}


class NativeUnavailable(RuntimeError):
    """Aucune bibliothèque PDFium utilisable."""


def _bindings_source() -> pathlib.Path:
    spec = importlib.util.find_spec("pypdfium2_raw")        # ne CHARGE pas le paquet
    if spec is None or not spec.submodule_search_locations:
        raise NativeUnavailable("pypdfium2 n'est pas installé (pip install pypdfium2==5.14.0)")
    return pathlib.Path(list(spec.submodule_search_locations)[0]) / "bindings.py"


def _read_flags(dll_dir: pathlib.Path) -> dict:
    """Options de compilation de la DLL (args.gn de pdfium-binaries), sinon déduites."""
    info = {"v8": False, "xfa": False, "build": None}
    args = dll_dir / "args.gn"
    if args.exists():
        text = args.read_text(encoding="utf-8", errors="replace")
        info["v8"] = "pdf_enable_v8 = true" in text
        info["xfa"] = "pdf_enable_xfa = true" in text
    ver = dll_dir / "VERSION"
    if ver.exists():
        for line in ver.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("BUILD="):
                try:
                    info["build"] = int(line.split("=", 1)[1])
                except ValueError:
                    pass
    vj = dll_dir / "version.json"                     # DLL de pypdfium2
    if vj.exists() and info["build"] is None:
        try:
            data = json.loads(vj.read_text(encoding="utf-8"))
            info["build"] = data.get("build")
            flags = data.get("flags") or []
            info["v8"] = "V8" in flags
            info["xfa"] = "XFA" in flags
        except (OSError, ValueError):
            pass
    return info


def candidates() -> list[pathlib.Path]:
    """Dossiers de DLL dans l'ordre de préférence (variable FM_PDF_PDFIUM_DIR pour forcer)."""
    out = []
    forced = os.environ.get("FM_PDF_PDFIUM_DIR")
    if forced:
        out.append(pathlib.Path(forced))
    if os.environ.get("FM_PDF_NO_XFA") != "1":
        out.append(NATIVE_DIR)
    try:
        out.append(_bindings_source().parent)
    except NativeUnavailable:
        pass
    return [p for p in out if (p / "pdfium.dll").exists()]


def load():
    """Module ctypes des fonctions PDFium (chargé une fois) ; `info()` dit lequel."""
    if "lib" in _STATE:
        return _STATE["lib"]
    src = _bindings_source()
    dirs = candidates()
    if not dirs:
        raise NativeUnavailable("aucune pdfium.dll trouvée")
    dll_dir = dirs[0]
    mod = types.ModuleType("fm_pdf._pdfium_c")
    mod.__file__ = str(dll_dir / "bindings.py")              # le chargeur résout ./pdfium.dll depuis ici
    code = compile(src.read_text(encoding="utf-8"), str(src), "exec")
    exec(code, mod.__dict__)
    sys.modules["fm_pdf._pdfium_c"] = mod
    flags = _read_flags(dll_dir)
    _STATE["lib"] = mod
    _STATE["info"] = {"dir": str(dll_dir), "bundled": dll_dir == NATIVE_DIR, **flags}
    return mod


def info() -> dict:
    """{'dir', 'bundled', 'v8', 'xfa', 'build'} de la DLL chargée (charge si besoin)."""
    load()
    return dict(_STATE["info"])


def xfa_engine_installed() -> bool:
    return (NATIVE_DIR / "pdfium.dll").exists() and _read_flags(NATIVE_DIR)["xfa"]

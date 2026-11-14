"""Compilation CIBLÉE du moteur audio natif (pas un build global du dépôt).

    python fm_audio_engine/build.py          compile si une source a changé
    python fm_audio_engine/build.py --force  recompile

Chaîne : MSVC Build Tools 2022 (vcvars64.bat), C++20, x64, /O2.
Sortie : fm_audio_engine/bin/fmz_audio_engine.exe (non versionné, reconstructible).

SDK tiers FACULTATIFS (téléchargés avec l'accord de l'utilisateur dans fm_audio_engine/third_party/, jamais
versionnés) :
- ASIO 2.3.4 (Steinberg, variante GPLv3) : third_party/ASIOSDK -> backend ASIO (FMZ_ASIO) ;
- VST3 3.8.1 (Steinberg, MIT) : third_party/vst3sdk -> hôte de plugins (FMZ_VST3).
Absent = moteur compilé sans cette fonction (message clair à l'exécution). Les sources d'un SDK sont
compilées UNE fois dans bin/sdk_<nom>_<empreinte>.lib, puis liées au moteur. FMZ_AUDIO_SANS_SDK=1 : aucun SDK.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NATIVE = HERE / "native"
THIRD = HERE / "third_party"
BIN = HERE / "bin"
EXE = BIN / "fmz_audio_engine.exe"
STAMP = BIN / "build_stamp.json"
LIBS = ["ole32.lib", "avrt.lib", "winmm.lib", "user32.lib"]
FLAGS = ["/nologo", "/std:c++20", "/O2", "/EHsc", "/utf-8", "/W3", "/MT", "/DUNICODE", "/D_UNICODE",
         "/D_CRT_SECURE_NO_WARNINGS"]


def _asio_sdk() -> dict | None:
    root = THIRD / "ASIOSDK"
    if not (root / "common" / "asio.cpp").exists():
        return None
    return {"name": "asio", "define": "FMZ_ASIO",
            "includes": [root / "common", root / "host", root / "host" / "pc"],
            "sources": [root / "common" / "asio.cpp", root / "host" / "asiodrivers.cpp", root / "host" / "pc" / "asiolist.cpp"],
            # le SDK appelle les API Windows en char : PAS de /DUNICODE pour ses sources
            "flags": ["/nologo", "/std:c++20", "/O2", "/EHsc", "/W0", "/MT", "/D_CRT_SECURE_NO_WARNINGS"],
            "libs": ["advapi32.lib"]}


def _vst3_sdk() -> dict | None:
    root = THIRD / "vst3sdk"
    if not (root / "pluginterfaces" / "base" / "funknown.cpp").exists():
        return None
    sys.path.insert(0, str(HERE))
    try:
        from vst3_sources import vst3_spec
    except ImportError:
        return None
    finally:
        sys.path.pop(0)
    return vst3_spec(root)


def sdks() -> list:
    if os.environ.get("FMZ_AUDIO_SANS_SDK"):
        return []
    return [s for s in (_asio_sdk(), _vst3_sdk()) if s]


def _sdk_digest(sdk: dict) -> str:
    h = hashlib.sha256()
    for p in sdk["sources"]:
        h.update(str(p).encode())
        h.update(Path(p).read_bytes())
    h.update(" ".join(sdk["flags"] + sdk.get("defines", [])).encode())
    return h.hexdigest()[:16]


def sources_digest() -> str:
    h = hashlib.sha256()
    for s in sdks():
        h.update(s["define"].encode())
        h.update(_sdk_digest(s).encode())
    for p in sorted(NATIVE.glob("*.*")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    h.update(" ".join(FLAGS + LIBS).encode())
    return h.hexdigest()


def find_vcvars() -> Path | None:
    roots = [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio",
             Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft Visual Studio"]
    for root in roots:
        for year in ("2022", "2019"):
            for ed in ("BuildTools", "Community", "Professional", "Enterprise"):
                p = root / year / ed / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
                if p.exists():
                    return p
    return None


def up_to_date() -> bool:
    if not EXE.exists() or not STAMP.exists():
        return False
    try:
        return json.loads(STAMP.read_text("utf-8")).get("digest") == sources_digest()
    except (OSError, ValueError):
        return False


def _run_bat(name: str, cmd: str, vc: Path) -> subprocess.CompletedProcess:
    bat = BIN / name
    bat.write_text(f'@echo off\r\ncall "{vc}" >nul && {cmd}\r\n', encoding="mbcs")
    return subprocess.run(["cmd", "/d", "/c", str(bat)], capture_output=True, text=True, encoding="mbcs", errors="replace")


def _errors(r: subprocess.CompletedProcess) -> str:
    out = r.stdout + r.stderr
    lines = [l for l in out.splitlines() if "error" in l.lower() or "erreur" in l.lower()]
    return "\n".join(lines[:15] or out.splitlines()[-40:])


def build_sdk_lib(sdk: dict, vc: Path) -> Path:
    """bin/sdk_<nom>_<empreinte>.lib, compilée une seule fois."""
    lib = BIN / f"sdk_{sdk['name']}_{_sdk_digest(sdk)}.lib"
    if lib.exists():
        return lib
    obj = BIN / "obj" / f"sdk_{sdk['name']}"
    obj.mkdir(parents=True, exist_ok=True)
    for old in obj.glob("*.obj"):
        old.unlink()
    inc = " ".join(f'/I"{p}"' for p in sdk["includes"])
    defs = " ".join(sdk.get("defines", []))
    srcs = " ".join(f'"{p}"' for p in sdk["sources"])
    cmd = (f'cl /c /MP {" ".join(sdk["flags"])} {defs} {inc} /Fo"{obj}\\\\" {srcs} '
           f'&& lib /nologo /OUT:"{lib}" "{obj}\\*.obj"')
    r = _run_bat(f"_build_sdk_{sdk['name']}.bat", cmd, vc)
    if r.returncode != 0 or not lib.exists():
        raise RuntimeError(f"compilation du SDK {sdk['name']} échouée :\n" + _errors(r))
    return lib


TEST_PLUGINS = BIN / "test_plugins"


def build_test_plugins() -> dict:
    """Plugins VST3 de TEST (native/test_plugins, compilés depuis le SDK) : {"good", "crash", "hang": chemin}.
    {} si le SDK VST3 est absent. Recompilés seulement si leur source ou le SDK change."""
    root = THIRD / "vst3sdk"
    if os.environ.get("FMZ_AUDIO_SANS_SDK") or not (root / "pluginterfaces" / "base" / "funknown.cpp").exists():
        return {}
    sys.path.insert(0, str(HERE))
    try:
        from vst3_sources import plugin_spec
    finally:
        sys.path.pop(0)
    spec = plugin_spec(root)
    src = NATIVE / "test_plugins" / "fmz_test_plugins.cpp"
    h = hashlib.sha256(src.read_bytes() + _sdk_digest(spec).encode()).hexdigest()[:16]
    out = {"good": TEST_PLUGINS / "FMZTest.vst3", "crash": TEST_PLUGINS / "FMZTestCrash.vst3",
           "hang": TEST_PLUGINS / "FMZTestHang.vst3"}
    stamp = TEST_PLUGINS / "stamp.txt"
    if all(p.exists() for p in out.values()) and stamp.exists() and stamp.read_text("utf-8") == h:
        return out
    vc = find_vcvars()
    if vc is None:
        raise RuntimeError("MSVC introuvable (vcvars64.bat)")
    BIN.mkdir(exist_ok=True)
    TEST_PLUGINS.mkdir(exist_ok=True)
    lib = build_sdk_lib(spec, vc)
    inc = " ".join(f'/I"{p}"' for p in spec["includes"])
    for key, extra in (("good", ""), ("crash", "/DFMZ_BAD_CRASH"), ("hang", "/DFMZ_BAD_HANG")):
        obj = BIN / "obj" / f"test_plugin_{key}"
        obj.mkdir(parents=True, exist_ok=True)
        cmd = (f'cl /LD {" ".join(spec["flags"])} {extra} {inc} /Fo"{obj}\\\\" "{src}" /Fe"{out[key]}" '
               f'/link "{lib}" {" ".join(spec["libs"])}')
        r = _run_bat(f"_build_test_plugin_{key}.bat", cmd, vc)
        if r.returncode != 0 or not out[key].exists():
            raise RuntimeError(f"compilation du plugin de test {key} échouée :\n" + _errors(r))
    stamp.write_text(h, "utf-8")
    return out


def build(force: bool = False) -> Path:
    if not force and up_to_date():
        return EXE
    vc = find_vcvars()
    if vc is None:
        raise RuntimeError("MSVC introuvable (vcvars64.bat) : installer les Build Tools 2022 (C++)")
    BIN.mkdir(exist_ok=True)
    obj = BIN / "obj"
    obj.mkdir(exist_ok=True)
    tmp = BIN / "fmz_audio_engine.new.exe"
    extra, libs = [], list(LIBS)
    for sdk in sdks():
        libs.append(f'"{build_sdk_lib(sdk, vc)}"')
        libs += sdk.get("libs", [])
        extra.append("/D" + sdk["define"])
        extra += [f'/I"{p}"' for p in sdk["includes"]]
        extra += sdk.get("defines", [])
    cmd = (f'cl {" ".join(FLAGS + extra)} /Fo"{obj}\\\\" "{NATIVE / "main.cpp"}" '
           f'/Fe"{tmp}" /link {" ".join(libs)}')
    r = _run_bat("_build.bat", cmd, vc)
    if r.returncode != 0 or not tmp.exists():
        raise RuntimeError("compilation du moteur échouée :\n" + _errors(r))
    # remplacement : un moteur en cours d'exécution (appli ouverte) verrouille son fichier contre l'effacement
    # mais pas contre le renommage : l'ancien est mis de côté (bin/old/), effacé à un build suivant une fois libre
    old_dir = BIN / "old"
    for old in old_dir.glob("*.exe") if old_dir.exists() else ():
        try:
            old.unlink()
        except OSError:
            pass
    try:
        os.replace(tmp, EXE)
    except OSError:
        try:
            import time
            old_dir.mkdir(exist_ok=True)
            os.replace(EXE, old_dir / f"fmz_audio_engine.{int(time.time())}.exe")
            os.replace(tmp, EXE)
        except OSError as e:
            raise RuntimeError(f"moteur en cours d'utilisation, binaire neuf laissé dans {tmp} : {e}")
    STAMP.write_text(json.dumps({"digest": sources_digest(), "sdks": [s["name"] for s in sdks()]}), "utf-8")
    return EXE


if __name__ == "__main__":
    try:
        path = build(force="--force" in sys.argv)
    except RuntimeError as e:
        print(e)
        sys.exit(1)
    print(path)

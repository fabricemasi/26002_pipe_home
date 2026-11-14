"""Sources du SDK VST3 3.8.1 (Steinberg, MIT) compilées par build.py : côté HÔTE (lié au moteur) et côté
PLUGIN (plugins de test du dépôt, fm_audio_engine/native/test_plugins/). Le SDK est dans
fm_audio_engine/third_party/vst3sdk (pluginterfaces, base, public.sdk : dépôts officiels, tag v3.8.1_build_84)."""
from __future__ import annotations

from pathlib import Path

FLAGS = ["/nologo", "/std:c++17", "/O2", "/EHsc", "/W0", "/MT", "/utf-8", "/DUNICODE", "/D_UNICODE",
         "/D_CRT_SECURE_NO_WARNINGS", "/DRELEASE=1", "/DNOMINMAX"]

_COMMON = [
    "pluginterfaces/base/conststringtable.cpp", "pluginterfaces/base/coreiids.cpp",
    "pluginterfaces/base/funknown.cpp", "pluginterfaces/base/ustring.cpp",
    "base/source/baseiids.cpp", "base/source/fbuffer.cpp", "base/source/fdebug.cpp", "base/source/fobject.cpp",
    "base/source/fstreamer.cpp", "base/source/fstring.cpp", "base/source/updatehandler.cpp",
    "base/thread/source/fcondition.cpp", "base/thread/source/flock.cpp",
    "public.sdk/source/common/commoniids.cpp", "public.sdk/source/common/commonstringconvert.cpp",
    "public.sdk/source/common/memorystream.cpp", "public.sdk/source/common/threadchecker_win32.cpp",
    "public.sdk/source/vst/vstinitiids.cpp",
    "public.sdk/source/vst/utility/stringconvert.cpp",
]

_HOST = [
    "public.sdk/source/vst/hosting/module.cpp", "public.sdk/source/vst/hosting/module_win32.cpp",
    "public.sdk/source/vst/hosting/hostclasses.cpp", "public.sdk/source/vst/hosting/pluginterfacesupport.cpp",
    "public.sdk/source/vst/hosting/plugprovider.cpp", "public.sdk/source/vst/hosting/connectionproxy.cpp",
    "public.sdk/source/vst/hosting/eventlist.cpp", "public.sdk/source/vst/hosting/parameterchanges.cpp",
    "public.sdk/source/vst/hosting/processdata.cpp",
    "public.sdk/source/vst/moduleinfo/moduleinfoparser.cpp",
]

_PLUGIN = [
    "public.sdk/source/main/dllmain.cpp", "public.sdk/source/main/pluginfactory.cpp",
    "public.sdk/source/main/moduleinit.cpp",
    "public.sdk/source/common/pluginview.cpp",
    "public.sdk/source/vst/vstaudioeffect.cpp", "public.sdk/source/vst/vstbus.cpp",
    "public.sdk/source/vst/vstcomponent.cpp", "public.sdk/source/vst/vstcomponentbase.cpp",
    "public.sdk/source/vst/vsteditcontroller.cpp", "public.sdk/source/vst/vstparameters.cpp",
    "public.sdk/source/vst/vstsinglecomponenteffect.cpp",
]


def vst3_spec(root: Path) -> dict:
    """Bibliothèque HÔTE liée au moteur (FMZ_VST3)."""
    root = Path(root)
    return {"name": "vst3", "define": "FMZ_VST3", "includes": [root], "flags": list(FLAGS),
            "defines": ["/DRELEASE=1", "/DNOMINMAX"],
            "sources": [root / s for s in _COMMON + _HOST], "libs": ["shell32.lib", "ole32.lib"]}


def plugin_spec(root: Path) -> dict:
    """Bibliothèque PLUGIN (plugins de test compilés depuis le SDK)."""
    root = Path(root)
    return {"name": "vst3plug", "define": "", "includes": [root], "flags": list(FLAGS), "defines": [],
            "sources": [root / s for s in _COMMON + _PLUGIN], "libs": ["ole32.lib", "user32.lib"]}

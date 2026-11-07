"""Installe le moteur PDF « V8 + XFA » du module PDF : `fm_pdf/native/pdfium.dll` (+ licences, args.gn, VERSION).

Source : pdfium-binaries (https://github.com/bblanchon/pdfium-binaries), release `chromium/<PINNED_BUILD>`, archive
`pdfium-v8-win-x64.tgz`, compilée par leur intégration continue GitHub ; l'empreinte SHA-256 est vérifiée contre
celle épinglée dans `fm_pdf/native.py` (identique à celle publiée par GitHub pour cet élément de la release).
La version est celle des bindings ctypes de pypdfium2 installé (5.14.0 = PDFium 156.0.8076).

    python tools/install_pdfium_xfa.py            # télécharge, vérifie, installe
    python tools/install_pdfium_xfa.py --check    # dit seulement si le moteur est installé
"""
from __future__ import annotations

import hashlib
import io
import pathlib
import sys
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fm_pdf import native  # noqa: E402


def install() -> int:
    print("Téléchargement :", native.PINNED_URL)
    with urllib.request.urlopen(native.PINNED_URL, timeout=120) as resp:
        blob = resp.read()
    digest = hashlib.sha256(blob).hexdigest().upper()
    if digest != native.PINNED_SHA256:
        print("EMPREINTE INATTENDUE : %s (attendu %s) — rien n'est installé." % (digest, native.PINNED_SHA256))
        return 2
    target = native.NATIVE_DIR
    (target / "licenses").mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            name = member.name.lstrip("./")
            if name == "bin/pdfium.dll":
                dest = target / "pdfium.dll"
            elif name in ("args.gn", "VERSION"):
                dest = target / name
            elif name == "LICENSE":
                dest = target / "licenses" / "pdfium-binaries.txt"
            elif name.startswith("licenses/") and member.isfile():
                dest = target / "licenses" / pathlib.Path(name).name
            else:
                continue
            data = tar.extractfile(member).read()
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
    print("Installé dans", target)
    return 0


def main(argv) -> int:
    if "--check" in argv:
        ok = native.xfa_engine_installed()
        print("moteur XFA installé" if ok else "moteur XFA ABSENT (python tools/install_pdfium_xfa.py)")
        return 0 if ok else 1
    return install()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

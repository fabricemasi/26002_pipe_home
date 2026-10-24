"""Inventaire du presse-papiers Windows (pour etudier ce que Miro y place).

Usage : copier quelque chose dans Miro (post-it, forme, texte...), puis lancer
    python tools/clipboard_formats.py [dossier]
Ecrit dans `dossier` (par defaut `clipboard_dump/` a cote du script) un fichier par format (`.bin`, et `.txt`
pour les formats texte) et `formats.txt` (liste, tailles). Rien n'est envoye nulle part."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("clipboard_dump")
    out.mkdir(parents=True, exist_ok=True)
    mime = app.clipboard().mimeData()
    lines = []
    for n, fmt in enumerate(mime.formats()):
        data = bytes(mime.data(fmt))
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", fmt)[:60]
        (out / f"{n:02d}_{safe}.bin").write_bytes(data)
        if fmt.startswith("text/") or "html" in fmt.lower():
            (out / f"{n:02d}_{safe}.txt").write_text(data.decode("utf-8", "replace"), encoding="utf-8")
        lines.append(f"{fmt}\t{len(data)} octets")
    lines.append(f"image : {mime.hasImage()}  texte : {mime.hasText()}  html : {mime.hasHtml()}  urls : {mime.hasUrls()}")
    (out / "formats.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Images glissees depuis les AUTRES logiciels (navigateur web, bureau / explorateur de Windows) sur le board.

Demande de l'utilisateur (2026-11-02) : glisser une image directement sur le board au lieu de passer par le
copier-coller. Ce qu'apporte un glisser, par ordre de preference (`image_sources`) :
1. des FICHIERS locaux (explorateur, bureau) : copies dans le dossier du board (`BoardView.add_image_files`) ;
2. les OCTETS d'une image dans un format declare (`image/png`, `image/jpeg`…, « PNG » de Windows) : gardes tels
   quels (pas de reencodage) ;
3. une URL d'image (`<img src>` du HTML glisse par le navigateur, sinon la liste d'URL) : TELECHARGEE dans un fil
   (`fetch`, jamais sur le fil de l'interface), l'image se pose a l'arrivee ; `data:` decodee sur place ;
4. l'image du glisser (`hasImage`, bitmap de Windows : sans transparence) : encodee en PNG. Sert aussi de repli
   quand le telechargement echoue (page protegee, hors ligne).
Le seul acces reseau du board, et seulement sur ce geste de l'utilisateur."""
from __future__ import annotations

import base64
import re
import threading
import urllib.parse
import urllib.request

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Signal
from PySide6.QtGui import QImage, QImageReader

MAX_BYTES = 100 << 20               # image telechargee : au plus 100 Mo
TIMEOUT_S = 20.0
RAW_FORMATS = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/tiff",
               'application/x-qt-windows-mime;value="PNG"', 'application/x-qt-windows-mime;value="JFIF"',
               'application/x-qt-windows-mime;value="FileContents"')    # fichier virtuel (navigateur) : vide si illisible
SUFFIXES = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "gif": ".gif", "webp": ".webp", "bmp": ".bmp",
            "tiff": ".tif", "tif": ".tif"}
_IMG_SRC = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*(["'])(.*?)\1""", re.I | re.S)


def accepts(mime) -> bool:
    """Le glisser peut-il apporter une image ? (survol : rien n'est lu en entier)"""
    if mime.hasUrls() or mime.hasImage():
        return True
    if mime.hasHtml() and "<img" in mime.html().lower():
        return True
    return any(mime.hasFormat(f) for f in RAW_FORMATS)


def image_bytes(data: bytes) -> tuple[bytes, str, int, int] | None:
    """(octets, suffixe, largeur, hauteur) si `data` est une image lisible par Qt, sinon None. Format courant :
    octets gardes ; autre format lisible (SVG, AVIF…) : reencode en PNG."""
    if not data:
        return None
    array = QByteArray(data)
    buffer = QBuffer(array)
    buffer.open(QIODevice.ReadOnly)
    reader = QImageReader(buffer)
    fmt = bytes(reader.format()).decode("ascii", "ignore").lower()
    size = reader.size()
    if fmt in SUFFIXES and size.isValid() and size.width() > 0 and size.height() > 0:
        return data, SUFFIXES[fmt], size.width(), size.height()
    image = QImage.fromData(array)
    if image.isNull():
        return None
    return png_bytes(image), ".png", image.width(), image.height()


def png_bytes(image: QImage) -> bytes:
    out = QBuffer()
    out.open(QIODevice.WriteOnly)
    image.save(out, "PNG")
    return bytes(out.data())


def _remote_urls(mime) -> list[str]:
    urls = []
    if mime.hasHtml():
        urls += [html_unescape(m.group(2)) for m in _IMG_SRC.finditer(mime.html())]
    if mime.hasUrls():
        urls += [u.toString() for u in mime.urls() if not u.isLocalFile()]
    seen, out = set(), []
    for url in urls:
        url = url.strip()
        if url.lower().startswith(("http://", "https://", "data:image/")) and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def html_unescape(text: str) -> str:
    import html
    return html.unescape(text)


def image_sources(mime) -> dict:
    """Ce que le glisser apporte : {"files": [Path], "raw": (octets, suffixe, l, h) | None, "urls": [str],
    "image": QImage | None}. L'image du glisser est COPIEE (les donnees du glisser disparaissent apres le depot)."""
    from pathlib import Path
    files = [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()] if mime.hasUrls() else []
    raw = None
    for fmt in RAW_FORMATS:
        if mime.hasFormat(fmt):
            raw = image_bytes(bytes(mime.data(fmt).data()))
            if raw is not None:
                break
    image = None
    if mime.hasImage():
        candidate = QImage(mime.imageData())
        if not candidate.isNull():
            image = candidate.copy()
    return {"files": files, "raw": raw, "urls": _remote_urls(mime), "image": image}


def decode_data_url(url: str) -> bytes | None:
    """Octets d'une URL `data:image/...;base64,...` (None si illisible)."""
    head, _, payload = url.partition(",")
    try:
        if ";base64" in head.lower():
            return base64.b64decode(payload, validate=False)
        return urllib.parse.unquote_to_bytes(payload)
    except (ValueError, TypeError):
        return None


def download(url: str) -> bytes:
    """Telechargement (fil de fond) : refuse au-dela de MAX_BYTES. Leve OSError / ValueError en cas d'echec."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                                   "Accept": "image/*,*/*;q=0.5"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:      # noqa: S310 - http(s) seulement
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("image trop lourde")
    return data


class _Notifier(QObject):
    done = Signal(object, object)           # (rappel, octets | None), recu sur le fil de l'interface


_NOTIFIER = None


def fetch(urls: list[str], callback):
    """Premiere URL qui donne une image, telechargee dans un fil ; `callback(resultat | None)` sur le fil de
    l'interface, resultat = `image_bytes`."""
    global _NOTIFIER
    if _NOTIFIER is None:
        _NOTIFIER = _Notifier()
        _NOTIFIER.done.connect(lambda cb, result: cb(result))

    def work():
        result = None
        for url in urls:
            try:
                data = decode_data_url(url) if url.lower().startswith("data:") else download(url)
            except Exception:                                # noqa: BLE001 - reseau, page protegee : URL suivante
                continue
            result = image_bytes(data) if data else None
            if result is not None:
                break
        _NOTIFIER.done.emit(callback, result)
    threading.Thread(target=work, name="board-drop", daemon=True).start()

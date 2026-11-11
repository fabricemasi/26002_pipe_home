"""Module CAD du board : envoi des entites vers PHOTOSHOP (demande de l'utilisateur).

Trois sorties (commandes PHOTOSHOP / PNGOUT / SVGOUT, clic droit > Photoshop, bouton de la barre « Gestion ») :
- « open » (par defaut) : PNG haute definition a fond TRANSPARENT des entites, ouvert dans Photoshop ;
- « save » : enregistrer en PNG ou en PSD (un calque transparent, `write_psd`) ;
- « vector » : enregistrer en PDF ou SVG VECTORIEL (Photoshop ouvre le PDF en choisissant la resolution).
Les entites exportees : la SELECTION, sinon toutes les entites CAD visibles. Rendu = celui de l'export du board
(fm_board.export : vraies epaisseurs, ni selection ni grille).

Photoshop est cherche dans « App Paths » (registre Windows) puis dans Program Files\\Adobe ; introuvable : le
fichier s'ouvre dans l'application associee (message)."""
from __future__ import annotations

import os
import re
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

LONG_SIDE = 4000.0                  # cote le plus long vise pour l'image (px), plafonne par fm_board.export


# -- PSD : un calque RGBA (compression RLE / PackBits) + image fusionnee sur blanc --

_RUN = re.compile(rb"(.)\1{2,}", re.S)


def _packbits(row: bytes) -> bytes:
    out = bytearray()

    def literal(chunk):
        for i in range(0, len(chunk), 128):
            part = chunk[i:i + 128]
            out.append(len(part) - 1)
            out.extend(part)

    pos = 0
    for match in _RUN.finditer(row):
        start, end = match.span()
        if start > pos:
            literal(row[pos:start])
        byte, n = row[start], end - start
        while n > 0:
            k = min(n, 128)
            out.extend(bytes((0, byte)) if k == 1 else bytes(((257 - k) & 0xFF, byte)))
            n -= k
        pos = end
    if pos < len(row):
        literal(row[pos:])
    return bytes(out)


def _rle_channel(plane: bytes, width: int, height: int) -> tuple[bytes, bytes]:
    """(comptes d'octets des lignes, donnees compressees) d'un plan."""
    rows = [_packbits(plane[y * width:(y + 1) * width]) for y in range(height)]
    return b"".join(struct.pack(">H", len(r)) for r in rows), b"".join(rows)


def _planes(image: QImage, fmt) -> list[bytes]:
    data = image.convertToFormat(fmt)
    raw = bytes(data.constBits())[:data.bytesPerLine() * data.height()]
    return [raw[i::4] for i in range(4)]            # 4 octets par pixel, lignes jamais completees


def _thumbnail_resource(flat: QImage) -> bytes:
    """Ressource 1036 (vignette JPEG) : l'apercu du navigateur lit les PSD par elle (preview_services.images)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    thumb = flat.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB888)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    thumb.save(buffer, "JPEG", 85)
    jpeg = bytes(data)
    w, h = thumb.width(), thumb.height()
    row = (w * 24 + 31) // 32 * 4
    payload = struct.pack(">IIIIIIHH", 1, w, h, row, row * h, len(jpeg), 24, 1) + jpeg
    return (b"8BIM" + struct.pack(">H", 1036) + b"\0\0" + struct.pack(">I", len(payload)) + payload
            + b"\0" * (len(payload) % 2))


def write_psd(image: QImage, path) -> Path:
    """`image` en PSD : un calque « CAD » a fond transparent (Photoshop l'ouvre tel quel) + l'image fusionnee
    sur blanc (apercus des autres logiciels)."""
    width, height = image.width(), image.height()
    r, g, b, a = _planes(image, QImage.Format_RGBA8888)
    layer_data, channel_info = [], []
    for cid, plane in ((-1, a), (0, r), (1, g), (2, b)):
        counts, packed = _rle_channel(plane, width, height)
        block = struct.pack(">H", 1) + counts + packed
        layer_data.append(block)
        channel_info.append(struct.pack(">hI", cid, len(block)))
    name = b"CAD"
    name_block = bytes((len(name),)) + name
    name_block += b"\0" * (-len(name_block) % 4)
    extra = struct.pack(">II", 0, 0) + name_block
    record = (struct.pack(">iiiiH", 0, 0, height, width, 4) + b"".join(channel_info) + b"8BIMnorm"
              + bytes((255, 0, 0, 0)) + struct.pack(">I", len(extra)) + extra)
    layer_info = struct.pack(">h", 1) + record + b"".join(layer_data)
    layer_info += b"\0" * (len(layer_info) % 2)
    layer_section = struct.pack(">I", len(layer_info)) + layer_info + struct.pack(">I", 0)
    flat = QImage(width, height, QImage.Format_RGBX8888)
    flat.fill(Qt.white)
    painter = QPainter(flat)
    painter.drawImage(0, 0, image)
    painter.end()
    counts, packed = [], []
    for plane in _planes(flat, QImage.Format_RGBX8888)[:3]:
        c, p = _rle_channel(plane, width, height)
        counts.append(c)
        packed.append(p)
    resources = _thumbnail_resource(flat)
    with open(path, "wb") as out:
        out.write(b"8BPS" + struct.pack(">H6xHIIHH", 1, 3, height, width, 8, 3))
        out.write(struct.pack(">I", 0))                 # donnees du mode colorimetrique
        out.write(struct.pack(">I", len(resources)) + resources)
        out.write(struct.pack(">I", len(layer_section)) + layer_section)
        out.write(struct.pack(">H", 1) + b"".join(counts) + b"".join(packed))
    return Path(path)


# -- Photoshop --

def photoshop_exe() -> str | None:
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Photoshop.exe") as key:
                value, _ = winreg.QueryValueEx(key, None)
            if value and Path(value).is_file():
                return str(value)
        except OSError:
            pass
    root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Adobe"
    try:
        found = sorted((p for p in root.glob("Adobe Photoshop*/Photoshop.exe") if p.is_file()), reverse=True)
    except OSError:
        found = []
    return str(found[0]) if found else None


def open_in_photoshop(path) -> bool:
    """Ouvre `path` dans Photoshop (deja lance : dans la meme instance). False : application associee."""
    exe = photoshop_exe()
    if exe is not None:
        subprocess.Popen([exe, str(path)], close_fds=True)
        return True
    os.startfile(str(path))                             # noqa: S606 - fichier que l'on vient d'ecrire
    return False


# -- commandes --

def _items(ctl) -> list:
    from .cad_items import CadLineItem
    items = ctl.selection()
    if items:
        return items
    return [i for i in ctl.scene.board_items() if isinstance(i, CadLineItem) and i.isVisible()]


def render(ctl, items) -> QImage:
    from fm_board import export
    source = export.items_source(items)
    scale = max(2.0, LONG_SIDE / max(1.0, source.width(), source.height()))
    return export.render_items(ctl.scene, items, scale, transparent=True)


def _zone_source(zone):
    from PySide6.QtCore import QRectF
    x0, y0, x1, y1 = zone
    return QRectF(x0, -y1, x1 - x0, y1 - y0)                    # scene : Y vers le bas


def render_zone(scene, items, zone, width: int, height: int) -> QImage:
    """Image `width` x `height` (fond transparent) des SEULS `items`, cadree EXACTEMENT sur la zone document
    [x0, y0, x1, y1] : ni marge ni cadre (clic droit > Exporter, cad_commands_export)."""
    from PySide6.QtCore import QRectF
    from fm_board.export import _render_only
    image = QImage(int(width), int(height), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        target = QRectF(0, 0, width, height)
        painter.setClipRect(target)
        _render_only(scene, items, painter, target, _zone_source(zone), True, Qt.IgnoreAspectRatio)
    finally:
        painter.end()
    return image


def write_zone_vector(scene, items, zone, width: int, height: int, path) -> Path:
    """Les SEULS `items` en VECTORIEL (SVG ou PDF selon l'extension), fond transparent, cadres EXACTEMENT sur la
    zone : SVG de `width` x `height` px ; PDF d'une page de `width` x `height` points (Photoshop l'ouvre a ces
    pixels a 72 ppp)."""
    from PySide6.QtCore import QMarginsF, QRectF, QSize, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter
    from fm_board.export import _render_only
    path = Path(path)
    if path.suffix.lower() == ".svg":
        from PySide6.QtSvg import QSvgGenerator
        device = QSvgGenerator()
        device.setFileName(str(path))
        device.setSize(QSize(int(width), int(height)))
        device.setViewBox(QRectF(0, 0, width, height))
        device.setTitle(path.stem)
        target = QRectF(0, 0, width, height)
    else:
        device = QPdfWriter(str(path))
        device.setResolution(72)
        device.setPageSize(QPageSize(QSizeF(width, height), QPageSize.Point))
        device.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Point)
        device.setTitle(path.stem)
        target = None
    painter = QPainter(device)
    try:
        if target is None:
            target = QRectF(0, 0, device.width(), device.height())
        painter.setClipRect(target)
        _render_only(scene, items, painter, target, _zone_source(zone), True, Qt.IgnoreAspectRatio)
    finally:
        painter.end()
    if path.suffix.lower() == ".svg":                   # Qt ecrit la taille en mm : en PIXELS (Photoshop, navigateurs)
        text = path.read_text(encoding="utf-8")
        text = re.sub(r'(<svg\b[^>]*?)width="[^"]*"\s+height="[^"]*"',
                      lambda m: f'{m.group(1)}width="{int(width)}px" height="{int(height)}px"', text, count=1)
        path.write_text(text, encoding="utf-8")
    return path


def _stem(ctl) -> str:
    base = getattr(ctl.pane, "path", None) or getattr(ctl.pane, "source", None)
    return f"{Path(base).stem}_cad" if base else "cad"


def _ask_path(ctl, title: str, filters: tuple) -> Path | None:
    from PySide6.QtWidgets import QFileDialog
    base = getattr(ctl.pane, "path", None) or getattr(ctl.pane, "source", None)
    folder = Path(base).parent if base else Path.home()
    first = filters[0][1]
    target, chosen = QFileDialog.getSaveFileName(ctl.pane, title, str(folder / f"{_stem(ctl)}{first}"),
                                                 ";;".join(f"{label} (*{ext})" for label, ext in filters))
    if not target:
        return None
    target = Path(target)
    suffixes = [ext for _label, ext in filters]
    if target.suffix.lower() not in suffixes:           # nom tape sans extension : celle du filtre
        ext = next((ext for label, ext in filters if chosen.startswith(label)), first)
        target = target.with_suffix(ext)
    return target


def run(ctl, action: str = "open"):
    items = _items(ctl)
    if not items:
        ctl.message("Rien à exporter : aucune entité CAD.", error=True)
        return
    what = f"{len(items)} entité(s)" + ("" if ctl.selection() else " (tout le dessin)")
    try:
        if action == "vector":
            target = _ask_path(ctl, "Exporter en vectoriel", (("Document PDF vectoriel", ".pdf"),
                                                              ("Image SVG vectorielle", ".svg")))
            if target is None:
                return
            from fm_board import export
            export.export_items_vector(ctl.scene, items, target)
            ctl.message(f"{what} exportée(s) en vectoriel : {target.name}")
            return
        if action == "save":
            target = _ask_path(ctl, "Enregistrer pour Photoshop", (("Image PNG transparente", ".png"),
                                                                   ("Document Photoshop", ".psd")))
            if target is None:
                return
            image = render(ctl, items)
            if target.suffix.lower() == ".psd":
                write_psd(image, target)
            elif not image.save(str(target)):
                raise OSError(f"Impossible d'écrire {target}")
            ctl.message(f"{what} enregistrée(s) : {target.name}")
            return
        image = render(ctl, items)
        folder = Path(tempfile.gettempdir()) / "pipeline_photoshop"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{_stem(ctl)}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        if not image.save(str(target)):
            raise OSError(f"Impossible d'écrire {target}")
        if open_in_photoshop(target):
            ctl.message(f"{what} envoyée(s) vers Photoshop.")
        else:
            ctl.message("Photoshop introuvable : image ouverte avec l'application associée.", error=True)
    except Exception as exc:                            # noqa: BLE001 - message a l'utilisateur
        ctl.message(f"Export impossible : {exc}", error=True)

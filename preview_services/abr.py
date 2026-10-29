"""Lecture des brosses Photoshop et planche des pointes.

Carte et pièges : docs/agents/apercus.md.
"""

import math
import re
import struct
from pathlib import Path
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient

# Brosses Photoshop (.abr) : planche des pointes ECHANTILLONNEES (image en niveaux de gris
# stockee dans le fichier). Parseur maison, aucune dependance ; meme lecture que GIMP
# (gimpbrush-load.c) : versions 1/2 (anciennes) et 6/7/10 (section 8BIM "samp").
_ABR_MAX_BRUSHES = 48        # au-dela, la planche serait illisible en vignette

_ABR_SAMPLE_MAX_DIM = 256    # chaque pointe est reduite des sa lecture (memoire bornee)

def _abr_unpackbits(f, height: int, row_bytes: int) -> bytes:
    """Echantillon compresse : longueur de chaque ligne (uint16) puis lignes en PackBits."""
    lengths = struct.unpack(f">{height}H", f.read(2 * height))
    out = bytearray()
    for length in lengths:
        row, line, i = f.read(length), bytearray(), 0
        while i < len(row):
            c = row[i]
            i += 1
            if c < 128:                     # c+1 octets litteraux
                line += row[i:i + c + 1]
                i += c + 1
            elif c > 128:                   # 1 octet repete 257-c fois (128 = rien)
                line += row[i:i + 1] * (257 - c)
                i += 1
        out += bytes(line[:row_bytes]).ljust(row_bytes, b"\0")
    return bytes(out)

def _abr_read_sample(f) -> QImage | None:
    """Bornes (4 x int32), profondeur, compression puis pixels d'une pointe -> QImage
    niveaux de gris (255 = peinture pleine), reduite a _ABR_SAMPLE_MAX_DIM."""
    top, left, bottom, right = struct.unpack(">4i", f.read(16))
    depth, compression = struct.unpack(">HB", f.read(3))
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0 or width * height > 64_000_000 or depth not in (8, 16):
        return None
    bpp = depth // 8
    data = _abr_unpackbits(f, height, width * bpp) if compression else f.read(width * height * bpp)
    if bpp == 2:
        data = data[0::2]                   # 16 bits gros-boutiste : octet de poids fort
    if len(data) < width * height:
        return None
    image = QImage(data, width, height, width, QImage.Format_Grayscale8).copy()
    if max(width, height) > _ABR_SAMPLE_MAX_DIM:
        image = image.scaled(_ABR_SAMPLE_MAX_DIM, _ABR_SAMPLE_MAX_DIM, Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
    return image

def _abr_brushes(path: Path) -> list:
    """Pointes d'un .abr, dans l'ordre du fichier : QImage (echantillon) ou tuple
    ("round", diametre, durete %, rondeur %, angle) pour une pointe calculee (v1/v2)."""
    brushes: list = []
    with open(path, "rb") as f:
        head = f.read(4)
        if len(head) < 4:
            return brushes
        version, second = struct.unpack(">HH", head)
        if version in (1, 2):
            for _ in range(second):         # `second` = nombre de pointes
                if len(brushes) >= _ABR_MAX_BRUSHES:
                    break
                kind, size = struct.unpack(">HI", f.read(6))
                next_brush = f.tell() + size
                if kind == 1:
                    _misc, _spacing, diameter, roundness, angle, hardness = struct.unpack(">IHHHhH", f.read(14))
                    brushes.append(("round", diameter, hardness, roundness, angle))
                elif kind == 2:
                    f.seek(6, 1)                                  # divers + espacement
                    if version == 2:
                        (chars,) = struct.unpack(">I", f.read(4))
                        f.seek(2 * chars, 1)                      # nom (UTF-16)
                    f.seek(1 + 8, 1)                              # anticrenelage + bornes courtes
                    sample = _abr_read_sample(f)
                    if sample is not None:
                        brushes.append(sample)
                f.seek(next_brush)
        elif version in (6, 7, 9, 10):
            sections = {}                     # cle 8BIM -> (debut, fin) ; on ne lit que ce qui sert
            while True:
                section = f.read(12)
                if len(section) < 12 or section[:4] != b"8BIM":
                    break
                (size,) = struct.unpack(">I", section[8:12])
                sections.setdefault(section[4:8], (f.tell(), f.tell() + size))
                f.seek(size, 1)
            order = []
            if b"desc" in sections:
                start, end = sections[b"desc"]
                f.seek(start)
                order = _abr_desc_order(f.read(end - start))[:_ABR_MAX_BRUSHES]
            wanted = {e for e in order if isinstance(e, str)}
            samples = {}
            if b"samp" in sections:
                start, end = sections[b"samp"]
                f.seek(start)
                # Sans description lisible : les pointes echantillonnees dans l'ordre du fichier.
                while f.tell() + 4 <= end and (len(samples) < (len(wanted) if order else _ABR_MAX_BRUSHES)):
                    (length,) = struct.unpack(">I", f.read(4))
                    begin = f.tell()
                    uuid = f.read(37)[1:].decode("ascii", "replace")     # "$" + identifiant
                    if not order or uuid in wanted:
                        f.seek(10 if second == 1 else 264, 1)            # entete propre a la sous-version
                        sample = _abr_read_sample(f)
                        if sample is not None:
                            samples[uuid] = sample
                    f.seek(begin + length + (-length % 4))              # pointes alignees sur 4 octets
            if order:
                brushes = [samples[e] if isinstance(e, str) else e for e in order
                           if not isinstance(e, str) or e in samples]
            else:
                brushes = list(samples.values())
    return brushes

def _abr_desc_order(desc: bytes) -> list:
    """Pointes dans l'ordre de Photoshop, lues dans la section "desc" (descripteur d'action) :
    identifiant de l'echantillon (str) pour une pointe echantillonnee, tuple ("round",
    diametre, durete %, rondeur %, angle) pour une pointe calculee. Lecture par motifs (cles
    "Brsh"/"Dmtr"/"Hrdn"... en clair) plutot qu'un parseur complet du descripteur."""
    starts = [(m.start(), m.group(1)) for m in
              re.finditer(rb"BrshObjc.{6}\x00\x00\x00[\x0c\x0d](computedBrush|sampledBrush)", desc, re.S)]
    order = []
    for index, (start, kind) in enumerate(starts):
        chunk = desc[start:starts[index + 1][0] if index + 1 < len(starts) else len(desc)]
        if kind == b"sampledBrush":
            m = re.search(rb"sampledDataTEXT(.{4})", chunk, re.S)
            if m:
                (chars,) = struct.unpack(">I", m.group(1))
                raw = chunk[m.end():m.end() + 2 * chars]
                order.append(raw.decode("utf-16-be", "replace").rstrip("\0"))
            continue
        params = {k.decode(): struct.unpack(">d", v)[0] for k, v in
                  re.findall(rb"(Dmtr|Hrdn|Angl|Rndn)UntF#\w{3}(.{8})", chunk[:400], re.S)}
        order.append(("round", params.get("Dmtr", 10.0), params.get("Hrdn", 100.0),
                      params.get("Rndn", 100.0), params.get("Angl", 0.0)))
    return order

def _decode_abr_image(path: Path, max_dim: int) -> QImage | None:
    """Planche des pointes d'une bibliotheque de brosses Photoshop : une case par pointe,
    peinture sombre sur fond clair (comme la planche des polices). None si aucune pointe lisible."""
    try:
        brushes = _abr_brushes(path)
    except (OSError, struct.error, ValueError):
        return None
    if not brushes:
        return None
    width = max(480, min(max_dim, 1100))
    cols = math.ceil(math.sqrt(len(brushes)))
    rows = math.ceil(len(brushes) / cols)
    cell = width / cols
    pad = cell * 0.08
    background = 244
    image = QImage(width, max(1, round(rows * cell)), QImage.Format_ARGB32)
    image.fill(QColor(background, background, background))
    # Niveau de peinture (255 = plein) -> gris affiche (fond clair -> noir).
    ink = bytes(round(background * (1 - v / 255)) for v in range(256))
    biggest = max((b[1] for b in brushes if isinstance(b, tuple)), default=1) or 1
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for index, brush in enumerate(brushes):
            box = QRectF((index % cols) * cell + pad, (index // cols) * cell + pad, cell - 2 * pad, cell - 2 * pad)
            if isinstance(brush, tuple):
                _kind, diameter, hardness, roundness, angle = brush
                # Racine : une pointe de 3 px reste visible a cote d'une de 300 px.
                radius = box.width() / 2 * max(0.12, math.sqrt(max(diameter, 0) / biggest))
                gradient = QRadialGradient(QPointF(0, 0), radius)
                gradient.setColorAt(0, QColor(0, 0, 0))
                # Durete = part du rayon peinte pleine (100 % : bord net, pas de degrade).
                gradient.setColorAt(max(0.0, min(0.97, hardness / 100)), QColor(0, 0, 0))
                gradient.setColorAt(1, QColor(0, 0, 0, 0))
                painter.save()
                painter.translate(box.center())
                painter.rotate(-angle)
                painter.scale(1, max(0.05, roundness / 100))
                painter.setPen(Qt.NoPen)
                painter.setBrush(gradient)
                painter.drawEllipse(QPointF(0, 0), radius, radius)
                painter.restore()
                continue
            gray = brush.convertToFormat(QImage.Format_Grayscale8)
            raw = bytes(gray.constBits())[:gray.sizeInBytes()]
            shown = QImage(raw.translate(ink), gray.width(), gray.height(), gray.bytesPerLine(),
                           QImage.Format_Grayscale8).copy()
            scaled = shown.size().scaled(box.size().toSize(), Qt.KeepAspectRatio)   # remplit sa case
            target = QRectF(0, 0, scaled.width(), scaled.height())
            target.moveCenter(box.center())
            painter.drawImage(target, shown)
    finally:
        painter.end()
    return image

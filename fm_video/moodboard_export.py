"""Assemblage PNG en fond, par rangées : jamais de grande image complète en mémoire."""
import json
import math
import os
import struct
import zlib
from PySide6.QtGui import QImage, QPainter, QColor


def export_board(cache, indices, layout, is_current=None):
    current = is_current or (lambda: True)
    if not indices or not current():
        return
    manifest = cache.directory / '.moodboard.json'
    signature = json.loads(manifest.read_text(encoding='utf-8'))
    if signature.get('indices') != list(indices) or signature.get('layout') != list(layout):
        return
    if cache.selection:
        signature['selection'] = {str(k):int(v) for k,v in cache.selection.items()}
    output = cache.directory / f'.moodboard - {cache.path.stem}.png'
    marker = cache.directory / '.moodboard-png.json'
    try:
        previous = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    # Le PNG est une planche de référence : il reste jointif même si la vue
    # Moodboard affiche un espacement entre ses vignettes.
    if previous.get('signature') == signature and previous.get('without_gaps') is True:
        old = cache.directory / previous.get('filename', output.name)
        if old.is_file():
            if old != output:
                os.replace(old, output)
                marker.write_text(json.dumps(dict(signature=signature, filename=output.name, without_gaps=True)), encoding='utf-8')
            return
    if any(not cache.filename(i).is_file() for i in indices):
        return
    first = QImage(str(cache.filename(indices[0])))
    if first.isNull():
        return
    cols = max(1, int(layout[0])) if layout else max(1, math.ceil(math.sqrt(len(indices))))
    rows = max(math.ceil(len(indices) / cols), int(layout[1]) if len(layout) > 1 else 1)
    gap = 0
    tile_w, tile_h = cache.width, first.height()
    width, height = cols * tile_w + (cols + 1) * gap, rows * tile_h + (rows + 1) * gap
    temporary = output.with_suffix('.part.png')
    def chunk(stream, kind, data):
        stream.write(struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))
    compressor = zlib.compressobj(6)
    try:
        with temporary.open('wb') as stream:
            stream.write(b'\x89PNG\r\n\x1a\n')
            chunk(stream, b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            for row in range(rows):
                if not current():
                    return
                band_h = tile_h + gap + (gap if row == 0 else 0)
                band = QImage(width, band_h, QImage.Format_RGB888)
                if band.isNull():
                    raise OSError('Mémoire insuffisante pour une rangée du moodboard')
                band.fill(QColor('#141414'))
                painter = QPainter(band)
                try:
                    for col in range(cols):
                        n = row * cols + col
                        if n >= len(indices):
                            break
                        image = QImage(str(cache.filename(indices[n])))
                        if image.isNull() or not current():
                            return
                        painter.drawImage(gap + col * (tile_w + gap), gap if row == 0 else 0, image)
                finally:
                    painter.end()
                data = band.constBits()
                stride = band.bytesPerLine()
                for y in range(band_h):
                    if y % 64 == 0 and not current():
                        return
                    compressed = compressor.compress(b'\0' + bytes(data[y * stride:y * stride + width * 3]))
                    if compressed:
                        chunk(stream, b'IDAT', compressed)
            chunk(stream, b'IDAT', compressor.flush())
            chunk(stream, b'IEND', b'')
        if not current():
            return
        os.replace(temporary, output)
        for pattern in ('.moodboard - *.png', 'moodboard - *.png'):
            for old in cache.directory.glob(pattern):
                if old != output:
                    old.unlink()
        marker.write_text(json.dumps(dict(signature=signature, filename=output.name, without_gaps=True)), encoding='utf-8')
    finally:
        temporary.unlink(missing_ok=True)

"""OCR (sans Qt) par le moteur de reconnaissance INTÉGRÉ à Windows 10 / 11 (Windows.Media.Ocr, via pywinrt) :
local, gratuit, langues installées dans Windows (ici fr-FR et en-US). Aucun envoi réseau.

- `available_languages()` : balises installées ; `recognize(bgra, w, h, langue)` : lignes et mots avec leurs
  rectangles (pixels de l'image).
- `add_text_layer(octets, résultats)` : PDF INTERROGEABLE — texte INVISIBLE (mode de rendu 3) posé exactement sur
  chaque mot reconnu, l'apparence de la page ne change pas ; le contenu existant n'est jamais retouché.
- `is_scanned(doc, page)` : page sans couche texte mais avec une image (fil du moteur).
"""
from __future__ import annotations

import asyncio
import io


class OcrUnavailable(RuntimeError):
    pass


def available_languages() -> list[str]:
    try:
        from winrt.windows.media.ocr import OcrEngine
    except ImportError as exc:
        raise OcrUnavailable("paquets winrt absents (pip install winrt-Windows.Media.Ocr …)") from exc
    return [lang.language_tag for lang in OcrEngine.available_recognizer_languages]


def _engine(tag: str):
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine
    engine = OcrEngine.try_create_from_language(Language(tag))
    if engine is None:
        raise OcrUnavailable("langue OCR non installée dans Windows : %s" % tag)
    return engine


def max_dimension() -> int:
    from winrt.windows.media.ocr import OcrEngine
    return int(OcrEngine.max_image_dimension)


def recognize(bgra: bytes, width: int, height: int, tag: str = "fr-FR") -> list[dict]:
    """[{'text', 'rect': (x0, y0, x1, y1), 'words': [{'text', 'rect'}]}] en pixels de l'image (BGRA 8 bits)."""
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.storage.streams import DataWriter
    engine = _engine(tag)
    writer = DataWriter()
    writer.write_bytes(bgra)
    bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8, width, height,
                                                    BitmapAlphaMode.PREMULTIPLIED)

    async def run():
        return await engine.recognize_async(bitmap)
    result = asyncio.run(run())
    lines = []
    for line in result.lines:
        words = []
        for word in line.words:
            r = word.bounding_rect
            words.append({"text": word.text, "rect": (r.x, r.y, r.x + r.width, r.y + r.height)})
        if words:
            xs = [w["rect"] for w in words]
            lines.append({"text": line.text, "words": words,
                          "rect": (min(r[0] for r in xs), min(r[1] for r in xs), max(r[2] for r in xs),
                                   max(r[3] for r in xs))})
    return lines


def is_scanned(doc, page: int) -> bool:
    return not doc.has_text_layer(page) and doc.image_count(page) > 0


def add_text_layer(data: bytes, results: dict[int, dict]) -> bytes:
    """`results` = {page: {'scale': pixels par point, 'lines': [...]}} -> PDF avec texte invisible par mot."""
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        font = pymupdf.Font("helv")
        for page_index, res in results.items():
            page = doc[page_index]
            k = float(res["scale"])
            for line in res["lines"]:
                for word in line["words"]:
                    text = word["text"]
                    if not text.strip():
                        continue
                    x0, y0, x1, y1 = (v / k for v in word["rect"])
                    r = pymupdf.Rect(x0, y0, x1, y1) * page.derotation_matrix
                    r.normalize()
                    size = max(2.0, r.height * 0.9)
                    natural = font.text_length(text, fontsize=size) or 1.0
                    origin = pymupdf.Point(r.x0, r.y1 - r.height * 0.18)
                    morph = (origin, pymupdf.Matrix(r.width / natural, 1.0))
                    page.insert_text(origin, text, fontsize=size, fontname="helv", render_mode=3, morph=morph)
        out = io.BytesIO()
        doc.save(out, garbage=1, deflate=True)
        return out.getvalue()
    finally:
        doc.close()

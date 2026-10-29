"""Aperçus DWG / DXF et conversion ODA.

Carte et pièges : docs/agents/apercus.md.
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from config import _DWG_RENDER_LOCK

def _oda_environment() -> dict:
    """Environnement d'ODA File Converter : une application Qt, que les variables Qt de NOTRE processus
    (`QT_QPA_PLATFORM`, `QT_PLUGIN_PATH`…) empechent de demarrer (« no Qt platform plugin could be initialized »)."""
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("QT_")}

def _oda_file_converter() -> str | None:
    """Trouve ODA File Converter, necessaire pour convertir un DWG en DXF."""
    configured = os.environ.get("ODA_FILE_CONVERTER")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("ODAFileConverter") or shutil.which("ODAFileConverter.exe")
    if found:
        return found
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ODA"]
    roots.append(Path(r"C:\Program Files\ODA"))
    for root in roots:
        try:
            candidates = sorted(root.glob("**/ODAFileConverter.exe"), reverse=True)
            if candidates:
                return str(candidates[0])
        except OSError:
            continue
    return None

_DWG_THUMBNAIL_SENTINEL = bytes((0x1F, 0x25, 0x6D, 0x07, 0xD4, 0x36, 0x28, 0x28,
                                 0x9D, 0x57, 0xCA, 0x3F, 0x9D, 0x44, 0x10, 0x2B))

def _decode_dwg_thumbnail(path: Path) -> QImage | None:
    """Vignette qu'AutoCAD range dans le DWG (option « enregistrer une vignette », active par
    defaut) : sans aucun outil externe. Adresse de la section a l'octet 0x0D de l'entete (en clair
    dans toutes les versions R13+), section = sentinelle de 16 octets, taille, nombre d'entrees,
    puis (code, debut, taille) par entree : 2 = BMP sans entete de fichier (DIB), 6 = PNG
    (AutoCAD 2013+). La plus grande image lisible ; None si le fichier n'en a pas."""
    import struct
    try:
        with open(path, "rb") as f:
            head = f.read(0x11)
            if len(head) < 0x11 or not head.startswith(b"AC10"):
                return None
            f.seek(struct.unpack_from("<I", head, 0x0D)[0])
            block = f.read(21)
            if len(block) < 21 or block[:16] != _DWG_THUMBNAIL_SENTINEL:
                return None
            entries = []
            for _ in range(block[20]):
                raw = f.read(9)
                if len(raw) < 9:
                    break
                entries.append(struct.unpack("<BII", raw))
            best = None
            for code, start, size in entries:
                if code not in (2, 6) or not 0 < size < 64 * 1024 * 1024:
                    continue
                f.seek(start)
                data = f.read(size)
                if code == 2 and len(data) >= 40:
                    # DIB : entete de fichier BMP ajoute (debut des pixels = apres l'entete
                    # d'image et la palette eventuelle) pour que Qt le lise.
                    header_size = struct.unpack_from("<I", data, 0)[0]
                    bits = struct.unpack_from("<H", data, 14)[0]
                    colors = struct.unpack_from("<I", data, 32)[0] or ((1 << bits) if bits <= 8 else 0)
                    data = b"BM" + struct.pack("<IHHI", 14 + len(data), 0, 0, 14 + header_size + colors * 4) + data
                image = QImage.fromData(data)
                if not image.isNull() and (best is None or image.width() * image.height() > best.width() * best.height()):
                    best = image
            return best
    except (OSError, struct.error):
        return None

def _decode_dwg_image(path: Path, max_dim: int, progress_callback=None, cancel_event=None) -> QImage | None:
    """Convertit le DWG en DXF puis rend le model space en image 2D. Sans ODA File Converter, ou
    si la conversion echoue : la vignette integree au DWG (_decode_dwg_thumbnail)."""
    image = _render_dwg_with_oda(path, max_dim, progress_callback, cancel_event)
    if image is None and not (cancel_event is not None and cancel_event.is_set()):
        image = _decode_dwg_thumbnail(path)
        if image is not None and max(image.width(), image.height()) > max_dim:
            image = image.scaled(max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image

def _render_dxf_file(dxf_path: Path, max_dim: int, progress_callback=None) -> QImage | None:
    """Dessin VECTORIEL du model space d'un DXF (ezdxf + matplotlib), traits clairs sur fond
    sombre, image cadree sur le dessin (proportions du plan, grand cote = `max_dim`). Sert aux .dxf
    et aux .dwg convertis par ODA File Converter. None si illisible ou dependances absentes."""
    try:
        import ezdxf
        from ezdxf import recover
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        from ezdxf.addons.drawing.properties import LayoutProperties
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError as exc:
        if progress_callback:
            progress_callback(99, f"Dependances d'apercu DXF manquantes : {exc}")
        return None
    if progress_callback:
        progress_callback(42, "Lecture du dessin 2D")
    try:
        try:
            doc, auditor = recover.readfile(str(dxf_path))
        except Exception:
            doc = ezdxf.readfile(str(dxf_path))
            auditor = None
    except (OSError, ezdxf.DXFError):
        return None
    if auditor is not None and auditor.errors:
        if progress_callback:
            progress_callback(99, "Le dessin DXF contient des erreurs")
        return None
    layout = doc.modelspace()
    inches = 6.0
    with _DWG_RENDER_LOCK:
        figure = Figure(figsize=(inches, inches), dpi=max(96.0, max_dim / inches))
        canvas = FigureCanvasAgg(figure)
        axes = figure.add_axes((0, 0, 1, 1))
        axes.set_aspect("equal", adjustable="datalim")
        context = RenderContext(doc)
        properties = LayoutProperties.from_layout(layout)
        properties.set_colors("#17191b", "#d6d9dc")
        if progress_callback:
            progress_callback(68, "Rendu du model space en 2D")
        Frontend(context, MatplotlibBackend(axes)).draw_layout(
            layout, finalize=True, layout_properties=properties
        )
        # Cadrage sur le dessin : la figure prend les proportions du plan (bornees a 1:4) au lieu
        # d'un carre ou un plan large flottait entre deux grandes bandes vides.
        width, height = axes.dataLim.width, axes.dataLim.height
        if width > 0 and height > 0:
            ratio = max(0.25, min(4.0, width / height))
            figure.set_size_inches(inches if ratio >= 1 else inches * ratio,
                                   inches / ratio if ratio >= 1 else inches)
        canvas.draw()
        buffer = io.BytesIO()
        canvas.print_png(buffer)
    image = QImage.fromData(buffer.getvalue(), "PNG")
    if image.isNull():
        return None
    if max(image.width(), image.height()) > max_dim:
        image = image.scaled(max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image

def _render_dwg_with_oda(path: Path, max_dim: int, progress_callback=None, cancel_event=None) -> QImage | None:
    """Rendu complet du model space (ODA File Converter + ezdxf + matplotlib). None sans ODA."""
    converter = _oda_file_converter()
    if not converter:
        if progress_callback:
            progress_callback(90, "ODA File Converter absent : vignette integree au DWG")
        return None
    try:
        import ezdxf
    except ImportError as exc:
        if progress_callback:
            progress_callback(99, f"Dependances d'apercu DWG manquantes : {exc}")
        return None

    try:
        with tempfile.TemporaryDirectory(prefix="pipe_dwg_preview_") as temp_dir:
            output_dir = Path(temp_dir)
            log_path = output_dir / "oda_converter.log"
            log_stream = log_path.open("w", encoding="utf-8", errors="replace")
            if progress_callback:
                progress_callback(8, "Conversion DWG vers DXF")
            kwargs = {"stdout": log_stream, "stderr": log_stream, "env": _oda_environment()}
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                [converter, str(path.parent), str(output_dir), "ACAD2018", "DXF", "0", "0", path.name],
                **kwargs,
            )
            deadline = time.monotonic() + 120
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    log_stream.close()
                    return None
                if time.monotonic() >= deadline:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    log_stream.close()
                    if progress_callback:
                        progress_callback(99, "Delai depasse pendant la conversion DWG")
                    return None
                time.sleep(0.1)
            log_stream.close()
            dxf_path = next(
                (candidate for candidate in output_dir.glob("*") if candidate.suffix.lower() == ".dxf"),
                None,
            )
            if proc.returncode != 0 or dxf_path is None:
                if progress_callback:
                    progress_callback(99, "Conversion DWG impossible avec ODA File Converter")
                return None
            return _render_dxf_file(dxf_path, max_dim, progress_callback)
    except (OSError, subprocess.SubprocessError, ezdxf.DXFStructureError) as exc:
        if progress_callback:
            progress_callback(99, f"Erreur de rendu DWG 2D : {exc}")
        return None

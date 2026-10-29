"""Images 2D, RAW, HDR et LUT ; dispatch des décodeurs statiques.

Carte et pièges : docs/agents/apercus.md.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from PySide6.QtCore import QSize, Qt, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage, QImageReader
from config import ABR_EXTENSIONS, DWG_EXTENSIONS, DXF_EXTENSIONS, EXR_EXTENSIONS, FONT_EXTENSIONS, CUBE_EXTENSIONS, HDR_EXTENSIONS, ILLUSTRATOR_EXTENSIONS, RAW_EXTENSIONS, PDF_EXTENSIONS, PSD_EXTENSIONS, TX_EXTENSIONS
from . import abr as _abr
from . import dwg as _dwg
from . import font as _font
from . import memory as _memory
from . import optional as _optional
from . import pdf as _pdf

def _decode_psd_thumbnail(path: Path) -> QImage | None:
    """Extrait la vignette JPEG que Photoshop embarque dans un .psd/.psb
    (ressource d'image ID 1036, "Thumbnail Resource (Photoshop 5.0)")
    plutot que de composer nous-memes les calques (hors de portee ici) :
    presente dans la quasi-totalite des fichiers Photoshop modernes, sauf
    enregistrement explicitement desactive. None si absente, fichier
    illisible, ou pas un vrai PSD (signature "8BPS" manquante)."""
    try:
        with open(path, "rb") as f:
            header = f.read(26)
            if len(header) < 26 or header[:4] != b"8BPS":
                return None
            length_bytes = f.read(4)
            if len(length_bytes) < 4:
                return None
            # Section "Color Mode Data" (uniquement utile pour le mode
            # Indexe/Duotone, pas pour la vignette) : on la saute.
            f.seek(int.from_bytes(length_bytes, "big"), 1)
            res_len_bytes = f.read(4)
            if len(res_len_bytes) < 4:
                return None
            data = f.read(int.from_bytes(res_len_bytes, "big"))
    except OSError:
        return None

    pos, n = 0, len(data)
    while pos + 12 <= n:
        if data[pos:pos + 4] != b"8BIM":
            break   # bloc de ressource corrompu/inattendu : mieux vaut s'arreter que boucler dans du bruit
        resource_id = int.from_bytes(data[pos + 4:pos + 6], "big")
        name_len = data[pos + 6]
        name_block = 1 + name_len
        if name_block % 2:   # chaine Pascal (longueur + nom) paddee au pair
            name_block += 1
        size_pos = pos + 6 + name_block
        if size_pos + 4 > n:
            break
        data_size = int.from_bytes(data[size_pos:size_pos + 4], "big")
        payload_pos = size_pos + 4
        if payload_pos + data_size > n:
            break
        if resource_id == 1036:
            # Format (4) + largeur/hauteur/widthbytes/taille totale (4x4) +
            # taille compressee (4) + bits/pixel (2) + plans (2) = 28 octets
            # d'entete, suivis directement du flux JPEG lui-meme.
            if data_size > 28 and int.from_bytes(data[payload_pos:payload_pos + 4], "big") == 1:
                jpeg_size = int.from_bytes(data[payload_pos + 20:payload_pos + 24], "big")
                jpeg_data = data[payload_pos + 28:payload_pos + 28 + jpeg_size]
                if jpeg_data:
                    image = QImage.fromData(jpeg_data, "JPEG")
                    if not image.isNull():
                        return image
            return None
        pos = payload_pos + data_size + (data_size % 2)
    return None

def _oiiotool_executable() -> str | None:
    """Trouve l'utilitaire OpenImageIO livre avec Arnold ou Maya."""
    found = shutil.which("oiiotool")
    if found:
        return found
    roots = []
    maya_location = os.environ.get("MAYA_LOCATION")
    if maya_location:
        roots.append(Path(maya_location))
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    roots.extend((program_files / "Autodesk" / "Arnold", program_files / "Autodesk"))
    candidates = []
    for root in roots:
        for pattern in ("Maya*/bin/oiiotool.exe", "*/bin/oiiotool.exe", "bin/oiiotool.exe"):
            try:
                candidates.extend(root.glob(pattern))
            except OSError:
                pass
    candidates = sorted({p for p in candidates if p.is_file()}, reverse=True)
    return str(candidates[0]) if candidates else None

def _decode_tx_image(path: Path, max_dim: int) -> QImage | None:
    """Convertit une texture Arnold .tx en petite image lisible par Qt."""
    oiiotool = _oiiotool_executable()
    if not oiiotool:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="pipe_tx_preview_") as temp_dir:
            output_path = Path(temp_dir) / "preview.png"
            tool_dir = str(Path(oiiotool).resolve().parent)
            env = os.environ.copy()
            env["PATH"] = tool_dir + os.pathsep + env.get("PATH", "")
            result = subprocess.run(
                [oiiotool, str(path.resolve()), "--fit", f"{max_dim}x{max_dim}", "-o", str(output_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=45, check=False, env=env,
            )
            if result.returncode != 0 or not output_path.is_file():
                return None
            image = QImage(str(output_path))
            return image.copy() if not image.isNull() else None
    except (OSError, subprocess.SubprocessError):
        return None

def _decode_exr_image(path: Path, max_dim: int) -> QImage | None:
    """Convertit le rendu HDR d'un .exr en image affichable : tone-mapping
    Reinhard simple (gere sans les cramer les valeurs > 1, frequentes en
    lineaire) puis gamma sRGB approche, sur le premier calque RGB(A) trouve
    (une passe "beaute", pas les innombrables AOV utilitaires que peut
    contenir un .exr multi-couches). None si le fichier n'a pas de calque
    exploitable, est illisible, ou si le paquet OpenEXR n'est pas installe
    (voir _OPENEXR_AVAILABLE)."""
    if not _optional._OPENEXR_AVAILABLE:
        return None
    try:
        channels = _optional.OpenEXR.File(str(path)).parts[0].channels
        pixels = None
        for key in ("RGBA", "RGB", "rgba", "rgb"):
            if key in channels:
                pixels = channels[key].pixels
                break
        if pixels is None and "R" in channels and "G" in channels and "B" in channels:
            pixels = _optional.np.stack(
                [channels["R"].pixels, channels["G"].pixels, channels["B"].pixels], axis=-1
            )
    except Exception:
        return None
    if pixels is None or pixels.ndim != 3 or pixels.shape[2] < 3:
        return None

    rgb = _optional.np.clip(pixels[..., :3].astype(_optional.np.float32), 0.0, None)
    rgb = rgb / (1.0 + rgb)             # tone-mapping Reinhard
    rgb = _optional.np.power(rgb, 1.0 / 2.2)      # gamma sRGB approche
    rgb8 = _optional.np.clip(rgb * 255.0 + 0.5, 0, 255).astype(_optional.np.uint8)

    h, w = rgb8.shape[:2]
    longest = max(h, w)
    if longest > max_dim:
        # Sous-echantillonnage simple (pas d'interpolation) avant de laisser
        # Qt remettre a l'echelle exacte au dessin : suffisant pour une
        # vignette, evite de garder une pleine resolution HDR en memoire
        # plus longtemps que necessaire.
        step = max(1, longest // max_dim)
        rgb8 = rgb8[::step, ::step]

    rgb8 = _optional.np.ascontiguousarray(rgb8)
    h, w = rgb8.shape[:2]
    # .copy() : QImage(buffer, ...) ne fait que referencer `rgb8.data`, qui
    # serait libere avec le tableau numpy des la sortie de cette fonction.
    return QImage(rgb8.data, w, h, w * 3, QImage.Format_RGB888).copy()

# Images de test des LUT (.cube), reglees dans Parametres generaux > LUT et
# recopiees ici par browser_core.apply_all_settings : l'apercu d'un .cube est
# l'image par defaut avec la LUT appliquee.
LUT_TEST_IMAGES: list[str] = []

LUT_DEFAULT_IMAGE: str = ""

# Encodage de l'image de test d'une LUT, un par image (cle = chemin) : "srgb"
# (aucune conversion) ou "slog3"/"flog"/"flog2" (RAW developpe dans cette
# courbe, ou image 8 bits convertie sRGB -> courbe). Sert uniquement a
# l'image de test (voir _lut_test_image), jamais aux vignettes.
LUT_IMAGE_CURVES: dict[str, str] = {}

_LUT_CURVE_NAMES = {
    "slog3": "S-Log3 / S-Gamut3.Cine (Sony)",
    "flog": "F-Log / F-Gamut (Fujifilm)",
    "flog2": "F-Log2 / F-Gamut (Fujifilm)",
}

def lut_image_kind(path) -> str:
    """"raw" (donnees capteur), "float" (EXR/HDR, tone-mappe) ou "8bit"."""
    suffix = Path(str(path)).suffix.lower()
    if suffix in RAW_EXTENSIONS:
        return "raw"
    if suffix in EXR_EXTENSIONS | HDR_EXTENSIONS:
        return "float"
    return "8bit"

def lut_curve_choices(kind: str) -> list[tuple[str, str]]:
    """Choix d'encodage (cle, libelle) proposes selon le type d'image."""
    if kind == "raw":
        head = [("srgb", "D\u00e9veloppement normal (sRGB, pour une LUT d'affichage)")]
        return head + [(k, f"D\u00e9velopper en {v}") for k, v in _LUT_CURVE_NAMES.items()]
    if kind == "8bit":
        head = [("srgb", "Telle quelle (d\u00e9j\u00e0 dans l'espace attendu par la LUT)")]
        return head + [(k, f"Convertir sRGB \u2192 {v} (simulation)") for k, v in _LUT_CURVE_NAMES.items()]
    return [("srgb", "Telle quelle (tone-mapping d'affichage)")]

def _lut_default_curve() -> str:
    return LUT_IMAGE_CURVES.get(LUT_DEFAULT_IMAGE, "srgb")

_GAMUT_PRIMARIES = {
    "rec709": ((0.64, 0.33), (0.30, 0.60), (0.15, 0.06)),
    "sgamut3cine": ((0.766, 0.275), (0.225, 0.800), (0.089, -0.087)),
    "fgamut": ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)),
}

_D65 = (0.3127, 0.3290)

_CURVE_GAMUT = {"slog3": "sgamut3cine", "flog": "fgamut", "flog2": "fgamut"}

def _rgb_to_xyz(gamut: str):
    """Matrice RGB lineaire -> XYZ (blanc D65) calculee depuis les primaires."""
    prim = _optional.np.array([[x / y, 1.0, (1 - x - y) / y] for x, y in _GAMUT_PRIMARIES[gamut]], dtype=_optional.np.float64).T
    white = _optional.np.array([_D65[0] / _D65[1], 1.0, (1 - _D65[0] - _D65[1]) / _D65[1]])
    return prim * _optional.np.linalg.solve(prim, white)

def _log_encode(x, curve: str):
    """Scene lineaire (0.18 = gris moyen) -> signal 0..1 de la courbe `curve`."""
    x = _optional.np.maximum(x, 0.0)
    if curve == "slog3":
        hi = (420.0 + _optional.np.log10(_optional.np.maximum(x + 0.01, 1e-9) / 0.19) * 261.5) / 1023.0
        lo = (x * (171.2102946929 - 95.0) / 0.01125 + 95.0) / 1023.0
        return _optional.np.where(x >= 0.01125, hi, lo)
    if curve == "flog":
        a, b, c, d, e, f, cut = 0.555556, 0.009468, 0.344676, 0.790453, 8.735631, 0.092864, 0.00089
    else:  # flog2
        a, b, c, d, e, f, cut = 5.555556, 0.064829, 0.245281, 0.384316, 8.799461, 0.092864, 0.000889
    hi = c * _optional.np.log10(_optional.np.maximum(a * x + b, 1e-9)) + d
    return _optional.np.where(x >= cut, hi, e * x + f)

def _raw_linear_in_gamut(path: Path, max_dim: int, gamut: str):
    """RAW -> RGB lineaire float32 (H,W,3) dans `gamut`, expose pour que la
    luminance moyenne vaille 0.18. rawpy (XYZ lineaire) si dispo ; sinon JPEG
    integre (sRGB -> lineaire, approximation : moins de latitude)."""
    lin = None
    if _optional._RAWPY_AVAILABLE:
        try:
            with _optional.rawpy.imread(str(path)) as raw:
                xyz = raw.postprocess(half_size=True, use_camera_wb=True, no_auto_bright=True,
                                      gamma=(1, 1), output_bps=16, output_color=_optional.rawpy.ColorSpace.XYZ)
            xyz = xyz.astype(_optional.np.float32) / 65535.0
            lin = xyz @ _optional.np.linalg.inv(_rgb_to_xyz(gamut)).T.astype(_optional.np.float32)
        except Exception:
            lin = None
    if lin is None:
        image = _decode_embedded_jpeg(path, max_dim)
        if image is None:
            return None
        image = image.convertToFormat(QImage.Format_RGB888)
        w, h = image.width(), image.height()
        buf = _optional.np.frombuffer(image.constBits(), dtype=_optional.np.uint8, count=image.bytesPerLine() * h)
        v = buf.reshape(h, image.bytesPerLine())[:, :w * 3].reshape(h, w, 3).astype(_optional.np.float32) / 255.0
        v = _optional.np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
        m = _optional.np.linalg.inv(_rgb_to_xyz(gamut)) @ _rgb_to_xyz("rec709")
        lin = v @ m.T.astype(_optional.np.float32)
    longest = max(lin.shape[:2])
    if longest > max_dim:
        step = max(1, longest // max_dim)
        lin = lin[::step, ::step]
    lin = _optional.np.maximum(lin, 0.0)
    luma = float(lin.mean())
    if luma > 1e-6:
        lin = lin * float(_optional.np.clip(0.18 / luma, 0.05, 64.0))
    return _optional.np.ascontiguousarray(lin)

def _encode_8bit_as_log(image: QImage, curve: str) -> QImage | None:
    """Image 8 bits (sRGB) -> signal de la courbe log `curve` : sRGB -> lineaire
    -> gamut de la camera -> courbe. Simulation : pas de vraie latitude, les
    hautes lumieres et ombres de l'image sont deja ecretees."""
    if not _optional._NUMPY_AVAILABLE or curve not in _CURVE_GAMUT or image is None or image.isNull():
        return None
    image = image.convertToFormat(QImage.Format_RGB888)
    w, h = image.width(), image.height()
    buf = _optional.np.frombuffer(image.constBits(), dtype=_optional.np.uint8, count=image.bytesPerLine() * h)
    v = buf.reshape(h, image.bytesPerLine())[:, :w * 3].reshape(h, w, 3).astype(_optional.np.float32) / 255.0
    v = _optional.np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    m = _optional.np.linalg.inv(_rgb_to_xyz(_CURVE_GAMUT[curve])) @ _rgb_to_xyz("rec709")
    enc = _optional.np.clip(_log_encode(v @ m.T.astype(_optional.np.float32), curve), 0.0, 1.0)
    rgb8 = _optional.np.ascontiguousarray((enc * 255.0 + 0.5).astype(_optional.np.uint8))
    return QImage(rgb8.data, w, h, w * 3, QImage.Format_RGB888).copy()

def lut_test_image_for(path, curve: str, max_dim: int) -> QImage | None:
    """Image de test `path` telle qu'elle est donnee a la LUT, avec l'encodage
    `curve` (voir LUT_IMAGE_CURVES) ; aussi utilisee par les reglages pour montrer
    l'image convertie."""
    path = Path(str(path))
    kind = lut_image_kind(path)
    if curve in _CURVE_GAMUT:
        if kind == "raw":
            image = _decode_raw_log_image(path, max_dim, curve)
            if image is not None and not image.isNull():
                return image
        elif kind == "8bit":
            image = _encode_8bit_as_log(_decode_2d_image(path, max_dim), curve)
            if image is not None:
                return image
    return _decode_2d_image(path, max_dim)

def _decode_raw_log_image(path: Path, max_dim: int, curve: str) -> QImage | None:
    if not _optional._NUMPY_AVAILABLE or curve not in _CURVE_GAMUT:
        return None
    lin = _raw_linear_in_gamut(path, max_dim, _CURVE_GAMUT[curve])
    if lin is None:
        return None
    enc = _optional.np.clip(_log_encode(lin, curve), 0.0, 1.0)
    rgb8 = _optional.np.ascontiguousarray((enc * 255.0 + 0.5).astype(_optional.np.uint8))
    h, w = rgb8.shape[:2]
    return QImage(rgb8.data, w, h, w * 3, QImage.Format_RGB888).copy()

def _lut_test_image_signature() -> str:
    """Identifie l'image de test courante (chemin + mtime) pour la cle de cache."""
    if not LUT_DEFAULT_IMAGE:
        return "builtin"
    try:
        st = os.stat(LUT_DEFAULT_IMAGE)
    except OSError:
        return "missing"
    return hashlib.sha1(
        f"{LUT_DEFAULT_IMAGE}:{st.st_mtime_ns}:{st.st_size}:{_lut_default_curve()}".encode("utf-8")).hexdigest()[:12]

def set_lut_test_images(images, default, curves=None) -> None:
    """Met a jour les images de test ; invalide les apercus .cube en memoire
    si l'image par defaut change (le cache disque suit via la signature)."""
    global LUT_TEST_IMAGES, LUT_DEFAULT_IMAGE, LUT_IMAGE_CURVES
    images = [str(v) for v in (images or []) if str(v).strip()]
    default = str(default or "")
    if not default and images:
        default = images[0]
    curves = {str(k): v for k, v in (curves or {}).items() if v in _CURVE_GAMUT}
    changed = default != LUT_DEFAULT_IMAGE or curves.get(default) != LUT_IMAGE_CURVES.get(default)
    LUT_TEST_IMAGES, LUT_DEFAULT_IMAGE, LUT_IMAGE_CURVES = images, default, curves
    if changed:
        for cache in (_memory._file_image_cache, _memory._file_image_high_cache, _memory._file_image_column_cache):
            for key in [k for k in cache if k.lower().endswith(".cube")]:
                cache.pop(key, None)
        _memory._PREVIEW_STALE_LOOKUP_MISSES.difference_update(
            {m for m in _memory._PREVIEW_STALE_LOOKUP_MISSES if m[0].lower().endswith(".cube")})
        _memory._FILE_IMAGE_COLUMN_LOOKUP_MISSES.difference_update(
            {m for m in _memory._FILE_IMAGE_COLUMN_LOOKUP_MISSES if m[0].lower().endswith(".cube")})

def _parse_cube_lut(path: Path):
    """Lit un .cube. Retourne (dimension, taille, table float32, domaine min,
    domaine max) ou None. 3D : table (N,N,N,3) indexee [b][g][r] (le rouge
    varie le plus vite dans le fichier) ; 1D : table (N,3)."""
    if not _optional._NUMPY_AVAILABLE:
        return None
    dim, size = 3, 0
    dmin, dmax = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    rows = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                head = line.split(None, 1)[0].upper()
                if head == "LUT_3D_SIZE":
                    dim, size = 3, int(line.split()[1])
                elif head == "LUT_1D_SIZE":
                    dim, size = 1, int(line.split()[1])
                elif head == "DOMAIN_MIN":
                    dmin = [float(v) for v in line.split()[1:4]]
                elif head == "DOMAIN_MAX":
                    dmax = [float(v) for v in line.split()[1:4]]
                elif head in ("TITLE", "LUT_3D_INPUT_RANGE", "LUT_1D_INPUT_RANGE"):
                    continue
                else:
                    parts = line.split()
                    if len(parts) >= 3:
                        rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
    except (OSError, ValueError, IndexError):
        return None
    expected = size ** 3 if dim == 3 else size
    if size < 2 or len(rows) < expected:
        return None
    table = _optional.np.asarray(rows[:expected], dtype=_optional.np.float32)
    table = table.reshape(size, size, size, 3) if dim == 3 else table
    return dim, size, table, _optional.np.asarray(dmin, _optional.np.float32), _optional.np.asarray(dmax, _optional.np.float32)

def _apply_cube_lut(rgb, lut):
    """Applique la LUT (interpolation trilineaire 3D / lineaire 1D) a `rgb`
    float32 (H,W,3) en 0..1."""
    dim, size, table, dmin, dmax = lut
    span = _optional.np.maximum(dmax - dmin, 1e-6)
    x = _optional.np.clip((rgb - dmin) / span, 0.0, 1.0) * (size - 1)
    i0 = _optional.np.minimum(_optional.np.floor(x).astype(_optional.np.int32), size - 2)
    f = x - i0
    i1 = i0 + 1
    if dim == 1:
        out = _optional.np.empty_like(rgb)
        for c in range(3):
            out[..., c] = table[i0[..., c], c] * (1 - f[..., c]) + table[i1[..., c], c] * f[..., c]
        return out
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    r1, g1, b1 = i1[..., 0], i1[..., 1], i1[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    c00 = table[b0, g0, r0] * (1 - fr) + table[b0, g0, r1] * fr
    c10 = table[b0, g1, r0] * (1 - fr) + table[b0, g1, r1] * fr
    c01 = table[b1, g0, r0] * (1 - fr) + table[b1, g0, r1] * fr
    c11 = table[b1, g1, r0] * (1 - fr) + table[b1, g1, r1] * fr
    c0 = c00 * (1 - fg) + c10 * fg
    c1 = c01 * (1 - fg) + c11 * fg
    return c0 * (1 - fb) + c1 * fb

def _lut_test_image(max_dim: int) -> QImage:
    """Image par defaut des reglages ; a defaut, un degrade + mires de couleurs."""
    if LUT_DEFAULT_IMAGE:
        image = lut_test_image_for(LUT_DEFAULT_IMAGE, _lut_default_curve(), max_dim)
        if image is not None and not image.isNull():
            return image
    w, h = 480, 270
    xs = _optional.np.linspace(0.0, 1.0, w, dtype=_optional.np.float32)[None, :, None]
    ys = _optional.np.linspace(0.0, 1.0, h, dtype=_optional.np.float32)[:, None, None]
    hue = _optional.np.array([[1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 1, 1], [0, 0, 1], [1, 0, 1]], _optional.np.float32)
    idx = _optional.np.minimum((xs * 6).astype(_optional.np.int32), 5)[0, :, 0]
    img = _optional.np.broadcast_to(hue[idx][None, :, :], (h, w, 3)).copy()
    img = img * (1 - ys * 0.6) + ys * 0.5 * (1 - ys)          # teintes -> gris moyen
    img[int(h * 0.8):] = _optional.np.broadcast_to(xs, (h - int(h * 0.8), w, 3))  # rampe de gris
    rgb8 = _optional.np.ascontiguousarray(_optional.np.clip(img * 255 + 0.5, 0, 255).astype(_optional.np.uint8))
    return QImage(rgb8.data, w, h, w * 3, QImage.Format_RGB888).copy()

def _decode_cube_image(path: Path, max_dim: int) -> QImage | None:
    """Apercu d'une LUT .cube : image de test (voir LUT_DEFAULT_IMAGE) avec la
    LUT appliquee, dans l'espace d'affichage de l'image (pas de conversion)."""
    lut = _parse_cube_lut(path)
    if lut is None:
        return None
    base = _lut_test_image(max_dim).convertToFormat(QImage.Format_RGB888)
    w, h = base.width(), base.height()
    stride = base.bytesPerLine()
    buf = _optional.np.frombuffer(base.constBits(), dtype=_optional.np.uint8, count=stride * h).reshape(h, stride)
    rgb = buf[:, :w * 3].reshape(h, w, 3).astype(_optional.np.float32) / 255.0
    out = _optional.np.clip(_apply_cube_lut(rgb, lut), 0.0, 1.0)
    rgb8 = _optional.np.ascontiguousarray((out * 255.0 + 0.5).astype(_optional.np.uint8))
    return QImage(rgb8.data, w, h, w * 3, QImage.Format_RGB888).copy()

def _decode_raw_image(path: Path, max_dim: int) -> QImage | None:
    """RAW d'appareil photo (.arw Sony, .raf Fuji...) : developpement via
    rawpy/LibRaw si installe (demi-resolution, balance des blancs appareil,
    sRGB) ; sinon (ou en cas d'echec) plus grande image JPEG integree au
    fichier, sans aucune dependance."""
    if _optional._RAWPY_AVAILABLE:
        try:
            with _optional.rawpy.imread(str(path)) as raw:
                rgb8 = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
            rgb8 = _optional.np.ascontiguousarray(rgb8)
            h, w = rgb8.shape[:2]
            image = QImage(rgb8.data, w, h, w * 3, QImage.Format_RGB888).copy()
            if not image.isNull():
                return image
        except Exception:
            pass
    return _decode_embedded_jpeg(path, max_dim)

def _decode_embedded_jpeg(path: Path, max_dim: int, *, include_transform: bool = False):
    """Plus grande image JPEG embarquee dans `path` (apercu des RAW Sony/Fuji) :
    cherche les marqueurs SOI, compare les tailles sans decoder, ne decode que
    la meilleure (reduite a max_dim, orientation EXIF appliquee)."""
    try:
        data = path.read_bytes()
    except OSError:
        return (None, 0) if include_transform else None
    best, best_area, pos = None, 0, 0
    while True:
        pos = data.find(b"\xff\xd8\xff", pos)
        if pos < 0:
            break
        buf = QBuffer()
        buf.setData(QByteArray(data[pos:pos + 8_000_000]))
        buf.open(QIODevice.ReadOnly)
        reader = QImageReader(buf, b"jpeg")
        size = reader.size()
        if size.isValid() and size.width() * size.height() > best_area:
            best, best_area = pos, size.width() * size.height()
        pos += 3
    if best is None:
        return (None, 0) if include_transform else None
    buf = QBuffer()
    buf.setData(QByteArray(data[best:]))
    buf.open(QIODevice.ReadOnly)
    reader = QImageReader(buf, b"jpeg")
    reader.setAutoTransform(True)
    transform = reader.transformation()
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > max_dim:
        scale = max_dim / max(size.width(), size.height())
        reader.setScaledSize(QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale))))
    image = reader.read()
    result = None if image.isNull() else image
    return (result, transform) if include_transform else result

def _decode_hdr_image(path: Path, max_dim: int) -> QImage | None:
    """Convertit un .hdr (Radiance RGBE) en image affichable — MEME tone-
    mapping Reinhard + gamma sRGB que _decode_exr_image (voir sa remarque)
    — voir la remarque de l'utilisateur, "possible de faire les apercus
    des hdri ?". Parseur RGBE MAISON (juste numpy, AUCUNE dependance
    externe contrairement a .exr/OpenEXR — le format Radiance est
    documente/stable et volontairement simple) : supporte le format RLE
    "nouveau style" (l'immense majorite des .hdr generes par les outils
    actuels, HDRI Haven/Poly Haven inclus) ET le format PLAT (non
    compresse) — PAS l'ancien RLE "repeat previous pixel" (marginal,
    fichiers tres anciens des annees 1990) : None dans ce cas, comme pour
    tout fichier illisible/non exploitable ailleurs dans ce module."""
    if not _optional._NUMPY_AVAILABLE:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    try:
        pos = data.index(b"\n") + 1
        if not data.startswith(b"#?"):
            return None
        # En-tete texte (FORMAT=.../EXPOSURE=.../commentaires) jusqu'a la
        # PREMIERE ligne vide.
        while True:
            nl = data.index(b"\n", pos)
            if data[pos:nl] == b"":
                pos = nl + 1
                break
            pos = nl + 1
        # Ligne de resolution ("-Y H +X W", quasi-universelle — les
        # variantes retournees/miroir sont ignorees ici, sans consequence
        # pour une simple vignette).
        nl = data.index(b"\n", pos)
        res_parts = data[pos:nl].decode("ascii", errors="ignore").split()
        pos = nl + 1
        if len(res_parts) != 4:
            return None
        h, w = int(res_parts[1]), int(res_parts[3])
        if h <= 0 or w <= 0:
            return None
    except (ValueError, IndexError, UnicodeDecodeError):
        return None

    rgbe = _optional.np.zeros((h, w, 4), dtype=_optional.np.uint8)
    try:
        for y in range(h):
            if pos + 4 > len(data):
                return None
            b0, b1, b2, b3 = data[pos], data[pos + 1], data[pos + 2], data[pos + 3]
            if b0 == 2 and b1 == 2 and 8 <= w < 0x8000 and (b2 << 8 | b3) == w:
                pos += 4
                row = _optional.np.zeros((4, w), dtype=_optional.np.uint8)
                for channel in range(4):
                    x = 0
                    while x < w:
                        count = data[pos]
                        pos += 1
                        if count > 128:
                            count -= 128
                            row[channel, x:x + count] = data[pos]
                            pos += 1
                        else:
                            row[channel, x:x + count] = _optional.np.frombuffer(
                                data, dtype=_optional.np.uint8, count=count, offset=pos)
                            pos += count
                        x += count
                rgbe[y] = row.T
            else:
                # Ancien format PLAT (4 octets/pixel, pas de RLE) — repli
                # simple, pas l'ancien RLE "repeat previous pixel" (voir
                # remarque de tete).
                row = _optional.np.frombuffer(data, dtype=_optional.np.uint8, count=w * 4, offset=pos).reshape(w, 4)
                pos += w * 4
                rgbe[y] = row
    except (ValueError, IndexError):
        return None

    e = rgbe[..., 3].astype(_optional.np.int32)
    # Decodage RGBE standard (voir rgbe2float de Radiance) : mantisse
    # (0-255) * 2^(exposant-128-8), 0 si exposant nul (pixel noir).
    scale = _optional.np.where(e > 0, _optional.np.exp2((e - 136).astype(_optional.np.float32)), 0.0)
    rgb = rgbe[..., :3].astype(_optional.np.float32) * scale[..., None]

    rgb = _optional.np.clip(rgb, 0.0, None)
    rgb = rgb / (1.0 + rgb)             # tone-mapping Reinhard
    rgb = _optional.np.power(rgb, 1.0 / 2.2)      # gamma sRGB approche
    rgb8 = _optional.np.clip(rgb * 255.0 + 0.5, 0, 255).astype(_optional.np.uint8)

    hh, ww = rgb8.shape[:2]
    longest = max(hh, ww)
    if longest > max_dim:
        step = max(1, longest // max_dim)
        rgb8 = rgb8[::step, ::step]
    rgb8 = _optional.np.ascontiguousarray(rgb8)
    hh, ww = rgb8.shape[:2]
    return QImage(rgb8.data, ww, hh, ww * 3, QImage.Format_RGB888).copy()

def _decode_2d_image(path: Path, max_dim: int, progress_callback=None, cancel_event=None) -> QImage | None:
    """Decode all static 2D preview formats to a bounded QImage."""
    suffix = path.suffix.lower()
    if progress_callback:
        progress_callback(12, f"Lecture de l'image 2D {suffix}")
    if suffix in DWG_EXTENSIONS:
        image = _dwg._decode_dwg_image(path, max_dim, progress_callback, cancel_event)
    elif suffix in DXF_EXTENSIONS:
        image = _dwg._render_dxf_file(path, max_dim, progress_callback)
    elif suffix in PDF_EXTENSIONS:
        image = _pdf._render_pdf_page(path, max_dim)
    elif suffix in ILLUSTRATOR_EXTENSIONS:
        image = _pdf._decode_ai_image(path, max_dim)
    elif suffix in PSD_EXTENSIONS:
        image = _decode_psd_thumbnail(path)
    elif suffix in EXR_EXTENSIONS:
        image = _decode_exr_image(path, max_dim)
    elif suffix in HDR_EXTENSIONS:
        image = _decode_hdr_image(path, max_dim)
    elif suffix in CUBE_EXTENSIONS:
        image = _decode_cube_image(path, max_dim)
    elif suffix in FONT_EXTENSIONS:
        image = _font._decode_font_image(path, max_dim)
    elif suffix in ABR_EXTENSIONS:
        image = _abr._decode_abr_image(path, max_dim)
    elif suffix in RAW_EXTENSIONS:
        image = _decode_raw_image(path, max_dim)
    elif suffix in TX_EXTENSIONS:
        image = _decode_tx_image(path, max_dim)
    else:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > max_dim:
            scale = max_dim / max(size.width(), size.height())
            reader.setScaledSize(QSize(
                max(1, round(size.width() * scale)), max(1, round(size.height() * scale)),
            ))
        image = reader.read()
    if image is None or image.isNull():
        return None
    if max(image.width(), image.height()) > max_dim:
        image = image.scaled(max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image

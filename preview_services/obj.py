"""Décodage et rastérisation OBJ de secours.

Carte et pièges : docs/agents/apercus.md.
"""

import math
from pathlib import Path
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from . import blender as _blender
from . import executables as _executables
from . import optional as _optional
from . import profiles as _profiles

# Camera fixe en haut a droite, axes Z-up : yaw autour de Z, puis pitch
# autour de X. L'ecran projette X horizontal et Z vertical.
_OBJ_YAW = math.radians(-20)

_OBJ_PITCH = math.radians(20)

def _decode_obj_image(path: Path, max_dim: int, progress_callback=None, cancel_event=None, render_mode: str = "low", profile_override=None) -> QImage | None:
    """Produit une image opaque en wireframe depuis un OBJ Wavefront."""
    eevee_image = _blender._render_wireframe_eevee(path, max_dim, progress_callback, cancel_event, render_mode=render_mode, profile_override=profile_override)
    if eevee_image is not None:
        return eevee_image
    if cancel_event is not None and cancel_event.is_set():
        return None
    template_path = Path(__file__).resolve().parent.parent / "files" / str(_profiles._render_profile(render_mode, profile_override)["template"])
    if _executables._blender_executable() and template_path.is_file():
        # Ne pas substituer silencieusement un rendu different du template.
        return None
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []   # triangles (fan) d'indices dans `vertices`
    wire_edges: list[tuple[int, int]] = []   # aretes des polygones sources, sans diagonales de triangulation
    source_y_up = False
    try:
        file_size = path.stat().st_size
    except OSError:
        return None
    last_parse_percent = -1
    if progress_callback:
        progress_callback(1, "Lecture du maillage OBJ")

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            while True:
                line = f.readline()
                if not line:
                    break
                if line.lower().startswith("# file exported by zbrush"):
                    # Dans les OBJ ZBrush de cette collection, l'axe vertical
                    # source est Y; le convertit vers la convention du rendu Z-up.
                    source_y_up = True
                elif line.startswith("v "):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
                        except ValueError:
                            pass
                elif line.startswith("f ") and len(faces) < _profiles.OBJ_PREVIEW_MAX_TRIANGLES:
                    idx = []
                    for tok in line.split()[1:]:
                        try:
                            n = int(tok.split("/", 1)[0])
                        except ValueError:
                            idx = []
                            break
                        # Index OBJ 1-based, negatif = relatif a la fin de la
                        # liste de sommets deja lus.
                        idx.append(n - 1 if n > 0 else len(vertices) + n)
                    if len(idx) >= 3:
                        if all(0 <= vertex < len(vertices) for vertex in idx):
                            wire_edges.extend((idx[i], idx[(i + 1) % len(idx)]) for i in range(len(idx)))
                        for i in range(1, len(idx) - 1):
                            faces.append((idx[0], idx[i], idx[i + 1]))
                            if len(faces) >= _profiles.OBJ_PREVIEW_MAX_TRIANGLES:
                                break
                if progress_callback and file_size:
                    percent = min(24, int(f.tell() * 24 / file_size))
                    if percent > last_parse_percent:
                        last_parse_percent = percent
                        progress_callback(percent, f"Lecture OBJ : {percent * 100 // 24}% du fichier")
    except OSError:
        return None

    if source_y_up:
        vertices = [(x, -z, y) for x, y, z in vertices]
        if progress_callback:
            progress_callback(25, "Conversion des coordonnées ZBrush Y-up vers Z-up")
    if not vertices or not faces:
        if progress_callback:
            progress_callback(100, "Aucune géométrie exploitable")
        return None
    # Une arete partagee par deux faces ne doit etre dessinee qu'une fois.
    wire_edges = list(dict.fromkeys((min(a, b), max(a, b)) for a, b in wire_edges if a != b))
    # Ne pas sous-echantillonner les faces : supprimer des triangles de façon
    # uniforme ouvre des trous dans la surface et donne un aspect « éclaté ».
    if len(wire_edges) > _profiles.OBJ_PREVIEW_RENDER_EDGES:
        stride = math.ceil(len(wire_edges) / _profiles.OBJ_PREVIEW_RENDER_EDGES)
        wire_edges = wire_edges[::stride]

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    cx, cy, cz = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
    extent = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1.0

    cos_y, sin_y = math.cos(_OBJ_YAW), math.sin(_OBJ_YAW)
    cos_p, sin_p = math.cos(_OBJ_PITCH), math.sin(_OBJ_PITCH)
    transformed: list[tuple[float, float, float]] = []
    for x, y, z in vertices:
        x, y, z = (x - cx) / extent, (y - cy) / extent, (z - cz) / extent
        x, y = x * cos_y - y * sin_y, x * sin_y + y * cos_y    # yaw autour de Z
        y, z = y * cos_p - z * sin_p, y * sin_p + z * cos_p    # pitch autour de X
        transformed.append((x, y, z))

    # Etendue projetee (x, z) reelle apres rotation, pour cadrer pile le
    # modele quelle que soit son orientation d'origine.
    proj_xs = [p[0] for p in transformed]
    proj_ys = [p[2] for p in transformed]
    span = max(max(proj_xs) - min(proj_xs), max(proj_ys) - min(proj_ys)) or 1.0
    scale = (max_dim * 0.82) / span
    ox = max_dim / 2 - (min(proj_xs) + max(proj_xs)) / 2 * scale
    oy = max_dim / 2 + (min(proj_ys) + max(proj_ys)) / 2 * scale

    def to_screen(p: tuple[float, float, float]) -> QPointF:
        return QPointF(p[0] * scale + ox, -p[2] * scale + oy)

    # Ajuste les plans selon la profondeur reelle, avec les bornes de
    # reference de l'utilisateur (near >= 0.1, far <= 10000). Les sommets
    # sont normalises avant cette etape : les valeurs restent adaptees au
    # modele plutot que d'utiliser systematiquement toute la plage.
    depth_values = [p[1] for p in transformed]
    depth_span = max(max(depth_values) - min(depth_values), 1e-4)
    near_clip = max(0.1, depth_span * 0.01)
    far_clip = min(10000.0, max(near_clip + 0.1, near_clip + depth_span * 1.05))
    depth_max = max(depth_values)
    camera_depth = [-(depth_max - value + near_clip) for value in depth_values]
    if progress_callback:
        progress_callback(26, f"Caméra Z-up : near={near_clip:.4g}, far={far_clip:.4g}")

    vertex_shade: list[float] = []  # conservé dans la signature du rasteriseur
    base_rgb = (190, 190, 196)

    if _optional._NUMPY_AVAILABLE:
        return _rasterize_obj_numpy(
            transformed, faces, vertex_shade, max_dim, scale, ox, oy, base_rgb, wire_edges,
            progress_callback=progress_callback, camera_depth=camera_depth,
            near_clip=near_clip, far_clip=far_clip,
        )
    return _rasterize_obj_qpainter(
        transformed, faces, vertex_shade, max_dim, to_screen, base_rgb, wire_edges,
        progress_callback=progress_callback,
    )

def _rasterize_obj_numpy(
    transformed: list[tuple[float, float, float]], faces: list[tuple[int, int, int]],
    vertex_shade: list[float], max_dim: int, scale: float, ox: float, oy: float,
    base_rgb: tuple[int, int, int], wire_edges: list[tuple[int, int]],
    camera_depth: list[float], near_clip: float, far_clip: float, progress_callback=None,
) -> QImage:
    """Construit un z-buffer pour masquer les arêtes cachées et trace un
    wireframe opaque, sans coloration ni occlusion ambiante."""
    supersample = 2.0 / 3.0
    render_dim = int(round(max_dim * supersample))
    r_scale, r_ox, r_oy = scale * supersample, ox * supersample, oy * supersample

    n = len(transformed)
    xs = _optional.np.empty(n, dtype=_optional.np.float64)
    ys = _optional.np.empty(n, dtype=_optional.np.float64)
    zs = _optional.np.empty(n, dtype=_optional.np.float64)
    for i, (x, y, z) in enumerate(transformed):
        xs[i], ys[i], zs[i] = x, y, z
    screen_x = xs * r_scale + r_ox
    screen_y = -zs * r_scale + r_oy
    depth_values = _optional.np.asarray(camera_depth, dtype=_optional.np.float64)

    color_buf = _optional.np.empty((render_dim, render_dim, 3), dtype=_optional.np.uint8)
    color_buf[:, :] = (238, 240, 242)
    depth_buf = _optional.np.full((render_dim, render_dim), -_optional.np.inf, dtype=_optional.np.float64)

    face_step = max(1, len(faces) // 20)
    if progress_callback:
        progress_callback(27, "Projection et préparation du z-buffer")
    for face_index, (a, b, c) in enumerate(faces):
        if progress_callback and face_index % face_step == 0:
            progress_callback(28 + int(face_index * 55 / max(1, len(faces))),
                              f"Rendu des faces : {face_index + 1}/{len(faces)}")
        x0, y0, z0 = screen_x[a], screen_y[a], depth_values[a]
        x1, y1, z1 = screen_x[b], screen_y[b], depth_values[b]
        x2, y2, z2 = screen_x[c], screen_y[c], depth_values[c]

        min_x = max(int(math.floor(min(x0, x1, x2))), 0)
        max_x = min(int(math.ceil(max(x0, x1, x2))), render_dim - 1)
        min_y = max(int(math.floor(min(y0, y1, y2))), 0)
        max_y = min(int(math.ceil(max(y0, y1, y2))), render_dim - 1)
        if min_x > max_x or min_y > max_y:
            continue

        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-9:
            continue   # triangle degenere (aire nulle en projection)

        px = _optional.np.arange(min_x, max_x + 1, dtype=_optional.np.float64) + 0.5
        py = _optional.np.arange(min_y, max_y + 1, dtype=_optional.np.float64) + 0.5
        gx, gy = _optional.np.meshgrid(px, py)

        l0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / denom
        l1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / denom
        l2 = 1.0 - l0 - l1

        inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not inside.any():
            continue

        z_interp = l0 * z0 + l1 * z1 + l2 * z2
        region_depth = depth_buf[min_y:max_y + 1, min_x:max_x + 1]
        in_clip_range = (z_interp <= -near_clip) & (z_interp >= -far_clip)
        closer = inside & in_clip_range & (z_interp > region_depth)
        if not closer.any():
            continue

        region_depth[closer] = z_interp[closer]

    # Conversion de l'image supersamplee : le wireframe est dessine avant
    # cette reduction pour rester net et fin dans l'apercu final.
    rgb8 = _optional.np.clip(color_buf, 0, 255).astype(_optional.np.uint8)
    rgb8 = _optional.np.ascontiguousarray(rgb8)
    # Dessine seulement les aretes des faces source, a la resolution
    # supersamplee, puis reduit proprement : les diagonales creees par la
    # triangulation interne ne deviennent pas visibles.
    image = QImage(rgb8.data, render_dim, render_dim, render_dim * 3, QImage.Format_RGB888).copy()
    if wire_edges:
        if progress_callback:
            progress_callback(93, "Traçage du wireframe des faces")
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(0, 0, 0), 0.75))
        edge_step = max(1, len(wire_edges) // 6)
        for edge_index, (a, b) in enumerate(wire_edges):
            x0, y0, z0 = screen_x[a], screen_y[a], depth_values[a]
            x1, y1, z1 = screen_x[b], screen_y[b], depth_values[b]
            steps = max(1, int(math.ceil(max(abs(x1 - x0), abs(y1 - y0)))))
            run_start = None
            previous = None
            for step in range(steps + 1):
                t = step / steps
                x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                ix, iy = int(round(x)), int(round(y))
                visible = False
                if 0 <= ix < render_dim and 0 <= iy < render_dim:
                    surface_depth = depth_buf[iy, ix]
                    edge_depth = z0 + (z1 - z0) * t
                    visible = _optional.np.isfinite(surface_depth) and edge_depth >= surface_depth - 0.025
                if visible:
                    point = QPointF(x, y)
                    if run_start is None:
                        run_start = point
                    previous = point
                elif run_start is not None:
                    if previous is not None:
                        painter.drawLine(run_start, previous)
                    run_start = previous = None
            if run_start is not None and previous is not None:
                painter.drawLine(run_start, previous)
            if progress_callback and edge_index % edge_step == 0:
                progress_callback(93 + int(edge_index * 6 / max(1, len(wire_edges))),
                                  f"Wireframe : {edge_index + 1}/{len(wire_edges)} arêtes")
        painter.end()
    if progress_callback:
        progress_callback(99, "Mise à l’échelle et finalisation")
    return image.scaled(max_dim, max_dim, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

def _rasterize_obj_qpainter(
    transformed: list[tuple[float, float, float]], faces: list[tuple[int, int, int]],
    vertex_shade: list[float], max_dim: int, to_screen, base_rgb: tuple[int, int, int],
    wire_edges: list[tuple[int, int]], progress_callback=None,
) -> QImage:
    """Repli opaque sans shader : dessine uniquement les aretes du maillage."""
    image = QImage(max_dim, max_dim, QImage.Format_RGB32)
    image.fill(QColor(238, 240, 242))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QPen(QColor(0, 0, 0), 0.7))
    edge_step = max(1, len(wire_edges) // 8)
    for edge_index, (a, b) in enumerate(wire_edges):
        painter.drawLine(to_screen(transformed[a]), to_screen(transformed[b]))
        if progress_callback and edge_index % edge_step == 0:
            progress_callback(35 + int(edge_index * 63 / max(1, len(wire_edges))),
                              f"Wireframe : {edge_index + 1}/{len(wire_edges)} aretes")
    painter.end()
    if progress_callback:
        progress_callback(99, "Finalisation de l'image opaque")
    return image

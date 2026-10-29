"""Rendu Blender EEVEE et script embarqué.

Carte et pièges : docs/agents/apercus.md.
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path
from PySide6.QtGui import QImage
from config import DATA_DIR
from . import executables as _executables
from . import profiles as _profiles
from . import render_log as _render_log

def _render_wireframe_eevee(path: Path, max_dim: int, progress_callback=None, cancel_event=None, kind_override=None, render_mode: str = "low", profile_override=None) -> QImage | None:
    """Rend l'objet dans la scene Eevee du template, avec son eclairage."""
    blender = _executables._blender_executable()
    if not blender:
        return None
    suffix = path.suffix.lower()
    profile = _profiles._render_profile(render_mode, profile_override)
    wireframe_thickness = float(profile["wireframe_thickness"])
    output_format = str(profile["format"]).strip().upper()
    turntable_output = str(profile.get("_turntable_output", ""))
    if turntable_output:
        output_format = "PNG"
    output_extensions = {"PNG": ".png", "JPEG": ".jpg", "BMP": ".bmp"}
    if output_format not in output_extensions:
        if progress_callback:
            progress_callback(99, "Format de rendu non pris en charge : " + output_format)
        return None
    script = r'''import bpy, os, sys, math, shutil
from mathutils import Matrix, Vector
bpy.context.preferences.edit.use_global_undo = False
src, dst, status_path, kind, output_dim, output_format = sys.argv[sys.argv.index("--") + 1:sys.argv.index("--") + 7]
output_dim = int(output_dim)
turntable_output = __TURNTABLE_OUTPUT__
def report(percent, text):
    try:
        with open(status_path, "w", encoding="utf-8") as f: f.write("%d|%s" % (percent, text))
    except OSError: pass
def fail(message):
    report(99, message)
    raise RuntimeError(message)
report(3, "Ouverture de la scene de rendu")
if __UNRECOGNIZED_FIELDS__:
    report(4, "Parametres non reconnus : " + ", ".join(__UNRECOGNIZED_FIELDS__))
scene = bpy.context.scene
if scene.camera is None: fail("La scene de preview ne contient pas de camera")
view_name = __VIEW_NAME__
if view_name and view_name.casefold() not in {"camera du fichier blender", "camera du template", "camera", "template"}:
    selected_camera = bpy.data.objects.get(view_name)
    if selected_camera is None or selected_camera.type != "CAMERA":
        fail("Camera demandee introuvable dans le template : " + view_name)
    scene.camera = selected_camera
lighting_path = __LIGHTING_PATH__
if not __LIGHTING_SCENE__:
    for light in scene.objects:
        if light.type == "LIGHT":
            light.hide_render = True
if lighting_path:
    if not os.path.isfile(lighting_path):
        fail("Fichier d'eclairage HDRI introuvable : " + lighting_path)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Pipeline HDRI World")
    scene.world.use_nodes = True
    world_nodes = scene.world.node_tree.nodes
    world_links = scene.world.node_tree.links
    background = next((node for node in world_nodes if node.type == "BACKGROUND"), None)
    if background is None:
        background = world_nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = __HDRI_STRENGTH__
    world_output = next((node for node in world_nodes if node.type == "OUTPUT_WORLD"), None)
    if world_output is None:
        world_output = world_nodes.new("ShaderNodeOutputWorld")
    if not any(link.from_node == background and link.to_node == world_output for link in world_links):
        world_links.new(background.outputs["Background"], world_output.inputs["Surface"])
    environment = world_nodes.new("ShaderNodeTexEnvironment")
    environment.image = bpy.data.images.load(lighting_path, check_existing=True)
    world_links.new(environment.outputs["Color"], background.inputs["Color"])
bbox_obj = bpy.data.objects.get("Cube")
if bbox_obj is None or bbox_obj.type != "MESH": fail("Le cube servant de bounding box est introuvable")
bbox_corners = [bbox_obj.matrix_world @ Vector(corner) for corner in bbox_obj.bound_box]
bbox_min = Vector(tuple(min(p[i] for p in bbox_corners) for i in range(3)))
bbox_max = Vector(tuple(max(p[i] for p in bbox_corners) for i in range(3)))
target_center = (bbox_min + bbox_max) * 0.5
target_size = max(bbox_max - bbox_min)
if target_size <= 1e-12: fail("Le cube de bounding box a une taille nulle")
initial_objects = {obj.as_pointer() for obj in scene.objects}
report(8, "Import du fichier dans le template")
try:
    if kind in {"abc", "maya", "houdini"}:
        bpy.ops.wm.alembic_import(filepath=src, scale=1.0, validate_meshes=False)
    elif kind == "blend":
        with bpy.data.libraries.load(src, link=False) as (data_from, data_to):
            if not data_from.scenes: raise RuntimeError("Aucune scene dans le fichier .blend")
            data_to.scenes = [data_from.scenes[0]]
        source_scene = data_to.scenes[0]
        if source_scene is None: raise RuntimeError("Scene source introuvable")
        # Visibilite de RENDU du fichier source, relevee AVANT d'exposer les collections
        # (voir expose_imported_collection) : une collection masquee au rendu ou exclue
        # du view layer (par exemple "SAVE", qui archive d'anciennes versions du modele)
        # ne doit pas entrer dans l'apercu, sinon ses objets sont fusionnes avec les
        # vrais et on obtient plusieurs modeles superposes.
        renderable_names = set()
        def collect_renderable(layer_collection, parent_ok):
            collection = layer_collection.collection
            ok = parent_ok and not layer_collection.exclude and not collection.hide_render
            if ok:
                for source_obj in collection.objects:
                    if not source_obj.hide_render:
                        renderable_names.add(source_obj.name)
            for child_layer in layer_collection.children:
                collect_renderable(child_layer, ok)
        try:
            collect_renderable(source_scene.view_layers[0].layer_collection, True)
        except (AttributeError, IndexError):
            renderable_names = set()
        source_objects = list(source_scene.objects)
        if not any(o.type == "MESH" and o.name in renderable_names for o in source_objects):
            renderable_names = {o.name for o in source_objects}   # rien de renderable : on ne filtre pas
        # Une master collection de Scene est un ID embarque : son lien dans
        # une AUTRE scene n'est pas fiable apres sauvegarde/rechargement.
        # Utiliser une vraie collection pour le snapshot de reprise.
        imported_collection = bpy.data.collections.new("Pipeline Imported Geometry")
        scene.collection.children.link(imported_collection)
        for source_obj in source_scene.collection.objects:
            imported_collection.objects.link(source_obj)
        for child in source_scene.collection.children:
            imported_collection.children.link(child)
        def expose_imported_collection(collection):
            collection.hide_viewport = False
            collection.hide_render = False
            for child in collection.children:
                expose_imported_collection(child)
        expose_imported_collection(imported_collection)
        bpy.context.view_layer.update()
        for source_obj in source_objects:
            if source_obj.name not in renderable_names:
                for owner in list(source_obj.users_collection):
                    owner.objects.unlink(source_obj)
                continue
            source_obj.hide_render = source_obj.type != "MESH"
    elif kind == "fbx":
        try:
            bpy.ops.import_scene.fbx(filepath=src)
        except Exception as exc:
            raise RuntimeError("Import FBX impossible : %s" % exc)
    else:
        try:
            bpy.ops.wm.obj_import(filepath=src, global_scale=1.0, clamp_size=0.0,
                forward_axis='NEGATIVE_Z', up_axis='Y', use_split_objects=True,
                use_split_groups=False, import_vertex_groups=False, validate_meshes=True,
                close_spline_loops=True, mtl_name_collision_mode='MAKE_UNIQUE')
        except (AttributeError, TypeError):
            bpy.ops.import_scene.obj(filepath=src, global_clamp_size=0.0,
                axis_forward='-Z', axis_up='Y', use_split_objects=True,
                use_split_groups=False, use_image_search=False)
except Exception as exc:
    fail("Import Blender impossible : %s" % exc)
objects = [o for o in scene.objects if o.as_pointer() not in initial_objects and o.type == "MESH"]
if not objects: fail("Aucun maillage importe par Blender")
for obj in objects:
    obj.hide_viewport = False
    obj.hide_set(False)
bpy.context.view_layer.update()
if kind in {"ma", "mb", "maya", "houdini"}:
    report(16, "Selection de tous les objets de la scene et fusion avec Ctrl+J")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if not turntable_output:
        try:
            bpy.ops.object.join()
        except Exception as exc:
            fail("Impossible de fusionner les objets Maya : %s" % exc)
        objects = [bpy.context.view_layer.objects.active]
    report(18, "Application de Ctrl+A - All Transforms avant le scale")
    try:
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    except Exception as exc:
        fail("Impossible d'appliquer All Transforms au maillage Maya fusionne : %s" % exc)
    bpy.context.view_layer.update()
subdivision_levels = max(0, int(__SUBDIVISIONS__))
if subdivision_levels > 0:
    report(13, "Ajout du modifier Subdivision : niveau %d" % subdivision_levels)
    for obj in objects:
        subdivision = obj.modifiers.new("Subdivision de rendu", "SUBSURF")
        subdivision.subdivision_type = "CATMULL_CLARK"
        subdivision.levels = subdivision_levels
        subdivision.render_levels = subdivision_levels
report(14, "Application de tous les modifiers avant le cadrage")
for obj in objects:
    modifier_names = [mod.name for mod in obj.modifiers]
    if modifier_names:
        obj.data = obj.data.copy()
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for modifier_name in modifier_names:
            modifier = obj.modifiers.get(modifier_name)
            if modifier is None:
                continue
            # Appliquer l'etat de rendu, pas celui du viewport. Un Subsurf
            # de niveau viewport 0 mais rendu 2 ne doit pas rester sur
            # l'objet actif et subdiviser tout le modele apres la fusion.
            if not modifier.show_render:
                obj.modifiers.remove(modifier)
                continue
            modifier.show_viewport = True
            if modifier.type in {'SUBSURF', 'MULTIRES'}:
                modifier.levels = modifier.render_levels
                if modifier.render_levels == 0:
                    obj.modifiers.remove(modifier)
                    continue
            try:
                bpy.ops.object.modifier_apply(modifier=modifier_name)
            except Exception as exc:
                error_text = str(exc)
                if "disabled" in error_text.casefold() or "skipping apply" in error_text.casefold():
                    report(15, "Modifier ignore car desactive : %s sur %s" % (modifier_name, obj.name))
                    remaining_modifier = obj.modifiers.get(modifier_name)
                    if remaining_modifier is not None:
                        obj.modifiers.remove(remaining_modifier)
                    continue
                fail("Impossible d'appliquer le modifier %s sur %s : %s" % (modifier_name, obj.name, exc))
bpy.context.view_layer.update()
for light in scene.objects:
    if light.type == "LIGHT" and hasattr(light.data, "use_shadow"):
        light.data.use_shadow = __SHADOWS__
    if light.type == "LIGHT" and hasattr(light.data, "energy"):
        light.data.energy *= __LIGHTING_SCENE_STRENGTH__
for obj in scene.objects:
    if any(marker in obj.name.casefold() for marker in ("ground", "sol", "floor")):
        obj.hide_render = not __GROUND_SHADOWS__
if len(objects) > 1 and not turntable_output:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    objects = [bpy.context.view_layer.objects.active]
report(20, "Calcul de la bounding box de l'objet")
world_matrices = {obj: obj.matrix_world.copy() for obj in objects}
world_points = [world_matrices[obj] @ vertex.co for obj in objects for vertex in obj.data.vertices]
if not world_points: fail("Aucune geometrie exploitable")
source_min = Vector(tuple(min(p[i] for p in world_points) for i in range(3)))
source_max = Vector(tuple(max(p[i] for p in world_points) for i in range(3)))
del world_points
source_center = (source_min + source_max) * 0.5
source_size = max(source_max - source_min)
if source_size <= 1e-12: fail("La bounding box de l'objet a une taille nulle")
uniform_scale = target_size / source_size
transform = Matrix.Translation(target_center) @ Matrix.Scale(uniform_scale, 4) @ Matrix.Translation(-source_center)
# Une seule transformation est calculee depuis la bounding box globale puis
# cuite dans la geometrie. Les objets Maya ont ete joints et leurs transforms
# appliques avant le calcul de cette bounding box.
report(32, "Scale et centrage du maillage fusionne dans le cube" if kind in {"ma", "mb", "maya", "houdini"} else "Mise a l'echelle et centrage dans le cube")
for obj in objects:
    original_world = world_matrices[obj]
    obj.data = obj.data.copy()
    obj.data.transform(transform @ original_world)
    obj.parent = None
    obj.matrix_world = Matrix.Identity(4)
    if turntable_output:
        obj.animation_data_clear()
        obj.constraints.clear()
        obj.data.animation_data_clear()
        if obj.data.shape_keys is not None:
            obj.data.shape_keys.animation_data_clear()
    for polygon in obj.data.polygons: polygon.use_smooth = __SHADE_SMOOTH__
    obj.data.materials.clear()
if __RECALCULATE_NORMALS__:
    report(35, "Recalcul des normales")
    for obj in objects:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception as exc:
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass
            fail("Impossible de recalculer les normales sur %s : %s" % (obj.name, exc))
shader_source = bpy.data.materials.get(__SHADER_NAME__) if __SHADER_NAME__ else None
if shader_source is None and __SHADER_NAME__:
    # Certains templates historiques nomment le matériau de lookdev
    # "Lookdev" ou "Material0", alors que le profil le désigne comme
    # "rendu_apercu". Résoudre ces alias permet d'appliquer le shader réel
    # présent dans le template au lieu de recréer un Principled par défaut.
    requested_shader = __SHADER_NAME__.casefold()
    aliases = {"rendu_apercu", "rendu apercu", "rendu aperçu"}
    if requested_shader in aliases:
        for candidate_name in ("Lookdev", "Material0", "Material"):
            shader_source = bpy.data.materials.get(candidate_name)
            if shader_source is not None:
                report(45, "Shader de rendu applique : " + shader_source.name)
                break
surface = shader_source.copy() if shader_source is not None else bpy.data.materials.new("Preview - surface opaque")
surface.name = "Preview - " + (__SHADER_NAME__ or "surface opaque")
surface.diffuse_color = __BASE_COLOR_WITH_ALPHA__
surface.use_nodes = True
if __BASE_ALPHA__ < 1.0:
    if hasattr(surface, "surface_render_method"):
        surface.surface_render_method = "DITHERED"
    elif hasattr(surface, "blend_method"):
        surface.blend_method = "BLEND"
principled = surface.node_tree.nodes.get("Principled BSDF")
if principled and shader_source is None:
    principled.inputs["Base Color"].default_value = surface.diffuse_color
    principled.inputs["Roughness"].default_value = __ROUGHNESS__
    principled.inputs["Metallic"].default_value = __METALLIC__
    principled.inputs["Alpha"].default_value = __BASE_ALPHA__
    coat_weight = principled.inputs.get("Coat Weight")
    if coat_weight is not None: coat_weight.default_value = __COAT_WEIGHT__
    coat_roughness = principled.inputs.get("Coat Roughness")
    if coat_roughness is not None: coat_roughness.default_value = __COAT_ROUGHNESS__
    if __AMBIENT_OCCLUSION__:
        # Le noeud AO des materiaux est pris en charge par Cycles, pas par
        # Eevee. On bascule donc le profil AO vers Cycles pour garantir un
        # effet reel dans le rendu final.
        ao_node = surface.node_tree.nodes.new("ShaderNodeAmbientOcclusion")
        ao_node.inputs["Distance"].default_value = __AMBIENT_OCCLUSION_DISTANCE__
        if hasattr(ao_node, "samples"):
            ao_node.samples = 16
        ao_strength = surface.node_tree.nodes.new("ShaderNodeMath")
        ao_strength.operation = "MULTIPLY"
        ao_strength.inputs[1].default_value = __AMBIENT_OCCLUSION_STRENGTH__
        ao_color = surface.node_tree.nodes.new("ShaderNodeMixRGB")
        ao_color.blend_type = "MIX"
        ao_color.inputs[1].default_value = __BASE_COLOR_WITH_ALPHA__
        ao_color.inputs[2].default_value = (0.0, 0.0, 0.0, __BASE_ALPHA__)
        surface.node_tree.links.new(ao_node.outputs["AO"], ao_strength.inputs[0])
        surface.node_tree.links.new(ao_strength.outputs[0], ao_color.inputs[0])
        surface.node_tree.links.new(ao_color.outputs[0], principled.inputs["Base Color"])
wire_material = bpy.data.materials.new("Preview - wireframe noir")
wire_material.diffuse_color = __WIRE_COLOR__
wire_material.use_nodes = True
if __WIRE_ALPHA__ < 1.0:
    if hasattr(wire_material, "surface_render_method"):
        wire_material.surface_render_method = "DITHERED"
    elif hasattr(wire_material, "blend_method"):
        wire_material.blend_method = "BLEND"
nodes = wire_material.node_tree.nodes
nodes.clear()
output = nodes.new("ShaderNodeOutputMaterial")
wire_shader = nodes.new("ShaderNodeBsdfPrincipled")
wire_shader.inputs["Base Color"].default_value = __WIRE_COLOR__
wire_shader.inputs["Roughness"].default_value = 1.0
wire_shader.inputs["Alpha"].default_value = __WIRE_ALPHA__
emission_input = wire_shader.inputs.get("Emission Color")
if emission_input is None:
    emission_input = wire_shader.inputs.get("Emission")
if emission_input is not None:
    emission_input.default_value = __WIRE_COLOR__
emission_strength = wire_shader.inputs.get("Emission Strength")
if emission_strength is not None:
    emission_strength.default_value = 1.0
wire_material.node_tree.links.new(wire_shader.outputs["BSDF"], output.inputs["Surface"])
for index, obj in enumerate(objects):
    obj.data.materials.append(surface)
    if __WIREFRAME_ENABLED__:
        obj.data.materials.append(wire_material)
    if index % max(1, len(objects) // 5) == 0:
        report(42 + int(20 * index / max(1, len(objects))), "Preparation du wireframe : objet %d/%d" % (index + 1, len(objects)))
# Grille, axes, curseur et gizmos sont des overlays du viewport, jamais rendus.
for obj in scene.objects:
    if obj.type in {'EMPTY', 'CAMERA'}: obj.hide_render = True
bbox_obj.hide_render = True
scene.camera.hide_render = False

scene.camera.data.clip_start = __CLIP_NEAR__
scene.camera.data.clip_end = __CLIP_FAR__
if __AMBIENT_OCCLUSION__:
    scene.render.engine = "CYCLES"
elif "eevee" in __ENGINE__.casefold():
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"
elif "cycles" in __ENGINE__.casefold():
    scene.render.engine = "CYCLES"
scene.render.resolution_x = output_dim
scene.render.resolution_y = output_dim
scene.render.resolution_percentage = 100
# Respecter le template par defaut ; un profil explicite peut fixer les
# echantillons (notamment pour les tests de memoire a resolution reduite).
if __RENDER_SAMPLES__ > 0:
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = __RENDER_SAMPLES__
    elif hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = __RENDER_SAMPLES__
if turntable_output:
    # Orbite horizontale a la hauteur du centre geometrique final.
    bpy.context.view_layer.update()
    camera = scene.camera
    matrix = camera.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
    radial = Vector((matrix.translation.x - target_center.x,
                     matrix.translation.y - target_center.y, 0.0))
    if radial.length < 1e-6:
        radial = Vector((0.0, -max(target_size * 4.0, 1.0), 0.0))
    camera.animation_data_clear()
    camera.constraints.clear()
    camera.parent = None
    camera.location = target_center + radial
    camera.rotation_mode = 'QUATERNION'
    camera.rotation_quaternion = (-radial).to_track_quat('-Z', 'Y')
    bpy.context.view_layer.update()
def fit_preview_camera(scene, objects, occupancy=0.70):
    import numpy as np
    # Mesurer la geometrie finale, y compris les modifiers encore actifs.
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    chunks = []
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        temporary_mesh = bool(obj.modifiers)
        # Les modifiers ont deja ete appliques. Ne pas recopier le maillage
        # entier uniquement pour lire ses coordonnees de cadrage.
        mesh = evaluated.to_mesh() if temporary_mesh else evaluated.data
        try:
            vertices = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", vertices)
            matrix = np.asarray(evaluated.matrix_world, dtype=np.float64)
            chunks.append(vertices.reshape((-1, 3)) @ matrix[:3, :3].T + matrix[:3, 3])
        finally:
            if temporary_mesh:
                evaluated.to_mesh_clear()
    if not chunks or not any(len(chunk) for chunk in chunks):
        fail("Aucune geometrie pour le cadrage camera")
    points = np.concatenate(chunks)
    del chunks
    if turntable_output:
        # Enveloppe cylindrique : une distance fixe contient la geometrie
        # pour les 72 angles, sans zoom ou recadrage entre les images.
        radial = points[:, :2] - np.array(tuple(target_center)[:2])
        radius = float(np.sqrt((radial * radial).sum(axis=1)).max())
        radius /= math.cos(math.pi / 72.0)
        zmin, zmax = float(points[:, 2].min()), float(points[:, 2].max())
        points = np.array([(target_center.x + radius * math.cos(i * math.tau / 72),
                            target_center.y + radius * math.sin(i * math.tau / 72), z)
                           for i in range(72) for z in (zmin, zmax)])
    camera = scene.camera
    if camera.data.type not in {'PERSP', 'ORTHO'}:
        fail("Cadrage automatique incompatible avec cette camera : " + camera.data.type)
    # Copier la camera evaluee evite qu'un parent ou une animation annule
    # le positionnement dans la scene temporaire de rendu.
    matrix = camera.evaluated_get(depsgraph).matrix_world.copy()
    camera.animation_data_clear()
    camera.constraints.clear()
    camera.parent = None
    camera.matrix_world = matrix
    camera.data = camera.data.copy()
    camera.data.animation_data_clear()
    bpy.context.view_layer.update()
    location, ortho_scale = camera.camera_fit_coords(depsgraph, points.reshape(-1))
    camera.location = location
    bpy.context.view_layer.update()
    inverse = camera.matrix_world.normalized().inverted()
    inverse_array = np.asarray(inverse, dtype=np.float64)
    local_points = points @ inverse_array[:3, :3].T + inverse_array[:3, 3]
    del points
    base_depths = -local_points[:, 2]
    minimum_depth = float(base_depths.min())
    base_location = camera.matrix_world.translation.copy()
    back = camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))
    near = max(camera.data.clip_start, 1e-5)

    def frame_bounds():
        frame = camera.data.view_frame(scene=scene)
        return (min(p.x for p in frame), max(p.x for p in frame),
                min(p.y for p in frame), max(p.y for p in frame), abs(frame[0].z))

    def measure(retreat):
        xmin, xmax, ymin, ymax, frame_depth = frame_bounds()
        if camera.data.type == 'ORTHO':
            projected = local_points[:, :2]
        else:
            if minimum_depth + retreat <= near:
                return float('inf'), None
            projected = local_points[:, :2] * (frame_depth / (base_depths + retreat))[:, None]
        bounds = ((float(projected[:, 0].min()) - xmin) / (xmax - xmin),
                  (float(projected[:, 0].max()) - xmin) / (xmax - xmin),
                  (float(projected[:, 1].min()) - ymin) / (ymax - ymin),
                  (float(projected[:, 1].max()) - ymin) / (ymax - ymin))
        return max(bounds[1] - bounds[0], bounds[3] - bounds[2]), bounds

    if camera.data.type == 'ORTHO':
        camera.data.ortho_scale = max(ortho_scale, 1e-6)
        span, bounds = measure(0.0)
        camera.data.ortho_scale *= span / occupancy
        retreat = max(0.0, near * 1.01 - minimum_depth)
    else:
        # Recherche bornee : toutes les profondeurs restent devant la camera.
        lower = near * 1.01 - minimum_depth
        upper = max(0.0, lower + 1.0)
        for _ in range(60):
            if measure(upper)[0] <= occupancy:
                break
            upper = lower + 2.0 * (upper - lower)
        else:
            fail("Impossible de trouver une distance de cadrage")
        for _ in range(28):
            middle = (lower + upper) * 0.5
            span, bounds = measure(middle)
            if span > occupancy:
                lower = middle
            else:
                upper = middle
            if bounds is not None and abs(span - occupancy) < 0.00001:
                upper = middle
                break
        retreat = upper
    camera.location = base_location + back * retreat
    bpy.context.view_layer.update()
    span, bounds = measure(retreat)
    # Centrer la silhouette projetee avec le decalage optique. Sa taille
    # reste identique ; les marges sur le grand cote deviennent 15%% chacune.
    base_frame = frame_bounds()
    for axis, center, width, index in (
            ('shift_x', (bounds[0] + bounds[1]) * 0.5, base_frame[1] - base_frame[0], 0),
            ('shift_y', (bounds[2] + bounds[3]) * 0.5, base_frame[3] - base_frame[2], 2)):
        value = getattr(camera.data, axis)
        before = frame_bounds()[index]
        setattr(camera.data, axis, value + 1.0)
        derivative = -(frame_bounds()[index] - before) / width
        setattr(camera.data, axis, value + (0.5 - center) / derivative)
    bpy.context.view_layer.update()
    span, bounds = measure(retreat)
    if minimum_depth + retreat <= camera.data.clip_start or float(base_depths.max()) + retreat >= camera.data.clip_end:
        fail("Objet hors des limites near/far de la camera apres cadrage")
    if abs(span - occupancy) > 0.001 or min(bounds) < 0.0 or max(bounds) > 1.0:
        fail("Verification du cadrage camera a %.0f%% echouee" % (occupancy * 100.0))
    report(68, "Cadrage camera : %.2f%% du rendu" % (span * 100.0))

if turntable_output:
    # Import, copies de datablocks, modifiers appliques et fusion laissent
    # des meshes sans utilisateur. Les liberer AVANT l'evaluation wireframe.
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
fit_preview_camera(scene, objects)
if __WIREFRAME_ENABLED__:
    # Ajouter le wireframe apres le cadrage : il ne doit ni influencer
    # la mesure de l'objet, ni garder une epaisseur liee a l'ancienne camera.
    camera = scene.camera
    frame = camera.data.view_frame(scene=scene)
    frame_width = max(p.x for p in frame) - min(p.x for p in frame)
    frame_height = max(p.y for p in frame) - min(p.y for p in frame)
    if camera.data.type == 'PERSP':
        reference_depth = -(camera.matrix_world.normalized().inverted() @ target_center).z
        depth_factor = reference_depth / max(abs(frame[0].z), 1e-8)
        frame_width *= depth_factor
        frame_height *= depth_factor
    world_per_pixel = min(frame_width / max(scene.render.resolution_x, 1),
                          frame_height / max(scene.render.resolution_y, 1))
    thickness_pixels = max(0.0, 1.8 * __WIREFRAME_THICKNESS__)
    for object_index, obj in enumerate(objects):
        wire = obj.modifiers.new("Wireframe fin", "WIREFRAME")
        wire.thickness = world_per_pixel * thickness_pixels
        wire.offset = 0.0
        wire.use_replace = False
        wire.use_even_offset = False
        wire.use_boundary = True
        wire.use_crease = False
        wire.use_relative_offset = False
        wire.material_offset = 1
        if turntable_output:
            # Evaluer chaque composant separement, pas un seul maillage
            # geant issu de la fusion : meme resultat visuel, pic RAM borne.
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=wire.name)
            obj.select_set(False)
            bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
            if object_index % max(1, len(objects) // 5) == 0:
                report(69, "Wireframe statique : composant %d/%d" % (object_index + 1, len(objects)))
    if not turntable_output:
        bpy.context.view_layer.update()
    report(69, "Epaisseur du wireframe apres cadrage : %.2f px" % thickness_pixels)
scene.render.image_settings.file_format = output_format
hide_hdri_background = bool(lighting_path)
# Le fond final est compose cote application lorsque le profil demande un
# rendu opaque. Garder l'alpha jusqu'a cette etape evite les franges du fond
# Blender/template autour de l'objet detoure.
scene.render.image_settings.color_mode = "RGBA"
scene.render.film_transparent = True
scene.render.filepath = dst
if turntable_output:
    # L'objet est statique : seule la camera et les lights tournent. Cuire
    # le wireframe UNE fois evite de reconstruire des millions de faces
    # et leurs caches de depsgraph pour chacun des 72 angles.
    report(69, "Optimisation memoire : preparation du maillage statique du turntable")
    bpy.context.view_layer.update()
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    scene.render.use_persistent_data = False
report(70, "Rendu " + scene.render.engine + " avec la camera du template")
if turntable_output:
    os.makedirs(turntable_output, exist_ok=True)
    camera_matrix = scene.camera.matrix_world.copy()
    lights = [(light, light.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy())
              for light in scene.objects if light.type == 'LIGHT' and not light.hide_render]
    for light, matrix in lights:
        light.animation_data_clear()
        light.data.animation_data_clear()
        light.constraints.clear()
        light.parent = None
        light.rotation_mode = 'QUATERNION'
        light.matrix_world = matrix
    # Tourner aussi l'environnement lumineux HDRI avec les lights.
    hdri_mapping = None
    if lighting_path:
        hdri_coordinates = world_nodes.new("ShaderNodeTexCoord")
        hdri_mapping = world_nodes.new("ShaderNodeMapping")
        world_links.new(hdri_coordinates.outputs["Generated"], hdri_mapping.inputs["Vector"])
        world_links.new(hdri_mapping.outputs["Vector"], environment.inputs["Vector"])
    for frame in range(72):
        scene.frame_set(frame + 1)
        angle = math.tau * frame / 72.0
        orbit = Matrix.Translation(target_center) @ Matrix.Rotation(angle, 4, 'Z') @ Matrix.Translation(-target_center)
        scene.camera.matrix_world = orbit @ camera_matrix
        for light, matrix in lights:
            light.matrix_world = orbit @ matrix
        for animated in [scene.camera] + [light for light, matrix in lights]:
            animated.keyframe_insert(data_path="location", frame=frame + 1)
            animated.keyframe_insert(data_path="rotation_quaternion", frame=frame + 1)
        if hdri_mapping is not None:
            hdri_mapping.inputs["Rotation"].default_value.z = -angle
            hdri_mapping.inputs["Rotation"].keyframe_insert(data_path="default_value", frame=frame + 1)
    # Un seul rendu d'animation conserve l'engine et ses buffers entre les
    # images, contrairement a 72 appels independants a render(write_still).
    scene.frame_start = 1
    scene.frame_end = 72
    scene.frame_step = 1
    scene.render.filepath = os.path.join(turntable_output, "render_####")
    rendered_paths = [scene.render.frame_path(frame=index + 1) for index in range(72)]
    def turntable_progress(render_scene, *_):
        index = render_scene.frame_current - 1
        report(70 + int(28 * index / 72), "Turntable : image %d / 72" % (index + 1))
    bpy.app.handlers.render_pre.append(turntable_progress)
    scene.frame_set(1)
    if __TURNTABLE_PREPARED_SCENE__:
        # Snapshot autonome de la geometrie preparee et des 72 positions.
        # Chaque image sera rendue dans un NOUVEAU processus Blender.
        prepared = __TURNTABLE_PREPARED_SCENE__
        temporary_scene = prepared + ".tmp.blend"
        # Le .blend importe peut ajouter d'autres scenes. Ne sauvegarder
        # que la scene de rendu pour que -b recharge bien celle-ci.
        if bpy.context.window is not None:
            bpy.context.window.scene = scene
        for other_scene in list(bpy.data.scenes):
            if other_scene != scene:
                bpy.data.scenes.remove(other_scene)
        bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=temporary_scene, check_existing=False, compress=True)
        os.replace(temporary_scene, prepared)
        report(98, "Scene du turntable preparee pour la reprise image par image")
    else:
        bpy.ops.render.render(animation=True)
        for index, rendered_path in enumerate(rendered_paths):
            os.replace(rendered_path, os.path.join(turntable_output, "frame_%03d.png" % index))
        scene.render.filepath = dst
        shutil.copyfile(os.path.join(turntable_output, "frame_000.png"), dst)
else:
    bpy.ops.render.render(write_still=True)
report(98, "Apercu Eevee pret")
    '''
    replacements = {
        "__TURNTABLE_PREPARED_SCENE__": repr(str(profile.get("_turntable_prepared_scene", ""))),
        "__RENDER_SAMPLES__": repr(max(0, int(profile.get("samples", 0)))),
        "__TURNTABLE_OUTPUT__": repr(turntable_output),
        "__LIGHTING_PATH__": repr(
            str((Path(__file__).resolve().parent.parent / str(profile.get("lighting_hdri") or profile.get("lighting", ""))).resolve())
            if (bool(profile.get("lighting_hdri_enabled", False)) or bool(profile.get("lighting", "")))
            and str(profile.get("lighting_hdri") or profile.get("lighting", "")).strip()
            and str(profile.get("lighting_hdri") or profile.get("lighting", "")).casefold().strip() not in {
                "eclairage du fichier blender", "éclairage du fichier blender",
                "fichier blender", "template", "none", "aucun",
            }
            else ""
        ),
        "__LIGHTING_SCENE__": repr(bool(profile["lighting_scene"])),
        "__LIGHTING_SCENE_STRENGTH__": repr(max(0.0, float(profile["lighting_scene_strength"]))),
        "__HDRI_STRENGTH__": repr(max(0.0, float(profile["lighting_hdri_strength"]))),
        "__SHADER_NAME__": repr(str(profile.get("shader_name", "")).strip()),
        "__VIEW_NAME__": repr(str(profile.get("view", "camera du fichier blender")).strip()),
        "__UNRECOGNIZED_FIELDS__": repr(profile.get("unrecognized", [])),
        "__WIREFRAME_THICKNESS__": repr(wireframe_thickness),
        "__WIREFRAME_ENABLED__": repr(bool(profile["wireframe"])),
        "__SUBDIVISIONS__": repr(max(0, int(profile.get("subdivisions", 0)))),
        "__RECALCULATE_NORMALS__": repr(bool(profile.get("recalculate_normals", False))),
        "__SHADOWS__": repr(bool(profile["shadows"])),
        "__GROUND_SHADOWS__": repr(bool(profile["ground_shadows"])),
        "__ENGINE__": repr(str(profile["engine"])),
        "__AMBIENT_OCCLUSION__": repr(bool(profile["ambient_occlusion"])),
        "__AMBIENT_OCCLUSION_STRENGTH__": repr(max(0.0, float(profile["ambient_occlusion_strength"]))),
        "__AMBIENT_OCCLUSION_DISTANCE__": repr(max(0.001, float(profile.get("ambient_occlusion_distance", 1.0)))),
        "__SHADE_SMOOTH__": repr(str(profile["shade"]).casefold() == "smooth"),
        "__BASE_COLOR_WITH_ALPHA__": repr(tuple(profile["base_color"][:3]) + (float(profile["base_color"][3]) if len(profile["base_color"]) >= 4 else float(profile["alpha"]),)),
        "__BASE_ALPHA__": repr(float(profile["base_color"][3]) if len(profile["base_color"]) >= 4 else float(profile["alpha"])),
        "__WIRE_COLOR__": repr(tuple(profile["wire_color"])),
        "__WIRE_ALPHA__": repr(float(profile["wire_color"][3]) if len(profile["wire_color"]) >= 4 else 1.0),
        "__METALLIC__": repr(float(profile["metallic"])),
        "__ROUGHNESS__": repr(float(profile["roughness"])),
        "__COAT_WEIGHT__": repr(float(profile["coat_weight"])),
        "__COAT_ROUGHNESS__": repr(float(profile["coat_roughness"])),
        "__ALPHA__": repr(float(profile["alpha"])),
        "__CLIP_NEAR__": repr(float(profile["clip_near"])),
        "__CLIP_FAR__": repr(float(profile["clip_far"])),
        "__FILM_TRANSPARENT__": repr(bool(profile["film_transparent"])),
    }
    for token, value in replacements.items():
        script = script.replace(token, value)
    try:
        with tempfile.TemporaryDirectory(prefix="pipe_eevee_wire_") as temp_dir:
            temp = Path(temp_dir)
            script_path, image_path, status_path = temp / "render.py", temp / ("preview" + output_extensions[output_format]), temp / "status.txt"
            error_path = temp / "blender_error.log"
            script_path.write_text(script, encoding="utf-8")
            error_stream = error_path.open("w", encoding="utf-8", errors="replace")
            kwargs = {"stdout": subprocess.DEVNULL, "stderr": error_stream}
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            template_path = Path(__file__).resolve().parent.parent / "files" / str(profile["template"])
            if not template_path.is_file():
                if progress_callback:
                    progress_callback(99, f"Scene de rendu introuvable : {template_path}")
                error_stream.close()
                return None
            proc = subprocess.Popen(
                [blender, "--background", str(template_path), "--python", str(script_path), "--",
                 str(path.resolve()), str(image_path), str(status_path),
                 kind_override or ("abc" if suffix == ".abc" else "blend" if suffix == ".blend" else "fbx" if suffix == ".fbx" else "obj"), str(profile["resolution"][0]), output_format],
                **kwargs,
            )
            last_status = ""
            # Les subdivisions des modeles complexes peuvent depasser 90 s
            # avant meme le calcul du cadrage. L'annulation reste disponible.
            deadline = time.monotonic() + (600 if int(profile.get("subdivisions", 0)) > 0 else 300)
            if turntable_output:
                deadline = time.monotonic() + 3600
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    error_stream.close()
                    return None
                try:
                    current = status_path.read_text(encoding="utf-8")
                    if current and current != last_status:
                        last_status = current
                        percent, message = current.split("|", 1)
                        if progress_callback:
                            progress_callback(int(percent), message)
                        if turntable_output:
                            deadline = time.monotonic() + 600
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    proc.terminate()
                    proc.wait(timeout=3)
                    error_stream.close()
                    return None
                time.sleep(0.1)
            error_stream.close()
            prepared = str(profile.get("_turntable_prepared_scene", ""))
            if proc.returncode == 0 and prepared and Path(prepared).is_file():
                image = QImage(1, 1, QImage.Format_ARGB32)
                image.fill(0)
                return image
            if proc.returncode != 0 or not image_path.is_file():
                if progress_callback:
                    try:
                        percent, message = last_status.split("|", 1)
                        details = error_path.read_text(encoding="utf-8", errors="replace").splitlines()
                        detail = next((line.strip() for line in reversed(details) if line.strip()), "")
                        try:
                            _render_log._write_render_log(DATA_DIR,
                                              f"[99%] {path.name} — Echec du rendu\n" + "\n".join(details[-200:]),
                                              str(path), "turntable" if turntable_output else "image")
                        except OSError:
                            pass
                        progress_callback(99, f"Echec Eevee : {detail or message}")
                    except ValueError:
                        pass
                return None
            image = QImage(str(image_path))
            if image.isNull():
                return None
            return _profiles._apply_render_background(image.copy(), profile)
    except (OSError, subprocess.SubprocessError):
        return None

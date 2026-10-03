"""Switch Assetto Corsa skin texture overrides without rebuilding materials."""

from pathlib import Path
import json
import tempfile

import bpy

from .ac_folders import car_skins
from .scene import _texture_image

IMAGE_EXTENSIONS = {".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp"}


def _opaque_zero_alpha_diffuse(detail):
    mix = detail.id_data.nodes.get("AC Skin Color")
    if not mix or not mix.inputs[1].is_linked:
        return
    diffuse = mix.inputs[1].links[0].from_node
    if diffuse.type != "TEX_IMAGE" or not diffuse.image:
        return
    image = diffuse.image
    # Some AC DDS paint maps have useful RGB but an entirely zero alpha channel.
    if (image.alpha_mode not in {"NONE", "CHANNEL_PACKED"}
            and not diffuse.outputs["Alpha"].is_linked and not any(image.pixels[:][3::4])):
        image.alpha_mode = "NONE"


def _texture_nodes(collection):
    seen = set()
    for obj in collection.all_objects:
        if obj.type != "MESH":
            continue
        for material in obj.data.materials:
            if material and material.as_pointer() not in seen:
                seen.add(material.as_pointer())
                if material.node_tree:
                    for node in material.node_tree.nodes:
                        if node.type == "TEX_IMAGE" and node.image:
                            yield node


def prepare_car(collection, folder, source_kn5, lod, model):
    skins = car_skins(folder)
    collection["ac_kind"] = "CAR"
    collection["ac_source_folder"] = str(folder)
    collection["ac_source_kn5"] = str(source_kn5)
    collection["ac_skin_paths"] = {key: str(path) for key, _, path in skins}
    collection["ac_skin_labels"] = {key: label for key, label, _ in skins}
    collection["ac_lod"] = lod
    collection["ac_active_skin"] = "BASE"
    warnings = set()
    override_names = {file.name.casefold() for _, _, skin in skins
                      for file in skin.iterdir() if file.is_file()}
    images = {}
    with tempfile.TemporaryDirectory(prefix="kn5_skin_base_") as temp_dir:
        materials = {material.as_pointer(): material for obj in collection.all_objects
                     if obj.type == "MESH" for material in obj.data.materials if material}
        for material in materials.values():
            if not material.node_tree:
                continue
            name = json.loads(material.get("kn5_textures", "{}")).get("txDetail", "")
            if Path(name.replace("\\", "/")).name.casefold() not in override_names:
                continue
            if any(node.type == "TEX_IMAGE" and node.get("kn5_texture_slot") == "txDetail"
                   and node.outputs["Color"].is_linked for node in material.node_tree.nodes):
                continue  # The converter already wired this replaceable detail layer.
            image = _texture_image(name, model, source_kn5, images, temp_dir, warnings,
                                   alpha_is_data=True)
            if image is None:
                continue
            tree = material.node_tree
            shader = next((node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
            if shader is None:
                continue
            color = shader.inputs["Base Color"]
            previous = color.links[0].from_socket if color.is_linked else None
            detail = tree.nodes.new("ShaderNodeTexImage")
            detail.name = "AC Skin Detail"
            detail["kn5_texture_slot"] = "txDetail"
            detail.image = image
            detail.location = (-400, -450)
            multiply = tree.nodes.new("ShaderNodeMixRGB")
            multiply.name = "AC Skin Color"
            multiply.blend_type = "MULTIPLY"
            multiply.inputs[0].default_value = 1.0
            multiply.location = (-100, 100)
            if previous:
                tree.links.new(previous, multiply.inputs[1])
            else:
                multiply.inputs[1].default_value = color.default_value
            tree.links.new(detail.outputs["Color"], multiply.inputs[2])
            tree.links.new(multiply.outputs[0], color)
            _opaque_zero_alpha_diffuse(detail)
    for node in list(_texture_nodes(collection)):
        node["ac_base_image"] = node.image.name
        node["ac_texture_name"] = node.image.get("kn5_original_name", node.image.name)
        node.image.use_fake_user = True
    return tuple(sorted(warnings))


def _skin_files(collection, skin):
    available = collection.get("ac_skin_paths")
    directory = next((path for key, path in available.items() if key.casefold() == skin.casefold()), None) if available else None
    if directory is None or not Path(bpy.path.abspath(directory)).is_dir():
        folder = Path(bpy.path.abspath(collection["ac_source_folder"])).expanduser()
        collection["ac_skin_paths"] = {key: str(path) for key, _, path in car_skins(folder)}
        available = collection["ac_skin_paths"]
        directory = next((path for key, path in available.items() if key.casefold() == skin.casefold()), None)
    if directory is None:
        raise FileNotFoundError(f"Skin folder not found for {skin!r} in {collection['ac_source_folder']}")
    skin_folder = Path(bpy.path.abspath(directory)).expanduser()
    if not skin_folder.is_dir():
        raise FileNotFoundError(f"Skin folder not found: {skin_folder}")
    files = {path.name.casefold(): path for path in skin_folder.iterdir()
             if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS}
    if not files:
        raise ValueError(f"Skin found, but no override textures found: {skin_folder}")
    return files


def _load_override(path, base, *, reload=False):
    key = str(path.resolve())
    if not path.is_file():
        raise FileNotFoundError(f"Skin texture missing: {path}")
    image = next((image for image in bpy.data.images if image.get("ac_skin_path") == key
                   and image.colorspace_settings.name == base.colorspace_settings.name
                   and image.alpha_mode == base.alpha_mode), None)
    if image and not reload:
        return image
    created = image is None
    if created:
        image = bpy.data.images.load(key, check_existing=False)
    else:
        image.reload()
    try:
        _ = image.pixels[0]  # DDS decode is lazy in Blender 5.
    except (IndexError, RuntimeError) as exc:
        if created:
            bpy.data.images.remove(image)
        raise RuntimeError(f"Blender cannot decode skin texture {path.name}: {exc}") from exc
    if not image.has_data or min(image.size) == 0:
        if created:
            bpy.data.images.remove(image)
        raise RuntimeError(f"Blender cannot decode skin texture {path.name}")
    if created:
        image["ac_skin_path"] = key
        image.use_fake_user = True
        image.colorspace_settings.name = base.colorspace_settings.name
        image.alpha_mode = base.alpha_mode
    return image


def _apply_skin(collection, skin, *, reload=False):
    """Assign overrides by original KN5 texture name; return (changed, warnings)."""
    files = {} if skin == "BASE" else _skin_files(collection, skin)
    assignments = []
    overrides = {}
    warnings = []
    for node in list(_texture_nodes(collection)):
        base = bpy.data.images.get(node.get("ac_base_image", ""))
        if base is None:
            warnings.append(f"Missing embedded base texture for {node.name}")
            continue
        target = base
        override = files.get(Path(node.get("ac_texture_name", "").replace("\\", "/")).name.casefold())
        if override:
            try:
                key = (override, base.colorspace_settings.name, base.alpha_mode)
                if key not in overrides:
                    overrides[key] = _load_override(override, base, reload=reload)
                target = overrides[key]
            except (OSError, RuntimeError, ValueError) as exc:
                raise RuntimeError(f"Cannot apply {override.name}: {exc}") from exc
            if node.name == "AC Skin Detail":
                _opaque_zero_alpha_diffuse(node)
        assignments.append((node, target))
    changed = sum(image != bpy.data.images.get(node.get("ac_base_image", ""))
                  for node, image in assignments)
    if skin != "BASE" and not changed:
        raise ValueError(f"Skin found, but no KN5 texture matches its overrides: {skin}")
    for node, image in assignments:
        node.image = image
    collection["ac_active_skin"] = skin
    return changed, tuple(sorted(set(warnings)))


def apply_skin(collection, skin, *, reload=False):
    """Keep assignments unchanged and remove new images if an override fails."""
    existing = {image.as_pointer() for image in bpy.data.images}
    try:
        return _apply_skin(collection, skin, reload=reload)
    except Exception:
        for image in list(bpy.data.images):
            if image.as_pointer() not in existing:
                bpy.data.images.remove(image)
        raise

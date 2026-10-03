"""Blender scene creation for parsed KN5 models."""

from pathlib import Path
from contextlib import contextmanager
import json
import math
import re
import tempfile

import bpy
from mathutils import Matrix, Vector

from .organize import organize_collection


def _texture_image(name, model, source, cache, temp_dir, warnings, *, non_color=False,
                   alpha_is_data=False):
    if not name:
        return None
    normalized = name.replace("\\", "/")
    safe_name = Path(normalized).name
    if safe_name in {"", ".", ".."} or "\0" in normalized:
        warnings.add(f"Invalid texture name: {name!r}")
        return None
    if "_embedded_names" not in cache:
        names, basenames = {}, {}
        for original, data in model.textures.items():
            normalized_original = original.replace("\\", "/").casefold()
            names.setdefault(normalized_original, (original, data))
            basenames.setdefault(Path(normalized_original).name, (original, data))
        cache["_embedded_names"], cache["_embedded_basenames"] = names, basenames
    match = ((name, model.textures[name]) if name in model.textures else
             cache["_embedded_names"].get(normalized.casefold()) or
             cache["_embedded_basenames"].get(safe_name.casefold()))
    embedded = match[1] if match else None
    path = None
    if embedded is None:
        if "_external_files" not in cache:
            parent = Path(source).parent
            files, exact = {}, {}
            for folder in (parent, parent / "texture", parent / "textures"):
                if folder.is_dir():
                    for candidate in folder.iterdir():
                        if candidate.is_file():
                            files.setdefault(candidate.name.casefold(), candidate)
                            exact.setdefault(candidate.name, candidate)
            cache["_external_files"], cache["_external_exact"] = files, exact
        path = cache["_external_exact"].get(safe_name) or cache["_external_files"].get(safe_name.casefold())
    key = (match[0] if match else str(path) if path else safe_name.casefold(), non_color, alpha_is_data)
    if key in cache:
        return cache[key]
    if embedded is not None:
        # Unique staging names also keep identically named lazy DDS sources separate.
        path = Path(temp_dir) / f"texture_{len(cache)}{Path(safe_name).suffix}"
    if path is None:
        warnings.add(f"Missing texture: {name}")
        cache[key] = None
        return None
    image = None
    try:
        if embedded is not None:
            path.write_bytes(embedded)
        image = bpy.data.images.load(str(path), check_existing=False)
        image.name = safe_name
        image["kn5_original_name"] = name
        image.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
        if alpha_is_data:
            # KN5 opaque/detail maps can store data (even zero) in alpha. Blender
            # otherwise premultiplies unused alpha into the texture's Color output.
            image.alpha_mode = "CHANNEL_PACKED"
        _ = image.pixels[0]  # DDS decoding is lazy; fail before retaining the image.
        if not image.has_data or min(image.size) == 0:
            raise RuntimeError("Blender cannot decode the texture")
        if embedded is not None:
            image.pack()
        cache[key] = image
        return image
    except (RuntimeError, OSError, TypeError, ValueError, IndexError) as exc:
        if image is not None:
            bpy.data.images.remove(image)
        warnings.add(f"Cannot load texture {name}: {exc}")
        cache[key] = None
        return None


def _finite(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _source_color(entry, name, default):
    vectors = entry.vectors.get(name, {})
    # KN5 stores separate scalar, float2, float3 and float4 values per property.
    for kind in ("float3", "float4"):
        values = vectors.get(kind, ())
        rgb = tuple(max(0.0, _finite(v)) for v in values[:3])
        if len(rgb) == 3 and (any(rgb) or name != "ksEmissive"):
            return (*rgb, 1.0)
    return default


def _source_uv_scale(entry, name, default=1.0):
    """Read the scalar or float2 tiling used by KN5 multilayer variants."""
    values = entry.vectors.get(name, {}).get("float2", ())
    if len(values) == 2 and any(_finite(value) for value in values):
        return tuple(_finite(value, default) for value in values)
    scale = _finite(entry.properties.get(name, default), default)
    return (scale, scale)


def _material_settings(entry):
    """Translate source parameters without requiring Blender or texture pixels."""
    props = entry.properties
    shader = entry.shader.casefold()
    name = entry.name.casefold()
    number = lambda key, default=0.0: _finite(props.get(key, default), default)
    clamp = lambda value: max(0.0, min(1.0, value))
    exponent = max(0.0, number("ksSpecularEXP", 30.0))
    # Principled uses perceptual roughness: GGX alpha is roughness squared.
    roughness = max(0.02, clamp(number("roughness", (2.0 / (exponent + 2.0)) ** 0.25)))
    cutout = entry.alpha_test or shader.startswith("ksperpixelat") or shader.endswith("_at") or shader in {
        "kstree", "ksgrass", "ksflags",
    }
    blended = entry.blend_mode != 0 or shader in {"ksperpixelalpha", "ksskidmark"}
    glass = shader in {"kswindscreen", "ksglass"} or (
        blended and ("reflection" in shader or any(tag in name for tag in ("glass", "windscreen", "window")))
    )
    family = "generic"
    if glass:
        family = "glass"
    elif "tyres" in shader or "rubber" in shader:
        family = "rubber"
    elif "multilayer" in shader or shader in {"ksgrass", "kstree"}:
        family = "terrain"
    elif "carbon" in shader:
        family = "carbon"
    elif "metal" in shader or "chrome" in shader:
        family = "metal"
    elif "multimap" in shader:
        # Names refine a shared shader family; they never override source finish.
        family = next((kind for kind, tags in (
            ("carbon", ("carbon",)), ("rubber", ("rubber", "tyre", "tire")),
            ("metal", ("metal", "chrome")), ("plastic", ("plastic",)),
            ("interior", ("leather", "cockpit", "interior")),
            ("paint", ("paint", "livery")),
        ) if any(tag in name for tag in tags)), "multimap")
    elif "asphalt" in shader:
        family = "track"
    if family == "rubber":
        roughness = 0.6 + 0.4 * roughness
    f0 = clamp(number("fresnelC", 0.04))
    ior = number("ior", 1.5)
    if "ior" not in props and 0 < f0 < 1:
        root = math.sqrt(f0)
        ior = (1 + root) / (1 - root)
    specular = max(0.0, number("ksSpecular", 1.0))
    if shader == "ksmultilayer_fresnel_nm":
        specular *= max(0.0, number("tarmacSpecularMultiplier", 1.0))
    metallic = number("metallic", number("metalness", 0.0))
    if "metallic" not in props and "metalness" not in props:
        if "chrome" in shader or "metal" in shader or (
            family == "metal" and f0 >= 0.25 and number("fresnelMaxLevel") >= 0.8
        ):
            metallic = 1.0
    # A second source specular lobe becomes coat, including matte/satin paint.
    coat = max(0.0, number("sunSpecular"))
    coat_exp = max(0.0, number("sunSpecularEXP", exponent))
    emission = _source_color(entry, "ksEmissive", None)
    if emission is None:
        emission = (1.0, 1.0, 1.0, 1.0)
        strength = max(0.0, number("ksEmissive"))
    else:
        strength = max(emission[:3])
        emission = tuple(v / strength for v in emission[:3]) + (1.0,)
    if strength == 0 and ("emissive" in shader or "txEmissive" in entry.textures):
        strength = 1.0
    tint = _source_color(entry, "diffuseColor", _source_color(entry, "baseColor", (1, 1, 1, 1)))
    alpha = clamp(number("alpha", number("opacity", 1.0)))
    return {
        "family": family, "roughness": roughness, "metallic": clamp(metallic),
        "ior": max(1.01, min(3.0, ior)), "specular": specular / (1.0 + specular),
        "coat": coat / (1.0 + coat),
        "coat_roughness": max(0.02, (2.0 / (coat_exp + 2.0)) ** 0.25),
        "tint": tint, "diffuse": clamp(number("ksDiffuse", 0.8)),
        "color_multiplier": max(0.0, number("diffuseMult", 1.0)),
        "emission": emission, "emission_strength": strength,
        "glass": glass, "cutout": cutout,
        "transparent": blended or cutout or glass or alpha < 1.0 or "txAlpha" in entry.textures,
        "alpha": alpha,
        # Older exporters also write byte alpha references into this float field.
        "alpha_ref": clamp(number("ksAlphaRef", 0.5) / (255.0 if number("ksAlphaRef", 0.5) > 1 else 1.0)),
    }


def _materials(model, source, import_textures, temp_dir, warnings):
    images, result = {}, []
    for entry in model.materials:
        mat = bpy.data.materials.new(entry.name or "KN5 Material")
        mat["kn5_original_name"] = entry.name
        mat["kn5_shader"] = entry.shader
        mat["kn5_textures"] = json.dumps(entry.textures)
        mat["kn5_properties"] = json.dumps(entry.properties)
        mat["kn5_property_vectors"] = json.dumps(entry.vectors)
        mat["kn5_blend_mode"] = entry.blend_mode
        mat["kn5_alpha_test"] = entry.alpha_test
        mat["kn5_depth_mode"] = entry.depth_mode
        if mat.node_tree is None:  # Preserve Blender 4.x first-import initialization.
            mat.use_nodes = True
        tree = mat.node_tree
        tree.nodes.clear()
        out = tree.nodes.new("ShaderNodeOutputMaterial")
        out.location = (650, 0)
        shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
        shader.location = (350, 0)
        tree.links.new(shader.outputs["BSDF"], out.inputs["Surface"])
        settings = _material_settings(entry)
        mat["kn5_material_family"] = settings["family"]
        props = entry.properties
        for socket, key in (
            ("Roughness", "roughness"), ("Metallic", "metallic"), ("IOR", "ior"),
            ("Specular IOR Level", "specular"), ("Coat Weight", "coat"),
            ("Coat Roughness", "coat_roughness"), ("Emission Strength", "emission_strength"),
        ):
            shader.inputs[socket].default_value = settings[key]
        shader.inputs["Emission Color"].default_value = settings["emission"]
        tint = settings["tint"]
        shader.inputs["Base Color"].default_value = tuple(v * settings["diffuse"] for v in tint[:3]) + (1.0,)
        shader.inputs["Alpha"].default_value = settings["alpha"]
        if settings["glass"]:
            shader.inputs["Transmission Weight"].default_value = 1.0
            shader.inputs["Alpha"].default_value = 1.0
            if hasattr(mat, "use_screen_refraction"):
                mat.use_screen_refraction = True
        if settings["transparent"]:
            if hasattr(mat, "surface_render_method"):
                mat.surface_render_method = "DITHERED"
            elif hasattr(mat, "blend_method"):
                mat.blend_method = "HASHED"

        used_slots = set()

        def texture(slot, y, non_color=False, scale=1.0):
            if not import_textures:
                return None
            image = _texture_image(entry.textures.get(slot), model, source, images, temp_dir, warnings,
                                   non_color=non_color, alpha_is_data=(non_color or
                                       slot in {"txDiffuse", "txBaseColor", "txAlbedo", "txBase", "txColor"}
                                       and not settings["transparent"]
                                       or slot in {"txDetail", "txDetailR", "txDetailG", "txDetailB", "txDetailA"}))
            if image is None:
                return None
            node = tree.nodes.new("ShaderNodeTexImage")
            node.name = "KN5 " + slot
            node["kn5_texture_slot"] = slot
            node.image = image
            node.location = (-1000, y)
            used_slots.add(slot)
            if isinstance(scale, (tuple, list)):
                uv_scale = tuple(_finite(value, 1.0) for value in scale[:2]) + (1.0,)
            else:
                scale = _finite(scale, 1.0)
                uv_scale = (scale, scale, 1.0)
            if uv_scale != (1.0, 1.0, 1.0):
                uv = tree.nodes.new("ShaderNodeTexCoord")
                uv.location = (-1450, y)
                mapping = tree.nodes.new("ShaderNodeVectorMath")
                mapping.operation = "MULTIPLY"
                mapping.inputs[1].default_value = uv_scale
                mapping.location = (-1250, y)
                tree.links.new(uv.outputs["UV"], mapping.inputs[0])
                vector = mapping.outputs[0]
                if isinstance(scale, (tuple, list)) and uv_scale[1] != 1.0:
                    # Mesh UVs already have V flipped; scale in the source convention.
                    offset = tree.nodes.new("ShaderNodeVectorMath")
                    offset.operation = "ADD"
                    offset.inputs[1].default_value = (0.0, 1.0 - uv_scale[1], 0.0)
                    tree.links.new(vector, offset.inputs[0])
                    vector = offset.outputs[0]
                tree.links.new(vector, node.inputs["Vector"])
            return node

        def multiply(color, tint_value, label):
            node = tree.nodes.new("ShaderNodeMixRGB")
            node.name = label
            node.blend_type = "MULTIPLY"
            node.inputs[0].default_value = 1.0
            node.inputs[2].default_value = tint_value
            tree.links.new(color, node.inputs[1])
            return node

        color = None
        for base_slot in ("txDiffuse", "txBaseColor", "txAlbedo", "txBase", "txColor"):
            if entry.textures.get(base_slot):
                color = texture(base_slot, 350)
                if color:
                    break
        color_output = color.outputs["Color"] if color else None
        detail_scale = _finite(props.get("detailUVMultiplier", 1.0), 1.0)
        detail_weight = max(0.0, min(1.0, _finite(props.get("useDetail", 0.0))))
        if detail_weight and ("multimap" in entry.shader.casefold() or entry.shader.casefold() in {"ksperpixelnm", "ksmultilayer"}):
            detail = texture("txDetail", 0, scale=detail_scale)
            if detail:
                mix = tree.nodes.new("ShaderNodeMixRGB")
                mix.name = "KN5 Detail Color"
                mix.blend_type = "MULTIPLY"
                mix.inputs[0].default_value = detail_weight
                mix.inputs[1].default_value = (1, 1, 1, 1)
                if color_output:
                    tree.links.new(color_output, mix.inputs[1])
                tree.links.new(detail.outputs["Color"], mix.inputs[2])
                color_output = mix.outputs[0]
        # Preserve a valid road albedo until this shader's detail color equations
        # are verified; its mask/detail maps must not redefine the base appearance.
        if entry.shader.casefold().startswith("ksmultilayer") and not (
                entry.shader.casefold() == "ksmultilayer_fresnel_nm" and color is not None):
            mask = texture("txMask", 1200, True)
            if mask:
                channels = tree.nodes.new("ShaderNodeSeparateColor")
                channels.mode = "RGB"
                tree.links.new(mask.outputs["Color"], channels.inputs["Color"])
                weighted_color, total_weight = None, None
                # Named R/G/B/A slots identify mask channels, unlike packed txMaps.
                for channel, output in (("R", "Red"), ("G", "Green"), ("B", "Blue"), ("A", None)):
                    layer = texture("txDetail" + channel, 1500,
                                    scale=_source_uv_scale(entry, "mult" + channel, detail_scale))
                    if layer:
                        weight = channels.outputs[output] if output else mask.outputs["Alpha"]
                        weighted = tree.nodes.new("ShaderNodeMixRGB")
                        weighted.name = "KN5 Layer " + channel
                        weighted.blend_type = "MULTIPLY"
                        weighted.inputs[0].default_value = 1.0
                        tree.links.new(layer.outputs["Color"], weighted.inputs[1])
                        tree.links.new(weight, weighted.inputs[2])
                        if weighted_color is None:
                            weighted_color, total_weight = weighted.outputs[0], weight
                        else:
                            add = tree.nodes.new("ShaderNodeMixRGB")
                            add.blend_type = "ADD"
                            add.inputs[0].default_value = 1.0
                            tree.links.new(weighted_color, add.inputs[1])
                            tree.links.new(weighted.outputs[0], add.inputs[2])
                            weighted_color = add.outputs[0]
                            total = tree.nodes.new("ShaderNodeMath")
                            total.operation = "ADD"
                            tree.links.new(total_weight, total.inputs[0])
                            tree.links.new(weight, total.inputs[1])
                            total_weight = total.outputs[0]
                if weighted_color is not None:
                    # ponytail: normalized RGBA blending; exact AC equations need verified shader code.
                    denominator = tree.nodes.new("ShaderNodeMath")
                    denominator.operation = "MAXIMUM"
                    denominator.inputs[1].default_value = 1e-6
                    tree.links.new(total_weight, denominator.inputs[0])
                    normalized = tree.nodes.new("ShaderNodeMixRGB")
                    normalized.blend_type = "DIVIDE"
                    normalized.inputs[0].default_value = 1.0
                    tree.links.new(weighted_color, normalized.inputs[1])
                    tree.links.new(denominator.outputs[0], normalized.inputs[2])
                    enabled = tree.nodes.new("ShaderNodeMath")
                    enabled.operation = "MINIMUM"
                    enabled.inputs[1].default_value = 1.0
                    tree.links.new(total_weight, enabled.inputs[0])
                    detail = tree.nodes.new("ShaderNodeMixRGB")
                    detail.name = "KN5 Masked Detail"
                    detail.blend_type = "MIX"
                    detail.inputs[1].default_value = (1, 1, 1, 1)
                    tree.links.new(enabled.outputs[0], detail.inputs[0])
                    tree.links.new(normalized.outputs[0], detail.inputs[2])
                    base = tree.nodes.new("ShaderNodeMixRGB")
                    base.name = "KN5 Multilayer Base"
                    base.blend_type = "MULTIPLY"
                    base.inputs[0].default_value = 1.0
                    base.inputs[1].default_value = (1, 1, 1, 1)
                    if color_output:
                        tree.links.new(color_output, base.inputs[1])
                    tree.links.new(detail.outputs[0], base.inputs[2])
                    color_output = base.outputs[0]
        if color_output:
            multiplier = tuple(v * settings["color_multiplier"] for v in tint[:3]) + (1.0,)
            if multiplier != (1, 1, 1, 1):
                color_output = multiply(color_output, multiplier, "KN5 Color Tint").outputs[0]
            tree.links.new(color_output, shader.inputs["Base Color"])

        # These dedicated slots have explicit meanings; txMaps does not.
        for slot, socket in (("txRoughness", "Roughness"), ("txMetallic", "Metallic"),
                             ("txSpecular", "Specular IOR Level")):
            data = texture(slot, -950, True)
            if data:
                tree.links.new(data.outputs["Color"], shader.inputs[socket])

        normal = texture("txNormal", -350, True, props.get("normalUVMultiplier", 1.0))
        normal_color = normal.outputs["Color"] if normal else None
        object_space = bool(_finite(props.get("nmObjectSpace", 0.0)))
        if entry.shader.casefold() == "ksmultilayer_fresnel_nm":
            detail_normal = texture("txDetailNM", -650, True,
                                    _source_uv_scale(entry, "detailNMMult"))
            if detail_normal:
                normal_color = detail_normal.outputs["Color"]
        if "nmdetail" in entry.shader.casefold() and not object_space:
            slot = "txNormalDetail" if "txNormalDetail" in entry.textures else "txDetailNM"
            detail_normal = texture(slot, -650, True, detail_scale)
            if detail_normal:
                mix = tree.nodes.new("ShaderNodeMixRGB")
                mix.name = "KN5 Detail Normal"
                mix.blend_type = "OVERLAY"
                mix.inputs[0].default_value = max(0.0, min(1.0, _finite(props.get("detailNormalBlend", 1.0), 1.0)))
                mix.inputs[1].default_value = (0.5, 0.5, 1.0, 1.0)
                if normal_color:
                    tree.links.new(normal_color, mix.inputs[1])
                tree.links.new(detail_normal.outputs["Color"], mix.inputs[2])
                normal_color = mix.outputs[0]
        if normal_color:
            normal_map = tree.nodes.new("ShaderNodeNormalMap")
            normal_map.location = (100, -350)
            normal_map.space = "OBJECT" if object_space else "TANGENT"
            normal_map.inputs["Strength"].default_value = max(0.0, _finite(props.get("normalMult", 1.0), 1.0))
            tree.links.new(normal_color, normal_map.inputs["Color"])
            tree.links.new(normal_map.outputs["Normal"], shader.inputs["Normal"])
            if settings["coat"]:
                tree.links.new(normal_map.outputs["Normal"], shader.inputs["Coat Normal"])

        alpha = texture("txAlpha", 650, True)
        alpha_output = alpha.outputs["Color"] if alpha else (color.outputs["Alpha"] if color else None)
        if settings["transparent"] and alpha_output:
            control = tree.nodes.new("ShaderNodeMath")
            control.location = (100, 300)
            if settings["glass"] and not settings["cutout"]:
                # Alpha controls tint opacity; transmission keeps surface reflections.
                control.operation = "SUBTRACT"
                control.inputs[0].default_value = 1.0
                tree.links.new(alpha_output, control.inputs[1])
                tree.links.new(control.outputs[0], shader.inputs["Transmission Weight"])
            else:
                control.operation = "GREATER_THAN" if settings["cutout"] else "MULTIPLY"
                control.inputs[1].default_value = settings["alpha_ref"] if settings["cutout"] else settings["alpha"]
                tree.links.new(alpha_output, control.inputs[0])
                tree.links.new(control.outputs[0], shader.inputs["Alpha"])

        emissive = texture("txEmissive", 950)
        if settings["emission_strength"]:
            emission_output = emissive.outputs["Color"] if emissive else color_output
            if emission_output:
                if settings["emission"] != (1, 1, 1, 1):
                    emission_output = multiply(emission_output, settings["emission"], "KN5 Emission Tint").outputs[0]
                tree.links.new(emission_output, shader.inputs["Emission Color"])

        # ponytail: unknown packed channels stay unmapped until a shader defines their semantics.
        unsupported = set(entry.textures) - used_slots
        if import_textures and unsupported:
            warnings.add(f"{entry.shader}: unmapped texture slots: {', '.join(sorted(unsupported))}")
        known = entry.shader.casefold().startswith(("ksperpixel", "ksmultilayer", "kstyres")) or entry.shader.casefold() in {
            "kswindscreen", "ksglass", "kstree", "ksgrass", "ksflags", "ksskidmark",
        }
        if not known:
            warnings.add(f"Unsupported shader {entry.shader}: generic material conversion")
        result.append(mat)
    return result


def _source_matrix(rows):
    # KN5 stores row-vector transforms; Blender uses column vectors.
    if rows is not None and (len(rows) != 4 or any(
            len(row) != 4 or not all(math.isfinite(value) for value in row) for row in rows)):
        raise ValueError("Invalid KN5 transform matrix")
    return Matrix(rows).transposed() if rows else Matrix.Identity(4)


def _make_mesh(name, meshes, materials, warnings):
    vertices, faces, uvs, normals, face_materials, material_ids = [], [], [], [], [], []
    for mesh, transform in meshes:
        count = len(mesh.positions)
        if (len(mesh.normals) != count or len(mesh.uvs) != count
                or any(len(row) != 3 for rows in (mesh.positions, mesh.normals) for row in rows)
                or any(len(row) != 2 for row in mesh.uvs)):
            raise ValueError(f"Invalid vertex data shape in mesh {name!r}")
        if len(mesh.indices) % 3 or any(
                not isinstance(index, int) or not 0 <= index < count for index in mesh.indices):
            raise ValueError(f"Invalid triangle indices in mesh {name!r}")
        start = len(vertices)
        material_ids.append(mesh.material_id)
        vertices.extend(tuple(transform @ Vector(v)) for v in mesh.positions)
        normal_matrix = transform.to_3x3().inverted_safe().transposed()
        normals.extend(tuple((normal_matrix @ Vector(n)).normalized()) for n in mesh.normals)
        uvs.extend(mesh.uvs)
        for j in range(0, len(mesh.indices), 3):
            triangle = mesh.indices[j:j + 3]
            if len(set(triangle)) != 3:
                warnings.add(f"Skipped degenerate triangle in mesh {name!r}")
                continue
            faces.append(tuple(start + i for i in triangle))
            face_materials.append(mesh.material_id)
    if any(not all(math.isfinite(value) for value in row)
           for rows in (vertices, uvs) for row in rows):
        raise ValueError(f"Non-finite position or UV in mesh {name!r}")
    authored_normals = []
    for normal in normals:
        length_squared = sum(value * value for value in normal)
        if (not all(math.isfinite(value) for value in normal)
                or not math.isfinite(length_squared)
                or length_squared <= 1e-12):
            authored_normals = None
            break
        length = math.sqrt(length_squared)
        authored_normals.append(tuple(value / length for value in normal))
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, [], faces)
    topology_changed = data.validate(clean_customdata=False)
    data.update()
    if uvs and data.loops:
        layer = data.uv_layers.new(name="UVMap")
        for loop in data.loops:
            layer.data[loop.index].uv = uvs[loop.vertex_index]
    for poly in data.polygons:
        poly.use_smooth = True
    if normals and hasattr(data, "normals_split_custom_set_from_vertices"):
        if (authored_normals is None or topology_changed
                or len(authored_normals) != len(data.vertices)):
            warnings.add("Skipped invalid custom normals")
        else:
            data.normals_split_custom_set_from_vertices(authored_normals)
    elif normals:
        warnings.add("This Blender build does not support imported custom normals")
    material_slots = {}
    for material_id in material_ids:
        if 0 <= material_id < len(materials) and material_id not in material_slots:
            material_slots[material_id] = len(data.materials)
            data.materials.append(materials[material_id])
    for poly, material_id in zip(data.polygons, face_materials):
        if material_id in material_slots:
            poly.material_index = material_slots[material_id]
        elif materials:
            warnings.add(f"Mesh references missing material {material_id}")
    obj = bpy.data.objects.new(name, data)
    return obj


def _build(model, source, *, import_materials=True, import_textures=True,
           import_hidden=False, scale=1.0,
           organize_meshes=True, clean_mesh_names=True):
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Import scale must be finite and positive")
    warnings = set(model.warnings)
    car_name = Path(source).stem.upper()
    collection = bpy.data.collections.new(car_name)
    collection["kn5_import"] = True
    bpy.context.scene.collection.children.link(collection)
    anchor = bpy.data.objects.new(car_name, None)
    anchor["kn5_import_root"] = True
    anchor["kn5_source_file"] = str(source)
    collection.objects.link(anchor)
    anchor.rotation_euler[0] = math.pi / 2  # Assetto Corsa Y-up to Blender Z-up.
    anchor.scale = (scale, scale, scale)
    with tempfile.TemporaryDirectory(prefix="kn5_textures_") as temp_dir:
        materials = _materials(model, source, import_textures, temp_dir, warnings) if import_materials else []

        def visit(node, parent):
            if not import_hidden and (not node.active or re.search(r"(^|[_ ])LOD[_ ]?[BCD](?=$|[_ ])", node.name, re.I)):
                return
            local = _source_matrix(node.matrix)
            if node.skinned:
                warnings.add("Skinned meshes imported in bind pose; bone weights are unsupported")
            if node.kind == 1:
                obj = bpy.data.objects.new(node.name + " [node]", None)
                obj["kn5_original_name"] = node.name
                collection.objects.link(obj)
                obj.parent = parent
                obj.matrix_basis = local
                parent = obj
            elif node.mesh and (import_hidden or (node.mesh.visible and node.mesh.renderable)):
                obj = _make_mesh(node.name, [(node.mesh, Matrix.Identity(4))], materials, warnings)
                obj["kn5_original_name"] = node.name
                collection.objects.link(obj)
                obj.parent = parent
                parent = obj
            for child in node.children:
                visit(child, parent)

        visit(model.root, anchor)
    organize_collection(collection, organize_meshes=organize_meshes,
                        clean_names=clean_mesh_names)
    return collection, sorted(warnings)


@contextmanager
def import_transaction():
    """Remove only newly created import data if any import stage fails."""
    groups = (bpy.data.objects, bpy.data.meshes, bpy.data.materials,
              bpy.data.images, bpy.data.collections)
    existing = [{item.as_pointer() for item in group} for group in groups]
    try:
        yield
    except Exception:
        for group, pointers in zip(groups, existing):
            for item in list(group):
                if item.as_pointer() not in pointers:
                    group.remove(item, do_unlink=True)
        raise


def build(model, source, **options):
    """Import one model, removing partial Blender data if scene creation fails."""
    with import_transaction():
        return _build(model, source, **options)

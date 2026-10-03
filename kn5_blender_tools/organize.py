"""Non-destructive collection and naming cleanup for imported KN5 scenes."""

import json
import re
from .classification import CAR_CATEGORIES, classify_car


CATEGORIES = CAR_CATEGORIES
_CORNERS = {"LF": "FL", "RF": "FR", "FL": "FL", "FR": "FR",
            "LB": "RL", "BL": "RL", "LR": "RL", "RB": "RR", "BR": "RR", "RR": "RR",
            "L": "L", "R": "R"}
_MATERIAL_ROLES = (("decals", "Decals"), ("paint", "Paint"),
                   ("detail", "Detail"), ("carbon", "Carbon"),
                   ("number", "Number"), ("generic", "Trim"),
                   ("chrome", "Chrome"), ("glass", "Glass"))


def _corner(name, ancestors):
    # A WHEEL_RF parent is more reliable than this car's mislabeled x0_tyre_fl.
    for ancestor in reversed(ancestors):
        match = re.search(r"(?:^|_)(?:WHEEL|HUB|SUSP|CALIPER|STEER)_?(LF|RF|LR|RR|FL|FR|BL|BR)(?:$|_)", ancestor, re.I)
        if match:
            return _CORNERS[match.group(1).upper()]
    match = re.search(r"(?:^|_)(LF|RF|LR|RR|FL|FR|BL|BR|L|R)(?:$|[_.])", name, re.I)
    return _CORNERS[match.group(1).upper()] if match else ""


def _clean(raw):
    raw = re.sub(r"([A-Za-z])(\d)", r"\1_\2", raw)
    words = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").split("_")
    acronyms = {"LED", "RPM", "KERS", "DRS", "FL", "FR", "RL", "RR", "LR"}
    return "_".join(word.upper() if word.upper() in acronyms else word.capitalize()
                    for word in words) or "Unnamed_Mesh"


def _material_suffix(material):
    lower = material.lower()
    return next((label for part, label in _MATERIAL_ROLES if part in lower), "")


def classify(original_name, material_name="", ancestors=()):
    """Return (collection, useful name), using KN5 names before material hints."""
    raw = original_name or "Unnamed_Mesh"
    low = raw.lower()
    material = material_name.lower()
    path = "/".join(ancestors).lower()
    corner = _corner(raw, ancestors)
    stem = re.sub(r"(?:\.\d+|__lr)$", "", low)
    variant = bool(re.search(r"\.\d+$|_sub\d+", low))

    def named(category, base, suffix=True):
        role = _material_suffix(material) if variant and suffix else ""
        return category, base + ("_" + role if role else "")

    # Material + wheel parent override misleading mesh names in the supplied F1.
    if "sidewall" in material or "tread" in material or "tyre" in stem or "tire" in stem:
        part = "_Sidewall" if "sidewall" in material else "_Tread" if "tread" in material else ""
        return "TYRES", "Tyre" + ("_" + corner if corner else "") + part
    if "caliper" in stem:
        return "BRAKES", "Brake_Caliper" + ("_" + corner if corner else "")
    if "disc" in stem and "wheel_hub" in material:
        return "WHEELS", "Wheel_Hub" + ("_" + corner if corner else "")
    if "disc" in stem:
        return "BRAKES", "Brake_Disc" + ("_" + corner if corner else "")
    if "suspension" in stem or "tether" in stem:
        number = re.search(r"suspension(\d+)", stem)
        base = "Suspension_Tether" if "tether" in stem else "Suspension"
        return named("SUSPENSION", base + ("_" + corner if corner else "") +
                     ("_" + number.group(1) if number else ""))

    steering = "steer" in path or "steering_wheel" in stem
    if stem.startswith("led_"):
        label = _clean(raw).replace("_LR", "_LowRes")
        return ("INTERIOR" if steering else "LIGHTS"), ("Steering_" if steering else "") + label
    if "steering_wheel" in stem or stem.startswith("steer_hr_sub"):
        sub = re.search(r"_sub(\d+)(?:_sub(\d+))?", stem)
        part = "_Part_" + "_".join(x for x in sub.groups() if x) if sub else ""
        return named("INTERIOR", "Steering_Wheel" + part)
    if "paddle" in stem:
        side = "L" if "left" in stem else "R" if "right" in stem else corner
        return "INTERIOR", "Steering_Paddle" + ("_" + side if side else "")
    if "dial" in stem:
        return "INTERIOR", "Steering_" + _clean(stem).replace("_001", "")
    if "cinture" in stem or "seatbelt" in stem:
        state = "_On" if "_on" in stem else "_Off" if "_off" in stem else ""
        return named("INTERIOR", "Seatbelt" + state)
    if "driver_surroun" in stem:
        return named("INTERIOR", "Cockpit_Surround")
    if stem.startswith("cockpit"):
        return named("INTERIOR", "Cockpit")

    if "mirror" in stem:
        side = (corner[-1:] if corner else
                "R" if "right" in material or stem.endswith("mirrorr") else
                "L" if "left" in material or stem.endswith("mirrorl") else "")
        base = "Mirror" + ("_" + side if side else "")
        if "glass" in material:
            return "GLASS", base + "_Glass"
        if "light" in material:
            return "LIGHTS", base + "_Indicator"
        return named("BODY", base)
    if "windscreen" in stem or "glass" in stem or "glass" in material:
        return named("GLASS", "Windscreen" if "windscreen" in stem else "Glass")

    if "antenna" in path and stem.startswith("safetycell"):
        return named("BODY", "Antenna")
    if stem.startswith("safetycell") and "light" in material:
        return "LIGHTS", "Rear_Light"
    if "frontwingmoving" in stem:
        return named("FRONT_WING", "Front_Wing_Movable" + ("_" + corner if corner else ""))
    if "frontwing" in stem:
        return named("FRONT_WING", "Front_Wing" + ("_" + corner if corner else ""))
    if "frontspoiler" in stem:
        return named("FRONT_WING", "Front_Wing_Center")
    if "rearwingmoving" in stem:
        return named("REAR_WING", "Rear_Wing_DRS")
    if "rearwing" in stem:
        return named("REAR_WING", "Rear_Wing")
    if "sidepod" in stem:
        side = corner[-1:] if corner else ""
        return named("BODY", "Sidepod" + ("_" + side if side else ""))
    if "nosecone" in stem:
        return named("BODY", "Nosecone")
    if "topcanopy" in stem:
        return named("BODY", "Bodywork_Top")
    if "safetycell" in stem:
        if "paint" in material:
            return "BODY", "Body"
        return named("BODY", "Body")
    if "floor" in stem:
        side = corner[-1:] if corner else ""
        return named("BODY", "Floor" + ("_" + side if side else ""))
    if "diffuser" in stem:
        return named("BODY", "Diffuser")
    if stem == "hal" or stem == "halo":
        return named("BODY", "Halo")
    if "camera_wing" in stem:
        return named("BODY", "Camera_Wing")
    if re.search(r"(?:^|_)wheel(?:_|$)", stem):
        return "WHEELS", "Wheel" + ("_" + corner if corner else "")
    if steering and not re.match(r"(?:object|cylinder)\d+", stem):
        return "INTERIOR", _clean(raw)
    if "light" in material and not re.match(r"(?:object|cylinder)\d+", stem):
        return "LIGHTS", _clean(raw)
    # Generic Blender/FBX labels give too little evidence for a more specific role.
    return "OTHER", _clean(raw)


def _source_name(obj):
    return obj.get("kn5_original_name") or obj.name.removesuffix(" [node]")


def _parent_names(obj):
    names = []
    parent = obj.parent
    while parent:
        names.append(_source_name(parent))
        parent = parent.parent
    return tuple(reversed(names))


def _assigned_material_name(obj):
    material = _assigned_material(obj)
    return material.get("kn5_original_name", material.name) if material else ""


def _assigned_material(obj):
    if not obj.data.materials:
        return None
    index = obj.data.polygons[0].material_index if obj.data.polygons else 0
    return obj.data.materials[index] if index < len(obj.data.materials) else None


def _child(parent, name):
    import bpy
    existing = next((child for child in parent.children
                     if child.get("kn5_collection_role") == name or child.name == name), None)
    if existing:
        existing["kn5_collection_role"] = name
        return existing
    collection = bpy.data.collections.new(name)
    collection["kn5_collection_role"] = name
    parent.children.link(collection)
    return collection


def _move(obj, target):
    if target not in obj.users_collection:
        target.objects.link(obj)
    for collection in list(obj.users_collection):
        if collection != target:
            collection.objects.unlink(obj)


def _remove_legacy_groups(top):
    import bpy
    for child in list(top.children):
        role = child.get("kn5_collection_role")
        if role == "MESHES" and not child.all_objects:
            for category in list(child.children):
                if not category.all_objects and not category.children:
                    bpy.data.collections.remove(category)
            if not child.children:
                bpy.data.collections.remove(child)


def organize_collection(top, *, organize_meshes=True, clean_names=True):
    """Organize meshes and hide the preserved KN5 helper hierarchy."""
    top.name = top.name.upper()
    top["kn5_import"] = True
    objects = list(top.all_objects)
    meshes = [obj for obj in objects if obj.type == "MESH"]
    empties = [obj for obj in objects if obj.type == "EMPTY" and (
        obj.get("kn5_import_root") or obj.get("kn5_original_name") or
        obj.name.endswith(" [node]") or obj.name.casefold() == top.name.casefold())]
    details = []
    for obj in meshes:
        if "kn5_original_name" not in obj:
            obj["kn5_original_name"] = _source_name(obj)
        if "kn5_parent_path" not in obj:
            obj["kn5_parent_path"] = json.dumps(_parent_names(obj))
        original = obj["kn5_original_name"]
        ancestors = json.loads(obj["kn5_parent_path"])
        material = _assigned_material(obj)
        material_name = _assigned_material_name(obj)
        textures = json.loads(material.get("kn5_textures", "{}")) if material else {}
        category, evidence = (classify_car(
            original, original, ancestors, material_name,
            material.get("kn5_shader", "") if material else "", textures.values())
            if organize_meshes else ("OTHER", "organization disabled"))
        name = classify(original, material_name, ancestors)[1] if clean_names else original
        if organize_meshes:
            obj["ac_category"] = category
            obj["ac_classification_evidence"] = evidence
        details.append((obj, category, name, original))

    if organize_meshes:
        legacy = next((child for child in top.children
                       if child.get("kn5_collection_role") == "MESHES"), None)
        if legacy:
            for obj in meshes:
                _move(obj, top)
            _remove_legacy_groups(top)
        groups = {}
        for category in {item[1] for item in details}:
            parent = top
            for segment in category.split("/"):
                parent = _child(parent, segment)
            groups[category] = parent
        for obj, category, _, _ in details:
            _move(obj, groups[category])

    if clean_names:
        # Free target names first so rerunning the operator stays stable.
        for obj, _, _, _ in details:
            obj.name = f"__KN5_TMP_{obj.as_pointer()}"
        used = set()
        for obj, _, base, _ in sorted(details, key=lambda item: item[3].casefold()):
            candidate = base
            number = 2
            while candidate in used:
                candidate = f"{base}_{number}"
                number += 1
            obj.name = candidate
            used.add(obj.name)

    if empties:
        hierarchy = _child(top, "KN5_HIERARCHY")
        for obj in empties:
            if "kn5_original_name" not in obj:
                obj["kn5_original_name"] = _source_name(obj)
            _move(obj, hierarchy)
        hierarchy.hide_viewport = True
    for parent in (top, *top.children):
        for child in list(parent.children):
            if child.get("kn5_collection_role") and not child.all_objects and not child.children:
                bpy.data.collections.remove(child)
    return {category: sum(item[1] == category for item in details) for category in CATEGORIES}


def find_import_collection(context):
    """Find the imported model containing the active object, or the sole model."""
    import bpy
    candidates = []
    for collection in bpy.data.collections:
        if collection.get("kn5_import"):
            candidates.append(collection)
            continue
        root = collection.objects.get(collection.name)
        if root and root.type == "EMPTY" and any(obj.type == "MESH" for obj in collection.all_objects):
            candidates.append(collection)  # imports made by earlier addon versions
    active = context.active_object
    if active:
        matching = [c for c in candidates if c.all_objects.get(active.name) is active]
        if len(matching) == 1:
            return matching[0]
    return candidates[0] if len(candidates) == 1 else None

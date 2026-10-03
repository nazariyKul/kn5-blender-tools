"""Cheap material checks with strict node sockets; no Blender process is required."""

import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace
import struct
import tempfile
import unittest
from unittest.mock import MagicMock

from kn5_blender_tools.kn5 import Material, parse


ROOT = Path(__file__).resolve().parents[1]
namespace = {"math": math, "json": json, "Path": Path}
source = ast.parse((ROOT / "kn5_blender_tools" / "scene.py").read_text())
names = {"_finite", "_source_color", "_source_uv_scale", "_material_settings", "_materials", "_texture_image"}
functions = ast.Module(body=[node for node in source.body
                           if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
exec(compile(functions, "scene material functions", "exec"), namespace)
settings = namespace["_material_settings"]


class MaterialTests(unittest.TestCase):
    def test_track_uv_scales_and_source_finish(self):
        scale = namespace["_source_uv_scale"]
        road = Material("EFVD_ASPH", "ksMultilayer_fresnel_nm",
                        properties={"multR": 0.4, "detailNMMult": 0, "ksSpecular": 1,
                                    "ksSpecularEXP": 15, "tarmacSpecularMultiplier": 0.5},
                        vectors={"detailNMMult": {"float2": (30, 30)}})
        self.assertEqual(scale(road, "multR"), (0.4, 0.4))
        self.assertEqual(scale(road, "detailNMMult"), (30, 30))
        building = Material("box1-mask", "ksMultilayer_objsp", properties={"multR": 0},
                            vectors={"multR": {"float2": (70, 32.5)}})
        self.assertEqual(scale(building, "multR"), (70, 32.5))
        self.assertEqual(scale(building, "multB", 2), (2, 2))
        self.assertAlmostEqual(settings(road)["specular"], 1 / 3)
        self.assertAlmostEqual(settings(road)["roughness"], (2 / 17) ** 0.25)
        smoother = Material("same road", road.shader, properties={**road.properties, "ksSpecularEXP": 150})
        self.assertLess(settings(smoother)["roughness"], settings(road)["roughness"])
        self.assertEqual((settings(road)["metallic"], settings(road)["coat"]), (0, 0))

    def test_rubber_roughness_preserves_source_variation(self):
        for shader, name in (("ksTyres", "tread"), ("ksRubber", "seal"),
                             ("ksPerPixelMultiMap", "INT_Rubber")):
            values = [settings(Material(name, shader, properties={"roughness": value}))["roughness"]
                      for value in (0.02, 0.4, 0.9, 1.0)]
            for actual, expected in zip(values, (0.608, 0.76, 0.96, 1.0)):
                self.assertAlmostEqual(actual, expected)
        glossy = settings(Material("tread", "ksTyres", properties={"ksSpecularEXP": 1000}))
        matte = settings(Material("tread", "ksTyres", properties={"ksSpecularEXP": 1}))
        self.assertGreaterEqual(glossy["roughness"], 0.6)
        self.assertLess(glossy["roughness"], matte["roughness"])
        for name in ("paint", "carbon", "metal", "plastic", "interior", "generic"):
            self.assertEqual(settings(Material(name, "ksPerPixelMultiMap",
                                              properties={"roughness": 0.4}))["roughness"], 0.4)

    def test_source_finish_and_conservative_fallback(self):
        glossy = settings(Material("paint", "ksPerPixelMultiMap", properties={
            "ksSpecularEXP": 1000, "sunSpecular": 2, "sunSpecularEXP": 1500,
        }))
        matte = settings(Material("paint", "ksPerPixelMultiMap", properties={"ksSpecularEXP": 1}))
        self.assertLess(glossy["roughness"], matte["roughness"])
        self.assertGreater(glossy["coat"], 0)
        self.assertEqual(glossy["metallic"], 0)
        self.assertEqual(matte["coat"], 0)
        explicit = settings(Material("paint", "ksPerPixelMultiMap", properties={"roughness": 0.8, "metallic": 0.4}))
        self.assertEqual((explicit["roughness"], explicit["metallic"]), (0.8, 0.4))
        fallback = settings(Material("mystery", "customShader", properties={"ksSpecularEXP": float("nan")}))
        self.assertTrue(all(math.isfinite(fallback[key]) for key in ("roughness", "ior", "coat", "specular")))

    def test_glass_alpha_and_source_emission(self):
        glass = settings(Material("window", "ksPerPixelReflection", blend_mode=1,
                                  properties={"ksSpecular": 3, "fresnelC": 0.1}))
        self.assertTrue(glass["glass"])
        self.assertAlmostEqual(glass["specular"], 0.75)
        decal = settings(Material("decal", "ksPerPixelMultiMap_AT", alpha_test=True,
                                  properties={"ksAlphaRef": 128}))
        self.assertTrue(decal["cutout"])
        self.assertFalse(decal["glass"])
        self.assertAlmostEqual(decal["alpha_ref"], 128 / 255)
        light = settings(Material("lamp", "ksPerPixel", vectors={
            "ksEmissive": {"float3": (6, 3, 0)},
        }))
        self.assertEqual(light["emission"], (1, 0.5, 0, 1))
        self.assertEqual(light["emission_strength"], 6)
        self.assertEqual(settings(Material("brake_light", "ksPerPixel"))["emission_strength"], 0)

    def test_material_record_preserves_vectors_and_flags(self):
        def string(value):
            data = value.encode()
            return struct.pack("<i", len(data)) + data
        data = b"sc6969" + struct.pack("<4i", 6, 0, 0, 1)
        data += string("test material") + string("ksPerPixelReflection")
        data += struct.pack("<2Bi", 1, 1, 2) + struct.pack("<i", 1)
        data += string("ksEmissive") + struct.pack("<10f", 0, 1, 2, 6, 3, 0, 4, 5, 6, 7)
        data += struct.pack("<i", 1) + string("txDiffuse") + struct.pack("<i", 0) + string("lamp.dds")
        data += struct.pack("<i", 1) + string("root") + struct.pack("<iB", 0, 1)
        data += struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.kn5"
            path.write_bytes(data)
            model = parse(path)
        material = model.materials[0]
        self.assertEqual((material.blend_mode, material.alpha_test, material.depth_mode), (1, True, 2))
        self.assertEqual(material.vectors["ksEmissive"]["float3"], (6, 3, 0))
        self.assertEqual(material.vectors["ksEmissive"]["float4"], (4, 5, 6, 7))
        self.assertEqual(model.warnings, [])

    def test_node_graphs_and_texture_color_spaces(self):
        # Strict socket names catch accidental use of an unavailable node input.
        sockets = {
            "ShaderNodeOutputMaterial": (["Surface"], []),
            "ShaderNodeBsdfPrincipled": (["Base Color", "Roughness", "Metallic", "IOR",
                "Specular IOR Level", "Coat Weight", "Coat Roughness", "Emission Strength",
                "Emission Color", "Alpha", "Transmission Weight", "Normal", "Coat Normal"], ["BSDF"]),
            "ShaderNodeTexImage": (["Vector"], ["Color", "Alpha"]),
            "ShaderNodeMixRGB": ([0, 1, 2], [0]),
            "ShaderNodeMath": ([0, 1], [0]),
            "ShaderNodeVectorMath": ([0, 1], [0]),
            "ShaderNodeTexCoord": ([], ["UV"]),
            "ShaderNodeNormalMap": (["Strength", "Color"], ["Normal"]),
            "ShaderNodeSeparateColor": (["Color"], ["Red", "Green", "Blue"]),
        }

        class Nodes(list):
            def new(self, kind):
                inputs, outputs = sockets[kind]
                node = MagicMock()
                node.kind = kind
                node.inputs = {key: SimpleNamespace(default_value=None) for key in inputs}
                node.outputs = {key: SimpleNamespace() for key in outputs}
                self.append(node)
                return node

        class BlenderMaterial(dict):
            def __init__(self):
                self.node_tree = None
                self.surface_render_method = "DITHERED"

            @property
            def use_nodes(self):
                return self.node_tree is not None

            @use_nodes.setter
            def use_nodes(self, value):
                self.node_tree = SimpleNamespace(nodes=Nodes(), links=MagicMock())

        class Image(dict):
            def __init__(self):
                self.colorspace_settings = SimpleNamespace(name="sRGB")
                self.alpha_mode = "STRAIGHT"
                self.pack = MagicMock()
                self.pixels, self.size, self.has_data = [0], (1, 1), True

        images = []
        def load_image(*args, **kwargs):
            image = Image()
            image.loaded_bytes = Path(args[0]).read_bytes()
            images.append(image)
            return image

        bpy = SimpleNamespace(data=SimpleNamespace(
            materials=SimpleNamespace(new=lambda name: BlenderMaterial()),
            images=SimpleNamespace(load=load_image)))
        namespace["bpy"] = bpy
        entries = [
            Material("satin paint", "ksPerPixelMultiMap_NMDetail", properties={
                "ksSpecularEXP": 30, "sunSpecular": 1, "useDetail": 1, "detailUVMultiplier": 5,
                "detailNormalBlend": 0.5,
            }, textures={"txDiffuse": "shared.dds", "txNormal": "shared.dds",
                         "txDetail": "detail.dds", "txNormalDetail": "normal.dds", "txMaps": "unknown.dds"}),
            Material("glass", "ksWindscreen", blend_mode=1, textures={"txDiffuse": "shared.dds"}),
            Material("lamp", "ksPerPixelMultiMap_emissive", textures={"txDiffuse": "shared.dds", "txEmissive": "light.dds"},
                     vectors={"ksEmissive": {"float3": (4, 2, 0)}}),
            Material("terrain", "ksMultilayer", textures={
                "txDiffuse": "shared.dds", "txMask": "mask.dds",
                "txDetailR": "detail.dds", "txDetailA": "detail.dds",
            }),
            Material("decal", "ksPerPixelMultiMap_AT", alpha_test=True, textures={"txDiffuse": "shared.dds"}),
            Material("unsupported", "customShader", textures={"txDiffuse": "shared.dds"}),
            # Source records from EF26_BARCELONA: opaque DDS alpha is data,
            # while groove.dds contains the opacity of a blended track overlay.
            Material("asph-red", "ksPerPixel", properties={"ksDiffuse": 0.588},
                     textures={"txDiffuse": "asph-red.dds"}),
            Material("jersey", "ksPerPixelMultiMap", properties={"useDetail": 0},
                     textures={"txDiffuse": "jersey.dds"}),
            Material("groove", "ksPerPixelAlpha", blend_mode=1,
                     properties={"alpha": 1, "ksDiffuse": 0.14},
                     textures={"txDiffuse": "shared.dds"}),
            # Reduced material records from the supplied Barcelona base/vegetation KN5s.
            Material("EFVD_ASPH", "ksMultilayer_fresnel_nm", properties={
                "ksSpecular": 1, "ksSpecularEXP": 15, "tarmacSpecularMultiplier": 0.5,
                "multR": 0.4, "multB": 1, "detailNMMult": 0,
            }, vectors={"detailNMMult": {"float2": (30, 30)}}, textures={
                "txDiffuse": "road-base.dds", "txMask": "road-mask.dds",
                "txDetailR": "fine.dds", "txDetailB": "coarse.dds", "txDetailNM": "road-nm.dds",
            }),
            Material("pitlane-buildb_ML", "ksMultilayer_objsp", properties={"multR": 0},
                     vectors={"multR": {"float2": (250, 150)}}, textures={
                         "txDiffuse": "building.dds", "txMask": "building-mask.dds", "txDetailR": "tile.dds",
                     }),
            Material("bushes", "ksGrass", alpha_test=True, properties={"ksAlphaRef": 0.9},
                     textures={"txDiffuse": "shared.dds", "txVariation": "variation.dds"}),
            Material("trees2", "ksTree", alpha_test=True, properties={"ksAlphaRef": 0.1},
                     textures={"txDiffuse": "shared.dds"}),
            Material("fence_track", "ksPerPixel", blend_mode=1, textures={"txDiffuse": "shared.dds"}),
            Material("unknown prop", "customTrackShader", textures={"txAlbedo": "shared.dds"}),
            Material("painted kerb", "ksPerPixelMultiMap_NMDetail", properties={
                "useDetail": 1, "detailUVMultiplier": 80, "ksSpecularEXP": 10,
            }, textures={"txDiffuse": "kerb.dds", "txDetail": "paint-detail.dds", "txNormal": "normal.dds"}),
            Material("generic layers", "ksMultilayer", textures={
                "txDiffuse": "road-base.dds", "txMask": "road-mask.dds",
                "txDetailR": "fine.dds", "txDetailB": "coarse.dds",
            }),
        ]
        model = SimpleNamespace(materials=entries, textures={
            name: b"fake image" for entry in entries for name in entry.textures.values()
        })
        warnings = set()
        with tempfile.TemporaryDirectory() as folder:
            materials = namespace["_materials"](model, "source.kn5", True, folder, warnings)
        self.assertEqual(len(materials), len(entries))
        self.assertTrue(all(material.use_nodes for material in materials))
        shared = [image for image in images if image["kn5_original_name"] == "shared.dds"]
        self.assertEqual({image.colorspace_settings.name for image in shared}, {"sRGB", "Non-Color"})
        self.assertEqual(len(shared), 3)
        self.assertEqual({image.alpha_mode for image in shared}, {"STRAIGHT", "CHANNEL_PACKED"})
        for material, entry in zip(materials, entries):
            for node in material.node_tree.nodes:
                if node.kind == "ShaderNodeTexImage":
                    packed = (node.image.colorspace_settings.name == "Non-Color"
                              or node.name in {"KN5 txDiffuse", "KN5 txAlbedo"} and not settings(entry)["transparent"]
                              or node.name in {"KN5 txDetail", "KN5 txDetailR", "KN5 txDetailG", "KN5 txDetailB", "KN5 txDetailA"})
                    self.assertEqual(node.image.alpha_mode, "CHANNEL_PACKED" if packed else "STRAIGHT")
        overlay = materials[8].node_tree
        diffuse = next(node for node in overlay.nodes if node.kind == "ShaderNodeTexImage")
        alpha = next(node for node in overlay.nodes if node.kind == "ShaderNodeMath")
        self.assertEqual(alpha.operation, "MULTIPLY")
        self.assertEqual(alpha.inputs[1].default_value, 1.0)
        overlay.links.new.assert_any_call(diffuse.outputs["Alpha"], alpha.inputs[0])
        principled = next(node for node in overlay.nodes if node.kind == "ShaderNodeBsdfPrincipled")
        overlay.links.new.assert_any_call(alpha.outputs[0], principled.inputs["Alpha"])

        road = materials[9].node_tree
        road_shader = next(node for node in road.nodes if node.kind == "ShaderNodeBsdfPrincipled")
        self.assertAlmostEqual(road_shader.inputs["Specular IOR Level"].default_value, 1 / 3)
        self.assertEqual(road_shader.inputs["Metallic"].default_value, 0)
        self.assertEqual(road_shader.inputs["Coat Weight"].default_value, 0)
        road_normal = next(node for node in road.nodes if node.kind == "ShaderNodeNormalMap")
        road_texture = next(node for node in road.nodes if node.name == "KN5 txDetailNM")
        road.links.new.assert_any_call(road_texture.outputs["Color"], road_normal.inputs["Color"])
        self.assertEqual(road_texture.image.colorspace_settings.name, "Non-Color")
        diffuse = next(node for node in road.nodes if node.name == "KN5 txDiffuse")
        # A valid road albedo must reach Base Color without uncertain detail/data
        # textures changing its appearance. Detail normals remain a separate path.
        road.links.new.assert_any_call(diffuse.outputs["Color"], road_shader.inputs["Base Color"])
        self.assertFalse(any(node.kind == "ShaderNodeMixRGB" for node in road.nodes))
        self.assertFalse(any(node.name in {"KN5 txMask", "KN5 txDetailR", "KN5 txDetailG",
                                         "KN5 txDetailB", "KN5 txDetailA"} for node in road.nodes))
        mappings = [node.inputs[1].default_value for node in road.nodes
                    if node.kind == "ShaderNodeVectorMath" and node.operation == "MULTIPLY"]
        self.assertIn((30, 30, 1), mappings)
        offsets = [node.inputs[1].default_value for node in road.nodes
                   if node.kind == "ShaderNodeVectorMath" and node.operation == "ADD"]
        self.assertIn((0, -29, 0), offsets)
        building = materials[10].node_tree
        self.assertTrue(any(node.kind == "ShaderNodeVectorMath" and node.operation == "MULTIPLY"
                            and node.inputs[1].default_value == (250, 150, 1) for node in building.nodes))
        for index, threshold in ((11, 0.9), (12, 0.1)):
            tree = materials[index].node_tree
            diffuse = next(node for node in tree.nodes if node.name == "KN5 txDiffuse")
            cutout = next(node for node in tree.nodes if node.kind == "ShaderNodeMath")
            self.assertEqual(diffuse.image.alpha_mode, "STRAIGHT")
            self.assertEqual(cutout.operation, "GREATER_THAN")
            self.assertAlmostEqual(cutout.inputs[1].default_value, threshold)
            tree.links.new.assert_any_call(diffuse.outputs["Alpha"], cutout.inputs[0])
        fence = materials[13].node_tree
        self.assertTrue(any(node.kind == "ShaderNodeMath" and node.operation == "MULTIPLY" for node in fence.nodes))
        fallback = materials[14].node_tree
        albedo = next(node for node in fallback.nodes if node.name == "KN5 txAlbedo")
        fallback_shader = next(node for node in fallback.nodes if node.kind == "ShaderNodeBsdfPrincipled")
        self.assertEqual(albedo.image.alpha_mode, "CHANNEL_PACKED")
        fallback.links.new.assert_any_call(albedo.outputs["Color"], fallback_shader.inputs["Base Color"])
        kerb = materials[15].node_tree
        base = next(node for node in kerb.nodes if node.name == "KN5 txDiffuse")
        detail = next(node for node in kerb.nodes if node.name == "KN5 Detail Color")
        kerb.links.new.assert_any_call(base.outputs["Color"], detail.inputs[1])

        # Evaluate the small color graph to catch lost base color and layer-order bias.
        layers = materials[16].node_tree
        layers_shader = next(node for node in layers.nodes if node.kind == "ShaderNodeBsdfPrincipled")
        incoming = {id(call.args[1]): call.args[0]
                    for tree in (road, layers) for call in tree.links.new.call_args_list}
        owners = {id(socket): (node, key) for tree in (road, layers)
                  for node in tree.nodes for key, socket in node.outputs.items()}
        mask_sample = [0.25, 0, 0.75, 0]
        samples = {"KN5 txDiffuse": (0.8, 0.6, 0.4), "KN5 txDetailR": (0.8, 0.2, 0.1),
                   "KN5 txDetailB": (0.2, 0.5, 0.8)}
        def rgb(value):
            return tuple(value[:3]) if isinstance(value, (tuple, list)) else (value,) * 3
        def value(socket):
            return evaluate(incoming[id(socket)]) if id(socket) in incoming else socket.default_value
        def evaluate(socket):
            node, key = owners[id(socket)]
            if node.kind == "ShaderNodeTexImage":
                if node.name == "KN5 txMask":
                    return mask_sample[3] if key == "Alpha" else tuple(mask_sample[:3])
                return samples[node.name]
            if node.kind == "ShaderNodeSeparateColor":
                return rgb(value(node.inputs["Color"]))[{"Red": 0, "Green": 1, "Blue": 2}[key]]
            a, b = value(node.inputs[0 if node.kind == "ShaderNodeMath" else 1]), value(node.inputs[1 if node.kind == "ShaderNodeMath" else 2])
            if node.kind == "ShaderNodeMath":
                return {"ADD": lambda: a + b, "MAXIMUM": lambda: max(a, b),
                        "MINIMUM": lambda: min(a, b)}[node.operation]()
            a, b, factor = rgb(a), rgb(b), value(node.inputs[0])
            result = {"MULTIPLY": lambda: tuple(x * y for x, y in zip(a, b)),
                      "ADD": lambda: tuple(x + y for x, y in zip(a, b)),
                      "DIVIDE": lambda: tuple(x / y for x, y in zip(a, b)),
                      "MIX": lambda: b}[node.blend_type]()
            return tuple(x * (1 - factor) + y * factor for x, y in zip(a, result))
        # Barcelona's source mask enables both red/blue details. Even adversarial
        # white detail/data samples must leave the road's valid base unchanged.
        original_samples = samples.copy()
        for detail_color in ((1, 1, 1), (0, 0, 0)):
            samples.update({"KN5 txDetailR": detail_color, "KN5 txDetailB": detail_color})
            mask_sample[:] = [1, 0, 1, 1 / 255]
            self.assertEqual(value(road_shader.inputs["Base Color"]), samples["KN5 txDiffuse"])
        samples.update(original_samples)
        mask_sample[:] = [0.25, 0, 0.75, 0]
        for actual, expected in zip(value(layers_shader.inputs["Base Color"]), (0.28, 0.255, 0.25)):
            self.assertAlmostEqual(actual, expected)
        mask_sample[:] = [0, 0, 0, 0]
        self.assertEqual(value(layers_shader.inputs["Base Color"]), (0.8, 0.6, 0.4))
        mask_sample[:] = [0.25, 0, 0.25, 0]
        for actual, expected in zip(value(layers_shader.inputs["Base Color"]), (0.6, 0.405, 0.29)):
            self.assertAlmostEqual(actual, expected)

        # Same basename in two KN5 owners must retain different embedded payloads.
        owner_images = []
        with tempfile.TemporaryDirectory() as folder:
            for filename, payload in (("part-a.kn5", b"owner A"), ("part-b.kn5", b"owner B")):
                owner = SimpleNamespace(materials=[Material("prop", "ksPerPixel", textures={"txDiffuse": "shared.dds"})],
                                        textures={"shared.dds": payload})
                material = namespace["_materials"](owner, filename, True, folder, set())[0]
                owner_images.append(next(node.image for node in material.node_tree.nodes if node.kind == "ShaderNodeTexImage"))
        self.assertIsNot(owner_images[0], owner_images[1])
        self.assertEqual([image.loaded_bytes for image in owner_images], [b"owner A", b"owner B"])
        self.assertTrue(any("txMaps" in warning for warning in warnings))
        self.assertTrue(any("customShader" in warning for warning in warnings))
        self.assertEqual(json.loads(materials[2]["kn5_property_vectors"])["ksEmissive"]["float3"], [4, 2, 0])
        paint_nodes = materials[0].node_tree.nodes
        self.assertTrue(any(node.kind == "ShaderNodeNormalMap" for node in paint_nodes))
        self.assertTrue(any(node.name == "KN5 Detail Normal" for node in paint_nodes))
        glass_nodes = materials[1].node_tree.nodes
        self.assertTrue(any(node.kind == "ShaderNodeMath" and node.operation == "SUBTRACT" for node in glass_nodes))
        with tempfile.TemporaryDirectory() as folder:
            without_textures = namespace["_materials"](model, "source.kn5", False, folder, set())
        self.assertTrue(all(not any(node.kind == "ShaderNodeTexImage" for node in material.node_tree.nodes)
                            for material in without_textures))

    def test_skin_override_cache_keeps_color_and_data_separate(self):
        source = ast.parse((ROOT / "kn5_blender_tools" / "skins.py").read_text())
        functions = ast.Module(body=[node for node in source.body
                                   if isinstance(node, ast.FunctionDef) and node.name == "_load_override"],
                               type_ignores=[])

        class Image(dict):
            def __init__(self):
                self.colorspace_settings = SimpleNamespace(name="sRGB")
                self.pixels, self.size, self.has_data = [0], (1, 1), True
                self.alpha_mode = "STRAIGHT"

        class Images(list):
            def load(self, *args, **kwargs):
                image = Image()
                self.append(image)
                return image

        images = Images()
        namespace = {"bpy": SimpleNamespace(data=SimpleNamespace(images=images))}
        exec(compile(functions, "skin override function", "exec"), namespace)
        color_base, data_base, opaque_base = Image(), Image(), Image()
        data_base.colorspace_settings.name = "Non-Color"
        opaque_base.alpha_mode = "CHANNEL_PACKED"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "skin.dds"
            path.write_bytes(b"fake image")
            color = namespace["_load_override"](path, color_base)
            data = namespace["_load_override"](path, data_base)
            opaque = namespace["_load_override"](path, opaque_base)
            self.assertIsNot(color, data)
            self.assertEqual(color.colorspace_settings.name, "sRGB")
            self.assertEqual(data.colorspace_settings.name, "Non-Color")
            self.assertIsNot(color, opaque)
            self.assertEqual(opaque.alpha_mode, "CHANNEL_PACKED")
            self.assertEqual(color.alpha_mode, "STRAIGHT")
            self.assertIs(namespace["_load_override"](path, opaque_base), opaque)
            self.assertIs(namespace["_load_override"](path, data_base), data)


if __name__ == "__main__":
    unittest.main()

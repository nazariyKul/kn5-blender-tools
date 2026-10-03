"""Focused native-boundary and failure-path checks without launching Blender."""

import ast
from contextlib import contextmanager
from dataclasses import replace
import json
import math
import re
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from kn5_blender_tools.ac_folders import car_skins
from kn5_blender_tools.kn5 import Material, Mesh, Model, Node


ROOT = Path(__file__).resolve().parents[1] / "kn5_blender_tools"


def load(module, names, **namespace):
    source = ast.parse((ROOT / module).read_text())
    selected = ast.Module(body=[node for node in source.body
                               if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                               and node.name in names], type_ignores=[])
    namespace.update(Path=Path, math=math, json=json, tempfile=tempfile,
                     contextmanager=contextmanager)
    exec(compile(selected, module, "exec"), namespace)
    return namespace


class Store(list):
    def new(self, name, *args):
        item = Resource(name)
        self.append(item)
        return item

    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def remove(self, item, **kwargs):
        self[:] = [other for other in self if other is not item]


class Resource(dict):
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.alpha_mode = "STRAIGHT"
        self.colorspace_settings = SimpleNamespace(name="sRGB")
        self.pixels = [1, 1, 1, 0]
        self.size, self.has_data = (1, 1), True
        self.reload = MagicMock()
        self.pack = MagicMock()

    def as_pointer(self):
        return id(self)

    def __bool__(self):
        return True


def blender_data():
    return SimpleNamespace(**{name: Store() for name in
                              ("objects", "meshes", "materials", "images", "collections")})


class Vector(tuple):
    def normalized(self):
        length = math.sqrt(sum(value * value for value in self))
        return Vector(value / length for value in self) if length else self


class Identity:
    def __matmul__(self, vector):
        return vector

    def to_3x3(self):
        return self

    inverted_safe = to_3x3
    transposed = to_3x3


class ReliabilityTests(unittest.TestCase):
    def test_mesh_boundary_and_smooth_before_authored_normals(self):
        mesh = Mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 2)] * 3,
                    [(0, 0), (1, 0), (0, 1)], (0, 1, 2), 0)
        data = SimpleNamespace(materials=[], validate=MagicMock(return_value=False), update=MagicMock())

        def from_pydata(vertices, edges, faces):
            data.vertices = vertices
            data.polygons = [SimpleNamespace(use_smooth=False, material_index=0) for _ in faces]
            data.loops = [SimpleNamespace(index=i, vertex_index=vertex)
                          for i, vertex in enumerate(v for face in faces for v in face)]
            data.uv_layers = SimpleNamespace(new=lambda **kwargs: SimpleNamespace(
                data=[SimpleNamespace(uv=None) for _ in data.loops]))

        data.from_pydata = MagicMock(side_effect=from_pydata)

        def normals_set(normals):
            self.assertTrue(all(poly.use_smooth for poly in data.polygons))
            self.assertEqual(normals, [(0, 0, 1)] * 3)

        data.normals_split_custom_set_from_vertices = MagicMock(side_effect=normals_set)
        bpy = SimpleNamespace(data=SimpleNamespace(meshes=SimpleNamespace(new=MagicMock(return_value=data)),
                                                   objects=SimpleNamespace(new=MagicMock())))
        namespace = load("scene.py", {"_make_mesh"}, bpy=bpy, Vector=Vector)
        make = namespace["_make_mesh"]
        for bad in (replace(mesh, uvs=[]), replace(mesh, normals=[(0, 1)] * 3),
                    replace(mesh, positions=[(0, 0)] * 3), replace(mesh, indices=(0, 1)),
                    replace(mesh, indices=(0, 1, 3)), replace(mesh, indices=(-1, 1, 2)),
                    replace(mesh, indices=(0, 1, 2.0)),
                    replace(mesh, positions=[(float("nan"), 0, 0)] * 3),
                    replace(mesh, uvs=[(0, float("inf"))] * 3)):
            with self.subTest(mesh=bad), self.assertRaises(ValueError):
                make("triangle", [(bad, Identity())], [object()], set())
            bpy.data.meshes.new.assert_not_called()
        make("triangle", [(mesh, Identity())], [object()], set())
        data.normals_split_custom_set_from_vertices.assert_called_once()
        data.materials.clear()
        materials = [object(), object(), object()]
        make("triangle", [(replace(mesh, material_id=2), Identity())], materials, set())
        self.assertEqual(data.materials, [materials[2]])
        self.assertEqual(data.polygons[0].material_index, 0)
        for normals in ([(0, 0, 0)] * 3, [(float("nan"), 0, 1)] * 3):
            data.normals_split_custom_set_from_vertices.reset_mock()
            warnings = set()
            make("triangle", [(replace(mesh, normals=normals), Identity())], [], warnings)
            data.normals_split_custom_set_from_vertices.assert_not_called()
            self.assertIn("Skipped invalid custom normals", warnings)
        data.validate.return_value = True
        data.normals_split_custom_set_from_vertices.reset_mock()
        make("triangle", [(mesh, Identity())], [], set())
        data.normals_split_custom_set_from_vertices.assert_not_called()
        warnings = set()
        make("triangle", [(replace(mesh, indices=(0, 0, 1, 0, 1, 2)), Identity())], [], warnings)
        self.assertEqual(data.from_pydata.call_args.args[2], [(0, 1, 2)])
        self.assertTrue(any("degenerate" in warning for warning in warnings))
        empty = Mesh([], [], [], (), -1)
        make("empty", [(empty, Identity())], [], set())
        self.assertEqual(data.from_pydata.call_args.args, ([], [], []))

    def test_mesh_visibility_filter_and_import_hidden(self):
        mesh = Mesh([], [], [], (), -1)
        visible = Node("visible", 2, True, mesh=mesh)
        collision_child = replace(visible, name="collision-child")
        hidden_child = replace(visible, name="hidden-child")
        collision = Node("collision", 2, True, mesh=replace(mesh, renderable=False),
                         children=[collision_child])
        hidden = Node("hidden", 2, True, mesh=replace(mesh, visible=False),
                      children=[hidden_child])
        both = Node("both", 2, True, mesh=replace(mesh, visible=False, renderable=False))
        model = Model(6, {}, [], Node("root", 1, True, children=[visible, collision, hidden, both]))
        for import_hidden in (False, True):
            with self.subTest(import_hidden=import_hidden):
                bpy = MagicMock()
                objects = {}
                def make_mesh(name, *args):
                    objects[name] = MagicMock()
                    return objects[name]
                make = MagicMock(side_effect=make_mesh)
                namespace = load("scene.py", {"_build"}, bpy=bpy, re=re,
                                 Matrix=SimpleNamespace(Identity=lambda size: Identity()),
                                 _source_matrix=lambda matrix: Identity(), _make_mesh=make,
                                 organize_collection=MagicMock())
                namespace["_build"](model, "source.kn5", import_materials=False,
                                    import_hidden=import_hidden)
                expected = ["visible", "collision-child", "hidden-child"]
                if import_hidden:
                    expected = ["visible", "collision", "collision-child", "hidden", "hidden-child", "both"]
                self.assertEqual([call.args[0] for call in make.call_args_list], expected)
                for name, child in (("collision", collision_child), ("hidden", hidden_child)):
                    parent = objects[name] if import_hidden else bpy.data.objects.new.return_value
                    self.assertIs(objects[child.name].parent, parent)

    def test_transform_and_scale_boundaries(self):
        matrix = MagicMock()
        namespace = load("scene.py", {"_source_matrix", "_build"}, Matrix=matrix)
        for rows in ((), ((1, 2, 3),) * 4, ((float("nan"), 0, 0, 0),) * 4):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                namespace["_source_matrix"](rows)
        matrix.assert_not_called()
        valid = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (10, 20, 30, 1))
        namespace["_source_matrix"](valid)
        matrix.assert_called_once_with(valid)
        matrix.return_value.transposed.assert_called_once()
        for scale in (float("inf"), float("nan"), 0, -1):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                namespace["_build"](None, "source.kn5", scale=scale)

    def test_import_transaction_and_car_postprocessing_failure(self):
        data = blender_data()
        original = [group.new("existing") for group in vars(data).values()]
        bpy = SimpleNamespace(data=data, types=SimpleNamespace(Operator=object),
                              path=SimpleNamespace(abspath=lambda path: path))
        namespace = load("scene.py", {"import_transaction"}, bpy=bpy)
        transaction = namespace["import_transaction"]
        with self.assertRaisesRegex(RuntimeError, "failure"):
            with transaction():
                for group in vars(data).values():
                    group.new("partial")
                raise RuntimeError("failure")
        self.assertEqual([list(group) for group in vars(data).values()], [[item] for item in original])

        def build(*args):
            for group in vars(data).values():
                group.new("partial")
            return data.collections[-1], ()

        property_stub = lambda **kwargs: None
        namespace = load("ac_ui.py", {"IMPORT_SCENE_OT_assetto_corsa_car"}, bpy=bpy,
            StringProperty=property_stub, BoolProperty=property_stub, EnumProperty=property_stub,
            _lod_items=None, _import_skin_items=None, import_transaction=transaction,
            car_lods=lambda path: [SimpleNamespace(path=path / "main.kn5", label="Main")],
            parse=lambda path: object(), build=build,
            prepare_car=MagicMock(side_effect=RuntimeError("skin failure")))
        operator = namespace["IMPORT_SCENE_OT_assetto_corsa_car"]()
        operator.directory, operator.lod, operator.skin = str(ROOT), "AUTO", "BASE"
        operator.report = MagicMock()
        self.assertEqual(operator.execute(SimpleNamespace(scene=SimpleNamespace())), {"CANCELLED"})
        self.assertEqual([list(group) for group in vars(data).values()], [[item] for item in original])
        namespace["prepare_car"] = lambda *args: ()
        namespace["car_skins"] = lambda folder: (("red", "Red", folder / "skins" / "red"),)
        namespace["apply_skin"] = MagicMock(side_effect=RuntimeError("override failure"))
        operator.skin = "red"
        self.assertEqual(operator.execute(SimpleNamespace(scene=SimpleNamespace())), {"CANCELLED"})
        self.assertEqual([list(group) for group in vars(data).values()], [[item] for item in original])

    def test_track_rolls_back_prior_parts_and_progress_errors(self):
        data = blender_data()
        original = [group.new("existing") for group in vars(data).values()]
        bpy = SimpleNamespace(data=data, context=SimpleNamespace(scene=SimpleNamespace(
            collection=SimpleNamespace(children=SimpleNamespace(link=MagicMock())))))
        transaction = load("scene.py", {"import_transaction"}, bpy=bpy)["import_transaction"]
        def build(*args, **kwargs):
            for group in vars(data).values():
                group.new("part")
            anchor = Resource("root")
            anchor["kn5_import_root"] = True
            return SimpleNamespace(all_objects=[anchor]), ()
        namespace = load("tracks.py", {"import_track"}, bpy=bpy, import_transaction=transaction,
                         build=build, _model_transform=MagicMock(), _move_part=MagicMock())
        layout = SimpleNamespace(parts=[SimpleNamespace(path=ROOT / "one.kn5"),
                                        SimpleNamespace(path=ROOT / "two.kn5")], key="DEFAULT")
        namespace["parse"] = MagicMock(side_effect=[object(), ValueError("bad second part")])
        with self.assertRaisesRegex(ValueError, "bad second part"):
            namespace["import_track"](ROOT, layout)
        namespace["_move_part"].assert_called_once()
        self.assertEqual([list(group) for group in vars(data).values()], [[item] for item in original])
        with self.assertRaisesRegex(RuntimeError, "progress failure"):
            namespace["import_track"](ROOT, layout, progress=MagicMock(side_effect=RuntimeError("progress failure")))
        self.assertEqual([list(group) for group in vars(data).values()], [[item] for item in original])

    def test_texture_identity_aliases_invalid_names_and_failed_pack(self):
        images, loaded = Store(), []

        def image_load(path, **kwargs):
            loaded.append((path, Path(path).read_bytes()))
            return images.new(path)

        images.load = image_load
        namespace = load("scene.py", {"_texture_image"}, bpy=SimpleNamespace(data=SimpleNamespace(images=images)))
        model = SimpleNamespace(textures={"first/body.dds": b"first", "second/body.dds": b"second"})
        cache, warnings = {}, set()
        with tempfile.TemporaryDirectory() as temp:
            image = namespace["_texture_image"]("second/body.dds", model, "source.kn5", cache, temp, warnings)
            alias = namespace["_texture_image"]("SECOND\\BODY.DDS", model, "source.kn5", cache, temp, warnings)
            self.assertIs(image, alias)
            self.assertEqual(loaded[0][1], b"second")
            namespace["_texture_image"]("first/body.dds", model, "source.kn5", cache, temp, warnings)
            self.assertNotEqual(loaded[0][0], loaded[1][0])
            for name in ("/", "..", "bad\0name.dds"):
                self.assertIsNone(namespace["_texture_image"](name, model, "source.kn5", cache, temp, warnings))
            self.assertEqual(len(images), 2)
            failed = Resource("failed")
            failed.pack.side_effect = RuntimeError("packing failed")
            def failing_image_load(*args, **kwargs):
                images.append(failed)
                return failed
            images.load = failing_image_load
            self.assertIsNone(namespace["_texture_image"]("first/body.dds", model, "source.kn5", cache,
                                                         temp, warnings, non_color=True))
            self.assertFalse(any(image is failed for image in images))
            failed.pack.side_effect = None
            failed.pixels = []
            self.assertIsNone(namespace["_texture_image"]("first/body.dds", model, "source.kn5", cache,
                                                         temp, warnings, alpha_is_data=True))
            self.assertFalse(any(image is failed for image in images))
        self.assertTrue(any("packing failed" in warning for warning in warnings))

    def test_skin_shared_reload_partial_overrides_and_failure_cleanup(self):
        images = Store()
        base = images.new("base")
        base["kn5_original_name"] = "body.dds"
        base.alpha_mode = "CHANNEL_PACKED"
        second = images.new("second")
        second["kn5_original_name"] = "detail.dds"
        nodes = [Resource("diffuse"), Resource("shared diffuse"), Resource("detail")]
        for node, image in zip(nodes, (base, base, second)):
            node.image = image
            node["ac_base_image"] = image.name
            node["ac_texture_name"] = image["kn5_original_name"]
        bpy = SimpleNamespace(data=SimpleNamespace(images=images))
        namespace = load("skins.py", {"_load_override", "_apply_skin", "apply_skin"}, bpy=bpy,
                         _texture_nodes=lambda collection: iter(nodes))
        with tempfile.TemporaryDirectory() as temp:
            override = Path(temp) / "body.dds"
            override.touch()
            images.load = lambda path, **kwargs: images.new(path)
            namespace["_skin_files"] = lambda collection, skin: {"body.dds": override}
            collection = {"ac_active_skin": "BASE"}
            self.assertEqual(namespace["apply_skin"](collection, "Синій skin")[0], 2)
            self.assertIs(nodes[0].image, nodes[1].image)
            self.assertIs(nodes[2].image, second)
            active = nodes[0].image
            self.assertEqual(active.alpha_mode, "CHANNEL_PACKED")
            namespace["apply_skin"](collection, "Синій skin", reload=True)
            active.reload.assert_called_once()
            namespace["apply_skin"](collection, "BASE")
            self.assertIs(nodes[0].image, base)
            self.assertIs(nodes[1].image, base)
            prior = list(images)
            namespace["_skin_files"] = lambda collection, skin: {"body.dds": override, "detail.dds": override}
            def bad_override(path, image, **kwargs):
                if image is second:
                    raise RuntimeError("decode failed")
                return images.new("unused override")
            namespace["_load_override"] = bad_override
            with self.assertRaisesRegex(RuntimeError, "decode failed"):
                namespace["apply_skin"](collection, "broken")
            self.assertEqual([id(image) for image in images], [id(image) for image in prior])
            self.assertEqual(collection["ac_active_skin"], "BASE")
            self.assertIs(nodes[0].image, base)

    def test_external_texture_cache_preserves_exact_case_and_source_priority(self):
        images = Store()
        namespace = load("scene.py", {"_texture_image"}, bpy=SimpleNamespace(data=SimpleNamespace(images=images)))
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "texture").mkdir()
            first, second = folder / "body.dds", folder / "texture" / "BODY.DDS"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            loaded = []
            def image_load(path, **kwargs):
                loaded.append(Path(path).read_bytes())
                return images.new(path)
            images.load = image_load
            # Supply a case-sensitive inventory even on macOS's default filesystem.
            cache = {"_external_files": {"body.dds": first},
                     "_external_exact": {"body.dds": first, "BODY.DDS": second}}
            model = SimpleNamespace(textures={})
            first_image = namespace["_texture_image"]("body.dds", model, folder / "main.kn5", cache, temp, set())
            namespace["_texture_image"]("BODY.DDS", model, folder / "main.kn5", cache, temp, set())
            alias = namespace["_texture_image"]("Body.dds", model, folder / "main.kn5", cache, temp, set())
            self.assertEqual(loaded, [b"first", b"second"])
            self.assertIs(first_image, alias)

    def test_duplicate_material_names_keep_their_own_skin_detail(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            skin = folder / "skins" / "test"
            skin.mkdir(parents=True)
            materials = []
            for name in ("one.dds", "two.dds"):
                (skin / name).touch()
                material = Resource("duplicate")
                material["kn5_original_name"] = "duplicate"
                material["kn5_textures"] = json.dumps({"txDetail": name})
                shader = MagicMock(type="BSDF_PRINCIPLED")
                shader.inputs["Base Color"].is_linked = False
                material.node_tree = MagicMock()
                material.node_tree.nodes.__iter__.side_effect = lambda shader=shader: iter([shader])
                materials.append(material)
            collection = Resource("car")
            collection.all_objects = [SimpleNamespace(type="MESH", data=SimpleNamespace(materials=materials))]
            texture = MagicMock(return_value=Resource("image"))
            namespace = load("skins.py", {"prepare_car"}, car_skins=car_skins, _texture_image=texture,
                             _opaque_zero_alpha_diffuse=lambda node: None, _texture_nodes=lambda collection: ())
            model = SimpleNamespace(materials=[Material("duplicate", "ksPerPixel", textures={"txDetail": name})
                                               for name in ("one.dds", "two.dds")])
            namespace["prepare_car"](collection, folder, folder / "main.kn5", "Main", model)
            self.assertEqual([call.args[0] for call in texture.call_args_list], ["one.dds", "two.dds"])
            self.assertTrue(all(call.kwargs["alpha_is_data"] for call in texture.call_args_list))

    def test_skin_alpha_repair_preserves_transparency_and_skips_packed_pixels(self):
        image = Resource("diffuse")
        diffuse = SimpleNamespace(type="TEX_IMAGE", image=image,
                                  outputs={"Alpha": SimpleNamespace(is_linked=True)})
        mix = SimpleNamespace(inputs={1: SimpleNamespace(is_linked=True,
                                links=[SimpleNamespace(from_node=diffuse)])})
        detail = SimpleNamespace(id_data=SimpleNamespace(nodes=SimpleNamespace(get=lambda name: mix)))
        namespace = load("skins.py", {"_opaque_zero_alpha_diffuse"})
        namespace["_opaque_zero_alpha_diffuse"](detail)
        self.assertEqual(image.alpha_mode, "STRAIGHT")
        diffuse.outputs["Alpha"].is_linked = False
        namespace["_opaque_zero_alpha_diffuse"](detail)
        self.assertEqual(image.alpha_mode, "NONE")
        diffuse.image = SimpleNamespace(alpha_mode="CHANNEL_PACKED")
        namespace["_opaque_zero_alpha_diffuse"](detail)  # No pixels property: no full-image copy.

    def test_sidebar_registration_releases_callback_cache(self):
        callbacks, classes, cache = [], [object() for _ in range(6)], {}
        bpy = SimpleNamespace(types=SimpleNamespace(Scene=SimpleNamespace(), Collection=SimpleNamespace(),
            TOPBAR_MT_file_import=SimpleNamespace(append=callbacks.append, remove=callbacks.remove)),
            utils=SimpleNamespace(register_class=MagicMock(), unregister_class=MagicMock()))
        namespace = load("ac_ui.py", {"register", "unregister", "_stable_items"}, bpy=bpy,
                         _CLASSES=classes, _enum_cache=cache, _menu=object(),
                         EnumProperty=lambda **kwargs: object())
        for name in ("_car_items", "_get_car_choice", "_set_car_choice", "_skin_items",
                     "_get_skin_choice", "_set_skin_choice"):
            namespace[name] = object()
        for _ in range(3):
            namespace["register"]()
            items = (("skin", "Skin", ""),)
            self.assertIs(namespace["_stable_items"](items), namespace["_stable_items"](items))
            namespace["unregister"]()
            self.assertEqual(callbacks, [])
            self.assertEqual(cache, {})
            self.assertFalse(hasattr(bpy.types.Scene, "ac_car_choice"))
            self.assertFalse(hasattr(bpy.types.Collection, "ac_skin_choice"))
        self.assertEqual([call.args[0] for call in bpy.utils.register_class.call_args_list], classes * 3)
        self.assertEqual([call.args[0] for call in bpy.utils.unregister_class.call_args_list], list(reversed(classes)) * 3)

    def test_folder_choice_callbacks_resolve_blender_relative_paths(self):
        namespace = load("ac_ui.py", {"_lod_items", "_layout_items"},
                         bpy=SimpleNamespace(path=SimpleNamespace(abspath=lambda path: "/asset/folder")),
                         car_lods=MagicMock(return_value=[]), track_layouts=MagicMock(return_value=[]),
                         _stable_items=lambda items: items)
        operator = SimpleNamespace(directory="//asset")
        self.assertEqual(namespace["_lod_items"](operator, None)[0][0], "AUTO")
        self.assertEqual(namespace["_layout_items"](operator, None)[0][0], "AUTO")
        namespace["car_lods"].assert_called_once_with("/asset/folder")
        namespace["track_layouts"].assert_called_once_with("/asset/folder")


if __name__ == "__main__":
    unittest.main()

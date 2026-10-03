import struct
import tempfile
import unittest
from pathlib import Path

from kn5_blender_tools.kn5 import KN5Error, parse
from kn5_blender_tools.organize import classify


def i(value):
    return struct.pack("<i", value)


def string(value):
    data = value.encode()
    return i(len(data)) + data


def fixture(indices=(0, 1, 2), translation=(0, 0, 0), visible=True, renderable=True):
    data = bytearray(b"sc6969" + i(6) + i(0) + i(0) + i(0))
    data += i(1) + string("root") + i(1) + b"\1"
    data += struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, *translation, 1)
    data += i(2) + string("triangle") + i(0) + bytes((1, 1, visible, 0)) + i(3)
    for pos, uv in [((0, 0, 0), (0, 0)), ((1, 0, 0), (1, 0)), ((0, 1, 0), (0, 1))]:
        data += struct.pack("<3f3f2f3f", *pos, 0, 0, 1, *uv, 0, 0, 0)
    data += i(len(indices)) + struct.pack("<" + str(len(indices)) + "H", *indices)
    data += i(-1) + bytes(28) + bytes((renderable,))
    return data


def skinned_fixture(visible=True):
    data = bytearray(b"sc6969" + i(6) + i(0) + i(0) + i(0))
    data += i(3) + string("driver") + i(0) + bytes((1, 1, visible, 0))
    data += i(1) + string("bone") + bytes(64) + i(3)
    for pos in ((0, 0, 0), (1, 0, 0), (0, 1, 0)):
        data += struct.pack("<3f3f2f11f", *pos, 0, 0, 1, 0, 0, *([0] * 11))
    data += i(3) + struct.pack("<3H", 0, 1, 2) + i(-1) + bytes(12)
    return data


class ParserTests(unittest.TestCase):
    def parse_bytes(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.kn5"
            path.write_bytes(data)
            return parse(path)

    def test_mesh_hierarchy_and_uv(self):
        model = self.parse_bytes(fixture())
        mesh_node = model.root.children[0]
        self.assertEqual(mesh_node.name, "triangle")
        self.assertEqual(mesh_node.mesh.indices, (0, 1, 2))
        self.assertEqual(mesh_node.mesh.uvs[0], (0, 1))
        self.assertEqual(mesh_node.mesh.uvs[2], (0, 0))
        self.assertEqual(mesh_node.mesh.normals[0], (0, 0, 1))
        self.assertEqual(model.warnings, [])

    def test_mesh_visibility_and_renderability_flags(self):
        for visible in (False, True):
            for renderable in (False, True):
                with self.subTest(visible=visible, renderable=renderable):
                    mesh = self.parse_bytes(fixture(visible=visible, renderable=renderable)).root.children[0].mesh
                    self.assertEqual(mesh.visible, visible)
                    self.assertEqual(mesh.renderable, renderable)
            mesh = self.parse_bytes(skinned_fixture(visible=visible)).root.mesh
            self.assertEqual(mesh.visible, visible)
            self.assertTrue(mesh.renderable)

    def test_rejects_corruption(self):
        for data in (b"BAD" + fixture()[3:], fixture()[:-1], fixture((0, 1, 9))):
            with self.subTest(data_length=len(data)), self.assertRaises(KN5Error):
                self.parse_bytes(data)

    def test_skinned_geometry_in_bind_pose(self):
        node = self.parse_bytes(skinned_fixture()).root
        self.assertTrue(node.skinned)
        self.assertEqual(node.mesh.indices, (0, 1, 2))

    def test_short_material_records_in_supported_versions(self):
        for version in (4, 5, 6):
            record = string("a") + string("x") + b"\0\0"
            if version > 4:
                record += i(0)
            record += i(0) + i(0)
            data = b"sc6969" + i(version) + (i(0) if version > 5 else b"")
            data += i(0) + i(12) + record * 12
            data += i(1) + string("root") + i(0) + b"\1"
            data += struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
            with self.subTest(version=version):
                self.assertEqual(len(self.parse_bytes(data).materials), 12)

    def test_rejects_nonfinite_geometry_but_preserves_normal_fallback(self):
        data = fixture()
        vertex = data.index(b"triangle") + len("triangle") + 12
        matrix = data.index(b"root") + len("root") + 5
        for offset in (vertex, vertex + 24, vertex + 28, matrix):
            for value in (float("nan"), float("inf"), -float("inf")):
                corrupt = bytearray(data)
                struct.pack_into("<f", corrupt, offset, value)
                with self.subTest(offset=offset, value=value), self.assertRaises(KN5Error):
                    self.parse_bytes(corrupt)
        unusual = bytearray(data)
        struct.pack_into("<f", unusual, vertex + 12, float("nan"))
        self.assertNotEqual(self.parse_bytes(unusual).root.children[0].mesh.normals[0][0], 0)

    def test_empty_mesh_bad_triangle_count_and_depth_limit(self):
        self.assertEqual(self.parse_bytes(fixture(())).root.children[0].mesh.indices, ())
        with self.assertRaises(KN5Error):
            self.parse_bytes(fixture((0, 1)))
        header = b"sc6969" + i(6) + i(0) + i(0) + i(0)
        matrix = struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
        parent = i(1) + string("node") + i(1) + b"\1" + matrix
        leaf = i(1) + string("leaf") + i(0) + b"\1" + matrix
        self.parse_bytes(header + parent * 256 + leaf)
        with self.assertRaisesRegex(KN5Error, "256 levels"):
            self.parse_bytes(header + parent * 257 + leaf)

    def test_f1_names_use_parent_and_material_evidence(self):
        cases = (
            (("x0_tyre_fl.003", "tread_medium.001", ("WHEEL_RF",)), ("TYRES", "Tyre_FR_Tread")),
            (("disc_bl.002", "sidewall.001", ("WHEEL_RR",)), ("TYRES", "Tyre_RR_Sidewall")),
            (("disc_fr_SUB1", "discs", ("WHEEL_RF",)), ("BRAKES", "Brake_Disc_FR")),
            (("suspension_fl.001", "sauber_detail", ()), ("SUSPENSION", "Suspension_FL_Detail")),
            (("frontwing_fr_01", "sauber_paint", ()), ("FRONT_WING", "Front_Wing_FR")),
            (("rearwing_top", "sauber_paint", ()), ("REAR_WING", "Rear_Wing")),
            (("safetycell.001", "sauber_paint", ()), ("BODY", "Body")),
            (("safetycell.013", "rear_light_2", ()), ("LIGHTS", "Rear_Light")),
            (("wing_mirror_r.004", "glass", ()), ("GLASS", "Mirror_R_Glass")),
            (("wing_mirror_l.004", "glass", ()), ("GLASS", "Mirror_L_Glass")),
            (("Cylinder014", "chrome.002", ("COCKPIT_HR",)), ("OTHER", "Cylinder_014")),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(classify(*source), expected)

    def test_real_sample_when_present(self):
        sample = Path(__file__).resolve().parents[1] / "f1_2026_r26.kn5"
        if not sample.is_file():
            self.skipTest("Real KN5 sample not installed")
        model = parse(sample)
        self.assertEqual((model.version, len(model.textures), len(model.materials)), (6, 42, 31))
        def meshes(node):
            return int(node.mesh is not None) + sum(map(meshes, node.children))
        self.assertEqual(meshes(model.root), 284)
        emissive = next(mat for mat in model.materials if mat.name == "kers_red")
        self.assertAlmostEqual(emissive.vectors["ksEmissive"]["float3"][0], 0.3)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from kn5_blender_tools.ac_folders import car_lods, car_skins, track_layouts


class FolderDiscoveryTests(unittest.TestCase):
    def test_car_lods_and_skins(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "data").mkdir()
            (folder / "skins" / "Red").mkdir(parents=True)
            (folder / "skins" / "Blue").mkdir()
            (folder / "skins" / "Red" / "ui_skin.json").write_text('{"skinname":"Race Red"}')
            for name in ("main.kn5", "low.kn5", "collider.kn5"):
                (folder / name).touch()
            (folder / "data" / "lods.ini").write_text(
                "[LOD_1]\nFILE=low.kn5\n[LOD_0]\nFILE=main.kn5\n")
            self.assertEqual([lod.path.name for lod in car_lods(folder)], ["main.kn5", "low.kn5"])
            self.assertEqual([name for _, name, _ in car_skins(folder)], ["Blue", "Race Red"])

    def test_ambiguous_car_and_missing_lod_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "a.kn5").touch()
            (folder / "b.kn5").touch()
            with self.assertRaisesRegex(ValueError, "Multiple visual KN5"):
                car_lods(folder)
            (folder / "data").mkdir()
            (folder / "data" / "lods.ini").write_text(
                "[LOD_0]\nFILE=missing.kn5\n[LOD_1]\nFILE=b.kn5\n")
            self.assertEqual(car_lods(folder)[0].path.name, "b.kn5")

    def test_track_models_layouts_and_collision_exclusion(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for name in ("road.kn5", "props.kn5", "collider.kn5", "dynamic.kn5"):
                (folder / name).touch()
            (folder / "models.ini").write_text(
                "[MODEL_1]\nFILE=props.kn5\n[MODEL_0]\nFILE=road.kn5\n"
                "POSITION=1,2,3\n[DYNAMIC_OBJECT_0]\nFILE=dynamic.kn5\n")
            (folder / "models_short.ini").write_text(
                "[MODEL_0]\nFILE=road.kn5\n[MODEL_1]\nFILE=collider.kn5\n")
            layouts = track_layouts(folder)
            self.assertEqual([layout.key for layout in layouts], ["DEFAULT", "short"])
            self.assertEqual([part.path.name for part in layouts[0].parts], ["road.kn5", "props.kn5"])
            self.assertEqual(layouts[0].parts[0].position, (1.0, 2.0, 3.0))
            self.assertEqual(len(layouts[1].parts), 1)

    def test_real_fixtures_when_present(self):
        root = Path(__file__).resolve().parents[1]
        car = root / "asw-ford-gt-12/content/cars/pb_fordgt_05"
        track = root / "eF26_Barcelona"
        if car.is_dir():
            self.assertEqual(car_lods(car)[0].path.name, "fordgt.kn5")
            self.assertEqual(len(car_skins(car)), 6)
        if track.is_dir():
            self.assertEqual(len(track_layouts(track)[0].parts), 34)

    def test_windows_model_paths_case_and_nested_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "Models").mkdir()
            model = folder / "Models" / "Road.KN5"
            model.touch()
            (folder / "data").mkdir()
            (folder / "data" / "lods.ini").write_text("[LOD_0]\nFILE=models\\road.kn5\n")
            self.assertTrue(car_lods(folder)[0].path.samefile(model))
            (folder / "short").mkdir()
            (folder / "short" / "models.ini").write_text("[MODEL_0]\nFILE=../models/ROAD.kn5\n")
            self.assertTrue(track_layouts(folder)[0].parts[0].path.samefile(model))
            (folder / "data" / "lods.ini").write_text("[LOD_0]\nFILE=../../escape.kn5\n")
            with self.assertRaisesRegex(ValueError, "Invalid KN5 path"):
                car_lods(folder)

    def test_missing_track_models_and_nonfinite_transforms_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "road.kn5").touch()
            ini = folder / "models.ini"
            ini.write_text("[MODEL_0]\nFILE=road.kn5\n[MODEL_1]\nFILE=missing.kn5\n")
            with self.assertRaisesRegex(FileNotFoundError, "MODEL_1"):
                track_layouts(folder)
            ini.write_text('[MODEL_0]\nFILE=road.kn5\n[MODEL_1]\nFILE="collider.kn5"\n')
            self.assertEqual(len(track_layouts(folder)[0].parts), 1)
            for value in ("nan,0,0", "1,inf,0", "0,0,-inf", "1,2"):
                ini.write_text(f"[MODEL_0]\nFILE=road.kn5\nPOSITION={value}\n")
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "transform"):
                    track_layouts(folder)

    def test_bad_optional_skin_metadata_and_ini_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            skin = folder / "skins" / "Синій skin"
            skin.mkdir(parents=True)
            for metadata in ("null", "[]", "42", '"text"', "{bad"):
                (skin / "ui_skin.json").write_text(metadata)
                with self.subTest(metadata=metadata):
                    self.assertEqual(car_skins(folder)[0][1], skin.name)
            (folder / "models.ini").write_text("FILE=road.kn5\n")
            with self.assertRaisesRegex(ValueError, "Invalid Assetto Corsa INI"):
                track_layouts(folder)

    def test_uppercase_kn5_fallback_ignores_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            model = folder / "main.KN5"
            model.touch()
            (folder / "other.kn5").mkdir()
            self.assertEqual(car_lods(folder)[0].path, model.resolve())
            self.assertEqual(track_layouts(folder)[0].parts[0].path, model.resolve())


if __name__ == "__main__":
    unittest.main()

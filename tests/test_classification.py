"""Small checks for the two independent Assetto Corsa classifiers."""

import unittest

from kn5_blender_tools.classification import classify_car, classify_track


class ClassificationTests(unittest.TestCase):
    def test_car_and_track_use_their_own_evidence(self):
        self.assertEqual(classify_car("RIM_RF_SUB1", ancestors=("SUSP_RF", "WHEEL_RF"))[0], "WHEELS")
        self.assertEqual(classify_car("HOOD_SUB0", material="CarPaint")[0], "BODY")
        self.assertEqual(classify_car("Unknown", material="COCKPIT_OPQ")[0], "INTERIOR")
        self.assertEqual(classify_track("01TRM-BRC", material="asph-red")[0], "ROAD")
        self.assertEqual(classify_track("WHEEL_LF", source="Sopwith_Path_Red.kn5")[0], "PROPS")
        self.assertEqual(classify_track("Object001", material="Material #1")[0], "OTHER")


if __name__ == "__main__":
    unittest.main()

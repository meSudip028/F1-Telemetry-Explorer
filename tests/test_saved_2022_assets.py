from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = PROJECT_ROOT / "images"

QUALIFYING_CHARTS = [
    "f1_circuit_speed_map.png",
    "f1_telemetry_analysis.png",
    "f1_driver_comparison.png",
]

RACE_CHARTS = [
    "race_position_progression.png",
    "race_lap_time_progression.png",
    "race_fastest_lap_comparison.png",
]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class TestSaved2022Assets(unittest.TestCase):

    def check_png(self, path):
        self.assertTrue(path.is_file(), f"Missing file: {path}")
        self.assertGreater(path.stat().st_size, 0, f"Empty file: {path}")

        with path.open("rb") as file:
            signature = file.read(8)

        self.assertEqual(
            signature,
            PNG_SIGNATURE,
            f"Invalid PNG file: {path}",
        )

    def test_all_22_qualifying_folders_exist(self):
        folders = list(IMAGE_DIR.glob("2022-*-qualifying"))
        self.assertEqual(len(folders), 22)

    def test_all_qualifying_charts_are_valid(self):
        folders = list(IMAGE_DIR.glob("2022-*-qualifying"))

        for folder in folders:
            with self.subTest(grand_prix=folder.name):
                for filename in QUALIFYING_CHARTS:
                    self.check_png(folder / filename)

    def test_all_22_race_folders_exist(self):
        folders = list(IMAGE_DIR.glob("2022-*-race"))
        self.assertEqual(len(folders), 22)

    def test_all_race_charts_and_source_notes_exist(self):
        folders = list(IMAGE_DIR.glob("2022-*-race"))

        for folder in folders:
            with self.subTest(grand_prix=folder.name):
                for filename in RACE_CHARTS:
                    self.check_png(folder / filename)

                source_note = folder / "RACE_DATA_SOURCE.txt"
                self.assertTrue(
                    source_note.is_file(),
                    f"Missing data-source note: {source_note}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)

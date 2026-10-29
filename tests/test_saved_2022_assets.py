from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = PROJECT_ROOT / "images"

YEARS = (2022, 2023)

TELEMETRY_CHARTS = [
    "f1_circuit_speed_map.png",
    "f1_telemetry_analysis.png",
    "f1_driver_comparison.png",
]

QUALIFYING_CHARTS = [
    "qualifying_q1_times.png",
    "qualifying_q2_times.png",
    "qualifying_q3_times.png",
]

RACE_CHARTS = [
    "race_position_progression.png",
    "race_lap_time_progression.png",
    "race_fastest_lap_comparison.png",
]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class TestSavedSeasonAssets(unittest.TestCase):

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

    def test_all_season_folders_exist(self):
        for year in YEARS:
            with self.subTest(year=year):
                qualifying = list(
                    IMAGE_DIR.glob(f"{year}-*-qualifying")
                )
                race = list(IMAGE_DIR.glob(f"{year}-*-race"))

                self.assertEqual(
                    len(qualifying), 22,
                    f"Expected 22 qualifying folders for {year}",
                )
                self.assertEqual(
                    len(race), 22,
                    f"Expected 22 race folders for {year}",
                )

    def test_all_qualifying_charts_are_valid(self):
        for year in YEARS:
            folders = list(
                IMAGE_DIR.glob(f"{year}-*-qualifying")
            )

            for folder in folders:
                with self.subTest(grand_prix=folder.name):
                    if year == 2022:
                        expected_charts = TELEMETRY_CHARTS
                    else:
                        expected_charts = QUALIFYING_CHARTS

                    for filename in expected_charts:
                        self.check_png(folder / filename)

                    if year == 2023:
                        self.assertTrue(
                            (folder / "QUALIFYING_DATA_SOURCE.txt").is_file(),
                            f"Missing qualifying data-source note: {folder}",
                        )

    def test_all_race_charts_are_valid(self):
        for year in YEARS:
            folders = list(IMAGE_DIR.glob(f"{year}-*-race"))

            for folder in folders:
                with self.subTest(grand_prix=folder.name):
                    for filename in RACE_CHARTS:
                        self.check_png(folder / filename)

                    self.assertTrue(
                        (folder / "RACE_DATA_SOURCE.txt").is_file(),
                        f"Missing race data-source note: {folder}",
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)

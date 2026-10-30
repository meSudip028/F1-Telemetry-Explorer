
import unittest

from driver_profiles import combine_driver_seasons


def make_driver(
    name,
    teams,
    starts,
    wins,
    podiums,
    points,
    position,
    best_finish,
):
    given_name, family_name = name.split(" ", 1)

    return {
        "given_name": given_name,
        "family_name": family_name,
        "full_name": name,
        "code": "",
        "permanent_number": "",
        "nationality": "",
        "date_of_birth": "",
        "wikipedia_url": "",
        "teams": teams,
        "grand_prix_starts": starts,
        "race_wins": wins,
        "podiums": podiums,
        "points": points,
        "championship_position": position,
        "best_finish": best_finish,
    }


def make_season(race_count, drivers):
    return {
        "race_count": race_count,
        "drivers": drivers,
    }


class TestDriverProfiles(unittest.TestCase):

    def setUp(self):

        self.seasons = {
            2022: make_season(22, {
                "zhou": make_driver(
                    "Guanyu Zhou",
                    ["Alfa Romeo"],
                    22, 0, 0, 6, 18, 8
                ),
                "sainz": make_driver(
                    "Carlos Sainz",
                    ["Ferrari"],
                    22, 1, 9, 246, 5, 1
                ),
            }),

            2023: make_season(22, {
                "zhou": make_driver(
                    "Guanyu Zhou",
                    ["Alfa Romeo"],
                    22, 0, 0, 6, 18, 9
                ),
                "sainz": make_driver(
                    "Carlos Sainz",
                    ["Ferrari"],
                    22, 1, 3, 200, 7, 1
                ),
            }),

            2024: make_season(24, {
                "zhou": make_driver(
                    "Guanyu Zhou",
                    ["Sauber"],
                    24, 0, 0, 4, 20, 11
                ),
                "sainz": make_driver(
                    "Carlos Sainz",
                    ["Ferrari"],
                    24, 2, 5, 290, 5, 1
                ),
            }),

            2025: make_season(24, {
                "sainz": make_driver(
                    "Carlos Sainz",
                    ["Williams"],
                    24, 0, 0, 64, 9, 3
                ),
            }),
        }

    def test_zhou_appears_in_all_participating_seasons(self):

        result = combine_driver_seasons(
            self.seasons,
            [2022, 2023, 2024, 2025],
        )

        zhou = result["drivers"]["zhou"]

        self.assertEqual(
            sorted(zhou["seasons"]),
            [2022, 2023, 2024],
        )

        self.assertEqual(
            zhou["teams"],
            ["Alfa Romeo", "Sauber"],
        )

    def test_driver_statistics_are_aggregated(self):

        result = combine_driver_seasons(
            self.seasons,
            [2022, 2023, 2024, 2025],
        )

        zhou = result["drivers"]["zhou"]

        self.assertEqual(zhou["total_starts"], 68)
        self.assertEqual(zhou["total_wins"], 0)
        self.assertEqual(zhou["total_podiums"], 0)
        self.assertEqual(zhou["total_points"], 16)

        sainz = result["drivers"]["sainz"]

        self.assertEqual(sainz["total_wins"], 4)
        self.assertEqual(sainz["total_points"], 800)

    def test_team_changes_are_preserved(self):

        result = combine_driver_seasons(
            self.seasons,
            [2022, 2023, 2024, 2025],
        )

        sainz = result["drivers"]["sainz"]

        self.assertEqual(
            sainz["teams"],
            ["Ferrari", "Williams"],
        )

    def test_unavailable_season_is_reported(self):

        available_seasons = {
            year: self.seasons[year]
            for year in (2022, 2023, 2024)
        }

        result = combine_driver_seasons(
            available_seasons,
            [2022, 2023, 2024, 2025],
            {2025: "HTTP 429: Too Many Requests"},
        )

        self.assertEqual(
            result["years"],
            [2022, 2023, 2024],
        )

        self.assertIn(
            2025,
            result["unavailable_seasons"],
        )

        zhou = result["drivers"]["zhou"]

        self.assertNotIn(2025, zhou["seasons"])

    def test_empty_database_raises_error(self):

        with self.assertRaises(ValueError):
            combine_driver_seasons(
                {},
                [2022, 2023, 2024, 2025],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

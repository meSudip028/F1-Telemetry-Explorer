
"""Pure data aggregation utilities for F1 driver profiles."""


def combine_driver_seasons(
    season_data_by_year,
    requested_years,
    unavailable_seasons=None,
):
    """Combine available season records into driver profiles."""

    requested_years = tuple(
        int(year) for year in requested_years
    )

    unavailable_seasons = dict(
        unavailable_seasons or {}
    )

    driver_database = {}
    race_counts = {}

    for year in requested_years:

        season_data = season_data_by_year.get(year)

        if season_data is None:
            continue

        race_counts[year] = int(
            season_data.get("race_count", 0)
        )

        for driver_id, season_profile in (
            season_data.get("drivers", {}).items()
        ):

            if driver_id not in driver_database:

                driver_database[driver_id] = {
                    "driver_id": driver_id,
                    "given_name": season_profile.get("given_name", ""),
                    "family_name": season_profile.get("family_name", ""),
                    "full_name": season_profile.get("full_name", ""),
                    "code": season_profile.get("code", ""),
                    "permanent_number": season_profile.get(
                        "permanent_number", ""
                    ),
                    "nationality": season_profile.get("nationality", ""),
                    "date_of_birth": season_profile.get(
                        "date_of_birth", ""
                    ),
                    "wikipedia_url": season_profile.get(
                        "wikipedia_url", ""
                    ),
                    "teams": [],
                    "seasons": {},
                    "total_starts": 0,
                    "total_wins": 0,
                    "total_podiums": 0,
                    "total_points": 0.0,
                    "championship_titles": 0,
                }

            profile = driver_database[driver_id]

            profile["seasons"][year] = {
                "team": list(season_profile.get("teams", [])),
                "starts": int(
                    season_profile.get("grand_prix_starts", 0)
                ),
                "wins": int(
                    season_profile.get("race_wins", 0)
                ),
                "podiums": int(
                    season_profile.get("podiums", 0)
                ),
                "points": float(
                    season_profile.get("points", 0)
                ),
                "championship_position": season_profile.get(
                    "championship_position"
                ),
                "best_finish": season_profile.get("best_finish"),
            }

            profile["total_starts"] += (
                season_profile.get("grand_prix_starts", 0)
            )

            profile["total_wins"] += (
                season_profile.get("race_wins", 0)
            )

            profile["total_podiums"] += (
                season_profile.get("podiums", 0)
            )

            profile["total_points"] += float(
                season_profile.get("points", 0)
            )

            if season_profile.get("championship_position") == 1:
                profile["championship_titles"] += 1

            for team in season_profile.get("teams", []):

                if team not in profile["teams"]:
                    profile["teams"].append(team)

    if not driver_database:
        raise ValueError(
            "No historical driver data could be loaded."
        )

    return {
        "years": sorted(race_counts.keys()),
        "requested_years": list(requested_years),
        "race_counts": race_counts,
        "drivers": driver_database,
        "unavailable_seasons": unavailable_seasons,
    }

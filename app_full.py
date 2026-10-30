
# ============================================================
# F1 Telemetry Explorer - Interactive Dashboard
# ============================================================

import io
import os
import re
import json
import urllib.error
import urllib.request
import urllib.parse
import unicodedata
from datetime import datetime
from pathlib import Path

import fastf1
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from matplotlib.collections import LineCollection
from driver_profiles import combine_driver_seasons


# ------------------------------------------------------------
# 1. Page and project settings
# ------------------------------------------------------------

st.set_page_config(
    page_title="F1 Telemetry Explorer",
    page_icon="🏎️",
    layout="wide"
)

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "fastf1_cache"
IMAGE_DIR = BASE_DIR / "images"
OUTPUT_ROOT = BASE_DIR / "f1_outputs"

CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Optional authentication from Streamlit Secrets.
# Never place account passwords directly in this file.
try:
    for key in ("F1_USERNAME", "F1_PASSWORD"):
        if key in st.secrets and st.secrets[key]:
            os.environ[key] = str(st.secrets[key])
except Exception:
    # Local development can continue without configured secrets.
    pass

fastf1.Cache.configure(cache_dir=str(CACHE_DIR))


# ------------------------------------------------------------
# 2. Styling
# ------------------------------------------------------------

BACKGROUND = "#15151e"
PANEL = "#1e1e2b"
GRID = "#3a3a4d"
TEXT = "#f0f0f5"
MUTED = "#a0a0b5"
RED = "#ff4d4d"
BLUE = "#4d9bff"
CYAN = "#00d2ff"
GREEN = "#2ee66b"
ORANGE = "#ffb020"


st.markdown(
    """
    <style>
        .stApp {
            background-color: #15151e;
        }

        h1, h2, h3, p, label {
            color: #f0f0f5;
        }

        [data-testid="stSidebar"] {
            background-color: #1e1e2b;
        }

        div[data-testid="stMetric"] {
            background-color: #1e1e2b;
            border: 1px solid #3a3a4d;
            padding: 14px;
            border-radius: 10px;
        }
    </style>
    """,
    unsafe_allow_html=True
)


# ------------------------------------------------------------
# 3. Helper functions
# ------------------------------------------------------------

class DataProblem(Exception):
    """An expected issue with session data or telemetry."""


def format_lap_time(lap_time):
    """Format a lap time like 1:30.558."""
    if pd.isna(lap_time):
        return "No time"

    seconds_total = lap_time.total_seconds()
    minutes = int(seconds_total // 60)
    seconds = seconds_total - minutes * 60

    return f"{minutes}:{seconds:06.3f}"


def slugify(value):
    """Convert a name into a safe folder name."""
    return re.sub(
        r"[^a-z0-9]+",
        "-",
        str(value).lower()
    ).strip("-")

# ------------------------------------------------------------
# ------------------------------------------------------------
# Multi-season Grand Prix results from the Jolpica F1 API
# ------------------------------------------------------------

JOLPICA_BASE_URL = "https://api.jolpi.ca/ergast/f1"


def normalize_race_slug(value):
    """Normalize race names for matching API names to image folders."""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def parse_saved_folder(folder_name):
    """Return the season, event slug, and session from a saved folder."""
    match = re.fullmatch(
        r"(?P<year>\d{4})-(?P<event>.+)-(?P<session>qualifying|race)",
        str(folder_name).lower(),
    )

    if not match:
        raise DataProblem(
            f"Unrecognized saved session folder: {folder_name}"
        )

    session = match.group("session").title()

    return (
        int(match.group("year")),
        match.group("event"),
        session,
    )


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_season_races(year):
    """Fetch the race schedule for a season and cache it for one day."""
    url = f"{JOLPICA_BASE_URL}/{int(year)}/races/?limit=100"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "F1-Telemetry-Explorer/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)

    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as error:
        raise DataProblem(
            f"Could not load the {year} race schedule."
        ) from error

    races = (
        payload.get("MRData", {})
        .get("RaceTable", {})
        .get("Races", [])
    )

    if not races:
        raise DataProblem(
            f"No races were returned for the {year} season."
        )

    return races


def get_race_round(year, folder_name):
    """Match a saved folder to its official season round."""
    folder_year, event_slug, _ = parse_saved_folder(folder_name)

    if folder_year != int(year):
        raise DataProblem(
            f"Folder season {folder_year} does not match {year}."
        )

    target_slug = normalize_race_slug(event_slug)

    for race in fetch_season_races(year):
        race_name = race.get("raceName", "")

        if normalize_race_slug(race_name) == target_slug:
            return int(race["round"])

    raise DataProblem(
        f"Could not match {folder_name} to a race in {year}."
    )


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_results(year, round_number, session_type):
    """Fetch qualifying or race results for any season."""
    endpoint_by_session = {
        "Qualifying": "qualifying",
        "Race": "results",
    }

    if session_type not in endpoint_by_session:
        raise ValueError("Session must be Qualifying or Race.")

    endpoint = endpoint_by_session[session_type]
    url = (
        f"{JOLPICA_BASE_URL}/{int(year)}/{int(round_number)}/"
        f"{endpoint}/?limit=100"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "F1-Telemetry-Explorer/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)

    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as error:
        raise DataProblem(
            f"Could not load {session_type.lower()} results "
            f"for {year}."
        ) from error

    races = (
        payload.get("MRData", {})
        .get("RaceTable", {})
        .get("Races", [])
    )

    if not races:
        raise DataProblem(
            f"No {session_type.lower()} results were returned "
            f"for round {round_number} of {year}."
        )

    return races[0]


# ------------------------------------------------------------
# Historical F1 championship standings
# ------------------------------------------------------------


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_championship_standings(year, category):
    """Fetch historical driver or constructor championship standings."""

    category = str(category).strip().lower()

    endpoint_by_category = {
        "drivers": "driverStandings",
        "constructors": "constructorStandings",
    }

    if category not in endpoint_by_category:
        raise ValueError(
            "Category must be 'drivers' or 'constructors'."
        )

    endpoint = endpoint_by_category[category]

    url = (
        f"{JOLPICA_BASE_URL}/{int(year)}/"
        f"{endpoint}/?limit=100"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "F1-Telemetry-Explorer/1.0"
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:
            payload = json.load(response)

    except urllib.error.HTTPError as error:
        raise DataProblem(
            f"Could not load {year} {category} championship "
            f"standings (HTTP {error.code}: {error.reason})."
        ) from error

    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as error:
        raise DataProblem(
            f"Could not load {year} {category} championship "
            f"standings ({type(error).__name__}: {error})."
        ) from error

    # Extract standings from the API response.
    standings_lists = (
        payload.get("MRData", {})
        .get("StandingsTable", {})
        .get("StandingsLists", [])
    )

    if not standings_lists:
        raise DataProblem(
            f"No {year} {category} standings were returned."
        )

    result_key = (
        "DriverStandings"
        if category == "drivers"
        else "ConstructorStandings"
    )

    standings = standings_lists[0].get(result_key, [])

    if not standings:
        raise DataProblem(
            f"No {year} {category} standings were available."
        )

    return standings


# ------------------------------------------------------------
# Historical race podium statistics
# ------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_season_podium_statistics(year):
    """Count driver and constructor podiums from all race results."""

    from collections import defaultdict
    import time

    driver_podiums = defaultdict(int)
    constructor_podiums = defaultdict(int)

    seen_results = set()
    race_rounds = set()

    limit = 100
    offset = 0
    total = None

    while total is None or offset < total:
        url = (
            f"{JOLPICA_BASE_URL}/{int(year)}/results/"
            f"?limit={limit}&offset={offset}"
        )

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "F1-Telemetry-Explorer/1.0"}
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)

        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as error:
            raise DataProblem(
                f"Could not load {year} race results for podium counts."
            ) from error

        metadata = payload.get("MRData", {})
        total = int(metadata.get("total", 0))
        actual_limit = int(metadata.get("limit", limit))

        races = (
            metadata.get("RaceTable", {})
            .get("Races", [])
        )

        if not races or actual_limit <= 0:
            break

        for race in races:
            round_number = race.get("round")
            race_rounds.add(round_number)

            for result in race.get("Results", []):
                try:
                    position = int(result["position"])
                except (KeyError, ValueError, TypeError):
                    continue

                if position not in (1, 2, 3):
                    continue

                driver_id = result["Driver"]["driverId"]
                constructor_id = (
                    result["Constructor"]["constructorId"]
                )

                result_key = (round_number, driver_id)

                if result_key in seen_results:
                    continue

                seen_results.add(result_key)

                driver_podiums[driver_id] += 1
                constructor_podiums[constructor_id] += 1

        offset += actual_limit

        if offset < total:
            time.sleep(0.2)

    return {
        "drivers": dict(driver_podiums),
        "constructors": dict(constructor_podiums),
        "race_count": len(race_rounds),
    }



# ------------------------------------------------------------
# Historical driver profile data
# ------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_season_driver_profiles(year):
    """
    Fetch every driver who appeared in a Grand Prix during a season.

    Championship points and positions come from final standings.
    Starts, race wins, podiums and team history come from race results.
    """

    import time

    limit = 100
    offset = 0
    total = None

    drivers = {}
    race_rounds = set()

    while total is None or offset < total:

        url = (
            f"{JOLPICA_BASE_URL}/{int(year)}/results/"
            f"?limit={limit}&offset={offset}"
        )

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "F1-Telemetry-Explorer/1.0"
            },
        )


        last_error = None

        for attempt in range(3):
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=30,
                ) as response:
                    payload = json.load(response)

                last_error = None
                break


            except urllib.error.HTTPError as error:

                if error.code == 429:
                    retry_after = error.headers.get("Retry-After")

                    message = (
                        f"Jolpica rate limit reached for {year} "
                        "(HTTP 429)."
                    )

                    if retry_after:
                        message += (
                            f" Retry after: {retry_after}."
                        )
                    else:
                        message += (
                            " Try again after the API rate window resets."
                        )

                    raise DataProblem(message) from error

                last_error = error

                if error.code not in (
                    408, 500, 502, 503, 504
                ):
                    break


            except (
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
            ) as error:
                last_error = error

            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))

        if last_error is not None:
            raise DataProblem(
                f"Could not load {year} driver race history "
                f"after {attempt + 1} attempt(s): "
                f"{type(last_error).__name__}: {last_error}"
            ) from last_error


        metadata = payload.get("MRData", {})

        try:
            total = int(metadata.get("total", 0))
            actual_limit = int(metadata.get("limit") or limit)
        except (TypeError, ValueError):
            raise DataProblem(
                f"Invalid pagination data returned for {year}."
            )

        if actual_limit <= 0:
            raise DataProblem(
                f"Invalid API pagination limit for {year}."
            )

        races = (
            metadata.get("RaceTable", {})
            .get("Races", [])
        )

        if not races:
            if offset < total:
                raise DataProblem(
                    f"Incomplete driver history download for {year}."
                )
            break

        for race in races:

            round_number = race.get("round")

            if round_number is not None:
                race_rounds.add(str(round_number))

            for result in race.get("Results", []):

                driver = result.get("Driver", {})
                driver_id = driver.get("driverId")

                if not driver_id:
                    continue

                if driver_id not in drivers:
                    drivers[driver_id] = {
                        "driver_id": driver_id,
                        "given_name": driver.get("givenName", ""),
                        "family_name": driver.get("familyName", ""),
                        "full_name": (
                            f"{driver.get('givenName', '')} "
                            f"{driver.get('familyName', '')}"
                        ).strip(),
                        "code": driver.get("code", ""),
                        "permanent_number": driver.get(
                            "permanentNumber", ""
                        ),
                        "nationality": driver.get("nationality", ""),
                        "date_of_birth": driver.get("dateOfBirth", ""),
                        "wikipedia_url": driver.get("url", ""),
                        "grand_prix_starts": 0,
                        "race_wins": 0,
                        "podiums": 0,
                        "best_finish": None,
                        "teams": [],
                        "points": 0.0,
                        "championship_position": None,
                    }

                profile = drivers[driver_id]

                # Count appearances in Grand Prix race results.
                profile["grand_prix_starts"] += 1

                constructor_name = (
                    result.get("Constructor", {}).get("name")
                )

                if (
                    constructor_name
                    and constructor_name not in profile["teams"]
                ):
                    profile["teams"].append(constructor_name)

                try:
                    position = int(result.get("position"))
                except (TypeError, ValueError):
                    position = None

                if position is not None:

                    if (
                        profile["best_finish"] is None
                        or position < profile["best_finish"]
                    ):
                        profile["best_finish"] = position

                    if position == 1:
                        profile["race_wins"] += 1

                    if position in (1, 2, 3):
                        profile["podiums"] += 1

        offset += actual_limit

        if offset < total:
            time.sleep(0.2)

    if not drivers:
        raise DataProblem(
            f"No participating drivers were found for {year}."
        )

    # Use final championship standings for official points
    # and championship positions.
    standings = fetch_championship_standings(
        year,
        "drivers",
    )

    standings_by_id = {
        item["Driver"]["driverId"]: item
        for item in standings
        if item.get("Driver", {}).get("driverId")
    }

    for driver_id, profile in drivers.items():

        standing = standings_by_id.get(driver_id)

        if standing:

            profile["points"] = float(
                standing.get("points", 0)
            )

            try:
                profile["championship_position"] = int(
                    standing["position"]
                )
            except (KeyError, TypeError, ValueError):
                profile["championship_position"] = None

    return {
        "year": int(year),
        "race_count": len(race_rounds),
        "drivers": drivers,
    }


# ------------------------------------------------------------
# Combined four-season driver database
# ------------------------------------------------------------


@st.cache_data(ttl=300, show_spinner=False)
def fetch_driver_profile_database(
    season_years=(2022, 2023, 2024, 2025),
):
    """Fetch available seasons and combine their driver profiles."""

    season_years = tuple(int(year) for year in season_years)

    season_data_by_year = {}
    unavailable_seasons = {}
    rate_limited = False

    for year in season_years:

        if rate_limited:
            unavailable_seasons[year] = (
                "Skipped because an earlier request encountered "
                "the Jolpica API rate limit."
            )
            continue

        try:
            season_data = fetch_season_driver_profiles(year)
            season_data_by_year[year] = season_data

        except DataProblem as error:
            unavailable_seasons[year] = str(error)

            if "HTTP 429" in str(error):
                rate_limited = True

    try:
        return combine_driver_seasons(
            season_data_by_year=season_data_by_year,
            requested_years=season_years,
            unavailable_seasons=unavailable_seasons,
        )

    except ValueError as error:
        raise DataProblem(
            "No historical driver data could be loaded. "
            "Please try again after the API rate limit resets."
        ) from error


# Backward-compatible wrappers for the existing 2022 gallery.
def get_2022_round(folder_name):
    return get_race_round(2022, folder_name)


def fetch_2022_results(round_number, session_type):
    return fetch_results(2022, round_number, session_type)
# ------------------------------------------------------------
# Driver portrait lookup using the Wikipedia page-image API
# ------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_driver_photo_url(driver_url):
    """Return a driver's Wikipedia thumbnail URL, if available."""
    if not driver_url:
        return None

    try:
        parsed_url = urllib.parse.urlparse(driver_url)

        if (
            not parsed_url.hostname
            or not parsed_url.hostname.endswith("wikipedia.org")
        ):
            return None

        page_title = urllib.parse.unquote(
            parsed_url.path.rstrip("/").split("/")[-1]
        )

        if not page_title:
            return None

        params = urllib.parse.urlencode({
            "action": "query",
            "format": "json",
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": 640,
            "titles": page_title,
        })

        request = urllib.request.Request(
            f"https://en.wikipedia.org/w/api.php?{params}",
            headers={
                "User-Agent": "F1-Telemetry-Explorer/1.0"
            },
        )

        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.load(response)

        pages = payload.get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})

        return page.get("thumbnail", {}).get("source")

    except Exception:
        return None

def style_axis(ax, ylabel):
    """Apply the dashboard's dark chart style."""
    ax.set_facecolor(PANEL)
    ax.set_ylabel(ylabel, color=TEXT, fontsize=10)
    ax.grid(True, color=GRID, linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=TEXT, labelsize=9)

    for spine in ax.spines.values():
        spine.set_color(GRID)


def figure_to_png(fig):
    """Convert a Matplotlib figure into downloadable PNG bytes."""
    buffer = io.BytesIO()

    fig.savefig(
        buffer,
        format="png",
        dpi=180,
        bbox_inches="tight",
        facecolor=fig.get_facecolor()
    )

    buffer.seek(0)
    return buffer.getvalue()


def get_driver_name(session, driver_code):
    """Look up a driver's full name when available."""
    try:
        results = session.results

        if (
            results is not None
            and not results.empty
            and {"Abbreviation", "FullName"}.issubset(results.columns)
        ):
            matching = results[
                results["Abbreviation"] == driver_code
            ]

            if not matching.empty:
                return matching.iloc[0]["FullName"]

    except Exception:
        pass

    return driver_code


def get_ranked_drivers(session):
    """Return classified drivers in finishing-position order."""
    try:
        results = session.results

        if (
            results is None
            or results.empty
            or not {"Position", "Abbreviation"}.issubset(results.columns)
        ):
            return []

        ranked = results.copy()

        ranked["Position"] = pd.to_numeric(
            ranked["Position"],
            errors="coerce"
        )

        ranked = ranked.dropna(
            subset=["Position", "Abbreviation"]
        ).sort_values("Position")

        ranked["Abbreviation"] = (
            ranked["Abbreviation"].astype(str).str.upper()
        )

        return ranked["Abbreviation"].drop_duplicates().tolist()

    except Exception:
        return []


def get_fastest_valid_lap(session, driver_code):
    """Prefer accurate timed laps, then select the fastest available."""
    laps = session.laps.pick_drivers(driver_code)
    laps = laps.dropna(subset=["LapTime"]).copy()

    if laps.empty:
        raise DataProblem(
            f"No timed laps were found for {driver_code}."
        )

    if "IsAccurate" in laps.columns:
        accurate = laps["IsAccurate"].eq(True)

        if accurate.any():
            laps = laps.loc[accurate].copy()

    if laps.empty:
        raise DataProblem(
            f"No usable laps were found for {driver_code}."
        )

    lap = laps.pick_fastest()

    if lap is None or pd.isna(lap["LapTime"]):
        raise DataProblem(
            f"No usable fastest lap was found for {driver_code}."
        )

    return lap


def prepare_telemetry(lap):
    """Retrieve and clean the channels used in our graphs."""
    telemetry = lap.get_telemetry()

    required = [
        "Distance", "Speed", "Throttle", "Brake", "nGear"
    ]

    if telemetry is None or telemetry.empty:
        raise DataProblem("No telemetry was available for this lap.")

    missing = [
        column for column in required
        if column not in telemetry.columns
    ]

    if missing:
        raise DataProblem(
            f"Telemetry is missing these columns: {missing}"
        )

    brake_raw = telemetry["Brake"]

    if pd.api.types.is_bool_dtype(brake_raw):
        brake = brake_raw.astype(int)
    else:
        brake = pd.to_numeric(brake_raw, errors="coerce")

    data = pd.DataFrame({
        "Distance": pd.to_numeric(
            telemetry["Distance"], errors="coerce"
        ),
        "Speed": pd.to_numeric(
            telemetry["Speed"], errors="coerce"
        ),
        "Throttle": pd.to_numeric(
            telemetry["Throttle"], errors="coerce"
        ),
        "Brake": pd.to_numeric(brake, errors="coerce"),
        "nGear": pd.to_numeric(
            telemetry["nGear"], errors="coerce"
        )
    })

    data = data.replace([np.inf, -np.inf], np.nan)
    data = data.dropna(subset=required)

    if len(data) < 10:
        raise DataProblem(
            "Too few usable telemetry points were found."
        )

    return data.sort_values("Distance").reset_index(drop=True)


def prepare_comparison_telemetry(lap, driver_code):
    """Prepare distance and elapsed-time data for comparison."""
    telemetry = lap.get_telemetry()

    required = ["Distance", "Speed", "Throttle", "Brake", "Time"]

    if telemetry is None or telemetry.empty:
        raise DataProblem(f"No telemetry was available for {driver_code}.")

    missing = [
        column for column in required
        if column not in telemetry.columns
    ]

    if missing:
        raise DataProblem(
            f"{driver_code} telemetry is missing: {missing}"
        )

    times = pd.to_timedelta(telemetry["Time"], errors="coerce")
    valid_times = times.dropna()

    if valid_times.empty:
        raise DataProblem(f"No usable timestamps for {driver_code}.")

    elapsed = (times - valid_times.iloc[0]).dt.total_seconds()

    brake_raw = telemetry["Brake"]

    if pd.api.types.is_bool_dtype(brake_raw):
        brake = brake_raw.astype(int)
    else:
        brake = pd.to_numeric(brake_raw, errors="coerce")

    data = pd.DataFrame({
        "Distance": pd.to_numeric(
            telemetry["Distance"], errors="coerce"
        ).to_numpy(),
        "Speed": pd.to_numeric(
            telemetry["Speed"], errors="coerce"
        ).to_numpy(),
        "Throttle": pd.to_numeric(
            telemetry["Throttle"], errors="coerce"
        ).to_numpy(),
        "Brake": pd.to_numeric(brake, errors="coerce").to_numpy(),
        "Elapsed": elapsed.to_numpy()
    })

    data = data.replace([np.inf, -np.inf], np.nan).dropna()

    if len(data) < 10:
        raise DataProblem(
            f"Too few usable telemetry points for {driver_code}."
        )

    # Interpolation needs unique, sorted distance values.
    data = data.sort_values("Distance")

    data = data.groupby(
        "Distance", as_index=False
    ).agg({
        "Speed": "mean",
        "Throttle": "mean",
        "Brake": "max",
        "Elapsed": "mean"
    })

    if data["Distance"].max() <= data["Distance"].min():
        raise DataProblem(
            f"Distance does not vary for {driver_code}."
        )

    return data


def show_saved_gallery():
    """Display screenshots already saved in the GitHub repository."""
    saved_races = [
        (
            "2022-bahrain-grand-prix-qualifying",
            "2022 Bahrain Grand Prix — Qualifying"
        ),
        (
            "2022-saudi-arabian-grand-prix-qualifying",
            "2022 Saudi Arabian Grand Prix — Qualifying"
        )
    ]

    st.subheader("Saved example analyses")

    st.caption(
        "These previously saved charts remain available even when "
        "the selected session cannot be downloaded."
    )

    for folder_name, title in saved_races:
        folder = IMAGE_DIR / folder_name

        files = [
            ("f1_circuit_speed_map.png", "Circuit speed map"),
            ("f1_telemetry_analysis.png", "Telemetry analysis"),
            ("f1_driver_comparison.png", "Driver comparison")
        ]

        existing = [
            (filename, label)
            for filename, label in files
            if (folder / filename).is_file()
        ]

        if not existing:
            continue

        st.markdown(f"### {title}")
    for filename, label in existing:
      image_path = folder / filename

    st.subheader(label)

    if image_path.is_file():
        st.image(
            str(image_path),
            caption=label,
            use_container_width=True
        )

        with st.expander(f"Download {label}"):
            st.download_button(
                label=f"Download {label} (PNG)",
                data=image_path.read_bytes(),
                file_name=filename,
                mime="image/png",
                key=f"download_{folder.name}_{filename}",
            )
    else:
        st.warning(f"Image not found: {filename}")

    st.divider()

# ------------------------------------------------------------
# 4. Cached data functions
# ------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def get_schedule(year):
    """Download an event schedule and cache it for one day."""
    return fastf1.get_event_schedule(year)



@st.cache_resource(show_spinner=False)
def load_session(year, event_name, session_name):
    """Load a FastF1 session and validate that lap data is available."""

    session = fastf1.get_session(
        year,
        event_name,
        session_name,
    )

    try:
        session.load(
            laps=True,
            telemetry=True,
            weather=False,
            messages=False,
        )

        laps = session.laps

    except Exception as error:
        error_name = type(error).__name__

        if error_name == "DataNotLoadedError":
            raise DataProblem(
                "FastF1 could not retrieve archived lap and timing data. "
                "This may be because the F1 TV subscription required "
                "for archived data is inactive or the archive is "
                "temporarily unavailable. Choose Browse saved analyses "
                "to access the available historical data."
            ) from error

        raise

    if laps is None or laps.empty:
        raise DataProblem(
            "The selected session loaded without usable lap data. "
            "Try Browse saved analyses instead."
        )

    return session



# ------------------------------------------------------------
# 5. Dashboard header
# ------------------------------------------------------------

st.title("🏎️ F1 Telemetry Explorer")

st.markdown(
    "Explore Formula 1 qualifying, circuit speed maps, "
    "car telemetry and driver comparisons."
)

st.caption(
    "Educational data analysis using FastF1. "
    "Results depend on the availability of the source data."
)


# ------------------------------------------------------------
# Choose saved analyses or attempt to load a new F1 session
# ------------------------------------------------------------

st.sidebar.title("Explore F1 Data")

data_mode = st.sidebar.radio(
    "Choose data source",
    [
        "Browse saved analyses",
        "Championship Comparison",
        "Driver Profiles",
        "Load a new F1 session",
    ],
    index=0,
)

if data_mode == "Browse saved analyses":
    st.info(
        "Browse your saved F1 analyses below. "
        "No F1 account or new data download is required."
    )

    saved_races = {
        "2022 Bahrain Grand Prix — Qualifying":
            "2022-bahrain-grand-prix-qualifying",
        "2022 Saudi Arabian Grand Prix — Qualifying":
            "2022-saudi-arabian-grand-prix-qualifying",
    }

    # Only show race choices for folders that actually exist locally.
    available_saved_races = {
        label: folder_name
        for label, folder_name in saved_races.items()
        if (IMAGE_DIR / folder_name).is_dir()
    }

    # Also include any other image folders added later.
    if IMAGE_DIR.is_dir():
        known_folders = set(available_saved_races.values())
        for folder in sorted(IMAGE_DIR.iterdir()):
            if folder.is_dir() and folder.name not in known_folders:
                label = folder.name.replace("-", " ").title()
                available_saved_races[label] = folder.name

    if not available_saved_races:
        st.warning(
            f"No saved race folders were found under {IMAGE_DIR}. "
            "Check that your images folder contains race-specific subfolders."
        )
    else:
                # --------------------------------------------------------
        # Choose a Grand Prix and session from saved analyses
        # --------------------------------------------------------

               # --------------------------------------------------------
        # Select season, Grand Prix, and session
        # --------------------------------------------------------

        available_gp_sessions = {}

        for folder in sorted(IMAGE_DIR.iterdir()):
            if not folder.is_dir():
                continue

            try:
                folder_year, event_slug, session_type = (
                    parse_saved_folder(folder.name)
                )
            except (DataProblem, ValueError):
                continue

            gp_short_name = event_slug.removesuffix("-grand-prix")
            gp_label = (
                f"{gp_short_name.replace('-', ' ').title()} Grand Prix"
            )

            available_gp_sessions.setdefault(
                folder_year, {}
            ).setdefault(gp_label, {})[session_type] = folder.name

        if not available_gp_sessions:
            st.warning("No saved Grand Prix sessions were found.")
            st.stop()

        available_years = sorted(
            available_gp_sessions.keys(),
            reverse=True,
        )

        selected_year = st.sidebar.selectbox(
            "Select a season",
            available_years,
            key="saved_season",
        )

        races_for_year = available_gp_sessions[selected_year]

        selected_gp = st.sidebar.selectbox(
            "Select a Grand Prix",
            sorted(races_for_year.keys()),
            key=f"saved_gp_{selected_year}",
        )

        session_options = [
            session
            for session in ["Qualifying", "Race"]
            if session in races_for_year[selected_gp]
        ]

        selected_session = st.sidebar.radio(
            "Choose session",
            session_options,
            horizontal=True,
            key=f"saved_session_{selected_year}_{normalize_race_slug(selected_gp)}",
        )

        race_folder = (
            IMAGE_DIR
            / races_for_year[selected_gp][selected_session]
        )

        st.header(f"{selected_year} {selected_gp}")
        st.caption(f"Selected session: {selected_session}")
        st.caption(f"Selected session: {selected_session}")

        # --------------------------------------------------------
        # Official top-three results
        # --------------------------------------------------------

        results = []

        try:
            round_number = get_race_round(
             selected_year,
             race_folder.name,
        )
            result_data = fetch_results(
    selected_year,
    round_number,
    selected_session,
)

            if selected_session == "Qualifying":
                results = result_data.get("QualifyingResults", [])
                st.subheader("⏱️ Qualifying — Top 3")
            else:
                results = result_data.get("Results", [])
                st.subheader("🏁 Race — Top 3")

        except Exception as error:
            st.warning(
                f"Official result cards are temporarily unavailable: {error}"
            )

        # --------------------------------------------------------
        # Pole sitter / race winner spotlight
        # --------------------------------------------------------

        if results:
            spotlight = results[0]
            driver = spotlight.get("Driver", {})
            team = spotlight.get("Constructor", {}).get(
                "name", "Unknown team"
            )

            driver_name = (
                f"{driver.get('givenName', '')} "
                f"{driver.get('familyName', '')}"
            ).strip()

            if selected_session == "Qualifying":
                spotlight_title = "🏁 POLE POSITION"
                spotlight_time = (
                    spotlight.get("Q3")
                    or spotlight.get("Q2")
                    or spotlight.get("Q1")
                    or "Time unavailable"
                )
                time_label = "Best qualifying lap"
            else:
                spotlight_title = "🏆 RACE WINNER"
                time_info = spotlight.get("Time") or {}
                spotlight_time = (
                    time_info.get("time")
                    or spotlight.get("status", "Unavailable")
                )
                time_label = "Race time / status"

            st.markdown(f"### {spotlight_title}")

            with st.container(border=True):
                photo_col, details_col = st.columns([1, 2])

                with photo_col:
                    photo_url = fetch_driver_photo_url(
                        driver.get("url")
                    )

                    if photo_url:
                        st.image(
                            photo_url,
                            caption=driver_name,
                            width=260,
                        )
                    else:
                        st.caption("Driver photo unavailable")

                with details_col:
                    st.markdown(f"## {driver_name}")
                    st.markdown(f"**Team:** {team}")
                    st.metric(time_label, spotlight_time)

                    if driver.get("url"):
                        st.markdown(
                            f"[Driver profile and photo source]"
                            f"({driver['url']})"
                        )

            st.divider()

            result_columns = st.columns(min(3, len(results)))

            for column, result in zip(
                result_columns,
                results[:3],
            ):
                result_driver = result.get("Driver", {})
                result_team = result.get("Constructor", {}).get(
                    "name", "Unknown team"
                )

                name = (
                    f"{result_driver.get('givenName', '')} "
                    f"{result_driver.get('familyName', '')}"
                ).strip()

                if selected_session == "Qualifying":
                    displayed_time = (
                        result.get("Q3")
                        or result.get("Q2")
                        or result.get("Q1")
                        or "Unavailable"
                    )
                    metric_label = "Qualifying lap"
                else:
                    time_info = result.get("Time") or {}
                    displayed_time = (
                        time_info.get("time")
                        or result.get("status", "Unavailable")
                    )
                    metric_label = "Race time / gap"

                with column:
                    with st.container(border=True):
                        st.caption(
                            f"POSITION {result.get('position', '—')}"
                        )
                        st.markdown(f"### {name}")
                        st.write(result_team)
                        st.metric(metric_label, displayed_time)

        # --------------------------------------------------------
        # Display only charts which exist for the chosen session
        # --------------------------------------------------------

              # --------------------------------------------------------
        # Display charts for the selected year and session
        # --------------------------------------------------------

        standard_qualifying_charts = [
            ("f1_circuit_speed_map.png", "Circuit speed map"),
            ("f1_telemetry_analysis.png", "Telemetry analysis"),
            ("f1_driver_comparison.png", "Driver comparison"),
        ]

        public_qualifying_charts = [
            (
                "qualifying_q1_times.png",
                "Qualifying Q1 — Lap-time comparison",
            ),
            (
                "qualifying_q2_times.png",
                "Qualifying Q2 — Lap-time comparison",
            ),
            (
                "qualifying_q3_times.png",
                "Qualifying Q3 — Lap-time comparison",
            ),
        ]

        public_race_charts = [
            (
                "race_position_progression.png",
                "Race position progression — public timing data",
            ),
            (
                "race_lap_time_progression.png",
                "Race lap-time progression — public timing data",
            ),
            (
                "race_fastest_lap_comparison.png",
                "Fastest recorded lap comparison — public timing data",
            ),
        ]

        if selected_session == "Race":
            charts = public_race_charts + [
                (
                    "f1_circuit_speed_map.png",
                    "Circuit speed map — FastF1 session data",
                ),
                (
                    "f1_telemetry_analysis.png",
                    "Car telemetry — FastF1 session data",
                ),
                (
                    "f1_driver_comparison.png",
                    "Driver comparison — FastF1 session data",
                ),
            ]

            st.subheader("Race analysis")
            st.caption(
                "Public Race charts use recorded lap times and positions, "
                "not high-frequency car telemetry. FastF1 charts appear "
                "only when those files are available."
            )

        elif (race_folder / "qualifying_q1_times.png").is_file():
            charts = public_qualifying_charts
            st.subheader("Qualifying lap-time analysis")
            st.caption(
                "These charts use public qualifying results for Q1, Q2, "
                "and Q3. They are not speed, throttle, brake, gear, "
                "or GPS telemetry."
            )

        else:
            charts = standard_qualifying_charts
            st.subheader("Qualifying telemetry analysis")

        existing_charts = [
            (filename, caption)
            for filename, caption in charts
            if (race_folder / filename).is_file()
        ]

        if not existing_charts:
            st.warning(
                "No charts were found for this session. "
                "Check the saved files under the images folder."
            )

        for filename, caption in existing_charts:
            image_path = race_folder / filename

            st.markdown(f"### {caption}")

            st.image(
                str(image_path),
                caption=caption,
                width="stretch",
            )

            with st.expander(f"Download {caption}"):
                st.download_button(
                    label=f"Download {caption} (PNG)",
                    data=image_path.read_bytes(),
                    file_name=filename,
                    mime="image/png",
                    key=f"download_{race_folder.name}_{filename}",
                )

            st.divider()


    # Don't execute any live-data code in saved-analysis mode.
    st.stop()




elif data_mode == "Championship Comparison":

    st.title("🏆 F1 Championship Comparison")

    st.caption(
        "Compare Formula 1 Drivers and Constructors "
        "Championship standings across 2022, 2023, 2024, and 2025."
    )

    category = st.radio(
        "Choose championship",
        ["Drivers", "Constructors"],
        horizontal=True,
        key="championship_category",
    )

    season_years = [2022, 2023, 2024, 2025]

    # --------------------------------------------------------
    # Load standings and podium statistics for all seasons
    # --------------------------------------------------------

    standings_by_year = {}
    podium_stats_by_year = {}

    try:
        with st.spinner("Loading four-season championship data..."):

            for season_year in season_years:

                standings_by_year[season_year] = (
                    fetch_championship_standings(
                        season_year,
                        category,
                    )
                )

                podium_stats_by_year[season_year] = (
                    fetch_season_podium_statistics(
                        season_year
                    )
                )

    except Exception as error:
        st.error(
            f"Could not load championship data: {error}"
        )
        st.stop()

    # --------------------------------------------------------
    # Prepare championship rows
    # --------------------------------------------------------

    def make_championship_rows(
        standings,
        category,
        podium_statistics,
    ):
        rows = []

        stats_key = (
            "drivers"
            if category == "Drivers"
            else "constructors"
        )

        podium_lookup = podium_statistics.get(
            stats_key, {}
        )

        for item in standings:

            if category == "Drivers":

                participant = item["Driver"]

                name = (
                    f"{participant.get('givenName', '')} "
                    f"{participant.get('familyName', '')}"
                ).strip()

                participant_id = participant["driverId"]

                team = item.get(
                    "Constructors", [{}]
                )[0].get("name", "Unknown")

            else:

                participant = item["Constructor"]

                name = participant.get("name", "Unknown")

                participant_id = participant["constructorId"]

                team = name

            rows.append({
                "Position": int(item["position"]),
                "Name": name,
                "Team": team,
                "Points": float(item["points"]),
                "Wins": int(item["wins"]),
                "Podiums": int(
                    podium_lookup.get(participant_id, 0)
                ),
            })

        return rows

    # Build standings for all four seasons.

    rows_by_year = {}

    for season_year in season_years:

        rows_by_year[season_year] = make_championship_rows(
            standings_by_year[season_year],
            category,
            podium_stats_by_year[season_year],
        )

        if not rows_by_year[season_year]:
            st.error(
                f"No {category.lower()} standings found for "
                f"{season_year}."
            )
            st.stop()

    # --------------------------------------------------------
    # Season champions
    # --------------------------------------------------------

    st.subheader("🏆 Season Champions")

    champion_columns = st.columns(len(season_years))

    for column, season_year in zip(
        champion_columns,
        season_years,
    ):

        champion = rows_by_year[season_year][0]

        with column:

            with st.container(border=True):

                st.caption(
                    f"{season_year} Champion"
                )

                st.markdown(
                    f"## 🏆 {champion['Name']}"
                )

                st.write(champion["Team"])

                st.metric(
                    "Championship Points",
                    f"{champion['Points']:,.0f}",
                )

                st.metric(
                    "Race Wins",
                    champion["Wins"],
                )

                st.metric(
                    "Podiums",
                    champion["Podiums"],
                )

    st.divider()

    # --------------------------------------------------------
    # Full championship standings
    # --------------------------------------------------------

    st.subheader(f"{category} Standings")

    season_tabs = st.tabs([
        f"{season_year} Season"
        for season_year in season_years
    ])

    for tab, season_year in zip(
        season_tabs,
        season_years,
    ):

        with tab:

            st.dataframe(
                pd.DataFrame(
                    rows_by_year[season_year]
                ),
                hide_index=True,
                width="stretch",
            )

    st.divider()

    # --------------------------------------------------------
    # Three-season points comparison
    # --------------------------------------------------------

    st.subheader("📊 Four-Season Points Comparison")

    points_by_year = {}

    for season_year in season_years:

        points_by_year[season_year] = {
            item["Name"]: item["Points"]
            for item in rows_by_year[season_year]
        }

    all_names = set()

    for points in points_by_year.values():
        all_names.update(points.keys())

    sorted_names = sorted(
        all_names,
        key=lambda name: sum(
            points_by_year[season_year].get(name, 0)
            for season_year in season_years
        ),
        reverse=True,
    )

    comparison_rows = []

    for name in sorted_names:

        row = {"Name": name}

        for season_year in season_years:

            row[f"{season_year} Points"] = (
                points_by_year[season_year].get(name, 0)
            )

        comparison_rows.append(row)

    comparison_df = pd.DataFrame(comparison_rows)

    st.bar_chart(
        comparison_df.set_index("Name"),
        height=600,
    )

    st.divider()

    # --------------------------------------------------------
    # Four-season podium comparison
    # --------------------------------------------------------

    st.subheader("🥉 Four-Season Podium Comparison")

    podiums_by_year = {}

    for season_year in season_years:

        podiums_by_year[season_year] = {
            item["Name"]: item["Podiums"]
            for item in rows_by_year[season_year]
        }

    all_participants = set()

    for podiums in podiums_by_year.values():
        all_participants.update(podiums.keys())

    sorted_participants = sorted(
        all_participants,
        key=lambda name: sum(
            podiums_by_year[season_year].get(name, 0)
            for season_year in season_years
        ),
        reverse=True,
    )

    podium_comparison_rows = []

    for name in sorted_participants:

        row = {"Name": name}

        for season_year in season_years:

            row[f"{season_year} Podiums"] = (
                podiums_by_year[season_year].get(name, 0)
            )

        podium_comparison_rows.append(row)

    podium_comparison_df = pd.DataFrame(
        podium_comparison_rows
    )

    st.bar_chart(
        podium_comparison_df.set_index("Name"),
        height=600,
    )

    st.caption(
        "Podium counts are calculated from official race "
        "finishing positions 1–3 across all completed "
        "race weekends in each season."
    )

    st.caption(
        "Points and wins use final championship standings. "
        "A zero means the participant did not score in that season."
    )

    st.success(
        "Three-season championship comparison loaded successfully."
    )

    st.stop()



elif data_mode == "Driver Profiles":

    st.title("🏎️ F1 Driver Profiles")

    st.caption(
        "Explore driver identities, team history and performance "
        "across the 2022–2025 Formula 1 seasons."
    )

    profile_years = [2022, 2023, 2024, 2025]

    # --------------------------------------------------------
    # Load historical driver database
    # --------------------------------------------------------

    try:
        with st.spinner(
            "Building the historical F1 driver database..."
        ):
            profile_data = fetch_driver_profile_database(
                profile_years
            )

    except Exception as error:
        st.error(
            f"Could not load driver profiles: "
            f"{type(error).__name__}: {error}"
        )
        st.stop()

    driver_records = profile_data["drivers"]

    unavailable_seasons = profile_data.get(
        "unavailable_seasons", {}
    )

    if unavailable_seasons:
        st.warning(
    "Some seasons could not be loaded. "
    "Showing data from the seasons currently available."
)
        for unavailable_year, reason in unavailable_seasons.items():
            st.caption(f"{unavailable_year}: {reason}")

    if not driver_records:
        st.warning("No driver profiles were found.")
        st.stop()

    # --------------------------------------------------------
    # Driver selector
    # --------------------------------------------------------

    driver_ids = sorted(
        driver_records.keys(),
        key=lambda driver_id: (
            driver_records[driver_id]["full_name"].casefold()
        ),
    )

    selected_driver_id = st.selectbox(
        "Select an F1 driver",
        driver_ids,
        format_func=lambda driver_id: (
            driver_records[driver_id]["full_name"]
        ),
        key="profile_driver_selector",
    )

    profile = driver_records[selected_driver_id]

    st.divider()

    # --------------------------------------------------------
    # Driver identity and portrait
    # --------------------------------------------------------

    photo_col, identity_col = st.columns([1, 2])

    with photo_col:

        photo_url = fetch_driver_photo_url(
            profile.get("wikipedia_url")
        )

        if photo_url:
            st.image(
                photo_url,
                caption=profile["full_name"],
                width=320,
            )
        else:
            st.info("Driver portrait is currently unavailable.")

    with identity_col:

        st.subheader(profile["full_name"])

        st.write(
            f"**Nationality:** "
            f"{profile.get('nationality') or 'Not available'}"
        )

        st.write(
            f"**Permanent racing number:** "
            f"{profile.get('permanent_number') or 'Not listed'}"
        )

        st.write(
            f"**Driver abbreviation:** "
            f"{profile.get('code') or 'Not available'}"
        )

        st.write(
            f"**Date of birth:** "
            f"{profile.get('date_of_birth') or 'Not available'}"
        )

        teams = profile.get("teams", [])

        st.write(
            f"**Teams during 2022–2025:** "
            f"{', '.join(teams) if teams else 'Not available'}"
        )

        if profile.get("wikipedia_url"):
            st.markdown(
                f"[View driver profile and source]({profile['wikipedia_url']})"
            )

    st.divider()

    # --------------------------------------------------------
    # Four-season performance statistics
    # --------------------------------------------------------

    st.subheader("📊 Performance Overview")



    available_years = ", ".join(
        str(year) for year in profile_data["years"]
    )

    st.caption(
        f"Statistics cover the available seasons: {available_years}. "
        "They are not lifetime career totals."
    )

    metric_columns = st.columns(4)

    metric_values = [
            (
                "Grand Prix entries",
                profile["total_starts"],
            ),
            (
                "Race wins",
                profile["total_wins"],
            ),
            (
                "Race podiums",
                profile["total_podiums"],
            ),
            (
                "Championship points",
                f"{profile['total_points']:,.0f}",
            ),
        ]

    for column, (label, value) in zip(
            metric_columns,
            metric_values,
        ):
            column.metric(label, value)

    st.metric(
            "Championship titles during 2022–2025",
            profile["championship_titles"],
        )

    st.divider()

        # --------------------------------------------------------
        # Season-by-season history
        # --------------------------------------------------------

    st.subheader("🏆 Season-by-Season Performance")

    season_rows = []

    for season_year in profile_data["years"]:

            season_stats = profile["seasons"].get(season_year)

            if season_stats is None:
                continue

            position = season_stats["championship_position"]

            season_rows.append({
                "Season": season_year,
                "Team": ", ".join(season_stats["team"]) or "Unknown",
                "Grand Prix Entries": season_stats["starts"],
                "Wins": season_stats["wins"],
                "Podiums": season_stats["podiums"],
                "Points": season_stats["points"],
                "Championship Position": (
                    f"P{position}" if position is not None else "N/A"
                ),
                "Best Race Finish": (
                    season_stats["best_finish"]
                    if season_stats["best_finish"] is not None
                    else "N/A"
                ),
            })


    season_df = pd.DataFrame(season_rows)

    if season_df.empty:
            st.info("No season statistics are available for this driver.")

    else:
            st.dataframe(
                season_df,
                hide_index=True,
                width="stretch",
            )

            # ----------------------------------------------------
            # Points progression
            # ----------------------------------------------------

            st.subheader("📈 Championship Points Progression")

            points_chart = season_df.set_index("Season")[["Points"]]

            st.bar_chart(
                points_chart,
                height=300,
            )

            # ----------------------------------------------------
            # Wins and podium progression
            # ----------------------------------------------------

            st.subheader("🏁 Race Wins and Podiums")

            performance_chart = season_df.set_index("Season")[
                ["Wins", "Podiums"]
            ]

            st.bar_chart(
                performance_chart,
                height=350,
            )

    st.divider()

    st.caption(
            "Sources: Jolpica-F1 historical championship standings "
            "and Grand Prix race classifications. "
            "Sprint results are not included in these statistics."
        )

    st.success(
            f"Driver profile loaded: {profile['full_name']}"
        )

    st.stop()



st.warning(
    "Loading a new F1 session may require eligible F1 TV access. "
    "If you do not have access, choose Browse saved analyses."
)


# ------------------------------------------------------------
# 6. Sidebar: season, Grand Prix and session
# ------------------------------------------------------------

st.sidebar.title("Session Settings")

current_year = datetime.now().year
years = list(range(2018, current_year + 1))

default_year = 2022
year = st.sidebar.selectbox(
    "Season",
    years,
    index=years.index(default_year) if default_year in years else len(years) - 1
)

try:
    with st.spinner(f"Loading the {year} event schedule..."):
        schedule = get_schedule(year)

except Exception as error:
    st.error(
        f"Could not load the {year} event schedule: "
        f"{type(error).__name__}: {error}"
    )
    show_saved_gallery()
    st.stop()

if schedule is None or schedule.empty or "EventName" not in schedule.columns:
    st.error("No events were found for the selected season.")
    show_saved_gallery()
    st.stop()

event_names = schedule["EventName"].dropna().astype(str).tolist()

if not event_names:
    st.error("The event schedule contains no event names.")
    show_saved_gallery()
    st.stop()

default_event = (
    "Saudi Arabian Grand Prix"
    if year == 2022 and "Saudi Arabian Grand Prix" in event_names
    else event_names[0]
)

event_index = event_names.index(default_event)

event_name = st.sidebar.selectbox(
    "Grand Prix",
    event_names,
    index=event_index
)

event_rows = schedule[
    schedule["EventName"].astype(str) == event_name
]

if event_rows.empty:
    st.error("Could not find the selected event in the schedule.")
    st.stop()

event_row = event_rows.iloc[0]

# Read the actual session names from this event's schedule.
session_columns = [
    f"Session{i}" for i in range(1, 6)
    if f"Session{i}" in schedule.columns
]

session_names = []

for column in session_columns:
    value = event_row[column]

    if pd.notna(value) and str(value).strip():
        session_label = str(value).strip()

        if session_label.lower() not in ("nan", "none"):
            session_names.append(session_label)

if not session_names:
    st.error("No sessions were listed for this Grand Prix.")
    st.stop()

default_session = (
    "Qualifying"
    if "Qualifying" in session_names
    else session_names[-1]
)

session_index = session_names.index(default_session)

session_name = st.sidebar.selectbox(
    "Session",
    session_names,
    index=session_index
)

selected_key = (year, event_name, session_name)

load_clicked = st.sidebar.button(
    "Load / analyze session",
    type="primary",
    use_container_width=True
)

if load_clicked:
    st.session_state["loaded_session_key"] = selected_key

if st.session_state.get("loaded_session_key") != selected_key:
    st.info(
        "Choose a season, Grand Prix and session, "
        "then click **Load / analyze session**."
    )

    show_saved_gallery()
    st.stop()


# ------------------------------------------------------------
# 7. Load session data
# ------------------------------------------------------------

try:
    with st.spinner(
        f"Loading {year} {event_name} — {session_name}. "
        "The first load may take some time..."
    ):
        session = load_session(year, event_name, session_name)

except Exception as error:
    st.error(
        f"Could not load this session: "
        f"{type(error).__name__}: {error}"
    )

    st.warning(
        "F1's live-timing archive now requires authentication for "
        "some data downloads. If the error mentions authentication, "
        "401, 403 or unavailable timing data, the selected session "
        "may not be accessible from this runtime. Your saved example "
        "images are still available below."
    )

    show_saved_gallery()
    st.stop()


# ------------------------------------------------------------
# 8. Choose the drivers
# ------------------------------------------------------------

laps = session.laps

available_drivers = sorted(
    laps["Driver"].dropna().astype(str).unique()
)

if len(available_drivers) < 1:
    st.error("No drivers with lap data were found.")
    st.stop()

ranked_drivers = get_ranked_drivers(session)

# Use the classification leaders as defaults when possible.
ranked_available = [
    code for code in ranked_drivers
    if code in available_drivers
]

default_driver_1 = (
    ranked_available[0]
    if ranked_available
    else available_drivers[0]
)

other_drivers = [
    code for code in available_drivers
    if code != default_driver_1
]

if not other_drivers:
    st.error("At least two drivers are needed for comparison.")
    st.stop()

default_driver_2 = next(
    (
        code for code in ranked_available
        if code != default_driver_1
    ),
    other_drivers[0]
)

widget_key = f"{year}_{slugify(event_name)}_{slugify(session_name)}"

driver_1 = st.sidebar.selectbox(
    "Main driver",
    available_drivers,
    index=available_drivers.index(default_driver_1),
    key=f"main_driver_{widget_key}"
)

comparison_options = [
    code for code in available_drivers
    if code != driver_1
]

comparison_default = (
    default_driver_2
    if default_driver_2 in comparison_options
    else comparison_options[0]
)

driver_2 = st.sidebar.selectbox(
    "Compare against",
    comparison_options,
    index=comparison_options.index(comparison_default),
    key=f"comparison_driver_{widget_key}"
)


# ------------------------------------------------------------
# 9. Select laps and create the analyses
# ------------------------------------------------------------

try:
    lap_1 = get_fastest_valid_lap(session, driver_1)
    lap_2 = get_fastest_valid_lap(session, driver_2)

    name_1 = get_driver_name(session, driver_1)
    name_2 = get_driver_name(session, driver_2)

    lap_time_1 = lap_1["LapTime"]
    lap_time_2 = lap_2["LapTime"]

    time_1_text = format_lap_time(lap_time_1)
    time_2_text = format_lap_time(lap_time_2)

    data_1 = prepare_telemetry(lap_1)
    data_2 = prepare_telemetry(lap_2)

    # Circuit map for the main driver.
    track_telemetry = lap_1.get_telemetry()

    required_track_columns = ["X", "Y", "Speed"]

    missing_track_columns = [
        column for column in required_track_columns
        if column not in track_telemetry.columns
    ]

    if missing_track_columns:
        raise DataProblem(
            f"Circuit position data is missing: {missing_track_columns}"
        )

    track_data = pd.DataFrame({
        column: pd.to_numeric(
            track_telemetry[column], errors="coerce"
        )
        for column in required_track_columns
    })

    track_data = track_data.replace(
        [np.inf, -np.inf], np.nan
    ).dropna()

    if len(track_data) < 10:
        raise DataProblem(
            "Too few usable circuit-position telemetry points."
        )

    # Compare the two drivers' telemetry.
    compare_1 = prepare_comparison_telemetry(lap_1, driver_1)
    compare_2 = prepare_comparison_telemetry(lap_2, driver_2)

    grid_start = max(
        compare_1["Distance"].min(),
        compare_2["Distance"].min()
    )

    grid_end = min(
        compare_1["Distance"].max(),
        compare_2["Distance"].max()
    )

    if grid_end - grid_start < 100:
        raise DataProblem(
            "The drivers' telemetry traces share too little distance."
        )

    distance_grid = np.linspace(grid_start, grid_end, 1000)

    elapsed_1 = np.interp(
        distance_grid,
        compare_1["Distance"],
        compare_1["Elapsed"]
    )

    elapsed_2 = np.interp(
        distance_grid,
        compare_2["Distance"],
        compare_2["Elapsed"]
    )

    # Positive means driver 1 reached that distance earlier.
    time_gap = elapsed_2 - elapsed_1

    lap_difference = (
        lap_time_2.total_seconds()
        - lap_time_1.total_seconds()
    )

except Exception as error:
    st.error(
        f"Could not complete the analysis: "
        f"{type(error).__name__}: {error}"
    )
    st.stop()


# ------------------------------------------------------------
# 10. Display session and lap summaries
# ------------------------------------------------------------

st.markdown(
    f"## {year} {session.event['EventName']} — {session.name}"
)

metric_1, metric_2, metric_3 = st.columns(3)

metric_1.metric(
    f"{name_1} ({driver_1})",
    time_1_text
)

metric_2.metric(
    f"{name_2} ({driver_2})",
    time_2_text
)

if lap_difference > 0:
    faster_text = f"{name_1} faster"
elif lap_difference < 0:
    faster_text = f"{name_2} faster"
else:
    faster_text = "Equal lap times"

metric_3.metric(
    "Lap-time difference",
    f"{lap_difference:+.3f} s",
    faster_text
)

st.caption(
    "Each driver's fastest selected timed lap is shown. "
    "The laps may have been set at different times or under "
    "different track conditions."
)


# ------------------------------------------------------------
# 11. Build the circuit speed map
# ------------------------------------------------------------

x = track_data["X"].to_numpy()
y = track_data["Y"].to_numpy()
speed = track_data["Speed"].to_numpy()

points = np.column_stack((x, y)).reshape(-1, 1, 2)
segments = np.concatenate(
    [points[:-1], points[1:]],
    axis=1
)

circuit_fig, circuit_ax = plt.subplots(figsize=(10, 8))

circuit_fig.patch.set_facecolor(BACKGROUND)
circuit_ax.set_facecolor(BACKGROUND)

circuit_ax.plot(
    x, y,
    color="#555565",
    linewidth=8,
    solid_capstyle="round",
    zorder=1
)

speed_line = LineCollection(
    segments,
    cmap="plasma",
    norm=plt.Normalize(speed.min(), speed.max()),
    linewidth=4,
    zorder=2
)

speed_line.set_array(speed[:-1])
circuit_ax.add_collection(speed_line)

padding = 0.05 * max(
    x.max() - x.min(),
    y.max() - y.min()
)

circuit_ax.set_xlim(x.min() - padding, x.max() + padding)
circuit_ax.set_ylim(y.min() - padding, y.max() + padding)
circuit_ax.set_aspect("equal")
circuit_ax.axis("off")

bar = circuit_fig.colorbar(
    speed_line,
    ax=circuit_ax,
    shrink=0.8,
    pad=0.025
)

bar.set_label("Speed (km/h)", color=TEXT)
bar.ax.tick_params(colors=TEXT)

circuit_ax.set_title(
    f"{name_1} ({driver_1}) — "
    f"Fastest selected lap: {time_1_text}",
    color=TEXT,
    fontsize=13,
    fontweight="bold"
)

circuit_fig.tight_layout()


# ------------------------------------------------------------
# 12. Build the main driver's telemetry graphs
# ------------------------------------------------------------

distance = data_1["Distance"].to_numpy()
main_speed = data_1["Speed"].to_numpy()
throttle = data_1["Throttle"].to_numpy()
brake = data_1["Brake"].to_numpy()
gear = data_1["nGear"].to_numpy()

telemetry_fig, axes = plt.subplots(
    4, 1,
    figsize=(13, 10),
    sharex=True,
    gridspec_kw={"height_ratios": [3, 2, 1.2, 1.7]},
    constrained_layout=True
)

telemetry_fig.patch.set_facecolor(BACKGROUND)

speed_ax, throttle_ax, brake_ax, gear_ax = axes

speed_ax.plot(distance, main_speed, color=CYAN, linewidth=1.8)
style_axis(speed_ax, "Speed (km/h)")

throttle_ax.plot(distance, throttle, color=GREEN, linewidth=1.7)
throttle_ax.fill_between(
    distance, throttle, color=GREEN, alpha=0.18
)
style_axis(throttle_ax, "Throttle (%)")
throttle_ax.set_ylim(-5, 105)

if np.isin(brake, [0, 1]).all():
    brake_ax.step(
        distance, brake, where="post",
        color=RED, linewidth=1.5
    )
    brake_ax.fill_between(
        distance, brake, step="post",
        color=RED, alpha=0.3
    )
    brake_ax.set_ylim(-0.15, 1.15)
    brake_ax.set_yticks([0, 1])
    brake_ax.set_yticklabels(["Off", "On"])
    style_axis(brake_ax, "Brake")
    brake_ax.set_title(
        "Brake signal (on/off), not brake pressure",
        loc="left", color=MUTED, fontsize=9
    )
else:
    brake_ax.plot(distance, brake, color=RED, linewidth=1.5)
    style_axis(brake_ax, "Brake (raw values)")

gear_ax.step(distance, gear, where="post", color=ORANGE, linewidth=1.7)
style_axis(gear_ax, "Gear")

gear_low = int(gear.min())
gear_high = int(gear.max())

gear_ax.set_yticks(np.arange(gear_low, gear_high + 1))
gear_ax.set_ylim(gear_low - 0.5, gear_high + 0.5)
gear_ax.set_xlim(distance.min(), distance.max())
gear_ax.set_xlabel("Distance along lap (m)", color=TEXT)

telemetry_fig.suptitle(
    f"{name_1} ({driver_1}) — Telemetry",
    color=TEXT,
    fontsize=14,
    fontweight="bold"
)


# ------------------------------------------------------------
# 13. Build the driver comparison graphs
# ------------------------------------------------------------

compare_fig, axes = plt.subplots(
    4, 1,
    figsize=(13, 12),
    sharex=True,
    gridspec_kw={"height_ratios": [3, 2, 1.5, 2.2]},
    constrained_layout=True
)

compare_fig.patch.set_facecolor(BACKGROUND)

speed_ax, throttle_ax, brake_ax, gap_ax = axes

speed_ax.plot(
    compare_1["Distance"], compare_1["Speed"],
    color=RED, linewidth=1.6,
    label=f"{name_1} ({driver_1})"
)

speed_ax.plot(
    compare_2["Distance"], compare_2["Speed"],
    color=BLUE, linewidth=1.6,
    label=f"{name_2} ({driver_2})"
)

style_axis(speed_ax, "Speed (km/h)")

speed_ax.legend(
    facecolor=PANEL,
    edgecolor=GRID,
    labelcolor=TEXT,
    ncol=2
)

throttle_ax.plot(
    compare_1["Distance"], compare_1["Throttle"],
    color=RED, linewidth=1.6
)

throttle_ax.plot(
    compare_2["Distance"], compare_2["Throttle"],
    color=BLUE, linewidth=1.6
)

style_axis(throttle_ax, "Throttle (%)")
throttle_ax.set_ylim(-5, 105)

if (
    np.isin(compare_1["Brake"], [0, 1]).all()
    and np.isin(compare_2["Brake"], [0, 1]).all()
):
    brake_ax.step(
        compare_1["Distance"],
        compare_1["Brake"],
        where="post", color=RED, linewidth=1.4
    )

    brake_ax.step(
        compare_2["Distance"],
        compare_2["Brake"] + 1.5,
        where="post", color=BLUE, linewidth=1.4
    )

    style_axis(brake_ax, "Brake (on/off)")
    brake_ax.set_yticks([0.5, 2.0])
    brake_ax.set_yticklabels([driver_1, driver_2])
    brake_ax.set_ylim(-0.2, 2.7)
    brake_ax.set_title(
        "On/off brake signal — not brake pressure",
        loc="left", color=MUTED, fontsize=9
    )
else:
    brake_ax.plot(
        compare_1["Distance"], compare_1["Brake"],
        color=RED, label=driver_1
    )

    brake_ax.plot(
        compare_2["Distance"], compare_2["Brake"],
        color=BLUE, label=driver_2
    )

    style_axis(brake_ax, "Brake (raw values)")
    brake_ax.legend(facecolor=PANEL, labelcolor=TEXT)

gap_ax.plot(
    distance_grid, time_gap,
    color=TEXT, linewidth=1.8
)

gap_ax.fill_between(
    distance_grid, time_gap, 0,
    where=time_gap >= 0,
    interpolate=True, color=RED, alpha=0.3
)

gap_ax.fill_between(
    distance_grid, time_gap, 0,
    where=time_gap < 0,
    interpolate=True, color=BLUE, alpha=0.3
)

gap_ax.axhline(0, color=MUTED, linestyle="--", linewidth=1)

style_axis(
    gap_ax,
    f"Estimated gap (s)\n{driver_2} - {driver_1}"
)

gap_limit = max(float(np.max(np.abs(time_gap))) * 1.3, 0.05)
gap_ax.set_ylim(-gap_limit, gap_limit)
gap_ax.set_xlim(grid_start, grid_end)
gap_ax.set_xlabel("Distance along lap (m)", color=TEXT)

gap_ax.set_title(
    f"Above zero: {driver_1} reached that distance earlier; "
    f"below zero: {driver_2} reached it earlier",
    loc="left", color=MUTED, fontsize=9
)

compare_fig.suptitle(
    f"{name_1} vs {name_2} — Driver Comparison",
    color=TEXT,
    fontsize=14,
    fontweight="bold"
)


# ------------------------------------------------------------
# 14. Save race-specific chart files and display the dashboard
# ------------------------------------------------------------

output_folder = OUTPUT_ROOT / (
    f"{year}-{slugify(event_name)}-{slugify(session_name)}"
)

output_folder.mkdir(parents=True, exist_ok=True)

circuit_path = output_folder / "f1_circuit_speed_map.png"
telemetry_path = output_folder / "f1_telemetry_analysis.png"
comparison_path = output_folder / "f1_driver_comparison.png"

# Save the generated charts so they can also be used outside the app.
circuit_fig.savefig(circuit_path, dpi=180, bbox_inches="tight",
                    facecolor=circuit_fig.get_facecolor())

telemetry_fig.savefig(telemetry_path, dpi=180, bbox_inches="tight",
                      facecolor=telemetry_fig.get_facecolor())

compare_fig.savefig(comparison_path, dpi=180, bbox_inches="tight",
                    facecolor=compare_fig.get_facecolor())

circuit_png = figure_to_png(circuit_fig)
telemetry_png = figure_to_png(telemetry_fig)
comparison_png = figure_to_png(compare_fig)

# Display all three visualizations directly on the page.
# Downloads are optional; users do not need to download an image to view it.

st.markdown("## 🗺️ Circuit speed map")
st.pyplot(circuit_fig, use_container_width=True)
st.download_button(
    "Download circuit map",
    data=circuit_png,
    file_name="f1_circuit_speed_map.png",
    mime="image/png",
    key="download_circuit"
)

st.divider()
st.markdown("## 📈 Telemetry analysis")
st.pyplot(telemetry_fig, use_container_width=True)
st.download_button(
    "Download telemetry graphs",
    data=telemetry_png,
    file_name="f1_telemetry_analysis.png",
    mime="image/png",
    key="download_telemetry"
)

st.divider()
st.markdown("## ⚔️ Driver comparison")
st.pyplot(compare_fig, use_container_width=True)
st.caption(
    "The distance-aligned time-gap curve is an estimate from "
    "sampled telemetry, not an official FIA timing calculation."
)
st.download_button(
    "Download driver comparison",
    data=comparison_png,
    file_name="f1_driver_comparison.png",
    mime="image/png",
    key="download_comparison"
)

with st.container():
    timed_laps = session.laps.dropna(
        subset=["Driver", "LapTime"]
    ).copy()

    # Prefer accurate laps for this summary if available.
    if "IsAccurate" in timed_laps.columns:
        accurate = timed_laps["IsAccurate"].eq(True)

        if accurate.any():
            timed_laps = timed_laps.loc[accurate].copy()

    fastest_ten = timed_laps.sort_values("LapTime").head(10).copy()

    fastest_ten["Lap Time"] = fastest_ten["LapTime"].map(
        format_lap_time
    )

    fastest_ten = fastest_ten.reset_index(drop=True)
    fastest_ten.index = fastest_ten.index + 1
    fastest_ten.index.name = "Rank"

    display_columns = [
        column for column in ["Driver", "LapNumber", "Lap Time"]
        if column in fastest_ten.columns
    ]

    st.dataframe(
        fastest_ten[display_columns],
        use_container_width=True
    )

st.success(
    f"Analysis complete. Charts saved in: {output_folder}"
)

st.caption(
    "Independent educational project. Not affiliated with Formula 1, "
    "the FIA, or any racing team."
)

with st.expander("Browse saved example analyses"):
    show_saved_gallery()

plt.close(circuit_fig)
plt.close(telemetry_fig)
plt.close(compare_fig)

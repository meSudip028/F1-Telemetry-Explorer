#!/usr/bin/env python3
"""Generate session-specific public charts from the Jolpica-F1 API.

Supported sessions:
- Race: position progression, lap-time progression, fastest recorded lap comparison.
- Qualifying: Q1, Q2, and Q3 lap-time comparisons, each using only that segment's times.

These charts use public classifications/lap timing, not high-frequency car telemetry.

Examples:
    python generate_public_session_charts.py --year 2023 --round 1 --session both
    python generate_public_session_charts.py --year 2023 --all --session both
    python generate_public_session_charts.py --year 2023 --all --session race
"""
from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE_DIR = Path(__file__).resolve().parent
IMAGE_DIR = BASE_DIR / "images"
API_ROOT = "https://api.jolpi.ca/ergast/f1"
USER_AGENT = "F1-Telemetry-Explorer/1.0 (educational project)"
REQUESTED_LIMIT = 1000
BG = "#15151e"
PANEL = "#1e1e2b"
GRID = "#3a3a4d"
TEXT = "#f0f0f5"
MUTED = "#a0a0b5"
COLORS = ["#00d2ff", "#ffb020", "#2ee66b", "#ff4d4d", "#b58cff",
          "#4d9bff", "#ff78b4", "#e5e7eb", "#f97316", "#a3e635"]
RACE_CHARTS = [
    "race_position_progression.png",
    "race_lap_time_progression.png",
    "race_fastest_lap_comparison.png",
]
QUALIFYING_CHARTS = [
    "qualifying_q1_times.png",
    "qualifying_q2_times.png",
    "qualifying_q3_times.png",
]


def slugify(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def api_get(url: str, retries: int = 3) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Could not fetch API response: {url}\n{last_error}")


def parse_time(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"\\N", "N/A", "-"}:
        return None
    try:
        parts = text.split(":")
        if len(parts) == 2:
            result = int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 1:
            result = float(parts[0])
        else:
            return None
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError):
        return None


def format_time(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds):
        return "N/A"
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:06.3f}"


def fetch_schedule(year: int) -> list[dict[str, Any]]:
    url = f"{API_ROOT}/{year}/races/?limit=100"
    payload = api_get(url)
    races = payload.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if not races:
        raise RuntimeError(f"No race schedule returned for {year}.")
    return races


def fetch_session_results(year: int, round_number: int, session: str) -> dict[str, Any]:
    endpoint = "qualifying" if session == "qualifying" else "results"
    url = f"{API_ROOT}/{year}/{round_number}/{endpoint}/?limit=100"
    payload = api_get(url)
    races = payload.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if not races:
        raise RuntimeError(f"No {session} results for {year} round {round_number}.")
    return races[0]


def fetch_all_lap_timings(year: int, round_number: int) -> list[dict[str, Any]]:
    base_url = f"{API_ROOT}/{year}/{round_number}/laps/"
    offset = 0
    total: int | None = None
    rows: dict[tuple[int, str], dict[str, Any]] = {}

    while True:
        query = urllib.parse.urlencode({"limit": REQUESTED_LIMIT, "offset": offset})
        payload = api_get(f"{base_url}?{query}")
        metadata = payload.get("MRData", {})
        if total is None:
            try:
                total = int(metadata.get("total", 0))
            except (TypeError, ValueError):
                total = 0
            print(f"  API reports {total} lap-timing records.")

        try:
            actual_limit = int(metadata.get("limit") or REQUESTED_LIMIT)
        except (TypeError, ValueError):
            actual_limit = REQUESTED_LIMIT

        races = metadata.get("RaceTable", {}).get("Races", [])
        page_count = 0
        for race in races:
            for lap in race.get("Laps", []):
                try:
                    lap_number = int(lap.get("number"))
                except (TypeError, ValueError):
                    continue
                for timing in lap.get("Timings", []):
                    driver_id = str(timing.get("driverId", "")).strip()
                    if not driver_id:
                        continue
                    seconds = parse_time(timing.get("time"))
                    try:
                        position = int(timing.get("position"))
                    except (TypeError, ValueError):
                        position = None
                    rows[(lap_number, driver_id)] = {
                        "lap": lap_number,
                        "driver_id": driver_id,
                        "position": position,
                        "seconds": seconds,
                    }
                    page_count += 1

        print(f"  Downloaded {page_count} timing rows at offset {offset}.")
        if page_count == 0 or total is None or offset + actual_limit >= total:
            break
        offset += actual_limit
        time.sleep(0.25)

    if not rows:
        raise RuntimeError(f"No lap-timing records returned for {year} round {round_number}.")
    if total and len(rows) < total:
        raise RuntimeError(f"Incomplete lap-timing download: retrieved {len(rows)} unique rows; API reports {total}.")
    return list(rows.values())


def classification_metadata(classification: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    names: dict[str, str] = {}
    classified: list[dict[str, Any]] = []
    for result in classification.get("Results", []):
        driver = result.get("Driver", {})
        driver_id = str(driver.get("driverId", ""))
        name = f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip() or driver_id
        names[driver_id] = name
        try:
            position = int(result.get("position"))
        except (TypeError, ValueError):
            position = None
        classified.append({"driver_id": driver_id, "name": name, "position": position})
    classified.sort(key=lambda item: (item["position"] is None, item["position"] or 999))
    return names, classified


def finish_chart(fig: Any, path: Path) -> None:
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    fig.savefig(path, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


def save_race_charts(race_name: str, rows: list[dict[str, Any]], names: dict[str, str], classified: list[dict[str, Any]], outdir: Path) -> None:
    top10 = [item["driver_id"] for item in classified if item["position"] is not None][:10]
    position_rows = [row for row in rows if row["driver_id"] in top10 and row["position"] is not None]
    if not position_rows:
        raise RuntimeError("No valid recorded positions for race position chart.")

    fig, ax = plt.subplots(figsize=(13, 7), facecolor=BG)
    ax.set_facecolor(PANEL)
    for index, driver_id in enumerate(top10):
        driver_rows = sorted((row for row in position_rows if row["driver_id"] == driver_id), key=lambda row: row["lap"])
        if driver_rows:
            ax.step([r["lap"] for r in driver_rows], [r["position"] for r in driver_rows],
                    where="post", linewidth=1.8, color=COLORS[index % len(COLORS)],
                    label=names.get(driver_id, driver_id))
    max_lap = max(row["lap"] for row in position_rows)
    ax.set_xlim(1, max_lap)
    ax.set_ylim(10.5, 0.5)
    ax.set_yticks(range(1, 11))
    ax.set_xlabel("Lap", color=TEXT)
    ax.set_ylabel("Recorded position (lower is better)", color=TEXT)
    ax.set_title(f"{race_name} — Race Position Progression (Top 10)", color=TEXT, fontsize=15)
    ax.grid(True, color=GRID, linewidth=0.7, alpha=0.8)
    ax.tick_params(colors=TEXT)
    for spine in ax.spines.values(): spine.set_color(GRID)
    ax.legend(ncol=2, fontsize=8, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT,
              loc="upper left", bbox_to_anchor=(1.01, 1))
    fig.text(0.01, 0.015, "Source: Jolpica-F1 public lap timing. Gaps may exist for retired drivers.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.05, 0.82, 1))
    fig.savefig(outdir / RACE_CHARTS[0], dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)

    top5 = [item["driver_id"] for item in classified if item["position"] is not None][:5]
    timed_rows = [row for row in rows if row["driver_id"] in top5 and row["seconds"] is not None]
    if not timed_rows:
        raise RuntimeError("No valid recorded lap times for lap-time chart.")
    fig, ax = plt.subplots(figsize=(13, 7), facecolor=BG)
    ax.set_facecolor(PANEL)
    for index, driver_id in enumerate(top5):
        driver_rows = sorted((row for row in timed_rows if row["driver_id"] == driver_id), key=lambda row: row["lap"])
        if driver_rows:
            ax.plot([r["lap"] for r in driver_rows], [r["seconds"] for r in driver_rows],
                    linewidth=1.5, marker="o", markersize=2.4,
                    color=COLORS[index % len(COLORS)], label=names.get(driver_id, driver_id))
    ax.set_xlabel("Lap", color=TEXT)
    ax.set_ylabel("Recorded lap time (seconds)", color=TEXT)
    ax.set_title(f"{race_name} — Race Lap-Time Progression (Top 5 Finishers)", color=TEXT, fontsize=15)
    ax.grid(True, color=GRID, linewidth=0.7, alpha=0.8)
    ax.tick_params(colors=TEXT)
    for spine in ax.spines.values(): spine.set_color(GRID)
    ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT)
    fig.text(0.01, 0.015, "Pit stops, traffic and safety-car periods can create large spikes.", color=MUTED, fontsize=8)
    finish_chart(fig, outdir / RACE_CHARTS[1])

    fastest: dict[str, float] = {}
    for row in rows:
        if row["seconds"] is not None:
            did = row["driver_id"]
            fastest[did] = min(fastest.get(did, float("inf")), row["seconds"])
    if not fastest:
        raise RuntimeError("No valid lap times for fastest recorded lap comparison.")
    ordered = sorted(fastest.items(), key=lambda item: item[1])
    labels = [names.get(did, did) for did, _ in ordered]
    values = [seconds for _, seconds in ordered]
    fig, ax = plt.subplots(figsize=(12, max(7, len(ordered) * 0.34)), facecolor=BG)
    ax.set_facecolor(PANEL)
    bars = ax.barh(labels, values, color=[COLORS[i % len(COLORS)] for i in range(len(values))], alpha=0.9)
    ax.invert_yaxis()
    ax.set_xlabel("Fastest recorded lap (seconds)", color=TEXT)
    ax.set_title(f"{race_name} — Fastest Recorded Lap Comparison", color=TEXT, fontsize=15)
    ax.grid(True, axis="x", color=GRID, linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=TEXT, labelsize=8)
    for spine in ax.spines.values(): spine.set_color(GRID)
    for bar, value in zip(bars, values):
        ax.text(value + 0.15, bar.get_y() + bar.get_height()/2, format_time(value),
                va="center", ha="left", color=TEXT, fontsize=7)
    fig.text(0.01, 0.015, "Computed from available public lap timing; may differ from official fastest-lap classification.", color=MUTED, fontsize=8)
    finish_chart(fig, outdir / RACE_CHARTS[2])


def qualifying_results_metadata(result: dict[str, Any]) -> list[dict[str, Any]]:
    drivers = []
    for item in result.get("QualifyingResults", []):
        driver = item.get("Driver", {})
        name = f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip()
        try:
            position = int(item.get("position"))
        except (TypeError, ValueError):
            position = 999
        drivers.append({
            "name": name or driver.get("driverId", "Unknown"),
            "position": position,
            "Q1": parse_time(item.get("Q1")),
            "Q2": parse_time(item.get("Q2")),
            "Q3": parse_time(item.get("Q3")),
        })
    return sorted(drivers, key=lambda item: item["position"])


def save_qualifying_charts(race_name: str, results: list[dict[str, Any]], outdir: Path) -> None:
    drivers = qualifying_results_metadata({"QualifyingResults": results})
    if not drivers:
        raise RuntimeError("No qualifying results returned.")

    # Each chart compares only the lap times from the same qualifying segment.
    for segment in ("Q1", "Q2", "Q3"):
        timed = [driver for driver in drivers if driver[segment] is not None]
        if not timed:
            raise RuntimeError(f"No public {segment} times returned.")
        timed.sort(key=lambda driver: driver[segment])
        labels = [driver["name"] for driver in timed]
        values = [driver[segment] for driver in timed]
        fig, ax = plt.subplots(figsize=(11, max(5, 0.34 * len(timed))), facecolor=BG)
        ax.set_facecolor(PANEL)
        bars = ax.barh(labels, values, color=COLORS[(int(segment[1]) - 1) % len(COLORS)], alpha=0.9)
        ax.invert_yaxis()
        ax.set_xlabel(f"{segment} lap time (seconds)", color=TEXT)
        ax.set_title(f"{race_name} — Qualifying {segment} Times", color=TEXT, fontsize=15)
        ax.grid(True, axis="x", color=GRID, linewidth=0.7, alpha=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=TEXT, labelsize=8)
        for spine in ax.spines.values(): spine.set_color(GRID)
        for bar, value in zip(bars, values):
            ax.text(value + 0.06, bar.get_y() + bar.get_height()/2, format_time(value),
                    va="center", ha="left", color=TEXT, fontsize=7)
        fig.text(0.01, 0.015, f"Source: Jolpica-F1 public qualifying classification. Only drivers with a recorded {segment} time are shown.", color=MUTED, fontsize=8)
        filename = f"qualifying_{segment.lower()}_times.png"
        finish_chart(fig, outdir / filename)


def apply_miami_2025_qualifying_fallback(
    results: list[dict[str, Any]],
) -> bool:
    """Use official FIA qualifying times when Miami's Jolpica fields are blank."""

    official_times = {
        "verstappen": ("1:26.870", "1:26.643", "1:26.204"),
        "norris": ("1:26.955", "1:26.499", "1:26.269"),
        "antonelli": ("1:27.077", "1:26.606", "1:26.271"),
        "piastri": ("1:27.006", "1:26.269", "1:26.375"),
        "russell": ("1:27.014", "1:26.575", "1:26.385"),
        "sainz": ("1:27.098", "1:26.847", "1:26.569"),
        "albon": ("1:27.042", "1:26.855", "1:26.682"),
        "leclerc": ("1:27.417", "1:26.948", "1:26.754"),
        "ocon": ("1:27.450", "1:26.967", "1:26.824"),
        "tsunoda": ("1:27.298", "1:26.959", "1:26.943"),
        "hadjar": ("1:27.301", "1:26.987", None),
        "hamilton": ("1:27.279", "1:27.006", None),
        "bortoleto": ("1:27.343", "1:27.151", None),
        "doohan": ("1:27.422", "1:27.186", None),
        "lawson": ("1:27.444", "1:27.363", None),
        "hulkenberg": ("1:27.473", None, None),
        "alonso": ("1:27.604", None, None),
        "gasly": ("1:27.710", None, None),
        "stroll": ("1:27.830", None, None),
        "bearman": ("1:27.999", None, None),
    }

    matched = set()

    for result in results:
        driver = result.get("Driver", {})
        driver_key = slugify(driver.get("familyName", ""))

        times = official_times.get(driver_key)

        if times is None:
            continue

        result["Q1"], result["Q2"], result["Q3"] = times
        matched.add(driver_key)

    missing = set(official_times) - matched

    if missing:
        raise RuntimeError(
            "Miami fallback could not match these drivers: "
            + ", ".join(sorted(missing))
        )

    print(
        "Applied official FIA qualifying-time fallback "
        f"for all {len(matched)} Miami drivers."
    )

    return True


def process_session(year: int, race_event: dict[str, Any], session: str, force: bool = False) -> str:
    round_number = int(race_event["round"])
    race_name = race_event.get("raceName", f"Round {round_number}")
    slug = slugify(race_name)
    if slug.endswith("-grand-prix"):
        slug = slug[:-len("-grand-prix")]
    folder_name = f"{year}-{slug}-grand-prix-{session}"
    output_folder = IMAGE_DIR / folder_name
    chart_files = QUALIFYING_CHARTS if session == "qualifying" else RACE_CHARTS
    qualifying_fallback_used = False

    if not force and all((output_folder / filename).is_file() for filename in chart_files):
        print(f"SKIP: {year} {race_name} — {session}, charts already exist.")
        return "skipped"

    print("\n" + "=" * 72)
    print(f"START: {year} {race_name} — {session.title()}")

    if session == "race":
        classification = fetch_session_results(year, round_number, "race")
        names, classified = classification_metadata(classification)
        rows = fetch_all_lap_timings(year, round_number)
    else:
            qualifying = fetch_session_results(
                year, round_number, "qualifying"
            )

            results = qualifying.get("QualifyingResults", [])

            if not results:
                raise RuntimeError("No qualifying result rows returned.")

            q1_available = any(
                str(item.get("Q1") or "").strip()
                for item in results
            )

            if year == 2025 and round_number == 6 and not q1_available:
                qualifying_fallback_used = (
                    apply_miami_2025_qualifying_fallback(results)
                )

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".chart-build-", dir=IMAGE_DIR) as temp_dir:
        temp_folder = Path(temp_dir)
        if session == "race":
            save_race_charts(race_name, rows, names, classified, temp_folder)
            (temp_folder / "RACE_DATA_SOURCE.txt").write_text(
                f"{year} race analysis data source\n"
                "Source: Jolpica-F1 public timing/classification API.\n\n"
                "These charts use lap times and recorded race positions. They do not contain high-frequency car telemetry such as speed, throttle, brake, gear, or GPS position.\n"
                "Position progression uses recorded position by lap; lap-time progression may include pit-stop, traffic, and safety-car spikes. Fastest recorded lap is computed from available timing rows and may differ from the official fastest-lap classification.\n",
                encoding="utf-8",
            )

        else:
            save_qualifying_charts(race_name, results, temp_folder)

            qualifying_source_note = (
                f"{year} qualifying analysis data source\n"
                "Source: Jolpica-F1 public qualifying classification API.\n\n"
                "These charts show Q1, Q2, and Q3 lap times separately. "
                "They are public result data, not high-frequency car "
                "telemetry such as speed, throttle, brake, gear, or GPS.\n"
            )

            if qualifying_fallback_used:
                qualifying_source_note += (
                    "\nMiami 2025 fallback:\n"
                    "Qualifying times were taken from the official FIA "
                    "Final Qualifying Classification because Jolpica "
                    "returned blank time fields.\n"
                    "Official source: "
                    "https://www.fia.com/system/files/decision-document/"
                    "2025_miami_grand_prix_-_final_qualifying_classification.pdf\n"
                )

            (temp_folder / "QUALIFYING_DATA_SOURCE.txt").write_text(
                qualifying_source_note,
                encoding="utf-8",
            )


        output_folder.mkdir(parents=True, exist_ok=True)
        for filename in chart_files:
            (temp_folder / filename).replace(output_folder / filename)
        note_name = "RACE_DATA_SOURCE.txt" if session == "race" else "QUALIFYING_DATA_SOURCE.txt"
        (temp_folder / note_name).replace(output_folder / note_name)

    print(f"SUCCESS: Saved {len(chart_files)} public {session} charts to {output_folder}")
    return "generated"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True, help="Season year, e.g. 2023")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--round", type=int, help="Generate a single calendar round")
    selection.add_argument("--all", action="store_true", help="Generate all rounds in the selected season")
    parser.add_argument("--session", choices=("both", "race", "qualifying"), default="both",
                        help="Which session(s) to generate; default: both")
    parser.add_argument("--force", action="store_true", help="Regenerate charts even when they already exist")
    args = parser.parse_args()

    try:
        schedule = fetch_schedule(args.year)
    except Exception as error:
        print(f"Could not load {args.year} schedule: {error}")
        return 1

    if args.round is not None:
        selected = [event for event in schedule if int(event.get("round", -1)) == args.round]
        if not selected:
            available = ", ".join(str(event.get("round")) for event in schedule)
            print(f"Round {args.round} was not found. Available rounds: {available}")
            return 2
    else:
        selected = schedule

    sessions = ["qualifying", "race"] if args.session == "both" else [args.session]
    generated = skipped = failed = 0
    failures: list[str] = []
    for race_event in selected:
        for session in sessions:
            try:
                state = process_session(args.year, race_event, session, force=args.force)
                if state == "generated":
                    generated += 1
                else:
                    skipped += 1
            except KeyboardInterrupt:
                print("\nStopped by user. Completed charts were kept.")
                return 130
            except Exception as error:
                failed += 1
                description = f"Round {race_event.get('round')} {race_event.get('raceName')} ({session}): {type(error).__name__}: {error}"
                failures.append(description)
                print(f"FAILED: {description}")
            time.sleep(0.25)

    report_path = BASE_DIR / f"public_session_charts_{args.year}_report.txt"
    report_lines = [
        f"{args.year} PUBLIC SESSION CHART GENERATION SUMMARY",
        f"Generated: {generated}",
        f"Already complete: {skipped}",
        f"Failed: {failed}",
        "Source: Jolpica-F1 public timing/classification API.",
        "These charts are results/lap timing, not high-frequency car telemetry.",
    ]
    if failures:
        report_lines.extend(["", "Failed sessions:", *[f"- {item}" for item in failures]])
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"{args.year} PUBLIC SESSION CHART GENERATION SUMMARY")
    print(f"Generated: {generated}")
    print(f"Already complete: {skipped}")
    print(f"Failed: {failed}")
    if failures:
        print("\nFailed sessions:")
        for item in failures:
            print(f"- {item}")
    print(f"\nDetailed report: {report_path}")
    print("Qualifying charts use Q1/Q2/Q3 result times; Race charts use public lap timing and classification.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

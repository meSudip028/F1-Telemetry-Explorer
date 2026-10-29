#!/usr/bin/env python3
"""Generate 2022 F1 race charts using public Jolpica-F1 timing/classification data.

This script deliberately does NOT use FastF1 car telemetry. It creates:
  1) Race position progression for the top 10 classified drivers
  2) Lap-time progression for the top 5 classified drivers
  3) Fastest recorded lap comparison for all drivers with available lap times

Usage from the project root:
    python generate_2022_public_race_charts.py --round 1
    python generate_2022_public_race_charts.py --all

Files are saved in images/2022-<race-slug>-grand-prix-race/ using distinct
filenames so the dashboard can label these charts accurately.
"""
from __future__ import annotations

import argparse
import json
import math
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

YEAR = 2022
BASE_DIR = Path(__file__).resolve().parent
IMAGE_DIR = BASE_DIR / "images"
REPORT_PATH = BASE_DIR / "race_lap_analysis_2022_report.txt"
BASE_API = "https://api.jolpi.ca/ergast/f1/2022"
REQUESTED_LIMIT = 1000
USER_AGENT = "F1-Telemetry-Explorer/1.0 (educational project)"

ROUND_SLUGS = {
    1: "bahrain",
    2: "saudi-arabian",
    3: "australian",
    4: "emilia-romagna",
    5: "miami",
    6: "spanish",
    7: "monaco",
    8: "azerbaijan",
    9: "canadian",
    10: "british",
    11: "austrian",
    12: "french",
    13: "hungarian",
    14: "belgian",
    15: "dutch",
    16: "italian",
    17: "singapore",
    18: "japanese",
    19: "united-states",
    20: "mexico-city",
    21: "sao-paulo",
    22: "abu-dhabi",
}

CHART_FILES = [
    "race_position_progression.png",
    "race_lap_time_progression.png",
    "race_fastest_lap_comparison.png",
]

# Readable dark styling consistent with the current app.
BG = "#15151e"
PANEL = "#1e1e2b"
GRID = "#3a3a4d"
TEXT = "#f0f0f5"
MUTED = "#a0a0b5"
COLORS = ["#00d2ff", "#ffb020", "#2ee66b", "#ff4d4d", "#b58cff",
          "#4d9bff", "#ff78b4", "#e5e7eb", "#f97316", "#a3e635"]


def api_get(url: str, retries: int = 3) -> dict[str, Any]:
    """GET JSON from Jolpica-F1 with small retries for transient errors."""
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


def parse_lap_time(value: Any) -> float | None:
    """Convert m:ss.sss or ss.sss to seconds; return None for invalid values."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"\\N", "N/A", "-"}:
        return None
    try:
        parts = text.split(":")
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            result = minutes * 60 + seconds
        elif len(parts) == 1:
            result = float(parts[0])
        else:
            return None
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError):
        return None


def format_lap_time(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds):
        return "N/A"
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes}:{remainder:06.3f}"


def fetch_race_classification(round_number: int) -> dict[str, Any]:
    url = f"{BASE_API}/{round_number}/results/?limit=100"
    payload = api_get(url)
    races = payload.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if not races:
        raise RuntimeError(f"No race classification returned for round {round_number}.")
    return races[0]


def fetch_all_lap_timings(round_number: int) -> list[dict[str, Any]]:
    """Fetch every paginated lap-timing row for one Grand Prix."""
    url_base = f"{BASE_API}/{round_number}/laps/"
    offset = 0
    total: int | None = None
    rows: dict[tuple[int, str], dict[str, Any]] = {}

    while True:
        query = urllib.parse.urlencode({"limit": REQUESTED_LIMIT, "offset": offset})
        payload = api_get(f"{url_base}?{query}")
        metadata = payload.get("MRData", {})
        if total is None:
            try:
                total = int(metadata.get("total", 0))
            except (TypeError, ValueError):
                total = 0
            print(f"  API reports {total} lap timing records.")

        actual_limit = int(metadata.get("limit") or REQUESTED_LIMIT)
        races = metadata.get("RaceTable", {}).get("Races", [])
        page_count = 0
        for race in races:
            for lap in race.get("Laps", []):
                try:
                    lap_no = int(lap.get("number"))
                except (TypeError, ValueError):
                    continue
                for timing in lap.get("Timings", []):
                    driver_id = str(timing.get("driverId", "")).strip()
                    position_raw = timing.get("position")
                    lap_time = timing.get("time")
                    seconds = parse_lap_time(lap_time)
                    try:
                        position = int(position_raw)
                    except (TypeError, ValueError):
                        position = None
                    if not driver_id:
                        continue
                    row = {
                        "lap": lap_no,
                        "driver_id": driver_id,
                        "position": position,
                        "time_text": str(lap_time or ""),
                        "seconds": seconds,
                    }
                    rows[(lap_no, driver_id)] = row
                    page_count += 1

        print(f"  Downloaded {page_count} timing rows at offset {offset}.")
        if page_count == 0 or total is None or offset + actual_limit >= total:
            break
        offset += actual_limit
        time.sleep(0.25)

    if not rows:
        raise RuntimeError(f"No lap-timing rows returned for round {round_number}.")
    if total and len(rows) < total:
        raise RuntimeError(
            f"Incomplete lap-timing download: got {len(rows)} unique rows; API reports {total}."
        )
    return list(rows.values())


def driver_metadata(classification: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    results = classification.get("Results", [])
    names: dict[str, str] = {}
    normalized: list[dict[str, Any]] = []
    for result in results:
        driver = result.get("Driver", {})
        driver_id = str(driver.get("driverId", ""))
        name = f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip()
        if not name:
            name = driver_id or "Unknown driver"
        team = result.get("Constructor", {}).get("name", "Unknown team")
        names[driver_id] = name
        normalized.append({
            "driver_id": driver_id,
            "name": name,
            "team": team,
            "position": safe_int(result.get("position")),
            "status": str(result.get("status", "")),
        })
    return names, sorted(normalized, key=lambda x: (x["position"] is None, x["position"] or 999))


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def style_axis(ax, ylabel: str) -> None:
    ax.set_facecolor(PANEL)
    ax.set_ylabel(ylabel, color=TEXT, fontsize=10)
    ax.grid(True, color=GRID, linewidth=0.7, alpha=0.85)
    ax.set_axisbelow(True)
    ax.tick_params(colors=TEXT, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(GRID)


def save_position_chart(race_name: str, rows: list[dict[str, Any]], classified: list[dict[str, Any]], names: dict[str, str], output: Path) -> None:
    top_drivers = [item["driver_id"] for item in classified if item["position"] is not None][:10]
    position_rows = [row for row in rows if row["driver_id"] in top_drivers and row["position"] is not None]
    if not position_rows:
        raise RuntimeError("No valid position data for the position progression chart.")

    fig, ax = plt.subplots(figsize=(13, 7), facecolor=BG)
    ax.set_facecolor(PANEL)
    for index, driver_id in enumerate(top_drivers):
        driver_rows = sorted((row for row in position_rows if row["driver_id"] == driver_id), key=lambda row: row["lap"])
        if not driver_rows:
            continue
        laps = [row["lap"] for row in driver_rows]
        positions = [row["position"] for row in driver_rows]
        ax.step(laps, positions, where="post", linewidth=2.0, color=COLORS[index % len(COLORS)], label=names.get(driver_id, driver_id), alpha=0.95)
    max_lap = max(row["lap"] for row in position_rows)
    ax.set_xlim(1, max_lap)
    ax.set_ylim(10.5, 0.5)
    ax.set_yticks(range(1, 11))
    ax.set_xlabel("Lap", color=TEXT)
    ax.set_ylabel("Position (lower is better)", color=TEXT)
    ax.set_title(f"{race_name} — Race Position Progression (Top 10)", color=TEXT, fontsize=16, pad=14)
    ax.grid(True, color=GRID, linewidth=0.7, alpha=0.8)
    ax.tick_params(colors=TEXT)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.legend(ncol=2, fontsize=8, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, loc="upper left", bbox_to_anchor=(1.01, 1))
    fig.text(0.01, 0.015, "Source: Jolpica-F1 lap timing API. Position is the recorded position at each lap; gaps may exist for retired drivers.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.05, 0.82, 1))
    fig.savefig(output, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


def save_lap_time_chart(race_name: str, rows: list[dict[str, Any]], classified: list[dict[str, Any]], names: dict[str, str], output: Path) -> None:
    top_drivers = [item["driver_id"] for item in classified if item["position"] is not None][:5]
    timed_rows = [row for row in rows if row["driver_id"] in top_drivers and row["seconds"] is not None]
    if not timed_rows:
        raise RuntimeError("No valid lap times for the lap-time progression chart.")

    fig, ax = plt.subplots(figsize=(13, 7), facecolor=BG)
    ax.set_facecolor(PANEL)
    for index, driver_id in enumerate(top_drivers):
        driver_rows = sorted((row for row in timed_rows if row["driver_id"] == driver_id), key=lambda row: row["lap"])
        if not driver_rows:
            continue
        ax.plot(
            [row["lap"] for row in driver_rows],
            [row["seconds"] for row in driver_rows],
            linewidth=1.6,
            marker="o",
            markersize=2.8,
            alpha=0.9,
            color=COLORS[index % len(COLORS)],
            label=names.get(driver_id, driver_id),
        )
    ax.set_xlabel("Lap", color=TEXT)
    ax.set_ylabel("Lap time (seconds)", color=TEXT)
    ax.set_title(f"{race_name} — Race Lap-Time Progression (Top 5 Finishers)", color=TEXT, fontsize=16, pad=14)
    ax.grid(True, color=GRID, linewidth=0.7, alpha=0.8)
    ax.tick_params(colors=TEXT)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT)
    fig.text(0.01, 0.015, "All available recorded lap times are plotted; pit stops, traffic, and safety-car periods can create large spikes.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(output, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


def save_fastest_lap_chart(race_name: str, rows: list[dict[str, Any]], names: dict[str, str], classified: list[dict[str, Any]], output: Path) -> None:
    fastest: dict[str, float] = {}
    for row in rows:
        seconds = row["seconds"]
        driver_id = row["driver_id"]
        if seconds is not None and (driver_id not in fastest or seconds < fastest[driver_id]):
            fastest[driver_id] = seconds
    if not fastest:
        raise RuntimeError("No valid lap times for the fastest-lap comparison chart.")

    classified_order = {item["driver_id"]: (item["position"] or 999) for item in classified}
    ordered = sorted(fastest.items(), key=lambda pair: pair[1])
    labels = [names.get(driver_id, driver_id) for driver_id, _ in ordered]
    values = [seconds for _, seconds in ordered]
    colors = [COLORS[i % len(COLORS)] for i in range(len(values))]

    fig, ax = plt.subplots(figsize=(12, max(7, len(ordered) * 0.34)), facecolor=BG)
    ax.set_facecolor(PANEL)
    bars = ax.barh(labels, values, color=colors, alpha=0.9)
    ax.invert_yaxis()
    ax.set_xlabel("Fastest recorded lap (seconds)", color=TEXT)
    ax.set_title(f"{race_name} — Fastest Recorded Lap Comparison", color=TEXT, fontsize=16, pad=14)
    ax.grid(True, axis="x", color=GRID, linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=TEXT, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    for bar, value in zip(bars, values):
        ax.text(value + 0.15, bar.get_y() + bar.get_height() / 2, format_lap_time(value), va="center", ha="left", color=TEXT, fontsize=7)
    fig.text(0.01, 0.015, "Calculated as the minimum recorded lap time per driver from the public lap-timing feed; not a substitute for official fastest-lap classification.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(output, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


def process_round(round_number: int, force: bool = False) -> str:
    slug = ROUND_SLUGS[round_number]
    output_folder = IMAGE_DIR / f"2022-{slug}-grand-prix-race"
    output_folder.mkdir(parents=True, exist_ok=True)

    if not force and all((output_folder / name).is_file() for name in CHART_FILES):
        print(f"SKIP: Round {round_number:02d} ({slug}) already has all public race charts.")
        return "skipped"

    print("\n" + "=" * 72)
    print(f"START round {round_number:02d}/22: {slug.replace('-', ' ').title()} — Race lap analysis")
    classification = fetch_race_classification(round_number)
    race_name = classification.get("raceName", f"2022 Round {round_number}")
    names, classified = driver_metadata(classification)
    rows = fetch_all_lap_timings(round_number)

    # Write to temporary names first. Only replace individual chart files after
    # a chart has rendered successfully; don't delete existing user's files.
    temp_paths = [output_folder / (name + ".tmp.png") for name in CHART_FILES]
    try:
        save_position_chart(race_name, rows, classified, names, temp_paths[0])
        save_lap_time_chart(race_name, rows, classified, names, temp_paths[1])
        save_fastest_lap_chart(race_name, rows, names, classified, temp_paths[2])
        for temp_path, final_name in zip(temp_paths, CHART_FILES):
            temp_path.replace(output_folder / final_name)
    finally:
        for temp_path in temp_paths:
            if temp_path.exists():
                temp_path.unlink()

    source_note = output_folder / "RACE_DATA_SOURCE.txt"
    source_note.write_text(
        "2022 race analysis data source\n"
        "Source: Jolpica-F1 public timing/classification API.\n\n"
        "These charts use lap times and recorded race positions. They do not contain car telemetry channels such as speed, throttle, brake, gear, or GPS position.\n"
        "Position progression uses reported position by lap; lap-time progression includes recorded times, so pit stops, traffic and safety-car periods can create spikes.\n"
        "The fastest recorded lap comparison is computed from the available lap-timing feed and may not match official classification in all edge cases.\n",
        encoding="utf-8",
    )
    print(f"SUCCESS: {race_name} — saved 3 public-data race charts to {output_folder}")
    return "generated"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--round", type=int, choices=range(1, 23), help="Generate one 2022 round (1–22).")
    group.add_argument("--all", action="store_true", help="Generate race charts for all 22 rounds.")
    parser.add_argument("--force", action="store_true", help="Regenerate charts even if all three public charts already exist.")
    args = parser.parse_args()

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    rounds = [args.round] if args.round is not None else list(range(1, 23))
    generated = skipped = failed = 0
    failures: list[tuple[int, str]] = []
    for round_number in rounds:
        try:
            status = process_round(round_number, force=args.force)
            if status == "generated":
                generated += 1
            else:
                skipped += 1
        except KeyboardInterrupt:
            print("\nStopped by user. Existing completed charts were kept.")
            break
        except Exception as exc:
            failed += 1
            failures.append((round_number, f"{type(exc).__name__}: {exc}"))
            print(f"FAILED: Round {round_number:02d} ({ROUND_SLUGS[round_number]}) — {type(exc).__name__}: {exc}")
            traceback.print_exc()
        time.sleep(0.25)

    report_lines = [
        "2022 PUBLIC RACE LAP ANALYSIS SUMMARY",
        f"Generated: {generated}",
        f"Already complete: {skipped}",
        f"Failed: {failed}",
    ]
    if failures:
        report_lines.append("\nFailed rounds:")
        report_lines.extend(f"- Round {number} ({ROUND_SLUGS[number]}): {reason}" for number, reason in failures)
    report_lines.append("\nSource: Jolpica-F1 public lap-timing and classification API.")
    report_lines.append("These are race lap-time/position charts, not car telemetry (speed/throttle/brake/gear/GPS).")
    REPORT_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 72)
    print("2022 PUBLIC RACE LAP ANALYSIS SUMMARY")
    print(f"Generated: {generated}")
    print(f"Already complete: {skipped}")
    print(f"Failed: {failed}")
    if failures:
        print("\nFailed rounds:")
        for number, reason in failures:
            print(f"- Round {number} ({ROUND_SLUGS[number]}): {reason}")
    print(f"\nDetailed report: {REPORT_PATH}")
    print("Charts are based on public lap timing/classification data, not car telemetry.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

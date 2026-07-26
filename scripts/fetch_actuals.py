"""
One-off fetch: pulls actual final NFL season stats for a given year from
ESPN's public stats API (no auth required) and writes them to
data/historical/{season}_actual_stats.csv in the app's canonical schema.

Usage:
    python scripts/fetch_actuals.py 2025
    python scripts/fetch_actuals.py 2024
    python scripts/fetch_actuals.py 2023

This is NOT called at app runtime -- the app just reads the CSVs this
script produces, so draft day doesn't depend on ESPN being reachable.

Team defense (DEF) rows are included via ESPN's standings endpoint, but
only points allowed (the dominant scoring category in this league's
D/ST rules) -- defensive TDs/safeties/return TDs/XP-returned aren't
exposed by that endpoint and are left at 0 pending a better source.
"""
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/statistics/byathlete"
STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/football/nfl/standings"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"

# (sort key, how many pages of 50 to pull) -- covers players whose primary
# production is in that category; deduped by athlete id afterward so a
# rushing WR caught by the receiving query isn't fetched twice.
QUERIES = [
    ("passing.passingYards", 2),
    ("rushing.rushingYards", 5),
    ("receiving.receivingYards", 6),
    ("kicking.fieldGoalsMade", 2),
]

CSV_FIELDS = [
    "name", "position", "team",
    "pass_yds", "pass_td",
    "rush_yds", "rush_td",
    "rec", "rec_yds", "rec_td",
    "return_td", "off_fumble_return_td", "two_pt",
    "fg_0_19", "fg_20_29", "fg_30_39", "fg_40_49", "fg_50_plus", "pat_made",
    "def_td", "def_safety", "def_return_td", "def_xp_returned", "def_points_allowed",
]


def fetch_page(season: int, sort: str, page: int) -> dict:
    url = (
        f"{BASE_URL}?region=us&lang=en&contentorigin=espn&isqualified=false"
        f"&page={page}&limit=50&sort={sort}%3Adesc&season={season}&seasontype=2"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def category_values(athlete_record: dict, category_names: dict[str, list[str]]) -> dict[str, float]:
    """Flattens an athlete's per-category totals into {statName: value} using
    the root response's category->names ordering."""
    out: dict[str, float] = {}
    for cat in athlete_record.get("categories", []):
        names = category_names.get(cat["name"])
        if not names:
            continue
        for name, value in zip(names, cat.get("values", [])):
            out[name] = value
    return out


def fetch_team_defense(season: int) -> dict[str, dict]:
    """Team-level DEF rows keyed by team abbreviation, sourced from the standings
    endpoint's pointsAgainst (season total). Only points allowed is available here --
    see module docstring for the gap on TDs/safeties/return TDs/XP-returned."""
    url = f"{STANDINGS_URL}?season={season}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    defenses: dict[str, dict] = {}
    for conference in data.get("children", []):
        for entry in conference.get("standings", {}).get("entries", []):
            team = entry["team"]
            points_against = next(
                (s["value"] for s in entry["stats"] if s["name"] == "pointsAgainst"), 0
            )
            defenses[team["abbreviation"]] = {
                "name": team.get("displayName", team["abbreviation"]),
                "position": "DEF",
                "team": team["abbreviation"],
                "def_td": 0,
                "def_safety": 0,
                "def_return_td": 0,
                "def_xp_returned": 0,
                "def_points_allowed": points_against,
            }
    return defenses


def fetch_season(season: int) -> dict[str, dict]:
    players: dict[str, dict] = {}  # athlete id -> canonical row

    for sort_key, num_pages in QUERIES:
        for page in range(1, num_pages + 1):
            try:
                data = fetch_page(season, sort_key, page)
            except urllib.error.HTTPError as e:
                print(f"  {sort_key} page {page}: request failed ({e.code}), skipping")
                continue
            category_names = {c["name"]: c["names"] for c in data.get("categories", [])}

            for record in data.get("athletes", []):
                athlete = record["athlete"]
                athlete_id = athlete["id"]
                if athlete_id in players:
                    continue  # already captured from an earlier query

                position = (athlete.get("position") or {}).get("abbreviation", "")
                if position == "PK":
                    position = "K"  # ESPN calls kickers "PK"; our schema uses "K"
                if position not in ("QB", "RB", "WR", "TE", "K"):
                    continue  # not a fantasy-relevant offensive/kicking position

                stats = category_values(record, category_names)
                players[athlete_id] = {
                    "name": athlete.get("displayName", ""),
                    "position": position,
                    "team": athlete.get("teamShortName", ""),
                    "pass_yds": stats.get("passingYards", 0),
                    "pass_td": stats.get("passingTouchdowns", 0),
                    "rush_yds": stats.get("rushingYards", 0),
                    "rush_td": stats.get("rushingTouchdowns", 0),
                    "rec": stats.get("receptions", 0),
                    "rec_yds": stats.get("receivingYards", 0),
                    "rec_td": stats.get("receivingTouchdowns", 0),
                    "return_td": stats.get("returnTouchdowns", 0),
                    "off_fumble_return_td": 0,  # not exposed by this endpoint
                    "two_pt": stats.get("totalTwoPointConvs", 0),
                    "fg_0_19": stats.get("fieldGoalsMade1_19", 0),
                    "fg_20_29": stats.get("fieldGoalsMade20_29", 0),
                    "fg_30_39": stats.get("fieldGoalsMade30_39", 0),
                    "fg_40_49": stats.get("fieldGoalsMade40_49", 0),
                    "fg_50_plus": stats.get("fieldGoalsMade50", 0),
                    "pat_made": stats.get("extraPointsMade", 0),
                }

            print(f"  {sort_key} page {page}: {len(data.get('athletes', []))} rows, {len(players)} unique so far")

    return players


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/fetch_actuals.py <season>")
        sys.exit(1)
    season = int(sys.argv[1])

    print(f"Fetching {season} actual stats...")
    players = fetch_season(season)

    print(f"Fetching {season} team defense (points allowed)...")
    defenses = fetch_team_defense(season)
    print(f"  {len(defenses)} teams")

    all_rows = list(players.values()) + list(defenses.values())

    out_path = DATA_DIR / f"{season}_actual_stats.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in sorted(all_rows, key=lambda r: r["name"]):
            writer.writerow(row)

    print(f"Wrote {len(all_rows)} players/teams to {out_path}")


if __name__ == "__main__":
    main()

"""
One-off fetch: pulls actual final 2025 NFL season stats from ESPN's public
stats API (no auth required) and writes them to data/historical/2025_actual_stats.csv
in the app's canonical schema.

Run manually when you want to refresh the data (e.g. next season):
    python scripts/fetch_2025_actuals.py

This is NOT called at app runtime -- the app just reads the CSV this script
produces, so draft day doesn't depend on ESPN being reachable.

Known gap: team defense (DEF) stats aren't included. ESPN's by-athlete
endpoint only covers individual players; team defense would need a
separate team-stats endpoint that hasn't been wired up yet.
"""
import csv
import json
import urllib.request
from pathlib import Path

SEASON = 2025
BASE_URL = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/statistics/byathlete"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "historical" / "2025_actual_stats.csv"

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
]


def fetch_page(sort: str, page: int) -> dict:
    url = (
        f"{BASE_URL}?region=us&lang=en&contentorigin=espn&isqualified=false"
        f"&page={page}&limit=50&sort={sort}%3Adesc&season={SEASON}&seasontype=2"
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


def main() -> None:
    players: dict[str, dict] = {}  # athlete id -> canonical row

    for sort_key, num_pages in QUERIES:
        for page in range(1, num_pages + 1):
            data = fetch_page(sort_key, page)
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

            print(f"{sort_key} page {page}: {len(data.get('athletes', []))} rows, {len(players)} unique so far")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in sorted(players.values(), key=lambda r: r["name"]):
            writer.writerow(row)

    print(f"Wrote {len(players)} players to {OUT_PATH}")


if __name__ == "__main__":
    main()

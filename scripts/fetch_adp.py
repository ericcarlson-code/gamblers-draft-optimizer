"""
Fetch consensus Average Draft Position (ADP) from Fantasy Football Calculator's
free API (https://fantasyfootballcalculator.com/api/v1/adp/) and write it to
data/historical/adp.csv (current season) and data/historical/{year}_adp.csv
(historical seasons, where available).

Usage:
    python scripts/fetch_adp.py

Why this source instead of a generic PPR/standard list: this league starts
2 QBs and scores 0 points per reception (non-PPR) -- a generic single-QB PPR
ADP list would systematically misvalue both QBs and pass-catchers relative
to how this league actually drafts. FFC's "2qb" format is REAL empirical ADP
from actual 2-QB-format drafts (not an approximation blended from generic
1-QB data), which is the closest free data source to this league's actual
settings. Their site explicitly reports this format as non-PPR-leaning too
(their generic "standard" format meta reports type "Non-PPR").

Attribution: per FFC's terms, ADP data is free for personal/commercial use
with attribution requested -- see the credit added to league_config.json's
notes.

Historical note: FFC's `year` param DOES return genuinely different, dated
data for past seasons (confirmed 2020-2024 all return real historical draft
windows, e.g. year=2024 returns drafts from 2024-08-22 to 2024-09-01) --
unlike the previous ESPN-based source, which was live-only regardless of the
season requested. 2025 has no 2QB-format data at FFC (returns "No ADP data
found") and is skipped. Historical years also aren't available at exactly
10 teams -- FFC silently substitutes the closest team-size it has archived
(usually 12), which is noted in the printed output but not treated as an
error, since it's still a real, directionally-useful historical ADP signal.
"""
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://fantasyfootballcalculator.com/api/v1/adp/2qb"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"
CURRENT_YEAR = 2026
HISTORICAL_YEARS = [2020, 2021, 2022, 2023, 2024]  # 2025 has no FFC 2QB data
CSV_FIELDS = ["name", "adp"]

# FFC names team defenses like "Denver Defense" / "LA Rams Defense" -- our
# canonical schema (see optimizer/schema.py, fetch_actuals.py) uses the full
# real team name ("Denver Broncos"). Join defenses by team abbreviation
# instead of name to bridge that gap.
TEAM_ABBR_TO_FULL_NAME = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LV": "Las Vegas Raiders", "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SF": "San Francisco 49ers", "SEA": "Seattle Seahawks", "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans", "WSH": "Washington Commanders",
}


def fetch_adp(year: int, teams: int = 10) -> tuple[list[dict], dict]:
    url = f"{BASE_URL}?teams={teams}&year={year}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  {year}: request failed ({e.code}), skipping")
        return [], {}

    if data.get("status") != "Success":
        print(f"  {year}: {data.get('errors', 'no data')}, skipping")
        return [], {}

    meta = data.get("meta", {})
    rows = []
    for p in data.get("players", []):
        name = p.get("name")
        adp = p.get("adp")
        if not name or adp is None:
            continue
        if p.get("position") == "DEF":
            name = TEAM_ABBR_TO_FULL_NAME.get(p.get("team"), name)
        rows.append({"name": name, "adp": round(float(adp), 1)})
    return rows, meta


def write_csv(rows: list[dict], out_path: Path) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["adp"]):
            writer.writerow(row)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {CURRENT_YEAR} (current) 2QB-format ADP...")
    rows, meta = fetch_adp(CURRENT_YEAR)
    if rows:
        if meta.get("teams") != 10:
            print(f"  NOTE: FFC returned teams={meta.get('teams')} (requested 10) -- using it anyway")
        write_csv(rows, DATA_DIR / "adp.csv")
        print(f"  Wrote {len(rows)} players to data/historical/adp.csv ({meta.get('total_drafts')} real drafts sampled)")

    for year in HISTORICAL_YEARS:
        print(f"Fetching {year} 2QB-format ADP...")
        rows, meta = fetch_adp(year)
        if not rows:
            continue
        if meta.get("teams") != 10:
            print(f"  NOTE: FFC returned teams={meta.get('teams')} (requested 10) -- using it anyway")
        write_csv(rows, DATA_DIR / f"{year}_adp.csv")
        print(f"  Wrote {len(rows)} players to data/historical/{year}_adp.csv ({meta.get('total_drafts')} real drafts sampled)")


if __name__ == "__main__":
    main()

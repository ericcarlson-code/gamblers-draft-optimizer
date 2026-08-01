"""
Fetch static player bio facts (height, weight, birth date, college) via
nflreadpy, writing data/player_bios.csv.

Not year-specific like the stats fetchers -- these are career-level facts
about a person, not a season's production, so one fetch covers every
history year and the live board alike.

Keyed by (name, position) rather than name alone: nflreadpy's own player
table has 119 real name collisions across different people/positions (e.g.
two people named "Josh Allen" -- a Bills QB and a long-retired Panthers
center), and this project's board data always carries a definite position
for every row, so exact (name, position) matching is sufficient here --
unlike the ADP/consensus joins elsewhere in this codebase, names in this
source come from the SAME nflreadpy/nflverse ecosystem as our own board
data, so there's no cross-source formatting drift to fall back through.
A person can also appear more than once for the same (name, position) pair
across nflreadpy's full player history table -- keeps whichever row has the
highest `last_season` (most likely to be the currently-relevant person).

Usage:
    python scripts/fetch_player_bios_nflreadpy.py
"""
import csv
from pathlib import Path

import nflreadpy as nfl
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

CSV_FIELDS = ["name", "position", "height", "weight", "birth_date", "college"]


def fetch_bios() -> list[dict]:
    df = nfl.load_players().to_pandas()
    best: dict[tuple[str, str], dict] = {}

    for _, row in df.iterrows():
        name = row.get("display_name")
        position = row.get("position")
        if not name or pd.isna(name) or not position or pd.isna(position):
            continue
        key = (name, position)
        last_season = row.get("last_season")
        last_season = 0 if pd.isna(last_season) else int(last_season)
        if key in best and best[key]["_last_season"] >= last_season:
            continue
        birth_date = row.get("birth_date")
        college = row.get("college_name")
        best[key] = {
            "name": name,
            "position": position,
            "height": None if pd.isna(row.get("height")) else float(row.get("height")),
            "weight": None if pd.isna(row.get("weight")) else float(row.get("weight")),
            "birth_date": "" if pd.isna(birth_date) else str(birth_date),
            "college": "" if pd.isna(college) else str(college),
            "_last_season": last_season,
        }

    return list(best.values())


def main() -> None:
    print("Fetching player bio data via nflreadpy...")
    rows = fetch_bios()
    print(f"  {len(rows)} (name, position) entries")

    out_path = DATA_DIR / "player_bios.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (r["name"], r["position"])):
            writer.writerow(row)

    print(f"Wrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()

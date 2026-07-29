"""
Fetch the real NFL schedule (week, matchup, kickoff time) via nflreadpy.

Backs three Rankings-tab features that all need to know "who plays whom,
and when, in a given week": the Week 1-18 selector's per-team bye-week
zeroing, the weekly schedule sidebar (two team logos + game time per
matchup), and This Week -> real-week semantics generally. Bye weeks are
NOT precomputed here -- derived client-side (any team absent from a
week's home/away rows that week is on a bye), a trivial one-line filter
not worth a second artifact.

Usage:
    python scripts/fetch_schedule.py 2026
"""
import csv
import sys
from pathlib import Path

import nflreadpy as nfl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.fetch_actuals import DATA_DIR

CSV_FIELDS = ["week", "gameday", "gametime", "away_team", "home_team", "location"]


def fetch_schedule(season: int) -> list[dict]:
    df = nfl.load_schedules(seasons=[season]).to_pandas()
    games = []
    for _, row in df.iterrows():
        games.append({
            "week": int(row["week"]),
            "gameday": row.get("gameday") or "",
            # nflreadpy's gametime is Eastern Time (confirmed against known
            # kickoff slots -- 13:00/16:05/16:25/20:20 ET). Not converted
            # here -- the site converts to the user's own timezone at
            # render time so this stays a plain, source-of-truth ET value.
            "gametime": row.get("gametime") or "",
            "away_team": row.get("away_team") or "",
            "home_team": row.get("home_team") or "",
            # "Neutral" (vs "Home") is nflreadpy's own flag for a non-home-
            # stadium game -- in practice this is exactly the international
            # game slate (London/Germany/Brazil/Australia), used client-side
            # to badge those games.
            "location": row.get("location") or "",
        })
    return sorted(games, key=lambda g: (g["week"], g["gameday"], g["gametime"]))


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/fetch_schedule.py <season>")
        sys.exit(1)
    season = int(sys.argv[1])

    print(f"Fetching {season} schedule via nflreadpy...")
    games = fetch_schedule(season)
    if not games:
        print(f"  No schedule data available yet for {season} -- NFL schedules "
              f"typically release mid-May; nothing written.")
        sys.exit(1)
    print(f"  {len(games)} games across {max(g['week'] for g in games)} weeks")

    out_path = DATA_DIR / f"{season}_schedule.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(games)

    print(f"Wrote {len(games)} games to {out_path}")


if __name__ == "__main__":
    main()

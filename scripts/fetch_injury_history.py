"""
Approximate games missed to injury, per player per season, via nflreadpy.

This is an EXPLICIT APPROXIMATION, not a precise detector -- confirmed via
research that no available data source can tell whether a player left a
game before or after halftime (nflreadpy's load_snap_counts() is per-game
totals only, no first-half/second-half split). Two things nflreadpy does
give us, combined here:

  - load_injuries(): a weekly injury-report appearance per player (practice
    designation + game status) -- but report_status itself is frequently
    null (~46% of rows in a spot check) even for players who go on to miss
    real time, so it can't be used alone as a week-by-week "missed this
    week for injury" flag. A player who lands on IR for a long stretch
    often stops appearing on the weekly report entirely once already out,
    rather than being re-listed "Out" every single week.
  - the canonical actual-stats CSV's own games_played field (already
    fetched by fetch_actuals_nflreadpy.py) -- the real, precise count of
    games a player actually played that season.

The proxy used here: games_missed = 17 (real NFL regular-season length)
minus games_played, attributed to INJURY only if the player appears on
that season's injury report at all (any week, any status) -- a player
who missed games with zero injury-report appearances all season (healthy
scratch, suspension, didn't make the roster until later) is not counted.
On top of that, a game the player technically appeared in but at very low
offensive snap share (<25%) while also on that week's injury report is
added as a "left early" proxy game -- the closest available signal to
"left before halftime," not an exact match for it.

Usage:
    python scripts/fetch_injury_history.py 2025
"""
import csv
import sys
from pathlib import Path

import nflreadpy as nfl
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.fetch_actuals import DATA_DIR

REGULAR_SEASON_GAMES = 17
LOW_SNAP_SHARE_THRESHOLD = 0.25
CSV_FIELDS = ["player", "season", "games_missed_injury"]


def _actual_games_played(season: int) -> dict[str, int]:
    path = DATA_DIR / f"{season}_actual_stats.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    df = df[df["position"].isin({"QB", "RB", "WR", "TE", "K"})]
    return {row["name"]: int(row["games_played"]) for _, row in df.iterrows() if pd.notna(row.get("games_played"))}


def compute_injury_games_missed(season: int) -> dict[str, int]:
    games_played = _actual_games_played(season)
    if not games_played:
        return {}

    injuries = nfl.load_injuries(seasons=[season]).to_pandas()
    players_with_injury_report = set(injuries["full_name"].dropna())

    snaps = nfl.load_snap_counts(seasons=[season]).to_pandas()
    # (player, week) on the injury report at all this week, any status.
    injury_weeks = set(zip(injuries["full_name"], injuries["week"]))
    low_snap_injured_games = (
        snaps[snaps["offense_pct"].notna() & (snaps["offense_pct"] < LOW_SNAP_SHARE_THRESHOLD)]
        .apply(lambda r: (r["player"], r["week"]) in injury_weeks, axis=1)
    )
    left_early_counts = (
        snaps[snaps["offense_pct"].notna() & (snaps["offense_pct"] < LOW_SNAP_SHARE_THRESHOLD)][low_snap_injured_games]
        .groupby("player")
        .size()
        .to_dict()
    )

    result: dict[str, int] = {}
    for name, played in games_played.items():
        missed = max(0, REGULAR_SEASON_GAMES - played)
        if missed == 0 and name not in left_early_counts:
            continue
        games_missed_injury = left_early_counts.get(name, 0)
        if missed > 0 and name in players_with_injury_report:
            games_missed_injury += missed
        if games_missed_injury > 0:
            result[name] = games_missed_injury
    return result


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/fetch_injury_history.py <season>")
        sys.exit(1)
    season = int(sys.argv[1])

    print(f"Computing {season} injury-games-missed approximation via nflreadpy...")
    result = compute_injury_games_missed(season)
    print(f"  {len(result)} players with a nonzero injury-games-missed count")

    out_path = DATA_DIR / f"{season}_injury_games_missed.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for name, count in sorted(result.items()):
            writer.writerow({"player": name, "season": season, "games_missed_injury": count})

    print(f"Wrote {len(result)} rows to {out_path}")


if __name__ == "__main__":
    main()

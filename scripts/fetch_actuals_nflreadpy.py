"""
Fetch actual season stats via nflreadpy (free nflverse data), writing the
same canonical data/historical/{season}_actual_stats.csv shape as
fetch_actuals.py -- but from the COMPLETE player pool instead of ESPN's
top-N-per-category leaderboards.

Why this exists alongside fetch_actuals.py, not instead of it: the ESPN
leaderboard approach only ever pulls a fixed number of pages sorted by one
stat category at a time (see fetch_actuals.py's QUERIES), so any player
whose season volume falls outside every category's page cap is silently
absent -- confirmed missing: George Kittle, Terry McLaurin, Cooper Kupp,
Jimmy Garoppolo, Dalton Kincaid, Jauan Jennings, Kayshon Boutte, Jayden
Higgins (2025). nflreadpy's load_player_stats() returns every player with
any recorded stat line, no leaderboard cutoff. fetch_actuals.py is kept as
a documented fallback (not deleted) since nflreadpy's polars dependency
needed a real Windows-ARM compatibility workaround (see requirements.txt --
polars-lts-cpu, not plain polars) to work in this dev environment at all.

Bonus: this source also reports fg_made_50_59 and fg_made_60_ as separate
counts (unlike ESPN's single combined "50+" aggregate), which finally lets
the league's real 60+ yard FG premium (15pts vs 5pts for 50-59) apply to
real kicks instead of being conservatively folded into the 50-59 bucket.

Usage:
    python scripts/fetch_actuals_nflreadpy.py 2025

Team defense (DEF) rows are NOT refetched here -- still sourced from
fetch_actuals.py's ESPN standings-based fetch_team_defense(), reused
as-is (points allowed only; DEF TDs/safeties/return TDs/XP-returned
remain a separate, unresolved data-source gap, unrelated to this fix).
"""
import sys
from pathlib import Path

import nflreadpy as nfl
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.fetch_actuals import CSV_FIELDS, DATA_DIR, fetch_team_defense

FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K"}


def _val(row: pd.Series, col: str) -> float:
    v = row.get(col, 0)
    return 0.0 if pd.isna(v) else v


def fetch_season(season: int) -> dict[str, dict]:
    df = nfl.load_player_stats(seasons=[season], summary_level="reg").to_pandas()
    players: dict[str, dict] = {}

    for _, row in df.iterrows():
        position = row.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        name = row.get("player_display_name")
        if not name or pd.isna(name):
            continue

        players[name] = {
            "name": name,
            "position": position,
            "team": row.get("recent_team") or "",
            "games_played": _val(row, "games"),
            "pass_yds": _val(row, "passing_yards"),
            "pass_td": _val(row, "passing_tds"),
            "pass_att": _val(row, "attempts"),
            "pass_cmp": _val(row, "completions"),
            "pass_int": _val(row, "passing_interceptions"),
            "rush_yds": _val(row, "rushing_yards"),
            "rush_td": _val(row, "rushing_tds"),
            "carries": _val(row, "carries"),
            "rec": _val(row, "receptions"),
            "rec_yds": _val(row, "receiving_yards"),
            "rec_td": _val(row, "receiving_tds"),
            "targets": _val(row, "targets"),
            # special_teams_tds is the closest available proxy for punt/kick
            # return TDs -- nflreadpy doesn't expose a dedicated
            # "this player scored via return" field the way it exposes FG
            # distance bands; fumble_recovery_tds likewise best-effort covers
            # off_fumble_return_td. Both are minor scoring categories (a few
            # points/season at most) -- not the focus of this fix.
            "return_td": _val(row, "special_teams_tds"),
            "off_fumble_return_td": _val(row, "fumble_recovery_tds"),
            "two_pt": (
                _val(row, "passing_2pt_conversions")
                + _val(row, "rushing_2pt_conversions")
                + _val(row, "receiving_2pt_conversions")
            ),
            "fg_0_19": _val(row, "fg_made_0_19"),
            "fg_20_29": _val(row, "fg_made_20_29"),
            "fg_30_39": _val(row, "fg_made_30_39"),
            "fg_40_49": _val(row, "fg_made_40_49"),
            "fg_50_plus": _val(row, "fg_made_50_59"),  # now genuinely 50-59 only
            "fg_60_plus": _val(row, "fg_made_60_"),  # new: real 60+ makes, precisely counted
            "pat_made": _val(row, "pat_made"),
        }

    return players


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/fetch_actuals_nflreadpy.py <season>")
        sys.exit(1)
    season = int(sys.argv[1])

    print(f"Fetching {season} actual stats via nflreadpy...")
    players = fetch_season(season)
    print(f"  {len(players)} fantasy-relevant players")

    print(f"Fetching {season} team defense (points allowed, via ESPN)...")
    defenses = fetch_team_defense(season)
    print(f"  {len(defenses)} teams")

    all_rows = list(players.values()) + list(defenses.values())

    out_path = DATA_DIR / f"{season}_actual_stats.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    import csv

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(all_rows, key=lambda r: r["name"]):
            writer.writerow(row)

    print(f"Wrote {len(all_rows)} players/teams to {out_path}")


if __name__ == "__main__":
    main()

"""
Fetch real per-week (not season-total) player and team-defense stats via
nflreadpy, writing data/historical/{season}_weekly_stats.csv -- same
canonical field names as {season}_actual_stats.csv (fetch_actuals_nflreadpy.py)
plus `week` and `opponent_team`.

Why this exists: every other stats file in this project is season-total only
(no `week` column anywhere), so Historical Review has never been able to show
a player's actual points for a specific week or who they played that week --
this is the real per-game-stats pipeline the project roadmap had listed as
"not started". nflreadpy's load_player_stats() accepts summary_level="week"
(its own default) and returns one row per player per game, with the same
underlying stat columns fetch_actuals_nflreadpy.py already maps from -- this
script is that same mapping, just not collapsed to one row per season.

Team defense weekly rows aren't in load_player_stats() at all (that's an
individual-player feed) -- built instead from load_team_stats(summary_level=
"week") for def_tds/def_safeties/etc., joined against load_schedules() for
that week's real points allowed (the opponent's final score), mirroring what
fetch_actuals.py's fetch_team_defense() already does at season granularity.

Usage:
    python scripts/fetch_weekly_actuals_nflreadpy.py 2024
"""
import csv
import sys
from pathlib import Path

import nflreadpy as nfl
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.fetch_actuals_nflreadpy import FANTASY_POSITIONS, POSITION_OVERRIDES

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"

WEEKLY_CSV_FIELDS = [
    "name", "position", "team", "week", "opponent_team",
    "pass_yds", "pass_td", "pass_att", "pass_cmp", "pass_int",
    "rush_yds", "rush_td", "carries",
    "rec", "rec_yds", "rec_td", "targets",
    "return_td", "off_fumble_return_td", "two_pt",
    "fg_0_19", "fg_20_29", "fg_30_39", "fg_40_49", "fg_50_plus", "fg_60_plus", "pat_made",
    "def_td", "def_safety", "def_return_td", "def_xp_returned", "def_points_allowed",
]


def _val(row: pd.Series, col: str) -> float:
    v = row.get(col, 0)
    return 0.0 if pd.isna(v) else v


def fetch_player_weeks(season: int) -> list[dict]:
    df = nfl.load_player_stats(seasons=[season], summary_level="week").to_pandas()
    rows: list[dict] = []

    for _, row in df.iterrows():
        position = row.get("position")
        name = row.get("player_display_name")
        position = POSITION_OVERRIDES.get((name, position), position)
        if position not in FANTASY_POSITIONS:
            continue
        if not name or pd.isna(name):
            continue

        rows.append({
            "name": name,
            "position": position,
            "team": row.get("team") or "",
            "week": int(row.get("week")),
            "opponent_team": row.get("opponent_team") or "",
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
            "fg_50_plus": _val(row, "fg_made_50_59"),
            "fg_60_plus": _val(row, "fg_made_60_"),
            "pat_made": _val(row, "pat_made"),
        })

    return rows


def fetch_team_defense_weeks(season: int) -> list[dict]:
    team_df = nfl.load_team_stats(seasons=[season], summary_level="week").to_pandas()
    sched_df = nfl.load_schedules(seasons=[season]).to_pandas()

    # {(week, team): points allowed that week} -- the OPPONENT's score in that
    # team's game, derived from each game's home/away final score.
    points_allowed: dict[tuple[int, str], float] = {}
    for _, g in sched_df.iterrows():
        week = g.get("week")
        if pd.isna(week):
            continue
        week = int(week)
        home, away = g.get("home_team"), g.get("away_team")
        home_score, away_score = g.get("home_score"), g.get("away_score")
        if pd.isna(home_score) or pd.isna(away_score):
            continue  # game not yet played
        points_allowed[(week, home)] = float(away_score)
        points_allowed[(week, away)] = float(home_score)

    rows: list[dict] = []
    for _, row in team_df.iterrows():
        week = row.get("week")
        team = row.get("team")
        if pd.isna(week) or not team:
            continue
        week = int(week)
        rows.append({
            "name": team,
            "position": "DEF",
            "team": team,
            "week": week,
            "opponent_team": row.get("opponent_team") or "",
            "def_td": _val(row, "def_tds"),
            "def_safety": _val(row, "def_safeties"),
            # No dedicated "defense/ST return TD" or "extra point returned"
            # column in load_team_stats -- left at 0, same documented gap
            # fetch_actuals.py's season-total fetch already carries.
            "def_return_td": 0,
            "def_xp_returned": 0,
            "def_points_allowed": points_allowed.get((week, team), 0.0),
        })

    return rows


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/fetch_weekly_actuals_nflreadpy.py <season>")
        sys.exit(1)
    season = int(sys.argv[1])

    print(f"Fetching {season} weekly player stats via nflreadpy...")
    player_rows = fetch_player_weeks(season)
    print(f"  {len(player_rows)} player-week rows")

    print(f"Fetching {season} weekly team defense stats via nflreadpy...")
    def_rows = fetch_team_defense_weeks(season)
    print(f"  {len(def_rows)} team-week rows")

    all_rows = player_rows + def_rows
    out_path = DATA_DIR / f"{season}_weekly_stats.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=WEEKLY_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(all_rows, key=lambda r: (r["week"], r["name"])):
            writer.writerow(row)

    print(f"Wrote {len(all_rows)} rows to {out_path}")


if __name__ == "__main__":
    main()

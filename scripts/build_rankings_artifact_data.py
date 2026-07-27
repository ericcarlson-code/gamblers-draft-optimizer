"""
Builds the JSON data bundle for the published rankings Artifact (a static
HTML snapshot, separate from the live app). Scores every available year
(2020-2025 actual, plus the 2026 projection) under the CURRENT
league_config.json, and attaches each 2026-projection player's VOR
trajectory across whatever prior years they appeared in -- this is what
powers the trend sparkline that explains "why is this the projection."

Run from the repo root:
    python scripts/build_rankings_artifact_data.py <output_path.json>
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from optimizer.config import load_config
from optimizer.data_loader import apply_mapping
from optimizer.schema import ALL_CANONICAL_FIELDS
from optimizer.scoring import score_player
from optimizer.tiers import assign_tiers
from optimizer.vor import compute_vor

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"
HISTORY_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]


def td_points(stats: dict, cfg: dict) -> float:
    """Isolates just the touchdown-value portion of a player's score (mirrors
    the position-scorer structure in optimizer/scoring.py's _POSITION_SCORERS,
    but only the TD-value terms -- no yardage/reception/FG points). Used to
    compute what fraction of a player's total points come from touchdowns
    vs. yardage/volume -- a proxy for week-to-week boom/bust variance, and
    for why a QB and his own pass-catcher are unusually correlated: a passing
    TD and its receiver's receiving TD are literally the same play. Kickers
    have no TD-value terms (FG distance swings are a different kind of
    variance, not this one), so they always score 0 here."""
    position = stats.get("position")
    scoring_cfg = cfg["scoring"]
    if position == "QB":
        return stats.get("pass_td", 0) * scoring_cfg["passing"]["touchdown"] + stats.get("rush_td", 0) * scoring_cfg["rushing"]["touchdown"]
    if position in ("RB", "WR", "TE"):
        return stats.get("rush_td", 0) * scoring_cfg["rushing"]["touchdown"] + stats.get("rec_td", 0) * scoring_cfg["receiving"]["touchdown"]
    if position == "DEF":
        return stats.get("def_td", 0) * scoring_cfg["defense"]["touchdown"] + stats.get("def_return_td", 0) * scoring_cfg["defense"]["return_touchdown"]
    return 0.0


def td_counts(stats: dict) -> tuple[float, float]:
    """Projected touchdown COUNTS (not point value), split passing vs.
    rushing+receiving -- the user wants these differentiated rather than
    blended into one dependency percentage. QBs are the only position that
    can throw a TD; DEF's return/defensive TDs are bucketed into the
    rush/rec column for simplicity since they aren't passing plays either."""
    position = stats.get("position")
    if position == "QB":
        return stats.get("pass_td", 0), stats.get("rush_td", 0)
    if position in ("RB", "WR", "TE"):
        return 0.0, stats.get("rush_td", 0) + stats.get("rec_td", 0)
    if position == "DEF":
        return 0.0, stats.get("def_td", 0) + stats.get("def_return_td", 0)
    return 0.0, 0.0


def load_adp(year: int | None = None) -> dict[str, float]:
    """name -> consensus ADP for that draft season (see scripts/fetch_adp.py).
    year=None loads the current/live ADP (data/historical/adp.csv, used for
    the 2026 board); a specific year loads that season's real historical ADP
    (data/historical/{year}_adp.csv) where Fantasy Football Calculator has it
    archived. Returns {} (not an error) for years with no archived data --
    currently just 2025 -- so those boards simply have no adp/value_vs_adp
    columns rather than failing the build."""
    path = DATA_DIR / (f"{year}_adp.csv" if year else "adp.csv")
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    return dict(zip(df["name"], df["adp"]))


def attach_adp_value(board: pd.DataFrame, adp_lookup: dict[str, float]) -> pd.DataFrame:
    """Adds 'adp' and 'value_vs_adp' columns. value_vs_adp compares a player's
    VOR to the VOR of whoever OUR OWN model ranks at their ADP slot -- e.g. if
    a player's ADP is 40 but our model's 40th-ranked player has much lower VOR,
    that player is a "value" relative to where the market is drafting them.
    Requires `board` already sorted by vor descending with no gaps in index
    (i.e. called after the same sort/overall_rank step as everything else)."""
    board = board.copy()
    board["adp"] = board["name"].map(adp_lookup)
    n = len(board)

    def value_vs_adp(row):
        if pd.isna(row["adp"]) or n == 0:
            return None
        rank = min(max(int(round(row["adp"])), 1), n)
        expected_vor = board.iloc[rank - 1]["vor"]
        return round(row["vor"] - expected_vor, 1)

    board["value_vs_adp"] = board.apply(value_vs_adp, axis=1)
    return board


def score_file(path: Path, cfg: dict, adp_lookup: dict[str, float] | None = None) -> pd.DataFrame:
    raw = pd.read_csv(path)
    mapping = {f: f for f in ALL_CANONICAL_FIELDS if f in raw.columns}
    df = apply_mapping(raw, mapping)
    board = df[["name", "position", "team"]].copy()
    # Only 2026_projections.csv has this column (real_stats vs draft_capital_model,
    # see optimizer/rookie_projections.py) -- actual-year stat files are all real.
    board["projection_source"] = raw["projection_source"] if "projection_source" in raw.columns else "real_stats"
    board["points"] = df.apply(lambda r: score_player(r.to_dict(), cfg), axis=1)
    td_pts = df.apply(lambda r: td_points(r.to_dict(), cfg), axis=1)
    board["td_dependency_pct"] = (td_pts / board["points"].where(board["points"] > 0)).fillna(0.0) * 100
    td_count_cols = df.apply(lambda r: td_counts(r.to_dict()), axis=1, result_type="expand")
    td_count_cols.columns = ["proj_pass_td", "proj_rush_rec_td"]
    board["proj_pass_td"] = td_count_cols["proj_pass_td"]
    board["proj_rush_rec_td"] = td_count_cols["proj_rush_rec_td"]
    board = compute_vor(board, cfg)
    board = assign_tiers(board, cfg)
    board = board.sort_values("vor", ascending=False).reset_index(drop=True)
    board["overall_rank"] = range(1, len(board) + 1)
    if adp_lookup:
        board = attach_adp_value(board, adp_lookup)
    else:
        board["adp"] = None
        board["value_vs_adp"] = None
    return board


def to_rows(board: pd.DataFrame) -> list[dict]:
    cols = [
        "overall_rank", "name", "position", "team", "points", "vor", "tier",
        "td_dependency_pct", "proj_pass_td", "proj_rush_rec_td",
    ]
    rows = board[cols].round(1).to_dict("records")
    for i, row in enumerate(rows):
        row["projection_source"] = board["projection_source"].iloc[i]
        adp = board["adp"].iloc[i]
        value_vs_adp = board["value_vs_adp"].iloc[i]
        row["adp"] = None if pd.isna(adp) else round(float(adp), 1)
        row["value_vs_adp"] = None if pd.isna(value_vs_adp) else float(value_vs_adp)
    return rows


def build_data_bundle(cfg: dict) -> dict:
    """{'2026': [...rows with history...], '2025': [...], ..., '2020': [...]}"""
    year_boards = {
        year: score_file(DATA_DIR / f"{year}_actual_stats.csv", cfg, adp_lookup=load_adp(year))
        for year in HISTORY_YEARS
    }
    projection_board = score_file(DATA_DIR / "2026_projections.csv", cfg, adp_lookup=load_adp())

    # Index each year's VOR by (name, position) for fast per-player lookup.
    year_vor_lookup = {
        year: {(r["name"], r["position"]): r["vor"] for r in board.to_dict("records")}
        for year, board in year_boards.items()
    }

    projection_rows = to_rows(projection_board)
    for row in projection_rows:
        key = (row["name"], row["position"])
        history = []
        for year in HISTORY_YEARS:
            vor = year_vor_lookup[year].get(key)
            if vor is not None:
                history.append({"year": year, "vor": round(vor, 1)})
        # The 2026 point itself is the projection, not an observed year -- flagged
        # so the frontend can render it (and the line leading to it) distinctly.
        history.append({"year": 2026, "vor": row["vor"], "projected": True})
        row["history"] = history

    bundle = {
        "meta": {
            "num_teams": cfg["league"]["num_teams"],
            "roster_slots": cfg["roster"]["slots"],
            "gap_threshold_stdevs": cfg["tiering"]["gap_threshold_stdevs"],
            "league": cfg["league"],
            "scoring": cfg["scoring"],
            "season": cfg["season"],
            "notes": cfg.get("notes", []),
        },
        "2026": projection_rows,
    }
    for year, board in year_boards.items():
        bundle[str(year)] = to_rows(board)
    return bundle


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/build_rankings_artifact_data.py <output_path.json>")
        sys.exit(1)
    out_path = Path(sys.argv[1])

    cfg = load_config()
    bundle = build_data_bundle(cfg)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f)

    print(f"Wrote {out_path}")
    for key, rows in bundle.items():
        if key == "meta":
            continue
        print(f"  {key}: {len(rows)} rows")
    with_history = sum(1 for r in bundle["2026"] if r["history"])
    print(f"  2026 rows with >=1 year of history: {with_history}/{len(bundle['2026'])}")


if __name__ == "__main__":
    main()

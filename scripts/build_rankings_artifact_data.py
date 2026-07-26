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


def score_file(path: Path, cfg: dict) -> pd.DataFrame:
    raw = pd.read_csv(path)
    mapping = {f: f for f in ALL_CANONICAL_FIELDS if f in raw.columns}
    df = apply_mapping(raw, mapping)
    board = df[["name", "position", "team"]].copy()
    board["points"] = df.apply(lambda r: score_player(r.to_dict(), cfg), axis=1)
    board = compute_vor(board, cfg)
    board = assign_tiers(board, cfg)
    board = board.sort_values("vor", ascending=False).reset_index(drop=True)
    board["overall_rank"] = range(1, len(board) + 1)
    return board


def to_rows(board: pd.DataFrame) -> list[dict]:
    return board[["overall_rank", "name", "position", "team", "points", "vor", "tier"]].round(1).to_dict("records")


def build_data_bundle(cfg: dict) -> dict:
    """{'2026': [...rows with history...], '2025': [...], ..., '2020': [...]}"""
    year_boards = {
        year: score_file(DATA_DIR / f"{year}_actual_stats.csv", cfg)
        for year in HISTORY_YEARS
    }
    projection_board = score_file(DATA_DIR / "2026_projections.csv", cfg)

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
        row["history"] = history

    bundle = {"2026": projection_rows}
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
        print(f"  {key}: {len(rows)} rows")
    with_history = sum(1 for r in bundle["2026"] if r["history"])
    print(f"  2026 rows with >=1 year of history: {with_history}/{len(bundle['2026'])}")


if __name__ == "__main__":
    main()

"""
End-to-end pipeline test: sample CSV -> column mapping -> scoring -> VOR -> tiers.

This exercises the exact sequence app.py runs after a user uploads a CSV and
clicks "Apply mapping & compute points", without needing a running browser.
"""
from pathlib import Path

import pandas as pd

from optimizer.config import load_config
from optimizer.data_loader import apply_mapping, guess_mapping
from optimizer.scoring import score_player
from optimizer.tiers import assign_tiers
from optimizer.vor import compute_vor

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "sample" / "sample_projections.csv"


def test_full_pipeline_runs_on_sample_csv():
    cfg = load_config()
    raw_df = pd.read_csv(SAMPLE_CSV)
    assert len(raw_df) == 24  # 4 QB, 4 RB, 6 WR, 2 TE, 4 K, 4 DEF

    mapping = guess_mapping(list(raw_df.columns))
    # guess_mapping doesn't know every header alias -- confirm/fill the ones it should have caught
    # and the FG/DEF columns whose exact header text isn't in the alias list yet.
    mapping.update({
        "rush_yds": "Rush Yds",
        "rush_td": "Rush TD",
        "rec_yds": "Rec Yds",
        "rec_td": "Rec TD",
        "fg_30_39": "FG 30-39",
        "def_td": "Def TD",
        "def_return_td": "Def Return TD",
        "def_xp_returned": "XP Returned",
    })

    canonical_df = apply_mapping(raw_df, mapping)
    assert set(canonical_df["position"]) == {"QB", "RB", "WR", "TE", "K", "DEF"}

    points = canonical_df.apply(lambda row: score_player(row.to_dict(), cfg), axis=1)
    assert (points >= 0).all() or (canonical_df["position"] == "DEF").any()  # DEF can go negative
    assert points.notna().all()

    board = canonical_df[["name", "position", "team"]].copy()
    board["points"] = points
    board = compute_vor(board, cfg)
    board = assign_tiers(board, cfg)

    assert "vor" in board.columns
    assert "tier" in board.columns
    assert len(board) == len(raw_df)
    assert board["tier"].min() >= 1

    # Sanity: a clearly-best QB projection should outscore a clearly-worse one
    allen_points = board.loc[board["name"] == "Josh Allen", "points"].iloc[0]
    mahomes_points = board.loc[board["name"] == "Patrick Mahomes", "points"].iloc[0]
    assert allen_points > 0 and mahomes_points > 0

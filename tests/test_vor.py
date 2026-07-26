import pandas as pd

from optimizer.vor import compute_replacement_baselines, compute_vor

# 10 teams, 2 QB starters/team, so replacement rank for QB = 20 (matches league_config.json).
CFG = {
    "league": {"num_teams": 10},
    "roster": {"slots": {"QB": 2, "WR": 4, "RB": 3, "TE": 1, "K": 2, "DEF": 1}},
}


def _fake_position_pool(position: str, n: int) -> pd.DataFrame:
    # descending points: 100.0, 99.0, 98.0, ...
    return pd.DataFrame({
        "name": [f"{position}{i}" for i in range(n)],
        "position": position,
        "points": [100.0 - i for i in range(n)],
    })


def test_replacement_baseline_uses_teams_times_starters():
    # 25 QBs available, replacement rank = 10*2 = 20 -> 20th-best QB's points (index 19) = 100-19 = 81
    players = _fake_position_pool("QB", 25)
    baselines = compute_replacement_baselines(players, CFG)
    assert baselines["QB"] == 81.0


def test_replacement_baseline_falls_back_when_pool_too_small():
    # Only 5 QBs but replacement rank wants 20 -> falls back to the worst (last) available: 100-4=96
    players = _fake_position_pool("QB", 5)
    baselines = compute_replacement_baselines(players, CFG)
    assert baselines["QB"] == 96.0


def test_vor_is_points_minus_baseline_and_sorted_descending():
    players = pd.concat([_fake_position_pool("QB", 25), _fake_position_pool("TE", 15)])
    out = compute_vor(players, CFG)

    # TE replacement rank = 10*1 = 10 -> 10th-best TE (index 9) = 100-9 = 91
    top_te = out[out["position"] == "TE"].iloc[0]
    assert top_te["points"] == 100.0
    assert top_te["replacement_points"] == 91.0
    assert top_te["vor"] == 9.0

    # Overall list must be sorted by vor descending
    assert list(out["vor"]) == sorted(out["vor"], reverse=True)

import pandas as pd

from optimizer.vor import apply_scarcity_boosts, compute_replacement_baselines, compute_vor

# 10 teams, 2 QB starters/team, so replacement rank for QB = 20 (matches league_config.json).
CFG = {
    "league": {"num_teams": 10},
    "roster": {"slots": {"QB": 2, "WR": 4, "RB": 3, "TE": 1, "K": 2, "DEF": 1}},
}

CFG_WITH_QB_BOOST = {
    **CFG,
    "scarcity_boosts": {
        "QB": {"max_multiplier": 2.0, "taper_to_rank": 11},
        "note": "test fixture, not real calibration",
    },
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


def test_scarcity_boost_scales_top_ranked_qb_by_max_multiplier():
    # 25 QBs, replacement rank 20 -> baseline is QB19 (index 19, points 81), so
    # QB0's raw vor is 100-81=19. With max_multiplier=2.0 at rank 1, boosted vor = 38.
    players = _fake_position_pool("QB", 25)
    out = compute_vor(players, CFG_WITH_QB_BOOST)
    top_qb = out[out["name"] == "QB0"].iloc[0]
    assert top_qb["vor"] == 38.0


def test_scarcity_boost_leaves_positions_past_taper_rank_unchanged():
    # taper_to_rank=11 -> the 11th-ranked QB (index 10, "QB10") gets frac=0, no boost.
    players = _fake_position_pool("QB", 25)
    out = compute_vor(players, CFG_WITH_QB_BOOST)
    qb10 = out[out["name"] == "QB10"].iloc[0]
    assert qb10["vor"] == qb10["points"] - qb10["replacement_points"]


def test_scarcity_boost_does_not_affect_unlisted_positions():
    players = pd.concat([_fake_position_pool("QB", 25), _fake_position_pool("TE", 15)])
    boosted = compute_vor(players, CFG_WITH_QB_BOOST)
    unboosted = compute_vor(players, CFG)
    te_boosted = boosted[boosted["position"] == "TE"].sort_values("name").reset_index(drop=True)
    te_unboosted = unboosted[unboosted["position"] == "TE"].sort_values("name").reset_index(drop=True)
    assert list(te_boosted["vor"]) == list(te_unboosted["vor"])


def test_apply_scarcity_boosts_is_a_no_op_with_no_config():
    players = _fake_position_pool("QB", 10)
    baselines = compute_replacement_baselines(players, CFG)
    players = players.copy()
    players["replacement_points"] = players["position"].map(baselines)
    players["vor"] = players["points"] - players["replacement_points"]
    out = apply_scarcity_boosts(players, CFG)  # CFG has no scarcity_boosts key
    assert list(out["vor"]) == list(players["vor"])


def test_compute_vor_can_skip_scarcity_boost_for_historical_scoring():
    players = _fake_position_pool("QB", 25)
    out = compute_vor(players, CFG_WITH_QB_BOOST, apply_scarcity=False)
    top_qb = out[out["name"] == "QB0"].iloc[0]
    assert top_qb["vor"] == top_qb["points"] - top_qb["replacement_points"]  # unboosted

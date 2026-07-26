import pandas as pd

from optimizer.tiers import assign_tiers

CFG = {"tiering": {"gap_threshold_stdevs": 1.0}}


def test_assign_tiers_splits_on_big_gap():
    # gaps: 10, 10, 60, 10, 10 -> mean=20, pstdev=20 -> threshold=40
    # only the 60-point gap (between 80 and 20) exceeds 40, so that's the one tier break
    players = pd.DataFrame({
        "name": ["A", "B", "C", "D", "E", "F"],
        "position": "WR",
        "vor": [100, 90, 80, 20, 10, 0],
    })
    out = assign_tiers(players, CFG)
    tiers_by_name = dict(zip(out["name"], out["tier"]))
    assert tiers_by_name["A"] == 1
    assert tiers_by_name["B"] == 1
    assert tiers_by_name["C"] == 1
    assert tiers_by_name["D"] == 2
    assert tiers_by_name["E"] == 2
    assert tiers_by_name["F"] == 2


def test_tiers_computed_independently_per_position():
    players = pd.DataFrame({
        "name": ["QB1", "QB2", "WR1", "WR2"],
        "position": ["QB", "QB", "WR", "WR"],
        "vor": [100, 0, 100, 0],
    })
    out = assign_tiers(players, CFG)
    # Each position only has 2 players -> 1 gap each -> mean==gap -> threshold==gap -> no break -> both tier 1
    assert set(out["tier"]) == {1}


def test_single_player_position_gets_tier_one():
    players = pd.DataFrame({"name": ["K1"], "position": ["K"], "vor": [42.0]})
    out = assign_tiers(players, CFG)
    assert out.iloc[0]["tier"] == 1

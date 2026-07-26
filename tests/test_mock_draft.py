import pandas as pd

from optimizer.mock_draft import build_snake_order, pick_for_bot, total_rounds_for


def test_build_snake_order_alternates_direction_each_round():
    # 3 teams, 2 rounds: round 0 forward, round 1 reversed
    order = build_snake_order(num_teams=3, total_rounds=2)
    assert order == [0, 1, 2, 2, 1, 0]


def test_total_rounds_for_sums_roster_slots():
    assert total_rounds_for({"QB": 2, "WR": 4, "RB": 3, "TE": 1, "K": 2, "DEF": 1, "BN": 1}) == 14


ROSTER_SLOTS = {"QB": 1, "RB": 1, "BN": 1}

RANKED_POOL = pd.DataFrame({
    "name": ["TopWR", "MidQB", "MidRB"],
    "position": ["WR", "QB", "RB"],
    "vor": [100, 90, 80],
})


def test_bot_prefers_needed_starter_position_over_higher_ranked_non_need():
    # Team needs QB and RB (nothing drafted yet); TopWR outranks everyone but isn't a starter need
    pick = pick_for_bot(RANKED_POOL, team_positions=[], roster_slots=ROSTER_SLOTS)
    assert pick["name"] == "MidQB"


def test_bot_moves_to_next_open_starter_need():
    pick = pick_for_bot(RANKED_POOL, team_positions=["QB"], roster_slots=ROSTER_SLOTS)
    assert pick["name"] == "MidRB"


def test_bot_falls_back_to_best_available_once_starters_filled():
    # QB and RB starters both filled -> only BN left -> best overall regardless of position
    pick = pick_for_bot(RANKED_POOL, team_positions=["QB", "RB"], roster_slots=ROSTER_SLOTS)
    assert pick["name"] == "TopWR"

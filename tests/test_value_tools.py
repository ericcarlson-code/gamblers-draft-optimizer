import pandas as pd

from optimizer.value_tools import evaluate_trade, stack_combo_summary, team_stack_summary, team_totals

BOARD = pd.DataFrame({
    "name": ["A", "B", "C", "D", "E"],
    "position": ["QB", "RB", "WR", "TE", "K"],
    "vor": [50.0, 30.0, 20.0, 10.0, 5.0],
    "drafted_by": ["Me", "Me", "Opponent 1", "", "Opponent 1"],
})

STACK_BOARD = pd.DataFrame({
    "name": ["Lions QB", "Lions RB", "Lions WR", "Lions TE", "Lions K", "Bears QB", "Bears RB"],
    "position": ["QB", "RB", "WR", "TE", "K", "QB", "RB"],
    "team": ["DET", "DET", "DET", "DET", "DET", "CHI", "CHI"],
    "vor": [40.0, 35.0, 30.0, 25.0, 2.0, 20.0, 5.0],
})

COMBO_BOARD = pd.DataFrame({
    "name": ["Lions QB", "Lions WR1", "Lions WR2", "Lions RB", "Bears QB", "Bears WR1"],
    "position": ["QB", "WR", "WR", "RB", "QB", "WR"],
    "team": ["DET", "DET", "DET", "DET", "CHI", "CHI"],
    "vor": [40.0, 30.0, 20.0, 15.0, 10.0, 5.0],
})


def test_team_totals_sums_vor_per_team_and_excludes_undrafted():
    totals = team_totals(BOARD)
    assert set(totals["team"]) == {"Me", "Opponent 1"}
    me_row = totals[totals["team"] == "Me"].iloc[0]
    assert me_row["total_vor"] == 80.0
    assert me_row["players"] == 2

    opp_row = totals[totals["team"] == "Opponent 1"].iloc[0]
    assert opp_row["total_vor"] == 25.0
    assert opp_row["players"] == 2


def test_team_totals_sorted_best_first():
    totals = team_totals(BOARD)
    assert totals.iloc[0]["team"] == "Me"  # 80 VOR beats Opponent 1's 25


def test_team_totals_empty_when_nothing_drafted():
    board = BOARD.copy()
    board["drafted_by"] = ""
    totals = team_totals(board)
    assert totals.empty


def test_evaluate_trade_favors_side_receiving_more_vor():
    # Side A gives up A (50 vor) and gets B... wait, evaluate_trade takes what each side GIVES UP.
    # Side A gives player A (50 vor), Side B gives players C+D (20+10=30 vor) -> B gives less, favors A? No:
    # net_for_a = vor B gives - vor A gives = 30 - 50 = -20 -> favors B (A gave up more than it got)
    result = evaluate_trade(BOARD, side_a_players=["A"], side_b_players=["C", "D"])
    assert result["side_a_vor_given"] == 50.0
    assert result["side_b_vor_given"] == 30.0
    assert result["net_for_a"] == -20.0
    assert result["verdict"] == "Favors Side B"


def test_evaluate_trade_even():
    result = evaluate_trade(BOARD, side_a_players=["A"], side_b_players=["B", "C"])  # 50 vs 30+20=50
    assert result["verdict"] == "Even trade"


def test_team_stack_ranks_best_offense_first():
    # DET's top 4 by VOR: 40+35+30+25=130 (Lions K excluded, only top 4 counted).
    # CHI: 20+5=25 (only 2 players total).
    stacks = team_stack_summary(STACK_BOARD, top_n=4)
    assert stacks.iloc[0]["team"] == "DET"
    assert stacks.iloc[0]["stack_vor"] == 130.0
    assert stacks.iloc[1]["team"] == "CHI"
    assert stacks.iloc[1]["stack_vor"] == 25.0


def test_team_stack_top_n_excludes_weakest_players():
    stacks = team_stack_summary(STACK_BOARD, top_n=4)
    det_players = stacks[stacks["team"] == "DET"].iloc[0]["players"]
    assert "Lions K" not in det_players  # 5th-best DET player, cut by top_n=4
    assert "Lions QB" in det_players


def test_team_stack_empty_board():
    empty = pd.DataFrame(columns=["name", "position", "team", "vor"])
    stacks = team_stack_summary(empty)
    assert stacks.empty


def test_stack_combo_cross_position_pairs_top_player_at_each_slot():
    combos = stack_combo_summary(COMBO_BOARD, "QB", "WR")
    det = combos[combos["team"] == "DET"].iloc[0]
    assert det["combo_vor"] == 70.0  # Lions QB (40) + best Lions WR (30, not 20)
    assert "Lions QB" in det["player_1"]
    assert "Lions WR1" in det["player_2"]


def test_stack_combo_ranks_best_pairing_first():
    combos = stack_combo_summary(COMBO_BOARD, "QB", "WR")
    assert combos.iloc[0]["team"] == "DET"  # 70 beats CHI's 10+5=15


def test_stack_combo_same_position_pairs_top_two():
    combos = stack_combo_summary(COMBO_BOARD, "WR", "WR")
    det = combos[combos["team"] == "DET"].iloc[0]
    assert det["combo_vor"] == 50.0  # top 2 Lions WRs: 30+20
    # CHI only has 1 WR, so it can't form a WR+WR pair and is excluded
    assert "CHI" not in set(combos["team"])


def test_stack_combo_excludes_team_missing_a_position():
    # No team here has a TE, so every team should be excluded
    combos = stack_combo_summary(COMBO_BOARD, "QB", "TE")
    assert combos.empty

import pandas as pd

from optimizer.value_tools import evaluate_trade, team_totals

BOARD = pd.DataFrame({
    "name": ["A", "B", "C", "D", "E"],
    "position": ["QB", "RB", "WR", "TE", "K"],
    "vor": [50.0, 30.0, 20.0, 10.0, 5.0],
    "drafted_by": ["Me", "Me", "Opponent 1", "", "Opponent 1"],
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

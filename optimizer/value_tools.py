"""
Team valuation and trade evaluation, both built on the same VOR numbers
the draft board already ranks players by -- no separate value model.
"""
import pandas as pd


def team_totals(board: pd.DataFrame, team_column: str = "drafted_by") -> pd.DataFrame:
    """Total VOR and player count per team label present in team_column.
    Rows with an empty team label (undrafted players) are excluded. Sorted
    by total VOR descending, i.e. best team first."""
    drafted = board[board[team_column] != ""]
    if drafted.empty:
        return pd.DataFrame(columns=["team", "total_vor", "players"])

    totals = (
        drafted.groupby(team_column)
        .agg(total_vor=("vor", "sum"), players=("name", "count"))
        .reset_index()
        .rename(columns={team_column: "team"})
        .sort_values("total_vor", ascending=False)
        .reset_index(drop=True)
    )
    return totals


def evaluate_trade(board: pd.DataFrame, side_a_players: list[str], side_b_players: list[str]) -> dict:
    """VOR given up by each side of a trade. net_for_a is what Side A gains
    (positive = good for A); net_for_b is the mirror for Side B."""
    side_a_vor = float(board.loc[board["name"].isin(side_a_players), "vor"].sum())
    side_b_vor = float(board.loc[board["name"].isin(side_b_players), "vor"].sum())
    net_for_a = side_b_vor - side_a_vor
    net_for_b = side_a_vor - side_b_vor

    if abs(net_for_a) < 1e-6:
        verdict = "Even trade"
    elif net_for_a > 0:
        verdict = "Favors Side A"
    else:
        verdict = "Favors Side B"

    return {
        "side_a_vor_given": side_a_vor,
        "side_b_vor_given": side_b_vor,
        "net_for_a": net_for_a,
        "net_for_b": net_for_b,
        "verdict": verdict,
    }

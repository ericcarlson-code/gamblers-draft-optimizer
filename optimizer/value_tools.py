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


def team_stack_summary(board: pd.DataFrame, top_n: int = 4) -> pd.DataFrame:
    """Combined value of each NFL team's best players (by the 'team' column,
    e.g. 'DET') -- not to be confused with team_totals, which groups by
    fantasy-draft-team ('drafted_by'). A team whose top players all rank
    highly is a good stacking target: their offense is collectively strong,
    so multiple of its players are likely to be valuable at once (e.g. a
    dominant offense's QB, WR1, and RB1 all having big seasons together).
    Only the top_n highest-VOR players per team count toward the total, so
    one team's deep bench doesn't outrank another team's few stars."""
    rows = []
    for team, group in board.groupby("team"):
        if not team:
            continue
        top = group.sort_values("vor", ascending=False).head(top_n)
        rows.append({
            "team": team,
            "stack_vor": float(top["vor"].sum()),
            "player_count": len(top),
            "players": ", ".join(f"{r['name']} ({r['position']})" for _, r in top.iterrows()),
        })

    result = pd.DataFrame(rows, columns=["team", "stack_vor", "player_count", "players"])
    if result.empty:
        return result
    return result.sort_values("stack_vor", ascending=False).reset_index(drop=True)


def stack_combo_summary(board: pd.DataFrame, position_a: str, position_b: str) -> pd.DataFrame:
    """For each NFL team, the best 2-player combo at the given position slots
    (e.g. 'QB','WR' -> that team's top QB paired with its top WR). If both
    positions are the same (e.g. 'WR','WR'), pairs the team's top 2 at that
    position instead of doubling up one player. Teams missing a player at
    either slot are excluded. Sorted by combined VOR descending -- these are
    the specific same-team pairings most worth targeting together, one level
    more specific than team_stack_summary's whole-team view."""
    rows = []
    for team, group in board.groupby("team"):
        if not team:
            continue

        if position_a == position_b:
            candidates = group[group["position"] == position_a].sort_values("vor", ascending=False)
            if len(candidates) < 2:
                continue
            first, second = candidates.iloc[0], candidates.iloc[1]
        else:
            a_candidates = group[group["position"] == position_a].sort_values("vor", ascending=False)
            b_candidates = group[group["position"] == position_b].sort_values("vor", ascending=False)
            if a_candidates.empty or b_candidates.empty:
                continue
            first, second = a_candidates.iloc[0], b_candidates.iloc[0]

        rows.append({
            "team": team,
            "combo_vor": float(first["vor"] + second["vor"]),
            "player_1": f"{first['name']} ({first['position']})",
            "player_2": f"{second['name']} ({second['position']})",
        })

    result = pd.DataFrame(rows, columns=["team", "combo_vor", "player_1", "player_2"])
    if result.empty:
        return result
    return result.sort_values("combo_vor", ascending=False).reset_index(drop=True)


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

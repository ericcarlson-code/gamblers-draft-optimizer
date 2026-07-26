"""
Value Over Replacement (VOR).

Raw projected points overrate positions with high scoring but shallow
depth requirements. VOR fixes that by subtracting a "replacement level"
baseline per position -- the points of a freely available bench/waiver
player at that position -- so players are ranked by how much better than
replacement they are, not by raw points.

The replacement rank for a position is teams * starters-per-position at
that position, both read from league_config.json (num_teams and
roster.slots), e.g. in a 10-team league starting 2 QBs, the 20th-best
QB is the replacement baseline: below that, any QB is essentially as
good as what you could get off waivers. This is what makes 2-QB/2-K
scarcity show up correctly instead of using a generic 1-QB league's math.
"""
import pandas as pd

from optimizer.schema import VALID_POSITIONS


def replacement_rank_for_position(position: str, cfg: dict) -> int:
    num_teams = cfg["league"]["num_teams"]
    starters = cfg["roster"]["slots"].get(position, 0)
    return num_teams * starters


def compute_replacement_baselines(players: pd.DataFrame, cfg: dict) -> dict[str, float]:
    """One baseline points value per position, from the ranked player list."""
    baselines: dict[str, float] = {}
    for position in VALID_POSITIONS:
        pool = players.loc[players["position"] == position, "points"].sort_values(ascending=False)
        rank = replacement_rank_for_position(position, cfg)
        if rank <= 0 or pool.empty:
            baselines[position] = 0.0
        elif rank > len(pool):
            # Not enough projected players at this position to fill every league
            # starting slot -- fall back to the worst available player's points.
            baselines[position] = float(pool.iloc[-1])
        else:
            baselines[position] = float(pool.iloc[rank - 1])
    return baselines


def compute_vor(players: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Adds 'replacement_points' and 'vor' columns; returns sorted by vor descending.
    `players` must have at least 'position' and 'points' columns."""
    baselines = compute_replacement_baselines(players, cfg)
    out = players.copy()
    out["replacement_points"] = out["position"].map(baselines).fillna(0.0)
    out["vor"] = out["points"] - out["replacement_points"]
    return out.sort_values("vor", ascending=False).reset_index(drop=True)

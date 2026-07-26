"""
Mock draft simulation.

Bot opponents draft the best available player at a position they still
need a starter for (falling back to best-player-available once their
starting lineup is full, since any remaining pick just fills a bench
slot). This doesn't need any external data -- it reuses the same
VOR-ranked pool the live Draft Board uses, so a mock draft reflects
whatever league settings are currently configured.
"""
from collections import Counter

import pandas as pd


def build_snake_order(num_teams: int, total_rounds: int) -> list[int]:
    """0-indexed team turn order across a full snake draft (odd rounds reversed)."""
    order: list[int] = []
    for rnd in range(total_rounds):
        round_order = list(range(num_teams)) if rnd % 2 == 0 else list(range(num_teams - 1, -1, -1))
        order.extend(round_order)
    return order


def total_rounds_for(roster_slots: dict) -> int:
    return sum(roster_slots.values())


def pick_for_bot(available_ranked: pd.DataFrame, team_positions: list[str], roster_slots: dict) -> pd.Series:
    """`available_ranked` must already be sorted best-to-worst (e.g. by VOR).
    Picks the top-ranked player at a position the team still needs a starter for;
    once every starter slot is filled, picks the top-ranked player overall (bench)."""
    counts = Counter(team_positions)
    starter_positions = [pos for pos, total in roster_slots.items() if pos != "BN" and counts.get(pos, 0) < total]

    if starter_positions:
        eligible = available_ranked[available_ranked["position"].isin(starter_positions)]
        if not eligible.empty:
            return eligible.iloc[0]

    return available_ranked.iloc[0]

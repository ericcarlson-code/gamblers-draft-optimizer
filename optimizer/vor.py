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


def apply_scarcity_boosts(out: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Multiplies a position's VOR by a factor that decays from
    max_multiplier (at that position's #1-ranked VOR) down to 1.0x by
    taper_to_rank, per league_config.json's scarcity_boosts section.

    VOR-over-replacement alone assumes marginal value is what drives real
    draft behavior, but a position with only a few required starters
    leaguewide relative to its startable NFL pool (this league's QB, at
    2-per-team) sees a real "run" in actual drafts that a static replacement
    baseline doesn't capture (see league_config.json's scarcity_boosts note
    for the real historical-draft evidence). This still ranks purely by VOR
    -- it corrects VOR itself, not a blend with ADP or any other signal."""
    boosts = cfg.get("scarcity_boosts", {})
    # reset_index is required: callers may pass a DataFrame built via
    # pd.concat() with duplicate index labels across positions (e.g. QB's
    # index 0 and TE's index 0 coexisting) -- .at[idx, ...] below would then
    # mutate every row sharing that label, not just the intended one.
    out = out.reset_index(drop=True)
    for position, params in boosts.items():
        if not isinstance(params, dict):
            continue  # skip the "note" string
        max_mult = params["max_multiplier"]
        taper = params["taper_to_rank"]
        pos_order = out.loc[out["position"] == position, "vor"].sort_values(ascending=False)
        for rank, idx in enumerate(pos_order.index, start=1):
            frac = max(0.0, (taper - rank) / (taper - 1)) if taper > 1 else 0.0
            out.at[idx, "vor"] *= 1 + (max_mult - 1) * frac
    return out


def compute_vor(players: pd.DataFrame, cfg: dict, apply_scarcity: bool = True) -> pd.DataFrame:
    """Adds 'replacement_points' and 'vor' columns; returns sorted by vor descending.
    `players` must have at least 'position' and 'points' columns.

    apply_scarcity gates apply_scarcity_boosts() -- on by default for the live
    2026 board and Mock Draft (the draft-day-recommendation use case the
    boost exists for), but should be passed False when scoring a PAST
    season's real results (Historical Review / Rankings' 2020-2025 views):
    those measure actual value delivered, not draft-day scarcity, and
    shouldn't be retroactively reshaped by a boost calibrated for the
    upcoming draft."""
    baselines = compute_replacement_baselines(players, cfg)
    out = players.copy()
    out["replacement_points"] = out["position"].map(baselines).fillna(0.0)
    out["vor"] = out["points"] - out["replacement_points"]
    if apply_scarcity:
        out = apply_scarcity_boosts(out, cfg)
    return out.sort_values("vor", ascending=False).reset_index(drop=True)

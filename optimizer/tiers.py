"""
Value-drop-off tiers per position.

Within one position's players (sorted best to worst by VOR), a new tier
starts wherever the point gap to the next player is unusually large
compared to the other gaps at that position. This flags real drop-offs
(e.g. "top 3 WRs are a clear tier above everyone else") without picking a
fixed group size, and the sensitivity is controlled by
league_config.json's tiering.gap_threshold_stdevs -- not hardcoded here.
"""
import statistics

import pandas as pd


def _tier_labels_for_group(vor_sorted_desc: list[float], gap_threshold_stdevs: float) -> list[int]:
    if len(vor_sorted_desc) <= 1:
        return [1] * len(vor_sorted_desc)

    gaps = [vor_sorted_desc[i] - vor_sorted_desc[i + 1] for i in range(len(vor_sorted_desc) - 1)]
    mean_gap = statistics.mean(gaps)
    stdev_gap = statistics.pstdev(gaps)
    threshold = mean_gap + gap_threshold_stdevs * stdev_gap

    tiers = [1]
    current_tier = 1
    for gap in gaps:
        if gap > threshold:
            current_tier += 1
        tiers.append(current_tier)
    return tiers


def assign_tiers(players: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Adds a 'tier' column (1 = best tier), computed independently per position.
    `players` must have 'position' and 'vor' columns (see vor.compute_vor)."""
    gap_threshold_stdevs = cfg["tiering"]["gap_threshold_stdevs"]
    out = players.copy()
    out["tier"] = 0

    for position, group in out.groupby("position"):
        ordered = group.sort_values("vor", ascending=False)
        tiers = _tier_labels_for_group(list(ordered["vor"]), gap_threshold_stdevs)
        out.loc[ordered.index, "tier"] = tiers

    return out

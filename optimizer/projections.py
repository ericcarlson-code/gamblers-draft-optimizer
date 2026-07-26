"""
Our own projection model: a recency-weighted average of a player's actual
counting stats over the last few real seasons (see scripts/fetch_actuals.py
for how those seasons are sourced). No external projections needed.

This is deliberately simple -- a transparent, editable weighted average,
not a black-box model -- and won't match a paid consensus-of-experts
service's accuracy. It's a fully-owned baseline with zero paywalls.
"""
import pandas as pd

from optimizer.schema import ALL_CANONICAL_FIELDS

STAT_FIELDS = [f for f in ALL_CANONICAL_FIELDS if f not in ("name", "position", "team")]

# Recency-weighted: most recent season counts most. Renormalized per player
# over whichever of these years they actually appear in (e.g. a rookie with
# only one season of data still gets a full-weight projection from it alone).
DEFAULT_WEIGHTS = {2025: 0.6, 2024: 0.25, 2023: 0.15}


def build_projection(history: dict[int, pd.DataFrame], weights: dict[int, float] = None) -> pd.DataFrame:
    """`history` maps season year -> that season's canonical-schema stats DataFrame
    (as produced by scripts/fetch_actuals.py). Returns one weighted-average row
    per player, in the same canonical schema, keyed by (name, position)."""
    weights = weights or DEFAULT_WEIGHTS

    frames = []
    for year, df in history.items():
        weight = weights.get(year, 0)
        if weight <= 0 or df.empty:
            continue
        tagged = df.copy()
        tagged["_year"] = year
        tagged["_weight"] = weight
        frames.append(tagged)

    if not frames:
        return pd.DataFrame(columns=["name", "position", "team"] + STAT_FIELDS)

    combined = pd.concat(frames, ignore_index=True)
    # Only average stat fields the source data actually has (e.g. fetch_actuals.py's
    # DEF rows only populate def_points_allowed -- other def_* fields stay 0).
    available_stat_fields = [f for f in STAT_FIELDS if f in combined.columns]

    # Only project players who appeared in the most recent season -- otherwise a
    # player who last played in an older included year (retired, out of the league)
    # would still show up with a phantom 2026 projection.
    most_recent_year = max(history.keys())
    current_players = history[most_recent_year][["name", "position", "team"]].drop_duplicates(
        subset=["name", "position"]
    )
    combined = combined.merge(current_players[["name", "position"]], on=["name", "position"], how="inner")

    # Use the team from whichever included season is most recent for that player
    # (covers a team change between the older seasons and the most recent one).
    current_team = (
        combined.sort_values("_year", ascending=False)
        .drop_duplicates(subset=["name", "position"])[["name", "position", "team"]]
    )

    def weighted_average(group: pd.DataFrame) -> pd.Series:
        total_weight = group["_weight"].sum()
        return pd.Series(
            {field: (group[field] * group["_weight"]).sum() / total_weight for field in available_stat_fields}
        )

    projected_stats = combined.groupby(["name", "position"], as_index=False).apply(
        weighted_average, include_groups=False
    )

    result = current_team.merge(projected_stats, on=["name", "position"], how="left")
    return result[["name", "position", "team"] + available_stat_fields].reset_index(drop=True)

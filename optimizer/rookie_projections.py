"""
Draft-capital rookie baseline: projects players with zero real NFL stat
history (this year's incoming rookie class) using where they were actually
picked in the NFL draft, instead of leaving them out of the rankings
entirely.

optimizer/projections.py's recency-weighted model needs a player to have
appeared in real stats before -- a true rookie has none, so they'd silently
vanish from Rankings/Mock Draft. Draft capital (round/pick) is consistently
the single most predictive signal for a rookie's opportunity in industry
rookie models (draft capital + college production + combine measurables);
this implements the draft-capital piece only -- college stats and combine
data are a separate data source and a bigger lift, deliberately out of
scope for now.

Method: for each of several past draft classes, join that class's real
draft slot to their OWN rookie-season actual stats (already fetched by
fetch_actuals.py), bucket by (round-group, position), and average the
canonical stat fields within each bucket. A new draft class can then be
slotted into that table by round and position to get a synthetic-but-
grounded stat line, which flows through score_player()/VOR exactly like
any other projected player -- no special-casing downstream.

Caveat worth knowing: fetch_actuals.py only pulls players who ranked highly
enough in a stat category to appear on ESPN's leaderboard pages. A Day 3
rookie who got zero meaningful playing time won't appear in that year's
actual-stats CSV at all -- they're simply absent, not a real zero. That
means each bucket's average is biased toward the rookies in that bucket who
*did* see the field, which typically overstates a "replacement level" Day 3
pick. Treat this baseline as optimistic for late-round rookies specifically.
"""
import pandas as pd

from optimizer.schema import ALL_CANONICAL_FIELDS

STAT_FIELDS = [f for f in ALL_CANONICAL_FIELDS if f not in ("name", "position", "team")]

# Round 1-3 get their own bucket (meaningfully different opportunity/investment
# at each); rounds 4-7 are pooled since Day 3 draft slot barely differentiates
# fantasy outcome and pooling keeps the sample size from getting too thin.
ROUND_BUCKETS = {1: "1", 2: "2", 3: "3"}
DEFAULT_ROUND_BUCKET = "4-7"


def round_bucket(round_num: int) -> str:
    return ROUND_BUCKETS.get(int(round_num), DEFAULT_ROUND_BUCKET)


def build_round_position_baseline(
    draft_history: dict[int, pd.DataFrame],
    actual_stats_history: dict[int, pd.DataFrame],
) -> pd.DataFrame:
    """`draft_history` maps draft year -> that year's draft results DataFrame
    (name, position, round, pick, overall -- from fetch_draft_results.py).
    `actual_stats_history` maps the SAME years -> that year's actual-stats
    DataFrame (that draft class's rookie-season production).

    Returns one row per (round_bucket, position) with the mean of each
    canonical stat field across every historical rookie in that bucket who
    has a matching actual-stats row, plus an "ALL" round_bucket per position
    (every round pooled) to fall back on when a specific bucket has no data.
    """
    rows = []
    for year, draft_df in draft_history.items():
        stats_df = actual_stats_history.get(year)
        if stats_df is None or draft_df.empty or stats_df.empty:
            continue
        merged = draft_df.merge(stats_df, on=["name", "position"], how="inner")
        merged["round_bucket"] = merged["round"].apply(round_bucket)
        rows.append(merged)

    if not rows:
        return pd.DataFrame(columns=["round_bucket", "position"] + STAT_FIELDS)

    combined = pd.concat(rows, ignore_index=True)
    available_stat_fields = [f for f in STAT_FIELDS if f in combined.columns]

    specific = (
        combined.groupby(["round_bucket", "position"], as_index=False)[available_stat_fields]
        .mean()
    )
    pooled = combined.groupby(["position"], as_index=False)[available_stat_fields].mean()
    pooled["round_bucket"] = "ALL"

    return pd.concat([specific, pooled], ignore_index=True)[["round_bucket", "position"] + available_stat_fields]


def project_rookies(
    draft_class: pd.DataFrame,
    baseline: pd.DataFrame,
    already_projected: set[tuple[str, str]],
) -> pd.DataFrame:
    """`draft_class` is this year's draft results (name, position, round, ...).
    `already_projected` is the set of (name, position) already covered by the
    real-stats veteran model -- e.g. a player drafted last year who already
    has a rookie season on record. Returns one synthetic-stat-line row per
    remaining true rookie, using their round bucket's baseline (falling back
    to the position's pooled "ALL" baseline if that exact bucket has no data).
    """
    if draft_class.empty or baseline.empty:
        return pd.DataFrame(columns=["name", "position", "team"] + STAT_FIELDS)

    stat_fields = [f for f in baseline.columns if f not in ("round_bucket", "position")]
    baseline_lookup = {(r["round_bucket"], r["position"]): r for r in baseline.to_dict("records")}
    pooled_lookup = {r["position"]: r for r in baseline.to_dict("records") if r["round_bucket"] == "ALL"}

    out_rows = []
    seen = set()
    for _, pick in draft_class.iterrows():
        key = (pick["name"], pick["position"])
        if key in already_projected or key in seen:
            continue
        seen.add(key)

        bucket = round_bucket(pick["round"])
        row = baseline_lookup.get((bucket, pick["position"])) or pooled_lookup.get(pick["position"])
        if row is None:
            continue  # no historical data at all for this position -- nothing to base a projection on

        out_row = {"name": pick["name"], "position": pick["position"], "team": pick.get("team", "")}
        for field in stat_fields:
            out_row[field] = row[field]
        out_rows.append(out_row)

    return pd.DataFrame(out_rows, columns=["name", "position", "team"] + stat_fields)

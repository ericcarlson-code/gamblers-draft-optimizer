"""
Depth-chart-aware damping for small-sample projections.

optimizer.projections.build_projection() extrapolates a player's per-game
stat rate straight to a full season regardless of how few real games that
rate is based on -- correct for an actual starter who simply missed time
(the low sample is injury-driven, not a signal about their role), but wrong
for a healthy backup/committee player whose few games happened because they
were buried on the depth chart. Concretely: Phil Mafah (RB, DAL) played 1
game in 2025 and got extrapolated to a full season of touches he was never
really in line for, while Javonte Williams -- the actual starter, with a
normal 16-game sample -- ranked lower on pure per-game rate. There is zero
committee/teammate awareness anywhere else in this codebase; this module is
a targeted correction layered on top of build_projection()'s own average,
not a replacement for it.

Depth chart data comes from nflreadpy (see requirements.txt for the
polars-lts-cpu workaround this needed on this dev machine). Imported lazily
inside the one function that needs it, so nothing else that imports
optimizer.projections (the Streamlit app, the test suite) is forced to
depend on nflreadpy just to run.
"""
import pandas as pd

# 1 = starter. Ranks are per (team, position group) -- see nflreadpy's
# load_depth_charts() pos_rank field.
DEPTH_RANK_DAMPING = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.3}
DEFAULT_DEEP_BENCH_DAMPING = 0.2

# Only damp when the real sample this season is this thin -- a player who
# played most of a season already has a robust rate regardless of any
# depth-chart shuffling since.
LOW_SAMPLE_GAMES_THRESHOLD = 4

DEPTH_CHART_POSITIONS = ("QB", "RB", "WR", "TE", "K")

# nflreadpy's own depth-chart feed tags kickers "PK", not "K" -- a different
# vocabulary than the canonical schema used everywhere else in this codebase
# (and than nflreadpy's OWN load_player_stats() output, which does use "K").
# Filter the raw feed on "PK", then normalize to "K" immediately below so
# every dict this module builds is keyed by the one canonical position code.
_RAW_POS_ALIASES = {"PK": "K"}
_RAW_DEPTH_CHART_POSITIONS = tuple(DEPTH_CHART_POSITIONS) + tuple(_RAW_POS_ALIASES)

_latest_snapshot_cache: dict[int, pd.DataFrame] = {}


def _load_latest_depth_chart(season: int) -> pd.DataFrame:
    """The LATEST depth-chart snapshot only, one row per (name, position) --
    depth charts shift all season and into the following offseason (e.g. a
    trade), so the most recent entry is the best signal for where a player
    really sits heading into the season being projected, not a frozen
    in-season moment. Cached per season since both load_depth_chart_ranks()
    and current_team_map() need it and it's one real network fetch."""
    if season not in _latest_snapshot_cache:
        import nflreadpy as nfl

        df = nfl.load_depth_charts(seasons=[season]).to_pandas()
        df = df[df["pos_abb"].isin(_RAW_DEPTH_CHART_POSITIONS)].copy()
        df["pos_abb"] = df["pos_abb"].replace(_RAW_POS_ALIASES)
        _latest_snapshot_cache[season] = df.sort_values("dt").drop_duplicates(
            subset=["player_name", "pos_abb"], keep="last"
        )
    return _latest_snapshot_cache[season]


def load_depth_chart_ranks(season: int) -> dict[tuple[str, str], int]:
    """Real, current depth-chart order per (name, position)."""
    latest = _load_latest_depth_chart(season)
    return {(row.player_name, row.pos_abb): int(row.pos_rank) for row in latest.itertuples()}


def current_team_map(season: int) -> dict[tuple[str, str], str]:
    """Real, current team per (name, position) -- corrects a player's team
    when it changed (trade/free agency) AFTER the most recent season's stats
    were recorded. build_projection() otherwise carries forward whichever
    team a player's stats CSV last showed them on, which goes stale the
    moment a player switches teams before the projection is built (e.g.
    Kenneth Walker III's stats CSV still shows SEA, his 2025 team, even
    though he signed with KC for 2026)."""
    latest = _load_latest_depth_chart(season)
    return {(row.player_name, row.pos_abb): row.team for row in latest.itertuples()}


def games_played_map(actual_stats: pd.DataFrame) -> dict[tuple[str, str], float]:
    """(name, position) -> games_played, from one season's canonical-schema
    actual-stats DataFrame (scripts/fetch_actuals_nflreadpy.py output)."""
    if "games_played" not in actual_stats.columns:
        return {}
    return {
        (row.name, row.position): row.games_played
        for row in actual_stats.itertuples()
        if row.position in DEPTH_CHART_POSITIONS
    }


def apply_depth_chart_damping(
    projection: pd.DataFrame,
    depth_ranks: dict[tuple[str, str], int],
    recent_games_played: dict[tuple[str, str], float],
    stat_fields: list[str],
    games_threshold: int = LOW_SAMPLE_GAMES_THRESHOLD,
) -> pd.DataFrame:
    """Scales down a projected stat line for a player whose extrapolation is
    both (a) built from a thin real sample this season and (b) not the real
    depth-chart starter -- leaves everyone else (real starters, and anyone
    with a normal-sized sample regardless of depth chart rank) untouched."""
    projection = projection.copy()
    for idx, row in projection.iterrows():
        key = (row["name"], row["position"])
        games = recent_games_played.get(key)
        if games is None or games >= games_threshold:
            continue
        rank = depth_ranks.get(key)
        if rank is None or rank <= 1:
            continue
        factor = DEPTH_RANK_DAMPING.get(rank, DEFAULT_DEEP_BENCH_DAMPING)
        for field in stat_fields:
            if field in projection.columns:
                projection.at[idx, field] = projection.at[idx, field] * factor
    return projection

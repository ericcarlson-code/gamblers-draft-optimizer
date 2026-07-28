import pandas as pd

from optimizer.depth_chart import apply_depth_chart_damping, games_played_map
from optimizer.schema import ALL_CANONICAL_FIELDS

STAT_FIELDS = [f for f in ALL_CANONICAL_FIELDS if f not in ("name", "position", "team")]


def _projection_row(name, position, team, rush_yds=0.0, rush_td=0.0):
    base = {f: 0.0 for f in STAT_FIELDS}
    base.update(rush_yds=rush_yds, rush_td=rush_td)
    return {"name": name, "position": position, "team": team, **base}


def test_low_sample_backup_gets_damped():
    # Phil Mafah: 1 real game, RB4 on the depth chart -- extrapolated stats
    # should be scaled down, not trusted at full value.
    projection = pd.DataFrame([_projection_row("Phil Mafah", "RB", "DAL", rush_yds=306.0, rush_td=17.0)])
    depth_ranks = {("Phil Mafah", "RB"): 4}
    recent_games = {("Phil Mafah", "RB"): 1}

    result = apply_depth_chart_damping(projection, depth_ranks, recent_games, STAT_FIELDS)
    row = result[result["name"] == "Phil Mafah"].iloc[0]

    assert row["rush_yds"] == 306.0 * 0.3
    assert row["rush_td"] == 17.0 * 0.3


def test_real_starter_never_damped_even_with_thin_sample():
    # An injured starter who only played a couple games should NOT be
    # punished for it -- the low sample there is injury-driven, not a
    # depth-chart signal.
    projection = pd.DataFrame([_projection_row("Star Starter", "RB", "DAL", rush_yds=200.0, rush_td=2.0)])
    depth_ranks = {("Star Starter", "RB"): 1}
    recent_games = {("Star Starter", "RB"): 2}

    result = apply_depth_chart_damping(projection, depth_ranks, recent_games, STAT_FIELDS)
    row = result[result["name"] == "Star Starter"].iloc[0]

    assert row["rush_yds"] == 200.0
    assert row["rush_td"] == 2.0


def test_normal_sample_size_never_damped_regardless_of_depth_rank():
    # A backup who played most of a full season already has a real,
    # non-noisy rate -- depth chart rank shouldn't retroactively punish it.
    projection = pd.DataFrame([_projection_row("Committee Back", "RB", "DAL", rush_yds=600.0, rush_td=4.0)])
    depth_ranks = {("Committee Back", "RB"): 3}
    recent_games = {("Committee Back", "RB"): 16}

    result = apply_depth_chart_damping(projection, depth_ranks, recent_games, STAT_FIELDS)
    row = result[result["name"] == "Committee Back"].iloc[0]

    assert row["rush_yds"] == 600.0
    assert row["rush_td"] == 4.0


def test_no_depth_chart_signal_leaves_projection_untouched():
    projection = pd.DataFrame([_projection_row("Mystery Player", "WR", "DAL", rush_yds=50.0)])
    result = apply_depth_chart_damping(projection, {}, {("Mystery Player", "WR"): 1}, STAT_FIELDS)
    row = result[result["name"] == "Mystery Player"].iloc[0]
    assert row["rush_yds"] == 50.0


def test_games_played_map_reads_canonical_columns():
    df = pd.DataFrame([
        {"name": "Phil Mafah", "position": "RB", "team": "DAL", "games_played": 1},
        {"name": "Some Kicker", "position": "K", "team": "DAL", "games_played": 17},
    ])
    result = games_played_map(df)
    assert result[("Phil Mafah", "RB")] == 1
    assert result[("Some Kicker", "K")] == 17  # K is damped too now (nflreadpy tags it "PK" upstream, normalized to "K")

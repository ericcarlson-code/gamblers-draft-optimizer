"""
Sanity checks for the scoring engine, verified by hand against
league_config.json's current values (Step 7 of the project plan).

If you edit league_config.json's scoring numbers, these hand-computed
expected values will no longer match -- that's expected, update them
alongside the config, or write scenario-specific configs inline instead.
"""
import math

from optimizer.config import load_config
from optimizer.scoring import score_player

cfg = load_config()


def test_nan_stat_value_treated_as_zero():
    # Reading a CSV with blank cells (e.g. a QB's field-goal columns) via pandas
    # produces float('nan'), not None -- must not propagate NaN through scoring.
    stats = {"position": "QB", "pass_yds": 300, "pass_td": 3, "rush_yds": float("nan")}
    result = score_player(stats, cfg)
    assert not math.isnan(result)
    assert result == 18.0  # rush_yds NaN treated as 0: 300/50 + 3*4 = 18


def test_qb_scoring():
    # 300 pass yds (6.0 pts @ 50/pt), 3 pass TD (12 pts @ 4/TD),
    # 20 rush yds (1.0 pt @ 20/pt), 1 rush TD (6 pts @ 6/TD) => 25.0
    stats = {
        "position": "QB",
        "pass_yds": 300,
        "pass_td": 3,
        "rush_yds": 20,
        "rush_td": 1,
    }
    assert score_player(stats, cfg) == 25.0


def test_rb_scoring():
    # 100 rush yds (5.0 pts), 1 rush TD (6 pts),
    # 3 rec / 30 rec yds (1.5 pts), 0 rec TD, reception value = 0 => 12.5
    stats = {
        "position": "RB",
        "rush_yds": 100,
        "rush_td": 1,
        "rec": 3,
        "rec_yds": 30,
        "rec_td": 0,
    }
    assert score_player(stats, cfg) == 12.5


def test_wr_scoring():
    # 120 rec yds (6.0 pts), 2 rec TD (12 pts) => 18.0
    stats = {
        "position": "WR",
        "rec": 8,
        "rec_yds": 120,
        "rec_td": 2,
    }
    assert score_player(stats, cfg) == 18.0


def test_kicker_scoring():
    # 1 PAT (1) + FG 0-19 (3, falls in the 0-39 bucket) + FG 20-29 (3, also 0-39 bucket)
    # + FG 40-49 (4) + FG 50+ (5) = 1 + 3 + 3 + 4 + 5 = 16
    stats = {
        "position": "K",
        "pat_made": 1,
        "fg_0_19": 1,
        "fg_20_29": 1,
        "fg_30_39": 0,
        "fg_40_49": 1,
        "fg_50_plus": 1,
    }
    assert score_player(stats, cfg) == 16.0


def test_defense_scoring():
    # TD (6) + safety (2) = 8 flat points.
    # 170 points allowed over a 17-game season = 10.0 pts allowed/game,
    # which falls in the 7-13 bucket (7 pts/game) => 7 * 17 = 119.
    # Total = 8 + 119 = 127.0
    stats = {
        "position": "DEF",
        "def_td": 1,
        "def_safety": 1,
        "def_points_allowed": 170,
    }
    assert score_player(stats, cfg) == 127.0


def test_defense_shutout_bucket():
    # 0 points allowed all season (17 games) => 0.0 pts allowed/game => shutout bucket (15 pts/game)
    stats = {
        "position": "DEF",
        "def_points_allowed": 0,
    }
    assert score_player(stats, cfg) == 15.0 * 17

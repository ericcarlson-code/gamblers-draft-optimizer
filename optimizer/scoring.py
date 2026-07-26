"""
Custom scoring engine.

score_player(stats, config) takes one player's stats (a dict using the
canonical field names from schema.py) plus the league config dict (loaded
from league_config.json) and returns the total fantasy points under this
league's rules. Every number that affects the result -- yards-per-point,
TD values, FG distance buckets, D/ST points-allowed buckets -- is read from
config, not hardcoded here, so editing league_config.json changes scoring
without touching this file.
"""
import math

from optimizer.schema import FG_INPUT_BANDS


def _get(stats: dict, field: str) -> float:
    value = stats.get(field, 0)
    if value is None or value == "":
        return 0.0
    value = float(value)
    return 0.0 if math.isnan(value) else value


def _bucket_points(value: float, buckets: list[dict], min_key: str, max_key: str) -> float:
    """Find the bucket whose [min_key, max_key] range contains value and return its points."""
    for bucket in buckets:
        if bucket[min_key] <= value <= bucket[max_key]:
            return bucket["points"]
    return 0.0


def score_passing(stats: dict, cfg: dict) -> float:
    passing_cfg = cfg["scoring"]["passing"]
    yds = _get(stats, "pass_yds")
    td = _get(stats, "pass_td")
    points = yds / passing_cfg["yards_per_point"] if passing_cfg["yards_per_point"] else 0.0
    points += td * passing_cfg["touchdown"]
    return points


def score_rushing(stats: dict, cfg: dict) -> float:
    rushing_cfg = cfg["scoring"]["rushing"]
    yds = _get(stats, "rush_yds")
    td = _get(stats, "rush_td")
    points = yds / rushing_cfg["yards_per_point"] if rushing_cfg["yards_per_point"] else 0.0
    points += td * rushing_cfg["touchdown"]
    return points


def score_receiving(stats: dict, cfg: dict) -> float:
    receiving_cfg = cfg["scoring"]["receiving"]
    yds = _get(stats, "rec_yds")
    td = _get(stats, "rec_td")
    rec = _get(stats, "rec")
    points = yds / receiving_cfg["yards_per_point"] if receiving_cfg["yards_per_point"] else 0.0
    points += td * receiving_cfg["touchdown"]
    points += rec * receiving_cfg.get("reception", 0)
    return points


def score_misc(stats: dict, cfg: dict) -> float:
    misc_cfg = cfg["scoring"]["misc"]
    points = _get(stats, "return_td") * misc_cfg["return_touchdown"]
    points += _get(stats, "off_fumble_return_td") * misc_cfg["offensive_fumble_return_touchdown"]
    points += _get(stats, "two_pt") * misc_cfg["two_point_conversion"]
    return points


def score_kicking(stats: dict, cfg: dict) -> float:
    kicking_cfg = cfg["scoring"]["kicking"]
    fg_buckets = kicking_cfg["field_goal_buckets"]
    points = _get(stats, "pat_made") * kicking_cfg["extra_point"]

    for field_name, band_min, band_max in FG_INPUT_BANDS:
        makes = _get(stats, field_name)
        if makes == 0:
            continue
        midpoint = (band_min + band_max) / 2
        points += makes * _bucket_points(midpoint, fg_buckets, "min_yards", "max_yards")

    return points


def score_defense(stats: dict, cfg: dict) -> float:
    defense_cfg = cfg["scoring"]["defense"]
    games = cfg["season"]["games_per_season"]

    points = _get(stats, "def_td") * defense_cfg["touchdown"]
    points += _get(stats, "def_safety") * defense_cfg["safety"]
    points += _get(stats, "def_return_td") * defense_cfg["return_touchdown"]
    points += _get(stats, "def_xp_returned") * defense_cfg["extra_point_returned"]

    season_pa = _get(stats, "def_points_allowed")
    if games:
        per_game_pa = season_pa / games
        per_game_bucket_points = _bucket_points(
            per_game_pa, defense_cfg["points_allowed_buckets"], "min_points", "max_points"
        )
        points += per_game_bucket_points * games

    return points


_POSITION_SCORERS = {
    "QB": lambda s, c: score_passing(s, c) + score_rushing(s, c) + score_misc(s, c),
    "RB": lambda s, c: score_rushing(s, c) + score_receiving(s, c) + score_misc(s, c),
    "WR": lambda s, c: score_rushing(s, c) + score_receiving(s, c) + score_misc(s, c),
    "TE": lambda s, c: score_rushing(s, c) + score_receiving(s, c) + score_misc(s, c),
    "K": score_kicking,
    "DEF": score_defense,
}


def score_player(stats: dict, cfg: dict) -> float:
    """Total fantasy points for one player's stat line under this league's rules."""
    position = stats.get("position")
    scorer = _POSITION_SCORERS.get(position)
    if scorer is None:
        raise ValueError(f"Unknown or missing position: {position!r}")
    return round(scorer(stats, cfg), 2)

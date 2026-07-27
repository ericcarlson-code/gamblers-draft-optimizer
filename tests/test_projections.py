import pandas as pd

from optimizer.projections import build_projection
from optimizer.schema import ALL_CANONICAL_FIELDS

STAT_FIELDS = [f for f in ALL_CANONICAL_FIELDS if f not in ("name", "position", "team")]


def _row(name, position, team, **stats):
    base = {f: 0.0 for f in STAT_FIELDS}
    base.update(stats)
    return {"name": name, "position": position, "team": team, **base}


def test_weighted_average_across_years():
    history = {
        2025: pd.DataFrame([_row("Josh Allen", "QB", "BUF", pass_yds=4000)]),
        2024: pd.DataFrame([_row("Josh Allen", "QB", "BUF", pass_yds=3000)]),
    }
    weights = {2025: 0.6, 2024: 0.4}
    result = build_projection(history, weights)

    row = result[result["name"] == "Josh Allen"].iloc[0]
    assert row["pass_yds"] == 4000 * 0.6 + 3000 * 0.4  # 3600
    assert row["team"] == "BUF"


def test_player_missing_from_some_years_renormalizes_over_available_years():
    # Only in 2025 (rookie) -- should get full weight from that year alone, not diluted.
    history = {
        2025: pd.DataFrame([_row("Rookie Guy", "WR", "DAL", rec_yds=1000)]),
        2024: pd.DataFrame([_row("Someone Else", "WR", "DAL", rec_yds=500)]),
    }
    weights = {2025: 0.6, 2024: 0.4}
    result = build_projection(history, weights)

    row = result[result["name"] == "Rookie Guy"].iloc[0]
    assert row["rec_yds"] == 1000.0


def test_player_absent_from_most_recent_year_is_excluded():
    # Only played in 2024 (retired/out of league by 2025) -- shouldn't get a phantom projection.
    history = {
        2025: pd.DataFrame([_row("Still Active", "RB", "SF", rush_yds=900)]),
        2024: pd.DataFrame([_row("Retired Guy", "RB", "SF", rush_yds=700)]),
    }
    weights = {2025: 0.6, 2024: 0.4}
    result = build_projection(history, weights)
    assert "Retired Guy" not in set(result["name"])
    assert "Still Active" in set(result["name"])


def test_uses_most_recent_teams_when_player_changed_teams():
    history = {
        2025: pd.DataFrame([_row("Traded Guy", "RB", "NYJ", rush_yds=800)]),
        2024: pd.DataFrame([_row("Traded Guy", "RB", "MIA", rush_yds=600)]),
    }
    weights = {2025: 0.6, 2024: 0.4}
    result = build_projection(history, weights)
    row = result[result["name"] == "Traded Guy"].iloc[0]
    assert row["team"] == "NYJ"


def test_injury_shortened_season_weighted_by_rate_not_raw_total():
    # A season where the player only suited up for a handful of games (injury)
    # shouldn't drag the projection down as if it were a full healthy season at
    # low output -- it should be weighted by per-game rate, same as a healthy year.
    history = {
        2025: pd.DataFrame([_row("Star RB", "RB", "SF", rush_yds=1200, games_played=17)]),
        2024: pd.DataFrame([_row("Star RB", "RB", "SF", rush_yds=200, games_played=3)]),  # injured, same ~pace
    }
    weights = {2025: 0.6, 2024: 0.4}
    result = build_projection(history, weights, games_per_season=17)

    row = result[result["name"] == "Star RB"].iloc[0]
    # Both seasons ran at roughly the same ~70 yds/game pace, so the rate-weighted
    # projection should land close to a full 17-game season at that pace (~1200),
    # not be dragged toward the 2024 season's low 200-yard *total*.
    assert row["rush_yds"] > 1100


def test_zero_games_season_is_excluded_not_treated_as_a_scoreless_full_season():
    # A season on IR the whole year (0 games, 0 stats) shouldn't count as
    # legitimate evidence of "zero production" -- it should drop out and
    # renormalize over the player's other seasons, like a missing year does.
    history = {
        2025: pd.DataFrame([_row("Comeback WR", "WR", "MIN", rec_yds=1000, games_played=17)]),
        2024: pd.DataFrame([_row("Comeback WR", "WR", "MIN", rec_yds=0, games_played=0)]),
    }
    weights = {2025: 0.6, 2024: 0.4}
    result = build_projection(history, weights, games_per_season=17)

    row = result[result["name"] == "Comeback WR"].iloc[0]
    assert row["rec_yds"] == 1000.0


def test_games_played_column_absent_falls_back_to_old_season_total_behavior():
    # No games_played column at all (e.g. an older cached CSV) -- should behave
    # exactly like the pre-fix season-total averaging, not error out.
    history = {
        2025: pd.DataFrame([_row("Vet TE", "TE", "KC", rec_yds=900)]),
        2024: pd.DataFrame([_row("Vet TE", "TE", "KC", rec_yds=600)]),
    }
    weights = {2025: 0.6, 2024: 0.4}
    result = build_projection(history, weights, games_per_season=17)
    row = result[result["name"] == "Vet TE"].iloc[0]
    assert row["rec_yds"] == 900 * 0.6 + 600 * 0.4

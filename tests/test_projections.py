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

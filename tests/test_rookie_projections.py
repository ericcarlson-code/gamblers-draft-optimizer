import pandas as pd

from optimizer.rookie_projections import build_round_position_baseline, project_rookies, round_bucket


def _draft_row(name, position, round_num, pick=1, overall=1, team="XXX"):
    return {"name": name, "position": position, "team": team, "round": round_num, "pick": pick, "overall": overall}


def _stat_row(name, position, **stats):
    from optimizer.schema import ALL_CANONICAL_FIELDS
    stat_fields = [f for f in ALL_CANONICAL_FIELDS if f not in ("name", "position", "team")]
    base = {f: 0.0 for f in stat_fields}
    base.update(stats)
    return {"name": name, "position": position, "team": "XXX", **base}


def test_round_bucket_groups_day3_together():
    assert round_bucket(1) == "1"
    assert round_bucket(2) == "2"
    assert round_bucket(3) == "3"
    assert round_bucket(4) == "4-7"
    assert round_bucket(7) == "4-7"


def test_baseline_averages_matched_rookies_within_a_bucket():
    draft_history = {
        2024: pd.DataFrame([_draft_row("RB One", "RB", 1), _draft_row("RB Two", "RB", 1)]),
    }
    actual_stats_history = {
        2024: pd.DataFrame([
            _stat_row("RB One", "RB", rush_yds=1000),
            _stat_row("RB Two", "RB", rush_yds=600),
        ]),
    }
    baseline = build_round_position_baseline(draft_history, actual_stats_history)
    row = baseline[(baseline["round_bucket"] == "1") & (baseline["position"] == "RB")].iloc[0]
    assert row["rush_yds"] == 800.0  # (1000 + 600) / 2


def test_baseline_only_includes_players_who_actually_appear_in_stats():
    # A drafted player who never showed up in the actual-stats CSV (didn't play
    # enough to make the leaderboard) shouldn't contribute a phantom zero season.
    draft_history = {
        2024: pd.DataFrame([_draft_row("Busted Pick", "WR", 4), _draft_row("Hit", "WR", 4)]),
    }
    actual_stats_history = {
        2024: pd.DataFrame([_stat_row("Hit", "WR", rec_yds=500)]),
    }
    baseline = build_round_position_baseline(draft_history, actual_stats_history)
    row = baseline[(baseline["round_bucket"] == "4-7") & (baseline["position"] == "WR")].iloc[0]
    assert row["rec_yds"] == 500.0  # only "Hit" contributed, not an average with a phantom 0


def test_project_rookies_uses_matching_round_bucket():
    draft_history = {2024: pd.DataFrame([_draft_row("Vet WR", "WR", 1)])}
    actual_stats_history = {2024: pd.DataFrame([_stat_row("Vet WR", "WR", rec_yds=900)])}
    baseline = build_round_position_baseline(draft_history, actual_stats_history)

    draft_class_2026 = pd.DataFrame([_draft_row("New WR", "WR", 1, team="DAL")])
    result = project_rookies(draft_class_2026, baseline, already_projected=set())

    row = result[result["name"] == "New WR"].iloc[0]
    assert row["rec_yds"] == 900.0
    assert row["team"] == "DAL"


def test_project_rookies_falls_back_to_pooled_baseline_for_empty_bucket():
    # Historical data only has round-1 WRs -- a round-5 WR should still get
    # something, via the pooled "ALL" fallback, not vanish.
    draft_history = {2024: pd.DataFrame([_draft_row("Vet WR", "WR", 1)])}
    actual_stats_history = {2024: pd.DataFrame([_stat_row("Vet WR", "WR", rec_yds=900)])}
    baseline = build_round_position_baseline(draft_history, actual_stats_history)

    draft_class_2026 = pd.DataFrame([_draft_row("Day3 WR", "WR", 5)])
    result = project_rookies(draft_class_2026, baseline, already_projected=set())

    row = result[result["name"] == "Day3 WR"].iloc[0]
    assert row["rec_yds"] == 900.0  # fell back to the pooled WR baseline


def test_project_rookies_skips_players_already_in_the_veteran_model():
    draft_history = {2024: pd.DataFrame([_draft_row("Vet RB", "RB", 1)])}
    actual_stats_history = {2024: pd.DataFrame([_stat_row("Vet RB", "RB", rush_yds=1000)])}
    baseline = build_round_position_baseline(draft_history, actual_stats_history)

    draft_class_2026 = pd.DataFrame([_draft_row("Already Projected", "RB", 1)])
    result = project_rookies(
        draft_class_2026, baseline, already_projected={("Already Projected", "RB")}
    )
    assert result.empty


def test_project_rookies_returns_empty_when_no_baseline_data_at_all():
    draft_class_2026 = pd.DataFrame([_draft_row("Mystery K", "K", 6)])
    result = project_rookies(draft_class_2026, pd.DataFrame(), already_projected=set())
    assert result.empty

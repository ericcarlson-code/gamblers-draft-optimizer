"""
Builds data/historical/2026_projections.csv -- our own projection model,
a recency-weighted average of real 2023-2025 stats (see optimizer/projections.py),
UNIONED with a draft-capital baseline projection for true rookies who have
zero real NFL stats to average (see optimizer/rookie_projections.py).

Run after fetch_actuals.py and fetch_draft_results.py have produced the year
CSVs this depends on:
    python scripts/fetch_actuals.py 2023   # ... 2024, 2025 (veteran model)
    python scripts/fetch_actuals.py 2020   # ... 2025 (rookie baseline training data)
    python scripts/fetch_draft_results.py 2020   # ... 2025 (rookie baseline training data)
    python scripts/fetch_draft_results.py 2026   # this year's incoming rookie class
    python scripts/build_2026_projections.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from optimizer.config import load_config  # noqa: E402
from optimizer.depth_chart import (  # noqa: E402
    apply_current_rank_damping,
    apply_depth_chart_damping,
    apply_team_change_damping,
    current_team_map,
    games_played_map,
    load_depth_chart_ranks,
)
from optimizer.projections import STAT_FIELDS, build_projection  # noqa: E402
from optimizer.rookie_projections import build_round_position_baseline, project_rookies  # noqa: E402
from optimizer.scoring import score_player  # noqa: E402
from scripts.build_rankings_artifact_data import CONSENSUS_NAME_ALIASES, _build_name_resolver  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"
VETERAN_MODEL_YEARS = [2023, 2024, 2025]
GAMES_SAMPLE_SEASON = 2025  # most recent completed season -- real games-played sample size
# The season being projected FOR, not the most recent completed one --
# nflreadpy's depth-chart feed already carries real, current preseason data
# for the upcoming season (confirmed 2026-08-02: Justin Fields shows KC,
# pos_rank 2, dated as recently as the day this was checked), which is
# needed for BOTH the team-label correction below and apply_team_change_
# damping. Using GAMES_SAMPLE_SEASON here instead was a real, confirmed bug:
# that season's depth-chart snapshot doesn't yet reflect a signing that
# happens later in that same offseason (Fields' 2025-season snapshot still
# showed NYJ, not KC), silently keeping the corrected damping from ever
# triggering for exactly the players it exists to catch.
CURRENT_DEPTH_CHART_SEASON = 2026
ROOKIE_BASELINE_TRAINING_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
ROOKIE_CLASS_YEAR = 2026


def _read_csv_if_exists(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        print(f"Missing {path}, skipping")
        return None
    return pd.read_csv(path)


def main() -> None:
    history = {}
    for year in VETERAN_MODEL_YEARS:
        df = _read_csv_if_exists(DATA_DIR / f"{year}_actual_stats.csv")
        if df is not None:
            history[year] = df

    games_per_season = load_config()["season"]["games_per_season"]
    veteran_projection = build_projection(history, games_per_season=games_per_season)

    if GAMES_SAMPLE_SEASON in history:
        try:
            depth_ranks = load_depth_chart_ranks(CURRENT_DEPTH_CHART_SEASON)
            recent_games = games_played_map(history[GAMES_SAMPLE_SEASON])
            veteran_projection = apply_depth_chart_damping(
                veteran_projection, depth_ranks, recent_games, STAT_FIELDS
            )
            print(f"Applied depth-chart damping using {len(depth_ranks)} real depth-chart entries")
        except Exception as e:  # network/data hiccup shouldn't break the whole projection build
            print(f"Depth-chart damping skipped ({e})")

        try:
            # QB/K only -- see apply_current_rank_damping's own docstring for
            # why current rank alone (independent of team change AND sample
            # size) is needed on top of the two passes above for these two
            # single-occupant-slot positions specifically.
            veteran_projection = apply_current_rank_damping(veteran_projection, depth_ranks, STAT_FIELDS)
            print("Applied current-rank QB/K damping")
        except Exception as e:
            print(f"Current-rank QB/K damping skipped ({e})")

        try:
            # A player's stats CSV team goes stale the moment they change
            # teams (trade/free agency) after their most recent season's
            # stats were recorded -- e.g. Kenneth Walker III's stats still
            # show SEA (his 2025 team) even after signing with KC for 2026.
            # The depth chart's own team field is real-time, not frozen to
            # last season.
            teams = current_team_map(CURRENT_DEPTH_CHART_SEASON)
            # Must run BEFORE the team-label correction below overwrites
            # row["team"] -- needs the OLD (stats-CSV) team still in place to
            # detect a real team change, which is the whole signal this
            # damping pass keys off (see apply_team_change_damping's own
            # docstring: a full-season starter who changed teams into a
            # backup role isn't caught by apply_depth_chart_damping's
            # thin-sample gate above).
            veteran_projection = apply_team_change_damping(veteran_projection, depth_ranks, teams, STAT_FIELDS)
            corrected = 0
            for idx, row in veteran_projection.iterrows():
                real_team = teams.get((row["name"], row["position"]))
                if real_team and real_team != row["team"]:
                    veteran_projection.at[idx, "team"] = real_team
                    corrected += 1
            print(f"Corrected {corrected} stale team assignments using current depth-chart data")
        except Exception as e:
            print(f"Team correction skipped ({e})")

    veteran_projection["projection_source"] = "real_stats"

    draft_history = {}
    actual_stats_history = {}
    for year in ROOKIE_BASELINE_TRAINING_YEARS:
        draft_df = _read_csv_if_exists(DATA_DIR / f"{year}_draft_results.csv")
        stats_df = _read_csv_if_exists(DATA_DIR / f"{year}_actual_stats.csv")
        if draft_df is not None and stats_df is not None:
            draft_history[year] = draft_df
            actual_stats_history[year] = stats_df

    draft_class = _read_csv_if_exists(DATA_DIR / f"{ROOKIE_CLASS_YEAR}_draft_results.csv")

    if draft_class is not None and draft_history:
        baseline = build_round_position_baseline(draft_history, actual_stats_history)
        already_projected = set(zip(veteran_projection["name"], veteran_projection["position"]))
        rookie_projection = project_rookies(draft_class, baseline, already_projected)
        rookie_projection["projection_source"] = "draft_capital_model"
        print(f"Draft-capital model projected {len(rookie_projection)} true rookies with no prior NFL stats")
    else:
        rookie_projection = pd.DataFrame(columns=veteran_projection.columns)
        print("No draft class / baseline data available -- skipping rookie projections")

    projection = pd.concat([veteran_projection, rookie_projection], ignore_index=True)

    # Trim the universe to the user's requested 500-player board: the real
    # ~468-player standard/non-PPR consensus ADP list (data/historical/
    # consensus_adp_2026.csv, see load_consensus_adp() in
    # build_rankings_artifact_data.py) plus all 32 D/ST teams -- that source
    # has zero defense coverage, so DEF rows are always kept regardless of
    # the consensus list. Uses the same suffix/accent-tolerant name matching
    # as the ADP/Flock joins (_build_name_resolver) rather than a bare-name
    # dict, since that mismatch class (e.g. "James Cook" vs "James Cook III")
    # has hit this codebase repeatedly.
    # CONSENSUS_NAME_ALIASES (imported above) handles cases where the
    # consensus source's own spelling diverges from our board's
    # nflreadpy-derived name in ways _build_name_resolver's suffix/accent
    # stripping can't catch (nicknames, dropped apostrophes) -- confirmed
    # real players missing this trim purely due to spelling, not genuine
    # data gaps. Shared with build_rankings_artifact_data.py's
    # load_consensus_adp()/load_consensus_rankings() so a player kept here
    # also gets real adp/consensus_overall_rank values, not a dash.
    before = len(projection)
    consensus_path = DATA_DIR / "consensus_adp_2026.csv"
    if consensus_path.exists():
        consensus_names = {CONSENSUS_NAME_ALIASES.get(n, n) for n in pd.read_csv(consensus_path)["name"]}
        resolver = _build_name_resolver({n: True for n in consensus_names})
        keep = projection.apply(
            lambda r: r["position"] == "DEF" or bool(resolver(r["name"])), axis=1
        )
        trimmed = projection[keep].reset_index(drop=True)

        # Kickers get the same real-team-coverage problem DEF used to have,
        # just less total (confirmed 2026-08-18: NYJ/NYG/BUF all had zero K
        # survive the consensus trim -- a generic consensus source doesn't
        # bother ranking every team's kicker, especially a team with an open
        # camp competition and no clear favorite yet). Unlike DEF (always
        # exactly one row per team, so "keep regardless of consensus" is
        # safe), a team can have several real kicker CANDIDATES in the
        # pre-trim universe (NYG had 4) -- keeping all of them would bloat
        # the board with deep camp-battle names nobody would draft. Instead:
        # only backfill a team that has ZERO kickers after the consensus
        # trim, adding back just that team's single highest-scoring
        # candidate (VOR doesn't exist yet at this stage of the pipeline --
        # that's computed later in build_rankings_artifact_data.py -- so
        # score_player() against the current scoring config is the
        # equivalent ranking signal available here) -- guarantees every
        # real team has at least one representative K without over-including
        # committee depth for teams that already have consensus coverage.
        all_k = projection[projection["position"] == "K"].copy()
        kept_k_teams = set(trimmed[trimmed["position"] == "K"]["team"])
        missing_k_teams = set(all_k["team"]) - kept_k_teams
        if missing_k_teams:
            score_cfg = load_config()
            all_k["_score"] = all_k.apply(lambda r: score_player(r.to_dict(), score_cfg), axis=1)
            backfill = (
                all_k[all_k["team"].isin(missing_k_teams)]
                .sort_values("_score", ascending=False)
                .drop_duplicates(subset="team", keep="first")
                .drop(columns="_score")
            )
            trimmed = pd.concat([trimmed, backfill], ignore_index=True)
            print(f"Backfilled {len(backfill)} kicker(s) with zero consensus coverage: {sorted(missing_k_teams)}")

        projection = trimmed
        print(f"Trimmed universe {before} -> {len(projection)} players (consensus list + all DEF + kicker backfill)")
    else:
        print(f"No {consensus_path} found -- skipping universe trim, keeping all {before} players")

    out_path = DATA_DIR / "2026_projections.csv"
    projection.to_csv(out_path, index=False)
    print(f"Wrote {len(projection)} projected players to {out_path}")


if __name__ == "__main__":
    main()

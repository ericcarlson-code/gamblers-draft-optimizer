"""
Builds the JSON data bundle for the published rankings Artifact (a static
HTML snapshot, separate from the live app). Scores every available year
(2020-2025 actual, plus the 2026 projection) under the CURRENT
league_config.json, and attaches each 2026-projection player's VOR
trajectory across whatever prior years they appeared in -- this is what
powers the trend sparkline that explains "why is this the projection."

Run from the repo root:
    python scripts/build_rankings_artifact_data.py <output_path.json>
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from optimizer.config import load_config
from optimizer.data_loader import apply_mapping
from optimizer.schema import ALL_CANONICAL_FIELDS
from optimizer.scoring import score_player
from optimizer.tiers import assign_tiers
from optimizer.vor import compute_vor

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"
HISTORY_YEARS = [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]

# ESPN's team abbreviations disagree with nflreadpy's (our board's own
# convention since the Phase 3 pipeline swap) for the Rams ("LAR" vs "LA")
# and Washington ("WSH" vs "WAS") -- same fixup duplicated in fetch_actuals.py/
# fetch_draft_results.py/fetch_player_images.py, applied there to NEW ESPN
# fetches. The 2020-2023 actual_stats CSVs were fetched before that fixup
# existed and still have the raw "LAR"/"WSH" codes baked in on disk (2024/2025
# are already normalized) -- normalizing here, at read time, fixes every
# consumer (team logos, team pages, badges) without needing to re-fetch or
# hand-edit four years of cached CSVs.
ESPN_TEAM_ABBR_FIXUPS = {"LAR": "LA", "WSH": "WAS"}


def td_points(stats: dict, cfg: dict) -> float:
    """Isolates just the touchdown-value portion of a player's score (mirrors
    the position-scorer structure in optimizer/scoring.py's _POSITION_SCORERS,
    but only the TD-value terms -- no yardage/reception/FG points). Used to
    compute what fraction of a player's total points come from touchdowns
    vs. yardage/volume -- a proxy for week-to-week boom/bust variance, and
    for why a QB and his own pass-catcher are unusually correlated: a passing
    TD and its receiver's receiving TD are literally the same play. Kickers
    have no TD-value terms (FG distance swings are a different kind of
    variance, not this one), so they always score 0 here."""
    position = stats.get("position")
    scoring_cfg = cfg["scoring"]
    if position == "QB":
        return stats.get("pass_td", 0) * scoring_cfg["passing"]["touchdown"] + stats.get("rush_td", 0) * scoring_cfg["rushing"]["touchdown"]
    if position in ("RB", "WR", "TE"):
        return stats.get("rush_td", 0) * scoring_cfg["rushing"]["touchdown"] + stats.get("rec_td", 0) * scoring_cfg["receiving"]["touchdown"]
    if position == "DEF":
        return stats.get("def_td", 0) * scoring_cfg["defense"]["touchdown"] + stats.get("def_return_td", 0) * scoring_cfg["defense"]["return_touchdown"]
    return 0.0


def td_counts(stats: dict) -> tuple[float, float, float]:
    """Projected touchdown COUNTS (not point value), split passing/rushing/
    receiving into 3 separate columns (previously rushing+receiving were
    blended into one -- Batch 2 item 8 asked to split them out; a QB's own
    rush_td already lived in the combined column before this split, still
    goes in the rush slot here, not receiving). QBs are the only position
    that can throw a TD. DEF's return/defensive TDs aren't really a
    "rushing" or "receiving" play -- bucketed into the rush slot as the
    closest fit (a return is a running play, just not from scrimmage),
    a judgment call flagged here rather than inventing a 4th column for it."""
    position = stats.get("position")
    if position == "QB":
        return stats.get("pass_td", 0), stats.get("rush_td", 0), 0.0
    if position in ("RB", "WR", "TE"):
        return 0.0, stats.get("rush_td", 0), stats.get("rec_td", 0)
    if position == "DEF":
        return 0.0, stats.get("def_td", 0) + stats.get("def_return_td", 0), 0.0
    return 0.0, 0.0, 0.0


def load_adp(year: int | None = None) -> dict[str, float]:
    """name -> real historical ADP for that draft season (see
    scripts/fetch_adp.py), from Fantasy Football Calculator's per-year
    archive (data/historical/{year}_adp.csv). Used only by the HISTORY_YEARS
    loop below -- the live 2026 board uses load_consensus_adp() instead (see
    that function's docstring). Returns {} (not an error) for years with no
    archived data -- currently just 2025 -- so those boards simply have no
    adp/value_vs_adp columns rather than failing the build."""
    path = DATA_DIR / f"{year}_adp.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    return dict(zip(df["name"], df["adp"]))


# The consensus source's own spelling occasionally diverges from our board's
# nflreadpy-derived name in ways _build_name_resolver's suffix/accent
# stripping can't catch (nicknames, dropped apostrophes) -- confirmed real
# players, not data gaps. Canonical home for this map: also imported by
# scripts/build_2026_projections.py for the universe trim, so a player kept
# in the board via this alias also gets a real adp/consensus_overall_rank
# instead of silently showing a dash. Mirrors the DST_NICKNAME_TO_FULL_NAME
# pattern used elsewhere in this codebase for the same class of problem.
CONSENSUS_NAME_ALIASES = {
    "Devon Achane": "De'Von Achane",
    "Joshua Palmer": "Josh Palmer",
    "Hollywood Brown": "Marquise Brown",
    "Zonovan Knight": "Bam Knight",
}


def load_consensus_adp() -> dict[str, float]:
    """name -> standard/non-PPR consensus ADP for the live 2026 board, from
    data/historical/consensus_adp_2026.csv (user-provided, averaged across
    Flock/Sleeper/ESPN/Yahoo/Underdog/CBS/FFPC -- replaces the old FFC
    2QB-format API and the old Flock PPR reference entirely, per the user's
    explicit "no PPR rankings anywhere on the site" instruction). Same
    {name: adp} shape as load_adp() so it's a drop-in replacement for the
    2026 board specifically; historical years keep using load_adp(year)."""
    path = DATA_DIR / "consensus_adp_2026.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    names = df["name"].map(lambda n: CONSENSUS_NAME_ALIASES.get(n, n))
    return dict(zip(names, df["adp"]))


_SUFFIX_RE = re.compile(r"\s+(Jr\.?|Sr\.?|II|III|IV|V)$", re.IGNORECASE)


def _strip_suffix(name: str) -> str:
    return _SUFFIX_RE.sub("", name).strip()


def _strip_accents(name: str) -> str:
    """Folds accented characters to their plain-ASCII equivalent (e.g.
    "Pineiro" vs "Piñeiro") -- a second real name-formatting mismatch
    class found the same way the suffix one was: nflreadpy (our board)
    strips the tilde, but Fantasy Football Calculator's ADP source keeps it,
    silently dropping "Eddy Piñeiro" from ADP entirely (found via a
    session 8 data-gap audit). Uses NFKD decomposition + dropping combining
    marks, the standard accent-fold technique."""
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))


def _build_name_resolver(lookup: dict[str, object]):
    """Our board's canonical name (from nflreadpy) doesn't always agree with
    an external source's own name on formatting -- two confirmed real-gap
    classes so far, both against BOTH Fantasy Football Calculator ADP and
    the Flock Fantasy reference data:
    (1) generational suffix: "James Cook" (board) vs "James Cook III" (FFC),
        "Travis Etienne" vs "Travis Etienne Jr.", "Aaron Jones" vs "Aaron
        Jones Sr.", "Kenneth Walker III" (board) vs "Kenneth Walker" (Flock).
    (2) accented characters: "Eddy Pineiro" (board, accent stripped) vs
        "Eddy Piñeiro" (FFC ADP, accent kept).
    All clearly fantasy-relevant players silently missing a match for a
    name-formatting reason, not a real data gap. Falls back first to a
    suffix-stripped match, then to a suffix+accent-folded match, each only
    when exactly one entry shares that key, so a genuine same-name-
    different-player collision still can't silently borrow the wrong value.
    Shared by ADP and Flock joins."""
    suffix_counts: dict[str, int] = {}
    suffix_value: dict[str, object] = {}
    folded_counts: dict[str, int] = {}
    folded_value: dict[str, object] = {}
    for name, value in lookup.items():
        suffix_key = _strip_suffix(name)
        suffix_counts[suffix_key] = suffix_counts.get(suffix_key, 0) + 1
        suffix_value[suffix_key] = value
        folded_key = _strip_accents(suffix_key)
        folded_counts[folded_key] = folded_counts.get(folded_key, 0) + 1
        folded_value[folded_key] = value

    def resolve(name: str):
        if name in lookup:
            return lookup[name]
        suffix_key = _strip_suffix(name)
        if suffix_counts.get(suffix_key) == 1:
            return suffix_value[suffix_key]
        folded_key = _strip_accents(suffix_key)
        if folded_counts.get(folded_key) == 1:
            return folded_value[folded_key]
        return None

    return resolve


def attach_adp_value(board: pd.DataFrame, adp_lookup: dict[str, float]) -> pd.DataFrame:
    """Adds 'adp' and 'value_vs_adp' columns. value_vs_adp compares a player's
    VOR to the VOR of whoever OUR OWN model ranks at their ADP slot -- e.g. if
    a player's ADP is 40 but our model's 40th-ranked player has much lower VOR,
    that player is a "value" relative to where the market is drafting them.
    Requires `board` already sorted by vor descending with no gaps in index
    (i.e. called after the same sort/overall_rank step as everything else)."""
    board = board.copy()
    board["adp"] = board["name"].map(_build_name_resolver(adp_lookup))
    n = len(board)

    def value_vs_adp(row):
        if pd.isna(row["adp"]) or n == 0:
            return None
        rank = min(max(int(round(row["adp"])), 1), n)
        expected_vor = board.iloc[rank - 1]["vor"]
        return round(row["vor"] - expected_vor, 1)

    board["value_vs_adp"] = board.apply(value_vs_adp, axis=1)
    return board


# How far our own overall_rank can diverge from the consensus's before it's
# flagged as "worth reviewing" rather than a normal scoring-model
# disagreement -- a judgment call, not a measured cutoff; raise it if it
# flags too many legitimate scoring-driven differences, lower it if real
# bugs are still slipping through unflagged. (Formerly compared against
# Flock's standalone PPR rankings; replaced with this multi-source non-PPR
# consensus per the user's explicit "no PPR rankings anywhere" instruction --
# same threshold value carried over unchanged.)
CONSENSUS_DIVERGENCE_THRESHOLD = 35


def load_consensus_rankings() -> dict[str, dict]:
    """name -> {overall_rank, pos_rank} from the standard/non-PPR consensus
    ADP dataset (data/historical/consensus_adp_2026.csv -- user-provided,
    averaged across Flock/Sleeper/ESPN/Yahoo/Underdog/CBS/FFPC). Used only
    as a display/sanity-check reference (see attach_consensus_reference),
    never blended into VOR or any actual ranking math. Returns {} if the
    file doesn't exist rather than erroring, since this reference is
    optional polish, not a build dependency."""
    path = DATA_DIR / "consensus_adp_2026.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    out = {}
    for row in df.itertuples():
        name = CONSENSUS_NAME_ALIASES.get(row.name, row.name)
        out[name] = {"overall_rank": int(row.rank), "pos_rank": int(row.pos_rank)}
    return out


def attach_consensus_reference(board: pd.DataFrame, consensus_lookup: dict[str, dict]) -> pd.DataFrame:
    """Adds 'consensus_overall_rank'/'consensus_pos_rank'/'consensus_diverges'
    -- a visible cross-check column, plus a flag for when our own ranking
    differs enough from the real multi-source consensus that it's more
    likely to be a data bug than a legitimate scoring-driven difference.
    Reference only -- never read by compute_vor/assign_tiers, and must stay
    that way."""
    board = board.copy()
    resolver = _build_name_resolver(consensus_lookup)
    consensus_data = board["name"].map(resolver)
    board["consensus_overall_rank"] = consensus_data.map(lambda d: d["overall_rank"] if d else None)
    board["consensus_pos_rank"] = consensus_data.map(lambda d: d["pos_rank"] if d else None)

    def diverges(row):
        if pd.isna(row["consensus_overall_rank"]):
            return False
        return abs(row["overall_rank"] - row["consensus_overall_rank"]) >= CONSENSUS_DIVERGENCE_THRESHOLD

    board["consensus_diverges"] = board.apply(diverges, axis=1)
    return board


RAW_STAT_FIELDS = [f for f in ALL_CANONICAL_FIELDS if f not in ("name", "position", "team")]


def score_file(
    path: Path,
    cfg: dict,
    adp_lookup: dict[str, float] | None = None,
    consensus_lookup: dict[str, dict] | None = None,
    apply_scarcity: bool = True,
) -> pd.DataFrame:
    raw = pd.read_csv(path)
    mapping = {f: f for f in ALL_CANONICAL_FIELDS if f in raw.columns}
    df = apply_mapping(raw, mapping)
    board = df[["name", "position", "team"]].copy()
    board["team"] = board["team"].replace(ESPN_TEAM_ABBR_FIXUPS)
    # Carried through for the player detail page (full stat line, not just
    # derived points/vor) -- must be added here, before compute_vor/
    # assign_tiers/sort_values, so the values stay aligned to the right
    # player through the row reordering that follows.
    for field in RAW_STAT_FIELDS:
        if field in df.columns:
            board[field] = df[field]
    # Only 2026_projections.csv has this column (real_stats vs draft_capital_model,
    # see optimizer/rookie_projections.py) -- actual-year stat files are all real.
    board["projection_source"] = raw["projection_source"] if "projection_source" in raw.columns else "real_stats"
    board["points"] = df.apply(lambda r: score_player(r.to_dict(), cfg), axis=1)
    td_pts = df.apply(lambda r: td_points(r.to_dict(), cfg), axis=1)
    board["td_dependency_pct"] = (td_pts / board["points"].where(board["points"] > 0)).fillna(0.0) * 100
    td_count_cols = df.apply(lambda r: td_counts(r.to_dict()), axis=1, result_type="expand")
    td_count_cols.columns = ["proj_pass_td", "proj_rush_td", "proj_rec_td"]
    board["proj_pass_td"] = td_count_cols["proj_pass_td"]
    board["proj_rush_td"] = td_count_cols["proj_rush_td"]
    board["proj_rec_td"] = td_count_cols["proj_rec_td"]
    board = compute_vor(board, cfg, apply_scarcity=apply_scarcity)
    board = assign_tiers(board, cfg)
    board = board.sort_values("vor", ascending=False).reset_index(drop=True)
    board["overall_rank"] = range(1, len(board) + 1)
    if adp_lookup:
        board = attach_adp_value(board, adp_lookup)
    else:
        board["adp"] = None
        board["value_vs_adp"] = None
    if consensus_lookup:
        board = attach_consensus_reference(board, consensus_lookup)
    else:
        board["consensus_overall_rank"] = None
        board["consensus_pos_rank"] = None
        board["consensus_diverges"] = False
    return board


def to_rows(board: pd.DataFrame) -> list[dict]:
    cols = [
        "overall_rank", "name", "position", "team", "points", "vor", "tier",
        "td_dependency_pct", "proj_pass_td", "proj_rush_td", "proj_rec_td",
    ]
    rows = board[cols].round(1).to_dict("records")
    stat_cols = [f for f in RAW_STAT_FIELDS if f in board.columns]
    for i, row in enumerate(rows):
        row["projection_source"] = board["projection_source"].iloc[i]
        adp = board["adp"].iloc[i]
        value_vs_adp = board["value_vs_adp"].iloc[i]
        row["adp"] = None if pd.isna(adp) else round(float(adp), 1)
        row["value_vs_adp"] = None if pd.isna(value_vs_adp) else float(value_vs_adp)
        consensus_rank = board["consensus_overall_rank"].iloc[i]
        consensus_pos_rank = board["consensus_pos_rank"].iloc[i]
        row["consensus_overall_rank"] = None if pd.isna(consensus_rank) else int(consensus_rank)
        row["consensus_pos_rank"] = None if pd.isna(consensus_pos_rank) else int(consensus_pos_rank)
        row["consensus_diverges"] = bool(board["consensus_diverges"].iloc[i])
        # Full raw stat line for the player detail page -- nested under its
        # own key rather than flattened, so it doesn't collide with any of
        # the derived column names above (e.g. Rankings' "TD%" column key).
        row["stats"] = {f: round(float(board[f].iloc[i]), 1) for f in stat_cols}
    return rows


def _week_boundaries(year: str) -> tuple[str, list[tuple[int, str]]] | None:
    """(week1_start_gameday, [(week_num, week_end_gameday), ...]) from
    data/historical/{year}_schedule.csv (scripts/fetch_schedule.py), sorted
    by week. None if that year has no schedule fetched yet."""
    path = DATA_DIR / f"{year}_schedule.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    week1_start = df[df["week"] == df["week"].min()]["gameday"].min()
    ends = df.groupby("week")["gameday"].max().reset_index().sort_values("week")
    return week1_start, list(ends.itertuples(index=False, name=None))


def _week_for_timestamp(timestamp: str, boundaries: tuple[str, list[tuple[int, str]]] | None) -> int | None:
    """Maps a transaction's ISO timestamp to the real NFL week it affects --
    a transaction made after week N's last game (Monday night, typically)
    but before week N+1's first game is a week-N+1 roster move (week N's
    lineups are already locked), matching the real fantasy-waiver
    convention. Week 0 = before the season's own Week 1 games start (real
    preseason/initial-roster activity, several of these exist in the actual
    2025 data -- late August entries). Plain ISO-date string comparison
    works correctly here since every date is the same YYYY-MM-DD format.
    None if no schedule data exists for this year at all (not every
    historical year will have one fetched)."""
    if boundaries is None:
        return None
    week1_start, week_ends = boundaries
    d = timestamp[:10]
    if d < week1_start:
        return 0
    for week_num, end in week_ends:
        if d <= end:
            return int(week_num)
    return int(week_ends[-1][0])  # after the last known game -- clamp to the final week


def load_transactions() -> dict[str, list[dict]]:
    """{year: [{timestamp, date_raw, team, type, week, player_added_resolved,
    player_added_nfl_team, player_added_pos, player_dropped_resolved,
    player_dropped_nfl_team, player_dropped_pos, counterparty_team}]}
    for every data/historical/{year}_transactions.csv on disk (Historical
    Data Phase 1 -- scripts/parse_transactions_paste.py). `type` is one of
    waiver/trade/commissioner_add/commissioner_drop -- commissioner actions
    are real rows but league-admin corrections, not owner decisions; kept in
    so a consumer CAN filter, but any behavioral-signal use (e.g. Mock
    Draft's team position affinity) must exclude them, per the project spec.
    `week` (real NFL week, 0 = preseason, see _week_for_timestamp) is null
    if that year has no {year}_schedule.csv fetched -- powers the
    Historical Review week-by-week roster feature, degrades to "no week
    data" rather than a wrong guess when schedule data isn't available.
    Drops raw_line/player_*_raw (parser-internal, not needed client-side)."""
    results: dict[str, list[dict]] = {}
    keep_cols = [
        "timestamp", "date_raw", "team", "type",
        "player_added_resolved", "player_added_nfl_team", "player_added_pos",
        "player_dropped_resolved", "player_dropped_nfl_team", "player_dropped_pos",
        "counterparty_team",
    ]
    for path in sorted(DATA_DIR.glob("*_transactions.csv")):
        year = path.stem.split("_")[0]
        df = pd.read_csv(path, keep_default_na=False)
        boundaries = _week_boundaries(year)
        rows = df[keep_cols].to_dict("records")
        for row, timestamp in zip(rows, df["timestamp"]):
            row["week"] = _week_for_timestamp(timestamp, boundaries)
        results[year] = rows
    return results


def load_fantasy_draft_results() -> dict[str, list[dict]]:
    """{year: [{overall_pick, round, pick_in_round, team, player, resolved}]}
    for every data/historical/{year}_fantasy_draft_results.csv on disk (this
    LEAGUE's real draft results, produced by scripts/parse_fantasy_draft_paste.py
    -- NOT {year}_draft_results.csv, which is the unrelated NFL rookie draft).
    Powers Historical Review's full-league draft grade (all 10 teams, not
    just a manually-entered single team) for any year this data exists for.
    `resolved` is False when the parser couldn't match the pasted name to
    that year's stats board (e.g. a real data gap like a missing kicker) --
    the frontend should show these as ungraded rather than silently omit
    them, since the pick itself is still real."""
    results: dict[str, list[dict]] = {}
    for path in sorted(DATA_DIR.glob("*_fantasy_draft_results.csv")):
        year = path.stem.split("_")[0]
        df = pd.read_csv(path, keep_default_na=False)
        picks = []
        for row in df.itertuples():
            player = row.player_resolved or row.player_raw
            picks.append({
                "overall_pick": int(row.overall_pick),
                "round": int(row.round),
                "pick_in_round": int(row.pick_in_round),
                "team": row.team,
                "player": player,
                "resolved": bool(row.player_resolved),
            })
        results[year] = picks
    return results


def load_schedule() -> dict[str, list[dict]]:
    """{week: [{gameday, gametime, away_team, home_team, location}]} for the
    live 2026 board, from data/historical/2026_schedule.csv
    (scripts/fetch_schedule.py). gametime is Eastern Time (nflreadpy's own
    convention) -- converted to the viewer's timezone client-side, not here.
    location is "Home" or "Neutral" (nflreadpy's flag for international
    games). {} if the file doesn't exist yet -- e.g. before the real
    schedule has been fetched for the season -- rather than erroring the
    whole build."""
    path = DATA_DIR / "2026_schedule.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, keep_default_na=False)
    by_week: dict[str, list[dict]] = {}
    for row in df.itertuples():
        by_week.setdefault(str(row.week), []).append({
            "gameday": row.gameday,
            "gametime": row.gametime,
            "away_team": row.away_team,
            "home_team": row.home_team,
            "location": row.location,
        })
    return by_week


# Per-position field order for WEEKLY_STATS' compact per-row arrays (see
# load_weekly_stats) -- mirrors site/rankings_template.html's own
# POSITION_STAT_FIELDS exactly (same fields, same order) so the frontend can
# decode a row using the same lookup it already has, and by hand-duplicating
# this must stay in sync with that constant the same way optimizer/vor.py's
# apply_scarcity_boosts already has to. A single UNIVERSAL field list (one
# order for every position, all 23 STAT_FIELDS) was tried first and measured
# at 11MB across the 11 embedded years -- this narrower, per-position list
# cuts that by roughly 3x with no loss of displayed detail, since it's
# exactly what the box-score card shows either way.
WEEKLY_POSITION_FIELDS = {
    "QB": ["pass_att", "pass_cmp", "pass_yds", "pass_td", "pass_int", "rush_yds", "rush_td", "two_pt"],
    "RB": ["carries", "rush_yds", "rush_td", "targets", "rec", "rec_yds", "rec_td", "two_pt"],
    "WR": ["targets", "rec", "rec_yds", "rec_td", "rush_yds", "rush_td", "two_pt"],
    "TE": ["targets", "rec", "rec_yds", "rec_td", "rush_yds", "rush_td", "two_pt"],
    "K": ["fg_0_19", "fg_20_29", "fg_30_39", "fg_40_49", "fg_50_plus", "fg_60_plus", "pat_made"],
    "DEF": ["def_td", "def_safety", "def_return_td", "def_points_allowed"],
}


# Years embedded with full weekly box-score data -- the 3 years Season
# Timeline already supports (real full-league draft + transaction data).
# Every {year}_weekly_stats.csv gets fetched (see
# fetch_weekly_actuals_nflreadpy.py) since fetching is cheap and may be
# useful later, but embedding weekly data for ALL 11 history years measured
# at 20.5MB total against the Artifact's confirmed-hard 16MB limit even
# after the free wins below (relevant-players-only bios, position-scoped
# stat fields, dropping 2025's embedded photos) closed most of the gap --
# user's own call (2026-08-01) to close the rest by scoping weekly data to
# these 3 years rather than cutting further into photos or stat depth.
# 2015-2022 keep everything they already had (season totals, draft grades)
# -- only the NEW per-week box-score feature doesn't reach that far back.
WEEKLY_STATS_YEARS = {2023, 2024, 2025}


def load_weekly_stats(cfg: dict) -> dict[str, dict[str, dict]]:
    """{year: {player_name_lower: {pos, w: [[week, points, opponent_team,
    *WEEKLY_POSITION_FIELDS[pos]], ...]}}} for every
    data/historical/{year}_weekly_stats.csv on disk whose year is in
    WEEKLY_STATS_YEARS (scripts/fetch_weekly_actuals_nflreadpy.py) -- powers
    Historical Review's per-week box score card. Array-encoded (not one JSON
    object per row) and position-scoped (see WEEKLY_POSITION_FIELDS) to keep
    this compact against the Artifact's confirmed-hard 16MB publish limit.
    `points` is computed here via the same score_player() every other view
    uses -- games=1 for DEF rows, since def_points_allowed in a weekly row is
    already a single game's total, not a season sum to re-divide. {} if no
    such files exist yet."""
    result: dict[str, dict[str, dict]] = {}
    for path in sorted(DATA_DIR.glob("*_weekly_stats.csv")):
        year = path.stem.split("_")[0]
        if int(year) not in WEEKLY_STATS_YEARS:
            continue
        df = pd.read_csv(path)
        df["team"] = df["team"].replace(ESPN_TEAM_ABBR_FIXUPS)
        df["opponent_team"] = df["opponent_team"].replace(ESPN_TEAM_ABBR_FIXUPS)
        by_player: dict[str, dict] = {}
        for row in df.to_dict("records"):
            position = row["position"]
            fields = WEEKLY_POSITION_FIELDS.get(position)
            if fields is None:
                continue
            stats = {f: row.get(f, 0) for f in RAW_STAT_FIELDS}
            games = 1 if position == "DEF" else None
            points = score_player({**stats, "position": position}, cfg, games=games)
            entry = [int(row["week"]), points, row["opponent_team"]]
            entry += [round(float(stats[f]), 1) if pd.notna(stats[f]) else 0 for f in fields]
            entry_holder = by_player.setdefault(row["name"].lower(), {"pos": position, "w": []})
            entry_holder["w"].append(entry)
        result[year] = by_player
    return result


def load_player_bios(relevant_names: set[str]) -> dict[str, dict]:
    """{player_name_lower: {height, weight, birth_date, college}} from
    data/player_bios.csv (scripts/fetch_player_bios_nflreadpy.py) -- static
    career facts, not year-specific, shared by every view. Keyed on name
    alone (lowercased) even though the source file is keyed by (name,
    position): a genuine same-name-different-position collision here would
    only matter if this project's own board ever rostered BOTH people, which
    isn't a real case among fantasy-relevant players -- keeps the frontend
    lookup a single flat dict rather than needing position context wherever
    a bio is displayed. Later rows win on collision (rare, harmless -- see
    the fetch script's own dedup for the real disambiguation logic).
    `relevant_names` (lowercased) restricts the embed to players who actually
    appear somewhere on this app's boards -- the raw fetch covers all ~25,000
    people in nflreadpy's full roster history (o-linemen, long-retired
    players, etc.), which would otherwise cost ~2.7MB against the Artifact's
    16MB hard limit for data nothing on this site ever displays. {} if the
    file doesn't exist yet."""
    path = Path(__file__).resolve().parent.parent / "data" / "player_bios.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, keep_default_na=False)
    result: dict[str, dict] = {}
    for row in df.itertuples():
        if row.name.lower() not in relevant_names:
            continue
        if not row.height and not row.weight and not row.birth_date and not row.college:
            continue
        result[row.name.lower()] = {
            "height": row.height or None,
            "weight": row.weight or None,
            "birth_date": row.birth_date or None,
            "college": row.college or None,
        }
    return result


def load_injury_games_missed() -> dict[str, dict[str, int]]:
    """{player: {season: games_missed_injury}} for every
    data/historical/{year}_injury_games_missed.csv on disk
    (scripts/fetch_injury_history.py) -- an explicit APPROXIMATION, not a
    precise play-by-play detector (see that script's docstring). {} if no
    such files exist yet."""
    result: dict[str, dict[str, int]] = {}
    for path in sorted(DATA_DIR.glob("*_injury_games_missed.csv")):
        df = pd.read_csv(path)
        for row in df.itertuples():
            result.setdefault(row.player, {})[str(row.season)] = int(row.games_missed_injury)
    return result


def build_data_bundle(cfg: dict) -> dict:
    """{'2026': [...rows with history...], '2025': [...], ..., '2020': [...]}"""
    year_boards = {
        # apply_scarcity=False: these score PAST seasons' real results (value
        # actually delivered), not the upcoming draft -- shouldn't be
        # reshaped by a boost calibrated for draft-day QB scarcity.
        year: score_file(DATA_DIR / f"{year}_actual_stats.csv", cfg, adp_lookup=load_adp(year), apply_scarcity=False)
        for year in HISTORY_YEARS
    }
    projection_board = score_file(
        DATA_DIR / "2026_projections.csv", cfg, adp_lookup=load_consensus_adp(), consensus_lookup=load_consensus_rankings()
    )

    # Index each year's VOR by (name, position) for fast per-player lookup.
    year_vor_lookup = {
        year: {(r["name"], r["position"]): r["vor"] for r in board.to_dict("records")}
        for year, board in year_boards.items()
    }

    relevant_names = {n.lower() for board in year_boards.values() for n in board["name"]}
    relevant_names |= {n.lower() for n in projection_board["name"]}

    projection_rows = to_rows(projection_board)
    for row in projection_rows:
        key = (row["name"], row["position"])
        history = []
        for year in HISTORY_YEARS:
            vor = year_vor_lookup[year].get(key)
            if vor is not None:
                history.append({"year": year, "vor": round(vor, 1)})
        # The 2026 point itself is the projection, not an observed year -- flagged
        # so the frontend can render it (and the line leading to it) distinctly.
        history.append({"year": 2026, "vor": row["vor"], "projected": True})
        row["history"] = history

    bundle = {
        "meta": {
            "num_teams": cfg["league"]["num_teams"],
            "roster_slots": cfg["roster"]["slots"],
            "gap_threshold_stdevs": cfg["tiering"]["gap_threshold_stdevs"],
            "league": cfg["league"],
            "scoring": cfg["scoring"],
            "season": cfg["season"],
            "scarcity_boosts": cfg.get("scarcity_boosts", {}),
            "notes": cfg.get("notes", []),
        },
        "2026": projection_rows,
        "fantasy_draft_results": load_fantasy_draft_results(),
        "transactions": load_transactions(),
        "schedule": load_schedule(),
        "weekly_stats": load_weekly_stats(cfg),
        "weekly_stat_fields": WEEKLY_POSITION_FIELDS,
        "player_bios": load_player_bios(relevant_names),
        "injury_games_missed": load_injury_games_missed(),
    }
    for year, board in year_boards.items():
        bundle[str(year)] = to_rows(board)
    return bundle


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/build_rankings_artifact_data.py <output_path.json>")
        sys.exit(1)
    out_path = Path(sys.argv[1])

    cfg = load_config()
    bundle = build_data_bundle(cfg)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f)

    print(f"Wrote {out_path}")
    for key, rows in bundle.items():
        if key == "meta":
            continue
        print(f"  {key}: {len(rows)} rows")
    with_history = sum(1 for r in bundle["2026"] if r["history"])
    print(f"  2026 rows with >=1 year of history: {with_history}/{len(bundle['2026'])}")


if __name__ == "__main__":
    main()

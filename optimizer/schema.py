"""
Canonical player-stat schema.

A raw projections CSV can name its columns anything (FantasyPros, ESPN, a
hand-built sheet, etc). The data loader's column-mapping step translates
whatever the CSV calls things into these fixed field names, and every other
module (scoring, VOR, tiers) only ever deals with this canonical schema.
That's what lets the CSV format change without touching scoring logic.

Each entry: (field_name, human_label, category)
"""

IDENTITY_FIELDS = [
    ("name", "Player Name"),
    ("position", "Position (QB/RB/WR/TE/K/DEF)"),
    ("team", "NFL Team"),
]

STAT_FIELDS = [
    # Passing
    ("pass_yds", "Passing Yards", "passing"),
    ("pass_td", "Passing TDs", "passing"),
    # Volume/context stats below (pass_att, pass_cmp, pass_int, carries,
    # targets) don't feed the scoring engine at all -- score_passing() etc.
    # only ever read the specific fields named above/below. They exist
    # purely to make the player detail page/card grid feel like a real
    # stat page (Yahoo/ESPN-style), not just derived fantasy points.
    ("pass_att", "Pass Attempts", "passing"),
    ("pass_cmp", "Completions", "passing"),
    ("pass_int", "Interceptions Thrown", "passing"),
    # Rushing
    ("rush_yds", "Rushing Yards", "rushing"),
    ("rush_td", "Rushing TDs", "rushing"),
    ("carries", "Carries", "rushing"),
    # Receiving
    ("rec", "Receptions", "receiving"),
    ("rec_yds", "Receiving Yards", "receiving"),
    ("rec_td", "Receiving TDs", "receiving"),
    ("targets", "Targets", "receiving"),
    # Misc offense
    ("return_td", "Punt/Kick Return TDs", "misc"),
    ("off_fumble_return_td", "Offensive Fumble Return TDs", "misc"),
    ("two_pt", "2-Point Conversions", "misc"),
    # Kicking (made field goals by distance bucket + made extra points)
    ("fg_0_19", "FG Made 0-19 yds", "kicking"),
    ("fg_20_29", "FG Made 20-29 yds", "kicking"),
    ("fg_30_39", "FG Made 30-39 yds", "kicking"),
    ("fg_40_49", "FG Made 40-49 yds", "kicking"),
    ("fg_50_plus", "FG Made 50-59 yds", "kicking"),
    ("fg_60_plus", "FG Made 60+ yds", "kicking"),
    ("pat_made", "Extra Points Made", "kicking"),
    # Defense/ST
    ("def_td", "Defensive/ST TDs", "defense"),
    ("def_safety", "Safeties", "defense"),
    ("def_return_td", "Defensive Return TDs", "defense"),
    ("def_xp_returned", "Extra Points Returned", "defense"),
    ("def_points_allowed", "Points Allowed (season total)", "defense"),
]

# Raw kicker CSVs almost always report makes in these fixed distance bands,
# even though the league's scoring buckets (in league_config.json) may be
# coarser or drawn at different cutoffs. We assign each raw band to whichever
# configured scoring bucket contains its midpoint.
#
# fg_60_plus (added 2026-07-27, session 6) exists because nflreadpy's
# load_player_stats() reports fg_made_50_59 and fg_made_60_ as genuinely
# separate counts -- unlike the older ESPN-leaderboard source (fetch_actuals.py),
# which only ever exposed one combined "50+ yards" aggregate with no way to
# split out true 60+ makes. That's why fg_50_plus's band still caps at 59
# rather than a wider range: years/rows fetched via the old ESPN source (or
# any hand-built CSV without real distance data) correctly fall back to the
# conservative assumption that an aggregate "50+" count is all 50-59 -- a
# real 60+ premium (this league scores it 15pts vs 5pts for 50-59, a 3x
# jump) should only ever be credited from an fg_60_plus count that's
# genuinely known, never inferred from the older aggregate.
FG_INPUT_BANDS = [
    ("fg_0_19", 0, 19),
    ("fg_20_29", 20, 29),
    ("fg_30_39", 30, 39),
    ("fg_40_49", 40, 49),
    ("fg_50_plus", 50, 59),
    ("fg_60_plus", 60, 89),
]

ALL_CANONICAL_FIELDS = [f[0] for f in IDENTITY_FIELDS] + [f[0] for f in STAT_FIELDS]

VALID_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

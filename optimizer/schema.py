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
    # Rushing
    ("rush_yds", "Rushing Yards", "rushing"),
    ("rush_td", "Rushing TDs", "rushing"),
    # Receiving
    ("rec", "Receptions", "receiving"),
    ("rec_yds", "Receiving Yards", "receiving"),
    ("rec_td", "Receiving TDs", "receiving"),
    # Misc offense
    ("return_td", "Punt/Kick Return TDs", "misc"),
    ("off_fumble_return_td", "Offensive Fumble Return TDs", "misc"),
    ("two_pt", "2-Point Conversions", "misc"),
    # Kicking (made field goals by distance bucket + made extra points)
    ("fg_0_19", "FG Made 0-19 yds", "kicking"),
    ("fg_20_29", "FG Made 20-29 yds", "kicking"),
    ("fg_30_39", "FG Made 30-39 yds", "kicking"),
    ("fg_40_49", "FG Made 40-49 yds", "kicking"),
    ("fg_50_plus", "FG Made 50+ yds", "kicking"),
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
# The "50+" band's upper bound is deliberately capped at 59, not a higher
# number: our data source only reports one aggregate "50+ yards" make count,
# with no way to split out true 60+ makes (which are genuinely rare -- a
# handful league-wide per season; the vast majority of "50+" kicks are
# 50-59). Using a wide range here (e.g. up to 89) would push the midpoint
# into whatever bucket covers 60+ yards, which -- once that tier scores
# meaningfully more (as this league's does: 60+ = 15pts vs 50-59 = 5pts,
# a 3x premium) -- would systematically overvalue every kicker's 50+
# makes. Capping at 59 keeps the conservative, realistic assumption:
# treat the aggregate as 50-59 yard makes unless/until a data source can
# split it further. Tradeoff: genuine 60+ specialists are currently
# UNDERVALUED since that premium is never captured at all.
FG_INPUT_BANDS = [
    ("fg_0_19", 0, 19),
    ("fg_20_29", 20, 29),
    ("fg_30_39", 30, 39),
    ("fg_40_49", 40, 49),
    ("fg_50_plus", 50, 59),
]

ALL_CANONICAL_FIELDS = [f[0] for f in IDENTITY_FIELDS] + [f[0] for f in STAT_FIELDS]

VALID_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

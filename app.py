"""Streamlit draft-day app: auto-loaded projections, tune league settings live, draft board."""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from optimizer import config as config_module
from optimizer import data_loader, mock_draft, scoring, schema, tiers, value_tools, vor

st.set_page_config(page_title="Gamblers Draft Optimizer", layout="wide")

HISTORICAL_DIR = Path(__file__).resolve().parent / "data" / "historical"
HISTORICAL_2025_PATH = HISTORICAL_DIR / "2025_actual_stats.csv"
PROJECTIONS_2026_PATH = HISTORICAL_DIR / "2026_projections.csv"

if "cfg" not in st.session_state:
    st.session_state.cfg = config_module.load_config()
if "drafted_by" not in st.session_state:
    st.session_state.drafted_by = {}  # player name -> "" / "Me" / "Opponent 1" / ...

cfg = st.session_state.cfg


def load_bundled_csv(path: Path) -> pd.DataFrame:
    """Loads one of our own committed CSVs (already in canonical-schema column
    names) through the same cleanup every uploaded CSV gets: numeric coercion,
    NaN->0, position validation."""
    raw = pd.read_csv(path)
    identity_mapping = {field: field for field in schema.ALL_CANONICAL_FIELDS if field in raw.columns}
    return data_loader.apply_mapping(raw, identity_mapping)


# Auto-load our own projections by default so every page just works with no
# upload step. Advanced users can still override this from League Settings.
if "canonical_df" not in st.session_state and PROJECTIONS_2026_PATH.exists():
    st.session_state.canonical_df = load_bundled_csv(PROJECTIONS_2026_PATH)
    st.session_state.data_source = "2026 Projections (Our Model)"

st.sidebar.title(cfg["league"]["name"])
st.sidebar.caption(f"Yahoo League ID {cfg['league']['yahoo_league_id']}")
page = st.sidebar.radio(
    "Navigate",
    ["Draft Board", "Mock Draft", "Trade Calculator", "Player Data", "League Settings"],
    label_visibility="collapsed",
)


def team_options(cfg: dict) -> list[str]:
    """'' (undrafted) + Me + one label per remaining team, so every real-draft pick can be
    attributed to a specific opponent instead of one generic 'Opponent' bucket -- that's what
    makes Team Power Rankings meaningful on the real draft, not just mock drafts."""
    num_teams = cfg["league"]["num_teams"]
    return ["", "Me"] + [f"Opponent {i}" for i in range(1, num_teams)]


def compute_scored_board(canonical_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Recomputes points/VOR/tier from raw stats + the CURRENT settings, every call.
    This is what makes editing League Settings instantly reshuffle the board."""
    board = canonical_df[["name", "position", "team"]].copy()
    board["points"] = canonical_df.apply(lambda row: scoring.score_player(row.to_dict(), cfg), axis=1)
    board = vor.compute_vor(board, cfg)
    board = tiers.assign_tiers(board, cfg)
    board["overall_rank"] = range(1, len(board) + 1)
    return board.set_index("name", drop=False)


def compute_board(canonical_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """compute_scored_board plus the real Draft Board's pick-tracking state."""
    board = compute_scored_board(canonical_df, cfg)
    board["drafted_by"] = board["name"].map(st.session_state.drafted_by).fillna("")
    return board


def record_mock_pick(md: dict, pick_row: pd.Series, team_label: str, num_teams: int) -> None:
    md["picks_log"].append({
        "pick": len(md["picks_log"]) + 1,
        "round": md["pick_idx"] // num_teams + 1,
        "team": team_label,
        "name": pick_row["name"],
        "position": pick_row["position"],
        "vor": pick_row["vor"],
    })
    md["rosters"][team_label].append(pick_row["position"])
    md["drafted_names"].add(pick_row["name"])
    md["pick_idx"] += 1


# =============================================================================
# PAGE: League Settings
# =============================================================================
if page == "League Settings":
    st.header("League Settings")
    st.caption(
        "Every number here feeds the scoring/ranking math directly — there are no built-in caps on roster "
        "counts or scoring values. Changes apply immediately to the Draft Board; use Save to keep them for next time."
    )

    st.subheader("League Info")
    li1, li2, li3 = st.columns(3)
    with li1:
        cfg["league"]["name"] = st.text_input("League name", cfg["league"]["name"])
    with li2:
        cfg["league"]["num_teams"] = st.number_input(
            "Number of teams", min_value=1, value=int(cfg["league"]["num_teams"]), step=1,
            help="Used for VOR replacement baselines: teams x starters at a position.",
        )
    with li3:
        cfg["league"]["yahoo_league_id"] = st.text_input("Yahoo League ID", cfg["league"]["yahoo_league_id"])

    st.subheader("Roster Slots")
    st.caption("Set any starter count per position — no maximum. This is what drives replacement-level scarcity.")
    roster_slots = cfg["roster"]["slots"]
    slot_cols = st.columns(len(roster_slots))
    for col, pos in zip(slot_cols, list(roster_slots.keys())):
        with col:
            roster_slots[pos] = st.number_input(pos, min_value=0, value=int(roster_slots[pos]), step=1, key=f"slot_{pos}")

    st.subheader("Scoring")

    with st.expander("Passing / Rushing / Receiving", expanded=True):
        p1, p2, p3 = st.columns(3)
        with p1:
            st.markdown("**Passing**")
            cfg["scoring"]["passing"]["yards_per_point"] = st.number_input(
                "Pass yards per point", min_value=1.0, value=float(cfg["scoring"]["passing"]["yards_per_point"]), key="pass_ypp"
            )
            cfg["scoring"]["passing"]["touchdown"] = st.number_input(
                "Pass TD", value=float(cfg["scoring"]["passing"]["touchdown"]), key="pass_td"
            )
        with p2:
            st.markdown("**Rushing**")
            cfg["scoring"]["rushing"]["yards_per_point"] = st.number_input(
                "Rush yards per point", min_value=1.0, value=float(cfg["scoring"]["rushing"]["yards_per_point"]), key="rush_ypp"
            )
            cfg["scoring"]["rushing"]["touchdown"] = st.number_input(
                "Rush TD", value=float(cfg["scoring"]["rushing"]["touchdown"]), key="rush_td"
            )
        with p3:
            st.markdown("**Receiving**")
            cfg["scoring"]["receiving"]["yards_per_point"] = st.number_input(
                "Rec yards per point", min_value=1.0, value=float(cfg["scoring"]["receiving"]["yards_per_point"]), key="rec_ypp"
            )
            cfg["scoring"]["receiving"]["touchdown"] = st.number_input(
                "Rec TD", value=float(cfg["scoring"]["receiving"]["touchdown"]), key="rec_td"
            )
            cfg["scoring"]["receiving"]["reception"] = st.number_input(
                "Per reception (PPR)", value=float(cfg["scoring"]["receiving"]["reception"]), key="rec_ppr"
            )

    with st.expander("Misc Offense"):
        m1, m2, m3 = st.columns(3)
        with m1:
            cfg["scoring"]["misc"]["return_touchdown"] = st.number_input(
                "Return TD", value=float(cfg["scoring"]["misc"]["return_touchdown"]), key="misc_return_td"
            )
        with m2:
            cfg["scoring"]["misc"]["offensive_fumble_return_touchdown"] = st.number_input(
                "Offensive fumble return TD",
                value=float(cfg["scoring"]["misc"]["offensive_fumble_return_touchdown"]),
                key="misc_fumble_td",
            )
        with m3:
            cfg["scoring"]["misc"]["two_point_conversion"] = st.number_input(
                "2-point conversion", value=float(cfg["scoring"]["misc"]["two_point_conversion"]), key="misc_2pt"
            )

    with st.expander("Kicking", expanded=True):
        cfg["scoring"]["kicking"]["extra_point"] = st.number_input(
            "Extra point (PAT)", value=float(cfg["scoring"]["kicking"]["extra_point"]), key="k_pat"
        )
        st.caption("Field goal distance buckets — add/remove rows freely; add finer tiers (e.g. split 50+ into 50-59/60+) as needed.")
        fg_df = pd.DataFrame(cfg["scoring"]["kicking"]["field_goal_buckets"])
        fg_edited = st.data_editor(
            fg_df, num_rows="dynamic", key="fg_buckets_editor", use_container_width=True,
            column_config={
                "min_yards": st.column_config.NumberColumn("Min Yards", min_value=0, step=1),
                "max_yards": st.column_config.NumberColumn("Max Yards", min_value=0, step=1),
                "points": st.column_config.NumberColumn("Points", step=1),
            },
        )
        fg_edited = fg_edited.dropna(how="all")
        if not fg_edited.empty:
            fg_edited = fg_edited.fillna(0)
            cfg["scoring"]["kicking"]["field_goal_buckets"] = [
                {"min_yards": int(r["min_yards"]), "max_yards": int(r["max_yards"]), "points": r["points"]}
                for r in fg_edited.to_dict("records")
            ]

    with st.expander("Defense / Special Teams", expanded=True):
        d1, d2, d3, d4 = st.columns(4)
        with d1:
            cfg["scoring"]["defense"]["touchdown"] = st.number_input(
                "TD", value=float(cfg["scoring"]["defense"]["touchdown"]), key="def_td"
            )
        with d2:
            cfg["scoring"]["defense"]["safety"] = st.number_input(
                "Safety", value=float(cfg["scoring"]["defense"]["safety"]), key="def_safety"
            )
        with d3:
            cfg["scoring"]["defense"]["return_touchdown"] = st.number_input(
                "Return TD", value=float(cfg["scoring"]["defense"]["return_touchdown"]), key="def_return_td"
            )
        with d4:
            cfg["scoring"]["defense"]["extra_point_returned"] = st.number_input(
                "XP returned", value=float(cfg["scoring"]["defense"]["extra_point_returned"]), key="def_xp_ret"
            )

        st.caption(
            "Points-allowed buckets, evaluated per game (see Season section below for games/season). "
            "Widen the swing here — e.g. make 0 pts allowed worth more, 35+ cost more — by editing rows directly."
        )
        pa_df = pd.DataFrame(cfg["scoring"]["defense"]["points_allowed_buckets"])
        pa_edited = st.data_editor(
            pa_df, num_rows="dynamic", key="pa_buckets_editor", use_container_width=True,
            column_config={
                "min_points": st.column_config.NumberColumn("Min Points Allowed", min_value=0, step=1),
                "max_points": st.column_config.NumberColumn("Max Points Allowed", min_value=0, step=1),
                "points": st.column_config.NumberColumn("Fantasy Points", step=1),
            },
        )
        pa_edited = pa_edited.dropna(how="all")
        if not pa_edited.empty:
            pa_edited = pa_edited.fillna(0)
            cfg["scoring"]["defense"]["points_allowed_buckets"] = [
                {"min_points": int(r["min_points"]), "max_points": int(r["max_points"]), "points": r["points"]}
                for r in pa_edited.to_dict("records")
            ]

    with st.expander("Season & Tiering"):
        s1, s2 = st.columns(2)
        with s1:
            cfg["season"]["games_per_season"] = st.number_input(
                "Games per season (for D/ST points-allowed math)",
                min_value=1, value=int(cfg["season"]["games_per_season"]), step=1, key="games_per_season",
            )
        with s2:
            cfg["tiering"]["gap_threshold_stdevs"] = st.number_input(
                "Tier sensitivity (higher = fewer, bigger tiers)",
                min_value=0.0, value=float(cfg["tiering"]["gap_threshold_stdevs"]), step=0.1, key="tier_sensitivity",
            )

    st.divider()
    save_col, reset_col = st.columns(2)
    with save_col:
        if st.button("Save settings to league_config.json", type="primary"):
            with open(config_module.DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            st.success("Saved. These settings will load automatically next time.")
    with reset_col:
        if st.button("Discard changes — reload from file"):
            st.session_state.cfg = config_module.load_config()
            st.rerun()

    st.divider()
    with st.expander("Advanced: use your own projections CSV instead"):
        st.caption(
            "The app defaults to our own auto-generated projections (see Player Data). "
            "Upload a different file here only if you have a specific export you'd rather use instead."
        )
        uploaded = st.file_uploader("Player projections CSV", type="csv", key="advanced_upload")

        if uploaded is not None:
            raw_df = pd.read_csv(uploaded)
            st.success(f"Loaded {len(raw_df)} rows, {len(raw_df.columns)} columns")

            if st.session_state.get("mapping_source_cols") != list(raw_df.columns):
                st.session_state.column_mapping = data_loader.guess_mapping(list(raw_df.columns))
                st.session_state.mapping_source_cols = list(raw_df.columns)

            saved = data_loader.list_saved_mappings()
            if saved:
                load_choice = st.selectbox("Load a saved column mapping", ["-- none --"] + saved)
                if load_choice != "-- none --" and st.button("Load mapping"):
                    st.session_state.column_mapping = data_loader.load_mapping(load_choice)

            st.caption("Confirm/correct which raw CSV column feeds each stat. Anything left as 'not in file' scores as 0.")
            options = ["-- not in file --"] + list(raw_df.columns)
            new_mapping = {}
            map_cols = st.columns(2)
            for i, field in enumerate(schema.ALL_CANONICAL_FIELDS):
                current = st.session_state.column_mapping.get(field)
                index = options.index(current) if current in options else 0
                with map_cols[i % 2]:
                    choice = st.selectbox(field, options, index=index, key=f"map_{field}")
                new_mapping[field] = None if choice == "-- not in file --" else choice
            st.session_state.column_mapping = new_mapping

            col_a, col_b = st.columns(2)
            with col_a:
                mapping_name = st.text_input("Save this mapping as", value="my_mapping")
                if st.button("Save mapping for reuse"):
                    data_loader.save_mapping(mapping_name, new_mapping)
                    st.success(f"Saved mapping '{mapping_name}'")
            with col_b:
                st.write("")
                st.write("")
                if st.button("Use This Data", type="primary"):
                    try:
                        canonical_df = data_loader.apply_mapping(raw_df, st.session_state.column_mapping)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        st.session_state.canonical_df = canonical_df
                        st.session_state.data_source = uploaded.name
                        st.session_state.drafted_by = {}
                        st.success(f"Loaded {len(canonical_df)} players. Go to Draft Board to see rankings.")

# =============================================================================
# PAGE: Draft Board
# =============================================================================
elif page == "Draft Board":
    st.header("Draft Board")
    st.caption(f"Data source: {st.session_state.get('data_source', 'unknown')}")

    if "canonical_df" not in st.session_state:
        st.info("No player data loaded. Go to **League Settings > Advanced** to import a CSV.")
    else:
        board = compute_board(st.session_state.canonical_df, cfg)

        if st.button("Reset all draft picks"):
            st.session_state.drafted_by = {}
            st.rerun()

        tab_full, tab_live, tab_roster, tab_teams = st.tabs(
            ["Full Player Pool — Mark Picks", "Best Available (Live)", "My Roster", "Team Power Rankings"]
        )

        with tab_full:
            st.caption("Rank/Points/VOR/Tier here reflect current League Settings across the full pool. Mark picks as they happen.")
            pos_filter = st.multiselect("Filter by position", sorted(board["position"].unique()), default=[])
            display_df = board if not pos_filter else board[board["position"].isin(pos_filter)]
            display_df = display_df[
                ["overall_rank", "name", "position", "team", "points", "vor", "tier", "drafted_by"]
            ]
            edited = st.data_editor(
                display_df,
                key="board_editor",
                hide_index=True,
                disabled=["overall_rank", "name", "position", "team", "points", "vor", "tier"],
                column_config={
                    "drafted_by": st.column_config.SelectboxColumn("Drafted By", options=team_options(cfg)),
                    "points": st.column_config.NumberColumn(format="%.1f"),
                    "vor": st.column_config.NumberColumn(format="%.1f"),
                },
                use_container_width=True,
            )
            for name, drafted_by in zip(edited.index, edited["drafted_by"]):
                st.session_state.drafted_by[name] = drafted_by

        with tab_live:
            st.caption("VOR and tiers recomputed from only the undrafted pool, so scarcity updates after every pick.")
            available = board[board["drafted_by"] == ""].copy()
            if available.empty:
                st.warning("Everyone in the pool has been marked drafted.")
            else:
                live = vor.compute_vor(available[["name", "position", "team", "points"]], cfg)
                live = tiers.assign_tiers(live, cfg)
                live["overall_rank"] = range(1, len(live) + 1)

                st.markdown("**Overall Top Available**")
                st.dataframe(
                    live.head(20)[["overall_rank", "name", "position", "team", "points", "vor", "tier"]],
                    hide_index=True,
                    use_container_width=True,
                )

                st.markdown("**Best Available by Position**")
                positions = sorted(schema.VALID_POSITIONS)
                cols = st.columns(len(positions))
                for col, position in zip(cols, positions):
                    with col:
                        st.caption(position)
                        pos_df = live[live["position"] == position].head(5)[["name", "points", "vor", "tier"]]
                        st.dataframe(pos_df, hide_index=True, use_container_width=True)

        with tab_roster:
            my_picks = board[board["drafted_by"] == "Me"].sort_values("vor", ascending=False)
            roster_slots = cfg["roster"]["slots"]
            slot_counts = {pos: 0 for pos in roster_slots}
            assignments = []
            for _, row in my_picks.iterrows():
                pos = row["position"]
                if slot_counts.get(pos, 0) < roster_slots.get(pos, 0):
                    slot_counts[pos] += 1
                    assignments.append((row["name"], pos, pos))
                elif slot_counts.get("BN", 0) < roster_slots.get("BN", 0):
                    slot_counts["BN"] += 1
                    assignments.append((row["name"], pos, "BN"))
                else:
                    assignments.append((row["name"], pos, "OVERFLOW — no slot left"))

            st.markdown("**Slots Filled**")
            slot_status = pd.DataFrame(
                [
                    {"Slot": pos, "Filled": slot_counts.get(pos, 0), "Total": total, "Open": total - slot_counts.get(pos, 0)}
                    for pos, total in roster_slots.items()
                ]
            )
            st.dataframe(slot_status, hide_index=True, use_container_width=True)

            st.markdown("**Picks**")
            if assignments:
                st.dataframe(
                    pd.DataFrame(assignments, columns=["Player", "Position", "Assigned Slot"]),
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.caption("No picks marked yet. Mark players as 'Me' in the Full Player Pool tab.")

        with tab_teams:
            st.caption("Total VOR of players marked to each team so far — the same value the board ranks players by.")
            totals = value_tools.team_totals(board, team_column="drafted_by")
            if totals.empty:
                st.caption("No picks marked yet. Assign players to teams in the Full Player Pool tab.")
            else:
                st.dataframe(totals, hide_index=True, use_container_width=True)

# =============================================================================
# PAGE: Mock Draft
# =============================================================================
elif page == "Mock Draft":
    st.header("Mock Draft")
    st.caption(
        f"Data source: {st.session_state.get('data_source', 'unknown')}. Bot opponents draft against the same "
        "VOR rankings as the real Draft Board. Separate from your real draft picks — safe to try and reset."
    )

    if "canonical_df" not in st.session_state:
        st.info("No player data loaded. Go to **League Settings > Advanced** to import a CSV.")
    else:
        num_teams = cfg["league"]["num_teams"]
        roster_slots = cfg["roster"]["slots"]

        if st.session_state.get("mock_draft") is None:
            st.subheader("Set Up")
            your_slot = st.number_input("Your draft slot", min_value=1, max_value=num_teams, value=1, step=1)
            if st.button("Start Mock Draft", type="primary"):
                total_rounds = mock_draft.total_rounds_for(roster_slots)
                order = mock_draft.build_snake_order(num_teams, total_rounds)
                team_labels = ["Me" if (i + 1) == your_slot else f"Team {i + 1}" for i in range(num_teams)]
                st.session_state.mock_draft = {
                    "team_labels": team_labels,
                    "order": order,
                    "pick_idx": 0,
                    "rosters": {label: [] for label in team_labels},
                    "picks_log": [],
                    "drafted_names": set(),
                }
                st.rerun()
        else:
            md = st.session_state.mock_draft
            scored = compute_scored_board(st.session_state.canonical_df, cfg)

            # Auto-run bot picks until it's the user's turn or the draft is complete.
            while md["pick_idx"] < len(md["order"]):
                team_label = md["team_labels"][md["order"][md["pick_idx"]]]
                if team_label == "Me":
                    break
                available = scored[~scored["name"].isin(md["drafted_names"])]
                if available.empty:
                    break
                ranked = vor.compute_vor(available[["name", "position", "team", "points"]], cfg)
                pick = mock_draft.pick_for_bot(ranked, md["rosters"][team_label], roster_slots)
                record_mock_pick(md, pick, team_label, num_teams)

            if st.button("Reset Mock Draft"):
                st.session_state.mock_draft = None
                st.rerun()

            if md["pick_idx"] >= len(md["order"]):
                st.success("Mock draft complete — see results below.")
            else:
                team_label = md["team_labels"][md["order"][md["pick_idx"]]]
                round_num = md["pick_idx"] // num_teams + 1
                st.subheader(f"Round {round_num}, Pick {md['pick_idx'] + 1} — {team_label} is on the clock")

                available = scored[~scored["name"].isin(md["drafted_names"])]
                ranked = vor.compute_vor(available[["name", "position", "team", "points"]], cfg)
                ranked = tiers.assign_tiers(ranked, cfg)

                pos_filter = st.multiselect(
                    "Filter by position", sorted(ranked["position"].unique()), default=[], key="mock_pos_filter"
                )
                display = ranked if not pos_filter else ranked[ranked["position"].isin(pos_filter)]
                st.dataframe(
                    display.head(30)[["name", "position", "team", "points", "vor", "tier"]],
                    hide_index=True,
                    use_container_width=True,
                )

                pick_name = st.selectbox("Your pick", display["name"].tolist(), key="mock_pick_select")
                if st.button("Draft This Player", type="primary"):
                    pick_row = ranked[ranked["name"] == pick_name].iloc[0]
                    record_mock_pick(md, pick_row, "Me", num_teams)
                    st.rerun()

            st.divider()
            st.subheader("Draft Log")
            if md["picks_log"]:
                st.dataframe(pd.DataFrame(md["picks_log"]), hide_index=True, use_container_width=True)
            else:
                st.caption("No picks yet.")

            st.subheader("Team Power Rankings")
            if md["picks_log"]:
                mock_board = pd.DataFrame(md["picks_log"]).rename(columns={"team": "drafted_by"})
                totals = value_tools.team_totals(mock_board, team_column="drafted_by")
                st.dataframe(totals, hide_index=True, use_container_width=True)
            else:
                st.caption("No picks yet.")

# =============================================================================
# PAGE: Trade Calculator
# =============================================================================
elif page == "Trade Calculator":
    st.header("Trade Calculator")
    st.caption(
        f"Data source: {st.session_state.get('data_source', 'unknown')}. "
        "Compares VOR given up by each side of a trade, using current League Settings."
    )

    if "canonical_df" not in st.session_state:
        st.info("No player data loaded. Go to **League Settings > Advanced** to import a CSV.")
    else:
        board = compute_scored_board(st.session_state.canonical_df, cfg)
        all_names = sorted(board["name"].tolist())

        col_a, col_b = st.columns(2)
        with col_a:
            side_a = st.multiselect("Side A gives up", all_names, key="trade_side_a")
        with col_b:
            side_b = st.multiselect("Side B gives up", all_names, key="trade_side_b")

        if side_a or side_b:
            result = value_tools.evaluate_trade(board, side_a, side_b)
            c1, c2, c3 = st.columns(3)
            c1.metric("Side A VOR given up", f"{result['side_a_vor_given']:.1f}")
            c2.metric("Side B VOR given up", f"{result['side_b_vor_given']:.1f}")
            c3.metric("Verdict", result["verdict"])
            st.caption(
                f"Net VOR swing — Side A: {result['net_for_a']:+.1f} · Side B: {result['net_for_b']:+.1f} "
                "(positive means that side comes out ahead)"
            )
        else:
            st.info("Pick at least one player on either side to evaluate.")

# =============================================================================
# PAGE: Player Data
# =============================================================================
elif page == "Player Data":
    st.header("Player Data")
    st.caption("Reference views of player stats by year -- nothing to upload, all sourced automatically.")

    ACTUAL_YEARS = [2025, 2024, 2023]

    def _year_board(path: Path, missing_hint: str):
        if not path.exists():
            st.warning(f"Data file not found. Generate it with: `{missing_hint}`")
            return
        year_df = load_bundled_csv(path)
        board = compute_scored_board(year_df, cfg)
        pos_filter = st.multiselect(
            "Filter by position", sorted(board["position"].unique()), default=[], key=f"filter_{path.stem}"
        )
        display = board if not pos_filter else board[board["position"].isin(pos_filter)]
        st.dataframe(
            display[["overall_rank", "name", "position", "team", "points", "vor", "tier"]],
            hide_index=True,
            use_container_width=True,
        )

    tab_proj, tab_actual, tab_playoffs = st.tabs(["2026 Projections (Our Model)", "Actual Results", "Playoffs"])

    with tab_proj:
        st.caption(
            "Our own projection model: a recency-weighted average of each player's real 2023-2025 stats "
            "(60% 2025 / 25% 2024 / 15% 2023, renormalized for players missing some years). "
            "This is what Draft Board, Mock Draft, and Trade Calculator use by default. "
            "Known gap: team defense (DEF) isn't included yet."
        )
        _year_board(PROJECTIONS_2026_PATH, "python scripts/build_2026_projections.py")

    with tab_actual:
        selected_year = st.segmented_control(
            "Year", options=[str(y) for y in ACTUAL_YEARS], default=str(ACTUAL_YEARS[0]), key="actual_year_selector"
        )
        selected_year = int(selected_year) if selected_year else ACTUAL_YEARS[0]
        st.caption(
            f"What actually happened in the {selected_year} season, scored under your current League Settings. "
            "Known gap: team defense (DEF) isn't included yet."
        )
        _year_board(HISTORICAL_DIR / f"{selected_year}_actual_stats.csv", f"python scripts/fetch_actuals.py {selected_year}")

    with tab_playoffs:
        st.info(
            "Coming soon -- playoff-only stats and scoring, for both the 2025 season and future seasons, "
            "will live here once that data pipeline is built."
        )

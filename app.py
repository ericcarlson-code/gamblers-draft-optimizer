"""Streamlit draft-day app: upload projections, tune league settings live, draft board."""
import json

import pandas as pd
import streamlit as st

from optimizer import config as config_module
from optimizer import data_loader, scoring, schema, tiers, vor

st.set_page_config(page_title="Gamblers Draft Optimizer", layout="wide")

if "cfg" not in st.session_state:
    st.session_state.cfg = config_module.load_config()
if "drafted_by" not in st.session_state:
    st.session_state.drafted_by = {}  # player name -> "" / "Me" / "Opponent"

cfg = st.session_state.cfg

st.sidebar.title(cfg["league"]["name"])
st.sidebar.caption(f"Yahoo League ID {cfg['league']['yahoo_league_id']}")
page = st.sidebar.radio(
    "Navigate",
    ["Upload & Map Data", "League Settings", "Draft Board"],
    label_visibility="collapsed",
)


def compute_board(canonical_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Recomputes points/VOR/tier from raw stats + the CURRENT settings, every call.
    This is what makes editing League Settings instantly reshuffle the board."""
    board = canonical_df[["name", "position", "team"]].copy()
    board["points"] = canonical_df.apply(lambda row: scoring.score_player(row.to_dict(), cfg), axis=1)
    board = vor.compute_vor(board, cfg)
    board = tiers.assign_tiers(board, cfg)
    board["overall_rank"] = range(1, len(board) + 1)
    board["drafted_by"] = board["name"].map(st.session_state.drafted_by).fillna("")
    return board.set_index("name", drop=False)


# =============================================================================
# PAGE: Upload & Map Data
# =============================================================================
if page == "Upload & Map Data":
    st.header("Upload & Map Data")
    st.caption("Upload a projections CSV once, confirm which columns mean what, then head to Draft Board.")

    uploaded = st.file_uploader("Player projections CSV", type="csv")

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

        st.subheader("Column Mapping")
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
            if st.button("Load Player Data", type="primary"):
                try:
                    canonical_df = data_loader.apply_mapping(raw_df, st.session_state.column_mapping)
                except ValueError as e:
                    st.error(str(e))
                else:
                    st.session_state.canonical_df = canonical_df
                    st.session_state.drafted_by = {}
                    st.success(f"Loaded {len(canonical_df)} players. Go to Draft Board to see rankings.")

# =============================================================================
# PAGE: League Settings
# =============================================================================
elif page == "League Settings":
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

# =============================================================================
# PAGE: Draft Board
# =============================================================================
elif page == "Draft Board":
    st.header("Draft Board")

    if "canonical_df" not in st.session_state:
        st.info("Go to **Upload & Map Data** first to load a projections CSV.")
    else:
        board = compute_board(st.session_state.canonical_df, cfg)

        if st.button("Reset all draft picks"):
            st.session_state.drafted_by = {}
            st.rerun()

        tab_full, tab_live, tab_roster = st.tabs(
            ["Full Player Pool — Mark Picks", "Best Available (Live)", "My Roster"]
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
                    "drafted_by": st.column_config.SelectboxColumn("Drafted By", options=["", "Me", "Opponent"]),
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

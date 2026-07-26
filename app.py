"""Streamlit draft-day app for The Gamblers 2025."""
import pandas as pd
import streamlit as st

from optimizer import config as config_module
from optimizer import data_loader, scoring, schema, tiers, vor

st.set_page_config(page_title="Gamblers Draft Optimizer", layout="wide")

cfg = config_module.load_config()  # reloaded fresh every run, so config edits take effect on next rerun

st.title(f"{cfg['league']['name']} — Draft Optimizer")
st.caption(
    f"Yahoo League ID {cfg['league']['yahoo_league_id']} · {cfg['league']['num_teams']} teams · "
    f"{cfg['league']['draft_type']} draft, {cfg['league']['scoring_type']}"
)

# --- Sidebar: upload, column mapping, board build -------------------------
st.sidebar.header("1. Upload Projections")
uploaded = st.sidebar.file_uploader("Player projections CSV", type="csv")

if uploaded is not None:
    raw_df = pd.read_csv(uploaded)
    st.sidebar.success(f"Loaded {len(raw_df)} rows, {len(raw_df.columns)} columns")

    if st.session_state.get("mapping_source_cols") != list(raw_df.columns):
        st.session_state.column_mapping = data_loader.guess_mapping(list(raw_df.columns))
        st.session_state.mapping_source_cols = list(raw_df.columns)

    st.sidebar.header("2. Map Columns")
    saved = data_loader.list_saved_mappings()
    if saved:
        load_choice = st.sidebar.selectbox("Load a saved mapping", ["-- none --"] + saved)
        if load_choice != "-- none --" and st.sidebar.button("Load mapping"):
            st.session_state.column_mapping = data_loader.load_mapping(load_choice)

    with st.sidebar.expander("Edit column mapping", expanded=True):
        options = ["-- not in file --"] + list(raw_df.columns)
        new_mapping = {}
        for field in schema.ALL_CANONICAL_FIELDS:
            current = st.session_state.column_mapping.get(field)
            index = options.index(current) if current in options else 0
            choice = st.selectbox(field, options, index=index, key=f"map_{field}")
            new_mapping[field] = None if choice == "-- not in file --" else choice
        st.session_state.column_mapping = new_mapping

        mapping_name = st.text_input("Save this mapping as", value="my_mapping")
        if st.button("Save mapping"):
            data_loader.save_mapping(mapping_name, new_mapping)
            st.success(f"Saved mapping '{mapping_name}'")

    st.sidebar.header("3. Build Draft Board")
    if st.sidebar.button("Apply mapping & compute points", type="primary"):
        try:
            canonical_df = data_loader.apply_mapping(raw_df, st.session_state.column_mapping)
        except ValueError as e:
            st.sidebar.error(str(e))
        else:
            points = canonical_df.apply(lambda row: scoring.score_player(row.to_dict(), cfg), axis=1)
            board = canonical_df[["name", "position", "team"]].copy()
            board["points"] = points
            board = vor.compute_vor(board, cfg)
            board = tiers.assign_tiers(board, cfg)
            board["overall_rank"] = range(1, len(board) + 1)
            board["drafted_by"] = ""
            board = board.set_index("name", drop=False)
            st.session_state.board_base = board
            st.sidebar.success(f"Board built: {len(board)} players")

if "board_base" in st.session_state:
    st.sidebar.divider()
    if st.sidebar.button("Reset all draft picks"):
        st.session_state.board_base["drafted_by"] = ""
        st.rerun()

# --- Main content -----------------------------------------------------------
if "board_base" not in st.session_state:
    st.info("Upload a CSV and click **Apply mapping & compute points** in the sidebar to get started.")
else:
    board = st.session_state.board_base

    tab_full, tab_live, tab_roster = st.tabs(
        ["Full Player Pool — Mark Picks", "Best Available (Live)", "My Roster"]
    )

    with tab_full:
        st.subheader("Full Player Pool")
        st.caption("Rank/Points/VOR/Tier here are from the original full pool. Mark picks below as they happen.")
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
        st.session_state.board_base.loc[edited.index, "drafted_by"] = edited["drafted_by"].values

    with tab_live:
        st.subheader("Best Available — Re-ranked From Remaining Players")
        available = st.session_state.board_base[st.session_state.board_base["drafted_by"] == ""].copy()
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
        st.subheader("My Roster")
        my_picks = st.session_state.board_base[st.session_state.board_base["drafted_by"] == "Me"].sort_values(
            "vor", ascending=False
        )
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

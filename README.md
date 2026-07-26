# Gamblers Draft Optimizer

Draft-day tool for **The Gamblers 2025** (Yahoo league ID `732599`, 10 teams, offline draft, season points, custom scoring) — computes custom fantasy points and Value Over Replacement (VOR) from uploaded projections, then tracks an offline draft live so you always see the best available player by position and value.

## Status

Work in progress, built incrementally step by step. See commit history for progress.

## Setup

This machine is Windows on ARM, where plain `pip` can't get pre-built wheels for
`pyarrow`/`streamlit`'s dependencies (they'd need to compile from source, which
requires build tools we don't have). The fix is [Miniforge](https://github.com/conda-forge/miniforge)
(a small conda distribution) so packages install from conda-forge's binary builds
instead. On a regular Windows/Mac/Linux x86_64 machine, a plain `pip install -r
requirements.txt` in a venv works fine and conda isn't needed.

**Windows on ARM (this machine):**

```bash
# one-time: winget install --id CondaForge.Miniforge3 -e
CONDA_SUBDIR=win-64 ~/miniforge3/Scripts/conda.exe create -y -p ./.conda-env -c conda-forge python=3.12 pandas pyarrow streamlit pytest
./.conda-env/python.exe -m streamlit run app.py
```

**Everywhere else:**

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Using the app

No upload needed to get started — the app auto-loads its own projections on launch. Five pages, navigated from the sidebar:

1. **Draft Board** — full player pool with pick tracking (attributable to "Me" or a specific opponent), a live-reranked "Best Available" view (VOR/tiers recomputed from only the undrafted pool after every pick), a roster tracker, and Team Power Rankings.
2. **Mock Draft** — practice against bot opponents that draft by need + VOR, snake order, fully separate from your real draft picks.
3. **Trade Calculator** — compares net VOR swing for any two sets of players.
4. **Player Data** — reference views by year: our own 2026 projections (see below), 2025 actual results, and a Playoffs tab (coming soon).
5. **League Settings** — every roster slot count and scoring value, editable with no built-in limits (e.g. any number of WR/K/QB slots). Changes apply to the board immediately; "Save" writes them to `league_config.json` so they persist next launch. An "Advanced" section lets you import your own projections CSV instead, if you have one.

## Player data

Instead of requiring a projections upload, the app ships with its own data, generated from ESPN's public stats API (no auth needed):

- `scripts/fetch_actuals.py <season>` pulls real final-season stats (QB/RB/WR/TE/K, plus all 32 team defenses' points allowed) into `data/historical/{season}_actual_stats.csv`. DEF only has points allowed for now -- defensive TDs/safeties/return TDs/XP-returned aren't available from this data source yet.
- `scripts/build_2026_projections.py` builds `data/historical/2026_projections.csv` — a recency-weighted average of each player's real 2023-2025 stats (`optimizer/projections.py`). This is what the Draft Board uses by default.

Re-run these next season to refresh the data.

## League settings

All scoring and roster rules live in [`league_config.json`](league_config.json) — nothing is hardcoded in the app logic. Edit them there directly, or through the League Settings page in the app.

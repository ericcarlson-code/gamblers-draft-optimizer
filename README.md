# Gamblers Draft Optimizer

Draft-day tool for **The Gamblers 2025** (Yahoo league ID `732599`, 10 teams, offline draft, season points, custom scoring) — computes custom fantasy points and Value Over Replacement (VOR) from uploaded projections, then tracks an offline draft live so you always see the best available player by position and value.

## Status

Work in progress, built incrementally step by step. See commit history for progress.

## Setup (once code lands)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## League settings

All scoring and roster rules live in [`league_config.json`](league_config.json) — nothing is hardcoded in the app logic, so you can edit the numbers there if Yahoo's actual settings differ from what's currently configured.

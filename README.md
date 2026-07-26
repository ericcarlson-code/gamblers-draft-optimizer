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

## League settings

All scoring and roster rules live in [`league_config.json`](league_config.json) — nothing is hardcoded in the app logic, so you can edit the numbers there if Yahoo's actual settings differ from what's currently configured.

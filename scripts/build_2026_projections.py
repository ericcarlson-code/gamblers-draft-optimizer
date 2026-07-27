"""
Builds data/historical/2026_projections.csv -- our own projection model,
a recency-weighted average of real 2023-2025 stats (see optimizer/projections.py).

Run after fetch_actuals.py has produced the year CSVs it depends on:
    python scripts/fetch_actuals.py 2023
    python scripts/fetch_actuals.py 2024
    python scripts/fetch_actuals.py 2025
    python scripts/build_2026_projections.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from optimizer.config import load_config  # noqa: E402
from optimizer.projections import build_projection  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"
YEARS = [2023, 2024, 2025]


def main() -> None:
    history = {}
    for year in YEARS:
        path = DATA_DIR / f"{year}_actual_stats.csv"
        if not path.exists():
            print(f"Missing {path}, skipping {year}")
            continue
        history[year] = pd.read_csv(path)

    games_per_season = load_config()["season"]["games_per_season"]
    projection = build_projection(history, games_per_season=games_per_season)
    out_path = DATA_DIR / "2026_projections.csv"
    projection.to_csv(out_path, index=False)
    print(f"Wrote {len(projection)} projected players to {out_path}")


if __name__ == "__main__":
    main()

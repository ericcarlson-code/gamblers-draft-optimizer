"""
One-off fetch: pulls live consensus Average Draft Position (ADP) from ESPN's
fantasy football player-info endpoint (no auth required) and writes it to
data/historical/adp.csv.

Usage:
    python scripts/fetch_adp.py

Note: this is LIVE, continuously-updating data reflecting today's real ESPN.com
fantasy drafts -- it is NOT a frozen historical snapshot. Querying past seasons
via this same endpoint was tried and found to return the same live ownership
numbers regardless of season, so this is only meaningful for the upcoming
draft (the current "2026 Projections" view) -- it is deliberately not wired
into the 2020-2025 actual-results views.
"""
import csv
import json
import sys
import urllib.request
from pathlib import Path

ADP_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leaguedefaults/3?view=kona_player_info"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"
PLAYER_LIMIT = 700  # deep enough to cover every player in our own projection pool
CSV_FIELDS = ["name", "adp"]


def fetch_adp() -> list[dict]:
    filter_header = json.dumps({
        "players": {"limit": PLAYER_LIMIT, "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": "STANDARD"}}
    })
    req = urllib.request.Request(
        ADP_URL,
        headers={"User-Agent": "Mozilla/5.0", "x-fantasy-filter": filter_header},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    rows = []
    for entry in data.get("players", []):
        player = entry.get("player") or {}
        adp = (player.get("ownership") or {}).get("averageDraftPosition")
        name = player.get("fullName")
        if not name or not adp:
            continue
        rows.append({"name": name, "adp": round(adp, 1)})
    return rows


def main() -> None:
    print("Fetching live ADP...")
    rows = fetch_adp()

    out_path = DATA_DIR / "adp.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["adp"]):
            writer.writerow(row)

    print(f"Wrote {len(rows)} players to {out_path}")


if __name__ == "__main__":
    main()

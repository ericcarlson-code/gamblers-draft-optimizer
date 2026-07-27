"""
One-off fetch: pulls real NFL draft results (round, overall pick, position)
for a given year from ESPN's public draft endpoint (no auth required) and
writes them to data/historical/{season}_draft_results.csv.

Usage:
    python scripts/fetch_draft_results.py 2026
    python scripts/fetch_draft_results.py 2020   # ... 2025, for the historical baseline

This is NOT called at app runtime -- see scripts/build_rookie_baseline.py and
optimizer/rookie_projections.py for what consumes these CSVs.

Only fantasy-relevant offensive/kicking positions are kept (QB/RB/WR/TE/K);
defensive/O-line picks are dropped since they're not fantasy-startable here.
"""
import csv
import sys
import urllib.request
from pathlib import Path

DRAFT_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/draft?season={season}"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"

FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K"}
CSV_FIELDS = ["name", "position", "team", "round", "pick", "overall"]

# ESPN's abbreviations disagree with nflreadpy's (our primary source since
# the Phase 3 pipeline swap) for the Rams ("LAR" vs "LA") and Washington
# ("WSH" vs "WAS") -- unnormalized, a rookie drafted by either team lands
# under a different `team` key than that same team's established players,
# splitting them apart everywhere team is used to group/match (confirmed:
# the Rams showed as two separate entries on the Stacks tab). See the same
# fixup in fetch_actuals.py and fetch_player_images.py.
ESPN_TEAM_ABBR_FIXUPS = {"LAR": "LA", "WSH": "WAS"}


def fetch_draft(season: int) -> dict:
    req = urllib.request.Request(DRAFT_URL.format(season=season), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        import json
        return json.loads(resp.read())


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/fetch_draft_results.py <season>")
        sys.exit(1)
    season = int(sys.argv[1])

    print(f"Fetching {season} NFL draft results...")
    data = fetch_draft(season)
    if data.get("year") != season:
        print(f"  WARNING: endpoint returned year {data.get('year')}, requested {season} -- season param may not be supported for this year, skipping")
        sys.exit(1)

    positions_by_id = {p["id"]: p["abbreviation"] for p in data.get("positions", [])}
    nfl_team_by_id = {
        t["id"]: ESPN_TEAM_ABBR_FIXUPS.get(t["abbreviation"], t["abbreviation"])
        for t in data.get("teams", [])
    }

    rows = []
    for pick in data.get("picks", []):
        athlete = pick.get("athlete") or {}
        position_id = (athlete.get("position") or {}).get("id")
        position = positions_by_id.get(position_id, "")
        if position == "PK":
            position = "K"  # match our schema's abbreviation
        if position not in FANTASY_POSITIONS:
            continue
        if not athlete.get("displayName"):
            continue
        rows.append({
            "name": athlete["displayName"],
            "position": position,
            # The NFL team that drafted them, not athlete.team (their college).
            "team": nfl_team_by_id.get(pick.get("teamId"), ""),
            "round": pick.get("round"),
            "pick": pick.get("pick"),
            "overall": pick.get("overall"),
        })

    out_path = DATA_DIR / f"{season}_draft_results.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["overall"]):
            writer.writerow(row)

    print(f"Wrote {len(rows)} fantasy-relevant picks to {out_path}")


if __name__ == "__main__":
    main()

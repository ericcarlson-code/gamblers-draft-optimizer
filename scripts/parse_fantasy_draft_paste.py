"""Parses a raw copy-paste of this league's REAL fantasy draft results (all
teams, all rounds, in actual pick order) into data/historical/
{year}_fantasy_draft_results.csv -- distinct from {year}_draft_results.csv,
which is the unrelated NFL rookie draft.

PASTE FORMAT: round headers followed by tab-separated pick lines, exactly
as copy-pasted from the league site's draft-results page:

    Round 1
    1.<TAB>Player Name<TAB>Team Name
    2.<TAB>Player Name<TAB>Team Name
    ...
    Round 2
    1.<TAB>Player Name<TAB>Team Name
    ...

The line's own number is the pick-within-round (1..num_teams), in actual
chronological pick order for that round (snake order is already baked into
the paste -- round 2's list is round 1's team order reversed, not
re-derived here). overall_pick = (round - 1) * num_teams + pick_in_round.

Player names are resolved against that year's data/historical/
{year}_actual_stats.csv board using the same suffix-tolerant matching as
build_rankings_artifact_data.py's _build_name_resolver (handles "James Cook"
vs "James Cook III", etc.), plus a nickname->full-name translation for team
D/ST picks pasted as a bare nickname (e.g. "Broncos" -> "Denver Broncos"),
mirroring site/rankings_template.html's DST_NICKNAME_TO_FULL_NAME (kept as
a separate copy here since the JS/Python sides don't share code -- if a new
team nickname ever fails to resolve, add it to BOTH places).

Usage:
    python scripts/parse_fantasy_draft_paste.py <year> <path_to_pasted_txt>

Unresolved names are still written to the CSV (with an empty
`player_resolved`) rather than dropped, so a human can review and fix them
by hand -- silently dropping a real historical pick would be worse than a
visible gap.
"""
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.build_rankings_artifact_data import _build_name_resolver  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"

ROUND_HEADER = re.compile(r"^Round\s+(\d+)$", re.IGNORECASE)
PICK_LINE = re.compile(r"^(\d+)\.\t(.+?)\t(.+)$")

# Team D/ST picks are sometimes pasted as a bare city/mascot nickname
# instead of the board's full team name. Mirror any additions here in
# site/rankings_template.html's DST_NICKNAME_TO_FULL_NAME too.
DST_NICKNAME_TO_FULL_NAME = {
    "Vikings": "Minnesota Vikings", "Steelers": "Pittsburgh Steelers", "Texans": "Houston Texans",
    "Packers": "Green Bay Packers", "Broncos": "Denver Broncos", "Seahawks": "Seattle Seahawks",
    "Rams": "Los Angeles Rams", "Chiefs": "Kansas City Chiefs", "Jaguars": "Jacksonville Jaguars",
    "Bills": "Buffalo Bills", "Eagles": "Philadelphia Eagles", "Ravens": "Baltimore Ravens",
    "Chargers": "Los Angeles Chargers", "Lions": "Detroit Lions",
    "Cowboys": "Dallas Cowboys", "Jets": "New York Jets", "49ers": "San Francisco 49ers",
    "Bengals": "Cincinnati Bengals",
}


def parse_paste(text: str) -> list[dict]:
    picks = []
    current_round = None
    pick_in_round = 0
    num_teams = None
    for line in text.splitlines():
        line = line.rstrip("\n").rstrip("\r")
        if not line.strip():
            continue
        rm = ROUND_HEADER.match(line.strip())
        if rm:
            current_round = int(rm.group(1))
            pick_in_round = 0
            continue
        pm = PICK_LINE.match(line)
        if not pm or current_round is None:
            continue
        pick_in_round = int(pm.group(1))
        player_raw = pm.group(2).strip()
        team = pm.group(3).strip()
        num_teams = max(num_teams or 0, pick_in_round)
        picks.append({
            "round": current_round,
            "pick_in_round": pick_in_round,
            "player_raw": DST_NICKNAME_TO_FULL_NAME.get(player_raw, player_raw),
            "team": team,
        })
    for p in picks:
        p["overall_pick"] = (p["round"] - 1) * num_teams + p["pick_in_round"]
    return picks


def resolve_names(picks: list[dict], year: int) -> None:
    stats_path = DATA_DIR / f"{year}_actual_stats.csv"
    board_names = set()
    if stats_path.exists():
        with open(stats_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                board_names.add(row["name"])
    resolver = _build_name_resolver({n: n for n in board_names})
    for p in picks:
        resolved = resolver(p["player_raw"])
        p["player_resolved"] = resolved or ""


def write_csv(picks: list[dict], year: int) -> Path:
    out_path = DATA_DIR / f"{year}_fantasy_draft_results.csv"
    fieldnames = ["overall_pick", "round", "pick_in_round", "team", "player_resolved", "player_raw"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in sorted(picks, key=lambda p: p["overall_pick"]):
            writer.writerow({k: p[k] for k in fieldnames})
    return out_path


def main():
    if len(sys.argv) != 3:
        print("Usage: python scripts/parse_fantasy_draft_paste.py <year> <path_to_pasted_txt>")
        sys.exit(1)
    year, path = int(sys.argv[1]), Path(sys.argv[2])
    text = path.read_text(encoding="utf-8")
    picks = parse_paste(text)
    resolve_names(picks, year)
    unresolved = [p for p in picks if not p["player_resolved"]]
    out_path = write_csv(picks, year)
    print(f"Parsed {len(picks)} picks across {max(p['round'] for p in picks)} rounds -> {out_path}")
    print(f"Resolved: {len(picks) - len(unresolved)}/{len(picks)}")
    if unresolved:
        print("UNRESOLVED (left blank in player_resolved, needs manual review):")
        for p in unresolved:
            print(f"  round {p['round']} pick {p['pick_in_round']} ({p['team']}): {p['player_raw']!r}")


if __name__ == "__main__":
    main()

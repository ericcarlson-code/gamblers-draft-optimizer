"""Parses a raw copy-paste of Flock Fantasy's positional consensus rankings
(as pasted directly from their site, one position at a time) and merges
corrected flock_list_no/team/fpts values into data/historical/
flock_fantasy_2026.csv -- the manually-maintained reference file loaded by
build_rankings_artifact_data.py's load_flock_rankings().

Why this exists: flock_fantasy_2026.csv was originally built from a single
one-off parse of a ~440-row all-positions paste (session 6, round 3). When
the user later has corrections for one position (e.g. an updated RB list),
re-pasting that position's block and running this script is much less
fragile than hand-editing the CSV, and doesn't require re-deriving the
paste format from scratch each time.

PASTE FORMAT (copy-pasted directly from Flock's site, one position's table
at a time, header row stripped or left in -- either is fine since only
lines matching the player-row pattern below are used):

    <overall_rank>. <Player Name>
    <POS><pos_rank>          e.g. "RB1", "TE9", "QB3"
    <TEAM or "-">
    <fpts or "-">
    <...any number of further stat columns, ignored...>

Repeats for each player. Flock's site inserts stray standalone lines
between some rows (doubled-letter tokens like "AA"/"BB"/"CC" -- confirmed
in session 6 round 3 to be page-divider artifacts from their table's
pagination, not real data). This parser doesn't need to specially detect
those: it only reads exactly 4 lines per player block (name, pos+rank,
team, fpts) then skips forward to the next line matching the "N. Name"
pattern, so extra stat columns AND divider lines are both skipped
automatically without needing to enumerate every position's different
stat-column layout (RB has rush+rec yards, TE has just receiving, QB will
differ again, etc. -- irrelevant here since only flock_list_no/team/fpts
feed the actual ranking-comparison logic; age/games_played/snap_pct in the
CSV are unused by load_flock_rankings() beyond passthrough context).

Usage:
    python scripts/parse_flock_paste.py <position> <path_to_pasted_txt>

<position> is the position code to assign (RB, TE, QB, WR, K, DEF) --
required rather than inferred from the pasted "RB1"-style tokens, since
those are trusted for pos_rank but position itself is passed explicitly to
avoid a mismatched-paste mistake silently mislabeling players.

Matches existing CSV rows by exact name (case-insensitive); updates
flock_list_no/team/fpts/position in place. Unmatched names are appended as
new rows with age/games_played/snap_pct left blank (not present in this
paste format). Players in the CSV but absent from this paste are left
untouched -- this is a targeted correction tool, not a full replace.
"""
import csv
import re
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"
CSV_PATH = DATA_DIR / "flock_fantasy_2026.csv"

NAME_LINE = re.compile(r"^(\d+)\.\s*([A-Za-z].*?)\s*$")
POSRANK_LINE = re.compile(r"^([A-Z]{1,3})(\d+)$")


def parse_paste(text: str, position: str) -> list[dict]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    players = []
    i = 0
    while i < len(lines):
        m = NAME_LINE.match(lines[i])
        if not m:
            i += 1
            continue
        overall_rank, name = int(m.group(1)), m.group(2)
        if i + 3 >= len(lines):
            break
        posrank_m = POSRANK_LINE.match(lines[i + 1])
        pos_rank = int(posrank_m.group(2)) if posrank_m else None
        team = lines[i + 2]
        team = None if team == "-" else team
        fpts_raw = lines[i + 3]
        fpts = None if fpts_raw in ("-", "INJ") else float(fpts_raw)
        players.append({
            "flock_list_no": overall_rank,
            "name": name,
            "position": position,
            "team": team,
            "fpts": fpts,
            "pos_rank": pos_rank,
        })
        # Skip forward past any remaining stat columns / divider lines to
        # the next "N. Name" row.
        j = i + 4
        while j < len(lines) and not NAME_LINE.match(lines[j]):
            j += 1
        i = j
    return players


def merge_into_csv(players: list[dict]) -> tuple[int, int]:
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    by_name = {row["name"].strip().lower(): row for row in rows}
    updated, added = 0, 0
    for p in players:
        key = p["name"].strip().lower()
        if key in by_name:
            row = by_name[key]
            row["flock_list_no"] = p["flock_list_no"]
            row["position"] = p["position"]
            row["team"] = row["team"] if p["team"] is None else p["team"]
            row["fpts"] = "" if p["fpts"] is None else p["fpts"]
            updated += 1
        else:
            rows.append({
                "flock_list_no": p["flock_list_no"],
                "name": p["name"],
                "position": p["position"],
                "team": p["team"] or "",
                "age": "",
                "games_played": "",
                "snap_pct": "",
                "fpts": "" if p["fpts"] is None else p["fpts"],
                "pos_rank": "",
                "overall_rank": "",
            })
            added += 1

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return updated, added


def main():
    if len(sys.argv) != 3:
        print("Usage: python scripts/parse_flock_paste.py <position> <path_to_pasted_txt>")
        sys.exit(1)
    position, path = sys.argv[1].upper(), Path(sys.argv[2])
    text = path.read_text(encoding="utf-8")
    players = parse_paste(text, position)
    print(f"Parsed {len(players)} {position} players from {path.name}")
    updated, added = merge_into_csv(players)
    print(f"Merged into {CSV_PATH}: {updated} updated, {added} added")


if __name__ == "__main__":
    main()

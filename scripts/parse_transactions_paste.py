"""Parses a raw copy-paste of this league's real in-season transaction log
(waiver swaps, trades, commissioner actions) into
data/historical/{season_year}_transactions.csv -- Historical Data Phase 1
(2025 Season Transactions). Distinct from {year}_fantasy_draft_results.csv
(draft-day picks only) and {year}_draft_results.csv (the unrelated NFL
rookie draft).

PASTE FORMAT: one transaction per line, exactly as copy-pasted from the
league site's transaction history. Three shapes, seen in real data:

    Standard waiver swap (add and/or drop):
        Xavier Legette Car-WR (Free Agent) / A.J. Brown NE-WR (To Free Agent) — Just Bout Dat Action — Jan 2, 9:28pm
        Tyrone Tracy Jr. NYG-RB (Free Agent) — Elite — Dec 10, 6:18pm            (add only)
        Alec Pierce Ind-WR PUP-P (To Free Agent) — Elite — Dec 10, 6:17pm        (drop only)
        Michael Wilson Ari-WR — Elite — Nov 26, 7:30pm                          (bare = add; the
                                                                                   site sometimes splits one
                                                                                   add+drop transaction across
                                                                                   two separate lines sharing
                                                                                   the same team+timestamp,
                                                                                   the add line often has no
                                                                                   "(Free Agent)" tag at all)

    Commissioner action (an extra " — {action}" segment vs. a standard line,
    always tagged "(Dac)" on the team -- kept OUT of owner behavioral data,
    these are league-admin corrections, not real roster decisions):
        Daniel Carlson LV-K NA — Free Agent Added (by Commissioner) — Greendawgs (Dac) — Dec 24, 5:01pm
        Jake Elliott Phi-K — Dropped (by Commissioner) To Free Agent — Greendawgs (Dac) — Dec 24, 5:00pm

    Trade (one line covers both sides, joined by " | ", each side using
    "→" instead of "(Free Agent)"/"(To Free Agent)"):
        TRADE: Kenneth Walker III KC-RB → Sportos (Dac) — Nov 5, 7:07pm | Khalil Shakir Buf-WR → Let's Ride (Dac) — Nov 5, 7:07pm

Dates in the paste have NO YEAR ("Jan 2, 9:28pm") -- inferred from
`season_year`: August-December belongs to `season_year`, January belongs to
`season_year + 1` (a fantasy season runs Aug/Sep-Jan, crossing a real
calendar-year boundary). The paste itself is newest-first PER BATCH, not
globally chronological -- this parser derives a real sortable ISO timestamp
per line and does not trust input order at all; sort the output CSV by
`timestamp`, never by row order.

Team names (both the fantasy team and each player's real NFL team) are
whatever the league site shows AS OF that transaction's own date -- fantasy
team names are NOT resolved against any other year's team identity here
(see the Historical Data Phase 1 spec: only "Sportos = Show Me Your TDs
(2017)" is confirmed so far, everything else stays unlinked until
confirmed). NFL team codes are upper-cased and passed through the same
ESPN_TEAM_ABBR_FIXUPS used elsewhere (LAR->LA, WSH->WAS) for consistency
with the board's own convention.

Player names are resolved against `{season_year}_actual_stats.csv`'s board
(same file every transaction-era player would appear on, regardless of
whether their specific transaction date fell in the Jan-of-next-year tail)
using the same suffix-tolerant matching as build_rankings_artifact_data.py's
_build_name_resolver, plus the same D/ST nickname table
parse_fantasy_draft_paste.py already uses for bare-mascot-name D/ST picks
(e.g. "Vikings" -> "Minnesota Vikings").

Usage:
    python scripts/parse_transactions_paste.py <season_year> <path_to_pasted_txt>

Unparsed lines (didn't match any of the three shapes above) and unresolved
player names are both still written to the CSV rather than dropped
silently, and also printed at the end for manual review -- same convention
as parse_fantasy_draft_paste.py.
"""
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.build_rankings_artifact_data import ESPN_TEAM_ABBR_FIXUPS, _build_name_resolver  # noqa: E402
from scripts.parse_fantasy_draft_paste import DST_NICKNAME_TO_FULL_NAME  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"

# The transaction log uses real common NFL nicknames the board itself
# doesn't (_build_name_resolver's suffix/accent-folding tiers don't cover
# nicknames) -- confirmed via the 2025 board: "Marquise Brown"/"Mike
# Badgley"/"John Parker Romo" are the real board names for these three.
# Add to this table if a future season's paste hits the same wall for a new
# player, rather than leaving them as a silent unresolved gap.
PLAYER_NAME_ALIASES = {
    "Hollywood Brown": "Marquise Brown",
    "Michael Badgley": "Mike Badgley",
    "Parker Romo": "John Parker Romo",
}

PLAYER_TOKEN = re.compile(
    r"^(?P<name>.+?)\s+(?P<team>[A-Za-z]{2,4})-(?P<pos>QB|RB|WR|TE|K|DEF)"
    r"(?:\s+(?P<flag>[A-Za-z]{1,4}(?:-[A-Za-z])?))?$"
)


def parse_player_token(text: str) -> dict | None:
    """"Xavier Legette Car-WR" / "Daniel Carlson LV-K NA" / "Vikings Min-DEF"
    -> {name, nfl_team, pos}. Returns None if the token doesn't match the
    expected "Name Team-Pos [flag]" shape at all (an unparsed line, not a
    resolution failure -- resolution against the real board happens later)."""
    m = PLAYER_TOKEN.match(text.strip())
    if not m:
        return None
    team = m.group("team").upper()
    team = ESPN_TEAM_ABBR_FIXUPS.get(team, team)
    name = m.group("name").strip()
    name = DST_NICKNAME_TO_FULL_NAME.get(name, name)
    name = PLAYER_NAME_ALIASES.get(name, name)
    return {"name": name, "nfl_team": team, "pos": m.group("pos")}


def parse_timestamp(date_str: str, season_year: int) -> str:
    dt = datetime.strptime(date_str.strip(), "%b %d, %I:%M%p")
    year = season_year + 1 if dt.month == 1 else season_year
    return dt.replace(year=year).isoformat()


def _empty_row() -> dict:
    return {
        "player_added_raw": "", "player_added_nfl_team": "", "player_added_pos": "",
        "player_dropped_raw": "", "player_dropped_nfl_team": "", "player_dropped_pos": "",
        "counterparty_team": "",
    }


def parse_standard_line(desc: str, team: str, date_str: str, raw: str) -> dict:
    row = _empty_row()
    row.update({"type": "waiver", "team": team, "date_str": date_str, "raw_line": raw})
    if " / " in desc:
        left, right = desc.split(" / ", 1)
        added = parse_player_token(left.replace("(Free Agent)", "").strip())
        dropped = parse_player_token(right.replace("(To Free Agent)", "").strip())
    elif "(To Free Agent)" in desc:
        added = None
        dropped = parse_player_token(desc.replace("(To Free Agent)", "").strip())
    else:
        # "(Free Agent)" suffix or fully bare -- both observed to mean an add
        # (see module docstring: the site sometimes splits one transaction
        # across two lines, and the add half is sometimes bare).
        added = parse_player_token(desc.replace("(Free Agent)", "").strip())
        dropped = None
    if added:
        row.update({"player_added_raw": added["name"], "player_added_nfl_team": added["nfl_team"], "player_added_pos": added["pos"]})
    if dropped:
        row.update({"player_dropped_raw": dropped["name"], "player_dropped_nfl_team": dropped["nfl_team"], "player_dropped_pos": dropped["pos"]})
    if desc and not added and not dropped:
        row["unparsed"] = True
    return row


def parse_commissioner_line(player_desc: str, action_desc: str, fteam_dac: str, date_str: str, raw: str) -> dict:
    row = _empty_row()
    team = fteam_dac.replace("(Dac)", "").strip()
    player = parse_player_token(player_desc)
    is_add = "Added" in action_desc
    row.update({
        "type": "commissioner_add" if is_add else "commissioner_drop",
        "team": team, "date_str": date_str, "raw_line": raw,
    })
    if player:
        key_prefix = "player_added" if is_add else "player_dropped"
        row.update({f"{key_prefix}_raw": player["name"], f"{key_prefix}_nfl_team": player["nfl_team"], f"{key_prefix}_pos": player["pos"]})
    else:
        row["unparsed"] = True
    return row


def parse_trade_line(line: str) -> list[dict]:
    body = line[len("TRADE:"):].strip()
    legs = [s.strip() for s in body.split(" | ")]
    results = []
    for leg in legs:
        parts = [s.strip() for s in leg.split(" — ")]
        row = _empty_row()
        row.update({"type": "trade", "date_str": "", "raw_line": line})
        if len(parts) == 2 and " → " in parts[0]:
            player_desc, fteam_dac = parts[0].split(" → ", 1)
            player = parse_player_token(player_desc.strip())
            row["team"] = fteam_dac.replace("(Dac)", "").strip()
            row["date_str"] = parts[1]
            if player:
                row.update({"player_added_raw": player["name"], "player_added_nfl_team": player["nfl_team"], "player_added_pos": player["pos"]})
            else:
                row["unparsed"] = True
        else:
            row["unparsed"] = True
        results.append(row)
    # Each leg's counterparty is simply the other leg's team (a trade this
    # parser has ever seen is always exactly 2 legs -- 3+ team trades, if
    # this league ever runs one, would need a real redesign here, not a
    # silent guess).
    if len(results) == 2 and not any(r.get("unparsed") for r in results):
        results[0]["counterparty_team"] = results[1]["team"]
        results[1]["counterparty_team"] = results[0]["team"]
    return results


def parse_line(line: str) -> list[dict]:
    line = line.strip()
    if not line:
        return []
    if line.startswith("TRADE:"):
        return parse_trade_line(line)
    parts = [s.strip() for s in line.split(" — ")]
    if len(parts) == 4 and "(by Commissioner)" in parts[1]:
        return [parse_commissioner_line(parts[0], parts[1], parts[2], parts[3], line)]
    if len(parts) == 3:
        return [parse_standard_line(parts[0], parts[1], parts[2], line)]
    return [{**_empty_row(), "type": "", "team": "", "date_str": "", "raw_line": line, "unparsed": True}]


def resolve_names(rows: list[dict], season_year: int) -> None:
    stats_path = DATA_DIR / f"{season_year}_actual_stats.csv"
    board_names = set()
    if stats_path.exists():
        with open(stats_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                board_names.add(r["name"])
    resolver = _build_name_resolver({n: n for n in board_names})
    for row in rows:
        row["player_added_resolved"] = (resolver(row["player_added_raw"]) or "") if row["player_added_raw"] else ""
        row["player_dropped_resolved"] = (resolver(row["player_dropped_raw"]) or "") if row["player_dropped_raw"] else ""


def write_csv(rows: list[dict], season_year: int) -> Path:
    out_path = DATA_DIR / f"{season_year}_transactions.csv"
    fieldnames = [
        "timestamp", "date_raw", "team", "type",
        "player_added_raw", "player_added_resolved", "player_added_nfl_team", "player_added_pos",
        "player_dropped_raw", "player_dropped_resolved", "player_dropped_nfl_team", "player_dropped_pos",
        "counterparty_team", "raw_line",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["timestamp"]):
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return out_path


def main():
    if len(sys.argv) != 3:
        print("Usage: python scripts/parse_transactions_paste.py <season_year> <path_to_pasted_txt>")
        sys.exit(1)
    season_year, path = int(sys.argv[1]), Path(sys.argv[2])
    text = path.read_text(encoding="utf-8")

    rows = []
    unparsed = []
    for line in text.splitlines():
        for row in parse_line(line):
            if row.get("unparsed"):
                unparsed.append(row)
                continue
            row["date_raw"] = row.pop("date_str")
            try:
                row["timestamp"] = parse_timestamp(row["date_raw"], season_year)
            except ValueError:
                row["timestamp"] = ""
                unparsed.append(row)
                continue
            rows.append(row)

    resolve_names(rows, season_year)
    unresolved = [
        r for r in rows
        if (r["player_added_raw"] and not r["player_added_resolved"])
        or (r["player_dropped_raw"] and not r["player_dropped_resolved"])
    ]

    out_path = write_csv(rows, season_year)
    print(f"Parsed {len(rows)} transaction rows -> {out_path}")
    by_type = {}
    for r in rows:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    for t, count in sorted(by_type.items()):
        print(f"  {t}: {count}")

    if unparsed:
        print(f"\nUNPARSED lines ({len(unparsed)}, needs manual review or a parser fix):")
        for r in unparsed:
            print(f"  {r['raw_line']!r}")

    if unresolved:
        print(f"\nUNRESOLVED player names ({len(unresolved)}, left blank in *_resolved, needs manual review):")
        for r in unresolved:
            bad = r["player_added_raw"] if r["player_added_raw"] and not r["player_added_resolved"] else r["player_dropped_raw"]
            print(f"  {bad!r} ({r['raw_line']!r})")


if __name__ == "__main__":
    main()

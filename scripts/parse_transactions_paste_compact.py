"""Parses a COMPACT transaction summary (as opposed to a verbatim raw Yahoo
export) into data/historical/{year}_transactions.csv -- same output schema
as parse_transactions_paste.py.

Why this exists: the 2025 pipeline (parse_transactions_paste.py) expects a
verbatim copy-paste of Yahoo's transaction history, with full "Free Agent"/
"To Free Agent" tags and minute-level timestamps. Starting with 2024, some
season logs have instead arrived as a date-only, "(FA)"/"(TFA)"-shorthand
summary reconstructed from batch context (confirmed with the user,
2026-07-30, who chose to proceed with this reduced-precision version rather
than track down the original Yahoo export each time). This script is kept
separate from parse_transactions_paste.py -- any year that DOES have a real
raw paste available should still use that script instead.

Known precision losses vs. the raw-paste pipeline:
  - No time-of-day: `timestamp` is set to local midnight on the parsed date,
    with a stable per-day sequence suffix (seconds = row's position within
    that day) so `sorted(key=timestamp)` still produces A valid order, but
    it reflects paste order within a day, not real chronological order.
  - Ambiguous slash-dates ("Nov 13/20", "Dec 4/11") use the FIRST date listed.
  - Injury-status flags (Q/NA/etc, present in the raw 2025 paste) don't
    exist in this input and are simply absent from the output.
  - A `TRADE: A → TeamA | B → TeamB — Date` line carries only ONE shared
    date for both legs (the raw-paste format gives each leg its own).

Deduplication: some years have distinct transaction descriptions recurring
verbatim under a second (or third) later date with nothing between them --
almost certainly the same real event restated across overlapping
reconstruction batches, not a genuine repeat (e.g. the exact same DEF swap
"twice" a month apart with no other DEF moves for that team in between).
This script keeps only the EARLIEST dated occurrence of each exact
description and drops the rest, logging what was dropped -- confirmed
present in both 2024 (28 cases) and 2023 (1 case) so far.

Lines that don't fit the add/drop-pair (or trade) shape at all -- e.g. a
multi-player "internal swap" description, or a self-contradictory line that
lists the same player as both add and drop -- are rejected outright and
left for manual review rather than silently force-parsed.

Usage:
    python scripts/parse_transactions_paste_compact.py <season_year> <path_to_pasted_txt>
"""
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.build_rankings_artifact_data import ESPN_TEAM_ABBR_FIXUPS, _build_name_resolver  # noqa: E402
from scripts.parse_fantasy_draft_paste import DST_NICKNAME_TO_FULL_NAME  # noqa: E402
from scripts.parse_transactions_paste import PLAYER_NAME_ALIASES, parse_player_token  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"


def parse_timestamp(date_str: str, season_year: int, day_seq: int) -> str:
    # Ambiguous slash-dates ("Nov 13/20") -> take the first date listed.
    date_str = date_str.split("/")[0].strip()
    # Drop any trailing parenthetical annotation, e.g.
    # "Oct 23 (Dec 11 date correction noted)" -> "Oct 23".
    date_str = re.sub(r"\s*\(.*\)\s*$", "", date_str).strip()
    dt = datetime.strptime(date_str, "%b %d")
    year = season_year + 1 if dt.month == 1 else season_year
    dt = dt.replace(year=year, second=min(day_seq, 59))
    return dt.isoformat()


def _empty_row() -> dict:
    return {
        "player_added_raw": "", "player_added_nfl_team": "", "player_added_pos": "",
        "player_dropped_raw": "", "player_dropped_nfl_team": "", "player_dropped_pos": "",
        "counterparty_team": "",
    }


def parse_standard_line(desc: str, team: str, date_str: str, raw: str) -> dict:
    row = _empty_row()
    row.update({"type": "waiver", "team": team, "date_str": date_str, "raw_line": raw})
    if desc.count("/") > 1:
        # More than one add/drop pair on one line (e.g. a multi-player
        # "internal swap" description) doesn't fit this model at all --
        # reject outright rather than silently keeping whichever single
        # token happens to parse and dropping the rest.
        row["unparsed"] = True
        return row
    if "/" in desc:
        left, right = desc.split("/", 1)
        added = parse_player_token(left.replace("(FA)", "").strip())
        dropped = parse_player_token(right.replace("(TFA)", "").strip())
        if added and dropped and added["name"] == dropped["name"]:
            # Self-contradictory line (same player listed as both add and
            # drop) -- a real example seen in 2024's compact paste. Doesn't
            # represent a genuine net roster change; reject for review.
            row["unparsed"] = True
            return row
    elif "(TFA)" in desc:
        added = None
        dropped = parse_player_token(desc.replace("(TFA)", "").strip())
    else:
        added = parse_player_token(desc.replace("(FA)", "").strip())
        dropped = None
    if added:
        row.update({"player_added_raw": added["name"], "player_added_nfl_team": added["nfl_team"], "player_added_pos": added["pos"]})
    if dropped:
        row.update({"player_dropped_raw": dropped["name"], "player_dropped_nfl_team": dropped["nfl_team"], "player_dropped_pos": dropped["pos"]})
    if desc and not added and not dropped:
        row["unparsed"] = True
    return row


def parse_commissioner_line(player_desc: str, action_desc: str, team: str, date_str: str, raw: str) -> dict:
    row = _empty_row()
    player = parse_player_token(player_desc.strip())
    is_add = "Added" in action_desc
    row.update({
        "type": "commissioner_add" if is_add else "commissioner_drop",
        "team": team.strip(), "date_str": date_str, "raw_line": raw,
    })
    if player:
        key_prefix = "player_added" if is_add else "player_dropped"
        row.update({f"{key_prefix}_raw": player["name"], f"{key_prefix}_nfl_team": player["nfl_team"], f"{key_prefix}_pos": player["pos"]})
    else:
        row["unparsed"] = True
    return row


def parse_trade_line(line: str) -> list[dict]:
    # "TRADE: PlayerA TeamA-Pos → FantasyTeamA | PlayerB TeamB-Pos → FantasyTeamB — Date"
    # -- unlike the raw-paste format, only ONE date trails the whole line,
    # shared by both legs (see module docstring).
    body = line[len("TRADE:"):].strip()
    if " — " not in body:
        return [{**_empty_row(), "type": "trade", "team": "", "date_str": "", "raw_line": line, "unparsed": True}]
    legs_part, date_str = body.rsplit(" — ", 1)
    legs = [s.strip() for s in legs_part.split(" | ")]
    results = []
    for leg in legs:
        row = _empty_row()
        row.update({"type": "trade", "date_str": date_str, "raw_line": line})
        if " → " in leg:
            player_desc, team = leg.split(" → ", 1)
            player = parse_player_token(player_desc.strip())
            row["team"] = team.strip()
            if player:
                row.update({"player_added_raw": player["name"], "player_added_nfl_team": player["nfl_team"], "player_added_pos": player["pos"]})
            else:
                row["unparsed"] = True
        else:
            row["unparsed"] = True
        results.append(row)
    if len(results) == 2 and not any(r.get("unparsed") for r in results):
        results[0]["counterparty_team"] = results[1]["team"]
        results[1]["counterparty_team"] = results[0]["team"]
    return results


def parse_line(line: str) -> list[dict]:
    line = line.strip()
    if not line:
        return []
    # Strip a trailing whole-line annotation, e.g. "... Oct 23 (Dec 11 date
    # correction noted)" or "... Nov 20 (labeled Oct 30 in one entry --
    # verify)" -- real transaction lines never legitimately end in "(...)"
    # (the date field is always last), so this only ever touches these
    # flagged-uncertain annotations, including ones with an em-dash inside
    # the parens that would otherwise corrupt the " — " field split below.
    line = re.sub(r"\s*\([^()]*\)\s*$", "", line).strip()
    if line.startswith("TRADE:"):
        return parse_trade_line(line)
    parts = [s.strip() for s in line.split(" — ")]
    if len(parts) == 4 and "by Commissioner" in parts[1]:
        return [parse_commissioner_line(parts[0], parts[1], parts[2], parts[3], line)]
    if len(parts) == 3:
        return [parse_standard_line(parts[0], parts[1], parts[2], line)]
    return [{**_empty_row(), "type": "", "team": "", "date_str": "", "raw_line": line, "unparsed": True}]


def dedupe_restatements(lines: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Collapses exact-description repeats (see module docstring) to their
    earliest dated occurrence. Returns (kept_lines, dropped_as_(desc, date))."""
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)  # desc -> [(date, full_line)]
    order: list[str] = []
    for raw_line in lines:
        line = re.sub(r"\s*\([^()]*\)\s*$", "", raw_line.strip()).strip()
        if line.startswith("TRADE:"):
            # Trades are rare (1-2 per season so far) and each one is
            # already unique -- pass through ungrouped rather than trying
            # to derive a dedup key from its own internal " | "/" — " shape.
            order.append(line)
            groups[line].append(("", line))
            continue
        parts = [s.strip() for s in line.split(" — ")]
        if len(parts) < 3:
            order.append(line)
            groups[line].append(("", line))
            continue
        desc_key = " — ".join(parts[:-1])
        date = parts[-1]
        if desc_key not in groups:
            order.append(desc_key)
        groups[desc_key].append((date, line))

    def sort_key(date_str: str) -> tuple:
        d = re.sub(r"\s*\(.*\)\s*$", "", date_str.split("/")[0]).strip()
        try:
            dt = datetime.strptime(d, "%b %d")
            month_rank = 0 if dt.month != 1 else 1  # Jan sorts after Aug-Dec
            return (month_rank, dt.month, dt.day)
        except ValueError:
            return (99, 99, 99)

    kept, dropped = [], []
    for key in order:
        entries = groups[key]
        entries_sorted = sorted(entries, key=lambda e: sort_key(e[0]))
        kept.append(entries_sorted[0][1])
        for date, full_line in entries_sorted[1:]:
            dropped.append((key, date))
    return kept, dropped


# PLAYER_NAME_ALIASES (imported from parse_transactions_paste.py) was built
# against the 2025 board's naming and is applied unconditionally inside
# parse_player_token -- but a different year's board can use the OPPOSITE
# name for the same player (confirmed: 2023's board has "Hollywood Brown"
# and "Michael Badgley" directly, the reverse of what the alias assumes).
# Fall back to the pre-alias spelling if the aliased one doesn't resolve,
# rather than leaving a real, resolvable player blank just because this
# particular year's board happens to prefer the other name.
_REVERSE_PLAYER_NAME_ALIASES = {v: k for k, v in PLAYER_NAME_ALIASES.items()}


def resolve_names(rows: list[dict], season_year: int) -> None:
    stats_path = DATA_DIR / f"{season_year}_actual_stats.csv"
    board_names = set()
    if stats_path.exists():
        with open(stats_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                board_names.add(r["name"])
    resolver = _build_name_resolver({n: n for n in board_names})

    def resolve_with_alias_fallback(name: str) -> str:
        if not name:
            return ""
        resolved = resolver(name)
        if resolved:
            return resolved
        alt = _REVERSE_PLAYER_NAME_ALIASES.get(name)
        return (resolver(alt) if alt else "") or ""

    for row in rows:
        row["player_added_resolved"] = resolve_with_alias_fallback(row["player_added_raw"])
        row["player_dropped_resolved"] = resolve_with_alias_fallback(row["player_dropped_raw"])


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
        print("Usage: python scripts/parse_transactions_paste_compact.py <season_year> <path_to_pasted_txt>")
        sys.exit(1)
    season_year, path = int(sys.argv[1]), Path(sys.argv[2])
    raw_lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    kept_lines, dropped = dedupe_restatements(raw_lines)
    if dropped:
        print(f"Deduped {len(dropped)} restated lines (same description, later date):")
        for desc, date in dropped:
            print(f"  {date!r} restates: {desc}")
        print()

    rows, unparsed = [], []
    day_counters: dict[str, int] = defaultdict(int)
    for line in kept_lines:
        for row in parse_line(line):
            if row.get("unparsed"):
                unparsed.append(row)
                continue
            row["date_raw"] = row.pop("date_str")
            norm_date = re.sub(r"\s*\(.*\)\s*$", "", row["date_raw"].split("/")[0]).strip()
            try:
                seq = day_counters[norm_date]
                row["timestamp"] = parse_timestamp(row["date_raw"], season_year, seq)
                day_counters[norm_date] += 1
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
        print(f"\nUNPARSED lines ({len(unparsed)}, needs manual review):")
        for r in unparsed:
            print(f"  {r['raw_line']!r}")

    if unresolved:
        print(f"\nUNRESOLVED player names ({len(unresolved)}, left blank in *_resolved, needs manual review):")
        for r in unresolved:
            bad = r["player_added_raw"] if r["player_added_raw"] and not r["player_added_resolved"] else r["player_dropped_raw"]
            print(f"  {bad!r} ({r['raw_line']!r})")


if __name__ == "__main__":
    main()

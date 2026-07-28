# Project Status

Fantasy football draft optimizer for a real 10-team, 2-QB, non-PPR Yahoo league (custom scoring, weekly-differential payout). The primary deliverable is the static site (`site/rankings_template.html`, built via `scripts/build_rankings_site.py`) — a Streamlit app (`app.py`) also exists but is parked in favor of the static site.

This file is the single source of truth for "what's actually built right now" — check it before assuming a feature exists or a bug is still open. Updated alongside meaningful changes; the git log is the detailed record, this is the summary.

## What's live

- **Rankings**: 2026 season projections (467 players — QB/RB/WR/TE/K/DEF) ranked by Value Over Replacement (VOR) under this league's real scoring rules, plus 2020–2025 actual-results views. Position filters, search, sortable columns (points, VOR, tier, TD splits, ADP, value-vs-ADP). A "Consensus" column shows a real ~500-player standard/non-PPR consensus ADP (averaged across Flock/Sleeper/ESPN/Yahoo/Underdog/CBS/FFPC) as a reference/divergence-flag layer only — VOR is always the actual ranking, never blended with market ADP.
- **Mock Draft**: full snake-draft simulation against 9 bot opponents who draft by real ADP + roster need (not our own VOR, since real opponents don't use this league's model). Multi-select position filters, live "Draft Value Edges" callout (where the market's consensus likely under/overrates a player for this league specifically), stack-value recommendations (QB+pass-catcher, RB+RB, etc.) woven into pick suggestions, persistent draft board, per-team roster viewer, post-draft grade report.
- **Trade Calculator**: side-by-side VOR comparison for proposed trades.
- **Historical Review**: for 2025 and 2024, the full real league draft (all teams, every pick) is loaded and graded pick-by-pick against that season's actual results, with real ADP context where available. Earlier years (2020–2023) support manual single-team entry instead.
- **League Details**: full league config (scoring rules, roster slots, current week) — editable, applies live everywhere — moved into a small modal off the header rather than a main tab.

## Known limitations / open items

- **DEF return-TD scoring is unresolved**: whether return TDs credit the DEF unit only or also the individual returner is ambiguous in the league's written rules; blocked on checking Yahoo's actual live scoring settings directly.
- **Defensive scoring is mostly points-allowed only**: `def_td`/`def_safety`/`def_return_td` are not sourced from a live feed for most teams (documented placeholder in `fetch_actuals.py`).
- **No real per-week projections yet**: "This Week" is an honest placeholder — there's no schedule/matchup data wired in, so a naive per-week number would just be a flat fraction of the season projection (misleading, not a real projection).
- **Kicker VOR can look inflated for a few low-snap kickers** — small-sample field-goal-rate extrapolation with no depth-chart damping applied to K, unlike skill positions. Cosmetically visible in the Draft Value Edges panel; not fixed yet.
- **~31 real players are missing from the 2026 board** (out of the underlying ~500-player consensus reference list) — genuine gaps in the underlying stats source (a few well-known: Travis Hunter, Jonathon Brooks, Brandon Aiyuk, Tyler Bass, Jason Sanders), not something silently faked around.
- **Season-total "over/under"-style player projections** (rush/rec/pass yards and TDs, betting-market style) for Mock Draft's player detail view: requested, not yet built — no confirmed free source for this specific market exists; likely needs the user to supply it manually for the top ~170 players (25 QB / 50 WR / 50 RB / 20 TE / 25 K).
- Yahoo Fantasy Sports live sync is built (`optimizer/yahoo_client.py`) but paused — needs a separate Yahoo API access application not yet submitted.

## Recent changes (most recent first)

- Removed the Team Rosters, League Scores, and Stacks tabs (all either unused placeholders or a reversed feature decision); League Details moved from a main tab into a header modal. Draft Value Edges removed from the Rankings tab specifically (still live in Mock Draft).
- Replaced Fantasy Football Calculator ADP and the Flock Fantasy PPR reference entirely with a real ~500-player standard/non-PPR consensus ADP (averaged across 7 real sources), trimmed the 2026 player universe to match (764 → 467 real players), fixed 4 real name-format mismatches found along the way.
- Added the full real 2024 season draft (9 teams, no Wildcard) to Historical Review; fixed a real bug where verdict grading used the current league's team count instead of that season's own.
- Mock Draft's position filter is multi-select (was single-select).
- 61 automated tests currently pass (`pytest`, run from repo root with the project's conda env — see `requirements.txt`/README for Windows-ARM setup notes).

## Repo notes

- Static site is generated, not hand-edited directly for data — `site/rankings_template.html` is the template; `scripts/build_rankings_site.py <output.html>` produces the actual deployable file (currently also published as a Claude Artifact for convenience).
- `data/historical/` holds real season stats, draft results, and ADP archives (tracked in git; regenerable via the `scripts/fetch_*.py` pipeline, not hand-authored).

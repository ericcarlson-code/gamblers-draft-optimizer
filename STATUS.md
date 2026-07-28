# Project Status

Fantasy football draft optimizer for a real 10-team, 2-QB, non-PPR Yahoo league (custom scoring, weekly-differential payout). The primary deliverable is the static site (`site/rankings_template.html`, built via `scripts/build_rankings_site.py`) — a Streamlit app (`app.py`) also exists but is parked in favor of the static site.

This file is the single source of truth for "what's actually built right now" — check it before assuming a feature exists or a bug is still open. Updated alongside meaningful changes; the git log is the detailed record, this is the summary.

## What's live

- **Rankings**: 2026 season projections (469 players — QB/RB/WR/TE/K/DEF) ranked by Value Over Replacement (VOR) under this league's real scoring rules, plus 2020–2025 actual-results views. Multi-select position filters, search, sortable columns (points, VOR, tier, TD splits, ADP, value-vs-ADP). A "Consensus" column shows a real ~500-player standard/non-PPR consensus ADP (averaged across Flock/Sleeper/ESPN/Yahoo/Underdog/CBS/FFPC) as a reference/divergence-flag layer only — VOR is always the actual ranking, never blended with market ADP. A position-count stat bar (Total/QB/WR/RB by default, arrows cycle to TE/K/DEF). Navigation is Rest of Season first, then a real Week 1-18 selector backed by the actual NFL schedule — a selected week correctly zeroes and BYE-flags players whose real team has a bye that week, with a Yahoo-style scrollable schedule sidebar (two team logos + kickoff time per matchup) alongside the table.
- **Mock Draft**: full snake-draft simulation against 9 bot opponents who draft by real ADP + roster need (not our own VOR, since real opponents don't use this league's model). Multi-select position filters that auto-navigate to the human's current starting-role needs (until the user manually overrides), live "Draft Value Edges" callout, stack-value recommendations (QB+pass-catcher, RB+RB, etc.) woven into pick suggestions, persistent draft board with a pencil-icon edit control on every pick (rewinds and re-simulates everything after the edited slot) plus an Undo Last Pick button, per-team roster viewer, post-draft grade report. "Sim Pick" auto-drafts the human's own turn using the current top recommendation; "Sim Draft" auto-completes the rest of the draft the same way (bot picking is still fully deterministic, so repeat runs currently converge to the same result — flagged, not yet built).
- **Trade Calculator**: side-by-side VOR comparison for proposed trades.
- **Historical Review**: for 2025 and 2024, the full real league draft (all teams, every pick) is loaded and graded pick-by-pick against that season's actual results, with real ADP context and a red "+N" approximate injury-games-missed badge per player per season. Earlier years (2020–2023) support manual single-team entry instead.
- **League Details**: full league config (scoring rules, roster slots, current week) — editable, applies live everywhere — moved into a small modal off the header rather than a main tab.

## Known limitations / open items

- **DEF return-TD scoring is unresolved**: whether return TDs credit the DEF unit only or also the individual returner is ambiguous in the league's written rules; blocked on checking Yahoo's actual live scoring settings directly. No Claude-in-Chrome browser has been connected yet to check this directly — resolve whenever the user connects one.
- **Defensive scoring is mostly points-allowed only**: `def_td`/`def_safety`/`def_return_td` are not sourced from a live feed for most teams (documented placeholder in `fetch_actuals.py`).
- **~31 real players are missing from the 2026 board**: 29 are genuine, currently-unfixable data-source gaps (IR/inactive/cut/unsigned real players with no usable 2025 stat line — Jonathon Brooks, Brandon Aiyuk, Tyler Bass, Jason Sanders, Deshaun Watson, and 24 others, mostly deep-bench/practice-squad names). Travis Hunter and Kyle Juszczyk were a real, fixable position-tagging bug (fixed — see Recent changes).
- **Injury-games-missed is an explicit approximation**, not exact — no data source can detect "left before halftime" specifically; it counts weeks reported Out, or weeks with very low offensive snap share while on the injury report. Historical Review's badge tooltip states this directly.
- **Charlie Smyth-style kicker inflation isn't fully resolved**: kicker VOR now gets the same depth-chart damping as skill positions (fixed), but a thin-sample kicker who's the nominal STARTER (not a backup) is untouched by design, same "don't punish a real starter for a short sample" rule used elsewhere — a residual case, not a bug in the new fix.
- **QB scarcity boost is a judgment-call calibration** (`league_config.json`'s `scarcity_boosts.QB`, `max_multiplier: 1.9`/`taper_to_rank: 16`) tuned against this league's real 2024/2025 draft data and real 2QB ADP, not an exact match — recalibrate via config only (no code change) if real draft behavior shifts. Scoped to QB only; no other position has direct evidence for a similar boost yet.
- **Season-total "over/under"-style player projections** (rush/rec/pass yards and TDs, betting-market style) for Mock Draft's player detail view: requested, not yet built — no confirmed free source for this specific market exists; likely needs the user to supply it manually for the top ~170 players (25 QB / 50 WR / 50 RB / 20 TE / 25 K).
- Yahoo Fantasy Sports live sync is built (`optimizer/yahoo_client.py`) but paused — needs a separate Yahoo API access application not yet submitted.

## Recent changes (most recent first)

**Batch "4pm" (2026-07-28), 4 phases, all committed:**
- **Phase 4 (Mock Draft)**: starter-role-first recommendation ordering + auto-navigating position filter (`computeStarterNeeds()`); undo/edit any pick via a new `rebuildMockDraftFromLog()` replay primitive (pencil icon on the draft board, truncate-and-resimulate semantics, warns before discarding the human's own later picks); Sim Pick / Sim Draft buttons (`topRecommendation()`).
- **Phase 3 (Rankings tab)**: multi-select position filter (ported from Mock Draft); position-count stat bar extended to QB/TE/K with a 4-visible-slot arrow carousel; nav restructured to Rest of Season + a real Week 1-18 selector with schedule-based bye zeroing/flagging (replacing the old flat-scalar "This Week" stub); a weekly schedule sidebar; a red injury-games-missed badge in Historical Review.
- **Phase 2 (data pipeline)**: new `scripts/fetch_schedule.py` (real 2026 NFL schedule via nflreadpy) and `scripts/fetch_injury_history.py` (approximate games-missed-to-injury), both wired into the site's data bundle.
- **Phase 1 (backend fixes)**: kicker VOR now gets the same depth-chart damping as skill positions (nflreadpy tags kickers "PK" in its depth-chart feed, not "K" — normalized); Travis Hunter/Kyle Juszczyk fixed onto the board (were tagged CB/FB and silently filtered out despite real offensive production); added a configurable QB positional-scarcity boost to VOR to reflect this league's real 2-QB draft-day "run," calibrated against real 2024/2025 draft data (VOR stays the sole ranking mechanism, scoped off for historical-season scoring). Also fixed a real duplicate-DataFrame-index bug in the new boost logic, caught by its own test.
- 469 players on the 2026 board (was 467 — Hunter/Juszczyk added back).
- 66 automated tests currently pass (`pytest`, run from repo root with the project's conda env — see `requirements.txt`/README for Windows-ARM setup notes), up from 61.

**Earlier:**
- Removed the Team Rosters, League Scores, and Stacks tabs (all either unused placeholders or a reversed feature decision); League Details moved from a main tab into a header modal. Draft Value Edges removed from the Rankings tab specifically (still live in Mock Draft).
- Replaced Fantasy Football Calculator ADP and the Flock Fantasy PPR reference entirely with a real ~500-player standard/non-PPR consensus ADP (averaged across 7 real sources), trimmed the 2026 player universe to match (764 → 467 real players), fixed 4 real name-format mismatches found along the way.
- Added the full real 2024 season draft (9 teams, no Wildcard) to Historical Review; fixed a real bug where verdict grading used the current league's team count instead of that season's own.

## Repo notes

- Static site is generated, not hand-edited directly for data — `site/rankings_template.html` is the template; `scripts/build_rankings_site.py <output.html>` produces the actual deployable file (currently also published as a Claude Artifact for convenience).
- `data/historical/` holds real season stats, draft results, and ADP archives (tracked in git; regenerable via the `scripts/fetch_*.py` pipeline, not hand-authored).

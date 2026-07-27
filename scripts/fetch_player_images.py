"""
Fetch player headshots and team logos for every player currently in
data/historical/2026_projections.csv, and every NFL team's logo (used as a
fallback when a player has no headshot). Downloads image bytes into a local
disk cache (data/image_cache/) so repeat builds don't re-download anything;
scripts/build_rankings_site.py embeds the cached files as base64 data URIs.

Usage:
    python scripts/fetch_player_images.py

Self-contained on purpose: rather than touching fetch_actuals.py/
fetch_draft_results.py's existing CSV schemas (which are also used for years
that don't need images at all), this does its own lightweight re-fetch of
the same two ESPN endpoints those scripts already use, purely to resolve
name -> headshot URL for the CURRENT player pool.

Images are resized via ESPN's own image-combiner endpoint (headshots to
120x120, logos to 80x80) before downloading -- full-size headshots are
~280KB each, which at 500+ players would balloon the site to an unreasonable
size; resized, they're ~15-20KB each (~10MB total for the whole pool, the
accepted tradeoff for embedding real images in a self-contained static page).
"""
import csv
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/statistics/byathlete"
DRAFT_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/draft?season=2026"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "image_cache"
HEADSHOT_SIZE = "120"
LOGO_SIZE = "80"

QUERIES = [
    ("passing.passingYards", 2),
    ("rushing.rushingYards", 5),
    ("receiving.receivingYards", 6),
    ("kicking.fieldGoalsMade", 2),
]

# All 32 real team abbreviations (matches optimizer/schema.py's DEF `team`
# field and scripts/fetch_adp.py's TEAM_ABBR_TO_FULL_NAME) -- used to fetch
# every team's logo as the universal fallback image.
ALL_TEAM_ABBRS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
    "HOU", "IND", "JAX", "KC", "LV", "LAC", "LAR", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SF", "SEA", "TB", "TEN", "WSH",
]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


SUFFIX_RE = re.compile(r"\s+(Jr\.?|Sr\.?|II|III|IV|V)$", re.IGNORECASE)


def strip_suffix(name: str) -> str:
    """Our board's canonical name (from nflreadpy) and ESPN's displayName
    don't always agree on whether a generational suffix is included -- e.g.
    our data has plain "James Cook" and "Travis Etienne", but ESPN's own
    headshot-endpoint records them as "James Cook III" and "Travis Etienne
    Jr.". A bare-name match would miss both. Used as a fallback key, not the
    primary one, so a real same-suffix-stripped-name collision (rare, but
    possible) still prefers an exact match first."""
    return SUFFIX_RE.sub("", name).strip()


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def fetch_veteran_headshots() -> dict[tuple[str, str], str]:
    """(name, team) -> headshot URL, from the same byathlete endpoint
    fetch_actuals.py uses (2025 season), fetched fresh here rather than
    reusing that script's output since headshot URLs aren't persisted to
    its CSVs.

    Keyed by (name, team), not bare name -- there are genuinely two NFL
    players named "Justin Jefferson" (the Vikings WR, and an unrelated
    Browns player), and bare-name "first seen wins" matching silently
    locked in the wrong one's headshot whenever the other's query ran
    first. Real player names are effectively unique within a single NFL
    team, so (name, team) is a cheap, reliable disambiguator without
    needing a full cross-site athlete-ID crosswalk."""
    out: dict[tuple[str, str], str] = {}
    for sort_key, num_pages in QUERIES:
        for page in range(1, num_pages + 1):
            url = (
                f"{BASE_URL}?region=us&lang=en&contentorigin=espn&isqualified=false"
                f"&page={page}&limit=50&sort={sort_key}%3Adesc&season=2025&seasontype=2"
            )
            try:
                data = fetch_json(url)
            except urllib.error.HTTPError as e:
                print(f"  {sort_key} page {page}: request failed ({e.code}), skipping")
                continue
            for record in data.get("athletes", []):
                athlete = record["athlete"]
                name = athlete.get("displayName")
                team = athlete.get("teamShortName", "")
                headshot = (athlete.get("headshot") or {}).get("href")
                key = (name, team)
                if name and headshot and key not in out:
                    out[key] = headshot
    return out


def fetch_rookie_headshots() -> dict[tuple[str, str], str]:
    """(name, team) -> headshot URL for the 2026 draft class, from the same
    endpoint fetch_draft_results.py uses -- covers true rookies with no 2025
    stats."""
    out: dict[tuple[str, str], str] = {}
    try:
        data = fetch_json(DRAFT_URL)
    except urllib.error.HTTPError as e:
        print(f"  2026 draft fetch failed ({e.code}), skipping rookie headshots")
        return out
    for pick in data.get("picks", []):
        athlete = pick.get("athlete") or {}
        name = athlete.get("displayName")
        team = (pick.get("team") or {}).get("abbreviation", "")
        headshot = (athlete.get("headshot") or {}).get("href")
        if name and headshot:
            out[(name, team)] = headshot
    return out


def resized_url(original_url: str, size: str) -> str:
    return f"https://a.espncdn.com/combiner/i?img={original_url.split('espncdn.com')[-1]}&w={size}&h={size}"


NFLREADPY_HEADSHOT_SEASON = 2025


def fetch_nflreadpy_headshots(season: int = NFLREADPY_HEADSHOT_SEASON) -> dict[tuple[str, str], str]:
    """(name, team) -> full-size headshot URL, sourced from nflreadpy's
    load_player_stats() (already used for scripts/fetch_actuals_nflreadpy.py
    -- same complete player pool, no top-N-leaderboard cap). Fills the exact
    gap the ESPN-based fetch above has: George Kittle and Christian Watson
    (11 and 10 games played in 2025 respectively) fell outside every ESPN
    QUERIES page window, so they never got a headshot URL at all -- but
    nflreadpy's per-player row always carries one when NFL.com has it,
    regardless of season totals. Since our own board's name/team ALSO come
    from nflreadpy now (fetch_actuals_nflreadpy.py), this should match by
    exact (name, team) far more often than the ESPN-keyed dict does.
    Lazily imported so nothing else that imports this module is forced to
    depend on nflreadpy/polars."""
    import nflreadpy as nfl

    df = nfl.load_player_stats(seasons=[season], summary_level="reg").to_pandas()
    out: dict[tuple[str, str], str] = {}
    for row in df.itertuples():
        name = row.player_display_name
        url = row.headshot_url
        if not name or not isinstance(url, str) or not url:
            continue
        out[(name, row.recent_team or "")] = url
    return out


def nflcdn_resized_url(original_url: str, size: str) -> str:
    """nflreadpy's headshot_url points at NFL.com's Cloudinary-backed CDN
    (static.www.nfl.com/image/upload/f_auto,q_auto/...) -- full-size images
    there run 3-4MB each, which would balloon the site the same way an
    un-resized ESPN headshot would. Cloudinary supports resize transforms
    inserted into the URL path itself (w_/h_/c_fill), same idea as ESPN's
    own combiner endpoint above, just a different CDN's syntax."""
    return original_url.replace("/upload/f_auto,q_auto/", f"/upload/f_auto,q_auto,w_{size},h_{size},c_fill/")


def download(url: str, dest: Path) -> bool:
    if dest.exists():
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.read())
        return True
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(f"  failed to download {url}: {e}")
        return False


def main() -> None:
    projections_path = DATA_DIR / "2026_projections.csv"
    if not projections_path.exists():
        print(f"Missing {projections_path} -- run scripts/build_2026_projections.py first")
        sys.exit(1)

    with open(projections_path, encoding="utf-8") as f:
        players = list(csv.DictReader(f))

    print("Fetching veteran headshot URLs (2025 season)...")
    headshot_urls = fetch_veteran_headshots()
    print(f"  {len(headshot_urls)} veteran headshots found")

    print("Fetching 2026 rookie headshot URLs...")
    headshot_urls.update(fetch_rookie_headshots())
    print(f"  {len(headshot_urls)} total headshots available")

    print("Fetching nflreadpy headshot URLs (complete player pool, fills gaps ESPN's leaderboard-only fetch leaves)...")
    nflreadpy_headshots = fetch_nflreadpy_headshots()
    print(f"  {len(nflreadpy_headshots)} nflreadpy headshots found")
    # Bare-name fallback -- our board's team can differ from nflreadpy's OWN
    # season-stats team for a player whose team we corrected via the
    # depth-chart current_team_map() fix (e.g. Kenneth Walker III shows SEA
    # in nflreadpy's 2025 stats row, but KC on our corrected board) -- an
    # exact (name, team) match would miss exactly the players that fix
    # applies to. Same uniqueness guard as the ESPN-side fallbacks.
    nflreadpy_by_name: dict[str, set[str]] = {}
    for (nname, _nteam), nurl in nflreadpy_headshots.items():
        nflreadpy_by_name.setdefault(nname, set()).add(nurl)

    headshots_dir = CACHE_DIR / "headshots"
    logos_dir = CACHE_DIR / "logos"

    print("Downloading team logos (32 teams)...")
    for abbr in ALL_TEAM_ABBRS:
        url = resized_url(f"/i/teamlogos/nfl/500/{abbr.lower()}.png", LOGO_SIZE)
        download(url, logos_dir / f"{abbr}.png")
    print(f"  Done -- cached in {logos_dir}")

    # Suffix-stripped (name, team) fallback -- our board and ESPN don't
    # always agree on whether "III"/"Jr." is part of the name (see
    # strip_suffix's docstring). First-seen-wins per key, matching the
    # existing "first query wins" convention.
    by_stripped_name_team: dict[tuple[str, str], str] = {}
    for (name, team), url in headshot_urls.items():
        by_stripped_name_team.setdefault((strip_suffix(name), team), url)

    # Bare-name fallback index, for a legitimate team-abbreviation mismatch
    # (e.g. a mid-cycle trade) -- only used when exactly one entry shares
    # that name, so a genuine two-different-people collision (Justin
    # Jefferson) still can't silently pick the wrong one.
    by_name: dict[str, list[str]] = {}
    for (name, _team), url in headshot_urls.items():
        by_name.setdefault(name, []).append(url)

    # Last-resort fallback: suffix stripped AND team ignored -- covers a
    # player who both changed teams and has a suffix mismatch (e.g. Travis
    # Etienne: our board says "Travis Etienne"/JAX from last season's stats,
    # ESPN's live data says "Travis Etienne Jr."/NO after a trade). Same
    # uniqueness guard as the other fallbacks.
    by_stripped_name: dict[str, list[str]] = {}
    for (name, _team), url in headshot_urls.items():
        by_stripped_name.setdefault(strip_suffix(name), []).append(url)

    print(f"Downloading player headshots ({len(players)} players in 2026 board)...")
    matched = 0
    for i, p in enumerate(players, 1):
        name = p["name"]
        team = p.get("team", "")
        if p["position"] == "DEF":
            continue  # defenses use their team logo, not an individual headshot
        url = headshot_urls.get((name, team))
        resizer = resized_url
        if not url:
            url = by_stripped_name_team.get((strip_suffix(name), team))
        if not url:
            candidates = by_name.get(name, [])
            url = candidates[0] if len(candidates) == 1 else None
        if not url:
            candidates = by_stripped_name.get(strip_suffix(name), [])
            url = candidates[0] if len(candidates) == 1 else None
        if not url:
            # ESPN's leaderboard-based fetch has nothing for this player
            # (e.g. George Kittle/Christian Watson, whose 2025 games-missed
            # kept them off every QUERIES page) -- nflreadpy's complete pool
            # covers exactly this gap. Name/team come from the same source
            # as our own board now, so an exact match is the common case;
            # bare-name fallback covers our own team-correction step shifting
            # a player off whatever team nflreadpy's stats row itself shows.
            url = nflreadpy_headshots.get((name, team))
            if not url:
                candidates = nflreadpy_by_name.get(name, set())
                url = next(iter(candidates)) if len(candidates) == 1 else None
            if url:
                resizer = nflcdn_resized_url
        if not url:
            continue
        matched += 1
        download(resizer(url, HEADSHOT_SIZE), headshots_dir / f"{slugify(name)}.png")
        if i % 100 == 0:
            print(f"  ...{i}/{len(players)} processed")

    print(f"Matched {matched}/{len(players)} players to a headshot ({len(players) - matched} will fall back to their team logo)")
    print(f"Cache: {CACHE_DIR}")


if __name__ == "__main__":
    main()

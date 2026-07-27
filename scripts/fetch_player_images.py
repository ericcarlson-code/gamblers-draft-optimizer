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


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def fetch_veteran_headshots() -> dict[str, str]:
    """name -> headshot URL, from the same byathlete endpoint fetch_actuals.py
    uses (2025 season), fetched fresh here rather than reusing that script's
    output since headshot URLs aren't persisted to its CSVs."""
    out: dict[str, str] = {}
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
                headshot = (athlete.get("headshot") or {}).get("href")
                if name and headshot and name not in out:
                    out[name] = headshot
    return out


def fetch_rookie_headshots() -> dict[str, str]:
    """name -> headshot URL for the 2026 draft class, from the same endpoint
    fetch_draft_results.py uses -- covers true rookies with no 2025 stats."""
    out: dict[str, str] = {}
    try:
        data = fetch_json(DRAFT_URL)
    except urllib.error.HTTPError as e:
        print(f"  2026 draft fetch failed ({e.code}), skipping rookie headshots")
        return out
    for pick in data.get("picks", []):
        athlete = pick.get("athlete") or {}
        name = athlete.get("displayName")
        headshot = (athlete.get("headshot") or {}).get("href")
        if name and headshot:
            out[name] = headshot
    return out


def resized_url(original_url: str, size: str) -> str:
    return f"https://a.espncdn.com/combiner/i?img={original_url.split('espncdn.com')[-1]}&w={size}&h={size}"


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

    headshots_dir = CACHE_DIR / "headshots"
    logos_dir = CACHE_DIR / "logos"

    print("Downloading team logos (32 teams)...")
    for abbr in ALL_TEAM_ABBRS:
        url = resized_url(f"/i/teamlogos/nfl/500/{abbr.lower()}.png", LOGO_SIZE)
        download(url, logos_dir / f"{abbr}.png")
    print(f"  Done -- cached in {logos_dir}")

    print(f"Downloading player headshots ({len(players)} players in 2026 board)...")
    matched = 0
    for i, p in enumerate(players, 1):
        name = p["name"]
        if p["position"] == "DEF":
            continue  # defenses use their team logo, not an individual headshot
        url = headshot_urls.get(name)
        if not url:
            continue
        matched += 1
        download(resized_url(url, HEADSHOT_SIZE), headshots_dir / f"{slugify(name)}.png")
        if i % 100 == 0:
            print(f"  ...{i}/{len(players)} processed")

    print(f"Matched {matched}/{len(players)} players to a headshot ({len(players) - matched} will fall back to their team logo)")
    print(f"Cache: {CACHE_DIR}")


if __name__ == "__main__":
    main()

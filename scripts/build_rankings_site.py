"""
One-command build for the published rankings site (a static HTML Artifact,
separate from the live Streamlit app). Replaces the old multi-step manual
process (score data -> write JSON -> hand-substitute fonts/data into the
template -> ...) with a single script:

    python scripts/build_rankings_site.py <output.html>

Reads site/rankings_template.html (the source of truth, versioned in this
repo) and site/fonts/*.woff2, embeds them as data URIs, injects the scored
data bundle from build_rankings_artifact_data.build_data_bundle(), and
writes the finished, self-contained HTML file to the given path -- ready
to hand straight to the Artifact tool.
"""
import base64
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from optimizer.config import load_config
from scripts.build_rankings_artifact_data import HISTORY_YEARS, build_data_bundle
from scripts.fetch_player_images import slugify

# Embedding a headshot for every player across every HISTORY_YEARS board
# (now back to 2015) pushed the built site to 23MB -- Artifact's hard limit
# is 16MB, confirmed by a real rejected publish attempt, not just the
# ~16MB figure noted from session 5's testing. Capping historical headshot
# embedding to this year and later keeps the site at the already-verified-
# safe ~15.75MB (the exact configuration published successfully before this
# expansion) -- players ONLY in 2015-2019 fall back to their team logo
# instead of a photo, the same graceful degradation already used for any
# player missing a headshot match. The underlying STATS DATA for 2015-2019
# is NOT affected by this constant -- Rankings/Historical Review still work
# fully for those years, this only trims which years' PHOTOS get embedded.
IMAGE_HISTORY_MIN_YEAR = 2025

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
TEMPLATE_PATH = SITE_DIR / "rankings_template.html"
INJURY_STATUS_PATH = Path(__file__).resolve().parent.parent / "data" / "injury_status.json"
IMAGE_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "image_cache"
FONTS = {
    "__BEBAS_B64__": SITE_DIR / "fonts" / "bebas.woff2",
    "__PUBLIC_B64__": SITE_DIR / "fonts" / "public.woff2",
    "__MONO_B64__": SITE_DIR / "fonts" / "mono.woff2",
}


def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build_image_lookups(all_player_names: set[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Embeds cached images (see scripts/fetch_player_images.py) as base64
    data URIs, keyed by player name / team abbreviation for direct JS lookup
    at render time -- the on-disk slugified filenames are an internal detail
    of the fetch/cache step, not exposed here. Silently skips anything not
    in the cache (missing images just fall back client-side to the team
    logo, or no image at all -- see rankings_template.html's playerImageHtml).
    `all_player_names` covers every year's board, not just 2026 -- historical-
    only players (real, on a past season's board, but not the current 2026
    one) have their own cached headshots too now (fetch_player_images.py's
    fetch_historical_headshots), which a 2026-only name list would silently
    never embed even though they're sitting right there on disk."""
    headshots_dir = IMAGE_CACHE_DIR / "headshots"
    logos_dir = IMAGE_CACHE_DIR / "logos"

    team_logos: dict[str, str] = {}
    if logos_dir.exists():
        for path in logos_dir.glob("*.png"):
            team_logos[path.stem] = _data_uri(path)

    player_images: dict[str, str] = {}
    if headshots_dir.exists():
        for name in all_player_names:
            path = headshots_dir / f"{slugify(name)}.png"
            if path.exists():
                player_images[name] = _data_uri(path)

    return player_images, team_logos


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/build_rankings_site.py <output.html>")
        sys.exit(1)
    out_path = Path(sys.argv[1])

    cfg = load_config()
    bundle = build_data_bundle(cfg)

    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    for placeholder, font_path in FONTS.items():
        b64 = base64.b64encode(font_path.read_bytes()).decode("ascii")
        html = html.replace(placeholder, b64)
    html = html.replace("__BOARD_DATA_BY_YEAR_JSON__", json.dumps(bundle))
    html = html.replace("__GEN_DATE__", date.today().strftime("%B %d, %Y"))

    injury_status = json.loads(INJURY_STATUS_PATH.read_text(encoding="utf-8")) if INJURY_STATUS_PATH.exists() else {}
    html = html.replace("__INJURY_STATUS_JSON__", json.dumps(injury_status))

    image_board_keys = ["2026"] + [str(y) for y in HISTORY_YEARS if y >= IMAGE_HISTORY_MIN_YEAR]
    all_player_names = {p["name"] for key in image_board_keys for p in bundle[key]}
    player_images, team_logos = build_image_lookups(all_player_names)
    html = html.replace("__PLAYER_IMAGES_JSON__", json.dumps(player_images))
    html = html.replace("__TEAM_LOGOS_JSON__", json.dumps(team_logos))
    print(f"  Embedded {len(player_images)} player headshots + {len(team_logos)} team logos")

    remaining = [tok for tok in ("__BEBAS_B64__", "__PUBLIC_B64__", "__MONO_B64__",
                                  "__BOARD_DATA_BY_YEAR_JSON__", "__GEN_DATE__",
                                  "__INJURY_STATUS_JSON__", "__PLAYER_IMAGES_JSON__",
                                  "__TEAM_LOGOS_JSON__") if tok in html]
    if remaining:
        print(f"WARNING: unreplaced placeholders remain: {remaining}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()

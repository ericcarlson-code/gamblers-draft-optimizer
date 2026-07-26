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
from scripts.build_rankings_artifact_data import build_data_bundle

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
TEMPLATE_PATH = SITE_DIR / "rankings_template.html"
FONTS = {
    "__BEBAS_B64__": SITE_DIR / "fonts" / "bebas.woff2",
    "__PUBLIC_B64__": SITE_DIR / "fonts" / "public.woff2",
    "__MONO_B64__": SITE_DIR / "fonts" / "mono.woff2",
}


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

    remaining = [tok for tok in ("__BEBAS_B64__", "__PUBLIC_B64__", "__MONO_B64__",
                                  "__BOARD_DATA_BY_YEAR_JSON__", "__GEN_DATE__") if tok in html]
    if remaining:
        print(f"WARNING: unreplaced placeholders remain: {remaining}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()

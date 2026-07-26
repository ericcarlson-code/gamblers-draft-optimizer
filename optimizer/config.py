"""Loads league_config.json so scoring/VOR code never hardcodes league rules."""
import json
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "league_config.json"


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

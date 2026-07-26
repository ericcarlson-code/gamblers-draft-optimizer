"""
CSV ingestion with an editable column-mapping step.

A raw projections export (FantasyPros, ESPN, a hand-built sheet, ...) can
name its columns anything. Instead of hardcoding "this column is always
called X", the app asks once, per file, which raw column corresponds to
each canonical field (see schema.py), and that mapping can be saved to
disk and reused. If next year's CSV export changes its headers, you redo
the mapping step in the UI -- no code changes required.
"""
import json
from pathlib import Path

import pandas as pd

from optimizer.schema import ALL_CANONICAL_FIELDS, VALID_POSITIONS

MAPPINGS_DIR = Path(__file__).resolve().parent.parent / "data" / "column_mappings"


def guess_mapping(raw_columns: list[str]) -> dict[str, str | None]:
    """Best-effort auto-guess of raw column -> canonical field, for a starting point.
    Always shown to the user to confirm/correct before applying, never applied blindly."""
    normalized = {c: c.strip().lower().replace(" ", "").replace("_", "") for c in raw_columns}
    aliases = {
        "name": ["playername", "name", "player"],
        "position": ["position", "pos"],
        "team": ["team", "tm"],
        "pass_yds": ["passyds", "passingyards", "yds", "passyards"],
        "pass_td": ["passtd", "passingtds", "td"],
        "rush_yds": ["rushyds", "rushingyards"],
        "rush_td": ["rushtd", "rushingtds"],
        "rec": ["rec", "receptions"],
        "rec_yds": ["recyds", "receivingyards"],
        "rec_td": ["rectd", "receivingtds"],
        "fg_0_19": ["fg019", "fg1_19", "fg0-19"],
        "fg_20_29": ["fg2029", "fg20-29"],
        "fg_30_39": ["fg3039", "fg30-39"],
        "fg_40_49": ["fg4049", "fg40-49"],
        "fg_50_plus": ["fg50", "fg50+"],
        "pat_made": ["xpt", "xpm", "patmade", "extrapointsmade"],
        "def_td": ["deftd", "td"],
        "def_safety": ["safety", "saf"],
        "def_points_allowed": ["pa", "pointsallowed"],
    }
    mapping: dict[str, str | None] = {field: None for field in ALL_CANONICAL_FIELDS}
    for field, candidates in aliases.items():
        for raw_col, norm in normalized.items():
            if norm in candidates:
                mapping[field] = raw_col
                break
    return mapping


def apply_mapping(df: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    """Rename/select raw columns into a canonical-schema DataFrame, filling
    any unmapped stat field with 0 and validating position values."""
    out = pd.DataFrame()
    for field in ALL_CANONICAL_FIELDS:
        raw_col = mapping.get(field)
        if raw_col and raw_col in df.columns:
            out[field] = df[raw_col]
        else:
            out[field] = "" if field in ("name", "position", "team") else 0

    out["position"] = out["position"].astype(str).str.strip().str.upper()
    numeric_fields = [f for f in ALL_CANONICAL_FIELDS if f not in ("name", "position", "team")]
    for field in numeric_fields:
        out[field] = pd.to_numeric(out[field], errors="coerce").fillna(0.0)

    unknown = sorted(set(out["position"]) - VALID_POSITIONS)
    if unknown:
        raise ValueError(
            f"Found position value(s) not in {sorted(VALID_POSITIONS)}: {unknown}. "
            "Fix the position column mapping or the source data."
        )
    return out


def save_mapping(name: str, mapping: dict[str, str | None]) -> Path:
    MAPPINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = MAPPINGS_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)
    return path


def load_mapping(name: str) -> dict[str, str | None] | None:
    path = MAPPINGS_DIR / f"{name}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_saved_mappings() -> list[str]:
    if not MAPPINGS_DIR.exists():
        return []
    return sorted(p.stem for p in MAPPINGS_DIR.glob("*.json"))

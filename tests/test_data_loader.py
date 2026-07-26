import pandas as pd
import pytest

from optimizer.data_loader import apply_mapping, guess_mapping


def test_guess_mapping_finds_common_headers():
    raw_columns = ["Player", "Position", "Team", "Pass Yds", "Pass TD"]
    mapping = guess_mapping(raw_columns)
    assert mapping["name"] == "Player"
    assert mapping["position"] == "Position"
    assert mapping["pass_yds"] == "Pass Yds"
    assert mapping["pass_td"] == "Pass TD"


def test_apply_mapping_fills_unmapped_stats_with_zero():
    df = pd.DataFrame({"Player": ["Josh Allen"], "Pos": ["QB"], "PassYds": [4000]})
    mapping = {"name": "Player", "position": "Pos", "pass_yds": "PassYds"}
    out = apply_mapping(df, mapping)
    row = out.iloc[0]
    assert row["name"] == "Josh Allen"
    assert row["position"] == "QB"
    assert row["pass_yds"] == 4000
    assert row["pass_td"] == 0
    assert row["rush_yds"] == 0


def test_apply_mapping_rejects_unknown_position():
    df = pd.DataFrame({"Player": ["Mystery Guy"], "Pos": ["FLEX"]})
    mapping = {"name": "Player", "position": "Pos"}
    with pytest.raises(ValueError):
        apply_mapping(df, mapping)

from scripts.fetch_actuals import category_values


def test_category_values_flattens_using_root_names_ordering():
    category_names = {
        "passing": ["completions", "passingAttempts", "passingYards", "passingTouchdowns"],
        "rushing": ["rushingAttempts", "rushingYards", "rushingTouchdowns"],
    }
    athlete_record = {
        "categories": [
            {"name": "passing", "values": [20.0, 30.0, 250.0, 2.0]},
            {"name": "rushing", "values": [5.0, 40.0, 1.0]},
        ]
    }
    result = category_values(athlete_record, category_names)
    assert result["passingYards"] == 250.0
    assert result["passingTouchdowns"] == 2.0
    assert result["rushingYards"] == 40.0
    assert result["rushingTouchdowns"] == 1.0


def test_category_values_ignores_categories_not_in_root_definitions():
    category_names = {"passing": ["passingYards"]}
    athlete_record = {"categories": [{"name": "someUnknownCategory", "values": [99.0]}]}
    result = category_values(athlete_record, category_names)
    assert result == {}

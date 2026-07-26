"""
Covers only what's testable without a live Yahoo account/credentials:
authorization URL construction and the defensive JSON-search helpers.
The actual OAuth token exchange and API calls are UNTESTED -- see the
module docstring in optimizer/yahoo_client.py.
"""
from optimizer.yahoo_client import build_authorization_url, find_dicts_with_keys


def test_build_authorization_url_includes_required_params():
    url = build_authorization_url("my-client-id")
    assert url.startswith("https://api.login.yahoo.com/oauth2/request_auth?")
    assert "client_id=my-client-id" in url
    assert "redirect_uri=oob" in url
    assert "response_type=code" in url


def test_find_dicts_with_keys_finds_nested_matches():
    data = {
        "a": {"league_key": "1", "league_id": "1", "name": "Foo", "extra": {"league_key": "2", "league_id": "2", "name": "Bar"}},
        "b": [{"league_key": "3", "league_id": "3", "name": "Baz"}, {"unrelated": True}],
    }
    found = find_dicts_with_keys(data, {"league_key", "league_id", "name"})
    names = sorted(d["name"] for d in found)
    assert names == ["Bar", "Baz", "Foo"]


def test_find_dicts_with_keys_ignores_partial_matches():
    data = {"a": {"league_key": "1"}, "b": {"league_key": "2", "name": "Only Partial"}}
    found = find_dicts_with_keys(data, {"league_key", "league_id", "name"})
    assert found == []


def test_find_dicts_with_keys_empty_when_no_match():
    assert find_dicts_with_keys({"x": 1, "y": [1, 2, 3]}, {"league_key"}) == []

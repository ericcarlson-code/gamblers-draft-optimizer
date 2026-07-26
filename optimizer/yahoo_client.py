"""
Yahoo Fantasy Sports OAuth2 client, using the out-of-band (oob) flow: no
redirect server needed. You open a URL in your own browser, log into
Yahoo yourself (we never see your password), and paste back a short code
Yahoo displays -- that's what scripts/yahoo_auth.py walks you through.

UNTESTED against a live Yahoo account as of writing -- built from Yahoo's
documented OAuth2 + Fantasy Sports API patterns, but this environment has
no Yahoo Developer credentials to actually exercise it against. Expect to
need a debugging pass once real credentials/tokens are available. The
JSON-parsing helpers below are deliberately defensive (search by key
rather than exact path) since Yahoo's fantasy API responses are known to
be awkwardly nested from their XML->JSON conversion.

Token/app-credential storage lives in .credentials/ (gitignored) at the
repo root -- never commit that directory.
"""
import json
import time
import urllib.parse
from pathlib import Path

import requests

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
FANTASY_BASE = "https://fantasysports.yahooapis.com/fantasysports/v2"
REDIRECT_URI = "oob"  # out-of-band: Yahoo shows a code on-screen instead of redirecting anywhere

CREDS_DIR = Path(__file__).resolve().parent.parent / ".credentials"
APP_CREDS_PATH = CREDS_DIR / "yahoo_app.json"
TOKENS_PATH = CREDS_DIR / "yahoo_tokens.json"


# ---------------------------------------------------------------------------
# Local credential/token storage
# ---------------------------------------------------------------------------
def save_app_credentials(client_id: str, client_secret: str) -> None:
    CREDS_DIR.mkdir(parents=True, exist_ok=True)
    with open(APP_CREDS_PATH, "w", encoding="utf-8") as f:
        json.dump({"client_id": client_id, "client_secret": client_secret}, f)


def load_app_credentials() -> dict | None:
    if not APP_CREDS_PATH.exists():
        return None
    with open(APP_CREDS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_tokens(tokens: dict) -> None:
    CREDS_DIR.mkdir(parents=True, exist_ok=True)
    tokens = dict(tokens)
    tokens["obtained_at"] = time.time()
    with open(TOKENS_PATH, "w", encoding="utf-8") as f:
        json.dump(tokens, f)


def load_tokens() -> dict | None:
    if not TOKENS_PATH.exists():
        return None
    with open(TOKENS_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# OAuth2 flow
# ---------------------------------------------------------------------------
def build_authorization_url(client_id: str) -> str:
    """URL to open in a real browser. The user logs into Yahoo there themselves
    and gets back a short verifier code to paste into exchange_code_for_tokens."""
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "language": "en-us",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(client_id: str, client_secret: str, code: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()
    save_tokens(tokens)
    return tokens


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()
    save_tokens(tokens)
    return tokens


def get_valid_access_token() -> str:
    """Returns a usable access token, refreshing automatically if the stored
    one has expired. Raises if no tokens/app credentials are saved yet --
    run scripts/yahoo_auth.py first."""
    app_creds = load_app_credentials()
    tokens = load_tokens()
    if not app_creds or not tokens:
        raise RuntimeError("No Yahoo credentials saved yet -- run scripts/yahoo_auth.py first.")

    expires_at = tokens.get("obtained_at", 0) + tokens.get("expires_in", 0)
    if time.time() < expires_at - 60:  # 60s safety margin
        return tokens["access_token"]

    refreshed = refresh_access_token(app_creds["client_id"], app_creds["client_secret"], tokens["refresh_token"])
    return refreshed["access_token"]


# ---------------------------------------------------------------------------
# Defensive JSON helpers -- Yahoo's fantasy API JSON is deeply/awkwardly
# nested from its XML origins, so we search by key rather than assume an
# exact path.
# ---------------------------------------------------------------------------
def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def find_dicts_with_keys(obj, required_keys: set) -> list[dict]:
    return [d for d in _walk(obj) if required_keys.issubset(d.keys())]


def _get(access_token: str, path: str) -> dict:
    resp = requests.get(
        f"{FANTASY_BASE}/{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"format": "json"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Fantasy Sports API calls
# ---------------------------------------------------------------------------
def get_user_leagues(access_token: str, game_code: str = "nfl") -> list[dict]:
    """This user's leagues for the given game (nfl by default). Returns
    deduplicated {league_key, league_id, name} dicts."""
    data = _get(access_token, f"users;use_login=1/games;game_codes={game_code}/leagues")
    found = find_dicts_with_keys(data, {"league_key", "league_id", "name"})
    seen = {}
    for d in found:
        seen[d["league_key"]] = {"league_key": d["league_key"], "league_id": d["league_id"], "name": d["name"]}
    return list(seen.values())


def get_league_settings(access_token: str, league_key: str) -> dict:
    """Raw settings response -- roster_positions and stat_categories/stat_modifiers
    are in here somewhere; use find_dicts_with_keys to pull out what you need."""
    return _get(access_token, f"league/{league_key}/settings")


def get_league_standings(access_token: str, league_key: str) -> list[dict]:
    """One row per team: name, wins, losses, ties, points_for, points_against, rank."""
    data = _get(access_token, f"league/{league_key}/standings")
    teams = find_dicts_with_keys(data, {"name", "team_standings"})
    rows = []
    for t in teams:
        standings = t.get("team_standings", {})
        outcome = standings.get("outcome_totals", {})
        rows.append({
            "team": t.get("name"),
            "rank": standings.get("rank"),
            "wins": outcome.get("wins"),
            "losses": outcome.get("losses"),
            "ties": outcome.get("ties"),
            "points_for": standings.get("points_for"),
            "points_against": standings.get("points_against"),
        })
    return rows


def get_league_scoreboard(access_token: str, league_key: str, week: int | None = None) -> list[dict]:
    """Matchup scores for a given week (current week if None). One row per
    matchup with each side's team name and points -- this is what would feed
    real weekly payout tracking (high point, point differential, etc.)."""
    path = f"league/{league_key}/scoreboard"
    if week is not None:
        path += f";week={week}"
    data = _get(access_token, path)
    matchups = find_dicts_with_keys(data, {"week", "status"})
    rows = []
    for m in matchups:
        teams = find_dicts_with_keys(m, {"name", "team_points"})
        sides = [{"team": t.get("name"), "points": t.get("team_points", {}).get("total")} for t in teams]
        if sides:
            rows.append({"week": m.get("week"), "teams": sides})
    return rows

"""
Run this yourself, interactively, to connect your Yahoo account. You'll
log into Yahoo in your own browser -- this script never sees your
password, only the short verifier code Yahoo shows you afterward.

One-time setup before running this:
    1. Go to https://developer.yahoo.com/apps/create/
    2. Create an app: any name, API permission = "Fantasy Sports" (Read),
       Redirect URI(s) = "oob"
    3. Copy the Client ID and Client Secret it gives you

Then:
    python scripts/yahoo_auth.py
"""
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from optimizer.yahoo_client import (
    build_authorization_url,
    exchange_code_for_tokens,
    get_user_leagues,
    load_app_credentials,
    save_app_credentials,
)


def main() -> None:
    creds = load_app_credentials()
    if creds:
        print(f"Using saved app credentials (client_id ending in ...{creds['client_id'][-6:]}).")
        reuse = input("Use these? [Y/n] ").strip().lower()
        if reuse == "n":
            creds = None

    if not creds:
        client_id = input("Yahoo Client ID: ").strip()
        client_secret = input("Yahoo Client Secret: ").strip()
        save_app_credentials(client_id, client_secret)
        creds = {"client_id": client_id, "client_secret": client_secret}

    auth_url = build_authorization_url(creds["client_id"])
    print("\nOpening this URL in your browser -- log into Yahoo there yourself:")
    print(auth_url)
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    code = input("\nAfter logging in, Yahoo will show you a code. Paste it here: ").strip()

    print("Exchanging code for tokens...")
    exchange_code_for_tokens(creds["client_id"], creds["client_secret"], code)
    print("Connected. Tokens saved to .credentials/yahoo_tokens.json (gitignored).")

    print("\nFetching your NFL fantasy leagues to confirm it worked...")
    from optimizer.yahoo_client import get_valid_access_token
    access_token = get_valid_access_token()
    leagues = get_user_leagues(access_token)
    if not leagues:
        print("No leagues found -- something may be off with the response parsing. See optimizer/yahoo_client.py.")
    for league in leagues:
        print(f"  {league['name']}  (league_key={league['league_key']}, league_id={league['league_id']})")


if __name__ == "__main__":
    main()

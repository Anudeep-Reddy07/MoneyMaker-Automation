#!/usr/bin/env python3
"""One-time OAuth2 flow to obtain a YouTube API refresh token.

Run this ONCE on your local machine to authorize YouTube access.
The printed values go into GitHub Secrets for the automated pipeline.

Prerequisites:
    pip install google-auth-oauthlib

Setup:
    1. Go to https://console.cloud.google.com/
    2. Create a project (or select an existing one)
    3. Enable "YouTube Data API v3" at APIs & Services → Library
    4. Go to APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
    5. Application type: "Desktop app"
    6. Download the JSON file (client_secret_xxx.json)
    7. Run:  python scripts/get_youtube_token.py --client-secrets client_secret_xxx.json
    8. A browser window opens — sign in and authorize "YouTube upload" access
    9. Copy the 3 printed values into GitHub Secrets

The refresh token does NOT expire unless you revoke it or change your
Google password, so you only need to do this once.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Get YouTube OAuth2 refresh token for CI automation"
    )
    parser.add_argument(
        "--client-secrets",
        required=True,
        help="Path to the OAuth2 client_secret JSON file from Google Cloud Console",
    )
    args = parser.parse_args()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
    except ImportError:
        print(
            "Missing dependency. Install it first:\n"
            "  pip install google-auth-oauthlib\n",
            file=sys.stderr,
        )
        raise SystemExit(1)

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secrets, scopes)
    credentials = flow.run_local_server(port=8090)

    # Read client ID and secret from the downloaded secrets file.
    with open(args.client_secrets, encoding="utf-8") as f:
        secrets = json.load(f)

    client_config = secrets.get("installed", secrets.get("web", {}))

    print("\n" + "=" * 64)
    print("  SUCCESS — Add these 3 values as GitHub Secrets")
    print("=" * 64)
    print(f"\n  YOUTUBE_CLIENT_ID      = {client_config['client_id']}")
    print(f"  YOUTUBE_CLIENT_SECRET  = {client_config['client_secret']}")
    print(f"  YOUTUBE_REFRESH_TOKEN  = {credentials.refresh_token}")
    print("\n" + "=" * 64)
    print(
        "\nGo to: Repo → Settings → Secrets and variables → Actions → New repository secret"
    )
    print("Add each of the 3 values above as a separate secret.\n")


if __name__ == "__main__":
    main()

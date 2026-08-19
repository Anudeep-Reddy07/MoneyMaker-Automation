#!/usr/bin/env python3
"""Upload a video to YouTube using the YouTube Data API v3.

Uses the OAuth2 refresh-token flow so no browser interaction is needed,
making it suitable for CI/CD environments like GitHub Actions.

Usage:
    python scripts/upload_youtube.py \
        --video-file storage/tasks/<id>/final-1.mp4 \
        --title "How AI is changing everyday life" \
        --description "An AI-generated short about artificial intelligence."

Required environment variables:
    YOUTUBE_CLIENT_ID       OAuth2 client ID from Google Cloud Console
    YOUTUBE_CLIENT_SECRET   OAuth2 client secret
    YOUTUBE_REFRESH_TOKEN   Long-lived refresh token from one-time OAuth flow
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

# Retry configuration for transient upload failures.
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5


def get_access_token(
    client_id: str, client_secret: str, refresh_token: str
) -> str:
    """Exchange a refresh token for a short-lived access token."""
    resp = requests.post(
        YOUTUBE_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(
            f"ERROR: Token exchange failed ({resp.status_code}): {resp.text}",
            file=sys.stderr,
        )
        sys.exit(1)
    token = resp.json().get("access_token")
    if not token:
        print("ERROR: No access_token in response", file=sys.stderr)
        sys.exit(1)
    print("✓ Access token obtained", file=sys.stderr)
    return token


def upload_video(
    access_token: str,
    video_file: str,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "28",  # Science & Technology
    privacy_status: str = "public",
) -> dict:
    """Upload a video using the YouTube resumable-upload protocol."""
    metadata = {
        "snippet": {
            "title": title[:100],  # YouTube title limit
            "description": description[:5000],
            "tags": tags[:30],  # YouTube allows max ~500 chars of tags
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
        },
    }

    file_size = os.path.getsize(video_file)
    print(
        f"Uploading {video_file} ({file_size / 1_048_576:.1f} MB)...",
        file=sys.stderr,
    )

    # Step 1: Initiate a resumable upload session.
    init_resp = requests.post(
        f"{YOUTUBE_UPLOAD_URL}?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
            "X-Upload-Content-Length": str(file_size),
            "X-Upload-Content-Type": "video/mp4",
        },
        json=metadata,
        timeout=30,
    )
    if init_resp.status_code not in (200, 308):
        print(
            f"ERROR: Upload init failed ({init_resp.status_code}): {init_resp.text}",
            file=sys.stderr,
        )
        sys.exit(1)

    upload_url = init_resp.headers.get("Location")
    if not upload_url:
        print("ERROR: No Location header in upload init response", file=sys.stderr)
        sys.exit(1)

    # Step 2: Upload the video bytes (with retry for transient failures).
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with open(video_file, "rb") as f:
                upload_resp = requests.put(
                    upload_url,
                    headers={
                        "Content-Length": str(file_size),
                        "Content-Type": "video/mp4",
                    },
                    data=f,
                    timeout=600,
                )
            if upload_resp.status_code in (200, 201):
                break
            print(
                f"WARNING: Upload attempt {attempt} returned {upload_resp.status_code}",
                file=sys.stderr,
            )
        except requests.RequestException as exc:
            print(
                f"WARNING: Upload attempt {attempt} failed: {exc}",
                file=sys.stderr,
            )
        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF_SECONDS * attempt
            print(f"Retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)
    else:
        print("ERROR: All upload attempts failed", file=sys.stderr)
        sys.exit(1)

    result = upload_resp.json()
    video_id = result.get("id", "unknown")
    print(
        f"✓ Upload complete: https://youtube.com/shorts/{video_id}",
        file=sys.stderr,
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a video to YouTube")
    parser.add_argument(
        "--video-file", required=True, help="Path to the .mp4 file"
    )
    parser.add_argument("--title", required=True, help="Video title")
    parser.add_argument(
        "--description", default="", help="Video description"
    )
    parser.add_argument(
        "--tags",
        default="AI,shorts,technology,science,education",
        help="Comma-separated tags",
    )
    parser.add_argument(
        "--privacy",
        default="public",
        choices=["public", "unlisted", "private"],
        help="Video privacy status",
    )
    args = parser.parse_args()

    # ── Read credentials from environment ───────────────────────────────
    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()

    missing = []
    if not client_id:
        missing.append("YOUTUBE_CLIENT_ID")
    if not client_secret:
        missing.append("YOUTUBE_CLIENT_SECRET")
    if not refresh_token:
        missing.append("YOUTUBE_REFRESH_TOKEN")
    if missing:
        print(
            f"ERROR: Missing required environment variables: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.path.isfile(args.video_file):
        print(f"ERROR: Video file not found: {args.video_file}", file=sys.stderr)
        sys.exit(1)

    # ── Execute ─────────────────────────────────────────────────────────
    access_token = get_access_token(client_id, client_secret, refresh_token)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    result = upload_video(
        access_token=access_token,
        video_file=args.video_file,
        title=args.title,
        description=args.description,
        tags=tags,
        privacy_status=args.privacy,
    )

    # JSON result to stdout for the workflow to capture if needed.
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Upload videos to YouTube with topic-relevant metadata."""
from __future__ import annotations
import argparse, json, os, sys, time
import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
MAX_RETRIES = 3


def get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    response = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=30)
    if response.status_code != 200:
        print(f"ERROR: Token exchange failed ({response.status_code}): {response.text}", file=sys.stderr)
        sys.exit(1)
    token = response.json().get("access_token")
    if not token:
        print("ERROR: No access_token in response", file=sys.stderr)
        sys.exit(1)
    return token


def format_viral_metadata(topic: str, custom_description: str = "", custom_tags: str = "") -> tuple[str, str, list[str]]:
    clean_topic = topic.strip()
    lower_topic = clean_topic.lower()
    animal_words = (
        "animal", "animals", "wildlife", "elephant", "lion", "tiger", "wolf", "bird",
        "owl", "dolphin", "whale", "shark", "octopus", "crow", "bat", "ant", "dog",
        "cat", "snake", "bear", "monkey", "insect", "reptile", "mammal", "fish",
        "frog", "penguin", "panda", "eagle", "spider", "species", "nature"
    )
    is_animal = any(word in lower_topic for word in animal_words)
    suffix = " 🔥 #shorts #viral"
    if "#shorts" not in lower_topic:
        title = f"{clean_topic[:100 - len(suffix)].rstrip()}{suffix}"
    else:
        title = clean_topic[:100]

    if custom_description.strip() and "moneyprinter" not in custom_description.lower():
        description = custom_description.strip()
    elif is_animal:
        description = (
            f"🐾 {clean_topic}\n\n"
            "Discover fascinating animal behavior, wildlife facts, and incredible facts from nature.\n\n"
            "👍 Like if you learned something new!\n"
            "💬 Share your thoughts in the comments.\n"
            "🔔 Subscribe for more fascinating facts and wildlife stories!\n\n"
            "#shorts #viral #trending #animals #wildlife #nature #animalfacts "
            "#interestingfacts #animalbehavior #wildlifefacts #naturelovers #facts"
        )
    else:
        description = (
            f"✨ {clean_topic}\n\n"
            "💡 Watch till the end for the full breakdown!\n\n"
            "👍 Like if you learned something new today!\n"
            "💬 Drop your thoughts in the comments below!\n"
            "🔔 Subscribe for more facts and insights!\n\n"
            "#shorts #viral #trending #facts #knowledge #education"
        )

    if custom_tags.strip():
        tags = [tag.strip() for tag in custom_tags.split(",") if tag.strip()]
    elif is_animal:
        tags = [
            "shorts", "youtube shorts", "viral", "trending", "animals", "wildlife",
            "nature", "animal facts", "wildlife facts", "interesting facts",
            "animal behavior", "nature facts", "animal documentary", "facts"
        ]
    else:
        tags = ["shorts", "youtube shorts", "viral", "trending", "facts", "knowledge", "education"]
    return title, description, tags


def upload_video(access_token: str, video_file: str, title: str, description: str, tags: list[str], category_id: str = "28", privacy_status: str = "public") -> dict:
    metadata = {
        "snippet": {"title": title[:100], "description": description[:5000], "tags": tags[:30], "categoryId": category_id},
        "status": {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": False, "embeddable": True},
    }
    file_size = os.path.getsize(video_file)
    init_response = requests.post(
        f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=utf-8", "X-Upload-Content-Length": str(file_size), "X-Upload-Content-Type": "video/mp4"},
        json=metadata, timeout=30,
    )
    if init_response.status_code not in (200, 308):
        print(f"ERROR: Upload init failed ({init_response.status_code}): {init_response.text}", file=sys.stderr)
        sys.exit(1)
    upload_url = init_response.headers.get("Location")
    if not upload_url:
        print("ERROR: No upload URL returned", file=sys.stderr)
        sys.exit(1)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with open(video_file, "rb") as video:
                response = requests.put(upload_url, headers={"Content-Length": str(file_size), "Content-Type": "video/mp4"}, data=video, timeout=600)
            if response.status_code in (200, 201):
                return response.json()
            print(f"WARNING: Upload attempt {attempt} returned {response.status_code}", file=sys.stderr)
        except requests.RequestException as error:
            print(f"WARNING: Upload attempt {attempt} failed: {error}", file=sys.stderr)
        if attempt < MAX_RETRIES:
            time.sleep(5 * attempt)
    print("ERROR: All upload attempts failed", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a video to YouTube")
    parser.add_argument("--video-file", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    args = parser.parse_args()
    credentials = {name: os.environ.get(name, "").strip() for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")}
    missing = [name for name, value in credentials.items() if not value]
    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(args.video_file):
        print(f"ERROR: Video file not found: {args.video_file}", file=sys.stderr)
        sys.exit(1)
    title, description, tags = format_viral_metadata(args.title, args.description, args.tags)
    result = upload_video(get_access_token(**credentials), args.video_file, title, description, tags, privacy_status=args.privacy)
    video_id = result.get("id", "unknown")
    print(f"Upload complete: https://youtube.com/shorts/{video_id}", file=sys.stderr)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

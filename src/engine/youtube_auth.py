"""YouTube OAuth posting backend for the 143 Engine.

Handles OAuth 2.0 authentication and Shorts uploads via the
YouTube Data API v3. Uses google-auth-oauthlib for the
installed-app flow.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

CREDENTIALS_DIR = Path(__file__).resolve().parent.parent.parent / ".credentials"
TOKEN_PATH = CREDENTIALS_DIR / "youtube_token.json"
CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def _get_credentials() -> object | None:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest

    if TOKEN_PATH.exists():
        raw = json.loads(TOKEN_PATH.read_text())
        if "client_id" not in raw:
            raw["client_id"] = CLIENT_ID
        if "client_secret" not in raw:
            raw["client_secret"] = CLIENT_SECRET

        creds = Credentials.from_authorized_user_info(raw, YOUTUBE_SCOPES)
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
            TOKEN_PATH.write_text(creds.to_json())
            return creds

    log.warning("No valid YouTube token. Run: bin/auth-youtube url")
    return None


def upload_short(
    video_path: str,
    title: str,
    description: str,
    tags: list[str] | None = None,
    category_id: str = "22",
) -> dict:
    creds = _get_credentials()
    if not creds:
        return {"status": "failed", "error": "YouTube OAuth not configured"}

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:30],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/*",
        resumable=True,
        chunksize=1024 * 1024 * 5,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("Upload progress: %d%%", int(status.progress() * 100))

    video_id = response.get("id", "")
    log.info("Uploaded Short: https://www.youtube.com/shorts/%s", video_id)

    return {
        "status": "posted",
        "video_id": video_id,
        "url": f"https://www.youtube.com/shorts/{video_id}",
        "title": title,
    }


def post_short_from_manifest(post: dict) -> dict:
    """Post a YouTube Short using metadata from the distribution manifest.

    Requires the video file to be available locally. For now, this
    returns a dry-run result until we have the actual video files
    downloaded and processed.
    """
    video_id = post.get("video_id", "")
    video_path = Path(__file__).resolve().parent.parent.parent / "data" / "clips" / f"{video_id}.mp4"

    if not video_path.exists():
        return {
            "status": "dry_run",
            "post_id": None,
            "error": f"Video file not found: {video_path}",
            "note": "Run ingest + clip generation before posting",
        }

    return upload_short(
        video_path=str(video_path),
        title=post.get("title", ""),
        description=post.get("caption", ""),
        tags=post.get("themes", []),
    )


def verify_auth() -> dict:
    """Check OAuth status. Returns config state without triggering auth flow."""
    if not CLIENT_ID or not CLIENT_SECRET:
        return {
            "configured": False,
            "reason": "Missing YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET env vars",
        }
    if TOKEN_PATH.exists():
        return {"configured": True, "authenticated": True, "token_path": str(TOKEN_PATH)}
    return {"configured": True, "authenticated": False, "reason": "No saved token — run upload to trigger OAuth flow"}

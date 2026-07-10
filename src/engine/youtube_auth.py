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
    if not CLIENT_ID or not CLIENT_SECRET:
        log.warning("YouTube OAuth not configured: missing CLIENT_ID or CLIENT_SECRET")
        return None

    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_info(
            json.loads(TOKEN_PATH.read_text()), YOUTUBE_SCOPES
        )
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request as GoogleRequest
            creds.refresh(GoogleRequest())
            TOKEN_PATH.write_text(creds.to_json())
            return creds

    client_config = {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, YOUTUBE_SCOPES)
    creds = flow.run_local_server(port=0)
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    return creds


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

import json
import logging
import os
import time
from pathlib import Path

import urllib.request

log = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
OUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "raw"


def _youtube_get(endpoint: str, params: dict) -> dict:
    params = {k: v for k, v in params.items() if v is not None}
    params["key"] = YOUTUBE_API_KEY
    qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    url = f"{YOUTUBE_API_BASE}/{endpoint}?{qs}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_playlist_videos(playlist_id: str, max_results: int = 50) -> list[dict]:
    videos = []
    page_token = None

    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": min(max_results, 50),
        }
        if page_token:
            params["pageToken"] = page_token

        data = _youtube_get("playlistItems", params)
        items = data.get("items", [])
        videos.extend(items)
        log.info("Fetched %d items (total: %d)", len(items), len(videos))

        page_token = data.get("nextPageToken")
        if not page_token or len(videos) >= max_results:
            break
        time.sleep(0.5)

    return videos


def fetch_video_details(video_ids: list[str]) -> list[dict]:
    details = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        data = _youtube_get(
            "videos",
            {
                "part": "snippet,contentDetails,statistics",
                "id": ",".join(batch),
            },
        )
        details.extend(data.get("items", []))
        if i + 50 < len(video_ids):
            time.sleep(0.5)
    return details


def ingest_channel(channel: dict) -> dict:
    name = channel["name"]
    playlist_id = channel["uploads_playlist"]

    log.info("Ingesting channel: %s (%s)", name, playlist_id)

    playlist_items = fetch_playlist_videos(playlist_id)
    video_ids = [item["contentDetails"]["videoId"] for item in playlist_items]
    video_details = fetch_video_details(video_ids)

    video_lookup = {v["id"]: v for v in video_details}

    enriched = []
    for item in playlist_items:
        vid = item["contentDetails"]["videoId"]
        detail = video_lookup.get(vid, {})
        statistics = detail.get("statistics", {})
        snippet = item.get("snippet", {})
        enriched.append(
            {
                "video_id": vid,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt", ""),
                "channel_id": snippet.get("channelId", ""),
                "channel_name": snippet.get("channelTitle", ""),
                "tags": detail.get("snippet", {}).get("tags", []),
                "duration": detail.get("contentDetails", {}).get("duration", ""),
                "definition": detail.get("contentDetails", {}).get("definition", ""),
                "view_count": int(statistics.get("viewCount", 0)),
                "like_count": int(statistics.get("likeCount", 0)),
                "comment_count": int(statistics.get("commentCount", 0)),
                "thumbnails": snippet.get("thumbnails", {}),
                "position": item.get("snippet", {}).get("position", 0),
            }
        )

    return {"channel": name, "channel_id": channel["id"], "video_count": len(enriched), "videos": enriched}


def run(config_path: str | None = None) -> None:
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY environment variable is not set")

    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent.parent / "configs" / "channels.json")

    config = json.loads(Path(config_path).read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for channel in config.get("channels", []):
        if not channel.get("enabled", True):
            continue
        result = ingest_channel(channel)
        out_path = OUT_DIR / f"{channel['handle'].lstrip('@')}.json"
        out_path.write_text(json.dumps(result, indent=2, default=str))
        log.info("Saved %d videos to %s", result["video_count"], out_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run()

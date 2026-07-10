"""Distribution engine: platform-optimized content generation and scheduling.

Reads the scored distribution manifest and generates platform-specific posts
with optimized captions, hashtags, and timing. Pluggable backends for actual
posting — dry-run for development, real APIs when keys are configured.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = PROJECT_ROOT / "data" / "processed" / "distribution_manifest.json"

PLATFORM_CONFIG = {
    "youtube_shorts": {
        "max_duration": 60,
        "aspect_ratio": "9:16",
        "max_hashtags": 5,
        "hashtag_prefix": "#",
        "caption_max_chars": 250,
        "optimal_times_utc": [13, 15, 17, 22],  # UTC hours
        "content_type": "shorts",
    },
    "tiktok": {
        "max_duration": 180,
        "aspect_ratio": "9:16",
        "max_hashtags": 5,
        "hashtag_prefix": "#",
        "caption_max_chars": 2200,
        "optimal_times_utc": [13, 16, 19, 23],
        "content_type": "short",
    },
}


def load_manifest(path: str | None = None) -> dict:
    p = Path(path) if path else MANIFEST_PATH
    return json.loads(p.read_text())


def optimize_caption(video: dict, platform: str) -> str:
    cfg = PLATFORM_CONFIG[platform]
    hook = video.get("caption_hook", video.get("title", ""))

    base_hashtags = ["#MisterRogers", "#KindnessMatters", "#143Engine"]
    if platform == "youtube_shorts":
        base_hashtags += ["#Shorts"]
    if platform == "tiktok":
        base_hashtags += ["#FYP", "#Viral"]

    hashtags = " ".join(base_hashtags[: cfg["max_hashtags"]])

    caption = f"{hook}\n\n{hashtags}"
    if len(caption) > cfg["caption_max_chars"]:
        caption = caption[: cfg["caption_max_chars"] - 3] + "..."

    return caption


def generate_posts(
    manifest: dict,
    platforms: list[str] | None = None,
    top_n: int = 5,
    min_composite: float = 7.0,
) -> list[dict]:
    platforms = platforms or list(PLATFORM_CONFIG.keys())
    videos = manifest.get("videos", [])

    posts = []
    for video in videos:
        kindness = video.get("kindness_score", 0)
        virality = video.get("virality_potential", 0)
        composite = (kindness + virality) / 2

        if composite < min_composite:
            continue

        for platform in platforms:
            if platform not in PLATFORM_CONFIG:
                continue

            target = video.get("target_platform", "")
            if target and target != "none" and platform not in target:
                continue

            posts.append(
                {
                    "video_id": video["video_id"],
                    "title": video["title"],
                    "platform": platform,
                    "caption": optimize_caption(video, platform),
                    "kindness_score": kindness,
                    "virality_potential": virality,
                    "composite_score": round(composite, 1),
                    "themes": video.get("thematic_tags", []),
                    "emotional_tone": video.get("emotional_tone", []),
                    "view_count": video.get("view_count", 0),
                    "status": "queued",
                }
            )

    ranked = sorted(posts, key=lambda p: p["composite_score"], reverse=True)
    return ranked[:top_n * len(platforms)]


def schedule_posts(posts: list[dict], posts_per_day: int = 2) -> list[dict]:
    now = datetime.now(timezone.utc)
    scheduled = []
    post_index = 0

    for day_offset in range(14):
        day = now + timedelta(days=day_offset)
        for platform in PLATFORM_CONFIG:
            cfg = PLATFORM_CONFIG[platform]
            for hour in cfg["optimal_times_utc"][:posts_per_day]:
                if post_index >= len(posts):
                    break
                post_time = day.replace(hour=hour, minute=0, second=0, microsecond=0)
                if post_time <= now:
                    continue

                post = dict(posts[post_index])
                post["scheduled_at"] = post_time.isoformat()
                post["status"] = "scheduled"
                scheduled.append(post)
                post_index += 1
        if post_index >= len(posts):
            break

    return scheduled


def post_to_platform(post: dict, dry_run: bool = True) -> dict:
    if dry_run:
        post["status"] = "dry_run"
        post["posted_at"] = None
        post["post_id"] = None
        return post

    platform = post["platform"]
    if platform == "youtube_shorts":
        return _post_youtube_short(post)
    elif platform == "tiktok":
        return _post_tiktok(post)
    else:
        post["status"] = "unsupported"
        post["error"] = f"Platform {platform} not supported"
        return post


def _post_youtube_short(post: dict) -> dict:
    api_key = __import__("os").environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        post["status"] = "failed"
        post["error"] = "YOUTUBE_API_KEY not set"
        return post

    # YouTube video upload requires OAuth 2.0, not just API key.
    # For now, fall back to dry-run with a note.
    # TODO: implement OAuth flow via google-auth-oauthlib
    post["status"] = "dry_run"
    post["error"] = "YouTube upload requires OAuth (not yet configured)"
    return post


def _post_tiktok(post: dict) -> dict:
    # TikTok Content Posting API requires developer app registration
    # TODO: implement TikTok API via access token
    post["status"] = "dry_run"
    post["error"] = "TikTok API requires developer app (not yet configured)"
    return post


def publish_all(posts: list[dict], dry_run: bool = True) -> list[dict]:
    results = []
    for post in posts:
        result = post_to_platform(post, dry_run=dry_run)
        results.append(result)
    return results


def export_schedule(posts: list[dict], path: str | None = None) -> str:
    out = path or str(PROJECT_ROOT / "data" / "processed" / "publishing_schedule.json")
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "pipeline": "143-engine-distribute",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_posts": len(posts),
        "platforms": list(set(p["platform"] for p in posts)),
        "schedule": [
            {
                "video_id": p["video_id"],
                "title": p["title"],
                "platform": p["platform"],
                "caption": p["caption"],
                "scheduled_at": p.get("scheduled_at"),
                "status": p.get("status", "queued"),
                "composite_score": p.get("composite_score"),
            }
            for p in posts
        ],
    }

    Path(out).write_text(json.dumps(manifest, indent=2, default=str))
    log.info("Publishing schedule written: %s (%d posts)", out, len(posts))
    return out


def run(manifest_path: str | None = None, top_n: int = 5, dry_run: bool = True) -> None:
    manifest = load_manifest(manifest_path)
    platforms = ["youtube_shorts", "tiktok"]

    posts = generate_posts(manifest, platforms=platforms, top_n=top_n, min_composite=6.0)
    log.info("Generated %d posts across %d platforms", len(posts), len(platforms))

    scheduled = schedule_posts(posts, posts_per_day=2)
    log.info("Scheduled %d posts over the next 14 days", len(scheduled))

    results = publish_all(scheduled, dry_run=dry_run)

    dry = sum(1 for r in results if r.get("status") == "dry_run")
    queued = sum(1 for r in results if r.get("status") == "scheduled")
    failed = sum(1 for r in results if r.get("status") == "failed")
    log.info("Publish results: %d dry-run, %d queued, %d failed", dry, queued, failed)

    export_schedule(results)

    for r in results[:8]:
        emoji = "📋" if r["status"] == "dry_run" else "✅" if r["status"] == "scheduled" else "❌"
        platform_icon = "📺" if r["platform"] == "youtube_shorts" else "🎵"
        time_str = r.get("scheduled_at", "unscheduled")[:16].replace("T", " ")
        print(f"  {emoji} {platform_icon} [{r['composite_score']:.1f}] {time_str} | {r['title'][:50]}")
        print(f"     {r['caption'][:80]}")
        print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run()

"""Clip downloader using yt-dlp.

Downloads the top-scored Shorts from the distribution manifest
for use in the automated posting pipeline.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = PROJECT_ROOT / "data" / "processed" / "distribution_manifest.json"
CLIPS_DIR = PROJECT_ROOT / "data" / "clips"


def download_clip(video_id: str, output_dir: Path | None = None) -> Path | None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_dir = output_dir or CLIPS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / f"{video_id}.%(ext)s")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "--format", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--quiet",
        "--no-warnings",
        url,
    ]

    try:
        subprocess.run(cmd, check=True, timeout=300)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning("Download failed for %s: %s", video_id, e)
        return None

    result = out_dir / f"{video_id}.mp4"
    if result.exists():
        log.info("Downloaded: %s (%s bytes)", result.name, result.stat().st_size)
        return result
    return None


def download_top_shorts(manifest_path: str | None = None, top_n: int = 5) -> list[dict]:
    p = Path(manifest_path) if manifest_path else MANIFEST_PATH
    manifest = json.loads(p.read_text())
    videos = manifest.get("videos", [])

    downloaded = []
    for video in videos:
        video_id = video.get("video_id", "")
        title = video.get("title", "")
        platform = video.get("target_platform", "")

        if "shorts" not in platform and "#shorts" not in title.lower():
            continue

        kindness = video.get("kindness_score", 0)
        virality = video.get("virality_potential", 0)

        log.info("Downloading: [k=%.1f v=%.1f] %s", kindness, virality, title[:60])
        path = download_clip(video_id)

        downloaded.append({
            "video_id": video_id,
            "title": title,
            "kindness_score": kindness,
            "virality_potential": virality,
            "file_path": str(path) if path else None,
            "status": "downloaded" if path else "failed",
        })

        if len([d for d in downloaded if d["status"] == "downloaded"]) >= top_n:
            break

    return downloaded


def run(manifest_path: str | None = None, top_n: int = 3) -> list[Path]:
    results = download_top_shorts(manifest_path, top_n=top_n)
    paths = []
    for r in results:
        if r["status"] == "failed":
            print(f'  ❌ {r["video_id"]} — download failed')
        else:
            print(f'  ✅ {r["video_id"]} — {r["file_path"]}')
            paths.append(Path(r["file_path"]))

    return paths


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run()

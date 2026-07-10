"""Scoring engine: rates clips on kindness, emotional tone, and virality potential.

Uses Dream Lab's LLM routing via deepseek adapter for text-based scoring.
Each video is scored on:
  - kindness_score     (0-10): how strongly it conveys empathy, warmth, care
  - emotional_tone     (calm, joyful, reflective, empowering, etc.)
  - virality_potential (0-10): hook strength, shareability, current-event relevance
  - thematic_tags      (empathy, community, self-acceptance, curiosity, ...)
  - best_clip_moment   (estimated timestamp of the most kindness-dense moment)
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

SCORING_PROMPT = """You are an expert content analyst specializing in emotional impact and kindness amplification.

Analyze this video's metadata and provide scores in strict JSON format. Consider the title, description, and tags as context for the video's content.

VIDEO TITLE: {title}
VIDEO DESCRIPTION: {description}
TAGS: {tags}
DURATION: {duration}
CURRENT VIEWS: {views}

Return ONLY valid JSON with no extra text:

{{
  "kindness_score": <float 0-10>,
  "kindness_rationale": "<one sentence why>",
  "emotional_tone": ["<primary>", "<secondary>"],
  "virality_potential": <float 0-10>,
  "virality_rationale": "<one sentence why>",
  "thematic_tags": ["<tag1>", "<tag2>", "..."],
  "best_clip_moment": "<estimated timestamp HH:MM:SS or 'full episode'>",
  "target_platform": "<youtube_shorts|tiktok|instagram|linkedin|none>",
  "caption_hook": "<one short, shareable caption for this clip>",
  "safe_for_brand": <true|false>,
  "requires_commentary": <true|false>
}}

Valid emotional_tone values: calm, joyful, reflective, empowering, curious, nostalgic, warm, playful, inspiring, gentle
Valid thematic_tags: empathy, community, self-acceptance, curiosity, kindness, resilience, creativity, friendship, gratitude, wonder, inclusion, patience, listening, celebration
"""


def score_video(video: dict, adapter: str = "deepseek", model: str = "") -> dict:
    from dreamlab.mcp.tools.execute import handle_execute

    prompt = SCORING_PROMPT.format(
        title=video["title"],
        description=video.get("description", "")[:500],
        tags=", ".join(video.get("tags", [])[:15]),
        duration=video.get("duration", "unknown"),
        views=video.get("view_count", 0),
    )

    result = handle_execute(
        {
            "task": prompt,
            "task_type": "review",
            "adapter": adapter,
            "model": model or "",
            "repo_path": str(Path(__file__).resolve().parent.parent.parent),
            "evaluate": False,
            "response_format": "json",
        }
    )

    try:
        parsed = json.loads(result.get("output", "{}"))
    except json.JSONDecodeError:
        log.warning("Failed to parse scoring output for %s: %s", video["video_id"], result.get("output", "")[:200])
        parsed = {
            "kindness_score": 0,
            "kindness_rationale": "parse error",
            "emotional_tone": ["unknown"],
            "virality_potential": 0,
            "virality_rationale": "parse error",
            "thematic_tags": [],
            "best_clip_moment": "",
            "target_platform": "none",
            "caption_hook": "",
            "safe_for_brand": True,
            "requires_commentary": False,
        }

    video["scores"] = parsed
    return video


def batch_score(videos: list[dict], adapter: str = "deepseek", model: str = "", max_workers: int = 4) -> list[dict]:
    from dreamlab.mcp.tools.pool_fan_out import handle_pool_fan_out

    tasks = [
        {
            "description": f"Score video {v['video_id']}: {v['title'][:60]}...",
            "task_type": "review",
        }
        for v in videos
    ]

    result = handle_pool_fan_out(
        tasks=tasks,
        max_workers=max_workers,
        adapter=adapter,
        model=model or "",
    )

    for i, video in enumerate(videos):
        if i < len(result.get("results", [])):
            worker_result = result["results"][i]
            try:
                video["scores"] = json.loads(worker_result.get("output", "{}"))
            except json.JSONDecodeError:
                log.warning("Parse error for video %s", video["video_id"])
                video["scores"] = {}

    return videos


def run(data_path: str | None = None, limit: int = 0) -> None:
    if data_path is None:
        data_path = str(Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "MisterRogersNeighborhood.json")

    data = json.loads(Path(data_path).read_text())
    videos = data["videos"]
    if limit:
        videos = videos[:limit]

    log.info("Scoring %d videos...", len(videos))

    for i, video in enumerate(videos):
        log.info("[%d/%d] Scoring: %s", i + 1, len(videos), video["title"][:60])
        score_video(video)

    out_path = Path(data_path).parent.parent / "scored" / Path(data_path).name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data["videos"] = videos
    out_path.write_text(json.dumps(data, indent=2, default=str))
    log.info("Saved scored data to %s", out_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run()

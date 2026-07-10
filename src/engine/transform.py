"""Transformation pipeline: transcribe → clip → caption → overlay.

Converts raw Mister Rogers videos into kindness-annotated Shorts
with word-level captions, AI commentary, and branded overlays.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CLIPS_DIR = PROJECT_ROOT / "data" / "clips"
OUTPUT_DIR = PROJECT_ROOT / "data" / "transformed"
WHISPER_MODEL = "base"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_PATH_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _llm(prompt: str) -> str:
    from dreamlab.platform.llm import get_adapter

    adapter = get_adapter("deepseek")
    result = adapter.invoke(prompt, model="", timeout=120)
    return (result.text or "").strip()


def _llm_json(prompt: str) -> dict:
    raw = _llm(prompt)
    try:
        if "```json" in raw:
            raw = raw.split("```json", 1)[-1].rsplit("```", 1)[0]
        elif raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        log.warning("JSON parse failed: %s", raw[:200])
        return {}


def transcribe(video_path: str) -> dict:
    log.info("Transcribing with Whisper (%s)...", WHISPER_MODEL)
    import whisper

    model = whisper.load_model(WHISPER_MODEL)
    result = model.transcribe(video_path, word_timestamps=True)
    log.info("Transcription: %d segments", len(result.get("segments", [])))
    return result


def find_best_segment(transcript: dict, kindness_context: str = "", duration_limit: int = 60) -> dict:
    segments = transcript.get("segments", [])
    if not segments:
        return {"start": 0, "end": duration_limit, "rationale": "no segments", "kindness_score": 0}

    segment_texts = []
    for seg in segments:
        t = seg.get("text", "").strip()
        if t:
            segment_texts.append(f'[{seg["start"]:.1f}-{seg["end"]:.1f}] {t}')

    full_text = "\n".join(segment_texts)
    context = kindness_context or "Mister Rogers teaching kindness, empathy, and emotional intelligence to children"

    prompt = f"""You are an expert at finding the most emotionally powerful moments in video transcripts.

Context: {context}

Below is a transcript with timestamps. Identify the best {duration_limit}-second segment that:
1. Contains the most kindness-dense or emotionally powerful moment
2. Has a clear message that resonates with modern audiences
3. Works as a standalone Short (self-contained, doesn't need prior context)

TRANSCRIPT:
{full_text[:3000]}

Reply with ONLY valid JSON:
{{"start": <float seconds>, "end": <float seconds>, "rationale": "<one sentence>", "kindness_score": <float 0-10>}}"""

    parsed = _llm_json(prompt)
    if not parsed:
        last_end = segments[-1]["end"] if segments else duration_limit
        return {"start": 0, "end": min(last_end, duration_limit), "rationale": "fallback", "kindness_score": 0}

    return {
        "start": float(parsed.get("start", 0)),
        "end": float(parsed.get("end", duration_limit)),
        "rationale": parsed.get("rationale", ""),
        "kindness_score": float(parsed.get("kindness_score", 0)),
    }


def extract_clip(video_path: str, start: float, end: float, output_path: str | None = None) -> str:
    out = output_path or str(CLIPS_DIR / f"clip_{int(start)}_{int(end)}.mp4")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    duration = end - start

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start), "-i", video_path, "-t", str(duration),
        "-c:v", "libx264", "-crf", "23", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", out,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    log.info("Extracted clip: %.1fs-%.1fs → %s", start, end, out)
    return out


def generate_commentary(transcript_segment: str, caption_hook: str = "", rationale: str = "") -> str:
    prompt = f"""You are writing commentary for a Mister Rogers kindness Short.

Context: {rationale}
Hook idea: {caption_hook}

Transcript of the selected moment:
{transcript_segment[:1000]}

Write a short (2-3 sentence) reflection that:
1. Explains why this moment matters
2. Connects it to modern life
3. Is warm like Fred Rogers would write

Keep it under 300 characters. No hashtags or emojis."""

    output = _llm(prompt)
    return output[:400] if output else "A moment of quiet kindness from Fred Rogers."


def generate_word_captions(transcript: dict, clip_start: float, clip_end: float) -> list[dict]:
    words = []
    for seg in transcript.get("segments", []):
        seg_start, seg_end = seg["start"], seg["end"]
        if seg_end < clip_start or seg_start > clip_end:
            continue
        text = seg.get("text", "").strip()
        if not text:
            continue
        raw_words = text.split()
        if not raw_words:
            continue
        seg_duration = max(seg_end - seg_start, 0.1)
        word_duration = seg_duration / len(raw_words)
        for i, w in enumerate(raw_words):
            ws = max(0, seg_start + i * word_duration - clip_start)
            we = ws + word_duration
            words.append({"word": w.strip(",.!?;:"), "start": ws, "end": we})
    return words


def build_caption_filter(words: list[dict]) -> str:
    if not words:
        return "null"

    tmpdir = Path(tempfile.mkdtemp(prefix="captions_"))
    filters = []
    current_line: list[str] = []
    current_start = words[0]["start"]
    chars_per_line = 24
    file_idx = 0

    def flush_line(line_text: str, start: float, duration: float) -> str:
        nonlocal file_idx
        tf = tmpdir / f"line_{file_idx:04d}.txt"
        file_idx += 1
        tf.write_text(line_text)
        return (
            f"drawtext=textfile='{tf}':fontfile={FONT_PATH}:fontsize=52:"
            f"fontcolor=white:bordercolor=black:borderw=3:"
            f"x=(w-text_w)/2:y=h-text_h-120:"
            f"enable='between(t,{start:.2f},{start + duration:.2f})'"
        )

    for i, w in enumerate(words):
        word = w["word"]
        test_text = " ".join(current_line + [word])
        if len(test_text) > chars_per_line and current_line:
            line_dur = max(w["start"] - current_start, 1.0)
            filters.append(flush_line(" ".join(current_line), current_start, line_dur))
            current_line = [word]
            current_start = w["start"]
        elif i == len(words) - 1:
            filters.append(flush_line(test_text, current_start, 2.0))
        else:
            current_line.append(word)
    return ",".join(filters)


def overlay_final(clip_path: str, captions: list[dict], commentary: str, output_path: str | None = None) -> str:
    out = output_path or str(OUTPUT_DIR / f"final_{Path(clip_path).stem}.mp4")
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    cf = build_caption_filter(captions)
    cm_file = Path(tempfile.mkdtemp(prefix="overlay_")) / "commentary.txt"
    cm_file.write_text(commentary)

    fc = (
        f"[0:v]"
        f"scale=1080:1920:force_original_aspect_ratio=decrease,"
        f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
        f"{cf},"
        f"drawtext=textfile='{cm_file}':fontfile={FONT_PATH_REGULAR}:fontsize=26:"
        f"fontcolor=white:line_spacing=8:box=1:boxcolor=black@0.6:boxborderw=15:"
        f"x=(w-text_w)/2:y=80:"
        f"enable='between(t,0.5,8)'"
        f"[vout]"
    )

    subprocess.run([
        "ffmpeg", "-y", "-i", clip_path, "-filter_complex", fc,
        "-map", "[vout]", "-map", "0:a",
        "-c:v", "libx264", "-crf", "23", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out,
    ], check=True, capture_output=True, text=True)

    log.info("Final Short: %s", out)
    return out


def transform(video_id: str, kindness_context: str = "", skip_download: bool = False) -> dict:
    video_path = CLIPS_DIR / f"{video_id}.mp4"

    if not skip_download and not video_path.exists():
        from src.engine.download import download_clip
        result = download_clip(video_id)
        if not result:
            return {"status": "failed", "error": "Download failed"}
        video_path = result

    if not video_path.exists():
        return {"status": "failed", "error": f"Video not found: {video_path}"}

    manifest_path = PROJECT_ROOT / "data" / "processed" / "distribution_manifest.json"
    video_meta = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for v in manifest.get("videos", []):
            if v.get("video_id") == video_id:
                video_meta = v
                break

    title = video_meta.get("title", "Mister Rogers Clip")
    themes = video_meta.get("thematic_tags", [])
    caption_hook = video_meta.get("caption_hook", "")

    log.info("Step 1/5: Transcribing %s...", title[:50])
    transcript = transcribe(str(video_path))

    kindness_ctx = kindness_context or f"Mister Rogers segment about {', '.join(themes[:3])}"

    log.info("Step 2/5: Finding best 60s segment...")
    best = find_best_segment(transcript, kindness_ctx)
    if best["start"] >= best["end"]:
        best = {"start": 0, "end": min(60, transcript.get("duration", 60)), "rationale": "auto", "kindness_score": 0}

    segment_text = ""
    for seg in transcript.get("segments", []):
        if best["start"] <= seg["start"] <= best["end"] or best["start"] <= seg["end"] <= best["end"]:
            segment_text += seg.get("text", "") + " "

    log.info("Step 3/5: Generating commentary...")
    commentary = generate_commentary(segment_text.strip(), caption_hook, best.get("rationale", ""))

    log.info("Step 4/5: Extracting clip...")
    clip_path = extract_clip(str(video_path), best["start"], best["end"])
    captions = generate_word_captions(transcript, best["start"], best["end"])

    log.info("Step 5/5: Rendering final Short with captions + commentary...")
    final_path = overlay_final(clip_path, captions, commentary)

    result = {
        "status": "transformed",
        "video_id": video_id,
        "title": title,
        "clip_start": best["start"],
        "clip_end": best["end"],
        "kindness_score": best.get("kindness_score", 0),
        "rationale": best.get("rationale", ""),
        "commentary": commentary,
        "segment_transcript": segment_text.strip()[:500],
        "word_count": len(captions),
        "output_path": final_path,
    }

    result_path = OUTPUT_DIR / f"{video_id}.json"
    result_path.write_text(json.dumps(result, indent=2, default=str))
    log.info("Transformation complete: %s", result_path)
    return result


def run(video_id: str, kindness_context: str = "") -> dict:
    return transform(video_id, kindness_context)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    vid = sys.argv[1] if len(sys.argv) > 1 else "Dp3UCQwkcsY"
    result = run(vid)
    print(json.dumps({k: str(v)[:120] for k, v in result.items()}, indent=2))

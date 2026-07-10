"""DataFlow pipelines for the 143 Engine.

Each pipeline is registered as a Dream Lab DataFlow step chain.
They process ingested + scored video data through filter → rank → export stages.
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def rank_kindness_top(data_path: str, top_n: int = 10) -> None:
    """Rank videos by kindness score, output top-N."""
    data = json.loads(Path(data_path).read_text())
    videos = data.get("videos", [])

    scored = [v for v in videos if v.get("scores", {}).get("kindness_score", 0) > 0]
    ranked = sorted(scored, key=lambda v: v["scores"]["kindness_score"], reverse=True)

    print(f"\nTop {top_n} videos by kindness score:\n")
    for i, v in enumerate(ranked[:top_n]):
        s = v["scores"]
        print(f"  {i+1:2d}. [{s['kindness_score']:.1f}] {v['title'][:70]}")
        print(f"      tone={', '.join(s.get('emotional_tone', []))}  viral={s.get('virality_potential', 0):.1f}")
        print(f"      caption: {s.get('caption_hook', '')}")
        print()

    return ranked


def export_for_distribution(data_path: str, output_path: str | None = None) -> str:
    """Export top scored videos as a distribution-ready manifest."""
    data = json.loads(Path(data_path).read_text())
    videos = data.get("videos", [])

    manifest = []
    for v in videos:
        s = v.get("scores", {})
        if s.get("kindness_score", 0) < 6 or s.get("safe_for_brand") is False:
            continue
        manifest.append({
            "video_id": v["video_id"],
            "title": v["title"],
            "kindness_score": s.get("kindness_score", 0),
            "virality_potential": s.get("virality_potential", 0),
            "emotional_tone": s.get("emotional_tone", []),
            "thematic_tags": s.get("thematic_tags", []),
            "caption_hook": s.get("caption_hook", ""),
            "target_platform": s.get("target_platform", "none"),
            "best_clip_moment": s.get("best_clip_moment", ""),
            "view_count": v["view_count"],
            "like_count": v["like_count"],
        })

    ranked = sorted(manifest, key=lambda m: (m["kindness_score"] + m["virality_potential"]) / 2, reverse=True)

    out = output_path or str(DATA_DIR / "processed" / "distribution_manifest.json")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({"pipeline": "143-engine", "total": len(ranked), "videos": ranked}, indent=2))
    log.info("Distribution manifest written to %s (%d videos)", out, len(ranked))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    scored_path = DATA_DIR / "scored" / "MisterRogersNeighborhood.json"
    if scored_path.exists():
        rank_kindness_top(str(scored_path))
        export_for_distribution(str(scored_path))
    else:
        log.warning("No scored data yet. Run 'python3 -m src.engine.score' first.")

# 143 Engine

> *"There are three ways to ultimate success: The first way is to be kind. The second way is to be kind. The third way is to be kind."* — Fred Rogers

**143 = I love you.** 1 letter, 4 letters, 3 letters.

The 143 Engine is a kindness amplification pipeline. It ingests, analyzes, transforms, and distributes content that makes the internet a little more like Mister Rogers' Neighborhood — one clip, one post, one moment of genuine human warmth at a time.

Built on [Dream Lab](https://github.com/peparhugo/dreamlab), the multi-agent orchestration layer that runs the cognitive loop: experiment, learn, remember, improve.

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   INGEST     │───▶│   ANALYZE    │───▶│   PRODUCE    │───▶│  DISTRIBUTE  │
│              │    │              │    │              │    │              │
│ yt-dlp       │    │ Dream Cycle  │    │ Clip assembly│    │ Scheduling   │
│ channel idx  │    │ multi-modal  │    │ captioning   │    │ cross-plat   │
│              │    │ LLM scoring  │    │ audio mix    │    │ posting      │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                            │                                      │
                            ▼                                      ▼
                    ┌──────────────────────────────────────────────────┐
                    │              FEEDBACK LOOP                       │
                    │  Source inventory · Claim tracker · Recall       │
                    │  "What made people feel something today?"        │
                    └──────────────────────────────────────────────────┘
```

## Dream Lab Orchestration

| Stage | Dream Lab Tool | What It Does |
|-------|---------------|--------------|
| **Ingest** | `dreamlab_data_pipeline` | ETL — read channel config → filter new → fan out downloads |
| **Analyze** | `dreamlab_dream_run` | Dream Cycle: score clips on kindness, emotional tone, virality |
| **Experiment** | `dreamlab_experiment` | A/B test formats, captions, posting times with proper stats |
| **Produce** | `dreamlab_job_manifest` | Multi-stage assembly: clip → caption → audio → render |
| **Distribute** | `dreamlab_execute` | Wrap platform APIs, track outcomes |
| **Learn** | `dreamlab_remember` / `dreamlab_recall` | Persist what worked, retrieve for the next cycle |

## Setup

```bash
git clone https://github.com/peparhugo/143-engine.git
cd 143-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## License

MIT

---

*Won't you be my neighbor?*

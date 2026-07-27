# Skill Bill vol. 1

YouTube-to-Claude-skill pipeline. Converts course playlists (or single videos) into structured markdown with transcripts, inline screenshots, and AI-refined lesson steps, then packages the result as a `SKILL.md` bundle.

## Project Structure

```
skillbill/
  config.py       — Constants, paths, segment-aware dedup thresholds, verbal cue keywords
  downloader.py   — Stage 1 (discovery) & Stage 3 (video download) via yt-dlp
  transcript.py   — Stage 2: transcript extraction with 3-tier fallback (cache → yt-dlp → Playwright)
  analyzer.py     — Stage 4: screenshot planning (segment classification, talking-head skip)
  capturer.py     — Stage 5: ffmpeg frame extraction + perceptual hash dedup (segment-aware)
  generator.py    — Stage 6: Jinja2 markdown assembly with inline screenshot interleaving
  refiner.py      — Stage 7: Haiku vision refinement (lesson extraction, captioning, topic index)
  pipeline.py     — Orchestrator: run_all(), run_transcript_only(), per-stage runners
templates/
  video.md.j2     — Jinja2 template using content_blocks (text + screenshot interleaved)
web/
  server.py       — FastAPI + WebSocket server
  routes/         — home, generate, library, download, settings
  services/
    pipeline_runner.py  — Async pipeline wrapper with progress events
    skill_packager.py   — ZIP packaging for Claude Code skills (two-tier SKILL.md)
    markdown_renderer.py — Markdown-to-HTML for course viewer
tests/            — 176 tests (unit + integration), run with pytest
run.py            — Click CLI entry point
data/
  raw/            — Downloaded manifests + video files (cached by course slug)
  processed/      — Cached transcripts + screenshot plans (JSON, keyed by video ID)
  assets/         — Extracted PNG screenshots (per-video subdirectories)
  knowledge_base/ — Final markdown output (index.md + per-video .md files)
```

## Quick Reference

```bash
# Transcript-only mode (fast, no video download)
python run.py playlist "URL" --transcript-only

# Full pipeline (all 7 stages)
python run.py playlist "URL"

# Single video (discovery wraps it as a one-item course)
python run.py video "URL"

# Full pipeline with AI refinement (Pro mode — requires ANTHROPIC_API_KEY)
ANTHROPIC_API_KEY=sk-... python run.py playlist "URL" --refine

# Web UI
python run.py serve

# Run tests
python -m pytest tests/ -v

# With YouTube cookies (if rate-limited)
python run.py playlist "URL" --cookies-from chrome
```

## Architecture: Screenshot Pipeline

Screenshots flow through 4 stages:

1. **Planning** (`analyzer.py`): Segments video into types (code-demo, slides, talking-head, etc.). Talking-head segments produce zero screenshots. Each screenshot entry carries `segment_type`.
2. **Capture** (`capturer.py`): Extracts frames via ffmpeg. Dedup uses per-segment thresholds from `config.DEDUP_THRESHOLDS` (code-demo=4, ui-walkthrough=4, slides=8, talking-head=12) — *lower* is stricter, keeping more frames where small details matter.
3. **Generation** (`generator.py`): `_interleave_content()` merges transcript entries and screenshots by timestamp into `content_blocks` rendered inline by `video.md.j2`.
4. **Refinement** (`refiner.py`, Pro mode): Filters screenshots, captions each with Haiku vision, sends to Haiku with transcript for lesson extraction. Generates `topics.json` keyword index.

## Conventions

- **Public repo:** This is published at `github.com/asrith926/skill-bill-vol-1`. Keep it free of client work, credentials, and personal paths.
- **Cost-conscious:** Minimize Claude API usage. Local heuristics handle screenshot planning; Haiku used only for segment classification (~$0.02/video) and Pro refinement (~$0.15-0.20/video).
- **Caching:** Transcripts cached in `data/processed/`, videos in `data/raw/`, screenshot plans in `data/processed/`. Pipeline reuses cached artifacts on re-run.
- **Rate limits:** Use `--cookies-from chrome` (or safari/firefox) if YouTube blocks requests.
- **Testing:** Always run `python -m pytest tests/ -v` before committing. Currently 189 tests.

## Known Issues (TODO)

1. ~~**Refiner drops screenshots**~~: Fixed. Prompt now requires ALL screenshots be placed; captions are passed through to the vision call.

## Using the Knowledge Base

Generated knowledge bases live in `data/knowledge_base/<course-slug>/`. Read `index.md` first, then load only the specific video file(s) needed (raw: 3-9K tokens each, refined: 2-5K tokens each).

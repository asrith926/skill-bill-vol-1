# YouTube-to-Knowledge-Base Pipeline Design

**Date:** 2026-02-25
**Status:** Approved

## Problem

YouTube contains vast amounts of tutorial and course content. Currently there is no way to systematically extract that knowledge into a format that Claude Code can consume and reason over. The goal is to build a pipeline that converts YouTube playlists (full courses) into structured markdown knowledge bases — faithful to the source material, with intelligently selected screenshots.

## Requirements

- Process full YouTube course playlists (primary use case)
- Extract timestamped transcripts
- Intelligently capture screenshots when the visual content is relevant to the tutorial
- Produce markdown files that stay true to the source material
- Minimize Claude API costs (use local heuristics wherever possible)
- Python-based with clean library/API separation for future UI
- Each pipeline stage independently runnable and retryable

## Architecture: Staged Pipeline with Intermediate Artifacts

### Stage 1: Discovery
**Tool:** yt-dlp Python API (`extract_flat`)
**Input:** YouTube playlist URL
**Output:** `manifest.json` — video list with titles, descriptions, chapters, linked URLs, ordering

### Stage 2: Transcripts
**Tool:** youtube-transcript-api
**Input:** Video IDs from manifest
**Output:** Timestamped transcript JSON per video, flags for videos with no/sparse captions

### Stage 3: Download
**Tool:** yt-dlp Python API
**Input:** Video URLs from manifest
**Output:** Video files (mp4) in `data/raw/<course-slug>/`

### Stage 4: Screenshot Planning
**Tools:** PySceneDetect + local heuristics + one Claude Haiku call per video
**Input:** Video files + transcripts
**Output:** Screenshot plan JSON per video (timestamps + reasons + segment classifications)

#### Screenshot Decision Heuristics

The pipeline classifies each video segment into types, then applies capture strategies:

**Segment Types (classified by Haiku from transcript):**
- **Code Demo** — frequent scene changes, sparse transcript, technical keywords → capture at scene changes + every 20-30s fallback
- **Slides/Presentation** — distinct transitions, steady speech → capture once per slide transition
- **Talking Head** — stable scene, dense speech, no visual cues → capture at start + topic transitions only
- **Whiteboard/Diagram** — gradual continuous change, drawing cues → capture every 15-20s
- **Unknown/Mixed** — capture every 45-60s safety net

**Local heuristic signals (free, no API):**
1. PySceneDetect ContentDetector → scene change timestamps
2. PySceneDetect AdaptiveDetector → gradual visual changes
3. Transcript keyword scan → verbal cues ("look at this", "as you can see", topic shifts)
4. Speech density analysis → words-per-minute per time window
5. Silence/gap detection → gaps >5s suggest visual-only content
6. Chapter boundaries from yt-dlp metadata

**Claude Haiku call (one per video, ~$0.02):**
- Receives full transcript text only
- Returns segment classification map + visual reference timestamps
- Guides which local heuristic strategy to apply per segment

**Default behavior:** CAPTURE. Screenshots are taken unless there's a strong signal the visual is irrelevant (talking head with no visual aids). The screen is assumed to be relevant to the tutorial.

**Sparse transcript handling:** When transcript density drops below threshold (configurable, default 10 words/minute), screenshot frequency increases automatically — the screen IS the content.

### Stage 5: Frame Capture
**Tools:** ffmpeg-python + imagehash (Pillow)
**Input:** Video files + screenshot plan
**Output:** PNG screenshots in `data/assets/<course-slug>/<video-num>/`

**Deduplication:** Perceptual hashing (imagehash library) compares each candidate frame to last N captured frames. Near-duplicates (hamming distance below threshold) are skipped.

### Stage 6: Generation
**Tools:** Python + Jinja2
**Input:** Transcripts + screenshots + metadata
**Output:** Final markdown knowledge base

**Principles:**
- Transcript reproduced faithfully — not summarized, not rewritten
- Chapter markers become section headers
- Screenshots embedded inline at correct transcript positions
- Each screenshot has a brief caption from transcript context
- Linked URLs preserved at bottom of each file
- Course-level index.md with lesson ordering and overview

## Project Structure

```
Skill Bill/
├── skillbill/                      # Python package
│   ├── __init__.py
│   ├── downloader.py            # Stage 1 + 3: yt-dlp discovery and download
│   ├── transcript.py            # Stage 2: youtube-transcript-api
│   ├── analyzer.py              # Stage 4: screenshot planning (heuristics + Haiku)
│   ├── capturer.py              # Stage 5: ffmpeg frame extraction + dedup
│   ├── generator.py             # Stage 6: markdown assembly
│   ├── pipeline.py              # Orchestrator
│   └── config.py                # Shared config
├── data/                        # All pipeline artifacts (gitignored)
│   ├── raw/                     # Video files, subtitle files, metadata
│   ├── processed/               # Clean transcripts, screenshot plans
│   ├── assets/                  # Extracted screenshots
│   └── knowledge_base/          # Final markdown output
├── templates/                   # Jinja2 markdown templates
│   ├── video.md.j2
│   └── index.md.j2
├── requirements.txt
├── run.py                       # CLI entry point
└── .gitignore
```

## CLI Interface

```bash
# Full playlist
python run.py playlist "https://youtube.com/playlist?list=xxxxx"

# Single video
python run.py video "https://youtube.com/watch?v=xxxxx"

# Run specific stage
python run.py playlist "URL" --stage discovery
python run.py playlist "URL" --stage transcript
python run.py playlist "URL" --stage download
python run.py playlist "URL" --stage screenshots
python run.py playlist "URL" --stage generate

# Screenshot density override
python run.py playlist "URL" --screenshot-density high
python run.py playlist "URL" --screenshot-density low

# Transcript-only mode (no video download, no screenshots)
python run.py playlist "URL" --transcript-only
```

## Configuration

```python
screenshot_config = {
    "min_interval_seconds": 10,
    "max_interval_seconds": 120,
    "dedup_threshold": 0.85,
    "sparse_transcript_threshold": 10,  # words per minute
    "verbal_cue_keywords": [
        "look at", "as you can see", "on screen", "this diagram",
        "this code", "let me show", "here we have", "notice",
        "this shows", "take a look", "on the left", "on the right",
    ],
}
```

## Dependencies

```
yt-dlp
youtube-transcript-api
ffmpeg-python
scenedetect
imagehash
Pillow
anthropic
click
jinja2
```

System: `ffmpeg` (via brew, already installed)

## Cost Analysis

Per 30-video course (average 10 min/video):
- youtube-transcript-api: free
- yt-dlp: free
- PySceneDetect: free (local)
- imagehash: free (local)
- ffmpeg: free (local)
- Claude Haiku: ~30 calls x $0.02 = ~$0.60 per course
- Storage: ~5-15 GB video files (can delete after screenshot extraction)

## Output Format

See design doc Section 3 for detailed markdown format specification.
Each video produces one .md file with faithful transcript, inline screenshots, and metadata.
Course-level index.md provides navigation and overview.

## Future Considerations (Not in v1)

- UI layer on top of Python API
- Audio analysis for keyboard sounds / silence detection
- Crawling linked URLs via Scrapling (on-demand)
- Converting knowledge bases into Claude Code skills
- Semantic search over knowledge base content

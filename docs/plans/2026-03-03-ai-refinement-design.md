# Skill Bill — AI Refinement Stage Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

## Summary

Add a "Pro" refinement stage to the pipeline that uses Haiku (with vision) to convert raw transcripts into clean, actionable lesson steps. Pro mode also de-clickbaits video titles, producing a fully polished knowledge base. The web UI offers two modes: **Base** (full pipeline, raw transcript) and **Pro** (full pipeline + AI refinement).

## Architecture

New pipeline Stage 7 ("Refinement") runs after Stage 6 (Generation), gated by a `refine=True` flag. One Haiku call per video with pre-filtered screenshots. A second Haiku call per video generates a clean descriptive title. Pro output replaces the raw transcript files entirely — clean `.md` files with lesson steps, descriptive filenames, and polished index.

## Two Modes: Base and Pro

### Base (default)
- Full 6-stage pipeline: discovery → transcripts → download → screenshot planning → capture → generation
- Output: raw transcript markdown files + screenshots
- No API key required
- Functional but verbose — raw speech transcription with filler, repetition, tangents

### Pro
- Full 6-stage pipeline + Stage 7: refinement
- Output: clean lesson-step markdown files + screenshot references + descriptive titles
- Requires API key (Anthropic; OpenAI and Google coming soon)
- Polished, concise, actionable — 70-80% token reduction vs Base

## Screenshot Pre-Filter

Before sending screenshots to Haiku, filter by quality:

**Always keep:**
- `slide_transition` — shows what's on screen
- `scene_change` — code/terminal state changes

**Keep verbal cues by default** — all `verbal_cue` screenshots pass, EXCEPT those matching an explicit blocklist:

```python
# config.py
SCREENSHOT_FILTER = {
    "keep_reasons": ["slide_transition", "scene_change"],
    "drop_reasons": ["section_start", "interval_fallback", "mid_section"],
    "verbal_cue_blocklist": ["this is", "notice"],
    # All verbal_cue screenshots NOT in blocklist are kept
    # New keywords added to verbal_cue_keywords auto-included
}
```

**Drop:**
- `section_start` — 30-second interval noise, mostly talking-head frames
- `interval_fallback` — safety net captures
- `mid_section` — talking-head midpoints

**Expected reduction:** ~60% fewer screenshots sent to Haiku. Generous verbal cue inclusion ensures useful visual context is preserved.

The blocklist is intentionally small (only proven-noisy phrases). New verbal cue keywords added to `config.py` are automatically included without touching the filter config.

## Haiku Refinement: Lesson Extraction

**One call per video.** Input:
- Full transcript text (by chapter if available)
- Filtered screenshots as images with captions/timestamps
- Video metadata: title, duration, chapter list

**Prompt:**

```
You are converting a YouTube video transcript into clean, actionable lesson steps.

Input: Raw transcript and screenshots from "{video_title}" ({duration}).

Produce ONLY this markdown:

1. **[Step/concept name]** — [1-2 sentence explanation]. [Code example if any, preserved exactly.]
2. **[Step/concept name]** — ...
...

Rules:
- Extract actionable steps and key concepts, not summaries of what the speaker said
- Preserve code examples, commands, and URLs exactly as spoken/shown
- Reference screenshots where they show something the text doesn't capture (UI state, diagram, code on screen) using: ![description](./assets/NN/MM-SS.png)
- Drop filler, repetition, tangents, and conversational speech
- Keep technical accuracy — don't paraphrase technical terms
- Target: 70-80% reduction in token count vs raw transcript
```

**Output:** Clean numbered lesson steps per video.

## Haiku Refinement: Title Cleanup

**One call per video.** Input:
- Original YouTube video title
- First 500 tokens of transcript (enough to understand the actual content)

**Prompt:**

```
The following YouTube video has a potentially clickbaity title. Generate a clean, descriptive title that accurately reflects the video's actual content. The title should be concise (5-10 words), professional, and useful for someone scanning a course index.

Original title: "{original_title}"
Content preview: "{transcript_preview}"

Return ONLY the new title, nothing else.
```

**Output:** Clean title string. Applied to:
- Markdown file header (`# Clean Title`)
- Filename (`01-clean-slugified-title.md`)
- Index file links
- SKILL.md references

## Pipeline Integration

### New module: `skillbill/refiner.py`

```python
# Key functions:
filter_screenshots(capture_results: list, config: dict) -> list[dict]
    # Apply keep/drop/blocklist filter, return screenshots worth sending

refine_video_title(original_title: str, transcript_preview: str) -> str
    # One Haiku call to de-clickbait a video title

refine_video_content(
    transcript_entries: list[dict],
    chapters: list[dict],
    filtered_screenshots: list[dict],
    video_title: str,
    duration: float,
) -> str
    # One Haiku call with vision, returns refined lesson markdown

refine_course(
    course_dir: Path,
    manifest: dict,
    transcripts: list[dict],
    capture_results: list[list[dict]],
) -> Path
    # Loops over videos, calls refine_video_title + refine_video_content
    # Writes clean .md files, renames files with clean titles
    # Regenerates index.md with clean titles
    # Returns course_dir
```

### Pipeline changes

```python
class Pipeline:
    def __init__(self, ..., refine: bool = False):
        self.refine = refine

    def run_refinement(self) -> Path:
        """Stage 7: AI refinement — clean titles + lesson extraction."""
        # Requires: manifest, transcripts, capture_results, generated course_dir
        return refine_course(
            self.kb_dir / self.manifest["slug"],
            self.manifest,
            self.transcripts,
            self.capture_results,
        )

    def run_all(self, url: str) -> Path:
        ...existing 6 stages...
        if self.refine:
            return self.run_refinement()
        return course_dir

    def run_transcript_only(self, url: str) -> Path:
        ...existing stages...
        if self.refine:
            return self.run_refinement()
        return course_dir
```

### Pro output file structure

```
data/knowledge_base/<course-slug>/
  index.md                              # Clean titles, links to lesson files
  01-clean-descriptive-title.md         # Refined lesson steps + screenshot refs
  02-clean-descriptive-title.md
  ...
  assets/
    01/                                 # Screenshots (unchanged)
    02/
    ...
```

In Pro mode, the refined files REPLACE the raw transcript files. The raw transcript data remains cached in `data/processed/` if ever needed, but the knowledge base output is clean.

## API Key Management

### Storage
- Persisted to `data/.config.json` (local, gitignored)
- Structure: `{"provider": "anthropic", "api_key": "sk-ant-..."}`
- Clear button available in the UI

### Flow
1. User selects Pro mode
2. System checks `data/.config.json` for saved key
3. If key exists → proceed
4. If no key → modal appears:
   - Provider selection: **Anthropic** (selectable) | **OpenAI** (coming soon, dimmed) | **Google** (coming soon, dimmed)
   - Each with proper brand logo
   - API key input field (password type, secure paste)
   - "Save & Continue" button
5. Key saved to config, pipeline proceeds

### Security
- `data/.config.json` added to `.gitignore`
- Input field uses `type="password"` — masked on screen
- Key only stored locally, never transmitted anywhere except the selected provider's API

## Web UI Changes

### Home page
- Two toggle pills: **Base** (default) | **Pro**
- Hover tooltips:
  - Base: "Full pipeline with transcripts and screenshots"
  - Pro: "AI-refined lessons with clean titles and concise steps"
- When Pro selected → API key check → modal if needed
- No mention of specific models or pricing

### Progress page
- Base: 6 stages (existing)
- Pro: 7 stages — "Refinement" appears after "Generation"
  - Shows per-video progress: "Refining 3/16: Variables and Data Types"

### Video page
- Base: shows raw transcript (existing behavior)
- Pro: shows refined lessons only. No toggle. Clean numbered steps.

### Library / Course page
- Pro courses show clean titles throughout
- Visual indicator on course card: subtle "Pro" badge if refined

### Download ZIP
- Base: raw transcript MDs + screenshots + SKILL.md
- Pro: clean refined MDs + screenshots + SKILL.md (with clean titles throughout)

## Provider Abstraction (Frontend Only)

The API key modal presents three providers but only Anthropic works:

```
┌─────────────────────────────────────────┐
│          Select AI Provider             │
│                                         │
│  [◉ Anthropic logo]  Anthropic          │
│  [○ OpenAI logo]     OpenAI  (soon)     │
│  [○ Google logo]     Google  (soon)     │
│                                         │
│  API Key: [••••••••••••••••••]          │
│                                         │
│            [Save & Continue]            │
└─────────────────────────────────────────┘
```

OpenAI and Google are visible but dimmed/unselectable with "Coming soon" labels. Backend only implements the Anthropic path for now.

## Cost Estimate

Per video in Pro mode:
- Title cleanup: ~$0.001 (text-only Haiku call, tiny input)
- Lesson refinement: ~$0.03-0.08 (transcript + 5-15 filtered screenshots via vision)
- **Total per video: ~$0.03-0.08**
- **16-video course: ~$0.50-1.30**

## Constraints

- All work inside `Skill Bill/`
- Existing `skillbill/` modules unchanged except `pipeline.py` (adds `refine` flag + `run_refinement()`)
- `config.py` gets new `SCREENSHOT_FILTER` dict
- New `skillbill/refiner.py` module
- Web UI template/route changes for Base/Pro toggle, API key modal, progress stage
- `data/.config.json` gitignored for API key storage

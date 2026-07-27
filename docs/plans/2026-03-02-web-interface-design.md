# Skill Bill — Web Interface Design

> Local web UI for generating and browsing YouTube knowledge bases. Users run it on their own machine — no hosted server, no cloud costs.

## Summary

Add a browser-based interface to the existing CLI pipeline. Users start the server with `python run.py serve`, paste a YouTube URL, watch the pipeline run with real-time progress, browse the generated knowledge base, and download it as a Claude Code skill package (.zip).

**Distribution:** Open-source GitHub repo. Users clone, `pip install`, and run locally.

## Architecture

```
Skill Bill/
  skillbill/                # Existing pipeline (UNCHANGED)
  web/
    server.py            # FastAPI app — mounts routes, static files, WebSocket
    routes/
      home.py            # GET / — landing page
      generate.py        # POST /generate — start pipeline; WS /ws/progress
      library.py         # GET /library, /course/<slug>, /video/<slug>/<file>
      download.py        # GET /download/<slug> — serve .zip skill package
    services/
      pipeline_runner.py   # Wraps skillbill.pipeline with progress callbacks
      skill_packager.py    # Generates SKILL.md + bundles .zip
      markdown_renderer.py # .md → HTML (markdown-it-py + Pygments)
    templates/
      base.html          # Shared dark theme shell, nav, fonts
      home.html          # Paste URL, pick options, generate
      progress.html      # Real-time pipeline progress via WebSocket
      library.html       # Grid of generated courses
      course.html        # Course index — sidebar video list
      video.html         # Full reading experience — transcript + screenshots
    static/
      css/
        style.css        # CSS variables, layout, components
        typography.css   # Font imports (JetBrains Mono + Newsreader), reading styles
        animations.css   # Transitions, progress timeline effects
      js/
        app.js           # Nav interactions, theme toggle
        progress.js      # WebSocket client, timeline updates, log scroll
        lightbox.js      # Screenshot expand on click
      img/               # Logo, icons
  run.py                 # Extended CLI: existing commands + `serve`
```

## Visual Design

### Aesthetic Direction

**Dark, editorial.** Vercel dashboard meets Stripe docs.

- **Background:** Deep charcoal (`#0a0a0b`)
- **Text:** Warm off-white (`#e8e4de`)
- **Accent:** Amber/gold (`#f0b429`) for CTAs, progress indicators, focus states
- **Secondary:** Muted grays for borders, metadata, inactive elements
- **Texture:** Subtle noise overlay on dark surfaces, faint grid pattern on home page

### Typography

- **Display/UI:** JetBrains Mono — headings, navigation, code, metadata
- **Reading:** Newsreader (serif) — transcript body text, long-form content. Line height 1.7+, max-width 720px
- **Pairing logic:** Monospace for the "tool" feel, serif for the "content" feel

### Pages

#### Home — The Launch Page

- Centered layout: large monospace heading, single input field with amber glow on focus, "Generate" button
- Toggle pills below input: "Full Pipeline" vs "Transcript Only"
- "Advanced" expander for `--cookies-from` browser dropdown
- If library has courses: subtle "Browse Library →" link
- Background: noise texture + faint grid

#### Progress — Pipeline Command Center

- Left: vertical timeline of 6 stages (Discovery → Transcripts → Download → Screenshot Planning → Frame Capture → Markdown Generation)
- Each stage card transitions: dimmed → pulsing amber (active) → green checkmark (done)
- Per-video progress within stages (e.g., "Transcripts: 5/16 videos")
- Right: live scrolling log panel, monospace terminal aesthetic
- On complete: timeline collapses, "View Knowledge Base →" + "Download as Skill (.zip)" buttons appear with reveal animation

#### Library — Browse Courses

- 2-3 column grid of course cards
- Each card: title, video count, thumbnail (first screenshot or gradient placeholder), generation date
- Hover: subtle lift + amber border glow
- Search/filter bar at top
- Empty state: "No courses yet. Generate one →"

#### Course — Course Index

- Left sidebar: numbered video list (scrollable, current highlighted)
- Main area: course title, playlist source link, video count, generation date
- Click any video → video reading view

#### Video — Reading Experience

- Sticky right-side chapter navigation (from `## [MM:SS]` headings), highlights on scroll
- Transcript body: serif font, generous spacing, max-width 720px
- Inline screenshots: rounded corners, click-to-expand lightbox with caption
- Top bar: video title, duration, "Watch on YouTube" link, prev/next navigation
- Linked resources: collapsible section at bottom

## Technical Details

### Backend

- **FastAPI** serves Jinja2 templates + static files + WebSocket
- **Screenshots** served via `StaticFiles` mount at `/assets/` → `data/assets/`
- **Markdown → HTML** via `markdown-it-py` with Pygments for code highlighting
- **Single pipeline at a time** — simple lock prevents concurrent runs, UI shows "Pipeline busy"
- **pipeline_runner.py** wraps existing `skillbill.pipeline` with a progress callback that emits WebSocket messages

### WebSocket Protocol

Server → client JSON events:

```json
{"type": "stage_start", "stage": "transcripts", "total": 16}
{"type": "video_progress", "stage": "transcripts", "current": 5, "total": 16, "title": "What Are Variables?"}
{"type": "stage_complete", "stage": "transcripts"}
{"type": "log", "message": "Fetching transcript for video 6..."}
{"type": "pipeline_complete", "course_slug": "python-tutorials-for-absolute-beginners"}
{"type": "error", "message": "Failed to fetch transcript for video 3", "fatal": false}
```

### Skill Packager

On "Download as Skill" click:

1. Auto-generates `SKILL.md` with YAML frontmatter from course metadata (title, description, video count)
2. Bundles `SKILL.md` + `index.md` + all video `.md` files + `assets/` into a `.zip`
3. Serves as file download
4. User unzips into `~/.claude/skills/<course-slug>/` — ready to use

### New Dependencies

All pip-installable, no npm/Node:

- `fastapi` + `uvicorn[standard]` — web server
- `markdown-it-py` — markdown rendering
- `pygments` — syntax highlighting
- `python-multipart` — form data handling

### CLI Extension

```bash
# Existing commands unchanged:
python run.py playlist "URL"
python run.py playlist "URL" --transcript-only

# New:
python run.py serve                # localhost:8000
python run.py serve --port 3000    # custom port
```

## Constraints

- All work stays inside `Skill Bill/`
- Existing `skillbill/` package is not modified — web layer imports and calls it
- No Node.js, no build step — Jinja2 templates + vanilla JS + CSS only
- Cost-conscious: runs locally, no API costs beyond existing Haiku usage (~$0.02/video)

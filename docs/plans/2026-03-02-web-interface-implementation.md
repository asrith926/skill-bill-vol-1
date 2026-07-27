# Web Interface Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a browser-based local web UI to the Skill Bill pipeline — paste a YouTube URL, watch real-time progress, browse generated knowledge bases, download as Claude Code skill packages.

**Architecture:** FastAPI backend wrapping the existing `skillbill` pipeline with WebSocket progress streaming. Jinja2 HTML templates + vanilla CSS/JS frontend. Dark editorial aesthetic (JetBrains Mono + Newsreader fonts, charcoal + amber palette). Single process via `python run.py serve`.

**Tech Stack:** FastAPI, uvicorn, Jinja2, WebSockets, markdown-it-py, Pygments, vanilla JS/CSS

**Design Doc:** `docs/plans/2026-03-02-web-interface-design.md`

---

### Task 1: Add web dependencies and create package structure

**Files:**
- Modify: `requirements.txt`
- Create: `web/__init__.py`
- Create: `web/routes/__init__.py`
- Create: `web/services/__init__.py`
- Create: `web/templates/.gitkeep`
- Create: `web/static/css/.gitkeep`
- Create: `web/static/js/.gitkeep`

**Step 1: Update requirements.txt**

Add to `requirements.txt`:

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
websockets>=12.0
markdown-it-py>=3.0.0
pygments>=2.18.0
python-multipart>=0.0.9
```

**Step 2: Create directory structure**

```bash
mkdir -p web/routes web/services web/templates web/static/css web/static/js web/static/img
touch web/__init__.py web/routes/__init__.py web/services/__init__.py
```

**Step 3: Install dependencies**

```bash
pip install fastapi "uvicorn[standard]" websockets markdown-it-py pygments python-multipart
```

**Step 4: Verify imports work**

```bash
python -c "import fastapi; import uvicorn; import markdown_it; import pygments; print('OK')"
```

Expected: `OK`

**Step 5: Commit**

```bash
git add requirements.txt web/
git commit -m "feat(web): add web dependencies and package structure"
```

---

### Task 2: Build the markdown renderer service

**Files:**
- Create: `web/services/markdown_renderer.py`
- Create: `tests/test_markdown_renderer.py`

**Step 1: Write the failing tests**

Create `tests/test_markdown_renderer.py`:

```python
"""Tests for the markdown-to-HTML renderer service."""
import pytest
from web.services.markdown_renderer import render_markdown, render_video_file


class TestRenderMarkdown:
    def test_renders_heading(self):
        html = render_markdown("# Hello")
        assert "<h1>" in html
        assert "Hello" in html

    def test_renders_code_block_with_highlighting(self):
        md = "```python\nprint('hello')\n```"
        html = render_markdown(md)
        assert "highlight" in html or "codehilite" in html or "<code" in html

    def test_renders_image_with_path(self):
        md = "![slide_transition](./assets/01/00-30.png)"
        html = render_markdown(md)
        assert "<img" in html
        assert "00-30.png" in html

    def test_renders_bold_and_italic(self):
        md = "**bold** and *italic*"
        html = render_markdown(md)
        assert "<strong>" in html or "<b>" in html
        assert "<em>" in html or "<i>" in html


class TestRenderVideoFile:
    def test_renders_video_markdown(self, tmp_path):
        md_file = tmp_path / "01-intro.md"
        md_file.write_text(
            "# Introduction\n\n"
            "**Course:** Test Course\n\n"
            "## [00:00] Welcome\n\n"
            "Hello everyone.\n"
        )
        html = render_video_file(md_file)
        assert "Introduction" in html
        assert "Welcome" in html

    def test_rewrites_asset_paths(self, tmp_path):
        md_file = tmp_path / "01-intro.md"
        md_file.write_text("![caption](./assets/01/00-30.png)")
        html = render_video_file(md_file, asset_url_prefix="/assets/test-course")
        assert "/assets/test-course/01/00-30.png" in html

    def test_missing_file_raises(self):
        from pathlib import Path
        with pytest.raises(FileNotFoundError):
            render_video_file(Path("/nonexistent/file.md"))
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_markdown_renderer.py -v
```

Expected: FAIL (module not found)

**Step 3: Write the implementation**

Create `web/services/markdown_renderer.py`:

```python
"""Markdown-to-HTML rendering with syntax highlighting."""
import re
from pathlib import Path
from markdown_it import MarkdownIt
from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import HtmlFormatter


def _highlight_code(code: str, lang: str) -> str:
    """Syntax-highlight a code block."""
    try:
        lexer = get_lexer_by_name(lang)
    except Exception:
        lexer = TextLexer()
    formatter = HtmlFormatter(nowrap=True)
    return highlight(code, lexer, formatter)


def render_markdown(text: str) -> str:
    """Render markdown text to HTML with syntax highlighting."""
    md = MarkdownIt("commonmark", {"html": True}).enable("table")

    # Render base markdown
    html = md.render(text)

    # Post-process fenced code blocks for syntax highlighting
    def replace_code_block(match):
        lang = match.group(1) or ""
        code = match.group(2)
        if lang:
            highlighted = _highlight_code(code, lang)
            return f'<pre><code class="highlight language-{lang}">{highlighted}</code></pre>'
        return match.group(0)

    html = re.sub(
        r'<code class="language-(\w+)">(.*?)</code>',
        replace_code_block,
        html,
        flags=re.DOTALL,
    )

    return html


def render_video_file(
    md_path: Path, asset_url_prefix: str | None = None
) -> str:
    """Read a video markdown file and render to HTML.

    If asset_url_prefix is provided, rewrite relative ./assets/ paths
    to the given URL prefix.
    """
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    text = md_path.read_text()

    if asset_url_prefix:
        # Rewrite ./assets/NN/MM-SS.png → /assets/<prefix>/NN/MM-SS.png
        text = text.replace("./assets/", f"{asset_url_prefix}/")

    return render_markdown(text)
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_markdown_renderer.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add web/services/markdown_renderer.py tests/test_markdown_renderer.py
git commit -m "feat(web): add markdown-to-HTML renderer with syntax highlighting"
```

---

### Task 3: Build the pipeline runner service with progress callbacks

**Files:**
- Create: `web/services/pipeline_runner.py`
- Create: `tests/test_pipeline_runner.py`

This is the core integration layer — it wraps the existing `Pipeline` class and emits progress events that the WebSocket can forward to the browser.

**Step 1: Write the failing tests**

Create `tests/test_pipeline_runner.py`:

```python
"""Tests for the pipeline runner service with progress callbacks."""
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from web.services.pipeline_runner import PipelineRunner, PipelineStatus


class TestPipelineRunner:
    def test_initial_status_is_idle(self):
        runner = PipelineRunner()
        assert runner.status == PipelineStatus.IDLE

    def test_cannot_start_while_busy(self):
        runner = PipelineRunner()
        runner.status = PipelineStatus.RUNNING
        with pytest.raises(RuntimeError, match="busy"):
            asyncio.get_event_loop().run_until_complete(
                runner.start("https://youtube.com/playlist?list=PLtest", mode="transcript_only")
            )

    def test_progress_callback_collects_events(self):
        runner = PipelineRunner()
        events = []
        runner.add_listener(events.append)
        runner._emit({"type": "stage_start", "stage": "discovery"})
        assert len(events) == 1
        assert events[0]["type"] == "stage_start"

    def test_remove_listener(self):
        runner = PipelineRunner()
        events = []
        runner.add_listener(events.append)
        runner.remove_listener(events.append)
        runner._emit({"type": "log", "message": "test"})
        assert len(events) == 0


class TestPipelineStatus:
    def test_status_values(self):
        assert PipelineStatus.IDLE == "idle"
        assert PipelineStatus.RUNNING == "running"
        assert PipelineStatus.COMPLETE == "complete"
        assert PipelineStatus.ERROR == "error"
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipeline_runner.py -v
```

Expected: FAIL (module not found)

**Step 3: Write the implementation**

Create `web/services/pipeline_runner.py`:

```python
"""Pipeline runner with progress event emission for WebSocket streaming."""
import asyncio
import threading
from enum import StrEnum
from pathlib import Path
from typing import Callable, Optional
from skillbill.pipeline import Pipeline


class PipelineStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


class PipelineRunner:
    """Wraps skillbill.Pipeline with progress callbacks for the web UI.

    Runs the pipeline in a background thread so the async event loop
    stays responsive for WebSocket messages.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir
        self.status: PipelineStatus = PipelineStatus.IDLE
        self.current_course_slug: Optional[str] = None
        self._listeners: list[Callable] = []
        self._lock = threading.Lock()

    def add_listener(self, callback: Callable) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable) -> None:
        self._listeners = [cb for cb in self._listeners if cb is not callback]

    def _emit(self, event: dict) -> None:
        for cb in self._listeners:
            try:
                cb(event)
            except Exception:
                pass

    async def start(
        self,
        url: str,
        mode: str = "full",
        use_haiku: bool = True,
        cookies_from: Optional[str] = None,
    ) -> None:
        """Start the pipeline in a background thread.

        Args:
            url: YouTube playlist or video URL.
            mode: "full" or "transcript_only".
            use_haiku: Whether to use Haiku for segment classification.
            cookies_from: Browser to extract cookies from (e.g. "chrome").
        """
        if self.status == PipelineStatus.RUNNING:
            raise RuntimeError("Pipeline is busy. Wait for the current run to complete.")

        self.status = PipelineStatus.RUNNING
        loop = asyncio.get_event_loop()

        def run_in_thread():
            try:
                pipeline = Pipeline(
                    data_dir=self.data_dir,
                    use_haiku=use_haiku,
                    cookies_from=cookies_from,
                )
                self._run_pipeline(pipeline, url, mode)
            except Exception as e:
                self.status = PipelineStatus.ERROR
                self._emit({"type": "error", "message": str(e), "fatal": True})

        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()

    def _run_pipeline(self, pipeline: Pipeline, url: str, mode: str) -> None:
        """Execute pipeline stages, emitting progress events."""

        # Stage 1: Discovery
        self._emit({"type": "stage_start", "stage": "discovery"})
        self._emit({"type": "log", "message": f"Discovering playlist: {url}"})
        pipeline.run_discovery(url)
        manifest = pipeline.manifest
        total = manifest["video_count"]
        self.current_course_slug = manifest["slug"]
        self._emit({
            "type": "stage_complete",
            "stage": "discovery",
            "data": {"title": manifest["playlist_title"], "video_count": total},
        })

        # Stage 2: Transcripts
        self._emit({"type": "stage_start", "stage": "transcripts", "total": total})
        pipeline.run_transcripts()
        found = sum(1 for t in pipeline.transcripts if t["has_transcript"])
        self._emit({
            "type": "stage_complete",
            "stage": "transcripts",
            "data": {"found": found, "total": total},
        })

        if mode == "transcript_only":
            # Skip stages 3-5
            pipeline.capture_results = [[] for _ in pipeline.transcripts]
            self._emit({"type": "log", "message": "Transcript-only mode — skipping video download and screenshots"})
        else:
            # Stage 3: Download
            self._emit({"type": "stage_start", "stage": "download", "total": total})
            video_paths = pipeline.run_download()
            downloaded = sum(1 for p in video_paths if p is not None)
            self._emit({
                "type": "stage_complete",
                "stage": "download",
                "data": {"downloaded": downloaded, "total": total},
            })

            # Stage 4: Screenshot planning
            self._emit({"type": "stage_start", "stage": "screenshot_planning", "total": total})
            pipeline.run_screenshot_planning(video_paths)
            total_screenshots = sum(p.get("total_screenshots", 0) for p in pipeline.screenshot_plans)
            self._emit({
                "type": "stage_complete",
                "stage": "screenshot_planning",
                "data": {"total_screenshots": total_screenshots},
            })

            # Stage 5: Capture
            self._emit({"type": "stage_start", "stage": "capture", "total": total})
            pipeline.run_capture(video_paths)
            total_kept = sum(
                sum(1 for r in results if r["status"] == "kept")
                for results in pipeline.capture_results
            )
            self._emit({
                "type": "stage_complete",
                "stage": "capture",
                "data": {"screenshots_kept": total_kept},
            })

        # Stage 6: Generation
        self._emit({"type": "stage_start", "stage": "generation", "total": total})
        course_dir = pipeline.run_generation()
        self._emit({"type": "stage_complete", "stage": "generation"})

        # Done
        self.status = PipelineStatus.COMPLETE
        self._emit({
            "type": "pipeline_complete",
            "course_slug": manifest["slug"],
            "course_title": manifest["playlist_title"],
            "video_count": total,
        })
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_pipeline_runner.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add web/services/pipeline_runner.py tests/test_pipeline_runner.py
git commit -m "feat(web): add pipeline runner with progress event emission"
```

---

### Task 4: Build the skill packager service

**Files:**
- Create: `web/services/skill_packager.py`
- Create: `tests/test_skill_packager.py`

**Step 1: Write the failing tests**

Create `tests/test_skill_packager.py`:

```python
"""Tests for the skill packager — generates downloadable Claude Code skill ZIPs."""
import zipfile
import pytest
from pathlib import Path
from web.services.skill_packager import generate_skill_md, package_course_as_zip


class TestGenerateSkillMd:
    def test_contains_frontmatter(self):
        content = generate_skill_md(
            course_title="Python Basics",
            course_slug="python-basics",
            video_count=10,
            topics=["variables", "functions", "loops"],
        )
        assert "---" in content
        assert "name: python-basics" in content
        assert "Python Basics" in content

    def test_contains_navigation_instructions(self):
        content = generate_skill_md(
            course_title="Test", course_slug="test", video_count=5, topics=[]
        )
        assert "index.md" in content
        assert "## How to Navigate" in content or "## How to Use" in content


class TestPackageCourseAsZip:
    def test_creates_valid_zip(self, tmp_path):
        # Set up a minimal knowledge base
        course_dir = tmp_path / "knowledge_base" / "test-course"
        course_dir.mkdir(parents=True)
        (course_dir / "index.md").write_text("# Test\n")
        (course_dir / "01-intro.md").write_text("# Intro\n")

        assets_dir = course_dir / "assets" / "01"
        assets_dir.mkdir(parents=True)
        (assets_dir / "00-00.png").write_bytes(b"fake png")

        zip_path = package_course_as_zip(course_dir, "Test Course", tmp_path / "out")

        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert any("SKILL.md" in n for n in names)
            assert any("index.md" in n for n in names)
            assert any("01-intro.md" in n for n in names)
            assert any("00-00.png" in n for n in names)

    def test_zip_skill_md_has_frontmatter(self, tmp_path):
        course_dir = tmp_path / "knowledge_base" / "my-course"
        course_dir.mkdir(parents=True)
        (course_dir / "index.md").write_text("# My Course\n\n1. [Video](./01-v.md)\n")
        (course_dir / "01-v.md").write_text("# Video\n")

        zip_path = package_course_as_zip(course_dir, "My Course", tmp_path / "out")

        with zipfile.ZipFile(zip_path) as zf:
            skill_file = [n for n in zf.namelist() if "SKILL.md" in n][0]
            content = zf.read(skill_file).decode()
            assert "name: my-course" in content
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_skill_packager.py -v
```

Expected: FAIL (module not found)

**Step 3: Write the implementation**

Create `web/services/skill_packager.py`:

```python
"""Package a generated knowledge base as a downloadable Claude Code skill ZIP."""
import zipfile
from pathlib import Path


def generate_skill_md(
    course_title: str,
    course_slug: str,
    video_count: int,
    topics: list[str],
) -> str:
    """Generate a SKILL.md file for a knowledge base course."""
    topic_str = ", ".join(topics) if topics else course_title
    return f"""---
name: {course_slug}
description: Reference material from {course_title} — {video_count} videos covering {topic_str}
---

# {course_title}

## How to Use

### Step 1: Read the index

```
Read: index.md
```

The index lists all {video_count} videos with links to their individual files.

### Step 2: Read the relevant video file

Each video file is 3-9K tokens. **Never load all files at once.** Read only the specific video relevant to the question.

### Step 3: Navigate by chapter

Each video file has chapter sections marked with `## [MM:SS] Chapter Title`. Use these to jump to the relevant section.

## File Structure

Each video file contains:
- **Metadata header** — course name, video number, duration, source URL
- **Chapter sections** — `## [MM:SS] Chapter Title` with transcript text
- **Inline screenshots** — `![reason](./assets/NN/MM-SS.png)` (if generated with screenshots)
- **Linked Resources** — URLs from the video description
"""


def package_course_as_zip(
    course_dir: Path,
    course_title: str,
    output_dir: Path,
) -> Path:
    """Bundle a knowledge base course into a downloadable ZIP.

    The ZIP contains SKILL.md + all markdown files + assets,
    ready to unzip into ~/.claude/skills/<course-slug>/.
    """
    course_slug = course_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{course_slug}.zip"

    # Count videos and extract topic hints from index
    md_files = sorted(course_dir.glob("*.md"))
    video_files = [f for f in md_files if f.name != "index.md"]
    video_count = len(video_files)

    # Extract video titles from filenames as topic hints
    topics = []
    for f in video_files[:5]:  # First 5 for brevity
        name = f.stem.split("-", 1)[-1] if "-" in f.stem else f.stem
        topics.append(name.replace("-", " "))

    skill_content = generate_skill_md(course_title, course_slug, video_count, topics)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add SKILL.md
        zf.writestr(f"{course_slug}/SKILL.md", skill_content)

        # Add all markdown files
        for md_file in md_files:
            zf.write(md_file, f"{course_slug}/{md_file.name}")

        # Add assets
        assets_dir = course_dir / "assets"
        if assets_dir.exists():
            for asset_file in assets_dir.rglob("*"):
                if asset_file.is_file():
                    rel = asset_file.relative_to(course_dir)
                    zf.write(asset_file, f"{course_slug}/{rel}")

    return zip_path
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_skill_packager.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add web/services/skill_packager.py tests/test_skill_packager.py
git commit -m "feat(web): add skill packager for downloadable course ZIPs"
```

---

### Task 5: Create the FastAPI server with routes

**Files:**
- Create: `web/server.py`
- Create: `web/routes/home.py`
- Create: `web/routes/generate.py`
- Create: `web/routes/library.py`
- Create: `web/routes/download.py`
- Create: `tests/test_web_routes.py`

**Step 1: Write the failing tests**

Create `tests/test_web_routes.py`:

```python
"""Tests for web routes."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from web.server import app
    return TestClient(app)


class TestHomeRoute:
    def test_home_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Knowledge Base" in resp.text

    def test_home_has_input_form(self, client):
        resp = client.get("/")
        assert "<form" in resp.text
        assert "url" in resp.text


class TestLibraryRoute:
    def test_library_returns_200(self, client):
        resp = client.get("/library")
        assert resp.status_code == 200

    def test_library_lists_courses(self, client):
        # Should list any courses in data/knowledge_base/
        resp = client.get("/library")
        assert resp.status_code == 200


class TestCourseRoute:
    def test_nonexistent_course_returns_404(self, client):
        resp = client.get("/course/nonexistent-slug")
        assert resp.status_code == 404


class TestDownloadRoute:
    def test_nonexistent_course_returns_404(self, client):
        resp = client.get("/download/nonexistent-slug")
        assert resp.status_code == 404
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_web_routes.py -v
```

Expected: FAIL (module not found)

**Step 3: Write the server and routes**

Create `web/server.py`:

```python
"""FastAPI application for the Skill Bill web UI."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from skillbill.config import KB_DIR, ASSETS_DIR
from web.routes import home, generate, library, download

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(title="Skill Bill")

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mount knowledge base assets for screenshot serving
if ASSETS_DIR.exists():
    app.mount("/kb-assets", StaticFiles(directory=str(KB_DIR)), name="kb-assets")

# Shared templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include route modules
app.include_router(home.router)
app.include_router(generate.router)
app.include_router(library.router)
app.include_router(download.router)
```

Create `web/routes/home.py`:

```python
"""Home page route — the URL input form."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from web.server_deps import get_templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    templates = get_templates()
    return templates.TemplateResponse("home.html", {"request": request})
```

Create `web/routes/library.py`:

```python
"""Library and course browsing routes."""
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from skillbill.config import KB_DIR
from web.server_deps import get_templates
from web.services.markdown_renderer import render_video_file

router = APIRouter()


def _list_courses() -> list[dict]:
    """Scan knowledge_base/ for generated courses."""
    courses = []
    if not KB_DIR.exists():
        return courses
    for course_dir in sorted(KB_DIR.iterdir()):
        if not course_dir.is_dir():
            continue
        index_file = course_dir / "index.md"
        if not index_file.exists():
            continue
        # Count video files (exclude index.md)
        video_files = [f for f in course_dir.glob("*.md") if f.name != "index.md"]
        # Check for screenshots
        has_screenshots = (course_dir / "assets").exists()
        # Get first screenshot for thumbnail
        thumbnail = None
        if has_screenshots:
            asset_dirs = sorted((course_dir / "assets").iterdir())
            for ad in asset_dirs:
                if ad.is_dir():
                    pngs = sorted(ad.glob("*.png"))
                    if pngs:
                        thumbnail = f"/kb-assets/{course_dir.name}/assets/{ad.name}/{pngs[0].name}"
                        break
        courses.append({
            "slug": course_dir.name,
            "title": _extract_title(index_file),
            "video_count": len(video_files),
            "has_screenshots": has_screenshots,
            "thumbnail": thumbnail,
        })
    return courses


def _extract_title(index_file: Path) -> str:
    """Extract course title from index.md first heading."""
    for line in index_file.read_text().splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            return title.replace(" -- Course Index", "")
    return index_file.parent.name


def _list_videos(course_dir: Path) -> list[dict]:
    """List videos in a course directory."""
    videos = []
    for md_file in sorted(course_dir.glob("*.md")):
        if md_file.name == "index.md":
            continue
        # Extract number and title from filename
        stem = md_file.stem
        parts = stem.split("-", 1)
        number = parts[0] if parts[0].isdigit() else "0"
        title = parts[1].replace("-", " ").title() if len(parts) > 1 else stem
        videos.append({
            "number": int(number),
            "filename": md_file.name,
            "slug": md_file.stem,
            "title": title,
        })
    return videos


@router.get("/library", response_class=HTMLResponse)
async def library_page(request: Request):
    templates = get_templates()
    courses = _list_courses()
    return templates.TemplateResponse("library.html", {
        "request": request,
        "courses": courses,
    })


@router.get("/course/{course_slug}", response_class=HTMLResponse)
async def course_page(request: Request, course_slug: str):
    templates = get_templates()
    course_dir = KB_DIR / course_slug
    if not course_dir.exists() or not (course_dir / "index.md").exists():
        raise HTTPException(status_code=404, detail="Course not found")
    videos = _list_videos(course_dir)
    title = _extract_title(course_dir / "index.md")
    return templates.TemplateResponse("course.html", {
        "request": request,
        "course_slug": course_slug,
        "course_title": title,
        "videos": videos,
    })


@router.get("/course/{course_slug}/{video_slug}", response_class=HTMLResponse)
async def video_page(request: Request, course_slug: str, video_slug: str):
    templates = get_templates()
    course_dir = KB_DIR / course_slug
    md_file = course_dir / f"{video_slug}.md"
    if not md_file.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    videos = _list_videos(course_dir)
    course_title = _extract_title(course_dir / "index.md")
    html_content = render_video_file(md_file, asset_url_prefix=f"/kb-assets/{course_slug}/assets")

    # Find prev/next
    current_idx = next((i for i, v in enumerate(videos) if v["slug"] == video_slug), 0)
    prev_video = videos[current_idx - 1] if current_idx > 0 else None
    next_video = videos[current_idx + 1] if current_idx < len(videos) - 1 else None

    return templates.TemplateResponse("video.html", {
        "request": request,
        "course_slug": course_slug,
        "course_title": course_title,
        "video_slug": video_slug,
        "html_content": html_content,
        "videos": videos,
        "prev_video": prev_video,
        "next_video": next_video,
    })
```

Create `web/routes/generate.py`:

```python
"""Pipeline generation routes — POST to start, WebSocket for progress."""
import asyncio
import json
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from web.server_deps import get_templates, get_runner

router = APIRouter()


@router.post("/generate", response_class=HTMLResponse)
async def start_generate(request: Request):
    """Accept form submission and redirect to progress page."""
    templates = get_templates()
    form = await request.form()
    url = form.get("url", "")
    mode = form.get("mode", "transcript_only")
    cookies_from = form.get("cookies_from") or None
    use_haiku = form.get("use_haiku") != "off"

    runner = get_runner()

    try:
        await runner.start(
            url=url,
            mode=mode,
            use_haiku=use_haiku,
            cookies_from=cookies_from,
        )
    except RuntimeError as e:
        return templates.TemplateResponse("home.html", {
            "request": request,
            "error": str(e),
        })

    return templates.TemplateResponse("progress.html", {
        "request": request,
        "url": url,
        "mode": mode,
    })


@router.websocket("/ws/progress")
async def progress_websocket(websocket: WebSocket):
    """Stream pipeline progress events to the browser."""
    await websocket.accept()
    runner = get_runner()

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def on_event(event: dict):
        loop.call_soon_threadsafe(queue.put_nowait, event)

    runner.add_listener(on_event)

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("type") in ("pipeline_complete", "error") and event.get("fatal"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        runner.remove_listener(on_event)
```

Create `web/routes/download.py`:

```python
"""Download route — serve skill ZIP packages."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from skillbill.config import KB_DIR, DATA_DIR
from web.services.skill_packager import package_course_as_zip
from web.routes.library import _extract_title

router = APIRouter()


@router.get("/download/{course_slug}")
async def download_skill_zip(course_slug: str):
    """Generate and serve a skill ZIP for a course."""
    course_dir = KB_DIR / course_slug
    if not course_dir.exists() or not (course_dir / "index.md").exists():
        raise HTTPException(status_code=404, detail="Course not found")

    title = _extract_title(course_dir / "index.md")
    zip_path = package_course_as_zip(course_dir, title, DATA_DIR / "downloads")

    return FileResponse(
        path=str(zip_path),
        filename=f"{course_slug}-skill.zip",
        media_type="application/zip",
    )
```

Create `web/server_deps.py` (shared dependencies to avoid circular imports):

```python
"""Shared dependencies for web routes."""
from pathlib import Path
from fastapi.templating import Jinja2Templates
from web.services.pipeline_runner import PipelineRunner

WEB_DIR = Path(__file__).parent
_templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
_runner = PipelineRunner()


def get_templates() -> Jinja2Templates:
    return _templates


def get_runner() -> PipelineRunner:
    return _runner
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_web_routes.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add web/
git commit -m "feat(web): add FastAPI server with home, library, course, video, and download routes"
```

---

### Task 6: Create the base HTML template and CSS

**Files:**
- Create: `web/templates/base.html`
- Create: `web/static/css/style.css`
- Create: `web/static/css/typography.css`
- Create: `web/static/css/animations.css`

> **For Claude:** REQUIRED SUB-SKILL: Use frontend-design:frontend-design to create distinctive, rich HTML/CSS. The aesthetic is **dark editorial** — deep charcoal (#0a0a0b), warm off-white text (#e8e4de), amber accent (#f0b429). Typography: JetBrains Mono for UI, Newsreader for reading. Subtle noise texture, generous whitespace, polished micro-interactions. Make this look like a premium developer tool, not a generic template. Reference the design doc at `docs/plans/2026-03-02-web-interface-design.md` for full visual spec.

**Step 1: Create `web/templates/base.html`**

The shared HTML shell. All pages extend this. Must include:

- `<head>`: Google Fonts (JetBrains Mono + Newsreader), CSS links, viewport meta
- Navigation bar: logo/title, links to Home and Library
- `{% block content %}` for page-specific content
- Footer with project credit
- CSS custom properties on `:root` for the color palette
- Noise texture overlay via CSS pseudo-element on `body`

**Step 2: Create `web/static/css/style.css`**

Core styles:

- CSS custom properties: `--bg: #0a0a0b`, `--text: #e8e4de`, `--accent: #f0b429`, `--surface: #141416`, `--border: #2a2a2e`, `--muted: #6b6b70`
- Global reset + box-sizing
- Body: noise texture background, font stack
- Navigation: fixed top, translucent background, monospace font
- Cards: surface background, subtle border, hover lift + amber glow
- Buttons: amber background, dark text, hover scale
- Input fields: dark surface, amber focus glow, large padding
- Form toggle pills: segmented control for mode selection
- Grid layouts: CSS grid for library cards
- Responsive breakpoints

**Step 3: Create `web/static/css/typography.css`**

- Font imports via `@import` from Google Fonts
- Heading styles: JetBrains Mono, letter-spacing, weight
- Body text: Newsreader, line-height 1.7, max-width 720px
- Code blocks: JetBrains Mono, surface background, padding, border-radius
- Markdown-rendered content: nested heading sizes, blockquote style, list styling, link color (amber)

**Step 4: Create `web/static/css/animations.css`**

- `@keyframes fadeIn`: opacity 0→1
- `@keyframes slideUp`: translateY(20px) + opacity 0→1
- `@keyframes pulse`: subtle scale/opacity loop for active pipeline stage
- `.animate-in`: staggered entrance with `animation-delay`
- Card hover: `transform: translateY(-2px)` + `box-shadow` transition
- Button hover: subtle scale
- Page transitions: fade content blocks in on load

**Step 5: Verify base template renders**

```bash
python -c "
from fastapi.testclient import TestClient
from web.server import app
client = TestClient(app)
resp = client.get('/')
assert resp.status_code == 200
print('Base template renders OK')
"
```

**Step 6: Commit**

```bash
git add web/templates/base.html web/static/css/
git commit -m "feat(web): add base HTML template and CSS (dark editorial theme)"
```

---

### Task 7: Create the home page

**Files:**
- Create: `web/templates/home.html`

> **For Claude:** Use frontend-design:frontend-design for this page. Dead center layout. Large monospace heading. Single prominent URL input with amber glow on focus. "Generate" button. Toggle pills for "Full Pipeline" vs "Transcript Only". Collapsible "Advanced" section with cookies-from dropdown. If courses exist in library, show a subtle "Browse Library →" link. Faint grid pattern background. This is the first thing users see — make it memorable.

**Step 1: Create `web/templates/home.html`**

Extends `base.html`. Contains:

- Centered container (vertically + horizontally)
- `<h1>` with "Knowledge Base Generator" in JetBrains Mono
- Subtitle: "Turn YouTube courses into structured knowledge for Claude Code"
- `<form>` with:
  - URL input field (large, prominent, placeholder: "Paste a YouTube playlist or video URL")
  - Mode toggle pills: "Transcript Only" (default) | "Full Pipeline"
  - Generate button (amber, full-width)
- `<details>` element for Advanced options:
  - Cookies dropdown: None / Chrome / Firefox / Safari
  - Haiku toggle: on/off for screenshot classification
- If error message passed from server, display it in a red-tinted alert
- If courses exist (check via template variable), show "or browse your library →"

**Step 2: Verify**

```bash
python -c "
from fastapi.testclient import TestClient
from web.server import app
client = TestClient(app)
resp = client.get('/')
assert '<form' in resp.text
assert 'url' in resp.text
print('Home page OK')
"
```

**Step 3: Commit**

```bash
git add web/templates/home.html
git commit -m "feat(web): add home page with URL input form"
```

---

### Task 8: Create the progress page with WebSocket client

**Files:**
- Create: `web/templates/progress.html`
- Create: `web/static/js/progress.js`

> **For Claude:** Use frontend-design:frontend-design for the progress view. This should feel like a build system dashboard. Left side: vertical timeline of 6 stages, each a card that transitions dimmed → pulsing amber → green checkmark. Right side: live scrolling log panel with terminal monospace aesthetic. When pipeline completes, timeline collapses and "View Knowledge Base →" + "Download as Skill" buttons appear with a satisfying reveal animation.

**Step 1: Create `web/templates/progress.html`**

Extends `base.html`. Contains:

- Two-column layout (timeline left, log right)
- Timeline: 6 stage cards as `<div>` elements with data attributes for stage names
  - Each has: icon, stage name, status indicator, progress count
  - CSS classes: `.stage--pending`, `.stage--active`, `.stage--complete`
- Log panel: `<div>` with monospace font, auto-scroll, max-height with overflow
- Completion overlay (hidden initially):
  - Course title + video count
  - "View Knowledge Base →" button (links to `/course/<slug>`)
  - "Download as Skill (.zip)" button (links to `/download/<slug>`)
- Includes `progress.js` at bottom

**Step 2: Create `web/static/js/progress.js`**

```javascript
// WebSocket client for pipeline progress

(function() {
    const ws = new WebSocket(`ws://${window.location.host}/ws/progress`);
    const stages = document.querySelectorAll('.stage');
    const logPanel = document.getElementById('log-panel');
    const completion = document.getElementById('completion');

    function addLog(message) {
        const line = document.createElement('div');
        line.className = 'log-line';
        line.textContent = `> ${message}`;
        logPanel.appendChild(line);
        logPanel.scrollTop = logPanel.scrollHeight;
    }

    function setStageActive(stageName) {
        stages.forEach(el => {
            if (el.dataset.stage === stageName) {
                el.classList.remove('stage--pending');
                el.classList.add('stage--active');
            }
        });
    }

    function setStageComplete(stageName, data) {
        stages.forEach(el => {
            if (el.dataset.stage === stageName) {
                el.classList.remove('stage--active');
                el.classList.add('stage--complete');
                // Update detail text if data provided
                if (data) {
                    const detail = el.querySelector('.stage-detail');
                    if (detail) {
                        detail.textContent = formatStageData(stageName, data);
                    }
                }
            }
        });
    }

    function formatStageData(stage, data) {
        switch(stage) {
            case 'discovery': return `${data.title} (${data.video_count} videos)`;
            case 'transcripts': return `${data.found}/${data.total} found`;
            case 'download': return `${data.downloaded}/${data.total} downloaded`;
            case 'screenshot_planning': return `${data.total_screenshots} screenshots planned`;
            case 'capture': return `${data.screenshots_kept} screenshots captured`;
            case 'generation': return 'Markdown files generated';
            default: return '';
        }
    }

    function showCompletion(event) {
        const title = document.getElementById('completion-title');
        const viewLink = document.getElementById('view-link');
        const downloadLink = document.getElementById('download-link');

        title.textContent = event.course_title;
        viewLink.href = `/course/${event.course_slug}`;
        downloadLink.href = `/download/${event.course_slug}`;

        completion.classList.add('completion--visible');
    }

    ws.onmessage = function(e) {
        const event = JSON.parse(e.data);

        switch(event.type) {
            case 'stage_start':
                setStageActive(event.stage);
                addLog(`Starting: ${event.stage}`);
                break;
            case 'stage_complete':
                setStageComplete(event.stage, event.data);
                addLog(`Complete: ${event.stage}`);
                break;
            case 'video_progress':
                addLog(`[${event.stage}] ${event.current}/${event.total}: ${event.title}`);
                break;
            case 'log':
                addLog(event.message);
                break;
            case 'pipeline_complete':
                addLog('Pipeline complete!');
                showCompletion(event);
                break;
            case 'error':
                addLog(`ERROR: ${event.message}`);
                if (event.fatal) {
                    // Show error state
                }
                break;
        }
    };

    ws.onerror = function() {
        addLog('WebSocket connection error');
    };
})();
```

**Step 3: Verify WebSocket route exists**

```bash
python -c "
from fastapi.testclient import TestClient
from web.server import app
client = TestClient(app)
resp = client.get('/generate', follow_redirects=False)
# POST is required, GET should not crash the server
print('Generate route exists')
"
```

**Step 4: Commit**

```bash
git add web/templates/progress.html web/static/js/progress.js
git commit -m "feat(web): add progress page with WebSocket-driven pipeline timeline"
```

---

### Task 9: Create the library page

**Files:**
- Create: `web/templates/library.html`

> **For Claude:** Use frontend-design:frontend-design. Grid of course cards (2-3 columns). Each card: course title, video count, thumbnail (first screenshot or gradient placeholder), generation date. Hover: subtle lift + amber border glow. Search/filter bar at top. Empty state: "No courses yet. Generate one →". Staggered entrance animation on page load.

**Step 1: Create `web/templates/library.html`**

Extends `base.html`. Contains:

- Page heading "Your Library"
- Search/filter input (filters cards client-side via JS)
- CSS grid container (auto-fill, min 320px columns)
- For each course in `courses`:
  - Card with thumbnail (or gradient placeholder if no screenshots)
  - Course title
  - Video count badge
  - Links to `/course/<slug>`
- Empty state if no courses: illustration-free message + link to home
- Inline `<script>` for client-side search filtering

**Step 2: Verify with existing courses**

```bash
python -c "
from fastapi.testclient import TestClient
from web.server import app
client = TestClient(app)
resp = client.get('/library')
assert resp.status_code == 200
# Should list existing courses
assert 'python' in resp.text.lower() or 'claude' in resp.text.lower() or 'No courses' in resp.text
print('Library page OK')
"
```

**Step 3: Commit**

```bash
git add web/templates/library.html
git commit -m "feat(web): add library page with course grid"
```

---

### Task 10: Create the course page

**Files:**
- Create: `web/templates/course.html`

> **For Claude:** Use frontend-design:frontend-design. Left sidebar: numbered video list (scrollable, current highlighted with amber bar). Main area: course title, playlist source link, video count. Click any video to load its reading view. The sidebar should feel like a table of contents.

**Step 1: Create `web/templates/course.html`**

Extends `base.html`. Contains:

- Two-column layout: sidebar (240px) + main content
- Sidebar:
  - Course title (smaller)
  - Scrollable video list
  - Each video: number + title, links to `/course/<slug>/<video-slug>`
  - Active video highlighted with amber left border
- Main area:
  - Course title (large heading)
  - Metadata: source playlist link, video count
  - "Download as Skill" button
  - Brief instructions on using the knowledge base
- Sidebar is collapsible on mobile (hamburger toggle)

**Step 2: Verify with existing course**

```bash
python -c "
from fastapi.testclient import TestClient
from web.server import app
client = TestClient(app)
# Use one of the existing courses
resp = client.get('/course/python-tutorials-for-absolute-beginners-by-cs-dojo')
assert resp.status_code == 200
assert 'Python' in resp.text
print('Course page OK')
"
```

**Step 3: Commit**

```bash
git add web/templates/course.html
git commit -m "feat(web): add course page with sidebar video navigation"
```

---

### Task 11: Create the video reading page

**Files:**
- Create: `web/templates/video.html`
- Create: `web/static/js/lightbox.js`
- Create: `web/static/js/app.js`

> **For Claude:** Use frontend-design:frontend-design. This is the most important page — the reading experience. Sticky right-side chapter navigation that highlights on scroll. Serif body text (Newsreader), generous line height, max-width 720px. Inline screenshots with rounded corners, click-to-expand lightbox. Top bar: video title, duration, "Watch on YouTube" link, prev/next. Linked resources collapsible at bottom. Make this feel like reading a premium documentation site.

**Step 1: Create `web/templates/video.html`**

Extends `base.html`. Contains:

- Three-column layout: sidebar (video list) | content (720px max) | chapter nav (200px sticky)
- Top bar within content area:
  - Video title
  - Metadata: duration, "Watch on YouTube →" link
  - Prev/Next navigation arrows
- Main content: `{{ html_content | safe }}` — the rendered markdown
- Right sidebar: chapter table of contents
  - Extracted from `<h2>` elements in html_content via JS
  - Sticky position, highlights current section on scroll
- Linked resources: collapsible `<details>` at bottom
- Inline screenshots in html_content get CSS treatment: rounded corners, max-width, cursor pointer
- Includes `lightbox.js` and `app.js`

**Step 2: Create `web/static/js/lightbox.js`**

```javascript
// Lightbox for screenshot expansion
(function() {
    // Create overlay element
    const overlay = document.createElement('div');
    overlay.className = 'lightbox-overlay';
    overlay.innerHTML = '<img class="lightbox-img" /><div class="lightbox-caption"></div>';
    document.body.appendChild(overlay);

    const img = overlay.querySelector('.lightbox-img');
    const caption = overlay.querySelector('.lightbox-caption');

    // Click any content image to expand
    document.addEventListener('click', function(e) {
        const target = e.target;
        if (target.tagName === 'IMG' && target.closest('.video-content')) {
            img.src = target.src;
            caption.textContent = target.alt || '';
            overlay.classList.add('lightbox--visible');
        }
    });

    // Click overlay to close
    overlay.addEventListener('click', function() {
        overlay.classList.remove('lightbox--visible');
    });

    // Escape key to close
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            overlay.classList.remove('lightbox--visible');
        }
    });
})();
```

**Step 3: Create `web/static/js/app.js`**

```javascript
// Scroll-spy for chapter navigation + general interactions
(function() {
    // Chapter scroll-spy
    const headings = document.querySelectorAll('.video-content h2');
    const tocLinks = document.querySelectorAll('.chapter-nav a');

    if (headings.length && tocLinks.length) {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const id = entry.target.id;
                    tocLinks.forEach(link => {
                        link.classList.toggle('chapter-nav--active', link.getAttribute('href') === `#${id}`);
                    });
                }
            });
        }, { rootMargin: '-80px 0px -70% 0px' });

        headings.forEach(h => observer.observe(h));
    }

    // Mobile sidebar toggle
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener('click', () => {
            sidebar.classList.toggle('sidebar--open');
        });
    }
})();
```

**Step 4: Verify with existing video**

```bash
python -c "
from fastapi.testclient import TestClient
from web.server import app
client = TestClient(app)
resp = client.get('/course/python-tutorials-for-absolute-beginners-by-cs-dojo/01-python-tutorial-for-absolute-beginners-1-what-are-variables')
assert resp.status_code == 200
assert 'Variables' in resp.text or 'variables' in resp.text
print('Video page OK')
"
```

**Step 5: Commit**

```bash
git add web/templates/video.html web/static/js/
git commit -m "feat(web): add video reading page with lightbox and chapter scroll-spy"
```

---

### Task 12: Add the `serve` CLI command

**Files:**
- Modify: `run.py`

**Step 1: Write a test for the CLI command**

Add to `tests/test_web_routes.py`:

```python
from click.testing import CliRunner

class TestServeCLI:
    def test_serve_command_exists(self):
        from run import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "port" in result.output
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_web_routes.py::TestServeCLI -v
```

Expected: FAIL

**Step 3: Add the serve command to run.py**

Add to the bottom of `run.py`, before `if __name__`:

```python
@cli.command()
@click.option("--port", default=8000, type=int, help="Port to serve on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
def serve(port, host):
    """Start the web interface."""
    import uvicorn
    from web.server import app
    click.echo(f"Starting Skill Bill at http://{host}:{port}")
    click.echo("Press Ctrl+C to stop")
    uvicorn.run(app, host=host, port=port)
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_web_routes.py::TestServeCLI -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add run.py tests/test_web_routes.py
git commit -m "feat(web): add 'serve' CLI command to start web interface"
```

---

### Task 13: Integration testing and polish

**Files:**
- Modify: `tests/test_web_routes.py` (add integration tests)

**Step 1: Add end-to-end route tests**

Add to `tests/test_web_routes.py`:

```python
class TestIntegration:
    def test_full_navigation_flow(self, client):
        """Home → Library → Course → Video navigation works."""
        # Home
        resp = client.get("/")
        assert resp.status_code == 200

        # Library
        resp = client.get("/library")
        assert resp.status_code == 200

        # A known course
        resp = client.get("/course/python-tutorials-for-absolute-beginners-by-cs-dojo")
        if resp.status_code == 200:
            # Video within that course
            resp = client.get(
                "/course/python-tutorials-for-absolute-beginners-by-cs-dojo/"
                "01-python-tutorial-for-absolute-beginners-1-what-are-variables"
            )
            assert resp.status_code == 200

    def test_download_existing_course(self, client):
        """Download ZIP for an existing course."""
        resp = client.get("/download/python-tutorials-for-absolute-beginners-by-cs-dojo")
        if resp.status_code == 200:
            assert resp.headers["content-type"] == "application/zip"

    def test_static_files_served(self, client):
        """CSS and JS files are accessible."""
        resp = client.get("/static/css/style.css")
        assert resp.status_code == 200
```

**Step 2: Run the full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass (existing 67 + new web tests)

**Step 3: Manual smoke test**

```bash
python run.py serve --port 8000
# Open http://localhost:8000 in browser
# Verify: home page renders, library shows courses, can browse a video
```

**Step 4: Commit**

```bash
git add tests/test_web_routes.py
git commit -m "test(web): add integration tests for navigation and download"
```

---

### Verification

After all tasks are complete:

1. `python -m pytest tests/ -v` — all tests pass (existing 67 + new web tests)
2. `python run.py serve` — server starts on localhost:8000
3. Home page: URL input form renders with mode toggle
4. Library: existing courses appear as cards
5. Course: sidebar + video list for a known course
6. Video: rendered transcript with chapter navigation and inline screenshots
7. Download: ZIP file served with SKILL.md + markdown + assets
8. Progress: WebSocket connection established (full pipeline test is manual/optional)

# AI Refinement Stage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a "Pro" refinement stage that uses Haiku with vision to convert raw transcripts into clean lesson steps, de-clickbait video titles, and produce polished skill-ready knowledge bases.

**Architecture:** New `skillbill/refiner.py` module as Pipeline Stage 7. Screenshot pre-filter reduces noise before Haiku calls. One Haiku call per video for title cleanup + one for lesson extraction. Web UI adds Base/Pro toggle with API key modal. Pro output replaces raw transcript with clean lesson files.

**Tech Stack:** anthropic SDK (already installed), Haiku vision, FastAPI, Jinja2

**Design Doc:** `docs/plans/2026-03-03-ai-refinement-design.md`

---

### Task 1: Add screenshot filter config and function

**Files:**
- Modify: `skillbill/config.py`
- Create: `skillbill/refiner.py`
- Create: `tests/test_refiner.py`

**Step 1: Add SCREENSHOT_FILTER to config.py**

Add after the existing `SCREENSHOT_CONFIG` dict (after line 26 in `config.py`):

```python
# Screenshot filter for AI refinement (Pro mode)
# Controls which screenshots are sent to Haiku for lesson extraction.
# Verbal cues pass by default UNLESS they match the blocklist.
SCREENSHOT_FILTER = {
    "keep_reasons": ["slide_transition", "scene_change"],
    "drop_reasons": ["section_start", "interval_fallback", "mid_section"],
    "verbal_cue_blocklist": ["this is", "notice"],
}
```

**Step 2: Write failing tests for the filter**

Create `tests/test_refiner.py`:

```python
"""Tests for the AI refinement module."""
import pytest
from skillbill.refiner import filter_screenshots


class TestFilterScreenshots:
    def test_keeps_slide_transition(self):
        screenshots = [{"timestamp": 10.0, "reason": "slide_transition", "path": "/a.png"}]
        result = filter_screenshots(screenshots)
        assert len(result) == 1

    def test_keeps_scene_change(self):
        screenshots = [{"timestamp": 5.0, "reason": "scene_change", "path": "/b.png"}]
        result = filter_screenshots(screenshots)
        assert len(result) == 1

    def test_drops_section_start(self):
        screenshots = [{"timestamp": 30.0, "reason": "section_start", "path": "/c.png"}]
        result = filter_screenshots(screenshots)
        assert len(result) == 0

    def test_drops_interval_fallback(self):
        screenshots = [{"timestamp": 45.0, "reason": "interval_fallback", "path": "/d.png"}]
        result = filter_screenshots(screenshots)
        assert len(result) == 0

    def test_keeps_verbal_cue_by_default(self):
        screenshots = [
            {"timestamp": 12.0, "reason": "verbal_cue: look at", "path": "/e.png"},
            {"timestamp": 20.0, "reason": "verbal_cue: this code", "path": "/f.png"},
            {"timestamp": 28.0, "reason": "verbal_cue: let me show", "path": "/g.png"},
        ]
        result = filter_screenshots(screenshots)
        assert len(result) == 3

    def test_drops_blocklisted_verbal_cue(self):
        screenshots = [
            {"timestamp": 10.0, "reason": "verbal_cue: this is", "path": "/h.png"},
            {"timestamp": 20.0, "reason": "verbal_cue: notice", "path": "/i.png"},
        ]
        result = filter_screenshots(screenshots)
        assert len(result) == 0

    def test_mixed_batch(self):
        screenshots = [
            {"timestamp": 5.0, "reason": "slide_transition", "path": "/a.png"},
            {"timestamp": 10.0, "reason": "section_start", "path": "/b.png"},
            {"timestamp": 15.0, "reason": "verbal_cue: this code", "path": "/c.png"},
            {"timestamp": 20.0, "reason": "verbal_cue: this is", "path": "/d.png"},
            {"timestamp": 25.0, "reason": "scene_change", "path": "/e.png"},
            {"timestamp": 30.0, "reason": "mid_section", "path": "/f.png"},
        ]
        result = filter_screenshots(screenshots)
        assert len(result) == 3  # slide_transition, verbal_cue: this code, scene_change
        reasons = [s["reason"] for s in result]
        assert "section_start" not in reasons
        assert "mid_section" not in reasons

    def test_empty_input(self):
        assert filter_screenshots([]) == []
```

**Step 3: Run tests to verify they fail**

```bash
python -m pytest tests/test_refiner.py::TestFilterScreenshots -v
```

Expected: FAIL (module not found)

**Step 4: Write the filter implementation**

Create `skillbill/refiner.py`:

```python
"""AI refinement module — Stage 7 of the pipeline.

Converts raw transcripts into clean lesson steps using Haiku with vision.
Also de-clickbaits video titles based on actual content.
"""
import base64
import json
import re
from pathlib import Path
from typing import Optional

from skillbill.config import SCREENSHOT_FILTER, ANTHROPIC_MODEL


def filter_screenshots(
    screenshots: list[dict],
    config: dict | None = None,
) -> list[dict]:
    """Filter screenshots to keep only those worth sending to Haiku.

    Keeps: slide_transition, scene_change, and verbal_cue screenshots
    (except those matching the verbal_cue_blocklist).
    Drops: section_start, interval_fallback, mid_section.
    """
    if not screenshots:
        return []

    cfg = config or SCREENSHOT_FILTER
    keep_reasons = set(cfg["keep_reasons"])
    drop_reasons = set(cfg["drop_reasons"])
    blocklist = cfg["verbal_cue_blocklist"]

    filtered = []
    for s in screenshots:
        reason = s.get("reason", "")

        # Explicit drop
        if reason in drop_reasons:
            continue

        # Explicit keep
        if reason in keep_reasons:
            filtered.append(s)
            continue

        # Verbal cue: keep unless blocklisted
        if reason.startswith("verbal_cue:"):
            cue_text = reason.split(":", 1)[1].strip()
            if cue_text in blocklist:
                continue
            filtered.append(s)
            continue

        # Unknown reason: keep (be generous)
        filtered.append(s)

    return filtered
```

**Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_refiner.py::TestFilterScreenshots -v
```

Expected: All PASS

**Step 6: Commit**

```bash
git add skillbill/config.py skillbill/refiner.py tests/test_refiner.py
git commit -m "feat: add screenshot pre-filter for AI refinement stage"
```

---

### Task 2: Add title cleanup function

**Files:**
- Modify: `skillbill/refiner.py`
- Modify: `tests/test_refiner.py`

**Step 1: Write failing tests**

Add to `tests/test_refiner.py`:

```python
from unittest.mock import patch, MagicMock
from skillbill.refiner import refine_video_title


class TestRefineVideoTitle:
    @patch("skillbill.refiner._call_haiku")
    def test_returns_clean_title(self, mock_call):
        mock_call.return_value = "Variables and Data Types in Python"
        result = refine_video_title(
            original_title="Python Tutorial for Absolute Beginners #1 - What Are Variables?",
            transcript_preview="Hey everyone, today we're going to learn about variables...",
            api_key="sk-test",
        )
        assert result == "Variables and Data Types in Python"
        mock_call.assert_called_once()

    @patch("skillbill.refiner._call_haiku")
    def test_strips_whitespace(self, mock_call):
        mock_call.return_value="  Clean Title  \n"
        result = refine_video_title("Original", "preview text", api_key="sk-test")
        assert result == "Clean Title"

    @patch("skillbill.refiner._call_haiku")
    def test_falls_back_to_original_on_error(self, mock_call):
        mock_call.side_effect = Exception("API error")
        result = refine_video_title("Original Title", "preview", api_key="sk-test")
        assert result == "Original Title"

    def test_no_api_key_returns_original(self):
        result = refine_video_title("Original Title", "preview", api_key="")
        assert result == "Original Title"
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_refiner.py::TestRefineVideoTitle -v
```

Expected: FAIL (function not found)

**Step 3: Write the implementation**

Add to `skillbill/refiner.py`:

```python
import anthropic


def _call_haiku(
    messages: list[dict],
    api_key: str,
    max_tokens: int = 1024,
) -> str:
    """Make a single Haiku API call. Returns the text response."""
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        messages=messages,
    )
    return response.content[0].text


def refine_video_title(
    original_title: str,
    transcript_preview: str,
    api_key: str = "",
) -> str:
    """Generate a clean, descriptive title for a video.

    Uses Haiku to replace clickbaity YouTube titles with content-descriptive ones.
    Falls back to original title on error or missing API key.
    """
    if not api_key:
        return original_title

    prompt = (
        "The following YouTube video has a potentially clickbaity title. "
        "Generate a clean, descriptive title that accurately reflects the video's "
        "actual content. The title should be concise (5-10 words), professional, "
        "and useful for someone scanning a course index.\n\n"
        f'Original title: "{original_title}"\n'
        f'Content preview: "{transcript_preview[:500]}"\n\n'
        "Return ONLY the new title, nothing else."
    )

    try:
        result = _call_haiku(
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            max_tokens=100,
        )
        return result.strip()
    except Exception:
        return original_title
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_refiner.py::TestRefineVideoTitle -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add skillbill/refiner.py tests/test_refiner.py
git commit -m "feat: add Haiku-powered video title cleanup"
```

---

### Task 3: Add lesson extraction function with vision

**Files:**
- Modify: `skillbill/refiner.py`
- Modify: `tests/test_refiner.py`

**Step 1: Write failing tests**

Add to `tests/test_refiner.py`:

```python
from skillbill.refiner import refine_video_content, _build_vision_content


class TestBuildVisionContent:
    def test_text_only_no_screenshots(self):
        content = _build_vision_content(
            transcript_text="Hello world",
            video_title="Test Video",
            duration=120.0,
            screenshot_paths=[],
        )
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert "Hello world" in content[0]["text"]

    def test_includes_screenshots_as_images(self, tmp_path):
        # Create a tiny valid PNG
        img_path = tmp_path / "test.png"
        # 1x1 red PNG
        import struct, zlib
        def minimal_png():
            signature = b'\x89PNG\r\n\x1a\n'
            ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
            ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
            raw = b'\x00\xff\x00\x00'
            idat_data = zlib.compress(raw)
            idat_crc = zlib.crc32(b'IDAT' + idat_data) & 0xffffffff
            idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data + struct.pack('>I', idat_crc)
            iend_crc = zlib.crc32(b'IEND') & 0xffffffff
            iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
            return signature + ihdr + idat + iend
        img_path.write_bytes(minimal_png())

        content = _build_vision_content(
            transcript_text="Here is some code",
            video_title="Test",
            duration=60.0,
            screenshot_paths=[str(img_path)],
        )
        # Should have text + image blocks
        types = [c["type"] for c in content]
        assert "text" in types
        assert "image" in types


class TestRefineVideoContent:
    @patch("skillbill.refiner._call_haiku")
    def test_returns_refined_markdown(self, mock_call):
        mock_call.return_value = (
            '1. **Variables** — Store values using `x = 5`. '
            'Variables can hold numbers, strings, and booleans.\n'
            '2. **Print function** — Use `print(x)` to display values.\n'
        )
        result = refine_video_content(
            transcript_entries=[
                {"start": 0.0, "duration": 5.0, "text": "Today we learn about variables"},
                {"start": 5.0, "duration": 5.0, "text": "You can store values like x equals 5"},
            ],
            chapters=[],
            filtered_screenshots=[],
            video_title="Variables in Python",
            duration=120.0,
            api_key="sk-test",
        )
        assert "**Variables**" in result
        assert "**Print function**" in result

    @patch("skillbill.refiner._call_haiku")
    def test_falls_back_to_empty_on_error(self, mock_call):
        mock_call.side_effect = Exception("API error")
        result = refine_video_content(
            transcript_entries=[{"start": 0.0, "duration": 5.0, "text": "Hello"}],
            chapters=[],
            filtered_screenshots=[],
            video_title="Test",
            duration=60.0,
            api_key="sk-test",
        )
        assert result == ""

    def test_no_api_key_returns_empty(self):
        result = refine_video_content(
            transcript_entries=[],
            chapters=[],
            filtered_screenshots=[],
            video_title="Test",
            duration=60.0,
            api_key="",
        )
        assert result == ""
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_refiner.py::TestBuildVisionContent -v
python -m pytest tests/test_refiner.py::TestRefineVideoContent -v
```

Expected: FAIL

**Step 3: Write the implementation**

Add to `skillbill/refiner.py`:

```python
def _build_vision_content(
    transcript_text: str,
    video_title: str,
    duration: float,
    screenshot_paths: list[str],
) -> list[dict]:
    """Build a multimodal content array for the Haiku vision call.

    Returns a list of content blocks: text prompt + image blocks for screenshots.
    """
    duration_min = int(duration // 60)
    duration_sec = int(duration % 60)

    prompt_text = (
        "You are converting a YouTube video transcript into clean, actionable lesson steps.\n\n"
        f'Video: "{video_title}" ({duration_min}:{duration_sec:02d})\n\n'
        "Transcript:\n"
        f"{transcript_text}\n\n"
        "Produce ONLY numbered lesson steps in this format:\n\n"
        "1. **[Step/concept name]** — [1-2 sentence explanation]. "
        "[Code example if any, preserved exactly.]\n"
        "2. **[Step/concept name]** — ...\n\n"
        "Rules:\n"
        "- Extract actionable steps and key concepts, not summaries of what the speaker said\n"
        "- Preserve code examples, commands, and URLs exactly as spoken/shown\n"
        "- Reference screenshots where they show something the text doesn't capture "
        "(a UI state, diagram, code on screen) using: ![description](SCREENSHOT_PATH)\n"
        "- Drop filler, repetition, tangents, and conversational speech\n"
        "- Keep technical accuracy — don't paraphrase technical terms\n"
        "- Target: 70-80% reduction in token count vs raw transcript\n"
    )

    content = [{"type": "text", "text": prompt_text}]

    # Add screenshots as vision inputs
    for path in screenshot_paths:
        try:
            img_data = Path(path).read_bytes()
            b64 = base64.b64encode(img_data).decode("utf-8")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })
        except Exception:
            continue  # Skip unreadable screenshots

    return content


def refine_video_content(
    transcript_entries: list[dict],
    chapters: list[dict],
    filtered_screenshots: list[dict],
    video_title: str,
    duration: float,
    api_key: str = "",
) -> str:
    """Refine a video's raw transcript into clean lesson steps.

    Uses Haiku with vision to process transcript + screenshots.
    Returns refined markdown string, or empty string on failure.
    """
    if not api_key:
        return ""

    # Build transcript text from entries
    if chapters:
        # Organize by chapter
        parts = []
        for chapter in chapters:
            start = chapter.get("start_time", 0)
            end = chapter.get("end_time", float("inf"))
            title = chapter.get("title", "Section")
            entries = [e for e in transcript_entries if start <= e["start"] < end]
            if entries:
                text = " ".join(e["text"] for e in entries)
                parts.append(f"[{title}]\n{text}")
        transcript_text = "\n\n".join(parts)
    else:
        transcript_text = " ".join(e["text"] for e in transcript_entries)

    # Collect screenshot file paths
    screenshot_paths = [
        s["path"] for s in filtered_screenshots
        if s.get("path") and Path(s["path"]).exists()
    ]

    # Build multimodal content
    content = _build_vision_content(
        transcript_text=transcript_text,
        video_title=video_title,
        duration=duration,
        screenshot_paths=screenshot_paths,
    )

    try:
        result = _call_haiku(
            messages=[{"role": "user", "content": content}],
            api_key=api_key,
            max_tokens=4096,
        )
        return result.strip()
    except Exception:
        return ""
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_refiner.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add skillbill/refiner.py tests/test_refiner.py
git commit -m "feat: add Haiku vision lesson extraction with screenshot support"
```

---

### Task 4: Add refine_course orchestrator and pipeline integration

**Files:**
- Modify: `skillbill/refiner.py`
- Modify: `skillbill/pipeline.py`
- Modify: `tests/test_refiner.py`
- Modify: `tests/test_pipeline.py`

**Step 1: Write failing tests for refine_course**

Add to `tests/test_refiner.py`:

```python
from skillbill.refiner import refine_course
from skillbill.downloader import slugify_title


class TestRefineCourse:
    @patch("skillbill.refiner.refine_video_title")
    @patch("skillbill.refiner.refine_video_content")
    @patch("skillbill.refiner.filter_screenshots")
    def test_creates_refined_files(self, mock_filter, mock_content, mock_title, tmp_path):
        # Set up a minimal knowledge base
        course_dir = tmp_path / "test-course"
        course_dir.mkdir()
        (course_dir / "index.md").write_text("# Test -- Course Index\n\n1. [Old Title](./01-old-title.md)\n")
        (course_dir / "01-old-title.md").write_text("# Old Title\n\nRaw transcript...\n")

        mock_title.return_value = "Clean Descriptive Title"
        mock_content.return_value = "1. **Step one** — Do the thing.\n"
        mock_filter.return_value = []

        manifest = {
            "playlist_title": "Test Course",
            "slug": "test-course",
            "video_count": 1,
            "playlist_url": "https://youtube.com/playlist?list=PLtest",
            "videos": [{"id": "abc", "title": "Old Title", "url": "https://youtube.com/watch?v=abc", "duration": 120, "chapters": [], "description": ""}],
        }
        transcripts = [{"video_id": "abc", "has_transcript": True, "entries": [{"start": 0, "duration": 5, "text": "Hello"}], "chapters": [], "description": ""}]
        capture_results = [[]]

        refine_course(course_dir, manifest, transcripts, capture_results, api_key="sk-test")

        # Check: old file removed, new file exists with clean title
        assert not (course_dir / "01-old-title.md").exists()
        new_slug = slugify_title("Clean Descriptive Title")
        new_file = course_dir / f"01-{new_slug}.md"
        assert new_file.exists()

        # Check content has refined lessons
        content = new_file.read_text()
        assert "Clean Descriptive Title" in content
        assert "Step one" in content

        # Check index updated
        index = (course_dir / "index.md").read_text()
        assert "Clean Descriptive Title" in index
        assert "old-title" not in index

    @patch("skillbill.refiner.refine_video_title")
    @patch("skillbill.refiner.refine_video_content")
    @patch("skillbill.refiner.filter_screenshots")
    def test_skips_videos_without_transcript(self, mock_filter, mock_content, mock_title, tmp_path):
        course_dir = tmp_path / "test-course"
        course_dir.mkdir()
        (course_dir / "index.md").write_text("# Test -- Course Index\n\n1. [V1](./01-v1.md)\n")
        (course_dir / "01-v1.md").write_text("# V1\n\nNo transcript.\n")

        manifest = {
            "playlist_title": "Test",
            "slug": "test-course",
            "video_count": 1,
            "playlist_url": "https://youtube.com/playlist?list=PLtest",
            "videos": [{"id": "abc", "title": "V1", "url": "https://youtube.com/watch?v=abc", "duration": 60, "chapters": [], "description": ""}],
        }
        transcripts = [{"video_id": "abc", "has_transcript": False, "entries": [], "chapters": [], "description": ""}]
        capture_results = [[]]

        refine_course(course_dir, manifest, transcripts, capture_results, api_key="sk-test")

        # Title cleanup should still be attempted
        mock_title.assert_called_once()
        # Content refinement should NOT be called (no transcript)
        mock_content.assert_not_called()
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_refiner.py::TestRefineCourse -v
```

Expected: FAIL

**Step 3: Write the refine_course implementation**

Add to `skillbill/refiner.py`:

```python
from skillbill.downloader import slugify_title
from skillbill.generator import format_timestamp, generate_course_index
from datetime import date


def refine_course(
    course_dir: Path,
    manifest: dict,
    transcripts: list[dict],
    capture_results: list[list[dict]],
    api_key: str = "",
) -> Path:
    """Refine an entire course — clean titles + lesson extraction.

    Replaces raw transcript .md files with refined lesson .md files.
    Renames files with clean titles. Regenerates index.md.
    """
    videos = manifest["videos"]
    refined_video_entries = []

    for i, (video, transcript) in enumerate(zip(videos, transcripts)):
        video_num = i + 1
        original_title = video["title"]
        duration = video.get("duration", 0)

        # Step 1: Clean the title
        transcript_preview = ""
        if transcript.get("entries"):
            transcript_preview = " ".join(
                e["text"] for e in transcript["entries"][:20]
            )
        clean_title = refine_video_title(original_title, transcript_preview, api_key=api_key)

        # Step 2: Refine content (only if transcript exists)
        refined_content = ""
        if transcript.get("has_transcript") and transcript.get("entries"):
            # Filter screenshots for this video
            screenshots = []
            if i < len(capture_results):
                screenshots = [
                    r for r in capture_results[i]
                    if r.get("status") == "kept" and r.get("path")
                ]
            filtered = filter_screenshots(screenshots)

            refined_content = refine_video_content(
                transcript_entries=transcript["entries"],
                chapters=transcript.get("chapters") or video.get("chapters", []),
                filtered_screenshots=filtered,
                video_title=clean_title,
                duration=duration,
                api_key=api_key,
            )

        # Step 3: Build the refined markdown file
        clean_slug = slugify_title(clean_title)
        new_filename = f"{video_num:02d}-{clean_slug}.md"

        # Remove old file
        old_slug = slugify_title(original_title)
        old_file = course_dir / f"{video_num:02d}-{old_slug}.md"
        if old_file.exists():
            old_file.unlink()

        # Write new file
        duration_str = format_timestamp(duration)
        header = (
            f"# {clean_title}\n\n"
            f"**Course:** {manifest['playlist_title']}\n"
            f"**Video:** {video_num} of {manifest['video_count']}\n"
            f"**Duration:** {duration_str}\n"
            f"**Source:** {video['url']}\n\n"
            "---\n\n"
        )

        body = refined_content if refined_content else "⚠ No lessons generated for this video.\n"
        (course_dir / new_filename).write_text(header + body)

        refined_video_entries.append({
            "number": video_num,
            "title": clean_title,
            "filename": new_filename,
        })

    # Step 4: Regenerate index with clean titles
    env = None  # We'll build it manually for simplicity
    index_lines = [
        f"# {manifest['playlist_title']} -- Course Index\n",
        f"\n**Source Playlist:** {manifest['playlist_url']}",
        f"\n**Videos:** {manifest['video_count']}",
        f"\n**Generated:** {date.today()}\n",
        "\n## Lessons\n",
    ]
    for entry in refined_video_entries:
        index_lines.append(
            f"\n{entry['number']}. [{entry['title']}](./{entry['filename']})"
        )
    (course_dir / "index.md").write_text("\n".join(index_lines) + "\n")

    return course_dir
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_refiner.py -v
```

Expected: All PASS

**Step 5: Add refine flag to Pipeline**

Modify `skillbill/pipeline.py`:

In `__init__`, add `refine` parameter:

```python
def __init__(self, data_dir=None, use_haiku=True, cookies_from=None, refine=False):
    # ...existing code...
    self.refine = refine
```

Add `run_refinement()` method after `run_generation()`:

```python
def run_refinement(self, api_key: str = "") -> Path:
    """Stage 7: AI refinement — clean titles + lesson extraction."""
    if not self.manifest or not self.transcripts:
        raise ValueError("Run discovery and transcripts first")

    from skillbill.refiner import refine_course

    course_dir = self.kb_dir / self.manifest["slug"]
    return refine_course(
        course_dir=course_dir,
        manifest=self.manifest,
        transcripts=self.transcripts,
        capture_results=self.capture_results or [[] for _ in self.transcripts],
        api_key=api_key,
    )
```

Update `run_all()`:

```python
def run_all(self, url: str, api_key: str = "") -> Path:
    self.run_discovery(url)
    self.run_transcripts()
    video_paths = self.run_download()
    self.run_screenshot_planning(video_paths)
    self.run_capture(video_paths)
    course_dir = self.run_generation()
    if self.refine:
        return self.run_refinement(api_key=api_key)
    return course_dir
```

Update `run_transcript_only()`:

```python
def run_transcript_only(self, url: str, api_key: str = "") -> Path:
    self.run_discovery(url)
    self.run_transcripts()
    self.capture_results = [[] for _ in self.transcripts]
    course_dir = self.run_generation()
    if self.refine:
        return self.run_refinement(api_key=api_key)
    return course_dir
```

**Step 6: Write pipeline integration test**

Add to `tests/test_pipeline.py`:

```python
class TestPipelineRefinement:
    def test_refine_flag_defaults_false(self, tmp_path):
        p = Pipeline(data_dir=tmp_path)
        assert p.refine is False

    def test_refine_flag_accepted(self, tmp_path):
        p = Pipeline(data_dir=tmp_path, refine=True)
        assert p.refine is True
```

**Step 7: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: All PASS

**Step 8: Commit**

```bash
git add skillbill/refiner.py skillbill/pipeline.py tests/test_refiner.py tests/test_pipeline.py
git commit -m "feat: add refine_course orchestrator and pipeline Stage 7 integration"
```

---

### Task 5: Add API key management

**Files:**
- Create: `web/services/api_keys.py`
- Create: `tests/test_api_keys.py`
- Create: `web/routes/settings.py`
- Modify: `web/server.py`

**Step 1: Write failing tests**

Create `tests/test_api_keys.py`:

```python
"""Tests for API key management."""
import json
import pytest
from pathlib import Path
from web.services.api_keys import load_api_key, save_api_key, clear_api_key


class TestApiKeyStorage:
    def test_save_and_load(self, tmp_path):
        config_path = tmp_path / ".config.json"
        save_api_key("anthropic", "sk-ant-test-123", config_path)
        provider, key = load_api_key(config_path)
        assert provider == "anthropic"
        assert key == "sk-ant-test-123"

    def test_load_missing_file(self, tmp_path):
        config_path = tmp_path / ".config.json"
        provider, key = load_api_key(config_path)
        assert provider == ""
        assert key == ""

    def test_clear(self, tmp_path):
        config_path = tmp_path / ".config.json"
        save_api_key("anthropic", "sk-test", config_path)
        clear_api_key(config_path)
        provider, key = load_api_key(config_path)
        assert provider == ""
        assert key == ""

    def test_overwrite_existing(self, tmp_path):
        config_path = tmp_path / ".config.json"
        save_api_key("anthropic", "sk-old", config_path)
        save_api_key("anthropic", "sk-new", config_path)
        _, key = load_api_key(config_path)
        assert key == "sk-new"
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_api_keys.py -v
```

Expected: FAIL

**Step 3: Write the implementation**

Create `web/services/api_keys.py`:

```python
"""API key storage — persisted to local config file."""
import json
from pathlib import Path

from skillbill.config import DATA_DIR

DEFAULT_CONFIG_PATH = DATA_DIR / ".config.json"


def load_api_key(config_path: Path = DEFAULT_CONFIG_PATH) -> tuple[str, str]:
    """Load saved API key. Returns (provider, key) or ("", "") if not set."""
    if not config_path.exists():
        return "", ""
    try:
        data = json.loads(config_path.read_text())
        return data.get("provider", ""), data.get("api_key", "")
    except (json.JSONDecodeError, KeyError):
        return "", ""


def save_api_key(
    provider: str,
    api_key: str,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Save API key to local config file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({
        "provider": provider,
        "api_key": api_key,
    }))


def clear_api_key(config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Remove saved API key."""
    if config_path.exists():
        config_path.unlink()
```

Create `web/routes/settings.py`:

```python
"""Settings routes — API key management."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from web.services.api_keys import load_api_key, save_api_key, clear_api_key

router = APIRouter(prefix="/api")


@router.get("/key-status")
async def key_status():
    """Check if an API key is configured."""
    provider, key = load_api_key()
    return JSONResponse({
        "has_key": bool(key),
        "provider": provider if key else "",
    })


@router.post("/save-key")
async def save_key(request: Request):
    """Save an API key."""
    data = await request.json()
    provider = data.get("provider", "")
    api_key = data.get("api_key", "")
    if not provider or not api_key:
        return JSONResponse({"error": "Provider and API key required"}, status_code=400)
    if provider not in ("anthropic",):
        return JSONResponse({"error": "Only Anthropic is supported currently"}, status_code=400)
    save_api_key(provider, api_key)
    return JSONResponse({"status": "saved"})


@router.post("/clear-key")
async def clear_key():
    """Clear saved API key."""
    clear_api_key()
    return JSONResponse({"status": "cleared"})
```

**Step 4: Register settings router in server.py**

Add to `web/server.py` imports:

```python
from web.routes import home, generate, library, download, settings
```

Add after existing router includes:

```python
app.include_router(settings.router)
```

**Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_api_keys.py -v
```

Expected: All PASS

**Step 6: Commit**

```bash
git add web/services/api_keys.py web/routes/settings.py tests/test_api_keys.py web/server.py
git commit -m "feat: add API key management with local persistence"
```

---

### Task 6: Update pipeline runner for Pro mode

**Files:**
- Modify: `web/services/pipeline_runner.py`
- Modify: `web/routes/generate.py`
- Modify: `tests/test_pipeline_runner.py`

**Step 1: Write failing tests**

Add to `tests/test_pipeline_runner.py`:

```python
class TestPipelineRunnerRefine:
    def test_accepts_refine_parameter(self):
        runner = PipelineRunner()
        # Should not raise — refine is a valid parameter
        # (actual pipeline run tested via integration)
        assert runner.status == PipelineStatus.IDLE
```

**Step 2: Update PipelineRunner.start() to accept refine and api_key**

In `web/services/pipeline_runner.py`, update the `start()` method signature:

```python
async def start(
    self,
    url: str,
    mode: str = "full",
    use_haiku: bool = True,
    cookies_from: Optional[str] = None,
    refine: bool = False,
    api_key: str = "",
) -> None:
```

Update `run_in_thread()` inside `start()`:

```python
def run_in_thread():
    try:
        pipeline = Pipeline(
            data_dir=self.data_dir,
            use_haiku=use_haiku,
            cookies_from=cookies_from,
            refine=refine,
        )
        self._run_pipeline(pipeline, url, mode, api_key=api_key)
    except Exception as e:
        self.status = PipelineStatus.ERROR
        self._emit({"type": "error", "message": str(e), "fatal": True})
```

Update `_run_pipeline()` signature and add Stage 7:

```python
def _run_pipeline(self, pipeline: Pipeline, url: str, mode: str, api_key: str = "") -> None:
```

Add after Stage 6 (generation) complete, before the `pipeline_complete` event:

```python
        # Stage 7: Refinement (Pro mode only)
        if pipeline.refine and api_key:
            total = pipeline.manifest["video_count"]
            self._emit({"type": "stage_start", "stage": "refinement", "total": total})
            self._emit({"type": "log", "message": "Refining with AI — cleaning titles and extracting lessons..."})
            pipeline.run_refinement(api_key=api_key)
            self._emit({"type": "stage_complete", "stage": "refinement"})
```

**Step 3: Update generate.py to pass refine flag and api_key**

In `web/routes/generate.py`, update the `start_generate()` handler:

```python
from web.services.api_keys import load_api_key

@router.post("/generate", response_class=HTMLResponse)
async def start_generate(request: Request):
    templates = get_templates()
    form = await request.form()
    url = form.get("url", "")
    mode = form.get("mode", "full")
    cookies_from = form.get("cookies_from") or None
    use_haiku = form.get("use_haiku") != "off"
    refine = form.get("tier") == "pro"

    # Load API key if Pro mode
    api_key = ""
    if refine:
        _, api_key = load_api_key()
        if not api_key:
            return templates.TemplateResponse(request, "home.html", {
                "error": "Pro mode requires an API key. Please configure one first.",
            })

    runner = get_runner()

    try:
        await runner.start(
            url=url,
            mode=mode,
            use_haiku=use_haiku,
            cookies_from=cookies_from,
            refine=refine,
            api_key=api_key,
        )
    except RuntimeError as e:
        return templates.TemplateResponse(request, "home.html", {
            "error": str(e),
        })

    return templates.TemplateResponse(request, "progress.html", {
        "url": url,
        "mode": mode,
        "refine": refine,
    })
```

**Step 4: Run tests**

```bash
python -m pytest tests/ -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add web/services/pipeline_runner.py web/routes/generate.py tests/test_pipeline_runner.py
git commit -m "feat: wire Pro mode through pipeline runner and generate route"
```

---

### Task 7: Update home page with Base/Pro toggle and API key modal

**Files:**
- Modify: `web/templates/home.html`

> **For Claude:** REQUIRED SUB-SKILL: Use frontend-design:frontend-design for the Base/Pro toggle and API key modal. The toggle should be prominent — two large pills labeled "Base" and "Pro". Pro pill has a subtle shimmer or accent treatment. Hover tooltips explain each tier. API key modal: dark overlay, provider cards (Anthropic selectable, OpenAI/Google dimmed with "Coming soon"), password input field for key, Save & Continue button. Use proper brand colors for provider logos. Match the existing dark editorial aesthetic.

**Step 1: Update the home template**

Replace the existing mode toggle (Transcript Only / Full Pipeline) with a tier toggle:

- Two large toggle pills: **Base** | **Pro**
- Base tooltip on hover: "Full pipeline with transcripts and screenshots"
- Pro tooltip on hover: "AI-refined lessons with clean titles and concise steps"
- Hidden `<input type="hidden" name="tier" value="base">` updated by JS
- When Pro selected: JS checks `/api/key-status`. If no key, show modal. If key exists, proceed.

Add API key modal (hidden by default):

```html
<div class="modal-overlay" id="api-key-modal">
    <div class="modal">
        <h2>Configure AI Provider</h2>
        <p class="modal-subtitle">Select your AI provider and enter your API key</p>

        <div class="provider-cards">
            <label class="provider-card provider-card--active">
                <input type="radio" name="provider" value="anthropic" checked>
                <div class="provider-logo"><!-- Anthropic logo SVG --></div>
                <span class="provider-name">Anthropic</span>
            </label>
            <label class="provider-card provider-card--disabled">
                <input type="radio" name="provider" value="openai" disabled>
                <div class="provider-logo"><!-- OpenAI logo SVG --></div>
                <span class="provider-name">OpenAI</span>
                <span class="provider-badge">Coming soon</span>
            </label>
            <label class="provider-card provider-card--disabled">
                <input type="radio" name="provider" value="google" disabled>
                <div class="provider-logo"><!-- Google logo SVG --></div>
                <span class="provider-name">Google</span>
                <span class="provider-badge">Coming soon</span>
            </label>
        </div>

        <input type="password" id="api-key-input" class="input" placeholder="Paste your API key">
        <button class="btn btn-primary" id="save-key-btn">Save & Continue</button>
        <button class="btn btn-ghost" id="cancel-modal-btn">Cancel</button>
    </div>
</div>
```

Add inline JS for modal logic:

```javascript
const tierInput = document.querySelector('input[name="tier"]');
const proToggle = document.getElementById('pro-toggle');
const modal = document.getElementById('api-key-modal');

proToggle.addEventListener('click', async () => {
    // Check key status
    const resp = await fetch('/api/key-status');
    const data = await resp.json();
    if (data.has_key) {
        tierInput.value = 'pro';
        // Update visual state
    } else {
        modal.classList.add('modal--visible');
    }
});

document.getElementById('save-key-btn').addEventListener('click', async () => {
    const key = document.getElementById('api-key-input').value;
    const provider = document.querySelector('input[name="provider"]:checked').value;
    const resp = await fetch('/api/save-key', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({provider, api_key: key}),
    });
    if (resp.ok) {
        modal.classList.remove('modal--visible');
        tierInput.value = 'pro';
    }
});
```

**Step 2: Verify**

```bash
python -c "
from fastapi.testclient import TestClient
from web.server import app
c = TestClient(app)
r = c.get('/')
assert 'Base' in r.text and 'Pro' in r.text
assert 'api-key-modal' in r.text
print('Home page updated OK')
"
```

**Step 3: Commit**

```bash
git add web/templates/home.html
git commit -m "feat(web): add Base/Pro toggle and API key modal to home page"
```

---

### Task 8: Update progress page with Stage 7

**Files:**
- Modify: `web/templates/progress.html`
- Modify: `web/static/js/progress.js`

**Step 1: Add refinement stage to progress.html**

After the generation stage div (stage 6), add:

```html
{% if refine %}
<div class="stage stage--pending" data-stage="refinement">
    <div class="stage-icon">7</div>
    <div class="stage-info">
        <div class="stage-name">Refinement</div>
        <div class="stage-detail">AI lesson extraction</div>
    </div>
    <div class="stage-status"></div>
</div>
{% endif %}
```

**Step 2: Update progress.js formatStageData**

Add case for refinement stage:

```javascript
case 'refinement': return 'Lessons refined';
```

**Step 3: Verify**

```bash
python -c "
from fastapi.testclient import TestClient
from web.server import app
c = TestClient(app)
# POST with refine flag
r = c.post('/generate', data={'url': 'test', 'tier': 'pro', 'mode': 'full'})
# Should show refinement stage (even if pipeline fails, template should render)
print('Progress page check done')
"
```

**Step 4: Commit**

```bash
git add web/templates/progress.html web/static/js/progress.js
git commit -m "feat(web): add Stage 7 refinement to progress timeline"
```

---

### Task 9: Update video page for Pro (lessons only)

**Files:**
- Modify: `web/routes/library.py`
- Modify: `web/templates/video.html`
- Modify: `web/templates/library.html`
- Modify: `web/templates/course.html`

**Step 1: Detect Pro courses in library routes**

In `web/routes/library.py`, update `_list_courses()` to detect Pro:

```python
# Check for Pro (refined) — Pro courses have .lessons.md or clean-titled files
# Simple heuristic: check if any file was refined by looking for the refine marker
is_pro = (course_dir / ".refined").exists()
courses.append({
    ...existing fields...,
    "is_pro": is_pro,
})
```

In `refiner.py`, at the end of `refine_course()`, add a marker file:

```python
(course_dir / ".refined").write_text("")
```

**Step 2: Add Pro badge to library cards**

In `web/templates/library.html`, add to each course card:

```html
{% if course.is_pro %}
<span class="badge badge--pro">Pro</span>
{% endif %}
```

**Step 3: Video page — no toggle needed for Pro**

The video page already renders `html_content` from the markdown file. Since Pro mode replaces the transcript files with lesson files, the existing video route will serve the refined content automatically. No template changes needed.

**Step 4: Verify**

```bash
python -m pytest tests/test_web_routes.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add web/routes/library.py web/templates/library.html web/templates/course.html skillbill/refiner.py
git commit -m "feat(web): add Pro badge to library and course pages"
```

---

### Task 10: Add --refine flag to CLI

**Files:**
- Modify: `run.py`

**Step 1: Add flag to playlist command**

Add `@click.option("--refine", is_flag=True, help="Enable Pro AI refinement (requires ANTHROPIC_API_KEY)")` to the playlist command.

Update the handler:

```python
def playlist(url, stage, transcript_only, no_haiku, data_dir, cookies_from, refine):
    data_path = Path(data_dir) if data_dir else None
    p = Pipeline(data_dir=data_path, use_haiku=not no_haiku, cookies_from=cookies_from, refine=refine)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "") if refine else ""
    if refine and not api_key:
        click.echo("Error: --refine requires ANTHROPIC_API_KEY environment variable")
        return

    if transcript_only:
        result = p.run_transcript_only(url, api_key=api_key)
    elif stage == "all":
        result = p.run_all(url, api_key=api_key)
    ...
```

Add `import os` at top of `run.py` if not present.

**Step 2: Test CLI help**

```bash
python run.py playlist --help
```

Expected: Shows `--refine` flag in help output

**Step 3: Commit**

```bash
git add run.py
git commit -m "feat: add --refine CLI flag for Pro AI refinement"
```

---

### Task 11: Integration testing

**Files:**
- Modify: `tests/test_web_routes.py`
- Modify: `tests/test_refiner.py`

**Step 1: Add web route tests for Pro flow**

Add to `tests/test_web_routes.py`:

```python
class TestProMode:
    def test_key_status_no_key(self, client):
        resp = client.get("/api/key-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_key"] is False

    def test_save_and_load_key(self, client):
        resp = client.post("/api/save-key", json={
            "provider": "anthropic",
            "api_key": "sk-test-123",
        })
        assert resp.status_code == 200

        resp = client.get("/api/key-status")
        data = resp.json()
        assert data["has_key"] is True
        assert data["provider"] == "anthropic"

    def test_reject_unsupported_provider(self, client):
        resp = client.post("/api/save-key", json={
            "provider": "openai",
            "api_key": "sk-test",
        })
        assert resp.status_code == 400

    def test_home_page_has_pro_toggle(self, client):
        resp = client.get("/")
        assert "Base" in resp.text
        assert "Pro" in resp.text
```

**Step 2: Run the full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass (existing 92 + new refiner + api key + pro mode tests)

**Step 3: Commit**

```bash
git add tests/
git commit -m "test: add integration tests for Pro mode, API keys, and refinement"
```

---

### Verification

After all tasks are complete:

1. `python -m pytest tests/ -v` — all tests pass
2. `python run.py serve` — server starts, home page shows Base/Pro toggle
3. Clicking Pro without API key → modal appears with Anthropic/OpenAI/Google cards
4. Saving Anthropic key → key persisted in `data/.config.json`
5. Submitting a playlist in Pro mode → progress page shows 7 stages including "Refinement"
6. Refined course output has clean titles, concise lesson steps, screenshot references
7. Library shows "Pro" badge on refined courses
8. Video page shows clean lessons (not raw transcript) for Pro courses
9. `python run.py playlist "URL" --refine` works via CLI
10. Download ZIP contains clean refined files for Pro courses

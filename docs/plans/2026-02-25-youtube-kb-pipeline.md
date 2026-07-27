# YouTube Knowledge Base Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a staged Python pipeline that converts YouTube course playlists into structured markdown knowledge bases with intelligently captured screenshots.

**Architecture:** Six-stage pipeline (discovery → transcripts → download → screenshot planning → frame capture → markdown generation) with intermediate artifacts on disk. Each stage independently runnable. One Claude Haiku call per video for transcript segment classification; all other processing is local.

**Tech Stack:** Python 3.14, yt-dlp, youtube-transcript-api, PySceneDetect, ffmpeg-python, imagehash, Pillow, anthropic SDK, click, jinja2, pytest

---

## Task 0: Project Scaffolding

**Files:**
- Create: `Skill Bill/skillbill/__init__.py`
- Create: `Skill Bill/skillbill/config.py`
- Create: `Skill Bill/requirements.txt`
- Create: `Skill Bill/.gitignore`
- Create: `Skill Bill/run.py`
- Create: `Skill Bill/tests/__init__.py`
- Create: `Skill Bill/tests/conftest.py`
- Create: `Skill Bill/templates/video.md.j2`
- Create: `Skill Bill/templates/index.md.j2`

**Step 1: Create requirements.txt**

```
yt-dlp>=2024.0.0
youtube-transcript-api>=1.0.0
ffmpeg-python>=0.2.0
scenedetect[opencv]>=0.6.0
imagehash>=4.3.0
Pillow>=10.0.0
anthropic>=0.40.0
click>=8.0.0
jinja2>=3.1.0
pytest>=8.0.0
```

**Step 2: Create .gitignore**

```
data/
*.mp4
*.webm
*.mkv
__pycache__/
*.pyc
.env
*.egg-info/
dist/
build/
```

**Step 3: Create config.py**

```python
from pathlib import Path
import os

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
ASSETS_DIR = DATA_DIR / "assets"
KB_DIR = DATA_DIR / "knowledge_base"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Screenshot config
SCREENSHOT_CONFIG = {
    "min_interval_seconds": 10,
    "max_interval_seconds": 120,
    "dedup_threshold": 12,  # imagehash hamming distance (lower = stricter)
    "sparse_transcript_threshold": 10,  # words per minute
    "verbal_cue_keywords": [
        "look at", "as you can see", "on screen", "this diagram",
        "this code", "let me show", "here we have", "notice",
        "this shows", "take a look", "on the left", "on the right",
        "you can see", "shown here", "right here", "over here",
        "this is", "watch", "observe", "check out",
    ],
}

# Claude API
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

def ensure_dirs():
    """Create all data directories if they don't exist."""
    for d in [RAW_DIR, PROCESSED_DIR, ASSETS_DIR, KB_DIR]:
        d.mkdir(parents=True, exist_ok=True)
```

**Step 4: Create __init__.py**

```python
"""Skill Bill - YouTube to Knowledge Base Pipeline."""
```

**Step 5: Create empty run.py stub**

```python
"""CLI entry point for Skill Bill pipeline."""
import click

@click.group()
def cli():
    """Skill Bill - YouTube to Knowledge Base Pipeline."""
    pass

if __name__ == "__main__":
    cli()
```

**Step 6: Create tests/conftest.py**

```python
import pytest
from pathlib import Path
import json
import tempfile

@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory structure."""
    for subdir in ["raw", "processed", "assets", "knowledge_base"]:
        (tmp_path / subdir).mkdir()
    return tmp_path

@pytest.fixture
def sample_manifest():
    """Sample playlist manifest for testing."""
    return {
        "playlist_title": "Test Course",
        "playlist_url": "https://youtube.com/playlist?list=PLtest",
        "videos": [
            {
                "id": "abc123",
                "title": "01 - Introduction",
                "description": "Welcome to the course. Check out https://github.com/example/repo",
                "duration": 600,
                "chapters": [
                    {"title": "Intro", "start_time": 0, "end_time": 120},
                    {"title": "Setup", "start_time": 120, "end_time": 360},
                    {"title": "First Steps", "start_time": 360, "end_time": 600},
                ],
                "url": "https://youtube.com/watch?v=abc123",
            },
            {
                "id": "def456",
                "title": "02 - Deep Dive",
                "description": "Let's go deeper.",
                "duration": 900,
                "chapters": [],
                "url": "https://youtube.com/watch?v=def456",
            },
        ],
    }

@pytest.fixture
def sample_transcript():
    """Sample timestamped transcript for testing."""
    return [
        {"start": 0.0, "duration": 3.5, "text": "Welcome to this tutorial on React."},
        {"start": 3.5, "duration": 4.0, "text": "Today we're going to look at server components."},
        {"start": 7.5, "duration": 3.0, "text": "Let me show you the code."},
        {"start": 10.5, "duration": 5.0, "text": "As you can see on screen, we have a component here."},
        {"start": 30.0, "duration": 3.0, "text": "Now let's move on to the next topic."},
        {"start": 60.0, "duration": 4.0, "text": "This diagram shows the architecture."},
        {"start": 64.0, "duration": 10.0, "text": "The server sends the serialized tree to the client."},
        {"start": 120.0, "duration": 3.0, "text": "Let me run the demo now."},
    ]

@pytest.fixture
def sample_screenshot_plan():
    """Sample screenshot plan for testing."""
    return {
        "video_id": "abc123",
        "segments": [
            {"type": "talking-head", "start": 0.0, "end": 7.5},
            {"type": "code-demo", "start": 7.5, "end": 30.0},
            {"type": "slides", "start": 60.0, "end": 120.0},
            {"type": "code-demo", "start": 120.0, "end": 600.0},
        ],
        "screenshots": [
            {"timestamp": 0.0, "reason": "section_start"},
            {"timestamp": 10.5, "reason": "verbal_cue: as you can see"},
            {"timestamp": 15.0, "reason": "scene_change"},
            {"timestamp": 25.0, "reason": "interval_fallback"},
            {"timestamp": 60.0, "reason": "verbal_cue: this diagram"},
            {"timestamp": 120.0, "reason": "chapter_boundary"},
        ],
    }
```

**Step 7: Create Jinja2 templates**

`templates/video.md.j2`:
```
# {{ video_title }}

**Course:** {{ course_title }}
**Video:** {{ video_number }} of {{ total_videos }}
**Duration:** {{ duration_formatted }}
**Source:** {{ video_url }}
{% if chapters %}**Chapters:** {{ chapters | join(' | ') }}{% endif %}

---

{% for section in sections %}
## [{{ section.timestamp }}] {{ section.heading }}

{{ section.transcript }}
{% for screenshot in section.screenshots %}

![{{ screenshot.caption }}]({{ screenshot.path }})
{% endfor %}

{% endfor %}
---

{% if linked_urls %}
**Linked Resources:**
{% for url in linked_urls %}- {{ url }}
{% endfor %}{% endif %}
```

`templates/index.md.j2`:
```
# {{ course_title }} -- Course Index

**Source Playlist:** {{ playlist_url }}
**Videos:** {{ total_videos }}
**Generated:** {{ generated_date }}

## Lessons

{% for video in videos %}
{{ video.number }}. [{{ video.title }}](./{{ video.filename }})
{% endfor %}
```

**Step 8: Install dependencies**

Run: `cd "skill-bill-vol-1" && pip install -r requirements.txt`

**Step 9: Run initial test to verify setup**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/ -v`
Expected: collected 0 items, no errors

**Step 10: Commit**

```bash
git add "Skill Bill/"
git commit -m "feat: scaffold Skill Bill project structure"
```

---

## Task 1: Discovery Module (yt-dlp playlist metadata)

**Files:**
- Create: `Skill Bill/skillbill/downloader.py`
- Create: `Skill Bill/tests/test_downloader.py`

**Step 1: Write the failing tests**

```python
# tests/test_downloader.py
import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from skillbill.downloader import discover_playlist, download_video, slugify_title


class TestSlugifyTitle:
    def test_basic(self):
        assert slugify_title("React Server Components") == "react-server-components"

    def test_special_chars(self):
        assert slugify_title("Lesson #1: What's New?") == "lesson-1-whats-new"

    def test_numbers_preserved(self):
        assert slugify_title("01 - Introduction") == "01-introduction"


class TestDiscoverPlaylist:
    @patch("skillbill.downloader.yt_dlp.YoutubeDL")
    def test_returns_manifest(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Test Playlist",
            "webpage_url": "https://youtube.com/playlist?list=PLtest",
            "entries": [
                {
                    "id": "abc123",
                    "title": "01 - Intro",
                    "description": "First video",
                    "duration": 600,
                    "chapters": [
                        {"title": "Start", "start_time": 0, "end_time": 300},
                    ],
                    "url": "https://youtube.com/watch?v=abc123",
                },
            ],
        }

        result = discover_playlist("https://youtube.com/playlist?list=PLtest")

        assert result["playlist_title"] == "Test Playlist"
        assert len(result["videos"]) == 1
        assert result["videos"][0]["id"] == "abc123"
        assert result["videos"][0]["chapters"][0]["title"] == "Start"

    @patch("skillbill.downloader.yt_dlp.YoutubeDL")
    def test_handles_missing_chapters(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Test Playlist",
            "webpage_url": "https://youtube.com/playlist?list=PLtest",
            "entries": [
                {
                    "id": "abc123",
                    "title": "01 - Intro",
                    "description": "",
                    "duration": 600,
                    "url": "https://youtube.com/watch?v=abc123",
                },
            ],
        }

        result = discover_playlist("https://youtube.com/playlist?list=PLtest")
        assert result["videos"][0]["chapters"] == []


class TestSaveManifest:
    @patch("skillbill.downloader.yt_dlp.YoutubeDL")
    def test_saves_to_disk(self, mock_ydl_class, tmp_data_dir):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Test Playlist",
            "webpage_url": "https://youtube.com/playlist?list=PLtest",
            "entries": [
                {
                    "id": "abc123",
                    "title": "01 - Intro",
                    "description": "",
                    "duration": 600,
                    "url": "https://youtube.com/watch?v=abc123",
                },
            ],
        }

        result = discover_playlist(
            "https://youtube.com/playlist?list=PLtest",
            output_dir=tmp_data_dir / "raw",
        )

        manifest_path = tmp_data_dir / "raw" / "test-playlist" / "manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["playlist_title"] == "Test Playlist"
```

**Step 2: Run tests to verify they fail**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_downloader.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Implement downloader.py**

```python
"""Stage 1 & 3: YouTube playlist discovery and video download via yt-dlp."""
import re
import json
from pathlib import Path
from typing import Optional

import yt_dlp

from skillbill.config import RAW_DIR, ensure_dirs


def slugify_title(title: str) -> str:
    """Convert a title to a filesystem-safe slug."""
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def discover_playlist(url: str, output_dir: Optional[Path] = None) -> dict:
    """Extract playlist metadata without downloading videos.

    Returns a manifest dict with playlist info and per-video metadata.
    Optionally saves manifest.json to output_dir/<course-slug>/.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    playlist_title = info.get("title", "Untitled Playlist")
    entries = info.get("entries", [])

    videos = []
    for entry in entries:
        if entry is None:
            continue
        videos.append({
            "id": entry.get("id", ""),
            "title": entry.get("title", "Untitled"),
            "description": entry.get("description", ""),
            "duration": entry.get("duration", 0),
            "chapters": entry.get("chapters") or [],
            "url": entry.get("url") or entry.get("webpage_url", ""),
        })

    manifest = {
        "playlist_title": playlist_title,
        "playlist_url": info.get("webpage_url", url),
        "slug": slugify_title(playlist_title),
        "video_count": len(videos),
        "videos": videos,
    }

    if output_dir is not None:
        course_dir = output_dir / manifest["slug"]
        course_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = course_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    return manifest


def download_video(video_url: str, output_dir: Path, filename_prefix: str = "") -> Path:
    """Download a single video file.

    Returns the path to the downloaded video file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    outtmpl = str(output_dir / f"{filename_prefix}%(title)s.%(ext)s")

    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        filename = ydl.prepare_filename(info)
        return Path(filename)
```

**Step 4: Run tests to verify they pass**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_downloader.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add "Skill Bill/skillbill/downloader.py" "Skill Bill/tests/test_downloader.py"
git commit -m "feat: add discovery module with yt-dlp playlist metadata extraction"
```

---

## Task 2: Transcript Module (youtube-transcript-api)

**Files:**
- Create: `Skill Bill/skillbill/transcript.py`
- Create: `Skill Bill/tests/test_transcript.py`

**Step 1: Write the failing tests**

```python
# tests/test_transcript.py
import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from skillbill.transcript import (
    fetch_transcript,
    fetch_all_transcripts,
    compute_speech_density,
    detect_sparse_sections,
)


class TestFetchTranscript:
    @patch("skillbill.transcript.YouTubeTranscriptApi.get_transcript")
    def test_returns_timestamped_entries(self, mock_get):
        mock_get.return_value = [
            {"start": 0.0, "duration": 3.0, "text": "Hello world"},
            {"start": 3.0, "duration": 4.0, "text": "Welcome to the course"},
        ]
        result = fetch_transcript("abc123")
        assert len(result["entries"]) == 2
        assert result["entries"][0]["text"] == "Hello world"
        assert result["video_id"] == "abc123"
        assert result["has_transcript"] is True

    @patch("skillbill.transcript.YouTubeTranscriptApi.get_transcript")
    def test_handles_no_transcript(self, mock_get):
        mock_get.side_effect = Exception("No transcript found")
        result = fetch_transcript("xyz789")
        assert result["has_transcript"] is False
        assert result["entries"] == []


class TestComputeSpeechDensity:
    def test_dense_speech(self, sample_transcript):
        density = compute_speech_density(sample_transcript, window_seconds=30)
        # First 30s has several entries → should be > 0
        assert density[0]["words_per_minute"] > 0

    def test_sparse_section(self):
        sparse = [
            {"start": 0.0, "duration": 2.0, "text": "Hi"},
            {"start": 58.0, "duration": 2.0, "text": "Okay"},
        ]
        density = compute_speech_density(sparse, window_seconds=30)
        # 30-60 window has only "Okay" → very sparse
        mid_window = [w for w in density if w["start"] == 30]
        if mid_window:
            assert mid_window[0]["words_per_minute"] < 10


class TestDetectSparseSections:
    def test_finds_gaps(self):
        transcript = [
            {"start": 0.0, "duration": 3.0, "text": "Hello world this is a test"},
            {"start": 60.0, "duration": 3.0, "text": "Back again"},
        ]
        gaps = detect_sparse_sections(transcript, gap_threshold_seconds=5)
        assert len(gaps) >= 1
        assert gaps[0]["start"] == pytest.approx(3.0, abs=1.0)


class TestSaveTranscript:
    @patch("skillbill.transcript.YouTubeTranscriptApi.get_transcript")
    def test_saves_to_disk(self, mock_get, tmp_data_dir):
        mock_get.return_value = [
            {"start": 0.0, "duration": 3.0, "text": "Hello"},
        ]
        result = fetch_transcript(
            "abc123",
            output_dir=tmp_data_dir / "processed",
            course_slug="test-course",
        )
        path = tmp_data_dir / "processed" / "test-course" / "abc123-transcript.json"
        assert path.exists()
```

**Step 2: Run tests to verify they fail**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_transcript.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Implement transcript.py**

```python
"""Stage 2: Transcript extraction via youtube-transcript-api."""
import json
from pathlib import Path
from typing import Optional

from youtube_transcript_api import YouTubeTranscriptApi


def fetch_transcript(
    video_id: str,
    languages: list[str] | None = None,
    output_dir: Optional[Path] = None,
    course_slug: Optional[str] = None,
) -> dict:
    """Fetch timestamped transcript for a single video.

    Returns dict with video_id, has_transcript, entries, and word_count.
    """
    if languages is None:
        languages = ["en"]

    try:
        entries = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        word_count = sum(len(e["text"].split()) for e in entries)
        result = {
            "video_id": video_id,
            "has_transcript": True,
            "entries": entries,
            "word_count": word_count,
            "duration": entries[-1]["start"] + entries[-1]["duration"] if entries else 0,
        }
    except Exception:
        result = {
            "video_id": video_id,
            "has_transcript": False,
            "entries": [],
            "word_count": 0,
            "duration": 0,
        }

    if output_dir is not None and course_slug is not None:
        save_dir = output_dir / course_slug
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / f"{video_id}-transcript.json"
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    return result


def fetch_all_transcripts(
    video_ids: list[str],
    output_dir: Optional[Path] = None,
    course_slug: Optional[str] = None,
) -> list[dict]:
    """Fetch transcripts for all videos in a playlist."""
    results = []
    for vid in video_ids:
        result = fetch_transcript(vid, output_dir=output_dir, course_slug=course_slug)
        results.append(result)
    return results


def compute_speech_density(
    entries: list[dict], window_seconds: int = 30
) -> list[dict]:
    """Compute words-per-minute in sliding windows over the transcript.

    Returns list of dicts with start, end, words_per_minute.
    """
    if not entries:
        return []

    max_time = entries[-1]["start"] + entries[-1]["duration"]
    windows = []

    t = 0.0
    while t < max_time:
        window_end = t + window_seconds
        words_in_window = sum(
            len(e["text"].split())
            for e in entries
            if e["start"] >= t and e["start"] < window_end
        )
        wpm = (words_in_window / window_seconds) * 60
        windows.append({
            "start": t,
            "end": window_end,
            "words_per_minute": round(wpm, 1),
        })
        t += window_seconds

    return windows


def detect_sparse_sections(
    entries: list[dict], gap_threshold_seconds: float = 5.0
) -> list[dict]:
    """Find gaps in the transcript where the speaker is silent.

    Returns list of dicts with start, end, duration of each gap.
    """
    gaps = []
    for i in range(len(entries) - 1):
        current_end = entries[i]["start"] + entries[i]["duration"]
        next_start = entries[i + 1]["start"]
        gap = next_start - current_end
        if gap >= gap_threshold_seconds:
            gaps.append({
                "start": current_end,
                "end": next_start,
                "duration": round(gap, 2),
            })
    return gaps
```

**Step 4: Run tests to verify they pass**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_transcript.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add "Skill Bill/skillbill/transcript.py" "Skill Bill/tests/test_transcript.py"
git commit -m "feat: add transcript module with speech density and gap detection"
```

---

## Task 3: Screenshot Analyzer (Local Heuristics + Haiku)

**Files:**
- Create: `Skill Bill/skillbill/analyzer.py`
- Create: `Skill Bill/tests/test_analyzer.py`

**Step 1: Write the failing tests**

```python
# tests/test_analyzer.py
import pytest
from skillbill.analyzer import (
    scan_verbal_cues,
    plan_screenshots_for_segment,
    merge_and_deduplicate_timestamps,
    classify_segments_local,
    build_screenshot_plan,
)
from skillbill.config import SCREENSHOT_CONFIG


class TestScanVerbalCues:
    def test_finds_visual_references(self, sample_transcript):
        cues = scan_verbal_cues(sample_transcript, SCREENSHOT_CONFIG["verbal_cue_keywords"])
        timestamps = [c["timestamp"] for c in cues]
        # "Let me show you" at 7.5s, "As you can see on screen" at 10.5s,
        # "This diagram shows" at 60.0s
        assert 7.5 in timestamps
        assert 10.5 in timestamps
        assert 60.0 in timestamps

    def test_no_false_positives(self):
        entries = [
            {"start": 0.0, "duration": 3.0, "text": "Hello everyone welcome back"},
        ]
        cues = scan_verbal_cues(entries, SCREENSHOT_CONFIG["verbal_cue_keywords"])
        assert len(cues) == 0


class TestClassifySegmentsLocal:
    def test_sparse_detected(self):
        density = [
            {"start": 0, "end": 30, "words_per_minute": 150},
            {"start": 30, "end": 60, "words_per_minute": 5},
            {"start": 60, "end": 90, "words_per_minute": 120},
        ]
        cues = []
        scene_changes = [35.0, 40.0, 45.0, 50.0]  # many changes in sparse section
        segments = classify_segments_local(density, cues, scene_changes)
        sparse_segment = [s for s in segments if s["start"] == 30][0]
        assert sparse_segment["type"] in ("code-demo", "unknown")

    def test_dense_speech_no_cues(self):
        density = [
            {"start": 0, "end": 30, "words_per_minute": 160},
        ]
        cues = []
        scene_changes = []
        segments = classify_segments_local(density, cues, scene_changes)
        assert segments[0]["type"] == "talking-head"


class TestPlanScreenshotsForSegment:
    def test_code_demo_captures_frequently(self):
        segment = {"type": "code-demo", "start": 0, "end": 60}
        scene_changes = [5.0, 15.0, 30.0, 45.0]
        timestamps = plan_screenshots_for_segment(segment, scene_changes)
        assert len(timestamps) >= 4

    def test_talking_head_captures_sparingly(self):
        segment = {"type": "talking-head", "start": 0, "end": 120}
        scene_changes = []
        timestamps = plan_screenshots_for_segment(segment, scene_changes)
        assert len(timestamps) <= 3

    def test_slides_captures_per_transition(self):
        segment = {"type": "slides", "start": 0, "end": 120}
        scene_changes = [20.0, 50.0, 80.0]
        timestamps = plan_screenshots_for_segment(segment, scene_changes)
        assert 20.0 in [t["timestamp"] for t in timestamps]
        assert 50.0 in [t["timestamp"] for t in timestamps]


class TestMergeAndDeduplicate:
    def test_removes_close_timestamps(self):
        timestamps = [
            {"timestamp": 10.0, "reason": "scene_change"},
            {"timestamp": 11.0, "reason": "verbal_cue"},
            {"timestamp": 30.0, "reason": "interval"},
        ]
        result = merge_and_deduplicate_timestamps(timestamps, min_interval=5)
        assert len(result) == 2

    def test_preserves_spread_timestamps(self):
        timestamps = [
            {"timestamp": 10.0, "reason": "a"},
            {"timestamp": 30.0, "reason": "b"},
            {"timestamp": 60.0, "reason": "c"},
        ]
        result = merge_and_deduplicate_timestamps(timestamps, min_interval=5)
        assert len(result) == 3
```

**Step 2: Run tests to verify they fail**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_analyzer.py -v`
Expected: FAIL

**Step 3: Implement analyzer.py**

```python
"""Stage 4: Screenshot planning with local heuristics and optional Haiku classification."""
import json
from pathlib import Path
from typing import Optional

from skillbill.config import SCREENSHOT_CONFIG, ANTHROPIC_MODEL, ANTHROPIC_API_KEY


def scan_verbal_cues(entries: list[dict], keywords: list[str]) -> list[dict]:
    """Scan transcript entries for verbal cues indicating visual content.

    Returns list of dicts with timestamp and matched keyword.
    """
    cues = []
    for entry in entries:
        text_lower = entry["text"].lower()
        for keyword in keywords:
            if keyword in text_lower:
                cues.append({
                    "timestamp": entry["start"],
                    "keyword": keyword,
                    "text": entry["text"],
                })
                break  # one match per entry is enough
    return cues


def classify_segments_local(
    density: list[dict],
    verbal_cues: list[dict],
    scene_changes: list[float],
) -> list[dict]:
    """Classify transcript segments using local heuristics only.

    Uses speech density, verbal cue presence, and scene change frequency
    to guess segment type: talking-head, code-demo, slides, whiteboard, unknown.
    """
    segments = []
    cue_timestamps = {c["timestamp"] for c in verbal_cues}

    for window in density:
        start, end = window["start"], window["end"]
        wpm = window["words_per_minute"]

        # Count scene changes in this window
        changes_in_window = [t for t in scene_changes if start <= t < end]
        change_rate = len(changes_in_window) / ((end - start) / 60)

        # Count verbal cues in this window
        cues_in_window = [t for t in cue_timestamps if start <= t < end]

        # Classification logic
        if wpm < SCREENSHOT_CONFIG["sparse_transcript_threshold"]:
            # Sparse speech — screen is the content
            if change_rate > 4:
                seg_type = "code-demo"
            else:
                seg_type = "unknown"  # could be whiteboard, could be demo
        elif wpm > 100 and change_rate < 1 and not cues_in_window:
            seg_type = "talking-head"
        elif change_rate >= 2 and change_rate <= 6:
            seg_type = "slides"
        elif change_rate > 6:
            seg_type = "code-demo"
        elif cues_in_window:
            seg_type = "slides"  # speaker referencing visuals with moderate changes
        else:
            seg_type = "unknown"

        segments.append({
            "type": seg_type,
            "start": start,
            "end": end,
            "wpm": wpm,
            "scene_change_rate": round(change_rate, 1),
        })

    return segments


def classify_segments_haiku(transcript_text: str) -> list[dict]:
    """Use Claude Haiku to classify transcript segments.

    Sends the full transcript as text, returns segment classifications.
    Cost: ~$0.02 per video.
    """
    import anthropic

    if not ANTHROPIC_API_KEY:
        return []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Analyze this video tutorial transcript. For each section, classify what is likely shown on screen.

Return a JSON array of segments with this structure:
[{{"type": "code-demo|slides|talking-head|whiteboard|ui-walkthrough", "start_seconds": N, "end_seconds": N, "description": "brief note"}}]

Types:
- code-demo: presenter is showing/writing/running code
- slides: presentation slides are being shown
- talking-head: just the presenter speaking to camera, no visual aids
- whiteboard: drawing diagrams or writing on a whiteboard
- ui-walkthrough: demonstrating a user interface or application

Transcript:
{transcript_text}

Return ONLY the JSON array, no other text."""

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        return json.loads(response.content[0].text)
    except (json.JSONDecodeError, IndexError):
        return []


def plan_screenshots_for_segment(
    segment: dict,
    scene_changes: list[float],
) -> list[dict]:
    """Generate screenshot timestamps for a single segment based on its type."""
    start = segment["start"]
    end = segment["end"]
    duration = end - start
    seg_type = segment["type"]
    timestamps = []

    changes_in_segment = [t for t in scene_changes if start <= t < end]

    if seg_type == "code-demo":
        # Capture at every scene change + fallback every 25s
        for t in changes_in_segment:
            timestamps.append({"timestamp": t, "reason": "scene_change"})
        fallback = start
        while fallback < end:
            timestamps.append({"timestamp": fallback, "reason": "interval_fallback"})
            fallback += 25

    elif seg_type == "slides":
        # Capture at each slide transition (scene change)
        for t in changes_in_segment:
            timestamps.append({"timestamp": t, "reason": "slide_transition"})
        # If no scene changes detected, fallback to intervals
        if not changes_in_segment and duration > 10:
            timestamps.append({"timestamp": start, "reason": "section_start"})

    elif seg_type == "talking-head":
        # Capture once at start, then only at topic transitions
        timestamps.append({"timestamp": start, "reason": "section_start"})
        if duration > 90:
            timestamps.append({"timestamp": start + duration / 2, "reason": "mid_section"})

    elif seg_type == "whiteboard":
        # Capture every 15-20s (evolving visual)
        t = start
        while t < end:
            timestamps.append({"timestamp": t, "reason": "whiteboard_interval"})
            t += 18

    else:  # unknown
        # Safety net: every 45s
        t = start
        while t < end:
            timestamps.append({"timestamp": t, "reason": "interval_fallback"})
            t += 45

    return timestamps


def merge_and_deduplicate_timestamps(
    timestamps: list[dict],
    min_interval: float = None,
) -> list[dict]:
    """Merge and deduplicate screenshot timestamps.

    Removes timestamps that are too close together (within min_interval seconds).
    Keeps the first occurrence.
    """
    if min_interval is None:
        min_interval = SCREENSHOT_CONFIG["min_interval_seconds"]

    if not timestamps:
        return []

    sorted_ts = sorted(timestamps, key=lambda t: t["timestamp"])
    result = [sorted_ts[0]]

    for ts in sorted_ts[1:]:
        if ts["timestamp"] - result[-1]["timestamp"] >= min_interval:
            result.append(ts)

    return result


def build_screenshot_plan(
    video_id: str,
    transcript_entries: list[dict],
    scene_changes: list[float],
    density: list[dict],
    chapters: list[dict] | None = None,
    use_haiku: bool = True,
    output_dir: Optional[Path] = None,
    course_slug: Optional[str] = None,
) -> dict:
    """Build the full screenshot plan for a video.

    Combines all heuristics and optional Haiku classification.
    """
    # 1. Scan verbal cues
    verbal_cues = scan_verbal_cues(
        transcript_entries, SCREENSHOT_CONFIG["verbal_cue_keywords"]
    )

    # 2. Classify segments
    if use_haiku and ANTHROPIC_API_KEY:
        transcript_text = "\n".join(
            f"[{e['start']:.1f}s] {e['text']}" for e in transcript_entries
        )
        segments = classify_segments_haiku(transcript_text)
        if not segments:
            segments = classify_segments_local(density, verbal_cues, scene_changes)
    else:
        segments = classify_segments_local(density, verbal_cues, scene_changes)

    # 3. Plan screenshots per segment
    all_timestamps = []
    for segment in segments:
        seg_timestamps = plan_screenshots_for_segment(segment, scene_changes)
        all_timestamps.extend(seg_timestamps)

    # 4. Add verbal cue timestamps
    for cue in verbal_cues:
        all_timestamps.append({
            "timestamp": cue["timestamp"],
            "reason": f"verbal_cue: {cue['keyword']}",
        })

    # 5. Add chapter boundary timestamps
    if chapters:
        for ch in chapters:
            all_timestamps.append({
                "timestamp": ch.get("start_time", 0),
                "reason": "chapter_boundary",
            })

    # 6. Merge and deduplicate
    final_timestamps = merge_and_deduplicate_timestamps(all_timestamps)

    plan = {
        "video_id": video_id,
        "segments": segments,
        "screenshots": final_timestamps,
        "total_screenshots": len(final_timestamps),
    }

    if output_dir is not None and course_slug is not None:
        save_dir = output_dir / course_slug
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / f"{video_id}-screenshot-plan.json"
        path.write_text(json.dumps(plan, indent=2))

    return plan
```

**Step 4: Run tests to verify they pass**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_analyzer.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add "Skill Bill/skillbill/analyzer.py" "Skill Bill/tests/test_analyzer.py"
git commit -m "feat: add screenshot analyzer with local heuristics and Haiku classification"
```

---

## Task 4: Frame Capturer (ffmpeg + deduplication)

**Files:**
- Create: `Skill Bill/skillbill/capturer.py`
- Create: `Skill Bill/tests/test_capturer.py`

**Step 1: Write the failing tests**

```python
# tests/test_capturer.py
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image
import imagehash

from skillbill.capturer import (
    extract_frame,
    is_duplicate_frame,
    capture_screenshots,
    detect_scenes,
)


class TestIsDuplicateFrame:
    def test_identical_images_are_duplicates(self, tmp_path):
        img = Image.new("RGB", (100, 100), color="red")
        path1 = tmp_path / "a.png"
        path2 = tmp_path / "b.png"
        img.save(path1)
        img.save(path2)
        assert is_duplicate_frame(path1, [path2], threshold=12) is True

    def test_different_images_not_duplicates(self, tmp_path):
        img1 = Image.new("RGB", (100, 100), color="red")
        img2 = Image.new("RGB", (100, 100), color="blue")
        path1 = tmp_path / "a.png"
        path2 = tmp_path / "b.png"
        img1.save(path1)
        img2.save(path2)
        assert is_duplicate_frame(path1, [path2], threshold=12) is False

    def test_empty_history(self, tmp_path):
        img = Image.new("RGB", (100, 100), color="red")
        path = tmp_path / "a.png"
        img.save(path)
        assert is_duplicate_frame(path, [], threshold=12) is False


class TestDetectScenes:
    @patch("skillbill.capturer.detect")
    def test_returns_timestamps(self, mock_detect):
        mock_start = MagicMock()
        mock_start.get_seconds.return_value = 10.0
        mock_end = MagicMock()
        mock_end.get_seconds.return_value = 25.0
        mock_detect.return_value = [(mock_start, mock_end)]

        result = detect_scenes("/fake/video.mp4")
        assert 10.0 in result
```

**Step 2: Run tests to verify they fail**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_capturer.py -v`
Expected: FAIL

**Step 3: Implement capturer.py**

```python
"""Stage 5: Frame extraction with ffmpeg and perceptual hash deduplication."""
import subprocess
from pathlib import Path

import imagehash
from PIL import Image
from scenedetect import detect, ContentDetector, AdaptiveDetector


def detect_scenes(video_path: str, threshold: float = 27.0) -> list[float]:
    """Detect scene change timestamps using PySceneDetect.

    Returns list of timestamps (seconds) where scene changes occur.
    """
    scene_list = detect(video_path, ContentDetector(threshold=threshold))
    timestamps = []
    for scene in scene_list:
        timestamps.append(scene[0].get_seconds())
    return timestamps


def extract_frame(video_path: str, timestamp: float, output_path: Path) -> Path:
    """Extract a single frame from video at the given timestamp using ffmpeg.

    Returns path to the saved PNG file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Format timestamp as HH:MM:SS.mmm
    hours = int(timestamp // 3600)
    minutes = int((timestamp % 3600) // 60)
    seconds = timestamp % 60
    ts_str = f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"

    cmd = [
        "ffmpeg",
        "-ss", ts_str,
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        "-y",
        str(output_path),
    ]

    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def is_duplicate_frame(
    frame_path: Path,
    previous_frames: list[Path],
    threshold: int = 12,
) -> bool:
    """Check if a frame is a near-duplicate of any previously captured frame.

    Uses perceptual hashing (dhash). Lower threshold = stricter matching.
    """
    if not previous_frames:
        return False

    current_hash = imagehash.dhash(Image.open(frame_path))

    for prev_path in previous_frames:
        if prev_path.exists():
            prev_hash = imagehash.dhash(Image.open(prev_path))
            if abs(current_hash - prev_hash) <= threshold:
                return True

    return False


def capture_screenshots(
    video_path: str,
    screenshot_plan: dict,
    output_dir: Path,
    dedup_threshold: int = 12,
    lookback: int = 5,
) -> list[dict]:
    """Execute the screenshot plan: extract frames and deduplicate.

    Returns list of dicts with timestamp, path, and kept/skipped status.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    kept_frames = []

    for entry in screenshot_plan["screenshots"]:
        ts = entry["timestamp"]
        minutes = int(ts // 60)
        seconds = int(ts % 60)
        filename = f"{minutes:02d}-{seconds:02d}.png"
        frame_path = output_dir / filename

        try:
            extract_frame(video_path, ts, frame_path)
        except subprocess.CalledProcessError:
            results.append({"timestamp": ts, "path": None, "status": "error"})
            continue

        # Check for duplicates against last N frames
        recent_frames = kept_frames[-lookback:]
        if is_duplicate_frame(frame_path, recent_frames, threshold=dedup_threshold):
            frame_path.unlink()  # delete duplicate
            results.append({"timestamp": ts, "path": None, "status": "duplicate"})
        else:
            kept_frames.append(frame_path)
            results.append({
                "timestamp": ts,
                "path": str(frame_path),
                "reason": entry["reason"],
                "status": "kept",
            })

    return results
```

**Step 4: Run tests to verify they pass**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_capturer.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add "Skill Bill/skillbill/capturer.py" "Skill Bill/tests/test_capturer.py"
git commit -m "feat: add frame capturer with ffmpeg extraction and perceptual hash dedup"
```

---

## Task 5: Knowledge Base Generator (Markdown Assembly)

**Files:**
- Create: `Skill Bill/skillbill/generator.py`
- Create: `Skill Bill/tests/test_generator.py`

**Step 1: Write the failing tests**

```python
# tests/test_generator.py
import pytest
from pathlib import Path
from skillbill.generator import (
    format_timestamp,
    build_sections,
    extract_urls_from_description,
    generate_video_markdown,
    generate_course_index,
)


class TestFormatTimestamp:
    def test_seconds_only(self):
        assert format_timestamp(45.0) == "00:45"

    def test_minutes_and_seconds(self):
        assert format_timestamp(125.0) == "02:05"

    def test_hours(self):
        assert format_timestamp(3661.0) == "1:01:01"


class TestExtractUrls:
    def test_finds_urls(self):
        desc = "Check out https://github.com/example/repo and https://docs.example.com"
        urls = extract_urls_from_description(desc)
        assert len(urls) == 2
        assert "https://github.com/example/repo" in urls

    def test_no_urls(self):
        urls = extract_urls_from_description("No links here")
        assert urls == []


class TestBuildSections:
    def test_with_chapters(self, sample_transcript):
        chapters = [
            {"title": "Intro", "start_time": 0, "end_time": 30},
            {"title": "Main", "start_time": 30, "end_time": 120},
            {"title": "Demo", "start_time": 120, "end_time": 600},
        ]
        screenshots = [
            {"timestamp": 10.5, "path": "./assets/01/00-10.png", "reason": "verbal_cue"},
            {"timestamp": 60.0, "path": "./assets/01/01-00.png", "reason": "verbal_cue"},
        ]
        sections = build_sections(sample_transcript, chapters, screenshots)
        assert len(sections) == 3
        assert sections[0]["heading"] == "Intro"
        # Screenshot at 10.5 should be in first section (0-30)
        assert len(sections[0]["screenshots"]) == 1

    def test_without_chapters(self, sample_transcript):
        sections = build_sections(sample_transcript, [], [])
        assert len(sections) >= 1


class TestGenerateVideoMarkdown:
    def test_produces_valid_markdown(self, sample_transcript, tmp_path):
        result = generate_video_markdown(
            video_title="Test Video",
            course_title="Test Course",
            video_number=1,
            total_videos=10,
            duration=600,
            video_url="https://youtube.com/watch?v=abc123",
            transcript_entries=sample_transcript,
            chapters=[],
            screenshots=[],
            description="Check out https://example.com",
            output_path=tmp_path / "test.md",
        )
        assert (tmp_path / "test.md").exists()
        content = (tmp_path / "test.md").read_text()
        assert "# Test Video" in content
        assert "https://example.com" in content
```

**Step 2: Run tests to verify they fail**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_generator.py -v`
Expected: FAIL

**Step 3: Implement generator.py**

```python
"""Stage 6: Markdown knowledge base generation."""
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from skillbill.config import TEMPLATES_DIR


def format_timestamp(seconds: float) -> str:
    """Format seconds into MM:SS or H:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def extract_urls_from_description(description: str) -> list[str]:
    """Extract URLs from a video description."""
    url_pattern = r'https?://[^\s<>"\')\]]*'
    return re.findall(url_pattern, description)


def build_sections(
    transcript_entries: list[dict],
    chapters: list[dict],
    screenshots: list[dict],
) -> list[dict]:
    """Build content sections from transcript, chapters, and screenshots.

    If chapters exist, use them as section boundaries.
    Otherwise, create one continuous section.
    """
    if not chapters:
        # No chapters — single section
        transcript_text = " ".join(e["text"] for e in transcript_entries)
        section_screenshots = [
            {
                "caption": s.get("reason", "Screenshot"),
                "path": s["path"],
            }
            for s in screenshots
            if s.get("path")
        ]
        return [{
            "timestamp": format_timestamp(0),
            "heading": "Content",
            "transcript": transcript_text,
            "screenshots": section_screenshots,
        }]

    sections = []
    for chapter in chapters:
        start = chapter.get("start_time", 0)
        end = chapter.get("end_time", float("inf"))
        title = chapter.get("title", "Section")

        # Collect transcript entries in this chapter range
        entries_in_chapter = [
            e for e in transcript_entries if start <= e["start"] < end
        ]
        transcript_text = " ".join(e["text"] for e in entries_in_chapter)

        # Collect screenshots in this chapter range
        section_screenshots = [
            {
                "caption": s.get("reason", "Screenshot"),
                "path": s["path"],
            }
            for s in screenshots
            if s.get("path") and start <= s["timestamp"] < end
        ]

        sections.append({
            "timestamp": format_timestamp(start),
            "heading": title,
            "transcript": transcript_text,
            "screenshots": section_screenshots,
        })

    return sections


def generate_video_markdown(
    video_title: str,
    course_title: str,
    video_number: int,
    total_videos: int,
    duration: float,
    video_url: str,
    transcript_entries: list[dict],
    chapters: list[dict],
    screenshots: list[dict],
    description: str = "",
    output_path: Path = None,
) -> str:
    """Generate a complete markdown file for a single video."""
    sections = build_sections(transcript_entries, chapters, screenshots)
    linked_urls = extract_urls_from_description(description)
    chapter_names = [c.get("title", "") for c in chapters] if chapters else []

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("video.md.j2")

    content = template.render(
        video_title=video_title,
        course_title=course_title,
        video_number=video_number,
        total_videos=total_videos,
        duration_formatted=format_timestamp(duration),
        video_url=video_url,
        chapters=chapter_names,
        sections=sections,
        linked_urls=linked_urls,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)

    return content


def generate_course_index(
    course_title: str,
    playlist_url: str,
    videos: list[dict],
    output_path: Path = None,
    generated_date: str = "",
) -> str:
    """Generate the course-level index.md."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("index.md.j2")

    video_entries = []
    for i, v in enumerate(videos, 1):
        slug = re.sub(r"[^\w\s-]", "", v["title"].lower())
        slug = re.sub(r"[\s_]+", "-", slug).strip("-")
        video_entries.append({
            "number": i,
            "title": v["title"],
            "filename": f"{i:02d}-{slug}.md",
        })

    content = template.render(
        course_title=course_title,
        playlist_url=playlist_url,
        total_videos=len(videos),
        generated_date=generated_date,
        videos=video_entries,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)

    return content
```

**Step 4: Run tests to verify they pass**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_generator.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add "Skill Bill/skillbill/generator.py" "Skill Bill/tests/test_generator.py" "Skill Bill/templates/"
git commit -m "feat: add markdown knowledge base generator with Jinja2 templates"
```

---

## Task 6: Pipeline Orchestrator

**Files:**
- Create: `Skill Bill/skillbill/pipeline.py`
- Modify: `Skill Bill/run.py`
- Create: `Skill Bill/tests/test_pipeline.py`

**Step 1: Write the failing tests**

```python
# tests/test_pipeline.py
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from skillbill.pipeline import Pipeline


class TestPipelineInit:
    def test_creates_data_dirs(self, tmp_path):
        p = Pipeline(data_dir=tmp_path)
        assert (tmp_path / "raw").exists()
        assert (tmp_path / "processed").exists()
        assert (tmp_path / "assets").exists()
        assert (tmp_path / "knowledge_base").exists()


class TestPipelineStages:
    @patch("skillbill.pipeline.discover_playlist")
    def test_discovery_stage(self, mock_discover, tmp_path, sample_manifest):
        mock_discover.return_value = sample_manifest
        p = Pipeline(data_dir=tmp_path)
        result = p.run_discovery("https://youtube.com/playlist?list=PLtest")
        assert result["playlist_title"] == "Test Course"
        mock_discover.assert_called_once()

    @patch("skillbill.pipeline.fetch_all_transcripts")
    def test_transcript_stage(self, mock_fetch, tmp_path, sample_manifest):
        mock_fetch.return_value = [
            {"video_id": "abc123", "has_transcript": True, "entries": []},
            {"video_id": "def456", "has_transcript": True, "entries": []},
        ]
        p = Pipeline(data_dir=tmp_path)
        p.manifest = sample_manifest
        result = p.run_transcripts()
        assert len(result) == 2
```

**Step 2: Run tests to verify they fail**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_pipeline.py -v`
Expected: FAIL

**Step 3: Implement pipeline.py**

```python
"""Pipeline orchestrator: runs all stages or individual stages."""
import json
from datetime import date
from pathlib import Path
from typing import Optional

from skillbill.config import DATA_DIR
from skillbill.downloader import discover_playlist, download_video, slugify_title
from skillbill.transcript import fetch_all_transcripts, compute_speech_density, detect_sparse_sections
from skillbill.analyzer import build_screenshot_plan
from skillbill.capturer import detect_scenes, capture_screenshots
from skillbill.generator import generate_video_markdown, generate_course_index


class Pipeline:
    """Orchestrates the full YouTube-to-Knowledge-Base pipeline."""

    def __init__(self, data_dir: Optional[Path] = None, use_haiku: bool = True):
        self.data_dir = data_dir or DATA_DIR
        self.raw_dir = self.data_dir / "raw"
        self.processed_dir = self.data_dir / "processed"
        self.assets_dir = self.data_dir / "assets"
        self.kb_dir = self.data_dir / "knowledge_base"
        self.use_haiku = use_haiku
        self.manifest = None
        self.transcripts = None
        self.screenshot_plans = None
        self.capture_results = None

        # Create directories
        for d in [self.raw_dir, self.processed_dir, self.assets_dir, self.kb_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def run_discovery(self, url: str) -> dict:
        """Stage 1: Discover playlist metadata."""
        self.manifest = discover_playlist(url, output_dir=self.raw_dir)
        print(f"Discovered: {self.manifest['playlist_title']} ({self.manifest['video_count']} videos)")
        return self.manifest

    def run_transcripts(self) -> list[dict]:
        """Stage 2: Fetch transcripts for all videos."""
        if not self.manifest:
            raise ValueError("Run discovery first")

        video_ids = [v["id"] for v in self.manifest["videos"]]
        slug = self.manifest["slug"]

        self.transcripts = fetch_all_transcripts(
            video_ids, output_dir=self.processed_dir, course_slug=slug,
        )

        found = sum(1 for t in self.transcripts if t["has_transcript"])
        print(f"Transcripts: {found}/{len(video_ids)} found")
        return self.transcripts

    def run_download(self) -> list[Path]:
        """Stage 3: Download video files."""
        if not self.manifest:
            raise ValueError("Run discovery first")

        slug = self.manifest["slug"]
        output_dir = self.raw_dir / slug
        paths = []

        for i, video in enumerate(self.manifest["videos"], 1):
            prefix = f"{i:02d}-"
            print(f"Downloading {i}/{self.manifest['video_count']}: {video['title']}")
            path = download_video(video["url"], output_dir, filename_prefix=prefix)
            paths.append(path)

        return paths

    def run_screenshot_planning(self, video_paths: list[Path]) -> list[dict]:
        """Stage 4: Plan screenshots for all videos."""
        if not self.manifest or not self.transcripts:
            raise ValueError("Run discovery and transcripts first")

        slug = self.manifest["slug"]
        self.screenshot_plans = []

        for i, (video, transcript) in enumerate(
            zip(self.manifest["videos"], self.transcripts)
        ):
            if not transcript["has_transcript"]:
                self.screenshot_plans.append({"video_id": video["id"], "screenshots": []})
                continue

            print(f"Analyzing {i + 1}/{len(self.transcripts)}: {video['title']}")

            # Detect scenes
            if i < len(video_paths) and video_paths[i].exists():
                scene_changes = detect_scenes(str(video_paths[i]))
            else:
                scene_changes = []

            # Compute density
            density = compute_speech_density(transcript["entries"])

            # Build plan
            plan = build_screenshot_plan(
                video_id=video["id"],
                transcript_entries=transcript["entries"],
                scene_changes=scene_changes,
                density=density,
                chapters=video.get("chapters"),
                use_haiku=self.use_haiku,
                output_dir=self.processed_dir,
                course_slug=slug,
            )
            self.screenshot_plans.append(plan)
            print(f"  → {plan['total_screenshots']} screenshots planned")

        return self.screenshot_plans

    def run_capture(self, video_paths: list[Path]) -> list[list[dict]]:
        """Stage 5: Capture screenshots."""
        if not self.screenshot_plans:
            raise ValueError("Run screenshot planning first")

        slug = self.manifest["slug"]
        self.capture_results = []

        for i, (plan, video_path) in enumerate(
            zip(self.screenshot_plans, video_paths)
        ):
            if not plan["screenshots"]:
                self.capture_results.append([])
                continue

            video_num = f"{i + 1:02d}"
            output_dir = self.assets_dir / slug / video_num
            print(f"Capturing frames for video {video_num}...")

            results = capture_screenshots(
                str(video_path), plan, output_dir,
            )
            kept = sum(1 for r in results if r["status"] == "kept")
            dupes = sum(1 for r in results if r["status"] == "duplicate")
            print(f"  → {kept} kept, {dupes} duplicates removed")
            self.capture_results.append(results)

        return self.capture_results

    def run_generation(self) -> Path:
        """Stage 6: Generate markdown knowledge base."""
        if not self.manifest or not self.transcripts:
            raise ValueError("Run discovery and transcripts first")

        slug = self.manifest["slug"]
        course_dir = self.kb_dir / slug
        course_dir.mkdir(parents=True, exist_ok=True)

        for i, (video, transcript) in enumerate(
            zip(self.manifest["videos"], self.transcripts)
        ):
            video_num = i + 1
            video_slug = slugify_title(video["title"])
            filename = f"{video_num:02d}-{video_slug}.md"

            # Collect kept screenshots with relative paths
            screenshots = []
            if self.capture_results and i < len(self.capture_results):
                for r in self.capture_results[i]:
                    if r["status"] == "kept" and r.get("path"):
                        rel_path = f"./assets/{video_num:02d}/{Path(r['path']).name}"
                        screenshots.append({
                            "timestamp": r["timestamp"],
                            "path": rel_path,
                            "reason": r.get("reason", ""),
                        })

            generate_video_markdown(
                video_title=video["title"],
                course_title=self.manifest["playlist_title"],
                video_number=video_num,
                total_videos=self.manifest["video_count"],
                duration=video.get("duration", 0),
                video_url=video["url"],
                transcript_entries=transcript.get("entries", []),
                chapters=video.get("chapters", []),
                screenshots=screenshots,
                description=video.get("description", ""),
                output_path=course_dir / filename,
            )

        # Copy assets to knowledge base
        src_assets = self.assets_dir / slug
        dst_assets = course_dir / "assets"
        if src_assets.exists():
            import shutil
            if dst_assets.exists():
                shutil.rmtree(dst_assets)
            shutil.copytree(src_assets, dst_assets)

        # Generate index
        generate_course_index(
            course_title=self.manifest["playlist_title"],
            playlist_url=self.manifest["playlist_url"],
            videos=self.manifest["videos"],
            output_path=course_dir / "index.md",
            generated_date=str(date.today()),
        )

        print(f"Knowledge base generated at: {course_dir}")
        return course_dir

    def run_all(self, url: str) -> Path:
        """Run the complete pipeline end-to-end."""
        self.run_discovery(url)
        self.run_transcripts()
        video_paths = self.run_download()
        self.run_screenshot_planning(video_paths)
        self.run_capture(video_paths)
        return self.run_generation()

    def run_transcript_only(self, url: str) -> Path:
        """Run pipeline without video download or screenshots."""
        self.run_discovery(url)
        self.run_transcripts()
        self.capture_results = [[] for _ in self.transcripts]
        return self.run_generation()
```

**Step 4: Update run.py with full CLI**

```python
"""CLI entry point for Skill Bill pipeline."""
import click
from pathlib import Path

from skillbill.pipeline import Pipeline


@click.group()
def cli():
    """Skill Bill - YouTube to Knowledge Base Pipeline."""
    pass


@cli.command()
@click.argument("url")
@click.option("--stage", type=click.Choice(
    ["discovery", "transcript", "download", "screenshots", "capture", "generate", "all"]
), default="all", help="Run a specific pipeline stage")
@click.option("--transcript-only", is_flag=True, help="Skip video download and screenshots")
@click.option("--no-haiku", is_flag=True, help="Disable Claude Haiku for segment classification")
@click.option("--data-dir", type=click.Path(), default=None, help="Custom data directory")
def playlist(url, stage, transcript_only, no_haiku, data_dir):
    """Process a YouTube playlist into a knowledge base."""
    data_path = Path(data_dir) if data_dir else None
    p = Pipeline(data_dir=data_path, use_haiku=not no_haiku)

    if transcript_only:
        result = p.run_transcript_only(url)
        click.echo(f"Done: {result}")
        return

    if stage == "all":
        result = p.run_all(url)
        click.echo(f"Done: {result}")
    elif stage == "discovery":
        p.run_discovery(url)
    elif stage == "transcript":
        p.run_discovery(url)
        p.run_transcripts()
    else:
        click.echo(f"Stage '{stage}' requires previous stages. Use --stage all.")


@cli.command()
@click.argument("url")
@click.option("--transcript-only", is_flag=True, help="Skip video download and screenshots")
@click.option("--no-haiku", is_flag=True, help="Disable Claude Haiku")
def video(url, transcript_only, no_haiku):
    """Process a single YouTube video into a knowledge base entry."""
    click.echo("Single video processing not yet implemented. Use playlist command.")


if __name__ == "__main__":
    cli()
```

**Step 5: Run all tests**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add "Skill Bill/skillbill/pipeline.py" "Skill Bill/run.py" "Skill Bill/tests/test_pipeline.py"
git commit -m "feat: add pipeline orchestrator and CLI entry point"
```

---

## Task 7: Integration Test with Real YouTube Video

**Files:**
- Create: `Skill Bill/tests/test_integration.py`

**Step 1: Write integration test**

```python
# tests/test_integration.py
"""Integration test using a short, public YouTube video.

Run with: pytest tests/test_integration.py -v -m integration
Requires: internet connection, ffmpeg installed
"""
import pytest
from pathlib import Path
from skillbill.pipeline import Pipeline

# Short Creative Commons video for testing
TEST_PLAYLIST_URL = None  # Set to a real playlist URL for manual testing
TEST_VIDEO_ID = "jNQXAC9IVRw"  # "Me at the zoo" - first YouTube video (19s)


@pytest.mark.integration
class TestTranscriptOnly:
    def test_fetch_real_transcript(self):
        from skillbill.transcript import fetch_transcript
        result = fetch_transcript(TEST_VIDEO_ID)
        # This video may or may not have captions
        assert "video_id" in result
        assert isinstance(result["entries"], list)


@pytest.mark.integration
class TestDiscoveryReal:
    def test_discover_single_video(self):
        from skillbill.downloader import discover_playlist
        # Single video URL also works with yt-dlp
        result = discover_playlist(f"https://youtube.com/watch?v={TEST_VIDEO_ID}")
        assert result is not None
```

**Step 2: Run integration tests**

Run: `cd "skill-bill-vol-1" && python -m pytest tests/test_integration.py -v -m integration`
Expected: PASS (with internet connection)

**Step 3: Commit**

```bash
git add "Skill Bill/tests/test_integration.py"
git commit -m "test: add integration tests with real YouTube content"
```

---

## Execution Checklist

| Task | Description | Tests |
|------|-------------|-------|
| 0 | Project scaffolding | Setup verified |
| 1 | Discovery module (yt-dlp) | 4 tests |
| 2 | Transcript module | 5 tests |
| 3 | Screenshot analyzer | 8 tests |
| 4 | Frame capturer | 3 tests |
| 5 | Knowledge base generator | 4 tests |
| 6 | Pipeline orchestrator + CLI | 3 tests |
| 7 | Integration test | 2 tests |

Total: ~29 unit tests + 2 integration tests

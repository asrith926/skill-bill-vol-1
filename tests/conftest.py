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
        "slug": "test-course",
        "video_count": 2,
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
            {"timestamp": 10.5, "reason": "verbal_cue: as you can see", "segment_type": "code-demo"},
            {"timestamp": 15.0, "reason": "scene_change", "segment_type": "code-demo"},
            {"timestamp": 25.0, "reason": "interval_fallback", "segment_type": "code-demo"},
            {"timestamp": 60.0, "reason": "verbal_cue: this diagram", "segment_type": "slides"},
            {"timestamp": 120.0, "reason": "chapter_boundary", "segment_type": "code-demo"},
        ],
    }

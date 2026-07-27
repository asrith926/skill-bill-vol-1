# tests/test_generator.py
import pytest
from pathlib import Path
from skillbill.generator import (
    format_timestamp,
    build_sections,
    extract_urls_from_description,
    generate_video_markdown,
    generate_course_index,
    _interleave_content,
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


class TestInterleaveContent:
    def test_text_only(self):
        entries = [
            {"start": 0.0, "text": "Hello"},
            {"start": 5.0, "text": "World"},
        ]
        blocks = _interleave_content(entries, [])
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"
        assert blocks[0]["content"] == "Hello World"

    def test_screenshot_splits_text(self):
        entries = [
            {"start": 0.0, "text": "Before"},
            {"start": 5.0, "text": "After"},
        ]
        screenshots = [
            {"timestamp": 3.0, "path": "/img.png", "reason": "scene_change"},
        ]
        blocks = _interleave_content(entries, screenshots)
        assert len(blocks) == 3
        assert blocks[0]["type"] == "text"
        assert blocks[0]["content"] == "Before"
        assert blocks[1]["type"] == "screenshot"
        assert blocks[1]["path"] == "/img.png"
        assert blocks[2]["type"] == "text"
        assert blocks[2]["content"] == "After"

    def test_screenshots_without_path_skipped(self):
        entries = [{"start": 0.0, "text": "Hello"}]
        screenshots = [{"timestamp": 1.0, "path": None, "reason": "dup"}]
        blocks = _interleave_content(entries, screenshots)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"

    def test_caption_from_reason(self):
        entries = [{"start": 0.0, "text": "Hi"}]
        screenshots = [{"timestamp": 5.0, "path": "/a.png", "reason": "slide_transition"}]
        blocks = _interleave_content(entries, screenshots)
        screenshot_block = [b for b in blocks if b["type"] == "screenshot"][0]
        assert screenshot_block["caption"] == "slide_transition"

    def test_caption_field_preferred(self):
        entries = [{"start": 0.0, "text": "Hi"}]
        screenshots = [{"timestamp": 5.0, "path": "/a.png", "caption": "Code editor", "reason": "scene_change"}]
        blocks = _interleave_content(entries, screenshots)
        screenshot_block = [b for b in blocks if b["type"] == "screenshot"][0]
        assert screenshot_block["caption"] == "Code editor"

    def test_empty_inputs(self):
        blocks = _interleave_content([], [])
        assert blocks == []


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
        # Screenshot at 10.5 should be in first section's content_blocks
        screenshot_blocks = [
            b for b in sections[0]["content_blocks"] if b["type"] == "screenshot"
        ]
        assert len(screenshot_blocks) == 1

    def test_without_chapters(self, sample_transcript):
        sections = build_sections(sample_transcript, [], [])
        assert len(sections) >= 1
        assert "content_blocks" in sections[0]

    def test_sections_have_content_blocks(self, sample_transcript):
        """Sections use content_blocks key for interleaved content."""
        chapters = [
            {"title": "Intro", "start_time": 0, "end_time": 30},
        ]
        screenshots = [
            {"timestamp": 10.0, "path": "/a.png", "reason": "scene_change"},
        ]
        sections = build_sections(sample_transcript, chapters, screenshots)
        assert "content_blocks" in sections[0]
        # Old keys should not exist
        assert "transcript" not in sections[0]
        assert "screenshots" not in sections[0]

    def test_inline_screenshots_between_text(self, sample_transcript):
        """Screenshot appears between text blocks at correct position."""
        chapters = [
            {"title": "Full", "start_time": 0, "end_time": 200},
        ]
        screenshots = [
            {"timestamp": 8.0, "path": "/mid.png", "reason": "scene_change"},
        ]
        sections = build_sections(sample_transcript, chapters, screenshots)
        blocks = sections[0]["content_blocks"]
        types = [b["type"] for b in blocks]
        # Should have text, screenshot, text pattern
        assert "screenshot" in types
        screenshot_idx = types.index("screenshot")
        # Text before screenshot
        assert any(t == "text" for t in types[:screenshot_idx])
        # Text after screenshot
        assert any(t == "text" for t in types[screenshot_idx + 1:])


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

    def test_inline_screenshots_in_output(self, sample_transcript, tmp_path):
        """Screenshot markdown appears inline in rendered output."""
        chapters = [
            {"title": "Intro", "start_time": 0, "end_time": 200},
        ]
        screenshots = [
            {"timestamp": 8.0, "path": "./assets/01/00-08.png", "reason": "scene_change"},
        ]
        content = generate_video_markdown(
            video_title="Test",
            course_title="Course",
            video_number=1,
            total_videos=1,
            duration=200,
            video_url="https://youtube.com/watch?v=test",
            transcript_entries=sample_transcript,
            chapters=chapters,
            screenshots=screenshots,
            output_path=tmp_path / "test.md",
        )
        # Screenshot should appear in the output
        assert "![scene_change](./assets/01/00-08.png)" in content
        # Transcript text should also appear
        assert "Welcome to this tutorial" in content

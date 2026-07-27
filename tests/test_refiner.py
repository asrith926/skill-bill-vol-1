"""Tests for the AI refinement module."""
import pytest
from unittest.mock import patch, MagicMock
from skillbill.refiner import (
    filter_screenshots,
    refine_video_title,
    refine_video_content,
    _build_vision_content,
    refine_course,
    generate_skill_description,
    _get_surrounding_transcript,
    caption_screenshot,
    generate_topic_index,
)
from skillbill.downloader import slugify_title


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
        assert len(result) == 3
        reasons = [s["reason"] for s in result]
        assert "section_start" not in reasons
        assert "mid_section" not in reasons

    def test_empty_input(self):
        assert filter_screenshots([]) == []


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
        mock_call.return_value = "  Clean Title  \n"
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

    def test_empty_transcript_returns_original(self):
        """Deleted/unavailable videos with no transcript should keep original title."""
        result = refine_video_title("My Video Title", "", api_key="sk-test")
        assert result == "My Video Title"

    def test_whitespace_only_transcript_returns_original(self):
        result = refine_video_title("My Video Title", "   ", api_key="sk-test")
        assert result == "My Video Title"

    @patch("skillbill.refiner._call_haiku")
    def test_rejects_haiku_refusal(self, mock_call):
        """If Haiku returns a refusal message, fall back to original title."""
        mock_call.return_value = "I cannot generate a title without content information."
        result = refine_video_title("Original Title", "some preview", api_key="sk-test")
        assert result == "Original Title"

    @patch("skillbill.refiner._call_haiku")
    def test_rejects_absurdly_long_title(self, mock_call):
        mock_call.return_value = "A" * 100
        result = refine_video_title("Original Title", "some preview", api_key="sk-test")
        assert result == "Original Title"


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
            screenshot_rel_paths=["./assets/01/test.png"],
            screenshot_captions=["Code editor showing main function"],
        )
        types = [c["type"] for c in content]
        assert "text" in types
        assert "image" in types
        # Verify the relative path label and caption are included before the image
        text_blocks = [c["text"] for c in content if c["type"] == "text"]
        assert any("./assets/01/test.png" in t for t in text_blocks)
        assert any("Code editor showing main function" in t for t in text_blocks)

    def test_prompt_requires_all_screenshots(self, tmp_path):
        """When screenshots are provided, prompt must require ALL be placed."""
        img_path = tmp_path / "test.png"
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
            transcript_text="Hello world",
            video_title="Test",
            duration=60.0,
            screenshot_paths=[str(img_path)],
            screenshot_rel_paths=["./assets/01/test.png"],
        )
        prompt_text = content[0]["text"]
        assert "MUST embed ALL" in prompt_text
        assert "Do NOT skip any screenshot" in prompt_text


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

    @patch("skillbill.refiner._build_vision_content")
    @patch("skillbill.refiner._call_haiku")
    def test_passes_captions_to_build_vision_content(self, mock_call, mock_build, tmp_path):
        """refine_video_content should collect captions from screenshots and pass them through."""
        mock_call.return_value = "1. **Step** — Do it.\n"
        mock_build.return_value = [{"type": "text", "text": "prompt"}]

        img_path = tmp_path / "shot.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        result = refine_video_content(
            transcript_entries=[{"start": 0.0, "duration": 5.0, "text": "Hello"}],
            chapters=[],
            filtered_screenshots=[
                {"timestamp": 10.0, "path": str(img_path), "reason": "scene_change", "caption": "Editor with code"},
                {"timestamp": 20.0, "path": str(img_path), "reason": "slide_transition", "caption": "Slide showing architecture"},
            ],
            video_title="Test",
            duration=60.0,
            video_num=1,
            api_key="sk-test",
        )
        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args[1]
        assert call_kwargs["screenshot_captions"] == ["Editor with code", "Slide showing architecture"]


class TestGetSurroundingTranscript:
    def test_extracts_entries_within_window(self):
        entries = [
            {"start": 0.0, "text": "Hello"},
            {"start": 10.0, "text": "World"},
            {"start": 25.0, "text": "Goodbye"},
            {"start": 50.0, "text": "Far away"},
        ]
        result = _get_surrounding_transcript(entries, timestamp=10.0, window_seconds=15.0)
        assert "Hello" in result
        assert "World" in result
        assert "Goodbye" in result
        assert "Far away" not in result

    def test_excludes_distant_entries(self):
        entries = [
            {"start": 0.0, "text": "Early"},
            {"start": 100.0, "text": "Late"},
        ]
        result = _get_surrounding_transcript(entries, timestamp=50.0, window_seconds=15.0)
        assert result == ""

    def test_empty_entries(self):
        result = _get_surrounding_transcript([], timestamp=10.0)
        assert result == ""


class TestCaptionScreenshot:
    @patch("skillbill.refiner._call_haiku")
    def test_returns_caption(self, mock_call, tmp_path):
        mock_call.return_value = "Terminal showing pytest output with 5 passing tests"
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        result = caption_screenshot(
            path=str(img_path),
            surrounding_transcript="Now let's run the tests",
            timestamp=30.0,
            video_title="TDD Tutorial",
            api_key="sk-test",
        )
        assert result == "Terminal showing pytest output with 5 passing tests"
        mock_call.assert_called_once()

    def test_no_api_key_returns_fallback(self):
        result = caption_screenshot(
            path="/fake.png",
            surrounding_transcript="test",
            timestamp=0.0,
            video_title="Test",
            api_key="",
        )
        assert result == "Screenshot"

    @patch("skillbill.refiner._call_haiku")
    def test_api_error_returns_fallback(self, mock_call, tmp_path):
        mock_call.side_effect = Exception("API error")
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        result = caption_screenshot(
            path=str(img_path),
            surrounding_transcript="test",
            timestamp=0.0,
            video_title="Test",
            api_key="sk-test",
        )
        assert result == "Screenshot"

    def test_missing_file_returns_fallback(self):
        result = caption_screenshot(
            path="/nonexistent/image.png",
            surrounding_transcript="test",
            timestamp=0.0,
            video_title="Test",
            api_key="sk-test",
        )
        assert result == "Screenshot"


class TestRefineCourse:
    @patch("skillbill.refiner.refine_video_title")
    @patch("skillbill.refiner.refine_video_content")
    @patch("skillbill.refiner.filter_screenshots")
    def test_creates_refined_files(self, mock_filter, mock_content, mock_title, tmp_path):
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

        # Old file removed, new file exists with clean title
        assert not (course_dir / "01-old-title.md").exists()
        new_slug = slugify_title("Clean Descriptive Title")
        new_file = course_dir / f"01-{new_slug}.md"
        assert new_file.exists()

        content = new_file.read_text()
        assert "Clean Descriptive Title" in content
        assert "Step one" in content

        index = (course_dir / "index.md").read_text()
        assert "Clean Descriptive Title" in index
        assert "old-title" not in index

        # Marker file created
        assert (course_dir / ".refined").exists()

    @patch("skillbill.refiner.refine_video_title")
    @patch("skillbill.refiner.refine_video_content")
    @patch("skillbill.refiner.filter_screenshots")
    def test_handles_none_duration(self, mock_filter, mock_content, mock_title, tmp_path):
        """Videos with duration=None should not crash the pipeline."""
        course_dir = tmp_path / "test-course"
        course_dir.mkdir()
        (course_dir / "01-v1.md").write_text("# V1\n\nRaw.\n")

        mock_title.return_value = "Clean Title"
        mock_content.return_value = "1. **Step** — Do it.\n"
        mock_filter.return_value = []

        manifest = {
            "playlist_title": "Test",
            "slug": "test-course",
            "video_count": 1,
            "playlist_url": "https://youtube.com/playlist?list=PLtest",
            "videos": [{"id": "abc", "title": "V1", "url": "https://youtube.com/watch?v=abc", "duration": None}],
        }
        transcripts = [{"video_id": "abc", "has_transcript": True, "entries": [{"start": 0, "duration": 5, "text": "Hi"}]}]

        result = refine_course(course_dir, manifest, transcripts, [[]], api_key="sk-test")
        assert (course_dir / ".refined").exists()

    @patch("skillbill.refiner.generate_skill_description")
    @patch("skillbill.refiner.refine_video_title")
    @patch("skillbill.refiner.refine_video_content")
    @patch("skillbill.refiner.filter_screenshots")
    def test_writes_skill_meta_json(self, mock_filter, mock_content, mock_title, mock_desc, tmp_path):
        import json
        course_dir = tmp_path / "test-course"
        course_dir.mkdir()
        (course_dir / "index.md").write_text("# Test\n")
        (course_dir / "01-v1.md").write_text("# V1\n")

        mock_title.return_value = "Clean Title"
        mock_content.return_value = "1. **Step** — Do it.\n"
        mock_filter.return_value = []
        mock_desc.return_value = "AI-crafted description with triggers."

        manifest = {
            "playlist_title": "Test Course",
            "slug": "test-course",
            "video_count": 1,
            "playlist_url": "https://youtube.com/playlist?list=PLtest",
            "videos": [{"id": "abc", "title": "V1", "url": "https://youtube.com/watch?v=abc", "duration": 120, "chapters": [], "description": ""}],
        }
        transcripts = [{"video_id": "abc", "has_transcript": True, "entries": [{"start": 0, "duration": 5, "text": "Hi"}], "chapters": [], "description": ""}]

        refine_course(course_dir, manifest, transcripts, [[]], api_key="sk-test")

        # .skill_meta.json should exist with ai_description
        meta_path = course_dir / ".skill_meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["ai_description"] == "AI-crafted description with triggers."
        mock_desc.assert_called_once()

    @patch("skillbill.refiner.generate_skill_description")
    @patch("skillbill.refiner.refine_video_title")
    @patch("skillbill.refiner.refine_video_content")
    @patch("skillbill.refiner.filter_screenshots")
    def test_skill_meta_uses_clean_titles(self, mock_filter, mock_content, mock_title, mock_desc, tmp_path):
        course_dir = tmp_path / "test-course"
        course_dir.mkdir()
        (course_dir / "index.md").write_text("# Test\n")
        (course_dir / "01-v1.md").write_text("# V1\n")

        mock_title.return_value = "Clean Video Title"
        mock_content.return_value = "1. **Step** — Do it.\n"
        mock_filter.return_value = []
        mock_desc.return_value = "Description."

        manifest = {
            "playlist_title": "Test Course",
            "slug": "test-course",
            "video_count": 1,
            "playlist_url": "https://youtube.com/playlist?list=PLtest",
            "videos": [{"id": "abc", "title": "Clickbait Original", "url": "https://youtube.com/watch?v=abc", "duration": 120, "chapters": [], "description": ""}],
        }
        transcripts = [{"video_id": "abc", "has_transcript": True, "entries": [{"start": 0, "duration": 5, "text": "Hi"}], "chapters": [], "description": ""}]

        refine_course(course_dir, manifest, transcripts, [[]], api_key="sk-test")

        # generate_skill_description should receive the CLEAN title, not original
        call_args = mock_desc.call_args
        video_titles_arg = call_args[1].get("video_titles") or call_args[0][1]
        assert "Clean Video Title" in video_titles_arg
        assert "Clickbait Original" not in video_titles_arg

    @patch("skillbill.refiner.refine_video_title")
    @patch("skillbill.refiner.refine_video_content")
    @patch("skillbill.refiner.filter_screenshots")
    def test_removes_stale_files_from_prior_runs(self, mock_filter, mock_content, mock_title, tmp_path):
        """Re-running refinement should remove files from prior runs, not accumulate duplicates."""
        course_dir = tmp_path / "test-course"
        course_dir.mkdir()
        (course_dir / "index.md").write_text("# Test\n")
        # Simulate stale files from 3 prior refinement runs with different Haiku titles
        (course_dir / "01-intro-to-mcp.md").write_text("# stale 1\n")
        (course_dir / "01-model-context-protocol-guide.md").write_text("# stale 2\n")
        (course_dir / "01-mcp-integration-overview.md").write_text("# stale 3\n")

        mock_title.return_value = "Getting Started With MCP"
        mock_content.return_value = "1. **Step** — Do it.\n"
        mock_filter.return_value = []

        manifest = {
            "playlist_title": "Test Course",
            "slug": "test-course",
            "video_count": 1,
            "playlist_url": "https://youtube.com/playlist?list=PLtest",
            "videos": [{"id": "abc", "title": "Original Title", "url": "https://youtube.com/watch?v=abc", "duration": 120, "chapters": [], "description": ""}],
        }
        transcripts = [{"video_id": "abc", "has_transcript": True, "entries": [{"start": 0, "duration": 5, "text": "Hi"}], "chapters": [], "description": ""}]

        refine_course(course_dir, manifest, transcripts, [[]], api_key="sk-test")

        # Only ONE file should exist for video 01
        video_01_files = list(course_dir.glob("01-*.md"))
        assert len(video_01_files) == 1
        assert "getting-started-with-mcp" in video_01_files[0].name

    @patch("skillbill.refiner.generate_topic_index")
    @patch("skillbill.refiner.refine_video_title")
    @patch("skillbill.refiner.refine_video_content")
    @patch("skillbill.refiner.filter_screenshots")
    def test_writes_topics_json(self, mock_filter, mock_content, mock_title, mock_topics, tmp_path):
        """refine_course should write topics.json when topic index succeeds."""
        import json
        course_dir = tmp_path / "test-course"
        course_dir.mkdir()
        (course_dir / "index.md").write_text("# Test\n")
        (course_dir / "01-v1.md").write_text("# V1\n")

        mock_title.return_value = "Clean Title"
        mock_content.return_value = "1. **Step** — Do it.\n"
        mock_filter.return_value = []
        mock_topics.return_value = {"topics": {"python": [{"video": 1, "step": 1}]}}

        manifest = {
            "playlist_title": "Test Course",
            "slug": "test-course",
            "video_count": 1,
            "playlist_url": "https://youtube.com/playlist?list=PLtest",
            "videos": [{"id": "abc", "title": "V1", "url": "https://youtube.com/watch?v=abc", "duration": 120, "chapters": [], "description": ""}],
        }
        transcripts = [{"video_id": "abc", "has_transcript": True, "entries": [{"start": 0, "duration": 5, "text": "Hi"}], "chapters": [], "description": ""}]

        refine_course(course_dir, manifest, transcripts, [[]], api_key="sk-test")

        topics_path = course_dir / "topics.json"
        assert topics_path.exists()
        data = json.loads(topics_path.read_text())
        assert "topics" in data
        assert "python" in data["topics"]

    @patch("skillbill.refiner.caption_screenshot")
    @patch("skillbill.refiner.refine_video_title")
    @patch("skillbill.refiner.refine_video_content")
    @patch("skillbill.refiner.filter_screenshots")
    def test_captions_each_screenshot(self, mock_filter, mock_content, mock_title, mock_caption, tmp_path):
        """refine_course should call caption_screenshot for each filtered screenshot."""
        course_dir = tmp_path / "test-course"
        course_dir.mkdir()
        (course_dir / "index.md").write_text("# Test\n")
        (course_dir / "01-v1.md").write_text("# V1\n")

        # Create a fake screenshot file
        img_path = tmp_path / "screenshot.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        mock_title.return_value = "Clean Title"
        mock_content.return_value = "1. **Step** — Do it.\n"
        mock_filter.return_value = [
            {"timestamp": 10.0, "path": str(img_path), "reason": "scene_change", "status": "kept"},
            {"timestamp": 30.0, "path": str(img_path), "reason": "slide_transition", "status": "kept"},
        ]
        mock_caption.return_value = "Code editor showing function"

        manifest = {
            "playlist_title": "Test Course",
            "slug": "test-course",
            "video_count": 1,
            "playlist_url": "https://youtube.com/playlist?list=PLtest",
            "videos": [{"id": "abc", "title": "V1", "url": "https://youtube.com/watch?v=abc", "duration": 120, "chapters": [], "description": ""}],
        }
        transcripts = [{"video_id": "abc", "has_transcript": True, "entries": [{"start": 0, "duration": 5, "text": "Hello"}], "chapters": [], "description": ""}]
        capture_results = [[
            {"timestamp": 10.0, "path": str(img_path), "reason": "scene_change", "status": "kept"},
            {"timestamp": 30.0, "path": str(img_path), "reason": "slide_transition", "status": "kept"},
        ]]

        refine_course(course_dir, manifest, transcripts, capture_results, api_key="sk-test")

        assert mock_caption.call_count == 2

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

        mock_title.return_value = "Clean V1"
        refine_course(course_dir, manifest, transcripts, capture_results, api_key="sk-test")

        # Title cleanup should still be attempted
        mock_title.assert_called_once()
        # Content refinement should NOT be called (no transcript)
        mock_content.assert_not_called()


class TestGenerateTopicIndex:
    @patch("skillbill.refiner._call_haiku")
    def test_returns_topic_mapping(self, mock_call):
        mock_call.return_value = '{"topics": {"kubernetes": [{"video": 1, "step": 2}], "docker": [{"video": 1, "step": 5}]}}'
        result = generate_topic_index(
            video_entries=[
                {"number": 1, "title": "Containers 101", "content": "1. **Docker** — ..."},
            ],
            api_key="sk-test",
        )
        assert "topics" in result
        assert "kubernetes" in result["topics"]
        mock_call.assert_called_once()

    def test_no_api_key_returns_empty(self):
        result = generate_topic_index(
            video_entries=[{"number": 1, "title": "Test", "content": "stuff"}],
            api_key="",
        )
        assert result == {}

    @patch("skillbill.refiner._call_haiku")
    def test_invalid_json_returns_empty(self, mock_call):
        mock_call.return_value = "not valid json {"
        result = generate_topic_index(
            video_entries=[{"number": 1, "title": "Test", "content": "stuff"}],
            api_key="sk-test",
        )
        assert result == {}

    @patch("skillbill.refiner._call_haiku")
    def test_api_error_returns_empty(self, mock_call):
        mock_call.side_effect = Exception("API error")
        result = generate_topic_index(
            video_entries=[{"number": 1, "title": "Test", "content": "stuff"}],
            api_key="sk-test",
        )
        assert result == {}


class TestGenerateSkillDescription:
    @patch("skillbill.refiner._call_haiku")
    def test_returns_ai_description(self, mock_call):
        mock_call.return_value = "Knowledge base covering MCPs, plugins, and skills. Use when asking about Claude Code features."
        result = generate_skill_description(
            course_title="Claude Code for Teams",
            video_titles=["MCPs Overview", "Plugins Setup", "Skills Deep Dive"],
            api_key="sk-test",
        )
        assert "MCPs" in result
        mock_call.assert_called_once()

    @patch("skillbill.refiner._call_haiku")
    def test_strips_whitespace(self, mock_call):
        mock_call.return_value = "  Clean description.  \n"
        result = generate_skill_description("Title", ["V1"], api_key="sk-test")
        assert result == "Clean description."

    @patch("skillbill.refiner._call_haiku")
    def test_falls_back_to_empty_on_error(self, mock_call):
        mock_call.side_effect = Exception("API error")
        result = generate_skill_description("Title", ["V1"], api_key="sk-test")
        assert result == ""

    def test_no_api_key_returns_empty(self):
        result = generate_skill_description("Title", ["V1"], api_key="")
        assert result == ""

    @patch("skillbill.refiner._call_haiku")
    def test_prompt_includes_video_titles(self, mock_call):
        mock_call.return_value = "Description."
        generate_skill_description(
            course_title="My Course",
            video_titles=["Intro to Python", "Advanced Functions"],
            api_key="sk-test",
        )
        prompt_text = mock_call.call_args[1]["messages"][0]["content"] if "messages" in mock_call.call_args[1] else mock_call.call_args[0][0][0]["content"]
        assert "Intro to Python" in prompt_text
        assert "Advanced Functions" in prompt_text

# tests/test_analyzer.py
import pytest
from unittest.mock import patch
from skillbill.analyzer import (
    scan_verbal_cues,
    plan_screenshots_for_segment,
    merge_and_deduplicate_timestamps,
    classify_segments_local,
    classify_segments_haiku,
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

    def test_talking_head_emits_no_screenshots(self):
        """Talking-head segments produce zero planned screenshots."""
        segment = {"type": "talking-head", "start": 0, "end": 120}
        scene_changes = []
        timestamps = plan_screenshots_for_segment(segment, scene_changes)
        assert len(timestamps) == 0

    def test_segment_type_preserved_in_entries(self):
        """Each planned screenshot entry carries segment_type."""
        segment = {"type": "code-demo", "start": 0, "end": 60}
        scene_changes = [10.0, 30.0]
        timestamps = plan_screenshots_for_segment(segment, scene_changes)
        assert len(timestamps) > 0
        for ts in timestamps:
            assert "segment_type" in ts
            assert ts["segment_type"] == "code-demo"

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

    def test_preserves_segment_type(self):
        """merge_and_deduplicate must not strip segment_type."""
        timestamps = [
            {"timestamp": 10.0, "reason": "scene_change", "segment_type": "code-demo"},
            {"timestamp": 50.0, "reason": "verbal_cue: look at", "segment_type": "slides"},
        ]
        result = merge_and_deduplicate_timestamps(timestamps, min_interval=5)
        assert all("segment_type" in r for r in result)
        assert result[0]["segment_type"] == "code-demo"
        assert result[1]["segment_type"] == "slides"


class TestClassifySegmentsHaiku:
    def test_no_api_key_returns_empty(self):
        segments = classify_segments_haiku("text", api_key="")
        assert segments == []

    @patch("skillbill.analyzer.json")
    def test_normalizes_start_seconds_to_start(self, mock_json):
        """Haiku returns start_seconds/end_seconds; should normalize to start/end."""
        # Mock the Anthropic client at the point of import inside the function
        from unittest.mock import MagicMock
        mock_client = MagicMock()
        mock_client.messages.create.return_value.content = [
            MagicMock(text="fake")
        ]
        mock_json.loads.return_value = [
            {"type": "code-demo", "start_seconds": 0, "end_seconds": 120},
            {"type": "slides", "start_seconds": 120, "end_seconds": 300},
        ]

        with patch("anthropic.Anthropic", return_value=mock_client):
            segments = classify_segments_haiku("transcript text", api_key="sk-test")

        assert len(segments) == 2
        assert segments[0]["start"] == 0
        assert segments[0]["end"] == 120
        assert segments[0]["type"] == "code-demo"
        assert segments[1]["start"] == 120

    @patch("skillbill.analyzer.json")
    def test_accepts_explicit_api_key(self, mock_json):
        from unittest.mock import MagicMock
        mock_client = MagicMock()
        mock_client.messages.create.return_value.content = [MagicMock(text="fake")]
        mock_json.loads.return_value = [{"type": "slides", "start_seconds": 0, "end_seconds": 60}]

        with patch("anthropic.Anthropic", return_value=mock_client) as mock_cls:
            classify_segments_haiku("text", api_key="sk-explicit")
            mock_cls.assert_called_once_with(api_key="sk-explicit")


class TestBuildScreenshotPlanApiKey:
    @patch("skillbill.analyzer.classify_segments_haiku")
    def test_passes_api_key_to_haiku(self, mock_haiku):
        """build_screenshot_plan should forward api_key to classify_segments_haiku."""
        mock_haiku.return_value = [
            {"type": "slides", "start": 0, "end": 60},
        ]
        build_screenshot_plan(
            video_id="test123",
            transcript_entries=[{"start": 0.0, "duration": 5.0, "text": "hello"}],
            scene_changes=[],
            density=[{"start": 0, "end": 60, "words_per_minute": 150}],
            use_haiku=True,
            api_key="sk-test-key",
        )
        mock_haiku.assert_called_once()
        assert mock_haiku.call_args[1]["api_key"] == "sk-test-key"

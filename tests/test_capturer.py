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
        # Use images with distinct gradient patterns — solid colors hash identically
        # under dhash since dhash measures gradient differences
        img1 = Image.new("RGB", (100, 100), color="red")
        img2 = Image.new("RGB", (100, 100))
        # Create a checkerboard pattern for visual distinctness
        pixels = img2.load()
        for x in range(100):
            for y in range(100):
                pixels[x, y] = (255, 255, 255) if (x // 10 + y // 10) % 2 == 0 else (0, 0, 0)
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


class TestCaptureScreenshots:
    """Tests for capture_screenshots with segment-aware dedup."""

    def _make_plan(self, entries):
        return {"screenshots": entries}

    @patch("skillbill.capturer.extract_frame")
    @patch("skillbill.capturer.is_duplicate_frame")
    def test_uses_segment_aware_thresholds(self, mock_dedup, mock_extract, tmp_path):
        """Different segment types should use different dedup thresholds."""
        # Track threshold values passed to is_duplicate_frame
        mock_dedup.return_value = False
        mock_extract.return_value = tmp_path / "frame.png"
        # Create dummy frame files so capture loop proceeds
        # scene_change gets +1.5s offset: 10→11.5 (00-11), 20→21.5 (00-21)
        for name in ["00-11.png", "00-21.png"]:
            (tmp_path / name).write_bytes(b"fake")

        plan = self._make_plan([
            {"timestamp": 10, "reason": "scene_change", "segment_type": "code-demo"},
            {"timestamp": 20, "reason": "scene_change", "segment_type": "slides"},
        ])

        thresholds = {"code-demo": 24, "slides": 16, "default": 18}
        capture_screenshots(
            "/fake/video.mp4", plan, tmp_path,
            segment_thresholds=thresholds,
        )

        # Verify is_duplicate_frame was called with the correct per-segment threshold
        calls = mock_dedup.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["threshold"] == 24  # code-demo
        assert calls[1].kwargs["threshold"] == 16  # slides

    @patch("skillbill.capturer.extract_frame")
    @patch("skillbill.capturer.is_duplicate_frame", return_value=False)
    def test_preserves_segment_type_in_results(self, mock_dedup, mock_extract, tmp_path):
        """Kept frames must carry segment_type in result dicts."""
        mock_extract.return_value = tmp_path / "frame.png"
        # scene_change +1.5s: 5→6.5 (00-06), slide_transition +1.5s: 30→31.5 (00-31)
        for name in ["00-06.png", "00-31.png"]:
            (tmp_path / name).write_bytes(b"fake")

        plan = self._make_plan([
            {"timestamp": 5, "reason": "scene_change", "segment_type": "code-demo"},
            {"timestamp": 30, "reason": "slide_transition", "segment_type": "slides"},
        ])

        results = capture_screenshots("/fake/video.mp4", plan, tmp_path)

        kept = [r for r in results if r["status"] == "kept"]
        assert len(kept) == 2
        assert kept[0]["segment_type"] == "code-demo"
        assert kept[1]["segment_type"] == "slides"

    @patch("skillbill.capturer.extract_frame")
    @patch("skillbill.capturer.is_duplicate_frame", return_value=False)
    def test_falls_back_to_default_threshold(self, mock_dedup, mock_extract, tmp_path):
        """Unknown segment types use the 'default' threshold from segment_thresholds."""
        mock_dedup.return_value = False
        mock_extract.return_value = tmp_path / "frame.png"
        (tmp_path / "00-10.png").write_bytes(b"fake")

        plan = self._make_plan([
            {"timestamp": 10, "reason": "interval", "segment_type": "whiteboard"},
        ])

        thresholds = {"code-demo": 24, "default": 18}
        capture_screenshots(
            "/fake/video.mp4", plan, tmp_path,
            segment_thresholds=thresholds,
        )

        calls = mock_dedup.call_args_list
        assert len(calls) == 1
        assert calls[0].kwargs["threshold"] == 18  # falls back to default

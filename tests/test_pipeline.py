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

    @patch("skillbill.pipeline.download_video")
    def test_download_skips_failed_videos(self, mock_download, tmp_path, sample_manifest):
        """Failed downloads return None instead of crashing the pipeline."""
        success_path = tmp_path / "raw" / "video.mp4"
        mock_download.side_effect = [Exception("Video unavailable"), success_path]

        p = Pipeline(data_dir=tmp_path)
        p.manifest = sample_manifest
        result = p.run_download()

        assert result == [None, success_path]

    @patch("skillbill.pipeline.download_video")
    def test_download_uses_cached_video(self, mock_download, tmp_path, sample_manifest):
        """Existing video files are reused instead of re-downloading."""
        p = Pipeline(data_dir=tmp_path)
        p.manifest = sample_manifest

        # Create cached file for the first video with video ID in filename
        cache_dir = tmp_path / "raw" / "test-course"
        cache_dir.mkdir(parents=True)
        cached = cache_dir / "01-abc123-introduction.mp4"
        cached.touch()

        fresh_path = tmp_path / "raw" / "test-course" / "02-def456-deep-dive.mp4"
        mock_download.return_value = fresh_path

        result = p.run_download()

        assert result[0] == cached
        assert result[1] == fresh_path
        mock_download.assert_called_once()  # only second video downloaded

    @patch("skillbill.pipeline.download_video")
    def test_download_rejects_stale_cache(self, mock_download, tmp_path, sample_manifest):
        """Cached file with wrong video ID triggers re-download."""
        p = Pipeline(data_dir=tmp_path)
        p.manifest = sample_manifest

        # Create cached file with a WRONG video ID for slot 01
        cache_dir = tmp_path / "raw" / "test-course"
        cache_dir.mkdir(parents=True)
        stale = cache_dir / "01-oldvid99-introduction.mp4"
        stale.touch()

        fresh_path_1 = cache_dir / "01-abc123-introduction.mp4"
        fresh_path_2 = cache_dir / "02-def456-deep-dive.mp4"
        mock_download.side_effect = [fresh_path_1, fresh_path_2]

        result = p.run_download()

        assert result[0] == fresh_path_1
        assert result[1] == fresh_path_2
        assert mock_download.call_count == 2  # both videos downloaded

    @patch("skillbill.pipeline.build_screenshot_plan")
    @patch("skillbill.pipeline.compute_speech_density")
    @patch("skillbill.pipeline.detect_scenes")
    def test_screenshot_planning_skips_none_paths(
        self, mock_scenes, mock_density, mock_plan, tmp_path, sample_manifest
    ):
        """Screenshot planning skips videos with no downloaded file."""
        valid_path = tmp_path / "video.mp4"
        valid_path.touch()
        mock_scenes.return_value = []
        mock_density.return_value = []
        mock_plan.return_value = {
            "video_id": "def456", "screenshots": [{"timestamp": 1.0}], "total_screenshots": 1,
        }

        p = Pipeline(data_dir=tmp_path)
        p.manifest = sample_manifest
        p.transcripts = [
            {"video_id": "abc123", "has_transcript": True, "entries": [{"start": 0, "duration": 1, "text": "hi"}]},
            {"video_id": "def456", "has_transcript": True, "entries": [{"start": 0, "duration": 1, "text": "hi"}]},
        ]

        result = p.run_screenshot_planning([None, valid_path])

        assert result[0] == {"video_id": "abc123", "screenshots": []}
        assert result[1]["video_id"] == "def456"
        mock_plan.assert_called_once()

    def test_capture_skips_none_paths(self, tmp_path, sample_manifest):
        """Capture stage skips videos with no downloaded file."""
        p = Pipeline(data_dir=tmp_path)
        p.manifest = sample_manifest
        p.screenshot_plans = [
            {"video_id": "abc123", "screenshots": [{"timestamp": 1.0}]},
            {"video_id": "def456", "screenshots": []},
        ]

        result = p.run_capture([None, tmp_path / "video.mp4"])

        assert result[0] == []
        assert result[1] == []


class TestPipelineSegmentIntegration:
    @patch("skillbill.pipeline.capture_screenshots")
    def test_passes_segment_thresholds(self, mock_capture, tmp_path, sample_manifest):
        """run_capture passes DEDUP_THRESHOLDS as segment_thresholds."""
        from skillbill.config import DEDUP_THRESHOLDS

        mock_capture.return_value = [
            {"timestamp": 10.0, "path": "/img.png", "status": "kept", "reason": "scene_change", "segment_type": "code-demo"},
        ]

        p = Pipeline(data_dir=tmp_path)
        p.manifest = sample_manifest
        p.screenshot_plans = [
            {"video_id": "abc123", "screenshots": [{"timestamp": 10.0, "reason": "scene_change", "segment_type": "code-demo"}]},
            {"video_id": "def456", "screenshots": []},
        ]

        video_path = tmp_path / "video.mp4"
        video_path.touch()
        p.run_capture([video_path, tmp_path / "v2.mp4"])

        # Verify segment_thresholds was passed
        call_kwargs = mock_capture.call_args[1]
        assert "segment_thresholds" in call_kwargs
        assert call_kwargs["segment_thresholds"] == DEDUP_THRESHOLDS

    def test_generation_carries_segment_type(self, tmp_path, sample_manifest):
        """run_generation includes segment_type in screenshot data."""
        p = Pipeline(data_dir=tmp_path)
        p.manifest = sample_manifest
        p.transcripts = [
            {"video_id": "abc123", "has_transcript": True, "entries": [{"start": 0, "duration": 1, "text": "hi"}], "chapters": [], "description": ""},
            {"video_id": "def456", "has_transcript": True, "entries": [{"start": 0, "duration": 1, "text": "hello"}], "chapters": [], "description": ""},
        ]
        p.capture_results = [
            [{"timestamp": 10.0, "path": str(tmp_path / "img.png"), "status": "kept", "reason": "scene_change", "segment_type": "code-demo"}],
            [],
        ]

        # We can't easily check the intermediate screenshots dict, but we can
        # verify the pipeline runs without error with segment_type present
        with patch("skillbill.pipeline.generate_video_markdown") as mock_gen, \
             patch("skillbill.pipeline.generate_course_index"):
            mock_gen.return_value = "# Test\n"
            p.run_generation()

            # Check that screenshots passed to generate_video_markdown have segment_type
            call_kwargs = mock_gen.call_args_list[0][1]
            if call_kwargs["screenshots"]:
                assert "segment_type" in call_kwargs["screenshots"][0]


class TestPipelineRefinement:
    def test_refine_flag_defaults_false(self, tmp_path):
        p = Pipeline(data_dir=tmp_path)
        assert p.refine is False

    def test_refine_flag_accepted(self, tmp_path):
        p = Pipeline(data_dir=tmp_path, refine=True)
        assert p.refine is True

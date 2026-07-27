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

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
                    "duration": 600,
                },
            ],
        }

        result = discover_playlist("https://youtube.com/playlist?list=PLtest")

        assert result["playlist_title"] == "Test Playlist"
        assert len(result["videos"]) == 1
        assert result["videos"][0]["id"] == "abc123"
        assert result["videos"][0]["url"] == "https://www.youtube.com/watch?v=abc123"
        assert result["videos"][0]["description"] == ""
        assert result["videos"][0]["chapters"] == []

    @patch("skillbill.downloader.yt_dlp.YoutubeDL")
    def test_flat_extraction_always_sets_empty_chapters(self, mock_ydl_class):
        """Flat extraction never includes chapters — verify they default to []."""
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
                    "duration": 600,
                },
            ],
        }

        result = discover_playlist("https://youtube.com/playlist?list=PLtest")
        assert result["videos"][0]["chapters"] == []
        assert result["videos"][0]["description"] == ""


class TestDiscoverSingleVideo:
    """A bare video URL has no `entries` — it becomes a one-item course."""

    @patch("skillbill.downloader.yt_dlp.YoutubeDL")
    def test_single_video_becomes_one_item_course(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "id": "solo123",
            "title": "Standalone Lesson",
            "webpage_url": "https://www.youtube.com/watch?v=solo123",
            "duration": 900,
            "description": "A single video.",
            "chapters": [{"title": "Intro", "start_time": 0}],
        }

        result = discover_playlist("https://www.youtube.com/watch?v=solo123")

        assert result["video_count"] == 1
        assert result["playlist_title"] == "Standalone Lesson"
        assert result["slug"] == "standalone-lesson"
        video = result["videos"][0]
        assert video["id"] == "solo123"
        assert video["url"] == "https://www.youtube.com/watch?v=solo123"
        assert video["duration"] == 900
        # Single-video extraction carries real chapters and description.
        assert video["description"] == "A single video."
        assert video["chapters"] == [{"title": "Intro", "start_time": 0}]

    @patch("skillbill.downloader.yt_dlp.YoutubeDL")
    def test_empty_playlist_yields_no_videos(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"title": "Empty Playlist", "entries": []}

        result = discover_playlist("https://youtube.com/playlist?list=PLempty")

        assert result["video_count"] == 0
        assert result["videos"] == []


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
                    "duration": 600,
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

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
    _parse_vtt,
    _dedup_entries,
    _vtt_timestamp_to_seconds,
    _extract_subtitles_browser,
)


SAMPLE_VTT = """\
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:03.000
Hello world

00:00:03.000 --> 00:00:07.000
Welcome to the course
"""

SAMPLE_VTT_WITH_TAGS = """\
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:03.000 align:start position:0%
<c.colorCCCCCC>Hello</c><c> world</c>

00:00:03.000 --> 00:00:07.000
<b>Welcome</b> to the <c.colorCCCCCC>course</c>
"""

SAMPLE_VTT_WITH_TIMESTAMPS = """\
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:03.000
<00:00:00.000>Hello <00:00:01.500>world

00:00:03.000 --> 00:00:07.000
<00:00:03.000>Welcome <00:00:05.000>to the course
"""


class TestParseVtt:
    def test_basic_parsing(self):
        entries = _parse_vtt(SAMPLE_VTT)
        assert len(entries) == 2
        assert entries[0]["start"] == 0.0
        assert entries[0]["duration"] == 3.0
        assert entries[0]["text"] == "Hello world"
        assert entries[1]["start"] == 3.0
        assert entries[1]["duration"] == 4.0
        assert entries[1]["text"] == "Welcome to the course"

    def test_strips_vtt_tags(self):
        entries = _parse_vtt(SAMPLE_VTT_WITH_TAGS)
        assert len(entries) == 2
        assert entries[0]["text"] == "Hello world"
        assert entries[1]["text"] == "Welcome to the course"

    def test_strips_positioning_timestamps(self):
        entries = _parse_vtt(SAMPLE_VTT_WITH_TIMESTAMPS)
        assert len(entries) == 2
        assert entries[0]["text"] == "Hello world"
        assert entries[1]["text"] == "Welcome to the course"

    def test_empty_content(self):
        entries = _parse_vtt("WEBVTT\n\n")
        assert entries == []

    def test_hour_timestamps(self):
        vtt = """\
WEBVTT

01:02:03.456 --> 01:02:07.456
Long video text
"""
        entries = _parse_vtt(vtt)
        assert len(entries) == 1
        assert entries[0]["start"] == pytest.approx(3723.456, abs=0.001)
        assert entries[0]["duration"] == pytest.approx(4.0, abs=0.001)


class TestDedupEntries:
    def test_removes_consecutive_duplicates(self):
        entries = [
            {"start": 0.0, "duration": 2.0, "text": "Hello"},
            {"start": 2.0, "duration": 2.0, "text": "Hello"},
            {"start": 4.0, "duration": 2.0, "text": "World"},
        ]
        result = _dedup_entries(entries)
        assert len(result) == 2
        assert result[0]["text"] == "Hello"
        assert result[1]["text"] == "World"

    def test_keeps_non_consecutive_duplicates(self):
        entries = [
            {"start": 0.0, "duration": 2.0, "text": "Hello"},
            {"start": 2.0, "duration": 2.0, "text": "World"},
            {"start": 4.0, "duration": 2.0, "text": "Hello"},
        ]
        result = _dedup_entries(entries)
        assert len(result) == 3

    def test_empty_list(self):
        assert _dedup_entries([]) == []

    def test_single_entry(self):
        entries = [{"start": 0.0, "duration": 2.0, "text": "Hello"}]
        assert _dedup_entries(entries) == entries


class TestVttTimestamp:
    def test_hms(self):
        assert _vtt_timestamp_to_seconds("00:01:23.456") == pytest.approx(83.456)

    def test_ms(self):
        assert _vtt_timestamp_to_seconds("01:23.456") == pytest.approx(83.456)

    def test_hours(self):
        assert _vtt_timestamp_to_seconds("01:00:00.000") == 3600.0


class TestCaching:
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_uses_cached_transcript(self, mock_extract, tmp_data_dir):
        """Cache hit: should return cached data without calling yt-dlp."""
        cache_dir = tmp_data_dir / "processed" / "test-course"
        cache_dir.mkdir(parents=True)
        cached = {
            "video_id": "abc123",
            "has_transcript": True,
            "entries": [{"start": 0.0, "duration": 3.0, "text": "Cached text"}],
            "word_count": 2,
            "duration": 3.0,
        }
        (cache_dir / "abc123-transcript.json").write_text(json.dumps(cached))

        result = fetch_transcript(
            "abc123", output_dir=tmp_data_dir / "processed", course_slug="test-course",
        )
        assert result["entries"][0]["text"] == "Cached text"
        mock_extract.assert_not_called()

    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_ignores_failed_cache(self, mock_extract, tmp_data_dir):
        """Cache with has_transcript=False should be ignored (re-fetched)."""
        cache_dir = tmp_data_dir / "processed" / "test-course"
        cache_dir.mkdir(parents=True)
        failed = {
            "video_id": "abc123",
            "has_transcript": False,
            "entries": [],
            "word_count": 0,
            "duration": 0,
        }
        (cache_dir / "abc123-transcript.json").write_text(json.dumps(failed))

        mock_extract.return_value = (
            [{"start": 0.0, "duration": 3.0, "text": "Fresh text"}],
            {"chapters": [], "description": ""},
        )

        result = fetch_transcript(
            "abc123", output_dir=tmp_data_dir / "processed", course_slug="test-course",
        )
        assert result["has_transcript"] is True
        assert result["entries"][0]["text"] == "Fresh text"
        mock_extract.assert_called_once()

    @patch("skillbill.transcript._extract_subtitles_browser")
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_failure_not_cached_to_disk(self, mock_extract, mock_browser, tmp_data_dir):
        """Failed fetches should NOT be written to disk."""
        mock_extract.side_effect = Exception("429")
        mock_browser.side_effect = RuntimeError("Browser failed")

        result = fetch_transcript(
            "abc123", output_dir=tmp_data_dir / "processed", course_slug="test-course",
        )
        assert result["has_transcript"] is False
        path = tmp_data_dir / "processed" / "test-course" / "abc123-transcript.json"
        assert not path.exists()


class TestAdaptiveBackoff:
    @patch("skillbill.transcript._extract_subtitles_browser")
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_stops_after_consecutive_failures(self, mock_extract, mock_browser):
        """After 3 consecutive failures, skip remaining uncached videos."""
        mock_extract.side_effect = Exception("429")
        mock_browser.side_effect = RuntimeError("Browser failed")
        results = fetch_all_transcripts(
            ["a", "b", "c", "d", "e"], delay=0, max_consecutive_failures=3,
        )
        # Should call yt-dlp 3 times, then skip the rest
        assert mock_extract.call_count == 3
        assert len(results) == 5
        assert all(not r["has_transcript"] for r in results)

    @patch("skillbill.transcript._extract_subtitles_browser")
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_resets_counter_on_success(self, mock_extract, mock_browser):
        """A successful fetch resets the consecutive failure counter."""
        mock_extract.side_effect = [
            Exception("429"),
            Exception("429"),
            ([{"start": 0.0, "duration": 3.0, "text": "OK"}], {"chapters": [], "description": ""}),
            Exception("429"),
            Exception("429"),
        ]
        mock_browser.side_effect = RuntimeError("Browser failed")
        results = fetch_all_transcripts(
            ["a", "b", "c", "d", "e"], delay=0, max_consecutive_failures=3,
        )
        assert mock_extract.call_count == 5
        assert results[2]["has_transcript"] is True


class TestFetchTranscript:
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_returns_timestamped_entries(self, mock_extract):
        mock_extract.return_value = (
            [
                {"start": 0.0, "duration": 3.0, "text": "Hello world"},
                {"start": 3.0, "duration": 4.0, "text": "Welcome to the course"},
            ],
            {"chapters": [{"title": "Intro", "start_time": 0, "end_time": 7}], "description": "A course"},
        )

        result = fetch_transcript("abc123")
        assert len(result["entries"]) == 2
        assert result["entries"][0]["text"] == "Hello world"
        assert result["video_id"] == "abc123"
        assert result["has_transcript"] is True
        assert result["chapters"] == [{"title": "Intro", "start_time": 0, "end_time": 7}]
        assert result["description"] == "A course"

    @patch("skillbill.transcript._extract_subtitles_browser")
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_handles_no_transcript(self, mock_extract, mock_browser):
        mock_extract.side_effect = Exception("No transcript found")
        mock_browser.side_effect = RuntimeError("Browser failed")

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
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_saves_success_to_disk(self, mock_extract, tmp_data_dir):
        mock_extract.return_value = (
            [{"start": 0.0, "duration": 3.0, "text": "Hello"}],
            {"chapters": [], "description": ""},
        )

        result = fetch_transcript(
            "abc123",
            output_dir=tmp_data_dir / "processed",
            course_slug="test-course",
        )
        path = tmp_data_dir / "processed" / "test-course" / "abc123-transcript.json"
        assert path.exists()
        saved = json.loads(path.read_text())
        assert saved["has_transcript"] is True


class TestBrowserFallback:
    """Tests the fallback chain: yt-dlp → browser → failure."""

    @patch("skillbill.transcript._extract_subtitles_browser")
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_ytdlp_success_skips_browser(self, mock_ytdlp, mock_browser):
        """When yt-dlp succeeds, browser fallback is not called."""
        mock_ytdlp.return_value = (
            [{"start": 0.0, "duration": 3.0, "text": "Hello"}],
            {"chapters": [], "description": ""},
        )

        result = fetch_transcript("abc123")
        assert result["has_transcript"] is True
        mock_browser.assert_not_called()

    @patch("skillbill.transcript._extract_subtitles_browser")
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_falls_back_to_browser_on_ytdlp_failure(self, mock_ytdlp, mock_browser):
        """When yt-dlp fails, browser fallback is tried and succeeds."""
        mock_ytdlp.side_effect = Exception("429 rate limited")
        mock_browser.return_value = (
            [{"start": 0.0, "duration": 5.0, "text": "Browser transcript"}],
            {"chapters": [], "description": ""},
        )

        result = fetch_transcript("abc123")
        assert result["has_transcript"] is True
        assert result["entries"][0]["text"] == "Browser transcript"
        mock_browser.assert_called_once_with("abc123")

    @patch("skillbill.transcript._extract_subtitles_browser")
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_both_fail_returns_no_transcript(self, mock_ytdlp, mock_browser):
        """When both yt-dlp and browser fail, returns has_transcript=False."""
        mock_ytdlp.side_effect = Exception("429")
        mock_browser.side_effect = RuntimeError("Browser failed")

        result = fetch_transcript("abc123")
        assert result["has_transcript"] is False
        assert result["entries"] == []

    @patch("skillbill.transcript._extract_subtitles_browser")
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_browser_fallback_result_is_cached(self, mock_ytdlp, mock_browser, tmp_data_dir):
        """Browser fallback success gets cached to disk."""
        mock_ytdlp.side_effect = Exception("429")
        mock_browser.return_value = (
            [{"start": 0.0, "duration": 5.0, "text": "From browser"}],
            {"chapters": [], "description": ""},
        )

        result = fetch_transcript(
            "abc123", output_dir=tmp_data_dir / "processed", course_slug="test-course",
        )
        assert result["has_transcript"] is True
        path = tmp_data_dir / "processed" / "test-course" / "abc123-transcript.json"
        assert path.exists()
        saved = json.loads(path.read_text())
        assert saved["entries"][0]["text"] == "From browser"

    @patch("skillbill.transcript._extract_subtitles_browser")
    @patch("skillbill.transcript._extract_subtitles_ytdlp")
    def test_browser_not_installed_graceful_failure(self, mock_ytdlp, mock_browser):
        """If Playwright isn't installed, fails gracefully."""
        mock_ytdlp.side_effect = Exception("429")
        mock_browser.side_effect = RuntimeError("Playwright is not installed")

        result = fetch_transcript("abc123")
        assert result["has_transcript"] is False
        assert result["entries"] == []


class TestExtractSubtitlesBrowser:
    """Tests _extract_subtitles_browser directly with mocked Playwright."""

    @patch("skillbill.transcript.sync_playwright")
    def test_extracts_segments_from_dom(self, mock_sp):
        """Mock page.evaluate returns raw segments → verify conversion."""
        mock_page = MagicMock()
        mock_browser = MagicMock()
        mock_pw = MagicMock()

        mock_sp.return_value.__enter__ = MagicMock(return_value=mock_pw)
        mock_sp.return_value.__exit__ = MagicMock(return_value=False)
        mock_pw.chromium.launch.return_value = mock_browser
        mock_browser.new_page.return_value = mock_page

        # Mock page.evaluate to return raw DOM segment data
        mock_page.evaluate.return_value = [
            {"startMs": "0", "endMs": "3000", "text": "Hello world"},
            {"startMs": "3000", "endMs": "7000", "text": "Welcome"},
        ]

        entries, metadata = _extract_subtitles_browser("abc123")
        assert len(entries) == 2
        assert entries[0] == {"start": 0.0, "duration": 3.0, "text": "Hello world"}
        assert entries[1] == {"start": 3.0, "duration": 4.0, "text": "Welcome"}
        assert metadata == {"chapters": [], "description": ""}

    @patch("skillbill.transcript.sync_playwright")
    def test_raises_when_no_transcript_button(self, mock_sp):
        """If 'Show transcript' click fails, raises RuntimeError."""
        mock_page = MagicMock()
        mock_browser = MagicMock()
        mock_pw = MagicMock()

        mock_sp.return_value.__enter__ = MagicMock(return_value=mock_pw)
        mock_sp.return_value.__exit__ = MagicMock(return_value=False)
        mock_pw.chromium.launch.return_value = mock_browser
        mock_browser.new_page.return_value = mock_page

        # "Show transcript" button click raises
        mock_page.get_by_role.return_value.click.side_effect = [
            None,  # ...more button succeeds
            Exception("Timeout"),  # Show transcript fails
        ]

        with pytest.raises(RuntimeError, match="No transcript available"):
            _extract_subtitles_browser("abc123")

    @patch("skillbill.transcript.sync_playwright")
    def test_raises_when_no_segments(self, mock_sp):
        """Transcript panel opens but is empty → raises RuntimeError."""
        mock_page = MagicMock()
        mock_browser = MagicMock()
        mock_pw = MagicMock()

        mock_sp.return_value.__enter__ = MagicMock(return_value=mock_pw)
        mock_sp.return_value.__exit__ = MagicMock(return_value=False)
        mock_pw.chromium.launch.return_value = mock_browser
        mock_browser.new_page.return_value = mock_page

        # evaluate returns empty list
        mock_page.evaluate.return_value = []

        with pytest.raises(RuntimeError, match="Transcript panel empty"):
            _extract_subtitles_browser("abc123")

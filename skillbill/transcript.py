"""Stage 2: Transcript extraction via yt-dlp subtitle download."""
import json
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

import yt_dlp

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def _vtt_timestamp_to_seconds(ts: str) -> float:
    """Parse a VTT timestamp like '00:01:23.456' into seconds."""
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    else:
        return float(parts[0])


def _parse_vtt(vtt_content: str) -> list[dict]:
    """Parse WebVTT content into [{start, duration, text}, ...].

    Strips VTT formatting tags (<c>, <b>, positioning info, etc.)
    and combines cue text into single entries.
    """
    entries = []
    # Match VTT cue blocks: timestamp line followed by text lines
    cue_pattern = re.compile(
        r"(\d[\d:.]+)\s*-->\s*(\d[\d:.]+)[^\n]*\n((?:(?!(?:\d[\d:.]+\s*-->|\n\n)).+\n?)+)",
        re.MULTILINE,
    )

    for match in cue_pattern.finditer(vtt_content):
        start_ts, end_ts, raw_text = match.group(1), match.group(2), match.group(3)

        start = _vtt_timestamp_to_seconds(start_ts)
        end = _vtt_timestamp_to_seconds(end_ts)
        duration = round(end - start, 3)

        # Strip VTT tags: <c>, </c>, <b>, </b>, <00:01:23.456>, positioning, etc.
        text = re.sub(r"<[^>]+>", "", raw_text)
        # Collapse whitespace and strip
        text = " ".join(text.split()).strip()

        if text and duration >= 0:
            entries.append({"start": round(start, 3), "duration": duration, "text": text})

    return entries


def _dedup_entries(entries: list[dict]) -> list[dict]:
    """Remove consecutive duplicate text entries (common in auto-generated subs)."""
    if not entries:
        return entries

    deduped = [entries[0]]
    for entry in entries[1:]:
        if entry["text"] != deduped[-1]["text"]:
            deduped.append(entry)
    return deduped


def strip_vtt_overlaps(entries: list[dict]) -> list[dict]:
    """Strip overlapping text from YouTube auto-generated VTT entries.

    YouTube's auto-generated VTT uses a scrolling two-line format where each
    cue contains the previous line plus a new line, like:
        [1.0] "All right today we're going to talk"
        [3.0] "All right today we're going to talk about MCPs"
        [6.7] "about MCPs"
        [6.8] "about MCPs Uh MCP stands for model"
        ...
    This causes every phrase to appear ~3 times when entries are concatenated.

    This function detects the overlap (entry starting with previous entry's text)
    and keeps only the unique new text from each entry.
    """
    if len(entries) < 2:
        return entries

    result = [entries[0]]
    for entry in entries[1:]:
        prev_text = result[-1]["text"]
        curr_text = entry["text"]

        if curr_text.startswith(prev_text):
            # Current entry contains the previous text plus new content
            new_part = curr_text[len(prev_text):].strip()
            if new_part:
                result.append({**entry, "text": new_part})
            # else: pure overlap with no new text — drop
        elif curr_text == prev_text:
            # Exact duplicate — drop
            pass
        else:
            # No overlap — keep as is
            result.append(entry)

    return result


def _extract_subtitles_ytdlp(
    url: str, languages: list[str] | None = None,
    cookies_from: Optional[str] = None,
) -> tuple[list[dict], dict]:
    """Use yt-dlp to download subtitles and parse into entry format.

    Tries manual subtitles first, falls back to auto-generated.
    Also captures chapters and description from the same extract_info() call
    (zero additional API requests).

    Returns (entries, metadata) where entries is list of {start, duration, text}
    dicts and metadata has {"chapters": [...], "description": "..."}.
    """
    if languages is None:
        languages = ["en"]

    with tempfile.TemporaryDirectory() as tmpdir:
        outtmpl = str(Path(tmpdir) / "%(id)s.%(ext)s")
        ydl_opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": languages,
            "subtitlesformat": "vtt",
            "skip_download": True,
            "ignore_no_formats_error": True,
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
        }
        if cookies_from:
            ydl_opts["cookiesfrombrowser"] = (cookies_from,)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Capture chapters and description from the info dict we already have
        metadata = {
            "chapters": info.get("chapters") or [],
            "description": info.get("description") or "",
        }

        # Find the VTT file that was written
        tmppath = Path(tmpdir)
        vtt_files = list(tmppath.glob("*.vtt"))
        if not vtt_files:
            raise FileNotFoundError(f"No subtitle file found for {url}")

        # Prefer manual subs (shorter filename) over auto-generated
        vtt_files.sort(key=lambda f: len(f.name))
        vtt_content = vtt_files[0].read_text(encoding="utf-8")

    entries = _parse_vtt(vtt_content)
    entries = _dedup_entries(entries)
    entries = strip_vtt_overlaps(entries)
    return entries, metadata


def _extract_subtitles_browser(video_id: str) -> tuple[list[dict], dict]:
    """Use Playwright headless browser to scrape YouTube's transcript panel.

    Fallback for when yt-dlp is rate-limited (HTTP 429). Opens the video page,
    expands the description, clicks "Show transcript", and extracts segments
    from the DOM.

    Returns (entries, metadata) tuple. Browser fallback cannot extract chapters
    or description, so metadata has empty values.
    """
    if sync_playwright is None:
        raise RuntimeError("Playwright is not installed")

    browser = None
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(
                f"https://www.youtube.com/watch?v={video_id}",
                wait_until="domcontentloaded",
            )

            # Dismiss cookie consent dialog if present
            try:
                consent_btn = page.locator('button:has-text("Accept all")')
                consent_btn.click(timeout=3000)
            except Exception:
                pass

            # Expand description to reveal "Show transcript" button
            try:
                more_btn = page.get_by_role("button", name="...more")
                more_btn.click(timeout=10000)
            except Exception:
                raise RuntimeError(f"Could not expand description for {video_id}")

            # Click "Show transcript"
            try:
                transcript_btn = page.get_by_role("button", name="Show transcript")
                transcript_btn.click(timeout=10000)
            except Exception:
                raise RuntimeError(f"No transcript available for {video_id}")

            # Wait for transcript segments to load
            page.wait_for_selector(
                "ytd-transcript-segment-renderer", timeout=10000,
            )

            # Extract segment data from DOM element properties
            raw_segments = page.evaluate("""
                () => {
                    const segments = document.querySelectorAll(
                        'ytd-transcript-segment-renderer'
                    );
                    return Array.from(segments).map(seg => ({
                        startMs: seg.data?.startMs,
                        endMs: seg.data?.endMs,
                        text: (seg.data?.snippet?.runs || [])
                            .map(r => r.text).join('')
                    }));
                }
            """)

            if not raw_segments:
                raise RuntimeError(f"Transcript panel empty for {video_id}")

            entries = []
            for seg in raw_segments:
                start_ms = seg.get("startMs")
                end_ms = seg.get("endMs")
                text = (seg.get("text") or "").strip()
                if start_ms is None or end_ms is None or not text:
                    continue
                start = int(start_ms) / 1000.0
                end = int(end_ms) / 1000.0
                duration = round(end - start, 3)
                entries.append({
                    "start": round(start, 3),
                    "duration": duration,
                    "text": text,
                })

            entries = _dedup_entries(entries)
            return entries, {"chapters": [], "description": ""}
        finally:
            if browser:
                browser.close()


def _load_cached_transcript(
    video_id: str, output_dir: Path, course_slug: str,
) -> dict | None:
    """Return cached transcript if it exists and has content, else None."""
    path = output_dir / course_slug / f"{video_id}-transcript.json"
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("has_transcript"):
            return cached
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def fetch_transcript(
    video_id: str,
    languages: list[str] | None = None,
    output_dir: Optional[Path] = None,
    course_slug: Optional[str] = None,
    cookies_from: Optional[str] = None,
) -> dict:
    """Fetch timestamped transcript for a single video.

    Checks for a cached transcript with content first. Only caches successful
    fetches so that rate-limit failures don't poison the cache.
    Returns dict with video_id, has_transcript, entries, and word_count.
    """
    if languages is None:
        languages = ["en"]

    # Check cache first
    if output_dir is not None and course_slug is not None:
        cached = _load_cached_transcript(video_id, output_dir, course_slug)
        if cached is not None:
            print(f"  Using cached transcript for {video_id}")
            return cached

    url = f"https://www.youtube.com/watch?v={video_id}"
    entries = None
    metadata = {"chapters": [], "description": ""}

    # Stage 1: yt-dlp
    try:
        entries, metadata = _extract_subtitles_ytdlp(url, languages=languages, cookies_from=cookies_from)
    except Exception as e:
        print(f"  yt-dlp failed for {video_id}: {type(e).__name__}. Trying browser fallback...")

    # Stage 2: browser (only if yt-dlp failed)
    if entries is None:
        try:
            entries, metadata = _extract_subtitles_browser(video_id)
            print(f"  Browser fallback succeeded for {video_id}")
        except Exception as e:
            print(f"  Browser fallback also failed for {video_id}: {type(e).__name__}")

    # Build result from entries (or lack thereof)
    if entries:
        word_count = sum(len(e["text"].split()) for e in entries)
        result = {
            "video_id": video_id,
            "has_transcript": True,
            "entries": entries,
            "word_count": word_count,
            "duration": entries[-1]["start"] + entries[-1]["duration"] if entries else 0,
            "chapters": metadata.get("chapters", []),
            "description": metadata.get("description", ""),
        }
    else:
        result = {
            "video_id": video_id,
            "has_transcript": False,
            "entries": [],
            "word_count": 0,
            "duration": 0,
            "chapters": [],
            "description": "",
        }

    # Only cache successful fetches
    if output_dir is not None and course_slug is not None and result["has_transcript"]:
        save_dir = output_dir / course_slug
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / f"{video_id}-transcript.json"
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    return result


def fetch_all_transcripts(
    video_ids: list[str],
    output_dir: Optional[Path] = None,
    course_slug: Optional[str] = None,
    delay: float = 2.0,
    cookies_from: Optional[str] = None,
    max_consecutive_failures: int = 3,
) -> list[dict]:
    """Fetch transcripts for all videos in a playlist.

    Uses cached transcripts when available. For uncached videos, adds a delay
    between requests and uses adaptive backoff: if max_consecutive_failures
    network fetches fail in a row, skips remaining uncached videos to avoid
    deepening an IP rate-limit block.
    """
    results = []
    consecutive_failures = 0
    rate_limited = False

    for i, vid in enumerate(video_ids):
        # If rate-limited, only serve from cache
        if rate_limited:
            cached = None
            if output_dir is not None and course_slug is not None:
                cached = _load_cached_transcript(vid, output_dir, course_slug)
            if cached is not None:
                print(f"  Using cached transcript for {vid}")
                results.append(cached)
            else:
                print(f"  Skipping {vid} (rate-limited, no cache)")
                results.append({
                    "video_id": vid,
                    "has_transcript": False,
                    "entries": [],
                    "word_count": 0,
                    "duration": 0,
                })
            continue

        result = fetch_transcript(
            vid, output_dir=output_dir, course_slug=course_slug,
            cookies_from=cookies_from,
        )
        results.append(result)

        if result["has_transcript"]:
            consecutive_failures = 0
        else:
            # Only count as failure if it wasn't served from cache
            # (cache hits print "Using cached" and always have has_transcript=True)
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                print(f"  Rate limit detected ({consecutive_failures} consecutive failures). "
                      f"Skipping remaining uncached videos.")
                rate_limited = True

        if delay > 0 and i < len(video_ids) - 1 and not rate_limited:
            time.sleep(delay)

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

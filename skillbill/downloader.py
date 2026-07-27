"""Stage 1 & 3: YouTube playlist discovery and video download via yt-dlp."""
import re
import json
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

import yt_dlp

from skillbill.config import RAW_DIR, ensure_dirs


def normalize_playlist_url(url: str) -> str:
    """Convert watch?v=...&list=... URLs to proper playlist URLs.

    yt-dlp with extract_flat=True treats watch URLs as single videos,
    ignoring the playlist parameter. This normalizes the URL so discovery
    always sees the full playlist.
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    list_id = params.get("list", [None])[0]
    if list_id and "watch" in parsed.path:
        return f"https://www.youtube.com/playlist?list={list_id}"
    return url


def slugify_title(title: str) -> str:
    """Convert a title to a filesystem-safe slug."""
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def discover_playlist(
    url: str, output_dir: Optional[Path] = None, cookies_from: Optional[str] = None,
) -> dict:
    """Extract playlist metadata with a single flat request (no per-video calls).

    Uses extract_flat=True so yt-dlp fetches only the playlist page,
    not each individual video.  This means chapters and descriptions
    are not available, but both analyzer.py and generator.py already
    handle that gracefully.

    A bare video URL (no `list` parameter) is treated as a one-video
    course, so every downstream stage works unchanged.

    Returns a manifest dict with playlist info and per-video metadata.
    Optionally saves manifest.json to output_dir/<course-slug>/.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
    }
    if cookies_from:
        ydl_opts["cookiesfrombrowser"] = (cookies_from,)

    url = normalize_playlist_url(url)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    playlist_title = info.get("title", "Untitled Playlist")
    entries = info.get("entries")

    # A single-video URL has no entries — wrap the video itself so the
    # rest of the pipeline sees a one-item course.
    if not entries:
        entries = [info] if info.get("id") else []

    videos = []
    for entry in entries:
        if entry is None:
            continue
        vid = entry.get("id", "")
        videos.append({
            "id": vid,
            # Flat playlist entries carry no description or chapters; a
            # single-video extraction does, so pass them through when present.
            "title": entry.get("title", "Untitled"),
            "description": entry.get("description") or "",
            "duration": entry.get("duration", 0),
            "chapters": entry.get("chapters") or [],
            "url": f"https://www.youtube.com/watch?v={vid}",
        })

    manifest = {
        "playlist_title": playlist_title,
        "playlist_url": info.get("webpage_url", url),
        "slug": slugify_title(playlist_title),
        "video_count": len(videos),
        "videos": videos,
    }

    if output_dir is not None:
        course_dir = output_dir / manifest["slug"]
        course_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = course_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    return manifest


def download_video(
    video_url: str, output_dir: Path, filename_prefix: str = "",
    cookies_from: Optional[str] = None,
) -> Path:
    """Download a single video file.

    Returns the path to the downloaded video file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    outtmpl = str(output_dir / f"{filename_prefix}%(title)s.%(ext)s")

    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
    }
    if cookies_from:
        ydl_opts["cookiesfrombrowser"] = (cookies_from,)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        filename = ydl.prepare_filename(info)
        return Path(filename)

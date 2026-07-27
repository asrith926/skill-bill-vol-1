"""Stage 6: Markdown knowledge base generation."""
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from skillbill.config import TEMPLATES_DIR
from skillbill.downloader import slugify_title
from skillbill.transcript import strip_vtt_overlaps


def format_timestamp(seconds: float) -> str:
    """Format seconds into MM:SS or H:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def extract_urls_from_description(description: str) -> list[str]:
    """Extract URLs from a video description."""
    url_pattern = r'https?://[^\s<>"\')\]]*'
    return re.findall(url_pattern, description)


def _interleave_content(
    entries: list[dict],
    screenshots: list[dict],
) -> list[dict]:
    """Merge transcript entries and screenshots into a timeline of content blocks.

    Returns list of blocks:
      {"type": "text", "content": "..."}  — grouped consecutive transcript entries
      {"type": "screenshot", "caption": "...", "path": "..."}  — at timestamp position
    """
    # Build a unified timeline: (timestamp, sort_key, item)
    # sort_key: 0=text first, 1=screenshot second at same timestamp
    items = []
    for e in entries:
        items.append((e["start"], 0, ("text", e["text"])))
    for s in screenshots:
        if s.get("path"):
            caption = s.get("caption", s.get("reason", "Screenshot"))
            items.append((s["timestamp"], 1, ("screenshot", caption, s["path"])))

    items.sort(key=lambda x: (x[0], x[1]))

    # Group consecutive text items into single blocks
    blocks = []
    current_texts = []
    for _, _, data in items:
        if data[0] == "text":
            current_texts.append(data[1])
        else:
            if current_texts:
                blocks.append({"type": "text", "content": " ".join(current_texts)})
                current_texts = []
            blocks.append({"type": "screenshot", "caption": data[1], "path": data[2]})
    if current_texts:
        blocks.append({"type": "text", "content": " ".join(current_texts)})

    return blocks


def build_sections(
    transcript_entries: list[dict],
    chapters: list[dict],
    screenshots: list[dict],
) -> list[dict]:
    """Build content sections from transcript, chapters, and screenshots.

    If chapters exist, use them as section boundaries.
    Otherwise, create one continuous section.
    Screenshots are interleaved inline with transcript text by timestamp.
    """
    # Strip VTT scrolling overlaps from transcript entries (handles cached data too)
    transcript_entries = strip_vtt_overlaps(transcript_entries)

    if not chapters:
        # No chapters — single section
        if transcript_entries:
            content_blocks = _interleave_content(transcript_entries, screenshots)
        else:
            content_blocks = [
                {"type": "text", "content": "⚠ No transcript available for this video."}
            ]
        return [{
            "timestamp": format_timestamp(0),
            "heading": "Content",
            "content_blocks": content_blocks,
        }]

    sections = []
    for chapter in chapters:
        start = chapter.get("start_time", 0)
        end = chapter.get("end_time", float("inf"))
        title = chapter.get("title", "Section")

        # Collect transcript entries in this chapter range
        entries_in_chapter = [
            e for e in transcript_entries if start <= e["start"] < end
        ]
        # Collect screenshots in this chapter range
        chapter_screenshots = [
            s for s in screenshots
            if s.get("path") and start <= s["timestamp"] < end
        ]

        if entries_in_chapter:
            content_blocks = _interleave_content(entries_in_chapter, chapter_screenshots)
        elif not transcript_entries:
            content_blocks = [
                {"type": "text", "content": "⚠ No transcript available for this video."}
            ]
        else:
            # Empty chapter with screenshots only
            content_blocks = _interleave_content([], chapter_screenshots)

        sections.append({
            "timestamp": format_timestamp(start),
            "heading": title,
            "content_blocks": content_blocks,
        })

    return sections


def generate_video_markdown(
    video_title: str,
    course_title: str,
    video_number: int,
    total_videos: int,
    duration: float,
    video_url: str,
    transcript_entries: list[dict],
    chapters: list[dict],
    screenshots: list[dict],
    description: str = "",
    output_path: Path = None,
) -> str:
    """Generate a complete markdown file for a single video."""
    sections = build_sections(transcript_entries, chapters, screenshots)
    linked_urls = extract_urls_from_description(description)
    chapter_names = [c.get("title", "") for c in chapters] if chapters else []

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("video.md.j2")

    content = template.render(
        video_title=video_title,
        course_title=course_title,
        video_number=video_number,
        total_videos=total_videos,
        duration_formatted=format_timestamp(duration),
        video_url=video_url,
        chapters=chapter_names,
        sections=sections,
        linked_urls=linked_urls,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)

    return content


def generate_course_index(
    course_title: str,
    playlist_url: str,
    videos: list[dict],
    output_path: Path = None,
    generated_date: str = "",
) -> str:
    """Generate the course-level index.md."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("index.md.j2")

    video_entries = []
    for i, v in enumerate(videos, 1):
        slug = slugify_title(v["title"])
        video_entries.append({
            "number": i,
            "title": v["title"],
            "filename": f"{i:02d}-{slug}.md",
        })

    content = template.render(
        course_title=course_title,
        playlist_url=playlist_url,
        total_videos=len(videos),
        generated_date=generated_date,
        videos=video_entries,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)

    return content

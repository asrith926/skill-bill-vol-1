"""AI refinement module — Stage 7 of the pipeline.

Converts raw transcripts into clean lesson steps using Haiku with vision.
Also de-clickbaits video titles based on actual content.
"""
import base64
import json
import re
from pathlib import Path
from typing import Optional

from skillbill.config import SCREENSHOT_FILTER, ANTHROPIC_MODEL


def filter_screenshots(
    screenshots: list[dict],
    config: dict | None = None,
) -> list[dict]:
    """Filter screenshots to keep only those worth sending to Haiku.

    Keeps: slide_transition, scene_change, and verbal_cue screenshots
    (except those matching the verbal_cue_blocklist).
    Drops: section_start, interval_fallback, mid_section.
    """
    if not screenshots:
        return []

    cfg = config or SCREENSHOT_FILTER
    keep_reasons = set(cfg["keep_reasons"])
    drop_reasons = set(cfg["drop_reasons"])
    blocklist = cfg["verbal_cue_blocklist"]

    filtered = []
    for s in screenshots:
        reason = s.get("reason", "")

        # Explicit drop
        if reason in drop_reasons:
            continue

        # Explicit keep
        if reason in keep_reasons:
            filtered.append(s)
            continue

        # Verbal cue: keep unless blocklisted
        if reason.startswith("verbal_cue:"):
            cue_text = reason.split(":", 1)[1].strip()
            if cue_text in blocklist:
                continue
            filtered.append(s)
            continue

        # Unknown reason: keep (be generous)
        filtered.append(s)

    return filtered


import anthropic


def _call_haiku(
    messages: list[dict],
    api_key: str,
    max_tokens: int = 1024,
) -> str:
    """Make a single Haiku API call. Returns the text response."""
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        messages=messages,
    )
    return response.content[0].text


def refine_video_title(
    original_title: str,
    transcript_preview: str,
    api_key: str = "",
) -> str:
    """Generate a clean, descriptive title for a video.

    Uses Haiku to replace clickbaity YouTube titles with content-descriptive ones.
    Falls back to original title on error or missing API key.
    """
    if not api_key:
        return original_title

    # No content to base a title on — keep original
    if not transcript_preview or not transcript_preview.strip():
        return original_title

    prompt = (
        "The following YouTube video has a potentially clickbaity title. "
        "Generate a clean, descriptive title that accurately reflects the video's "
        "actual content. The title should be concise (5-10 words), professional, "
        "and useful for someone scanning a course index.\n\n"
        f'Original title: "{original_title}"\n'
        f'Content preview: "{transcript_preview[:500]}"\n\n'
        "Return ONLY the new title, nothing else."
    )

    try:
        result = _call_haiku(
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            max_tokens=100,
        )
        cleaned = result.strip()
        # Sanity check: reject if Haiku returned a refusal or absurdly long title
        if len(cleaned) > 80 or cleaned.lower().startswith("i cannot"):
            return original_title
        return cleaned
    except Exception:
        return original_title


def generate_skill_description(
    course_title: str,
    video_titles: list[str],
    api_key: str = "",
) -> str:
    """Generate an AI-crafted SKILL.md description for a course.

    Uses Haiku to create a description with contextual trigger phrases,
    following Anthropic's skill best practices.
    Returns empty string on error or missing API key.
    """
    if not api_key:
        return ""

    numbered_titles = "\n".join(f"{i+1}. {t}" for i, t in enumerate(video_titles))

    prompt = (
        "You are generating a YAML description field for a Claude Code skill file. "
        "The skill is a knowledge base from a YouTube course.\n\n"
        f'Course: "{course_title}"\n'
        f"Videos:\n{numbered_titles}\n\n"
        "Generate a description under 1024 characters that includes:\n"
        "1. What this knowledge base contains (1 sentence)\n"
        "2. Key topics covered (comma-separated)\n"
        "3. Trigger phrases — specific things a user might say that should "
        "activate this skill (3-5 phrases)\n\n"
        "Format: A single paragraph. No YAML markers, no quotes, no newlines.\n"
        "Return ONLY the description text, nothing else."
    )

    try:
        result = _call_haiku(
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            max_tokens=300,
        )
        return result.strip()
    except Exception:
        return ""


def _get_surrounding_transcript(
    entries: list[dict],
    timestamp: float,
    window_seconds: float = 15.0,
) -> str:
    """Return transcript text within ±window_seconds of a timestamp."""
    relevant = [
        e["text"] for e in entries
        if abs(e["start"] - timestamp) <= window_seconds
    ]
    return " ".join(relevant)


def caption_screenshot(
    path: str,
    surrounding_transcript: str,
    timestamp: float,
    video_title: str,
    api_key: str = "",
) -> str:
    """Generate a concise caption for a single screenshot using Haiku vision.

    Returns a caption string (under 15 words). Falls back to "Screenshot" on error.
    Cost: ~$0.005 per call.
    """
    if not api_key:
        return "Screenshot"

    try:
        img_data = Path(path).read_bytes()
        b64 = base64.b64encode(img_data).decode("utf-8")
    except Exception:
        return "Screenshot"

    minutes = int(timestamp // 60)
    seconds = int(timestamp % 60)

    content = [
        {
            "type": "text",
            "text": (
                "Describe what this screenshot shows in one concise sentence (under 15 words). "
                "Focus on the visual content (code, UI element, diagram, slide text), not the speaker. "
                f'Video: "{video_title}" at {minutes}:{seconds:02d}.\n'
                f'Surrounding transcript: "{surrounding_transcript[:300]}"\n'
                "Return ONLY the caption, nothing else."
            ),
        },
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64,
            },
        },
    ]

    try:
        result = _call_haiku(
            messages=[{"role": "user", "content": content}],
            api_key=api_key,
            max_tokens=60,
        )
        return result.strip()
    except Exception:
        return "Screenshot"


def _build_vision_content(
    transcript_text: str,
    video_title: str,
    duration: float,
    screenshot_paths: list[str],
    screenshot_rel_paths: list[str] | None = None,
    screenshot_captions: list[str] | None = None,
) -> list[dict]:
    """Build a multimodal content array for the Haiku vision call.

    Returns a list of content blocks: text prompt + image blocks for screenshots.
    Each image is labelled with its relative markdown path (and caption if provided)
    so the model can embed the correct reference.
    """
    duration_min = int(duration // 60)
    duration_sec = int(duration % 60)

    screenshot_rule = (
        "- You MUST embed ALL provided screenshots in your output. "
        "Place each screenshot at the most relevant step using the EXACT path from its label, "
        "e.g. ![caption](./assets/01/04-30.png). "
        "Do NOT skip any screenshot — every one must appear exactly once.\n"
        if screenshot_paths else ""
    )

    prompt_text = (
        "You are converting a YouTube video transcript into clean, actionable lesson steps.\n\n"
        f'Video: "{video_title}" ({duration_min}:{duration_sec:02d})\n\n'
        "Transcript:\n"
        f"{transcript_text}\n\n"
        "Produce ONLY numbered lesson steps in this format:\n\n"
        "1. **[Step/concept name]** — [1-2 sentence explanation]. "
        "[Code example if any, preserved exactly.]\n"
        "2. **[Step/concept name]** — ...\n\n"
        "Rules:\n"
        "- Extract actionable steps and key concepts, not summaries of what the speaker said\n"
        "- Preserve code examples, commands, and URLs exactly as spoken/shown\n"
        + screenshot_rule +
        "- Drop filler, repetition, tangents, and conversational speech\n"
        "- Keep technical accuracy — don't paraphrase technical terms\n"
        "- Target: 70-80% reduction in token count vs raw transcript\n"
    )

    content = [{"type": "text", "text": prompt_text}]

    rel_paths = screenshot_rel_paths or [None] * len(screenshot_paths)
    captions = screenshot_captions or [None] * len(screenshot_paths)

    # Add screenshots as vision inputs, each labelled with its path and caption
    for abs_path, rel_path, caption in zip(screenshot_paths, rel_paths, captions):
        try:
            img_data = Path(abs_path).read_bytes()
            b64 = base64.b64encode(img_data).decode("utf-8")
            if rel_path:
                label = f"Screenshot — use path: {rel_path}"
                if caption:
                    label += f" | caption: {caption}"
                content.append({"type": "text", "text": label})
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })
        except Exception:
            continue  # Skip unreadable screenshots

    return content


def refine_video_content(
    transcript_entries: list[dict],
    chapters: list[dict],
    filtered_screenshots: list[dict],
    video_title: str,
    duration: float,
    video_num: int = 0,
    api_key: str = "",
) -> str:
    """Refine a video's raw transcript into clean lesson steps.

    Uses Haiku with vision to process transcript + screenshots.
    Returns refined markdown string, or empty string on failure.
    """
    if not api_key:
        return ""

    # Build transcript text from entries
    if chapters:
        # Organize by chapter
        parts = []
        for chapter in chapters:
            start = chapter.get("start_time", 0)
            end = chapter.get("end_time", float("inf"))
            title = chapter.get("title", "Section")
            entries = [e for e in transcript_entries if start <= e["start"] < end]
            if entries:
                text = " ".join(e["text"] for e in entries)
                parts.append(f"[{title}]\n{text}")
        transcript_text = "\n\n".join(parts)
    else:
        transcript_text = " ".join(e["text"] for e in transcript_entries)

    # Collect screenshot file paths, relative KB paths, and captions
    screenshot_paths = []
    screenshot_rel_paths = []
    screenshot_captions = []
    for s in filtered_screenshots:
        abs_path = s.get("path", "")
        if abs_path and Path(abs_path).exists():
            screenshot_paths.append(abs_path)
            filename = Path(abs_path).name
            screenshot_rel_paths.append(f"./assets/{video_num:02d}/{filename}")
            screenshot_captions.append(s.get("caption", ""))

    # Build multimodal content
    content = _build_vision_content(
        transcript_text=transcript_text,
        video_title=video_title,
        duration=duration,
        screenshot_paths=screenshot_paths,
        screenshot_rel_paths=screenshot_rel_paths,
        screenshot_captions=screenshot_captions,
    )

    try:
        result = _call_haiku(
            messages=[{"role": "user", "content": content}],
            api_key=api_key,
            max_tokens=4096,
        )
        return result.strip()
    except Exception:
        return ""


def generate_topic_index(
    video_entries: list[dict],
    api_key: str = "",
) -> dict:
    """Generate a keyword→video+step topic index using Haiku.

    Args:
        video_entries: list of {"number": int, "title": str, "content": str}
        api_key: Anthropic API key

    Returns dict like {"topics": {"kubernetes": [{"video": 1, "step": 3}], ...}}.
    Returns empty dict on error or missing API key. Cost: ~$0.01/course.
    """
    if not api_key:
        return {}

    # Build a summary of all video content for the prompt
    video_summaries = []
    for v in video_entries:
        video_summaries.append(f"Video {v['number']}: {v['title']}\n{v['content'][:800]}")

    prompt = (
        "Analyze these video lesson summaries and create a topic index. "
        "Map 15-30 keywords/phrases to the specific video number and step number "
        "where that topic is covered.\n\n"
        + "\n\n---\n\n".join(video_summaries)
        + "\n\nReturn a JSON object with this exact structure:\n"
        '{"topics": {"keyword": [{"video": 1, "step": 3}], "another keyword": [{"video": 2, "step": 1}]}}\n\n'
        "Rules:\n"
        "- Use lowercase keywords\n"
        "- Include specific technical terms, tools, and concepts\n"
        "- A keyword can map to multiple video+step locations\n"
        "- Return ONLY the JSON, nothing else."
    )

    try:
        result = _call_haiku(
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            max_tokens=2000,
        )
        return json.loads(result.strip())
    except (json.JSONDecodeError, Exception):
        return {}


from skillbill.downloader import slugify_title
from skillbill.generator import format_timestamp
from datetime import date


def refine_course(
    course_dir: Path,
    manifest: dict,
    transcripts: list[dict],
    capture_results: list[list[dict]],
    api_key: str = "",
) -> Path:
    """Refine an entire course — clean titles + lesson extraction.

    Replaces raw transcript .md files with refined lesson .md files.
    Renames files with clean titles. Regenerates index.md.
    """
    videos = manifest["videos"]
    refined_video_entries = []

    for i, (video, transcript) in enumerate(zip(videos, transcripts)):
        video_num = i + 1
        original_title = video["title"]
        duration = video.get("duration") or 0

        # Step 1: Clean the title
        transcript_preview = ""
        if transcript.get("entries"):
            transcript_preview = " ".join(
                e["text"] for e in transcript["entries"][:20]
            )
        clean_title = refine_video_title(original_title, transcript_preview, api_key=api_key)

        # Step 2: Refine content (only if transcript exists)
        refined_content = ""
        if transcript.get("has_transcript") and transcript.get("entries"):
            # Filter screenshots for this video
            screenshots = []
            if i < len(capture_results):
                screenshots = [
                    r for r in capture_results[i]
                    if r.get("status") == "kept" and r.get("path")
                ]
            filtered = filter_screenshots(screenshots)

            # Caption each screenshot with Haiku vision
            for s in filtered:
                s_path = s.get("path", "")
                if s_path and Path(s_path).exists():
                    surrounding = _get_surrounding_transcript(
                        transcript["entries"], s["timestamp"],
                    )
                    s["caption"] = caption_screenshot(
                        path=s_path,
                        surrounding_transcript=surrounding,
                        timestamp=s["timestamp"],
                        video_title=clean_title,
                        api_key=api_key,
                    )

            refined_content = refine_video_content(
                transcript_entries=transcript["entries"],
                chapters=transcript.get("chapters") or video.get("chapters", []),
                filtered_screenshots=filtered,
                video_title=clean_title,
                duration=duration,
                video_num=video_num,
                api_key=api_key,
            )

        # Step 3: Build the refined markdown file
        clean_slug = slugify_title(clean_title)
        new_filename = f"{video_num:02d}-{clean_slug}.md"

        # Remove ALL existing files for this video number (handles re-runs
        # where Haiku generates different clean titles each time)
        for old_file in course_dir.glob(f"{video_num:02d}-*.md"):
            old_file.unlink()

        # Write new file
        duration_str = format_timestamp(duration)
        header = (
            f"# {clean_title}\n\n"
            f"**Course:** {manifest['playlist_title']}\n"
            f"**Video:** {video_num} of {manifest['video_count']}\n"
            f"**Duration:** {duration_str}\n"
            f"**Source:** {video['url']}\n\n"
            "---\n\n"
        )

        body = refined_content if refined_content else "No lessons generated for this video.\n"
        (course_dir / new_filename).write_text(header + body)

        refined_video_entries.append({
            "number": video_num,
            "title": clean_title,
            "filename": new_filename,
        })

    # Step 4: Regenerate index with clean titles
    index_lines = [
        f"# {manifest['playlist_title']} -- Course Index\n",
        f"\n**Source Playlist:** {manifest['playlist_url']}",
        f"\n**Videos:** {manifest['video_count']}",
        f"\n**Generated:** {date.today()}\n",
        "\n## Lessons\n",
    ]
    for entry in refined_video_entries:
        index_lines.append(
            f"\n{entry['number']}. [{entry['title']}](./{entry['filename']})"
        )
    (course_dir / "index.md").write_text("\n".join(index_lines) + "\n")

    # Step 5: Generate AI description for SKILL.md
    clean_titles = [entry["title"] for entry in refined_video_entries]
    ai_description = generate_skill_description(
        course_title=manifest["playlist_title"],
        video_titles=clean_titles,
        api_key=api_key,
    )
    if ai_description:
        skill_meta = {"ai_description": ai_description}
        (course_dir / ".skill_meta.json").write_text(
            json.dumps(skill_meta, ensure_ascii=False)
        )

    # Step 6: Generate topic index from refined content
    if api_key:
        topic_entries = []
        for entry in refined_video_entries:
            content_path = course_dir / entry["filename"]
            if content_path.exists():
                topic_entries.append({
                    "number": entry["number"],
                    "title": entry["title"],
                    "content": content_path.read_text(),
                })
        topic_index = generate_topic_index(topic_entries, api_key=api_key)
        if topic_index:
            (course_dir / "topics.json").write_text(
                json.dumps(topic_index, indent=2, ensure_ascii=False)
            )

    # Write marker file for Pro detection
    (course_dir / ".refined").write_text("")

    return course_dir

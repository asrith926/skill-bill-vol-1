"""Package a generated knowledge base as a downloadable Claude Code skill ZIP."""
import zipfile
from pathlib import Path


def generate_skill_md(
    course_title: str,
    course_slug: str,
    video_count: int,
    topics: list[str],
    video_files: list[str] | None = None,
    ai_description: str = "",
    is_refined: bool = False,
    has_topic_index: bool = False,
) -> str:
    """Generate a SKILL.md file following Anthropic's skill best practices.

    Args:
        course_title: Human-readable course title.
        course_slug: kebab-case slug used as skill name.
        video_count: Total number of videos.
        topics: List of video titles (used for topics list and examples).
        video_files: List of markdown filenames (e.g. ["01-intro.md", ...]).
        ai_description: Optional AI-generated description (Pro mode). If empty,
            a template-based description is used.
        is_refined: Whether the course was processed with AI refinement (Pro mode).
        has_topic_index: Whether a topics.json file exists for keyword lookup.
    """
    # --- Description ---
    if ai_description:
        description = ai_description
    else:
        topic_str = ", ".join(topics[:8]) if topics else course_title
        description = (
            f"Reference knowledge base from {course_title} ({video_count} videos) "
            f"covering {topic_str}. "
            f'Use when user asks about these topics, wants to reference video content, '
            f'or asks "what does the course say about [topic]?"'
        )

    # --- Topics list ---
    if len(topics) > 8:
        topic_lines = "\n".join(f"{i+1}. {t}" for i, t in enumerate(topics[:8]))
        topic_lines += f"\n\n... and {len(topics) - 8} more"
    else:
        topic_lines = "\n".join(f"{i+1}. {t}" for i, t in enumerate(topics))

    # --- Examples ---
    files = video_files or []
    examples = ""
    if topics and files:
        # Pick up to 3: first, middle, last
        indices = [0]
        if len(topics) > 2:
            indices.append(len(topics) // 2)
        if len(topics) > 1:
            indices.append(len(topics) - 1)

        example_parts = []
        for idx, i in enumerate(indices, 1):
            title = topics[i] if i < len(topics) else topics[-1]
            fname = files[i] if i < len(files) else files[-1]
            if is_refined:
                example_parts.append(
                    f'Example {idx}: "Tell me about {title}"\n'
                    f"1. Read index.md\n"
                    f"2. Find video {i+1}: {title}\n"
                    f"3. Read {fname}\n"
                    f"4. Find the relevant numbered lesson step\n"
                    f"5. Reference inline screenshots for visual context"
                )
            else:
                example_parts.append(
                    f'Example {idx}: "Tell me about {title}"\n'
                    f"1. Read index.md\n"
                    f"2. Find video {i+1}: {title}\n"
                    f"3. Read {fname}\n"
                    f"4. Navigate to relevant chapter headings"
                )
        examples = "\n\n".join(example_parts)
    elif topics:
        if is_refined:
            examples = (
                f'Example: "Tell me about {topics[0]}"\n'
                f"1. Read index.md\n"
                f"2. Find the relevant video\n"
                f"3. Read that video's markdown file\n"
                f"4. Find the relevant numbered lesson step"
            )
        else:
            examples = (
                f'Example: "Tell me about {topics[0]}"\n'
                f"1. Read index.md\n"
                f"2. Find the relevant video\n"
                f"3. Read that video's markdown file\n"
                f"4. Navigate to relevant chapter headings"
            )

    # --- How to Use (two-tier) ---
    if is_refined:
        topic_index_step = ""
        if has_topic_index:
            topic_index_step = """

### Step 0: Quick topic lookup (optional)

Read `topics.json` for a keyword-to-video+step mapping. Use this to jump directly to the right video and step number when the user asks about a specific concept.
"""

        how_to_use = f"""{topic_index_step}
### Step 1: Read the index

Read `index.md` for a numbered list of all {video_count} videos with links.

### Step 2: Read only the relevant video file

Each video file is 2-5K tokens of refined lesson steps. **Never load all files at once.** Read only the specific video relevant to the question.

### Step 3: Navigate by lesson step

Each video contains numbered lesson steps (e.g. `1. **Step Name** — explanation`). Reference the specific step number when answering. Inline screenshots with descriptive captions provide visual context — reference them when the visual adds value.

### Token Budget

Each file is compact (2-5K tokens). Load one file at a time. If the user needs information spanning multiple videos, load them sequentially."""
    else:
        how_to_use = f"""
### Step 1: Read the index

Read `index.md` for a numbered list of all {video_count} videos with links.

### Step 2: Read only the relevant video file

Each video file is 3-9K tokens. **Never load all files at once.** Read only the specific video relevant to the question.

### Step 3: Navigate by chapter

Each video file has chapter sections marked with `## [MM:SS] Chapter Title`. Use these to jump to the relevant section rather than reading the entire transcript."""

    # --- File Structure ---
    if is_refined:
        file_structure = """Each video file contains:
- **Metadata header** — course name, video number, duration, source URL
- **Numbered lesson steps** — `1. **Step Name** — explanation with code examples`
- **Inline captioned screenshots** — `![descriptive caption](./assets/NN/MM-SS.png)`"""
    else:
        file_structure = """Each video file contains:
- **Metadata header** — course name, video number, duration, source URL
- **Chapter sections** — `## [MM:SS] Chapter Title` with transcript text
- **Inline screenshots** — `![reason](./assets/NN/MM-SS.png)` (if generated with screenshots)
- **Linked Resources** — URLs from the video description"""

    return f"""---
name: {course_slug}
description: >
  {description}
metadata:
  author: Skill Bill
  version: "1.0"
  source: youtube-playlist
---

# {course_title}

## Topics Covered

{topic_lines}

## When to Use

- User asks about a topic covered in this course
- User wants to reference or quote specific video content
- User asks "what does the course say about [topic]?"
- User is building content related to these topics

## When NOT to Use

- User asks about topics not covered in this course
- User needs real-time or up-to-date information (this is a static knowledge base)
- User needs general knowledge not specific to this course

## How to Use
{how_to_use}

## Examples

{examples}

## File Structure

{file_structure}
"""


def package_course_as_zip(
    course_dir: Path,
    course_title: str,
    output_dir: Path,
) -> Path:
    """Bundle a knowledge base course into a downloadable ZIP.

    The ZIP contains SKILL.md + all markdown files + assets,
    ready to unzip into ~/.claude/skills/<course-slug>/.
    """
    import json

    course_slug = course_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{course_slug}.zip"

    # Count videos and extract topic hints from filenames
    md_files = sorted(course_dir.glob("*.md"))
    video_files = [f for f in md_files if f.name != "index.md"]
    video_count = len(video_files)

    # Extract ALL topics — generate_skill_md handles truncation
    topics = []
    for f in video_files:
        name = f.stem.split("-", 1)[-1] if "-" in f.stem else f.stem
        topics.append(name.replace("-", " "))

    video_filenames = [f.name for f in video_files]

    # Check for AI-generated description (Pro mode)
    ai_description = ""
    skill_meta_path = course_dir / ".skill_meta.json"
    if skill_meta_path.exists():
        try:
            meta = json.loads(skill_meta_path.read_text())
            ai_description = meta.get("ai_description", "")
        except Exception:
            pass

    # Detect refinement and topic index
    is_refined = (course_dir / ".refined").exists()
    has_topic_index = (course_dir / "topics.json").exists()

    skill_content = generate_skill_md(
        course_title, course_slug, video_count, topics,
        video_files=video_filenames,
        ai_description=ai_description,
        is_refined=is_refined,
        has_topic_index=has_topic_index,
    )

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add SKILL.md
        zf.writestr(f"{course_slug}/SKILL.md", skill_content)

        # Add all markdown files
        for md_file in md_files:
            zf.write(md_file, f"{course_slug}/{md_file.name}")

        # Add topics.json if it exists
        topics_json_path = course_dir / "topics.json"
        if topics_json_path.exists():
            zf.write(topics_json_path, f"{course_slug}/topics.json")

        # Add assets
        assets_dir = course_dir / "assets"
        if assets_dir.exists():
            for asset_file in assets_dir.rglob("*"):
                if asset_file.is_file():
                    rel = asset_file.relative_to(course_dir)
                    zf.write(asset_file, f"{course_slug}/{rel}")

    return zip_path

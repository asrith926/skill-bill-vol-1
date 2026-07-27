# Skill Best Practices Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade generated SKILL.md files to follow Anthropic's official skill building guide — trigger phrases, examples, topics, When to Use sections, metadata, and optional Haiku-generated descriptions in Pro mode.

**Architecture:** `skill_packager.py` is the single owner of SKILL.md assembly. It reads video titles from the course directory and checks for an optional `.skill_meta.json` sidecar file written by `refiner.py` in Pro mode. The packager uses a smart template for Base mode and slots in an AI-generated description for Pro mode.

**Tech Stack:** Python, pytest, unittest.mock, anthropic (Haiku for Pro descriptions)

---

### Task 1: Upgrade `generate_skill_md()` with the improved template

**Files:**
- Modify: `web/services/skill_packager.py:6-46`
- Test: `tests/test_skill_packager.py`

**Step 1: Write failing tests for the new template structure**

Add these tests to `tests/test_skill_packager.py`, inside `TestGenerateSkillMd`:

```python
def test_description_includes_trigger_phrases(self):
    content = generate_skill_md(
        course_title="Python Basics",
        course_slug="python-basics",
        video_count=10,
        topics=["variables", "functions", "loops"],
    )
    assert "Use when" in content
    assert "python-basics" in content

def test_contains_topics_section(self):
    content = generate_skill_md(
        course_title="Python Basics",
        course_slug="python-basics",
        video_count=3,
        topics=["variables", "functions", "loops"],
    )
    assert "## Topics Covered" in content
    assert "variables" in content
    assert "functions" in content
    assert "loops" in content

def test_contains_when_to_use(self):
    content = generate_skill_md(
        course_title="Test",
        course_slug="test",
        video_count=5,
        topics=["topic a"],
    )
    assert "## When to Use" in content
    assert "## When NOT to Use" in content

def test_contains_examples(self):
    content = generate_skill_md(
        course_title="Test Course",
        course_slug="test-course",
        video_count=3,
        topics=["intro", "advanced", "recap"],
        video_files=["01-intro.md", "02-advanced.md", "03-recap.md"],
    )
    assert "## Examples" in content
    assert "01-intro.md" in content

def test_contains_metadata(self):
    content = generate_skill_md(
        course_title="Test",
        course_slug="test",
        video_count=5,
        topics=[],
    )
    assert "metadata:" in content
    assert "author: Skill Bill" in content

def test_uses_ai_description_when_provided(self):
    ai_desc = "AI-crafted description with smart trigger phrases about Python."
    content = generate_skill_md(
        course_title="Python Basics",
        course_slug="python-basics",
        video_count=10,
        topics=["variables"],
        ai_description=ai_desc,
    )
    assert ai_desc in content
    # Should NOT contain the template description
    assert "Reference knowledge base from" not in content

def test_topics_truncated_at_8(self):
    topics = [f"topic-{i}" for i in range(12)]
    content = generate_skill_md(
        course_title="Big Course",
        course_slug="big-course",
        video_count=12,
        topics=topics,
    )
    assert "topic-7" in content       # 8th topic (0-indexed)
    assert "topic-8" not in content   # 9th topic should be truncated
    assert "and 4 more" in content
```

**Step 2: Run tests to verify they fail**

Run: `cd "Skill Bill" && python -m pytest tests/test_skill_packager.py::TestGenerateSkillMd -v`
Expected: Multiple FAIL (new tests fail because current template lacks these sections)

**Step 3: Rewrite `generate_skill_md()` with the improved template**

Replace the `generate_skill_md` function in `web/services/skill_packager.py` with:

```python
def generate_skill_md(
    course_title: str,
    course_slug: str,
    video_count: int,
    topics: list[str],
    video_files: list[str] | None = None,
    ai_description: str = "",
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
            example_parts.append(
                f'Example {idx}: "Tell me about {title}"\n'
                f"1. Read index.md\n"
                f"2. Find video {i+1}: {title}\n"
                f"3. Read {fname}\n"
                f"4. Navigate to relevant chapter headings"
            )
        examples = "\n\n".join(example_parts)
    elif topics:
        examples = (
            f'Example: "Tell me about {topics[0]}"\n'
            f"1. Read index.md\n"
            f"2. Find the relevant video\n"
            f"3. Read that video's markdown file\n"
            f"4. Navigate to relevant chapter headings"
        )

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

### Step 1: Read the index

Read `index.md` for a numbered list of all {video_count} videos with links.

### Step 2: Read only the relevant video file

Each video file is 3-9K tokens. **Never load all files at once.** Read only the specific video relevant to the question.

### Step 3: Navigate by chapter

Each video file has chapter sections marked with `## [MM:SS] Chapter Title`. Use these to jump to the relevant section rather than reading the entire transcript.

## Examples

{examples}

## File Structure

Each video file contains:
- **Metadata header** — course name, video number, duration, source URL
- **Chapter sections** — `## [MM:SS] Chapter Title` with transcript text
- **Inline screenshots** — `![reason](./assets/NN/MM-SS.png)` (if generated with screenshots)
- **Linked Resources** — URLs from the video description
"""
```

**Step 4: Run tests to verify they pass**

Run: `cd "Skill Bill" && python -m pytest tests/test_skill_packager.py::TestGenerateSkillMd -v`
Expected: All PASS

**Step 5: Commit**

```bash
cd "Skill Bill"
git add web/services/skill_packager.py tests/test_skill_packager.py
git commit -m "feat: upgrade SKILL.md template with Anthropic best practices

Adds trigger phrases, topics list, When to Use/NOT to Use sections,
example interactions, metadata block, and optional AI description."
```

---

### Task 2: Update `package_course_as_zip()` to pass video files and check for `.skill_meta.json`

**Files:**
- Modify: `web/services/skill_packager.py:49-92`
- Test: `tests/test_skill_packager.py`

**Step 1: Write failing tests**

Add to `TestPackageCourseAsZip` in `tests/test_skill_packager.py`:

```python
def test_skill_md_includes_topics_and_examples(self, tmp_path):
    course_dir = tmp_path / "knowledge_base" / "test-course"
    course_dir.mkdir(parents=True)
    (course_dir / "index.md").write_text("# Test\n")
    (course_dir / "01-intro.md").write_text("# Intro\n")
    (course_dir / "02-advanced.md").write_text("# Advanced\n")

    zip_path = package_course_as_zip(course_dir, "Test Course", tmp_path / "out")

    with zipfile.ZipFile(zip_path) as zf:
        skill_file = [n for n in zf.namelist() if "SKILL.md" in n][0]
        content = zf.read(skill_file).decode()
        assert "## Topics Covered" in content
        assert "## Examples" in content
        assert "01-intro.md" in content

def test_uses_ai_description_from_skill_meta(self, tmp_path):
    import json
    course_dir = tmp_path / "knowledge_base" / "ai-course"
    course_dir.mkdir(parents=True)
    (course_dir / "index.md").write_text("# AI Course\n")
    (course_dir / "01-basics.md").write_text("# Basics\n")

    # Write .skill_meta.json (created by refiner in Pro mode)
    meta = {"ai_description": "AI-crafted description with smart triggers."}
    (course_dir / ".skill_meta.json").write_text(json.dumps(meta))

    zip_path = package_course_as_zip(course_dir, "AI Course", tmp_path / "out")

    with zipfile.ZipFile(zip_path) as zf:
        skill_file = [n for n in zf.namelist() if "SKILL.md" in n][0]
        content = zf.read(skill_file).decode()
        assert "AI-crafted description with smart triggers." in content

def test_skill_meta_not_included_in_zip(self, tmp_path):
    import json
    course_dir = tmp_path / "knowledge_base" / "ai-course"
    course_dir.mkdir(parents=True)
    (course_dir / "index.md").write_text("# AI Course\n")
    (course_dir / "01-basics.md").write_text("# Basics\n")
    (course_dir / ".skill_meta.json").write_text(json.dumps({"ai_description": "test"}))

    zip_path = package_course_as_zip(course_dir, "AI Course", tmp_path / "out")

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert not any(".skill_meta.json" in n for n in names)
```

**Step 2: Run tests to verify they fail**

Run: `cd "Skill Bill" && python -m pytest tests/test_skill_packager.py::TestPackageCourseAsZip -v`
Expected: FAIL (current packager doesn't pass `video_files` or read `.skill_meta.json`)

**Step 3: Update `package_course_as_zip()`**

Replace the function in `web/services/skill_packager.py`:

```python
def package_course_as_zip(
    course_dir: Path,
    course_title: str,
    output_dir: Path,
) -> Path:
    """Bundle a knowledge base course into a downloadable ZIP.

    The ZIP contains SKILL.md + all markdown files + assets,
    ready to unzip into ~/.claude/skills/<course-slug>/.
    """
    course_slug = course_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{course_slug}.zip"

    # Count videos and extract topic hints from filenames
    md_files = sorted(course_dir.glob("*.md"))
    video_files = [f for f in md_files if f.name != "index.md"]
    video_count = len(video_files)

    # Extract video titles from filenames as topic hints
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
            import json
            meta = json.loads(skill_meta_path.read_text())
            ai_description = meta.get("ai_description", "")
        except Exception:
            pass

    skill_content = generate_skill_md(
        course_title, course_slug, video_count, topics,
        video_files=video_filenames,
        ai_description=ai_description,
    )

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add SKILL.md
        zf.writestr(f"{course_slug}/SKILL.md", skill_content)

        # Add all markdown files
        for md_file in md_files:
            zf.write(md_file, f"{course_slug}/{md_file.name}")

        # Add assets (skip hidden files like .skill_meta.json, .refined)
        assets_dir = course_dir / "assets"
        if assets_dir.exists():
            for asset_file in assets_dir.rglob("*"):
                if asset_file.is_file():
                    rel = asset_file.relative_to(course_dir)
                    zf.write(asset_file, f"{course_slug}/{rel}")

    return zip_path
```

Note: The key changes are:
1. Extract ALL topics (not just first 5) — `generate_skill_md` handles truncation.
2. Pass `video_filenames` list.
3. Read `.skill_meta.json` if present.
4. Hidden files (`.skill_meta.json`, `.refined`) are NOT included in the ZIP since they live in the course root, not assets/.

**Step 4: Run tests to verify they pass**

Run: `cd "Skill Bill" && python -m pytest tests/test_skill_packager.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
cd "Skill Bill"
git add web/services/skill_packager.py tests/test_skill_packager.py
git commit -m "feat: packager passes video files and reads .skill_meta.json

Enables example interactions using actual filenames, and uses AI-generated
descriptions from Pro mode when available."
```

---

### Task 3: Add `generate_skill_description()` to `refiner.py`

**Files:**
- Modify: `skillbill/refiner.py`
- Test: `tests/test_refiner.py`

**Step 1: Write failing tests**

Add a new test class to `tests/test_refiner.py`:

```python
from skillbill.refiner import generate_skill_description


class TestGenerateSkillDescription:
    @patch("skillbill.refiner._call_haiku")
    def test_returns_ai_description(self, mock_call):
        mock_call.return_value = "Knowledge base covering MCPs, plugins, and skills. Use when asking about Claude Code features."
        result = generate_skill_description(
            course_title="Claude Code for Teams",
            video_titles=["MCPs Overview", "Plugins Setup", "Skills Deep Dive"],
            api_key="sk-test",
        )
        assert "MCPs" in result
        mock_call.assert_called_once()

    @patch("skillbill.refiner._call_haiku")
    def test_strips_whitespace(self, mock_call):
        mock_call.return_value = "  Clean description.  \n"
        result = generate_skill_description("Title", ["V1"], api_key="sk-test")
        assert result == "Clean description."

    @patch("skillbill.refiner._call_haiku")
    def test_falls_back_to_empty_on_error(self, mock_call):
        mock_call.side_effect = Exception("API error")
        result = generate_skill_description("Title", ["V1"], api_key="sk-test")
        assert result == ""

    def test_no_api_key_returns_empty(self):
        result = generate_skill_description("Title", ["V1"], api_key="")
        assert result == ""

    @patch("skillbill.refiner._call_haiku")
    def test_prompt_includes_video_titles(self, mock_call):
        mock_call.return_value = "Description."
        generate_skill_description(
            course_title="My Course",
            video_titles=["Intro to Python", "Advanced Functions"],
            api_key="sk-test",
        )
        prompt_text = mock_call.call_args[1]["messages"][0]["content"] if "messages" in mock_call.call_args[1] else mock_call.call_args[0][0][0]["content"]
        assert "Intro to Python" in prompt_text
        assert "Advanced Functions" in prompt_text
```

**Step 2: Run tests to verify they fail**

Run: `cd "Skill Bill" && python -m pytest tests/test_refiner.py::TestGenerateSkillDescription -v`
Expected: FAIL with ImportError (function doesn't exist yet)

**Step 3: Implement `generate_skill_description()` in `skillbill/refiner.py`**

Add this function after `refine_video_title()` (around line 109):

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `cd "Skill Bill" && python -m pytest tests/test_refiner.py::TestGenerateSkillDescription -v`
Expected: All PASS

**Step 5: Commit**

```bash
cd "Skill Bill"
git add skillbill/refiner.py tests/test_refiner.py
git commit -m "feat: add generate_skill_description() for Pro skill descriptions

One Haiku call per course to generate contextual trigger phrases and
a tailored description following Anthropic's skill best practices."
```

---

### Task 4: Wire `generate_skill_description()` into `refine_course()`

**Files:**
- Modify: `skillbill/refiner.py:246-343` (the `refine_course` function)
- Test: `tests/test_refiner.py`

**Step 1: Write failing test**

Add to `TestRefineCourse` in `tests/test_refiner.py`:

```python
@patch("skillbill.refiner.generate_skill_description")
@patch("skillbill.refiner.refine_video_title")
@patch("skillbill.refiner.refine_video_content")
@patch("skillbill.refiner.filter_screenshots")
def test_writes_skill_meta_json(self, mock_filter, mock_content, mock_title, mock_desc, tmp_path):
    import json
    course_dir = tmp_path / "test-course"
    course_dir.mkdir()
    (course_dir / "index.md").write_text("# Test\n")
    (course_dir / "01-v1.md").write_text("# V1\n")

    mock_title.return_value = "Clean Title"
    mock_content.return_value = "1. **Step** — Do it.\n"
    mock_filter.return_value = []
    mock_desc.return_value = "AI-crafted description with triggers."

    manifest = {
        "playlist_title": "Test Course",
        "slug": "test-course",
        "video_count": 1,
        "playlist_url": "https://youtube.com/playlist?list=PLtest",
        "videos": [{"id": "abc", "title": "V1", "url": "https://youtube.com/watch?v=abc", "duration": 120, "chapters": [], "description": ""}],
    }
    transcripts = [{"video_id": "abc", "has_transcript": True, "entries": [{"start": 0, "duration": 5, "text": "Hi"}], "chapters": [], "description": ""}]

    refine_course(course_dir, manifest, transcripts, [[]], api_key="sk-test")

    # .skill_meta.json should exist with ai_description
    meta_path = course_dir / ".skill_meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["ai_description"] == "AI-crafted description with triggers."
    mock_desc.assert_called_once()

@patch("skillbill.refiner.generate_skill_description")
@patch("skillbill.refiner.refine_video_title")
@patch("skillbill.refiner.refine_video_content")
@patch("skillbill.refiner.filter_screenshots")
def test_skill_meta_uses_clean_titles(self, mock_filter, mock_content, mock_title, mock_desc, tmp_path):
    course_dir = tmp_path / "test-course"
    course_dir.mkdir()
    (course_dir / "index.md").write_text("# Test\n")
    (course_dir / "01-v1.md").write_text("# V1\n")

    mock_title.return_value = "Clean Video Title"
    mock_content.return_value = "1. **Step** — Do it.\n"
    mock_filter.return_value = []
    mock_desc.return_value = "Description."

    manifest = {
        "playlist_title": "Test Course",
        "slug": "test-course",
        "video_count": 1,
        "playlist_url": "https://youtube.com/playlist?list=PLtest",
        "videos": [{"id": "abc", "title": "Clickbait Original", "url": "https://youtube.com/watch?v=abc", "duration": 120, "chapters": [], "description": ""}],
    }
    transcripts = [{"video_id": "abc", "has_transcript": True, "entries": [{"start": 0, "duration": 5, "text": "Hi"}], "chapters": [], "description": ""}]

    refine_course(course_dir, manifest, transcripts, [[]], api_key="sk-test")

    # generate_skill_description should receive the CLEAN title, not original
    call_args = mock_desc.call_args
    video_titles_arg = call_args[1].get("video_titles") or call_args[0][1]
    assert "Clean Video Title" in video_titles_arg
    assert "Clickbait Original" not in video_titles_arg
```

**Step 2: Run tests to verify they fail**

Run: `cd "Skill Bill" && python -m pytest tests/test_refiner.py::TestRefineCourse::test_writes_skill_meta_json tests/test_refiner.py::TestRefineCourse::test_skill_meta_uses_clean_titles -v`
Expected: FAIL

**Step 3: Add skill description call to `refine_course()`**

At the end of `refine_course()` in `skillbill/refiner.py`, after writing the index and before the `.refined` marker, add:

```python
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
```

This goes right before the existing line:
```python
    # Write marker file for Pro detection
    (course_dir / ".refined").write_text("")
```

**Step 4: Run tests to verify they pass**

Run: `cd "Skill Bill" && python -m pytest tests/test_refiner.py::TestRefineCourse -v`
Expected: All PASS

**Step 5: Run the full test suite**

Run: `cd "Skill Bill" && python -m pytest tests/ -v`
Expected: All tests PASS (no regressions)

**Step 6: Commit**

```bash
cd "Skill Bill"
git add skillbill/refiner.py tests/test_refiner.py
git commit -m "feat: refine_course writes .skill_meta.json with AI description

Calls generate_skill_description at the end of course refinement using
clean de-clickbaited titles, saves result for skill_packager to pick up."
```

---

### Task 5: Update existing tests that may break with new function signature

**Files:**
- Modify: `tests/test_skill_packager.py`

**Step 1: Check if existing tests still pass**

Run: `cd "Skill Bill" && python -m pytest tests/test_skill_packager.py -v`

The existing `test_contains_frontmatter` and `test_contains_navigation_instructions` tests call `generate_skill_md()` without the new `video_files` and `ai_description` parameters. Since these have default values (`None` and `""`), they should still pass. But verify the assertions still hold with the new template — in particular, `test_contains_navigation_instructions` checks for `"## How to Navigate" in content or "## How to Use" in content` which should still pass.

If all pass, no changes needed. If any fail due to template changes (e.g., frontmatter format changed from single-line `description:` to multi-line `description: >`), update the assertions:

For `test_contains_frontmatter`, the assertion `"name: python-basics" in content` should still pass. The assertion `"Python Basics" in content` should still pass (it's in the `# Python Basics` heading).

**Step 2: Run full suite one final time**

Run: `cd "Skill Bill" && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 3: Commit (only if changes were needed)**

```bash
cd "Skill Bill"
git add tests/test_skill_packager.py
git commit -m "fix(test): update skill packager test assertions for new template"
```

---

### Verification

After all tasks are complete:

1. `generate_skill_md()` produces SKILL.md with: trigger phrases in description, Topics Covered, When to Use, When NOT to Use, Examples with filenames, metadata block
2. `package_course_as_zip()` reads `.skill_meta.json` and passes AI description when available
3. `generate_skill_description()` makes one Haiku call per course with clean titles
4. `refine_course()` writes `.skill_meta.json` after refinement
5. All existing + new tests pass: `cd "Skill Bill" && python -m pytest tests/ -v`
6. Base mode produces a smart-template SKILL.md (no API call)
7. Pro mode produces a SKILL.md with Haiku-crafted description

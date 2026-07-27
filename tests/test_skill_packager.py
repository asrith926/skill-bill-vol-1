"""Tests for the skill packager — generates downloadable Claude Code skill ZIPs."""
import json
import zipfile
import pytest
from pathlib import Path
from web.services.skill_packager import generate_skill_md, package_course_as_zip


class TestGenerateSkillMd:
    def test_contains_frontmatter(self):
        content = generate_skill_md(
            course_title="Python Basics",
            course_slug="python-basics",
            video_count=10,
            topics=["variables", "functions", "loops"],
        )
        assert "---" in content
        assert "name: python-basics" in content
        assert "Python Basics" in content

    def test_contains_navigation_instructions(self):
        content = generate_skill_md(
            course_title="Test", course_slug="test", video_count=5, topics=[]
        )
        assert "index.md" in content
        assert "## How to Use" in content

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

    def test_raw_mode_has_chapter_navigation(self):
        """Raw (non-refined) SKILL.md uses chapter-based navigation."""
        content = generate_skill_md(
            course_title="Test",
            course_slug="test",
            video_count=5,
            topics=["intro"],
            is_refined=False,
        )
        assert "Navigate by chapter" in content
        assert "## [MM:SS] Chapter Title" in content

    def test_refined_mode_has_step_navigation(self):
        """Refined SKILL.md uses lesson step navigation."""
        content = generate_skill_md(
            course_title="Test",
            course_slug="test",
            video_count=5,
            topics=["intro"],
            video_files=["01-intro.md"],
            is_refined=True,
        )
        assert "Navigate by lesson step" in content
        assert "numbered lesson step" in content
        assert "inline screenshots" in content.lower() or "Inline" in content

    def test_refined_with_topic_index_mentions_topics_json(self):
        """Refined SKILL.md with topic index mentions topics.json."""
        content = generate_skill_md(
            course_title="Test",
            course_slug="test",
            video_count=5,
            topics=["intro"],
            is_refined=True,
            has_topic_index=True,
        )
        assert "topics.json" in content

    def test_refined_without_topic_index_omits_topics_json(self):
        """Refined SKILL.md without topic index does NOT mention topics.json."""
        content = generate_skill_md(
            course_title="Test",
            course_slug="test",
            video_count=5,
            topics=["intro"],
            is_refined=True,
            has_topic_index=False,
        )
        assert "topics.json" not in content


class TestPackageCourseAsZip:
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
        course_dir = tmp_path / "knowledge_base" / "ai-course"
        course_dir.mkdir(parents=True)
        (course_dir / "index.md").write_text("# AI Course\n")
        (course_dir / "01-basics.md").write_text("# Basics\n")
        (course_dir / ".skill_meta.json").write_text(json.dumps({"ai_description": "test"}))

        zip_path = package_course_as_zip(course_dir, "AI Course", tmp_path / "out")

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert not any(".skill_meta.json" in n for n in names)

    def test_creates_valid_zip(self, tmp_path):
        # Set up a minimal knowledge base
        course_dir = tmp_path / "knowledge_base" / "test-course"
        course_dir.mkdir(parents=True)
        (course_dir / "index.md").write_text("# Test\n")
        (course_dir / "01-intro.md").write_text("# Intro\n")

        assets_dir = course_dir / "assets" / "01"
        assets_dir.mkdir(parents=True)
        (assets_dir / "00-00.png").write_bytes(b"fake png")

        zip_path = package_course_as_zip(course_dir, "Test Course", tmp_path / "out")

        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert any("SKILL.md" in n for n in names)
            assert any("index.md" in n for n in names)
            assert any("01-intro.md" in n for n in names)
            assert any("00-00.png" in n for n in names)

    def test_zip_skill_md_has_frontmatter(self, tmp_path):
        course_dir = tmp_path / "knowledge_base" / "my-course"
        course_dir.mkdir(parents=True)
        (course_dir / "index.md").write_text("# My Course\n\n1. [Video](./01-v.md)\n")
        (course_dir / "01-v.md").write_text("# Video\n")

        zip_path = package_course_as_zip(course_dir, "My Course", tmp_path / "out")

        with zipfile.ZipFile(zip_path) as zf:
            skill_file = [n for n in zf.namelist() if "SKILL.md" in n][0]
            content = zf.read(skill_file).decode()
            assert "name: my-course" in content

    def test_refined_course_skill_md_has_step_navigation(self, tmp_path):
        """Refined courses get step-based navigation in SKILL.md."""
        course_dir = tmp_path / "knowledge_base" / "refined-course"
        course_dir.mkdir(parents=True)
        (course_dir / "index.md").write_text("# Refined\n")
        (course_dir / "01-intro.md").write_text("# Intro\n")
        (course_dir / ".refined").write_text("")

        zip_path = package_course_as_zip(course_dir, "Refined Course", tmp_path / "out")

        with zipfile.ZipFile(zip_path) as zf:
            skill_file = [n for n in zf.namelist() if "SKILL.md" in n][0]
            content = zf.read(skill_file).decode()
            assert "lesson step" in content
            assert "Navigate by chapter" not in content

    def test_topics_json_included_in_zip(self, tmp_path):
        """topics.json is included in the ZIP when it exists."""
        course_dir = tmp_path / "knowledge_base" / "indexed-course"
        course_dir.mkdir(parents=True)
        (course_dir / "index.md").write_text("# Indexed\n")
        (course_dir / "01-intro.md").write_text("# Intro\n")
        (course_dir / ".refined").write_text("")
        (course_dir / "topics.json").write_text(json.dumps({"topics": {"python": [{"video": 1, "step": 1}]}}))

        zip_path = package_course_as_zip(course_dir, "Indexed Course", tmp_path / "out")

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert any("topics.json" in n for n in names)
            # SKILL.md should mention topics.json
            skill_file = [n for n in names if "SKILL.md" in n][0]
            content = zf.read(skill_file).decode()
            assert "topics.json" in content

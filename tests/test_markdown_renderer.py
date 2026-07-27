"""Tests for the markdown-to-HTML renderer service."""
import pytest
from web.services.markdown_renderer import render_markdown, render_video_file


class TestRenderMarkdown:
    def test_renders_heading(self):
        html = render_markdown("# Hello")
        assert "<h1>" in html
        assert "Hello" in html

    def test_renders_code_block_with_highlighting(self):
        md = "```python\nprint('hello')\n```"
        html = render_markdown(md)
        assert "highlight" in html or "codehilite" in html or "<code" in html

    def test_renders_image_with_path(self):
        md = "![slide_transition](./assets/01/00-30.png)"
        html = render_markdown(md)
        assert "<img" in html
        assert "00-30.png" in html

    def test_renders_bold_and_italic(self):
        md = "**bold** and *italic*"
        html = render_markdown(md)
        assert "<strong>" in html or "<b>" in html
        assert "<em>" in html or "<i>" in html


class TestRenderVideoFile:
    def test_renders_video_markdown(self, tmp_path):
        md_file = tmp_path / "01-intro.md"
        md_file.write_text(
            "# Introduction\n\n"
            "**Course:** Test Course\n\n"
            "## [00:00] Welcome\n\n"
            "Hello everyone.\n"
        )
        html = render_video_file(md_file)
        assert "Introduction" in html
        assert "Welcome" in html

    def test_rewrites_asset_paths(self, tmp_path):
        md_file = tmp_path / "01-intro.md"
        md_file.write_text("![caption](./assets/01/00-30.png)")
        html = render_video_file(md_file, asset_url_prefix="/assets/test-course")
        assert "/assets/test-course/01/00-30.png" in html

    def test_missing_file_raises(self):
        from pathlib import Path
        with pytest.raises(FileNotFoundError):
            render_video_file(Path("/nonexistent/file.md"))

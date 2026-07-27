"""Markdown-to-HTML rendering with syntax highlighting."""
import re
from pathlib import Path
from markdown_it import MarkdownIt
from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import HtmlFormatter


def _highlight_code(code: str, lang: str) -> str:
    """Syntax-highlight a code block."""
    try:
        lexer = get_lexer_by_name(lang)
    except Exception:
        lexer = TextLexer()
    formatter = HtmlFormatter(nowrap=True)
    return highlight(code, lexer, formatter)


def render_markdown(text: str) -> str:
    """Render markdown text to HTML with syntax highlighting."""
    md = MarkdownIt("commonmark", {"html": True}).enable("table")

    # Render base markdown
    html = md.render(text)

    # Post-process fenced code blocks for syntax highlighting
    def replace_code_block(match):
        lang = match.group(1) or ""
        code = match.group(2)
        if lang:
            highlighted = _highlight_code(code, lang)
            return f'<pre><code class="highlight language-{lang}">{highlighted}</code></pre>'
        return match.group(0)

    html = re.sub(
        r'<code class="language-(\w+)">(.*?)</code>',
        replace_code_block,
        html,
        flags=re.DOTALL,
    )

    return html


def render_video_file(
    md_path: Path, asset_url_prefix: str | None = None
) -> str:
    """Read a video markdown file and render to HTML.

    If asset_url_prefix is provided, rewrite relative ./assets/ paths
    to the given URL prefix.
    """
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    text = md_path.read_text()

    if asset_url_prefix:
        # Rewrite ./assets/NN/MM-SS.png → /assets/<prefix>/NN/MM-SS.png
        text = text.replace("./assets/", f"{asset_url_prefix}/")

    return render_markdown(text)

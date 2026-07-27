"""Library and course browsing routes."""
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from skillbill.config import KB_DIR
from web.server_deps import get_templates
from web.services.markdown_renderer import render_video_file

router = APIRouter()


def _list_courses() -> list[dict]:
    """Scan knowledge_base/ for generated courses."""
    courses = []
    if not KB_DIR.exists():
        return courses
    for course_dir in sorted(KB_DIR.iterdir()):
        if not course_dir.is_dir():
            continue
        index_file = course_dir / "index.md"
        if not index_file.exists():
            continue
        # Count video files (exclude index.md)
        video_files = [f for f in course_dir.glob("*.md") if f.name != "index.md"]
        # Check for screenshots
        has_screenshots = (course_dir / "assets").exists()
        # Get first screenshot for thumbnail
        thumbnail = None
        if has_screenshots:
            asset_dirs = sorted((course_dir / "assets").iterdir())
            for ad in asset_dirs:
                if ad.is_dir():
                    pngs = sorted(ad.glob("*.png"))
                    if pngs:
                        thumbnail = f"/kb-assets/{course_dir.name}/assets/{ad.name}/{pngs[0].name}"
                        break
        is_pro = (course_dir / ".refined").exists()
        courses.append({
            "slug": course_dir.name,
            "title": _extract_title(index_file),
            "video_count": len(video_files),
            "has_screenshots": has_screenshots,
            "thumbnail": thumbnail,
            "is_pro": is_pro,
        })
    return courses


def _extract_title(index_file: Path) -> str:
    """Extract course title from index.md first heading."""
    for line in index_file.read_text().splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            return title.replace(" -- Course Index", "")
    return index_file.parent.name


def _list_videos(course_dir: Path) -> list[dict]:
    """List videos in a course directory."""
    videos = []
    for md_file in sorted(course_dir.glob("*.md")):
        if md_file.name == "index.md":
            continue
        # Extract number and title from filename
        stem = md_file.stem
        parts = stem.split("-", 1)
        number = parts[0] if parts[0].isdigit() else "0"
        title = parts[1].replace("-", " ").title() if len(parts) > 1 else stem
        videos.append({
            "number": int(number),
            "filename": md_file.name,
            "slug": md_file.stem,
            "title": title,
        })
    return videos


@router.get("/library", response_class=HTMLResponse)
async def library_page(request: Request):
    templates = get_templates()
    courses = _list_courses()
    return templates.TemplateResponse(request, "library.html", {
        "courses": courses,
    })


@router.get("/course/{course_slug}", response_class=HTMLResponse)
async def course_page(request: Request, course_slug: str):
    templates = get_templates()
    course_dir = KB_DIR / course_slug
    if not course_dir.exists() or not (course_dir / "index.md").exists():
        raise HTTPException(status_code=404, detail="Course not found")
    videos = _list_videos(course_dir)
    title = _extract_title(course_dir / "index.md")
    return templates.TemplateResponse(request, "course.html", {
        "course_slug": course_slug,
        "course_title": title,
        "videos": videos,
    })


@router.get("/course/{course_slug}/{video_slug}", response_class=HTMLResponse)
async def video_page(request: Request, course_slug: str, video_slug: str):
    templates = get_templates()
    course_dir = KB_DIR / course_slug
    md_file = course_dir / f"{video_slug}.md"
    if not md_file.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    videos = _list_videos(course_dir)
    course_title = _extract_title(course_dir / "index.md")
    html_content = render_video_file(md_file, asset_url_prefix=f"/kb-assets/{course_slug}/assets")

    # Find prev/next
    current_idx = next((i for i, v in enumerate(videos) if v["slug"] == video_slug), 0)
    prev_video = videos[current_idx - 1] if current_idx > 0 else None
    next_video = videos[current_idx + 1] if current_idx < len(videos) - 1 else None

    return templates.TemplateResponse(request, "video.html", {
        "course_slug": course_slug,
        "course_title": course_title,
        "video_slug": video_slug,
        "html_content": html_content,
        "videos": videos,
        "prev_video": prev_video,
        "next_video": next_video,
    })

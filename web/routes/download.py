"""Download route — serve skill ZIP packages."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from skillbill.config import KB_DIR, DATA_DIR
from web.services.skill_packager import package_course_as_zip
from web.routes.library import _extract_title

router = APIRouter()


@router.get("/download/{course_slug}")
async def download_skill_zip(course_slug: str):
    """Generate and serve a skill ZIP for a course."""
    course_dir = KB_DIR / course_slug
    if not course_dir.exists() or not (course_dir / "index.md").exists():
        raise HTTPException(status_code=404, detail="Course not found")

    title = _extract_title(course_dir / "index.md")
    zip_path = package_course_as_zip(course_dir, title, DATA_DIR / "downloads")

    return FileResponse(
        path=str(zip_path),
        filename=f"{course_slug}-skill.zip",
        media_type="application/zip",
    )

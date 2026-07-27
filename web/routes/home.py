"""Home page route — the URL input form."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from web.server_deps import get_templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    templates = get_templates()
    return templates.TemplateResponse(request, "home.html")

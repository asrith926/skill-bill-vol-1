"""FastAPI application for the Skill Bill web UI."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from skillbill.config import KB_DIR, ASSETS_DIR
from web.routes import home, generate, library, download, settings

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(title="Skill Bill")

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mount knowledge base assets for screenshot serving
if KB_DIR.exists():
    app.mount("/kb-assets", StaticFiles(directory=str(KB_DIR)), name="kb-assets")

# Shared templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include route modules
app.include_router(home.router)
app.include_router(generate.router)
app.include_router(library.router)
app.include_router(download.router)
app.include_router(settings.router)

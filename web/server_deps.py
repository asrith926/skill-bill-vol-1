"""Shared dependencies for web routes."""
from pathlib import Path
from fastapi.templating import Jinja2Templates
from web.services.pipeline_runner import PipelineRunner

WEB_DIR = Path(__file__).parent
_templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
_runner = PipelineRunner()


def get_templates() -> Jinja2Templates:
    return _templates


def get_runner() -> PipelineRunner:
    return _runner

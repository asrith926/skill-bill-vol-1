"""Pipeline generation routes — POST to start, WebSocket for progress."""
import asyncio
import json
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from web.server_deps import get_templates, get_runner
from web.services.api_keys import load_api_key

router = APIRouter()


@router.post("/generate", response_class=HTMLResponse)
async def start_generate(request: Request):
    """Accept form submission and redirect to progress page."""
    templates = get_templates()
    form = await request.form()
    url = form.get("url", "")
    mode = form.get("mode", "full")
    cookies_from = form.get("cookies_from") or None
    use_haiku = form.get("use_haiku") != "off"
    refine = form.get("tier") == "pro"

    # Load API key — used for Haiku segment classification and Pro refinement
    _, api_key = load_api_key()
    if refine and not api_key:
        return templates.TemplateResponse(request, "home.html", {
            "error": "Pro mode requires an API key. Please configure one first.",
        })

    runner = get_runner()

    try:
        await runner.start(
            url=url,
            mode=mode,
            use_haiku=use_haiku,
            cookies_from=cookies_from,
            refine=refine,
            api_key=api_key,
        )
    except RuntimeError as e:
        return templates.TemplateResponse(request, "home.html", {
            "error": str(e),
        })

    return templates.TemplateResponse(request, "progress.html", {
        "url": url,
        "mode": mode,
        "refine": refine,
    })


@router.websocket("/ws/progress")
async def progress_websocket(websocket: WebSocket):
    """Stream pipeline progress events to the browser."""
    await websocket.accept()
    runner = get_runner()

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def on_event(event: dict):
        loop.call_soon_threadsafe(queue.put_nowait, event)

    runner.add_listener(on_event)

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("type") in ("pipeline_complete", "error") and event.get("fatal"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        runner.remove_listener(on_event)

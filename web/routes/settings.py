"""Settings routes -- API key management."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from web.services.api_keys import load_api_key, save_api_key, clear_api_key

router = APIRouter(prefix="/api")


@router.get("/key-status")
async def key_status():
    """Check if an API key is configured."""
    provider, key = load_api_key()
    return JSONResponse({
        "has_key": bool(key),
        "provider": provider if key else "",
    })


@router.post("/save-key")
async def save_key(request: Request):
    """Save an API key."""
    data = await request.json()
    provider = data.get("provider", "")
    api_key = data.get("api_key", "")
    if not provider or not api_key:
        return JSONResponse({"error": "Provider and API key required"}, status_code=400)
    if provider not in ("anthropic",):
        return JSONResponse({"error": "Only Anthropic is supported currently"}, status_code=400)
    save_api_key(provider, api_key)
    return JSONResponse({"status": "saved"})


@router.post("/clear-key")
async def clear_key():
    """Clear saved API key."""
    clear_api_key()
    return JSONResponse({"status": "cleared"})

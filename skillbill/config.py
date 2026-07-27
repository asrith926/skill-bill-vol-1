from pathlib import Path
import os

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
ASSETS_DIR = DATA_DIR / "assets"
KB_DIR = DATA_DIR / "knowledge_base"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Screenshot config
SCREENSHOT_CONFIG = {
    "min_interval_seconds": 10,
    "max_interval_seconds": 120,
    "dedup_threshold": 12,  # legacy global threshold; superseded by DEDUP_THRESHOLDS
    "sparse_transcript_threshold": 10,  # words per minute
    "verbal_cue_keywords": [
        "look at", "as you can see", "on screen", "this diagram",
        "this code", "let me show", "here we have", "notice",
        "this shows", "take a look", "on the left", "on the right",
        "you can see", "shown here", "right here", "over here",
        "this is", "watch", "observe", "check out",
    ],
}

# Segment-aware dedup thresholds (imagehash hamming distance).
# Lower = stricter (only drops near-identical frames, keeps more).
# Higher = looser (drops more frames as "duplicates").
# dhash is 64 bits. Truly identical frames differ by 0-1.
# Meaningful screen content changes differ by 13+.
DEDUP_THRESHOLDS = {
    "code-demo": 4,       # very strict — even small code changes matter
    "ui-walkthrough": 4,  # very strict — small UI state changes matter
    "whiteboard": 6,      # strict — evolving drawings
    "slides": 8,          # moderate — distinct slides differ significantly
    "talking-head": 12,   # looser — face doesn't change, dedup more aggressively
    "unknown": 6,
    "default": 6,
}

# Screenshot filter for AI refinement (Pro mode)
# Controls which screenshots are sent to Haiku for lesson extraction.
# Verbal cues pass by default UNLESS they match the blocklist.
SCREENSHOT_FILTER = {
    "keep_reasons": ["slide_transition", "scene_change"],
    "drop_reasons": ["section_start", "interval_fallback", "mid_section"],
    "verbal_cue_blocklist": ["this is", "notice"],
}

# Claude API
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

def ensure_dirs():
    """Create all data directories if they don't exist."""
    for d in [RAW_DIR, PROCESSED_DIR, ASSETS_DIR, KB_DIR]:
        d.mkdir(parents=True, exist_ok=True)

"""Stage 5: Frame extraction with ffmpeg and perceptual hash deduplication."""
import subprocess
from pathlib import Path

import imagehash
from PIL import Image
from scenedetect import detect, ContentDetector, AdaptiveDetector


def detect_scenes(video_path: str, threshold: float = 27.0) -> list[float]:
    """Detect scene change timestamps using PySceneDetect.

    Returns list of timestamps (seconds) where scene changes occur.
    """
    scene_list = detect(video_path, ContentDetector(threshold=threshold))
    timestamps = []
    for scene in scene_list:
        timestamps.append(scene[0].get_seconds())
    return timestamps


def extract_frame(video_path: str, timestamp: float, output_path: Path) -> Path:
    """Extract a single frame from video at the given timestamp using ffmpeg.

    Returns path to the saved PNG file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Format timestamp as HH:MM:SS.mmm
    hours = int(timestamp // 3600)
    minutes = int((timestamp % 3600) // 60)
    seconds = timestamp % 60
    ts_str = f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"

    cmd = [
        "ffmpeg",
        "-ss", ts_str,
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        "-y",
        str(output_path),
    ]

    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def is_duplicate_frame(
    frame_path: Path,
    previous_frames: list[Path],
    threshold: int = 12,
) -> bool:
    """Check if a frame is a near-duplicate of any previously captured frame.

    Uses perceptual hashing (dhash). Lower threshold = stricter matching.
    """
    if not previous_frames:
        return False

    current_hash = imagehash.dhash(Image.open(frame_path))

    for prev_path in previous_frames:
        if prev_path.exists():
            prev_hash = imagehash.dhash(Image.open(prev_path))
            if abs(current_hash - prev_hash) <= threshold:
                return True

    return False


def capture_screenshots(
    video_path: str,
    screenshot_plan: dict,
    output_dir: Path,
    dedup_threshold: int = 18,
    segment_thresholds: dict | None = None,
    lookback: int = 5,
) -> list[dict]:
    """Execute the screenshot plan: extract frames and deduplicate.

    Uses segment-aware dedup thresholds when segment_thresholds is provided.
    Returns list of dicts with timestamp, path, segment_type, and status.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    kept_frames = []

    # Transition reasons that benefit from a small forward offset
    # to avoid capturing mid-transition frames (fades, dissolves, overlays)
    _TRANSITION_REASONS = {"scene_change", "slide_transition"}
    TRANSITION_OFFSET = 1.5  # seconds

    for entry in screenshot_plan["screenshots"]:
        ts = entry["timestamp"]
        reason = entry.get("reason", "")
        seg_type = entry.get("segment_type", "default")

        # Offset transition captures to get the settled frame
        if reason in _TRANSITION_REASONS:
            ts = ts + TRANSITION_OFFSET

        minutes = int(ts // 60)
        seconds = int(ts % 60)
        filename = f"{minutes:02d}-{seconds:02d}.png"
        frame_path = output_dir / filename

        try:
            extract_frame(video_path, ts, frame_path)
        except Exception:
            results.append({"timestamp": ts, "path": None, "status": "error"})
            continue

        if not frame_path.exists():
            results.append({"timestamp": ts, "path": None, "status": "error"})
            continue

        # Look up effective threshold for this segment type
        effective_threshold = dedup_threshold
        if segment_thresholds:
            effective_threshold = segment_thresholds.get(
                seg_type, segment_thresholds.get("default", dedup_threshold)
            )

        # Check for duplicates against last N frames
        recent_frames = kept_frames[-lookback:]
        if is_duplicate_frame(frame_path, recent_frames, threshold=effective_threshold):
            frame_path.unlink()  # delete duplicate
            results.append({"timestamp": ts, "path": None, "status": "duplicate"})
        else:
            kept_frames.append(frame_path)
            results.append({
                "timestamp": ts,
                "path": str(frame_path),
                "reason": entry["reason"],
                "segment_type": seg_type,
                "status": "kept",
            })

    return results

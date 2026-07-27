"""Stage 4: Screenshot planning with local heuristics and optional Haiku classification."""
import json
from pathlib import Path
from typing import Optional

from skillbill.config import SCREENSHOT_CONFIG, ANTHROPIC_MODEL, ANTHROPIC_API_KEY


def scan_verbal_cues(entries: list[dict], keywords: list[str]) -> list[dict]:
    """Scan transcript entries for verbal cues indicating visual content.

    Returns list of dicts with timestamp and matched keyword.
    """
    cues = []
    for entry in entries:
        text_lower = entry["text"].lower()
        for keyword in keywords:
            if keyword in text_lower:
                cues.append({
                    "timestamp": entry["start"],
                    "keyword": keyword,
                    "text": entry["text"],
                })
                break  # one match per entry is enough
    return cues


def classify_segments_local(
    density: list[dict],
    verbal_cues: list[dict],
    scene_changes: list[float],
) -> list[dict]:
    """Classify transcript segments using local heuristics only.

    Uses speech density, verbal cue presence, and scene change frequency
    to guess segment type: talking-head, code-demo, slides, whiteboard, unknown.
    """
    segments = []
    cue_timestamps = {c["timestamp"] for c in verbal_cues}

    for window in density:
        start, end = window["start"], window["end"]
        wpm = window["words_per_minute"]

        # Count scene changes in this window
        changes_in_window = [t for t in scene_changes if start <= t < end]
        change_rate = len(changes_in_window) / ((end - start) / 60)

        # Count verbal cues in this window
        cues_in_window = [t for t in cue_timestamps if start <= t < end]

        # Classification logic
        if wpm < SCREENSHOT_CONFIG["sparse_transcript_threshold"]:
            # Sparse speech — screen is the content
            if change_rate > 4:
                seg_type = "code-demo"
            else:
                seg_type = "unknown"  # could be whiteboard, could be demo
        elif wpm > 100 and change_rate < 1 and not cues_in_window:
            seg_type = "talking-head"
        elif change_rate >= 2 and change_rate <= 6:
            seg_type = "slides"
        elif change_rate > 6:
            seg_type = "code-demo"
        elif cues_in_window:
            seg_type = "slides"  # speaker referencing visuals with moderate changes
        else:
            seg_type = "unknown"

        segments.append({
            "type": seg_type,
            "start": start,
            "end": end,
            "wpm": wpm,
            "scene_change_rate": round(change_rate, 1),
        })

    return segments


def classify_segments_haiku(transcript_text: str, api_key: str = "") -> list[dict]:
    """Use Claude Haiku to classify transcript segments.

    Sends the full transcript as text, returns segment classifications.
    Cost: ~$0.02 per video.
    """
    import anthropic

    key = api_key or ANTHROPIC_API_KEY
    if not key:
        return []

    client = anthropic.Anthropic(api_key=key)

    prompt = f"""Analyze this video tutorial transcript. For each section, classify what is likely shown on screen.

Return a JSON array of segments with this structure:
[{{"type": "code-demo|slides|talking-head|whiteboard|ui-walkthrough", "start_seconds": N, "end_seconds": N, "description": "brief note"}}]

Types:
- code-demo: presenter is showing/writing/running code
- slides: presentation slides are being shown
- talking-head: just the presenter speaking to camera, no visual aids
- whiteboard: drawing diagrams or writing on a whiteboard
- ui-walkthrough: demonstrating a user interface or application

Transcript:
{transcript_text}

Return ONLY the JSON array, no other text."""

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        raw_segments = json.loads(response.content[0].text)
        # Normalize key names: Haiku returns start_seconds/end_seconds,
        # but plan_screenshots_for_segment expects start/end
        normalized = []
        for seg in raw_segments:
            normalized.append({
                "type": seg.get("type", "unknown"),
                "start": seg.get("start", seg.get("start_seconds", 0)),
                "end": seg.get("end", seg.get("end_seconds", 0)),
            })
        return normalized
    except (json.JSONDecodeError, IndexError, TypeError):
        return []


def plan_screenshots_for_segment(
    segment: dict,
    scene_changes: list[float],
) -> list[dict]:
    """Generate screenshot timestamps for a single segment based on its type."""
    start = segment["start"]
    end = segment["end"]
    duration = end - start
    seg_type = segment["type"]
    timestamps = []

    changes_in_segment = [t for t in scene_changes if start <= t < end]

    if seg_type == "code-demo":
        # Capture at every scene change + fallback every 25s
        for t in changes_in_segment:
            timestamps.append({"timestamp": t, "reason": "scene_change", "segment_type": seg_type})
        fallback = start
        while fallback < end:
            timestamps.append({"timestamp": fallback, "reason": "interval_fallback", "segment_type": seg_type})
            fallback += 25

    elif seg_type == "slides":
        # Capture at each slide transition (scene change)
        for t in changes_in_segment:
            timestamps.append({"timestamp": t, "reason": "slide_transition", "segment_type": seg_type})
        # If no scene changes detected, fallback to intervals
        if not changes_in_segment and duration > 10:
            timestamps.append({"timestamp": start, "reason": "section_start", "segment_type": seg_type})

    elif seg_type == "talking-head":
        # Skip all planned screenshots — verbal cues are added
        # separately in build_screenshot_plan() and still fire.
        pass

    elif seg_type == "whiteboard":
        # Capture every 15-20s (evolving visual)
        t = start
        while t < end:
            timestamps.append({"timestamp": t, "reason": "whiteboard_interval", "segment_type": seg_type})
            t += 18

    else:  # unknown
        # Safety net: every 45s
        t = start
        while t < end:
            timestamps.append({"timestamp": t, "reason": "interval_fallback", "segment_type": seg_type})
            t += 45

    return timestamps


def merge_and_deduplicate_timestamps(
    timestamps: list[dict],
    min_interval: float = None,
) -> list[dict]:
    """Merge and deduplicate screenshot timestamps.

    Removes timestamps that are too close together (within min_interval seconds).
    Keeps the first occurrence.
    """
    if min_interval is None:
        min_interval = SCREENSHOT_CONFIG["min_interval_seconds"]

    if not timestamps:
        return []

    sorted_ts = sorted(timestamps, key=lambda t: t["timestamp"])
    result = [sorted_ts[0]]

    for ts in sorted_ts[1:]:
        if ts["timestamp"] - result[-1]["timestamp"] >= min_interval:
            result.append(ts)

    return result


def build_screenshot_plan(
    video_id: str,
    transcript_entries: list[dict],
    scene_changes: list[float],
    density: list[dict],
    chapters: list[dict] | None = None,
    use_haiku: bool = True,
    output_dir: Optional[Path] = None,
    course_slug: Optional[str] = None,
    api_key: str = "",
) -> dict:
    """Build the full screenshot plan for a video.

    Combines all heuristics and optional Haiku classification.
    """
    # 1. Scan verbal cues
    verbal_cues = scan_verbal_cues(
        transcript_entries, SCREENSHOT_CONFIG["verbal_cue_keywords"]
    )

    # 2. Classify segments
    key = api_key or ANTHROPIC_API_KEY
    if use_haiku and key:
        transcript_text = "\n".join(
            f"[{e['start']:.1f}s] {e['text']}" for e in transcript_entries
        )
        segments = classify_segments_haiku(transcript_text, api_key=key)
        if not segments:
            segments = classify_segments_local(density, verbal_cues, scene_changes)
    else:
        segments = classify_segments_local(density, verbal_cues, scene_changes)

    # 3. Plan screenshots per segment
    all_timestamps = []
    for segment in segments:
        seg_timestamps = plan_screenshots_for_segment(segment, scene_changes)
        all_timestamps.extend(seg_timestamps)

    # 4. Add verbal cue timestamps (look up which segment each falls in)
    for cue in verbal_cues:
        cue_seg_type = "unknown"
        for seg in segments:
            if seg["start"] <= cue["timestamp"] < seg["end"]:
                cue_seg_type = seg["type"]
                break
        all_timestamps.append({
            "timestamp": cue["timestamp"],
            "reason": f"verbal_cue: {cue['keyword']}",
            "segment_type": cue_seg_type,
        })

    # 5. Add chapter boundary timestamps
    if chapters:
        for ch in chapters:
            ch_time = ch.get("start_time", 0)
            ch_seg_type = "unknown"
            for seg in segments:
                if seg["start"] <= ch_time < seg["end"]:
                    ch_seg_type = seg["type"]
                    break
            all_timestamps.append({
                "timestamp": ch_time,
                "reason": "chapter_boundary",
                "segment_type": ch_seg_type,
            })

    # 6. Merge and deduplicate
    final_timestamps = merge_and_deduplicate_timestamps(all_timestamps)

    plan = {
        "video_id": video_id,
        "segments": segments,
        "screenshots": final_timestamps,
        "total_screenshots": len(final_timestamps),
    }

    if output_dir is not None and course_slug is not None:
        save_dir = output_dir / course_slug
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / f"{video_id}-screenshot-plan.json"
        path.write_text(json.dumps(plan, indent=2))

    return plan

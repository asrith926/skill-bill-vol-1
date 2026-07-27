"""Pipeline runner with progress event emission for WebSocket streaming."""
import asyncio
import threading
from enum import StrEnum
from pathlib import Path
from typing import Callable, Optional
from skillbill.pipeline import Pipeline


class PipelineStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


class PipelineRunner:
    """Wraps skillbill.Pipeline with progress callbacks for the web UI.

    Runs the pipeline in a background thread so the async event loop
    stays responsive for WebSocket messages.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir
        self.status: PipelineStatus = PipelineStatus.IDLE
        self.current_course_slug: Optional[str] = None
        self._listeners: list[Callable] = []
        self._lock = threading.Lock()

    def add_listener(self, callback: Callable) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable) -> None:
        self._listeners = [cb for cb in self._listeners if cb != callback]

    def _emit(self, event: dict) -> None:
        for cb in self._listeners:
            try:
                cb(event)
            except Exception:
                pass

    async def start(
        self,
        url: str,
        mode: str = "full",
        use_haiku: bool = True,
        cookies_from: Optional[str] = None,
        refine: bool = False,
        api_key: str = "",
    ) -> None:
        """Start the pipeline in a background thread.

        Args:
            url: YouTube playlist or video URL.
            mode: "full" or "transcript_only".
            use_haiku: Whether to use Haiku for segment classification.
            cookies_from: Browser to extract cookies from (e.g. "chrome").
            refine: Whether to run Stage 7 AI refinement (Pro mode).
            api_key: API key for refinement calls.
        """
        if self.status == PipelineStatus.RUNNING:
            raise RuntimeError("Pipeline is busy. Wait for the current run to complete.")

        self.status = PipelineStatus.RUNNING
        loop = asyncio.get_event_loop()

        def run_in_thread():
            try:
                pipeline = Pipeline(
                    data_dir=self.data_dir,
                    use_haiku=use_haiku,
                    cookies_from=cookies_from,
                    refine=refine,
                    api_key=api_key,
                )
                self._run_pipeline(pipeline, url, mode, api_key=api_key)
            except Exception as e:
                self.status = PipelineStatus.ERROR
                self._emit({"type": "error", "message": str(e), "fatal": True})

        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()

    def _run_pipeline(self, pipeline: Pipeline, url: str, mode: str, api_key: str = "") -> None:
        """Execute pipeline stages, emitting progress events."""

        # Stage 1: Discovery
        self._emit({"type": "stage_start", "stage": "discovery"})
        self._emit({"type": "log", "message": f"Discovering playlist: {url}"})
        pipeline.run_discovery(url)
        manifest = pipeline.manifest
        total = manifest["video_count"]
        self.current_course_slug = manifest["slug"]
        self._emit({
            "type": "stage_complete",
            "stage": "discovery",
            "data": {"title": manifest["playlist_title"], "video_count": total},
        })

        if total == 0:
            self.status = PipelineStatus.ERROR
            self._emit({"type": "error", "message": "No videos found in playlist. Check the URL and try again.", "fatal": True})
            return

        # Stage 2: Transcripts
        self._emit({"type": "stage_start", "stage": "transcripts", "total": total})
        pipeline.run_transcripts()
        found = sum(1 for t in pipeline.transcripts if t["has_transcript"])
        self._emit({
            "type": "stage_complete",
            "stage": "transcripts",
            "data": {"found": found, "total": total},
        })

        if mode == "transcript_only":
            # Skip stages 3-5
            pipeline.capture_results = [[] for _ in pipeline.transcripts]
            self._emit({"type": "log", "message": "Transcript-only mode — skipping video download and screenshots"})
        else:
            # Stage 3: Download
            self._emit({"type": "stage_start", "stage": "download", "total": total})
            video_paths = pipeline.run_download()
            downloaded = sum(1 for p in video_paths if p is not None)
            self._emit({
                "type": "stage_complete",
                "stage": "download",
                "data": {"downloaded": downloaded, "total": total},
            })

            # Stage 4: Screenshot planning
            self._emit({"type": "stage_start", "stage": "screenshot_planning", "total": total})
            pipeline.run_screenshot_planning(video_paths)
            total_screenshots = sum(p.get("total_screenshots", 0) for p in pipeline.screenshot_plans)
            self._emit({
                "type": "stage_complete",
                "stage": "screenshot_planning",
                "data": {"total_screenshots": total_screenshots},
            })

            # Stage 5: Capture
            self._emit({"type": "stage_start", "stage": "capture", "total": total})
            pipeline.run_capture(video_paths)
            total_kept = sum(
                sum(1 for r in results if r["status"] == "kept")
                for results in pipeline.capture_results
            )
            self._emit({
                "type": "stage_complete",
                "stage": "capture",
                "data": {"screenshots_kept": total_kept},
            })

        # Stage 6: Generation
        self._emit({"type": "stage_start", "stage": "generation", "total": total})
        course_dir = pipeline.run_generation()
        self._emit({"type": "stage_complete", "stage": "generation"})

        # Stage 7: Refinement (Pro mode only)
        if pipeline.refine and api_key:
            self._emit({"type": "stage_start", "stage": "refinement", "total": total})
            self._emit({"type": "log", "message": "Refining with AI — cleaning titles and extracting lessons..."})
            pipeline.run_refinement(api_key=api_key)
            self._emit({"type": "stage_complete", "stage": "refinement"})

        # Done
        self.status = PipelineStatus.COMPLETE
        self._emit({
            "type": "pipeline_complete",
            "course_slug": manifest["slug"],
            "course_title": manifest["playlist_title"],
            "video_count": total,
        })

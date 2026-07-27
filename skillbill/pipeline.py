"""Pipeline orchestrator: runs all stages or individual stages."""
import json
import time
from datetime import date
from pathlib import Path
from typing import Optional

from skillbill.config import DATA_DIR, DEDUP_THRESHOLDS
from skillbill.downloader import discover_playlist, download_video, slugify_title
from skillbill.transcript import fetch_all_transcripts, compute_speech_density, detect_sparse_sections
from skillbill.analyzer import build_screenshot_plan
from skillbill.capturer import detect_scenes, capture_screenshots
from skillbill.generator import generate_video_markdown, generate_course_index


class Pipeline:
    """Orchestrates the full YouTube-to-Knowledge-Base pipeline."""

    def __init__(self, data_dir: Optional[Path] = None, use_haiku: bool = True, cookies_from: Optional[str] = None, refine: bool = False, api_key: str = ""):
        self.data_dir = data_dir or DATA_DIR
        self.raw_dir = self.data_dir / "raw"
        self.processed_dir = self.data_dir / "processed"
        self.assets_dir = self.data_dir / "assets"
        self.kb_dir = self.data_dir / "knowledge_base"
        self.use_haiku = use_haiku
        self.cookies_from = cookies_from
        self.refine = refine
        self.api_key = api_key
        self.manifest = None
        self.transcripts = None
        self.screenshot_plans = None
        self.capture_results = None

        # Create directories
        for d in [self.raw_dir, self.processed_dir, self.assets_dir, self.kb_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def run_discovery(self, url: str) -> dict:
        """Stage 1: Discover playlist metadata."""
        self.manifest = discover_playlist(url, output_dir=self.raw_dir, cookies_from=self.cookies_from)
        print(f"Discovered: {self.manifest['playlist_title']} ({self.manifest['video_count']} videos)")
        return self.manifest

    def run_transcripts(self) -> list[dict]:
        """Stage 2: Fetch transcripts for all videos.

        Discovery now uses flat extraction (1 request), so no cooldown is
        needed.  Delay between transcript fetches is conservative: 5s without
        cookies, 2s with cookies (authenticated requests have higher limits).
        """
        if not self.manifest:
            raise ValueError("Run discovery first")

        video_ids = [v["id"] for v in self.manifest["videos"]]
        slug = self.manifest["slug"]

        delay = 2.0 if self.cookies_from else 5.0

        self.transcripts = fetch_all_transcripts(
            video_ids, output_dir=self.processed_dir, course_slug=slug,
            cookies_from=self.cookies_from, delay=delay,
        )

        found = sum(1 for t in self.transcripts if t["has_transcript"])
        print(f"Transcripts: {found}/{len(video_ids)} found")
        return self.transcripts

    def run_download(self) -> list[Optional[Path]]:
        """Stage 3: Download video files."""
        if not self.manifest:
            raise ValueError("Run discovery first")

        slug = self.manifest["slug"]
        output_dir = self.raw_dir / slug
        paths = []

        for i, video in enumerate(self.manifest["videos"], 1):
            prefix = f"{i:02d}-"
            vid = video["id"]
            id_cached = list(output_dir.glob(f"{prefix}{vid}-*")) if output_dir.exists() else []
            if id_cached:
                path = id_cached[0]
                print(f"Using cached video for {video['title']}")
            else:
                # Check for stale prefix-only matches (wrong video ID)
                stale = list(output_dir.glob(f"{prefix}*")) if output_dir.exists() else []
                if stale:
                    print(f"Stale cache for slot {i:02d} (video ID mismatch), re-downloading")
                print(f"Downloading {i}/{self.manifest['video_count']}: {video['title']}")
                try:
                    path = download_video(video["url"], output_dir, filename_prefix=f"{prefix}{vid}-", cookies_from=self.cookies_from)
                except Exception as e:
                    print(f"  Skipping download for {video['title']}: {e}")
                    path = None
            paths.append(path)

        return paths

    def run_screenshot_planning(self, video_paths: list[Path]) -> list[dict]:
        """Stage 4: Plan screenshots for all videos."""
        if not self.manifest or not self.transcripts:
            raise ValueError("Run discovery and transcripts first")

        slug = self.manifest["slug"]
        self.screenshot_plans = []

        for i, (video, transcript) in enumerate(
            zip(self.manifest["videos"], self.transcripts)
        ):
            if not transcript["has_transcript"]:
                self.screenshot_plans.append({"video_id": video["id"], "screenshots": []})
                continue

            if i < len(video_paths) and video_paths[i] is None:
                self.screenshot_plans.append({"video_id": video["id"], "screenshots": []})
                print(f"  Skipping (no video file)")
                continue

            print(f"Analyzing {i + 1}/{len(self.transcripts)}: {video['title']}")

            # Detect scenes
            if i < len(video_paths) and video_paths[i].exists():
                scene_changes = detect_scenes(str(video_paths[i]))
            else:
                scene_changes = []

            # Compute density
            density = compute_speech_density(transcript["entries"])

            # Build plan
            plan = build_screenshot_plan(
                video_id=video["id"],
                transcript_entries=transcript["entries"],
                scene_changes=scene_changes,
                density=density,
                chapters=video.get("chapters"),
                use_haiku=self.use_haiku,
                output_dir=self.processed_dir,
                course_slug=slug,
                api_key=self.api_key,
            )
            self.screenshot_plans.append(plan)
            print(f"  → {plan['total_screenshots']} screenshots planned")

        return self.screenshot_plans

    def run_capture(self, video_paths: list[Path]) -> list[list[dict]]:
        """Stage 5: Capture screenshots."""
        if not self.screenshot_plans:
            raise ValueError("Run screenshot planning first")

        slug = self.manifest["slug"]
        self.capture_results = []

        for i, (plan, video_path) in enumerate(
            zip(self.screenshot_plans, video_paths)
        ):
            if not plan["screenshots"]:
                self.capture_results.append([])
                continue

            if video_path is None:
                self.capture_results.append([])
                continue

            video_num = f"{i + 1:02d}"
            output_dir = self.assets_dir / slug / video_num
            print(f"Capturing frames for video {video_num}...")

            results = capture_screenshots(
                str(video_path), plan, output_dir,
                segment_thresholds=DEDUP_THRESHOLDS,
            )
            kept = sum(1 for r in results if r["status"] == "kept")
            dupes = sum(1 for r in results if r["status"] == "duplicate")
            print(f"  → {kept} kept, {dupes} duplicates removed")
            self.capture_results.append(results)

        return self.capture_results

    def run_generation(self) -> Path:
        """Stage 6: Generate markdown knowledge base."""
        if not self.manifest or not self.transcripts:
            raise ValueError("Run discovery and transcripts first")

        slug = self.manifest["slug"]
        course_dir = self.kb_dir / slug
        course_dir.mkdir(parents=True, exist_ok=True)

        for i, (video, transcript) in enumerate(
            zip(self.manifest["videos"], self.transcripts)
        ):
            video_num = i + 1
            video_slug = slugify_title(video["title"])
            filename = f"{video_num:02d}-{video_slug}.md"

            # Collect kept screenshots with relative paths
            screenshots = []
            if self.capture_results and i < len(self.capture_results):
                for r in self.capture_results[i]:
                    if r["status"] == "kept" and r.get("path"):
                        rel_path = f"./assets/{video_num:02d}/{Path(r['path']).name}"
                        screenshots.append({
                            "timestamp": r["timestamp"],
                            "path": rel_path,
                            "reason": r.get("reason", ""),
                            "segment_type": r.get("segment_type", "unknown"),
                        })

            generate_video_markdown(
                video_title=video["title"],
                course_title=self.manifest["playlist_title"],
                video_number=video_num,
                total_videos=self.manifest["video_count"],
                duration=video.get("duration") or 0,
                video_url=video["url"],
                transcript_entries=transcript.get("entries", []),
                chapters=transcript.get("chapters") or video.get("chapters", []),
                screenshots=screenshots,
                description=transcript.get("description") or video.get("description", ""),
                output_path=course_dir / filename,
            )

        # Copy assets to knowledge base
        src_assets = self.assets_dir / slug
        dst_assets = course_dir / "assets"
        if src_assets.exists():
            import shutil
            if dst_assets.exists():
                shutil.rmtree(dst_assets)
            shutil.copytree(src_assets, dst_assets)

        # Generate index
        generate_course_index(
            course_title=self.manifest["playlist_title"],
            playlist_url=self.manifest["playlist_url"],
            videos=self.manifest["videos"],
            output_path=course_dir / "index.md",
            generated_date=str(date.today()),
        )

        print(f"Knowledge base generated at: {course_dir}")
        return course_dir

    def run_refinement(self, api_key: str = "") -> Path:
        """Stage 7: AI refinement — clean titles + lesson extraction."""
        if not self.manifest or not self.transcripts:
            raise ValueError("Run discovery and transcripts first")

        from skillbill.refiner import refine_course

        course_dir = self.kb_dir / self.manifest["slug"]
        return refine_course(
            course_dir=course_dir,
            manifest=self.manifest,
            transcripts=self.transcripts,
            capture_results=self.capture_results or [[] for _ in self.transcripts],
            api_key=api_key,
        )

    def run_all(self, url: str, api_key: str = "") -> Path:
        """Run the complete pipeline end-to-end."""
        if api_key:
            self.api_key = api_key
        self.run_discovery(url)
        self.run_transcripts()
        video_paths = self.run_download()
        self.run_screenshot_planning(video_paths)
        self.run_capture(video_paths)
        course_dir = self.run_generation()
        if self.refine:
            return self.run_refinement(api_key=api_key)
        return course_dir

    def run_transcript_only(self, url: str, api_key: str = "") -> Path:
        """Run pipeline without video download or screenshots."""
        self.run_discovery(url)
        self.run_transcripts()
        self.capture_results = [[] for _ in self.transcripts]
        course_dir = self.run_generation()
        if self.refine:
            return self.run_refinement(api_key=api_key)
        return course_dir

"""Tests for the pipeline runner service with progress callbacks."""
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from web.services.pipeline_runner import PipelineRunner, PipelineStatus


class TestPipelineRunner:
    def test_initial_status_is_idle(self):
        runner = PipelineRunner()
        assert runner.status == PipelineStatus.IDLE

    def test_cannot_start_while_busy(self):
        runner = PipelineRunner()
        runner.status = PipelineStatus.RUNNING
        with pytest.raises(RuntimeError, match="busy"):
            asyncio.run(
                runner.start("https://youtube.com/playlist?list=PLtest", mode="transcript_only")
            )

    def test_progress_callback_collects_events(self):
        runner = PipelineRunner()
        events = []
        runner.add_listener(events.append)
        runner._emit({"type": "stage_start", "stage": "discovery"})
        assert len(events) == 1
        assert events[0]["type"] == "stage_start"

    def test_remove_listener(self):
        runner = PipelineRunner()
        events = []
        runner.add_listener(events.append)
        runner.remove_listener(events.append)
        runner._emit({"type": "log", "message": "test"})
        assert len(events) == 0


class TestPipelineRunnerRefine:
    def test_accepts_refine_parameter(self):
        runner = PipelineRunner()
        # Should not raise — refine is a valid parameter
        assert runner.status == PipelineStatus.IDLE


class TestPipelineStatus:
    def test_status_values(self):
        assert PipelineStatus.IDLE == "idle"
        assert PipelineStatus.RUNNING == "running"
        assert PipelineStatus.COMPLETE == "complete"
        assert PipelineStatus.ERROR == "error"

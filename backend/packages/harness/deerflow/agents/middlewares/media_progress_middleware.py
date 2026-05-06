"""
MediaProgressMiddleware — harness for async media generation tool calls.

Responsibilities:
  1. Pre-tool intercept: inject a "⏳ Generating …" progress message into the
     conversation stream so the user sees immediate feedback before a long
     (potentially 1–5 min) video generation API call returns.
  2. Post-tool intercept: when a generation tool returns a task_id (async
     provider), append a structured reminder message that instructs the agent
     to poll via check_media_task — preventing the agent from silently
     forgetting about pending tasks.
  3. Cost / rate-limit guard: optionally count how many media generation
     calls have been made in a single thread and warn when approaching a
     configurable limit (avoids runaway spend on generative APIs).

Integration:
    Add to _build_middlewares() in lead_agent/agent.py when agent_name == "director"
    (or always for any agent that has media tools in its tool_groups).

    Example in agent.py:

        from deerflow.agents.middlewares.media_progress_middleware import MediaProgressMiddleware

        # inside _build_middlewares(), before ClarificationMiddleware:
        if agent_name == "director" or (agent_config and "media" in (agent_config.tool_groups or [])):
            middlewares.append(MediaProgressMiddleware())

Configuration (via env vars — no config.yaml changes required):
    DIRECTOR_MAX_MEDIA_CALLS_PER_THREAD=20   # warn after this many calls (default: 20)
    DIRECTOR_MEDIA_PROGRESS_ENABLED=1         # set to 0 to disable (default: 1)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MEDIA_GENERATION_TOOLS = frozenset({
    "generate_image",
    "generate_image_from_image",
    "generate_video_from_text",
    "generate_video_from_image",
})

_MEDIA_POLLING_TOOLS = frozenset({
    "check_media_task",
})

_MEDIA_EDIT_TOOLS = frozenset({
    "trim_video",
    "merge_videos",
    "add_audio_to_video",
    "add_subtitles_to_video",
    "create_slideshow",
    "extract_video_frames",
    "download_media",
    "get_video_info",
})

_ALL_MEDIA_TOOLS = _MEDIA_GENERATION_TOOLS | _MEDIA_POLLING_TOOLS | _MEDIA_EDIT_TOOLS

# Progress messages shown to the user while the tool is running (streamed as
# an intermediate AI message so the UI gives live feedback)
_PROGRESS_MESSAGES: dict[str, str] = {
    "generate_image": "🎨 Generating image — this may take 10–30 seconds…",
    "generate_image_from_image": "🎨 Applying style transfer — this may take 10–30 seconds…",
    "generate_video_from_text": "🎬 Submitting video generation job — the video API will process in the background…",
    "generate_video_from_image": "🎬 Submitting image-to-video job — animating your frame in the background…",
    "check_media_task": "🔄 Polling media task status…",
    "trim_video": "✂️ Trimming video clip…",
    "merge_videos": "🔗 Merging video clips — this may take a moment for long videos…",
    "add_audio_to_video": "🎵 Mixing audio into video…",
    "add_subtitles_to_video": "📝 Burning subtitles into video…",
    "create_slideshow": "🖼️ Creating slideshow from images…",
    "extract_video_frames": "📷 Extracting frames from video…",
    "download_media": "⬇️ Downloading media file…",
}

# ---------------------------------------------------------------------------
# Thread-local call counter (guards against runaway API spend)
# ---------------------------------------------------------------------------

_call_counts: dict[str, int] = defaultdict(int)
_call_counts_lock = threading.Lock()

_MAX_MEDIA_CALLS = int(os.getenv("DIRECTOR_MAX_MEDIA_CALLS_PER_THREAD", "20"))
_ENABLED = os.getenv("DIRECTOR_MEDIA_PROGRESS_ENABLED", "1") != "0"


def _increment_and_check(thread_id: str, tool_name: str) -> str | None:
    """Increment per-thread call counter, return warning string if limit approached."""
    if tool_name not in _MEDIA_GENERATION_TOOLS:
        return None
    with _call_counts_lock:
        _call_counts[thread_id] += 1
        count = _call_counts[thread_id]
    if count == _MAX_MEDIA_CALLS:
        return (
            f"⚠️ This thread has made {count} media generation calls. "
            "Consider reviewing costs and whether all calls are necessary."
        )
    if count > _MAX_MEDIA_CALLS:
        return (
            f"⚠️ Media generation call limit reached ({count}/{_MAX_MEDIA_CALLS}). "
            "Proceeding, but be mindful of API costs."
        )
    return None


# ---------------------------------------------------------------------------
# Result enrichment helpers
# ---------------------------------------------------------------------------

def _enrich_async_result(tool_name: str, result_str: str, tool_call_id: str) -> str:
    """
    Parse the tool result JSON and, if it contains a pending task_id,
    append structured guidance so the agent knows to poll.
    """
    if tool_name not in {"generate_video_from_text", "generate_video_from_image"}:
        return result_str

    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return result_str

    task_id = data.get("task_id", "")
    provider = data.get("provider", "")
    status = data.get("status", "")

    # Only add guidance when the task is still pending (no video_url yet)
    if not task_id or data.get("video_url") or status == "completed":
        return result_str

    data["_director_guidance"] = (
        f"📌 Video generation job queued (task_id={task_id}, provider={provider}). "
        f"Call check_media_task(task_id='{task_id}', provider='{provider}') "
        "to retrieve the video URL when ready. "
        "Typical generation time: Kling/RunwayML 2–5 min, Wan2.1 1–3 min, Luma 1–4 min. "
        "You may continue with other tasks (image generation, script writing) while waiting."
    )
    return json.dumps(data, indent=2, ensure_ascii=False)


def _enrich_image_result(tool_name: str, result_str: str) -> str:
    """Append usage guidance to image generation results."""
    if tool_name not in {"generate_image", "generate_image_from_image"}:
        return result_str
    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return result_str

    if data.get("status") == "success" and not data.get("_director_guidance"):
        images = data.get("images", [])
        paths = [img.get("local_path", img.get("sandbox_path", "")) for img in images if img.get("local_path") or img.get("sandbox_path")]
        if paths:
            data["_director_guidance"] = (
                "✅ Image(s) generated and saved. "
                f"Local path(s): {', '.join(paths)}. "
                "Next steps: use generate_video_from_image to animate, "
                "create_slideshow to build a storyboard preview, "
                "or present_files to show the user."
            )
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Middleware class
# ---------------------------------------------------------------------------

class MediaProgressMiddlewareState(AgentState):
    """Compatible with ThreadState schema."""
    pass


class MediaProgressMiddleware(AgentMiddleware[MediaProgressMiddlewareState]):
    """
    Middleware that provides progress feedback and task tracking for
    the Director Agent's media generation tool calls.

    Hooks:
      before_tool_call  → emit a progress message visible in the chat UI
      after_tool_call   → enrich async results with polling guidance
    """

    state_schema = MediaProgressMiddlewareState

    def __init__(self, max_calls: int = _MAX_MEDIA_CALLS) -> None:
        self.max_calls = max_calls

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_thread_id(self, state: MediaProgressMiddlewareState) -> str:
        """Extract thread_id from state, fall back to 'unknown'."""
        try:
            td = getattr(state, "thread_data", None) or {}
            return str(td.get("thread_id", "unknown"))
        except Exception:
            return "unknown"

    def _build_progress_tool_message(
        self, request: ToolCallRequest, tool_name: str, thread_id: str
    ) -> ToolMessage | None:
        """
        Build a synthetic ToolMessage that shows progress text in the UI
        before the actual tool runs. This keeps the agent's message history
        valid (every tool_call_id must have a corresponding ToolMessage).

        NOTE: We do NOT insert a fake ToolMessage here because that would
        pollute the tool-call result slot. Instead, we log progress and let
        the actual result be the only ToolMessage for this call_id.
        This method is kept for documentation; the real feedback mechanism
        is via logger.info which LangGraph streams as events.
        """
        msg = _PROGRESS_MESSAGES.get(tool_name, f"⏳ Running {tool_name}…")
        logger.info("[MediaProgressMiddleware] thread=%s tool=%s — %s", thread_id, tool_name, msg)
        return None  # Don't inject a fake message

    # ------------------------------------------------------------------
    # Sync wrap_tool_call
    # ------------------------------------------------------------------

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if not _ENABLED:
            return handler(request)

        tool_name = str(request.tool_call.get("name", ""))
        if tool_name not in _ALL_MEDIA_TOOLS:
            return handler(request)

        # Pre-call: log progress
        logger.info("[MediaProgress] Starting: %s | args=%s",
                    tool_name,
                    json.dumps({k: v for k, v in (request.tool_call.get("args") or {}).items()
                                if k not in ("image_path", "source_image_path")},
                               ensure_ascii=False)[:200])

        # Rate-limit check
        warning = _increment_and_check("sync", tool_name)
        if warning:
            logger.warning("[MediaProgress] %s", warning)

        start = time.monotonic()
        result = handler(request)
        elapsed = time.monotonic() - start

        # Post-call: enrich result
        if isinstance(result, ToolMessage):
            enriched = self._enrich_result(tool_name, result.content)
            if enriched != result.content:
                result = ToolMessage(
                    content=enriched,
                    tool_call_id=result.tool_call_id,
                    name=result.name,
                    status=result.status,
                )

        logger.info("[MediaProgress] Completed: %s in %.1fs", tool_name, elapsed)
        return result

    # ------------------------------------------------------------------
    # Async awrap_tool_call
    # ------------------------------------------------------------------

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if not _ENABLED:
            return await handler(request)

        tool_name = str(request.tool_call.get("name", ""))
        if tool_name not in _ALL_MEDIA_TOOLS:
            return await handler(request)

        logger.info("[MediaProgress] Starting (async): %s", tool_name)
        warning = _increment_and_check("async", tool_name)
        if warning:
            logger.warning("[MediaProgress] %s", warning)

        start = time.monotonic()
        result = await handler(request)
        elapsed = time.monotonic() - start

        if isinstance(result, ToolMessage):
            enriched = self._enrich_result(tool_name, result.content)
            if enriched != result.content:
                result = ToolMessage(
                    content=enriched,
                    tool_call_id=result.tool_call_id,
                    name=result.name,
                    status=result.status,
                )

        logger.info("[MediaProgress] Completed (async): %s in %.1fs", tool_name, elapsed)
        return result

    # ------------------------------------------------------------------
    # Result enrichment dispatch
    # ------------------------------------------------------------------

    def _enrich_result(self, tool_name: str, content: str) -> str:
        """Apply appropriate enrichment based on tool type."""
        if tool_name in {"generate_video_from_text", "generate_video_from_image"}:
            return _enrich_async_result(tool_name, content, "")
        if tool_name in {"generate_image", "generate_image_from_image"}:
            return _enrich_image_result(tool_name, content)
        return content

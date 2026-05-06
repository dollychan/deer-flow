"""
Video generation tools for the Director Agent.

Supports async video APIs with task-based polling pattern:
  - Kling Video   (KLING_ACCESS_KEY + KLING_SECRET_KEY)   — text-to-video & image-to-video
  - RunwayML Gen-3 (RUNWAY_API_KEY)                       — text-to-video & image-to-video
  - Wan2.1 / Alibaba (ALIBABA_DASHSCOPE_API_KEY)         — text-to-video (open source model)
  - Luma Dream Machine (LUMAAI_API_KEY)                   — text-to-video & image-to-video

All providers are async: the tool submits the job and returns a task_id.
Use `check_media_task` to poll for completion and retrieve the output URL.

Usage in config.yaml:
    - name: generate_video_from_text
      group: media
      use: deerflow.community.media_generation.video_tools:generate_video_from_text_tool
      provider: kling    # kling | runway | wan21 | luma
      default_duration: 5
"""

from __future__ import annotations

import base64
import hmac
import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from langchain.tools import tool

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path("/mnt/user-data/outputs")
_WORKSPACE_DIR = Path("/mnt/user-data/workspace")


def _outputs_dir() -> Path:
    if _OUTPUT_DIR.exists():
        return _OUTPUT_DIR
    if _WORKSPACE_DIR.exists():
        return _WORKSPACE_DIR
    return Path("/tmp")


# ---------------------------------------------------------------------------
# JWT helper for Kling
# ---------------------------------------------------------------------------

def _kling_jwt(ak: str, sk: str) -> str:
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    now = int(time.time())
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps({"iss": ak, "exp": now + 1800, "nbf": now - 5}).encode()
    ).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(
        hmac.new(sk.encode(), f"{header}.{payload_b64}".encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{header}.{payload_b64}.{sig}"


# ---------------------------------------------------------------------------
# Provider: Kling Video
# ---------------------------------------------------------------------------

def _kling_text_to_video(
    prompt: str,
    negative_prompt: str,
    duration: int,
    aspect_ratio: str,
    mode: str,
    camera_control: dict | None,
) -> dict:
    ak = os.getenv("KLING_ACCESS_KEY", "")
    sk = os.getenv("KLING_SECRET_KEY", "")
    if not ak or not sk:
        raise ValueError("KLING_ACCESS_KEY and KLING_SECRET_KEY must be set")

    token = _kling_jwt(ak, sk)
    payload: dict[str, Any] = {
        "model_name": "kling-v1",
        "prompt": prompt,
        "negative_prompt": negative_prompt or "",
        "cfg_scale": 0.5,
        "mode": mode,          # "std" | "pro"
        "aspect_ratio": aspect_ratio,
        "duration": str(duration),
    }
    if camera_control:
        payload["camera_control"] = camera_control

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            "https://api.klingai.com/v1/videos/text2video",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    task_id = data.get("data", {}).get("task_id", "")
    return {
        "task_id": task_id,
        "provider": "kling",
        "poll_endpoint": f"https://api.klingai.com/v1/videos/text2video/{task_id}",
        "poll_header_type": "kling_jwt",
    }


def _kling_image_to_video(
    image_path: str,
    prompt: str,
    negative_prompt: str,
    duration: int,
    mode: str,
) -> dict:
    ak = os.getenv("KLING_ACCESS_KEY", "")
    sk = os.getenv("KLING_SECRET_KEY", "")
    if not ak or not sk:
        raise ValueError("KLING_ACCESS_KEY and KLING_SECRET_KEY must be set")

    token = _kling_jwt(ak, sk)

    if image_path.startswith("http"):
        payload: dict[str, Any] = {"image_url": image_path}
    else:
        img_bytes = Path(image_path).read_bytes()
        b64 = base64.b64encode(img_bytes).decode()
        ext = Path(image_path).suffix.lstrip(".") or "png"
        payload = {"image": f"data:image/{ext};base64,{b64}"}

    payload.update({
        "model_name": "kling-v1",
        "prompt": prompt,
        "negative_prompt": negative_prompt or "",
        "cfg_scale": 0.5,
        "mode": mode,
        "duration": str(duration),
    })

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            "https://api.klingai.com/v1/videos/image2video",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    task_id = data.get("data", {}).get("task_id", "")
    return {
        "task_id": task_id,
        "provider": "kling",
        "poll_endpoint": f"https://api.klingai.com/v1/videos/image2video/{task_id}",
        "poll_header_type": "kling_jwt",
    }


# ---------------------------------------------------------------------------
# Provider: RunwayML Gen-3
# ---------------------------------------------------------------------------

def _runway_text_to_video(prompt: str, duration: int, ratio: str) -> dict:
    api_key = os.getenv("RUNWAY_API_KEY", "")
    if not api_key:
        raise ValueError("RUNWAY_API_KEY is not set")

    payload = {
        "model": "gen3a_turbo",
        "textPrompt": prompt,
        "duration": min(duration, 10),
        "ratio": ratio,  # e.g. "1280:768" or "768:1280"
        "watermark": False,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            "https://api.dev.runwayml.com/v1/image_to_video",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                     "X-Runway-Version": "2024-11-06"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    task_id = data.get("id", "")
    return {
        "task_id": task_id,
        "provider": "runway",
        "poll_endpoint": f"https://api.dev.runwayml.com/v1/tasks/{task_id}",
        "poll_header_type": "runway",
    }


def _runway_image_to_video(image_path: str, prompt: str, duration: int, ratio: str) -> dict:
    api_key = os.getenv("RUNWAY_API_KEY", "")
    if not api_key:
        raise ValueError("RUNWAY_API_KEY is not set")

    if image_path.startswith("http"):
        image_b64 = None
        image_url = image_path
    else:
        img_bytes = Path(image_path).read_bytes()
        ext = Path(image_path).suffix.lstrip(".") or "png"
        image_b64 = f"data:image/{ext};base64,{base64.b64encode(img_bytes).decode()}"
        image_url = None

    payload: dict[str, Any] = {
        "model": "gen3a_turbo",
        "duration": min(duration, 10),
        "ratio": ratio,
        "watermark": False,
    }
    if prompt:
        payload["textPrompt"] = prompt
    if image_b64:
        payload["promptImage"] = image_b64
    elif image_url:
        payload["promptImage"] = image_url

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            "https://api.dev.runwayml.com/v1/image_to_video",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                     "X-Runway-Version": "2024-11-06"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    task_id = data.get("id", "")
    return {
        "task_id": task_id,
        "provider": "runway",
        "poll_endpoint": f"https://api.dev.runwayml.com/v1/tasks/{task_id}",
        "poll_header_type": "runway",
    }


# ---------------------------------------------------------------------------
# Provider: Alibaba DashScope / Wan2.1
# ---------------------------------------------------------------------------

def _wan21_text_to_video(prompt: str, size: str, duration: int) -> dict:
    api_key = os.getenv("ALIBABA_DASHSCOPE_API_KEY", os.getenv("DASHSCOPE_API_KEY", ""))
    if not api_key:
        raise ValueError("ALIBABA_DASHSCOPE_API_KEY (or DASHSCOPE_API_KEY) is not set")

    payload = {
        "model": "wan2.1-t2v-turbo",
        "input": {"prompt": prompt},
        "parameters": {"size": size, "duration": duration},
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    task_id = data.get("output", {}).get("task_id", "")
    return {
        "task_id": task_id,
        "provider": "wan21",
        "poll_endpoint": f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
        "poll_header_type": "dashscope",
    }


# ---------------------------------------------------------------------------
# Provider: Luma Dream Machine
# ---------------------------------------------------------------------------

def _luma_text_to_video(prompt: str, aspect_ratio: str, duration: int) -> dict:
    api_key = os.getenv("LUMAAI_API_KEY", "")
    if not api_key:
        raise ValueError("LUMAAI_API_KEY is not set")

    payload: dict[str, Any] = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,  # e.g. "16:9"
        "loop": False,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            "https://api.lumalabs.ai/dream-machine/v1/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    task_id = data.get("id", "")
    return {
        "task_id": task_id,
        "provider": "luma",
        "poll_endpoint": f"https://api.lumalabs.ai/dream-machine/v1/generations/{task_id}",
        "poll_header_type": "luma",
    }


def _luma_image_to_video(image_path: str, prompt: str, aspect_ratio: str) -> dict:
    api_key = os.getenv("LUMAAI_API_KEY", "")
    if not api_key:
        raise ValueError("LUMAAI_API_KEY is not set")

    if image_path.startswith("http"):
        start_frame = {"type": "image", "url": image_path}
    else:
        img_bytes = Path(image_path).read_bytes()
        ext = Path(image_path).suffix.lstrip(".") or "png"
        b64 = f"data:image/{ext};base64,{base64.b64encode(img_bytes).decode()}"
        start_frame = {"type": "image", "url": b64}

    payload: dict[str, Any] = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "keyframes": {"frame0": start_frame},
        "loop": False,
    }

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            "https://api.lumalabs.ai/dream-machine/v1/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    task_id = data.get("id", "")
    return {
        "task_id": task_id,
        "provider": "luma",
        "poll_endpoint": f"https://api.lumalabs.ai/dream-machine/v1/generations/{task_id}",
        "poll_header_type": "luma",
    }


# ---------------------------------------------------------------------------
# Polling helper
# ---------------------------------------------------------------------------

def _poll_task(task_id: str, provider: str, poll_endpoint: str, poll_header_type: str, timeout: int = 300) -> dict:
    """Poll a video generation task until complete or timed out."""
    headers: dict[str, str] = {}

    if poll_header_type == "kling_jwt":
        ak = os.getenv("KLING_ACCESS_KEY", "")
        sk = os.getenv("KLING_SECRET_KEY", "")
        headers["Authorization"] = f"Bearer {_kling_jwt(ak, sk)}"
    elif poll_header_type == "runway":
        headers["Authorization"] = f"Bearer {os.getenv('RUNWAY_API_KEY', '')}"
        headers["X-Runway-Version"] = "2024-11-06"
    elif poll_header_type == "dashscope":
        headers["Authorization"] = f"Bearer {os.getenv('ALIBABA_DASHSCOPE_API_KEY', os.getenv('DASHSCOPE_API_KEY', ''))}"
    elif poll_header_type == "luma":
        headers["Authorization"] = f"Bearer {os.getenv('LUMAAI_API_KEY', '')}"

    deadline = time.time() + timeout
    interval = 5

    while time.time() < deadline:
        time.sleep(interval)
        interval = min(interval * 1.5, 30)  # exponential back-off, cap at 30s

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(poll_endpoint, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning("poll_task %s error: %s", task_id, e)
            continue

        # Normalise status across providers
        status = _extract_status(data, provider)
        if status == "succeeded":
            url = _extract_video_url(data, provider)
            return {"status": "completed", "video_url": url, "raw": data}
        elif status in ("failed", "error", "cancelled"):
            return {"status": "failed", "error": _extract_error(data, provider), "raw": data}
        # else still processing

    return {"status": "timeout", "error": f"Task {task_id} timed out after {timeout}s"}


def _extract_status(data: dict, provider: str) -> str:
    if provider == "kling":
        return data.get("data", {}).get("task_status", "").lower()
    if provider == "runway":
        return data.get("status", "").lower()
    if provider == "wan21":
        return data.get("output", {}).get("task_status", "").lower()
    if provider == "luma":
        state = data.get("state", "").lower()
        return "succeeded" if state == "completed" else state
    return ""


def _extract_video_url(data: dict, provider: str) -> str:
    if provider == "kling":
        works = data.get("data", {}).get("task_result", {}).get("videos", [])
        return works[0].get("url", "") if works else ""
    if provider == "runway":
        outputs = data.get("output", [])
        return outputs[0] if outputs else ""
    if provider == "wan21":
        outputs = data.get("output", {}).get("video_url", "")
        return outputs
    if provider == "luma":
        return data.get("assets", {}).get("video", "")
    return ""


def _extract_error(data: dict, provider: str) -> str:
    if provider == "kling":
        return data.get("data", {}).get("task_status_msg", "Unknown error")
    if provider == "runway":
        return data.get("failure", "Unknown error")
    if provider == "wan21":
        return data.get("output", {}).get("message", "Unknown error")
    if provider == "luma":
        return data.get("failure_reason", "Unknown error")
    return "Unknown error"


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------

def _resolve_video_provider(tool_name: str) -> str:
    try:
        from deerflow.config import get_app_config
        cfg = get_app_config().get_tool_config(tool_name)
        if cfg and "provider" in (cfg.model_extra or {}):
            return cfg.model_extra["provider"]
    except Exception:
        pass
    if os.getenv("KLING_ACCESS_KEY"):
        return "kling"
    if os.getenv("RUNWAY_API_KEY"):
        return "runway"
    if os.getenv("ALIBABA_DASHSCOPE_API_KEY") or os.getenv("DASHSCOPE_API_KEY"):
        return "wan21"
    if os.getenv("LUMAAI_API_KEY"):
        return "luma"
    return "kling"


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------

@tool("generate_video_from_text", parse_docstring=True)
def generate_video_from_text_tool(
    prompt: str,
    duration: int = 5,
    aspect_ratio: str = "16:9",
    negative_prompt: str = "",
    mode: str = "std",
    camera_control: str = "",
    wait_for_completion: bool = False,
    poll_timeout: int = 300,
) -> str:
    """Generate a video clip from a text description.

    Use this to create video clips for individual scenes in the storyboard.
    The API is asynchronous — by default returns a task_id immediately and
    you should call `check_media_task` to retrieve the final video URL.

    Args:
        prompt: Detailed description of the video scene. Include:
            - Subject and action (who/what is doing what)
            - Camera movement (slow pan left, dolly zoom, static wide shot)
            - Lighting and atmosphere (golden hour, studio lighting, foggy morning)
            - Visual style (cinematic 4K, documentary, anime, stop-motion)
            Example: "A lone astronaut walks slowly across a red Martian desert,
            dust swirling around boots, epic wide shot, cinematic, golden light"
        duration: Length of the video clip in seconds. Supported values depend
            on provider: Kling supports 5 or 10, RunwayML up to 10, Wan2.1 up to 8.
            Default: 5
        aspect_ratio: Output aspect ratio. Common values: "16:9" (landscape, default),
            "9:16" (vertical/portrait), "1:1" (square), "4:3" (classic).
        negative_prompt: Elements to exclude (e.g., "blurry, shaky camera, watermark").
        mode: Quality mode. "std" = standard speed, "pro" = higher quality (Kling only).
        camera_control: Optional camera movement JSON string for Kling Pro.
            Example: '{"type":"zoom_in"}'. Leave empty for default camera behavior.
        wait_for_completion: If True, poll synchronously and return the final video URL.
            WARNING: This may block for several minutes. Default: False.
        poll_timeout: Maximum seconds to wait when wait_for_completion=True. Default: 300.
    """
    provider = _resolve_video_provider("generate_video_from_text")
    logger.info("generate_video_from_text: provider=%s duration=%ds ratio=%s", provider, duration, aspect_ratio)

    camera = None
    if camera_control:
        try:
            camera = json.loads(camera_control)
        except Exception:
            pass

    try:
        if provider == "kling":
            result = _kling_text_to_video(prompt, negative_prompt, duration, aspect_ratio, mode, camera)
        elif provider == "runway":
            runway_ratio = aspect_ratio.replace(":", ":").replace("16:9", "1280:768").replace("9:16", "768:1280")
            result = _runway_text_to_video(prompt, duration, runway_ratio)
        elif provider == "wan21":
            size_map = {"16:9": "1280*720", "9:16": "720*1280", "1:1": "720*720", "4:3": "960*720"}
            result = _wan21_text_to_video(prompt, size_map.get(aspect_ratio, "1280*720"), duration)
        elif provider == "luma":
            result = _luma_text_to_video(prompt, aspect_ratio, duration)
        else:
            return json.dumps({"error": f"Unknown provider: {provider}"})
    except Exception as e:
        logger.exception("generate_video_from_text failed")
        return json.dumps({"error": str(e), "provider": provider})

    if wait_for_completion and result.get("task_id"):
        poll_result = _poll_task(
            result["task_id"], provider,
            result["poll_endpoint"], result["poll_header_type"],
            timeout=poll_timeout,
        )
        result.update(poll_result)
        if poll_result.get("status") == "completed" and poll_result.get("video_url"):
            result["usage_hint"] = (
                "Video is ready. Download with download_media tool, "
                "then use video editing tools to trim/merge, or present_files to share."
            )
        return json.dumps(result, indent=2, ensure_ascii=False)

    result["usage_hint"] = (
        f"Task submitted. Use check_media_task(task_id='{result.get('task_id')}', "
        f"provider='{provider}') to poll for completion."
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


@tool("generate_video_from_image", parse_docstring=True)
def generate_video_from_image_tool(
    image_path: str,
    prompt: str = "",
    duration: int = 5,
    aspect_ratio: str = "16:9",
    negative_prompt: str = "",
    mode: str = "std",
    wait_for_completion: bool = False,
    poll_timeout: int = 300,
) -> str:
    """Animate a still image into a video clip (image-to-video).

    Use this to bring storyboard frames to life — take a generated or reference
    image and animate it with motion, camera movement, and scene dynamics.

    Args:
        image_path: Path to the source image inside the sandbox
            (e.g., /mnt/user-data/outputs/scene_01.png) or a remote URL.
            Accepts PNG, JPG, WEBP formats.
        prompt: Optional motion description to guide animation.
            Example: "The camera slowly pulls back revealing the full city skyline,
            clouds drift gently, lights flicker on as dusk falls"
        duration: Length in seconds. Default: 5
        aspect_ratio: Output ratio. Usually should match the source image ratio.
            Options: "16:9", "9:16", "1:1". Default: "16:9"
        negative_prompt: Elements to exclude. Example: "jerky motion, artifacts".
        mode: Quality mode. "std" = standard, "pro" = higher quality (Kling only).
        wait_for_completion: If True, poll synchronously until done. Default: False.
        poll_timeout: Max wait seconds when polling. Default: 300.
    """
    provider = _resolve_video_provider("generate_video_from_image")
    logger.info("generate_video_from_image: provider=%s source=%s", provider, image_path)

    try:
        if provider == "kling":
            result = _kling_image_to_video(image_path, prompt, negative_prompt, duration, mode)
        elif provider == "runway":
            runway_ratio = aspect_ratio.replace("16:9", "1280:768").replace("9:16", "768:1280")
            result = _runway_image_to_video(image_path, prompt, duration, runway_ratio)
        elif provider == "luma":
            result = _luma_image_to_video(image_path, prompt, aspect_ratio)
        else:
            # Wan2.1 doesn't natively support image-to-video in the standard API
            return json.dumps({
                "error": f"Provider '{provider}' does not support image-to-video. "
                         "Set provider to kling, runway, or luma."
            })
    except Exception as e:
        logger.exception("generate_video_from_image failed")
        return json.dumps({"error": str(e), "provider": provider})

    if wait_for_completion and result.get("task_id"):
        poll_result = _poll_task(
            result["task_id"], provider,
            result["poll_endpoint"], result["poll_header_type"],
            timeout=poll_timeout,
        )
        result.update(poll_result)

    if not wait_for_completion:
        result["usage_hint"] = (
            f"Task submitted. Use check_media_task(task_id='{result.get('task_id')}', "
            f"provider='{provider}') to poll for completion."
        )
    return json.dumps(result, indent=2, ensure_ascii=False)


@tool("check_media_task", parse_docstring=True)
def check_media_task_tool(
    task_id: str,
    provider: str,
    download_on_complete: bool = True,
    output_filename: str = "",
) -> str:
    """Check the status of an async media generation task.

    Poll a previously submitted video (or image) generation task. When the task
    completes, optionally downloads the media to the sandbox outputs folder.

    Args:
        task_id: The task ID returned by generate_video_from_text or
            generate_video_from_image.
        provider: The provider that created the task.
            Options: "kling", "runway", "wan21", "luma"
        download_on_complete: If True and the task succeeded, automatically download
            the video to /mnt/user-data/outputs/. Default: True.
        output_filename: Optional filename for the downloaded video
            (e.g., "scene_01.mp4"). Auto-generated if empty.
    """
    logger.info("check_media_task: task_id=%s provider=%s", task_id, provider)

    # Build poll endpoint and headers
    endpoint_map = {
        "kling_text": f"https://api.klingai.com/v1/videos/text2video/{task_id}",
        "kling_image": f"https://api.klingai.com/v1/videos/image2video/{task_id}",
        "kling": f"https://api.klingai.com/v1/videos/text2video/{task_id}",
        "runway": f"https://api.dev.runwayml.com/v1/tasks/{task_id}",
        "wan21": f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
        "luma": f"https://api.lumalabs.ai/dream-machine/v1/generations/{task_id}",
    }
    poll_endpoint = endpoint_map.get(provider, "")
    if not poll_endpoint:
        return json.dumps({"error": f"Unknown provider: {provider}"})

    headers: dict[str, str] = {}
    if provider == "kling" or provider.startswith("kling"):
        ak = os.getenv("KLING_ACCESS_KEY", "")
        sk = os.getenv("KLING_SECRET_KEY", "")
        if ak and sk:
            headers["Authorization"] = f"Bearer {_kling_jwt(ak, sk)}"
    elif provider == "runway":
        headers["Authorization"] = f"Bearer {os.getenv('RUNWAY_API_KEY', '')}"
        headers["X-Runway-Version"] = "2024-11-06"
    elif provider == "wan21":
        headers["Authorization"] = f"Bearer {os.getenv('ALIBABA_DASHSCOPE_API_KEY', os.getenv('DASHSCOPE_API_KEY', ''))}"
    elif provider == "luma":
        headers["Authorization"] = f"Bearer {os.getenv('LUMAAI_API_KEY', '')}"

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(poll_endpoint, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return json.dumps({"error": str(e), "task_id": task_id, "provider": provider})

    prov_key = "kling" if provider.startswith("kling") else provider
    status = _extract_status(data, prov_key)
    video_url = _extract_video_url(data, prov_key) if status in ("succeeded", "completed", "succeed") else ""

    result: dict[str, Any] = {
        "task_id": task_id,
        "provider": provider,
        "status": status,
        "video_url": video_url,
    }

    is_done = status in ("succeeded", "completed", "succeed")
    if is_done and video_url and download_on_complete:
        try:
            out_dir = _outputs_dir()
            fname = output_filename or f"video_{task_id[:8]}.mp4"
            out_path = out_dir / fname
            with httpx.Client(timeout=300, follow_redirects=True) as client:
                with client.stream("GET", video_url) as r:
                    r.raise_for_status()
                    with open(out_path, "wb") as f:
                        for chunk in r.iter_bytes(65536):
                            f.write(chunk)
            result["local_path"] = str(out_path)
            result["usage_hint"] = (
                "Video downloaded. Use merge_videos, add_audio_to_video, "
                "or present_files to share with the user."
            )
        except Exception as e:
            result["download_error"] = str(e)
    elif not is_done:
        result["usage_hint"] = (
            f"Task still processing (status={status}). "
            "Call check_media_task again in 15–30 seconds."
        )
    elif is_done and not video_url:
        result["error"] = _extract_error(data, prov_key)

    return json.dumps(result, indent=2, ensure_ascii=False)

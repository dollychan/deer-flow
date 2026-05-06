"""
Image generation tools for the Director Agent.

Supports:
  - OpenAI DALL-E 3  (OPENAI_API_KEY)
  - Stability AI     (STABILITY_API_KEY)
  - Kling Image      (KLING_ACCESS_KEY + KLING_SECRET_KEY)
  - Volcano Engine   (VOLCENGINE_ACCESS_KEY + VOLCENGINE_SECRET_KEY)

Provider is resolved from config.yaml tool entry, then falls back to
whichever API key is present in the environment.

Usage in config.yaml:
    - name: generate_image
      group: media
      use: deerflow.community.media_generation.image_tools:generate_image_tool
      provider: openai        # openai | stability | kling | volcano
      default_size: "1024x1024"
      default_quality: hd
"""

from __future__ import annotations

import base64
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

# ---------------------------------------------------------------------------
# Sandbox output path (mirrors DeerFlow convention)
# ---------------------------------------------------------------------------
_OUTPUT_DIR = Path("/mnt/user-data/outputs")
_WORKSPACE_DIR = Path("/mnt/user-data/workspace")


def _outputs_dir() -> Path:
    """Return writable output directory, falling back to /tmp."""
    if _OUTPUT_DIR.exists():
        return _OUTPUT_DIR
    if _WORKSPACE_DIR.exists():
        return _WORKSPACE_DIR
    return Path("/tmp")


def _media_filename(prefix: str, ext: str) -> str:
    uid = uuid.uuid4().hex[:8]
    return f"{prefix}_{uid}.{ext}"


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _generate_openai(prompt: str, size: str, quality: str, style: str, n: int) -> list[dict]:
    """Generate images via OpenAI DALL-E 3."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    # DALL-E 3 supports: 1024x1024, 1792x1024, 1024x1792
    valid_sizes = {"1024x1024", "1792x1024", "1024x1792"}
    if size not in valid_sizes:
        size = "1024x1024"

    payload = {
        "model": "dall-e-3",
        "prompt": prompt,
        "n": min(n, 1),  # DALL-E 3 only supports n=1
        "size": size,
        "quality": quality if quality in ("standard", "hd") else "standard",
        "style": style if style in ("vivid", "natural") else "vivid",
        "response_format": "url",
    }

    with httpx.Client(timeout=120) as client:
        resp = client.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    return [
        {
            "url": item.get("url", ""),
            "revised_prompt": item.get("revised_prompt", prompt),
            "provider": "openai",
        }
        for item in data.get("data", [])
    ]


def _generate_stability(prompt: str, size: str, style: str, negative_prompt: str) -> list[dict]:
    """Generate images via Stability AI (SDXL / SD3)."""
    api_key = os.getenv("STABILITY_API_KEY", "")
    if not api_key:
        raise ValueError("STABILITY_API_KEY is not set")

    # Parse width/height from size string
    try:
        w, h = (int(x) for x in size.split("x"))
    except Exception:
        w, h = 1024, 1024

    payload: dict[str, Any] = {
        "text_prompts": [{"text": prompt, "weight": 1.0}],
        "cfg_scale": 7,
        "height": h,
        "width": w,
        "samples": 1,
        "steps": 30,
    }
    if negative_prompt:
        payload["text_prompts"].append({"text": negative_prompt, "weight": -1.0})
    if style:
        payload["style_preset"] = style

    with httpx.Client(timeout=120) as client:
        resp = client.post(
            "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for artifact in data.get("artifacts", []):
        b64 = artifact.get("base64", "")
        if b64:
            fname = _media_filename("stability", "png")
            out_path = _outputs_dir() / fname
            out_path.write_bytes(base64.b64decode(b64))
            results.append({
                "url": f"file://{out_path}",
                "local_path": str(out_path),
                "provider": "stability",
            })
    return results


def _generate_kling_image(prompt: str, size: str, negative_prompt: str) -> list[dict]:
    """Generate images via Kling Image API (Kuaishou)."""
    import hmac
    import hashlib as _hashlib
    import time as _time

    ak = os.getenv("KLING_ACCESS_KEY", "")
    sk = os.getenv("KLING_SECRET_KEY", "")
    if not ak or not sk:
        raise ValueError("KLING_ACCESS_KEY and KLING_SECRET_KEY must be set")

    # --- JWT for Kling ---
    def _kling_jwt(ak: str, sk: str) -> str:
        import json as _json
        header = base64.urlsafe_b64encode(
            _json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        now = int(_time.time())
        payload_b64 = base64.urlsafe_b64encode(
            _json.dumps({"iss": ak, "exp": now + 1800, "nbf": now - 5}).encode()
        ).rstrip(b"=").decode()
        sig = base64.urlsafe_b64encode(
            hmac.new(sk.encode(), f"{header}.{payload_b64}".encode(), _hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        return f"{header}.{payload_b64}.{sig}"

    token = _kling_jwt(ak, sk)

    aspect_map = {
        "1024x1024": "1:1",
        "1792x1024": "16:9",
        "1024x1792": "9:16",
        "1280x720": "16:9",
        "720x1280": "9:16",
    }
    aspect_ratio = aspect_map.get(size, "1:1")

    payload = {
        "model_name": "kling-v1",
        "prompt": prompt,
        "negative_prompt": negative_prompt or "",
        "image_count": 1,
        "aspect_ratio": aspect_ratio,
    }

    with httpx.Client(timeout=120) as client:
        resp = client.post(
            "https://api.klingai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    images = data.get("data", {}).get("works", [])
    results = []
    for img in images:
        url = img.get("resource_list", [{}])[0].get("resource", "")
        if url:
            results.append({"url": url, "provider": "kling"})
    return results


def _resolve_provider(tool_config: Any) -> str:
    """Determine which image-gen provider to use."""
    if tool_config and "provider" in (tool_config.model_extra or {}):
        return tool_config.model_extra["provider"]
    # Fallback: pick based on available env vars
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("STABILITY_API_KEY"):
        return "stability"
    if os.getenv("KLING_ACCESS_KEY"):
        return "kling"
    return "openai"


def _download_to_local(url: str, output_dir: Path, ext: str = "png") -> str:
    """Download a remote URL to a local path, return local path string."""
    if url.startswith("file://"):
        return url[7:]
    fname = _media_filename("img", ext)
    out_path = output_dir / fname
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
    return str(out_path)


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------

@tool("generate_image", parse_docstring=True)
def generate_image_tool(
    prompt: str,
    size: str = "1024x1024",
    quality: str = "standard",
    style: str = "vivid",
    negative_prompt: str = "",
    save_local: bool = True,
) -> str:
    """Generate an image from a text prompt.

    Use this tool to create images for storyboard frames, scene illustrations,
    character portraits, product shots, or any visual asset the director needs.
    Before calling, consider searching for reference images with `image_search`.

    Args:
        prompt: Detailed description of the image to generate. Include style, lighting,
            composition, color palette, and mood. More detail = better results.
            Example: "Cinematic wide shot of a futuristic Tokyo skyline at golden hour,
            neon reflections on wet streets, blade runner aesthetic, 8k"
        size: Image dimensions. Options: "1024x1024" (square), "1792x1024" (landscape 16:9),
            "1024x1792" (portrait 9:16). Default: "1024x1024"
        quality: Output quality. Options: "standard" (faster), "hd" (higher detail, slower).
            Default: "standard"
        style: Visual style for OpenAI provider. Options: "vivid" (dramatic/hyper-real),
            "natural" (more realistic). Default: "vivid"
        negative_prompt: Elements to avoid in the image (used by Stability AI / Kling).
            Example: "blurry, watermark, text, low quality, distorted"
        save_local: If True (default), download the image to /mnt/user-data/outputs/
            and return the local path. If False, return only the remote URL.
    """
    try:
        from deerflow.config import get_app_config
        tool_config = get_app_config().get_tool_config("generate_image")
    except Exception:
        tool_config = None

    provider = _resolve_provider(tool_config)
    logger.info("generate_image: provider=%s size=%s", provider, size)

    try:
        if provider == "openai":
            results = _generate_openai(prompt, size, quality, style, n=1)
        elif provider == "stability":
            results = _generate_stability(prompt, size, style, negative_prompt)
        elif provider == "kling":
            results = _generate_kling_image(prompt, size, negative_prompt)
        else:
            return json.dumps({"error": f"Unknown provider: {provider}"})
    except Exception as e:
        logger.exception("generate_image failed")
        return json.dumps({"error": str(e), "provider": provider})

    if not results:
        return json.dumps({"error": "No images returned from provider", "provider": provider})

    out_dir = _outputs_dir()
    output_results = []
    for r in results:
        entry = dict(r)
        if save_local and r.get("url", "").startswith("http"):
            try:
                local_path = _download_to_local(r["url"], out_dir)
                entry["local_path"] = local_path
                entry["sandbox_path"] = local_path  # path visible inside sandbox
            except Exception as dl_err:
                entry["download_error"] = str(dl_err)
        output_results.append(entry)

    return json.dumps({
        "status": "success",
        "provider": provider,
        "prompt": prompt,
        "images": output_results,
        "usage_hint": (
            "Use the 'local_path' or 'sandbox_path' in further tools like "
            "generate_video_from_image or create_slideshow. "
            "Present the file to the user with present_files tool."
        ),
    }, indent=2, ensure_ascii=False)


@tool("generate_image_from_image", parse_docstring=True)
def generate_image_from_image_tool(
    source_image_path: str,
    prompt: str,
    strength: float = 0.75,
    size: str = "1024x1024",
    negative_prompt: str = "",
) -> str:
    """Transform or modify an existing image using a text prompt (image-to-image).

    Use this to apply style transfers, modify specific elements, or create
    variations of an existing frame or reference image.

    Args:
        source_image_path: Path to the source image inside the sandbox
            (e.g., /mnt/user-data/outputs/img_abc123.png) or a remote URL.
        prompt: Description of the desired output. Describe what to change
            or the overall style to apply. Example: "Watercolor painting style,
            soft brushstrokes, warm pastel tones"
        strength: How much to transform the source (0.0 = keep original, 1.0 = full
            transformation). Default: 0.75. Values 0.5–0.85 work best.
        size: Output dimensions. Default: "1024x1024"
        negative_prompt: Elements to avoid. Example: "photorealistic, dark, gloomy"
    """
    api_key = os.getenv("STABILITY_API_KEY", "")
    if not api_key:
        return json.dumps({"error": "generate_image_from_image requires STABILITY_API_KEY"})

    try:
        if source_image_path.startswith("http"):
            img_bytes = httpx.get(source_image_path, timeout=30).content
        else:
            img_bytes = Path(source_image_path).read_bytes()
    except Exception as e:
        return json.dumps({"error": f"Failed to read source image: {e}"})

    try:
        w, h = (int(x) for x in size.split("x"))
    except Exception:
        w, h = 1024, 1024

    with httpx.Client(timeout=120) as client:
        files = {"init_image": ("image.png", img_bytes, "image/png")}
        data: dict[str, Any] = {
            "text_prompts[0][text]": prompt,
            "text_prompts[0][weight]": "1",
            "cfg_scale": "7",
            "image_strength": str(1.0 - strength),
            "samples": "1",
            "steps": "30",
            "width": str(w),
            "height": str(h),
        }
        if negative_prompt:
            data["text_prompts[1][text]"] = negative_prompt
            data["text_prompts[1][weight]"] = "-1"

        try:
            resp = client.post(
                "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/image-to-image",
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                files=files,
                data=data,
            )
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            logger.exception("img2img failed")
            return json.dumps({"error": str(e)})

    out_dir = _outputs_dir()
    output_paths = []
    for artifact in result.get("artifacts", []):
        b64 = artifact.get("base64", "")
        if b64:
            fname = _media_filename("img2img", "png")
            out_path = out_dir / fname
            out_path.write_bytes(base64.b64decode(b64))
            output_paths.append(str(out_path))

    return json.dumps({
        "status": "success",
        "source_image": source_image_path,
        "prompt": prompt,
        "output_images": output_paths,
        "usage_hint": "Use local paths in create_slideshow or generate_video_from_image tools.",
    }, indent=2, ensure_ascii=False)


@tool("download_media", parse_docstring=True)
def download_media_tool(
    url: str,
    filename: str = "",
    output_subdir: str = "",
) -> str:
    """Download a remote media file (image or video) to the sandbox outputs folder.

    Use this to save generated images/videos that were returned as URLs by
    generation APIs, so they are available for further editing tools.

    Args:
        url: Remote URL of the media file to download.
        filename: Optional custom filename (e.g., "scene_01.mp4"). If empty,
            a unique name is auto-generated.
        output_subdir: Optional subdirectory inside outputs/ (e.g., "frames").
            Will be created if it does not exist.
    """
    out_base = _outputs_dir()
    if output_subdir:
        out_dir = out_base / output_subdir
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = out_base

    if not filename:
        ext = url.split("?")[0].rsplit(".", 1)[-1] if "." in url.split("?")[0].rsplit("/", 1)[-1] else "bin"
        ext = ext[:5]  # guard against long query strings
        filename = _media_filename("media", ext)

    out_path = out_dir / filename

    try:
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(out_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
    except Exception as e:
        logger.exception("download_media failed for url=%s", url)
        return json.dumps({"error": str(e), "url": url})

    size_mb = out_path.stat().st_size / (1024 * 1024)
    return json.dumps({
        "status": "success",
        "url": url,
        "local_path": str(out_path),
        "size_mb": round(size_mb, 2),
        "usage_hint": "Use 'local_path' in video editing tools or present_files to share with user.",
    }, indent=2, ensure_ascii=False)

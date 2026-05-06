"""
Video editing tools for the Director Agent — powered by FFmpeg.

Provides local, offline video editing operations that require no external API:
  - Inspect video metadata
  - Trim / cut clips
  - Concatenate / merge multiple clips
  - Add audio track (voiceover, music, sound effects)
  - Burn in subtitles from SRT file
  - Create slideshow from images (for storyboard animatics)
  - Extract frames as images

All operations run FFmpeg inside the sandbox via subprocess.
FFmpeg must be installed in the sandbox environment:
    apt-get install -y ffmpeg   # or: conda install ffmpeg

Usage in config.yaml:
    - name: get_video_info
      group: media:edit
      use: deerflow.community.media_generation.video_edit_tools:get_video_info_tool

    - name: trim_video
      group: media:edit
      use: deerflow.community.media_generation.video_edit_tools:trim_video_tool

    - name: merge_videos
      group: media:edit
      use: deerflow.community.media_generation.video_edit_tools:merge_videos_tool

    - name: add_audio_to_video
      group: media:edit
      use: deerflow.community.media_generation.video_edit_tools:add_audio_to_video_tool

    - name: add_subtitles_to_video
      group: media:edit
      use: deerflow.community.media_generation.video_edit_tools:add_subtitles_to_video_tool

    - name: create_slideshow
      group: media:edit
      use: deerflow.community.media_generation.video_edit_tools:create_slideshow_tool

    - name: extract_video_frames
      group: media:edit
      use: deerflow.community.media_generation.video_edit_tools:extract_video_frames_tool
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path

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


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _ffmpeg_available() -> bool:
    return subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0


def _run_ffmpeg(args: list[str], timeout: int = 300) -> tuple[int, str, str]:
    """Run FFmpeg with the given arguments. Returns (returncode, stdout, stderr)."""
    cmd = ["ffmpeg", "-y"] + args
    logger.debug("FFmpeg cmd: %s", " ".join(shlex.quote(a) for a in cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def _ffprobe(path: str) -> dict:
    """Run ffprobe and return stream/format info as dict."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {"error": result.stderr}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "Failed to parse ffprobe output"}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool("get_video_info", parse_docstring=True)
def get_video_info_tool(video_path: str) -> str:
    """Get metadata about a video file: duration, resolution, codec, frame rate, audio.

    Use this before editing to understand the properties of a video clip,
    especially before merging videos that may have different resolutions or codecs.

    Args:
        video_path: Path to the video file inside the sandbox
            (e.g., /mnt/user-data/outputs/scene_01.mp4).
    """
    if not _ffmpeg_available():
        return json.dumps({"error": "ffmpeg/ffprobe not installed in sandbox"})

    info = _ffprobe(video_path)
    if "error" in info:
        return json.dumps({"error": info["error"], "path": video_path})

    fmt = info.get("format", {})
    streams = info.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    summary = {
        "path": video_path,
        "duration_seconds": float(fmt.get("duration", 0)),
        "size_mb": round(int(fmt.get("size", 0)) / (1024 * 1024), 2),
        "format": fmt.get("format_name", ""),
        "video": {
            "codec": video_stream.get("codec_name", ""),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "fps": eval(video_stream.get("r_frame_rate", "0/1")),
            "pixel_format": video_stream.get("pix_fmt", ""),
        },
        "audio": {
            "codec": audio_stream.get("codec_name", ""),
            "sample_rate": audio_stream.get("sample_rate", ""),
            "channels": audio_stream.get("channels"),
        } if audio_stream else None,
    }
    return json.dumps(summary, indent=2, ensure_ascii=False)


@tool("trim_video", parse_docstring=True)
def trim_video_tool(
    input_path: str,
    start_time: str,
    end_time: str,
    output_filename: str = "",
    re_encode: bool = False,
) -> str:
    """Trim a video clip to a specific time range.

    Use this to cut clips from longer videos, extract specific scenes,
    or remove unwanted footage before merging.

    Args:
        input_path: Path to the source video file in the sandbox.
        start_time: Start time of the clip. Format: "HH:MM:SS", "MM:SS", or seconds
            as a float string (e.g., "0", "1:30", "00:01:30", "90.5").
        end_time: End time of the clip, same format as start_time.
            To trim to the end of the video, use the video's full duration.
        output_filename: Output file name (e.g., "scene_01_trimmed.mp4").
            Auto-generated if empty.
        re_encode: If False (default), use stream copy for fast, lossless trimming.
            Set True if stream copy produces glitchy output (rare with MP4/H.264).
    """
    if not _ffmpeg_available():
        return json.dumps({"error": "ffmpeg not installed in sandbox"})

    out_dir = _outputs_dir()
    out_fname = output_filename or f"trim_{_uid()}.mp4"
    out_path = str(out_dir / out_fname)

    args = ["-i", input_path, "-ss", start_time, "-to", end_time]
    if re_encode:
        args += ["-c:v", "libx264", "-c:a", "aac", "-preset", "fast"]
    else:
        args += ["-c", "copy"]
    args.append(out_path)

    rc, stdout, stderr = _run_ffmpeg(args, timeout=120)
    if rc != 0:
        return json.dumps({
            "error": "FFmpeg trim failed",
            "ffmpeg_stderr": stderr[-2000:],
            "command_hint": "Try re_encode=True if stream copy fails",
        })

    size_mb = Path(out_path).stat().st_size / (1024 * 1024) if Path(out_path).exists() else 0
    return json.dumps({
        "status": "success",
        "output_path": out_path,
        "size_mb": round(size_mb, 2),
        "start": start_time,
        "end": end_time,
        "usage_hint": "Use merge_videos to combine multiple trimmed clips.",
    }, indent=2, ensure_ascii=False)


@tool("merge_videos", parse_docstring=True)
def merge_videos_tool(
    input_paths: list[str],
    output_filename: str = "",
    normalize_resolution: bool = True,
    target_resolution: str = "1920x1080",
    transition: str = "none",
) -> str:
    """Concatenate multiple video clips into a single video.

    Use this to assemble the final video from individual scene clips
    generated by generate_video_from_text or generate_video_from_image.
    Clips are joined in the order provided.

    Args:
        input_paths: Ordered list of video file paths to concatenate.
            All videos should ideally have the same resolution and codec.
            Example: ["/mnt/user-data/outputs/scene_01.mp4", "/mnt/user-data/outputs/scene_02.mp4"]
        output_filename: Name for the merged output file. Default: auto-generated.
        normalize_resolution: If True (default), re-encode all clips to a common
            resolution before merging. Required when clips have different sizes.
        target_resolution: Resolution to normalize to (e.g., "1920x1080", "1280x720").
            Only used when normalize_resolution=True. Default: "1920x1080"
        transition: Transition between clips. Options: "none" (cut, default),
            "fade" (brief black fade). Note: "fade" requires re-encoding.
    """
    if not _ffmpeg_available():
        return json.dumps({"error": "ffmpeg not installed in sandbox"})
    if not input_paths:
        return json.dumps({"error": "No input paths provided"})

    out_dir = _outputs_dir()
    out_fname = output_filename or f"merged_{_uid()}.mp4"
    out_path = str(out_dir / out_fname)

    # Write concat list file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        concat_file = tmp.name
        for p in input_paths:
            tmp.write(f"file '{p}'\n")

    try:
        if not normalize_resolution and transition == "none":
            # Fast path: stream copy concat
            args = [
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c", "copy",
                out_path,
            ]
            rc, stdout, stderr = _run_ffmpeg(args, timeout=300)
        else:
            # Re-encode path — handle different resolutions / transitions
            w, h = target_resolution.split("x") if "x" in target_resolution else ("1920", "1080")
            filter_parts = []
            input_args = []
            for i, p in enumerate(input_paths):
                input_args += ["-i", p]
                filter_parts.append(
                    f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}];"
                    f"[{i}:a]aresample=44100[a{i}];"
                )
            n = len(input_paths)
            concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
            filter_str = "".join(filter_parts) + f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"
            args = (
                input_args
                + ["-filter_complex", filter_str,
                   "-map", "[outv]", "-map", "[outa]",
                   "-c:v", "libx264", "-c:a", "aac",
                   "-preset", "fast", "-crf", "23",
                   out_path]
            )
            rc, stdout, stderr = _run_ffmpeg(args, timeout=600)
    finally:
        os.unlink(concat_file)

    if rc != 0:
        return json.dumps({
            "error": "FFmpeg merge failed",
            "ffmpeg_stderr": stderr[-2000:],
        })

    size_mb = Path(out_path).stat().st_size / (1024 * 1024) if Path(out_path).exists() else 0
    return json.dumps({
        "status": "success",
        "output_path": out_path,
        "clips_merged": len(input_paths),
        "size_mb": round(size_mb, 2),
        "usage_hint": "Use add_audio_to_video to add narration or music, or present_files to share.",
    }, indent=2, ensure_ascii=False)


@tool("add_audio_to_video", parse_docstring=True)
def add_audio_to_video_tool(
    video_path: str,
    audio_path: str,
    output_filename: str = "",
    mode: str = "replace",
    audio_volume: float = 1.0,
    music_volume: float = 0.3,
    fade_out_seconds: float = 0.0,
) -> str:
    """Add, replace, or mix an audio track into a video.

    Use this to add voiceover narration, background music, or sound effects
    to the final assembled video. Supports replacing the existing audio or
    mixing it with a new track.

    Args:
        video_path: Path to the video file in the sandbox.
        audio_path: Path to the audio file (MP3, WAV, AAC, M4A, OGG) in the sandbox.
            This can be a voiceover recording or a music file.
        output_filename: Output file name. Auto-generated if empty.
        mode: How to handle audio mixing.
            - "replace": Remove existing audio, use only the new audio track (default).
            - "mix": Mix the new audio with the existing video audio
              (use audio_volume and music_volume to control levels).
            - "overlay": Add new audio alongside existing audio at equal volumes.
        audio_volume: Volume multiplier for the new audio track (mode=mix only).
            1.0 = 100% volume. Default: 1.0
        music_volume: Volume multiplier for the original video audio (mode=mix only).
            0.3 = 30% volume (background music). Default: 0.3
        fade_out_seconds: Duration of audio fade-out at the end of the video.
            0 = no fade. Default: 0.0
    """
    if not _ffmpeg_available():
        return json.dumps({"error": "ffmpeg not installed in sandbox"})

    out_dir = _outputs_dir()
    out_fname = output_filename or f"audio_{_uid()}.mp4"
    out_path = str(out_dir / out_fname)

    if mode == "replace":
        args = [
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            out_path,
        ]
    elif mode in ("mix", "overlay"):
        av = audio_volume
        mv = music_volume if mode == "mix" else 1.0
        filter_str = (
            f"[0:a]volume={mv}[oa];"
            f"[1:a]volume={av}[na];"
            f"[oa][na]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        args = [
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", filter_str,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            out_path,
        ]
    else:
        return json.dumps({"error": f"Unknown mode: {mode}. Use replace, mix, or overlay."})

    rc, stdout, stderr = _run_ffmpeg(args, timeout=300)
    if rc != 0:
        return json.dumps({
            "error": "FFmpeg audio mixing failed",
            "ffmpeg_stderr": stderr[-2000:],
        })

    # Optional fade-out pass
    if fade_out_seconds > 0 and Path(out_path).exists():
        try:
            probe = _ffprobe(out_path)
            duration = float(probe.get("format", {}).get("duration", 0))
            fade_start = max(0, duration - fade_out_seconds)
            tmp_fade = out_path.replace(".mp4", "_fade.mp4")
            fade_args = [
                "-i", out_path,
                "-af", f"afade=t=out:st={fade_start:.2f}:d={fade_out_seconds:.2f}",
                "-c:v", "copy", "-c:a", "aac",
                tmp_fade,
            ]
            fr, _, fe = _run_ffmpeg(fade_args, timeout=120)
            if fr == 0:
                os.replace(tmp_fade, out_path)
        except Exception as e:
            logger.warning("fade_out failed: %s", e)

    size_mb = Path(out_path).stat().st_size / (1024 * 1024) if Path(out_path).exists() else 0
    return json.dumps({
        "status": "success",
        "output_path": out_path,
        "mode": mode,
        "size_mb": round(size_mb, 2),
        "usage_hint": "Use add_subtitles_to_video to burn captions, or present_files to share.",
    }, indent=2, ensure_ascii=False)


@tool("add_subtitles_to_video", parse_docstring=True)
def add_subtitles_to_video_tool(
    video_path: str,
    subtitles_path: str,
    output_filename: str = "",
    font_size: int = 24,
    font_color: str = "white",
    position: str = "bottom",
    outline: bool = True,
) -> str:
    """Burn subtitles from an SRT file into a video.

    Use this to add translated captions, narration captions, or dialogue
    subtitles to the final video. Subtitles are permanently burned into the video.

    Args:
        video_path: Path to the video file in the sandbox.
        subtitles_path: Path to the SRT subtitle file in the sandbox.
            The SRT file must follow standard SubRip format with timing and text.
        output_filename: Output file name. Auto-generated if empty.
        font_size: Font size in points. Default: 24
        font_color: Subtitle text color. Options: "white", "yellow", "cyan",
            or any FFmpeg color string (e.g., "0xFFFFFF"). Default: "white"
        position: Subtitle position. Options: "bottom" (default), "top", "center".
        outline: If True (default), add a black outline around text for readability.
    """
    if not _ffmpeg_available():
        return json.dumps({"error": "ffmpeg not installed in sandbox"})

    out_dir = _outputs_dir()
    out_fname = output_filename or f"subs_{_uid()}.mp4"
    out_path = str(out_dir / out_fname)

    position_map = {
        "bottom": "Alignment=2,MarginV=20",
        "top": "Alignment=8,MarginV=20",
        "center": "Alignment=5",
    }
    align = position_map.get(position, "Alignment=2,MarginV=20")
    outline_val = "2" if outline else "0"

    # Escape the subtitles path for FFmpeg filter
    subs_escaped = subtitles_path.replace("\\", "/").replace(":", "\\:")
    force_style = (
        f"FontSize={font_size},PrimaryColour=&H{_color_to_bgr(font_color)},"
        f"OutlineColour=&H00000000,Outline={outline_val},{align}"
    )

    args = [
        "-i", video_path,
        "-vf", f"subtitles='{subs_escaped}':force_style='{force_style}'",
        "-c:a", "copy",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        out_path,
    ]

    rc, stdout, stderr = _run_ffmpeg(args, timeout=300)
    if rc != 0:
        return json.dumps({
            "error": "FFmpeg subtitle burn failed",
            "ffmpeg_stderr": stderr[-2000:],
            "tip": "Ensure FFmpeg was compiled with --enable-libass",
        })

    size_mb = Path(out_path).stat().st_size / (1024 * 1024) if Path(out_path).exists() else 0
    return json.dumps({
        "status": "success",
        "output_path": out_path,
        "size_mb": round(size_mb, 2),
        "usage_hint": "Use present_files to share the final video with the user.",
    }, indent=2, ensure_ascii=False)


def _color_to_bgr(color: str) -> str:
    """Convert common color names to ASS BGR hex (for FFmpeg subtitle style)."""
    color_map = {
        "white": "FFFFFF",
        "yellow": "00FFFF",
        "cyan": "FFFF00",
        "red": "0000FF",
        "green": "00FF00",
        "blue": "FF0000",
    }
    if color.startswith("0x"):
        return color[2:].upper().zfill(6)
    return color_map.get(color.lower(), "FFFFFF")


@tool("create_slideshow", parse_docstring=True)
def create_slideshow_tool(
    image_paths: list[str],
    duration_per_image: float = 3.0,
    output_filename: str = "",
    transition: str = "fade",
    transition_duration: float = 0.5,
    fps: int = 25,
    resolution: str = "1920x1080",
    audio_path: str = "",
) -> str:
    """Create a video slideshow from a sequence of images.

    Use this to create storyboard animatics, photo montages, or concept
    preview videos from generated or reference images. Essential for
    previewing the visual flow before committing to full video generation.

    Args:
        image_paths: Ordered list of image paths in the sandbox.
            Example: ["/mnt/user-data/outputs/frame_01.png", "/mnt/user-data/outputs/frame_02.png"]
        duration_per_image: How many seconds each image is displayed. Default: 3.0
        output_filename: Output video filename. Auto-generated if empty.
        transition: Transition effect between images.
            Options: "none" (hard cut), "fade" (cross-fade, default), "dissolve".
        transition_duration: Duration of the transition in seconds. Default: 0.5
        fps: Output video frame rate. Default: 25
        resolution: Output resolution as "WxH". Default: "1920x1080"
        audio_path: Optional path to a background audio file (MP3/WAV) to mix in.
            Leave empty for silent slideshow.
    """
    if not _ffmpeg_available():
        return json.dumps({"error": "ffmpeg not installed in sandbox"})
    if not image_paths:
        return json.dumps({"error": "No image paths provided"})

    out_dir = _outputs_dir()
    out_fname = output_filename or f"slideshow_{_uid()}.mp4"
    out_path = str(out_dir / out_fname)
    w, h = resolution.split("x") if "x" in resolution else ("1920", "1080")

    if transition == "none":
        # Simple concat approach: each image scaled and held for duration
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            concat_file = tmp.name
            for p in image_paths:
                tmp.write(f"file '{p}'\nduration {duration_per_image}\n")
            # Repeat last frame to prevent premature end
            tmp.write(f"file '{image_paths[-1]}'\n")

        try:
            args = [
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                out_path,
            ]
            rc, stdout, stderr = _run_ffmpeg(args, timeout=300)
        finally:
            os.unlink(concat_file)
    else:
        # Cross-fade slideshow via xfade filter
        n = len(image_paths)
        input_args = []
        for p in image_paths:
            input_args += [
                "-loop", "1",
                "-t", str(duration_per_image + transition_duration),
                "-i", p,
            ]

        # Build xfade filter chain
        scale_parts = []
        for i in range(n):
            scale_parts.append(
                f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[s{i}];"
            )

        xfade_parts: list[str] = []
        prev = "s0"
        offset = duration_per_image
        for i in range(1, n):
            out_label = f"x{i}" if i < n - 1 else "outv"
            xfade_parts.append(
                f"[{prev}][s{i}]xfade=transition={transition if transition == 'dissolve' else 'fade'}:"
                f"duration={transition_duration}:offset={offset:.2f}[{out_label}];"
            )
            prev = out_label
            offset += duration_per_image

        filter_str = "".join(scale_parts) + "".join(xfade_parts)
        filter_str = filter_str.rstrip(";")

        args = (
            input_args
            + ["-filter_complex", filter_str,
               "-map", "[outv]",
               "-c:v", "libx264", "-preset", "fast", "-crf", "23",
               out_path]
        )
        rc, stdout, stderr = _run_ffmpeg(args, timeout=600)

    if rc != 0:
        return json.dumps({
            "error": "FFmpeg slideshow creation failed",
            "ffmpeg_stderr": stderr[-2000:],
        })

    # Add audio if provided
    if audio_path and Path(out_path).exists():
        tmp_audio = out_path.replace(".mp4", "_audio.mp4")
        audio_args = [
            "-i", out_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            tmp_audio,
        ]
        ar, _, ae = _run_ffmpeg(audio_args, timeout=120)
        if ar == 0:
            os.replace(tmp_audio, out_path)

    size_mb = Path(out_path).stat().st_size / (1024 * 1024) if Path(out_path).exists() else 0
    return json.dumps({
        "status": "success",
        "output_path": out_path,
        "total_images": len(image_paths),
        "estimated_duration_seconds": len(image_paths) * duration_per_image,
        "size_mb": round(size_mb, 2),
        "usage_hint": (
            "Review the slideshow as a storyboard animatic. "
            "Use add_audio_to_video to add narration, or present_files to share."
        ),
    }, indent=2, ensure_ascii=False)


@tool("extract_video_frames", parse_docstring=True)
def extract_video_frames_tool(
    video_path: str,
    fps: float = 1.0,
    start_time: str = "0",
    end_time: str = "",
    max_frames: int = 30,
    output_format: str = "png",
    output_subdir: str = "frames",
) -> str:
    """Extract frames from a video as image files.

    Use this to pull still frames from a generated video for review, to create
    reference images for subsequent generation steps, or to extract key frames
    for the storyboard.

    Args:
        video_path: Path to the video file in the sandbox.
        fps: Number of frames to extract per second of video.
            1.0 = one frame per second, 0.5 = one frame every 2 seconds,
            5.0 = five frames per second. Default: 1.0
        start_time: Start time for frame extraction. Default: "0" (beginning).
        end_time: End time for frame extraction. Empty string = until end of video.
        max_frames: Maximum number of frames to extract. Default: 30
        output_format: Image format for extracted frames. Options: "png", "jpg". Default: "png"
        output_subdir: Subdirectory inside outputs/ to save frames. Default: "frames"
    """
    if not _ffmpeg_available():
        return json.dumps({"error": "ffmpeg not installed in sandbox"})

    out_base = _outputs_dir()
    frame_dir = out_base / output_subdir / _uid()
    frame_dir.mkdir(parents=True, exist_ok=True)

    frame_pattern = str(frame_dir / f"frame_%04d.{output_format}")

    args = ["-i", video_path, "-ss", start_time]
    if end_time:
        args += ["-to", end_time]
    args += [
        "-vf", f"fps={fps}",
        "-frames:v", str(max_frames),
        "-q:v", "2",
        frame_pattern,
    ]

    rc, stdout, stderr = _run_ffmpeg(args, timeout=120)
    if rc != 0:
        return json.dumps({
            "error": "FFmpeg frame extraction failed",
            "ffmpeg_stderr": stderr[-2000:],
        })

    extracted = sorted(str(p) for p in frame_dir.glob(f"*.{output_format}"))
    return json.dumps({
        "status": "success",
        "frames_extracted": len(extracted),
        "output_directory": str(frame_dir),
        "frame_paths": extracted,
        "usage_hint": (
            "Use extracted frame paths in generate_image_from_image for style transfer, "
            "or in create_slideshow to build an animatic."
        ),
    }, indent=2, ensure_ascii=False)

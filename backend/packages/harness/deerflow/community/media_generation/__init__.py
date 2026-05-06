"""
Media generation community tools for DeerFlow.

Provides image generation, video generation, and video editing capabilities.

Supported providers:
  Image: OpenAI DALL-E 3, Stability AI, Kling (Kuaishou), ByteDance Volcano Engine
  Video: Kling (Kuaishou), RunwayML Gen-3, Wan2.1 (Alibaba), Luma Dream Machine
  Edit:  FFmpeg / MoviePy (local, no API key required)
"""

from .image_tools import (
    generate_image_tool,
    generate_image_from_image_tool,
    download_media_tool,
)
from .video_tools import (
    generate_video_from_text_tool,
    generate_video_from_image_tool,
    check_media_task_tool,
)
from .video_edit_tools import (
    get_video_info_tool,
    trim_video_tool,
    merge_videos_tool,
    add_audio_to_video_tool,
    add_subtitles_to_video_tool,
    create_slideshow_tool,
    extract_video_frames_tool,
)

__all__ = [
    # Image
    "generate_image_tool",
    "generate_image_from_image_tool",
    "download_media_tool",
    # Video generation
    "generate_video_from_text_tool",
    "generate_video_from_image_tool",
    "check_media_task_tool",
    # Video editing
    "get_video_info_tool",
    "trim_video_tool",
    "merge_videos_tool",
    "add_audio_to_video_tool",
    "add_subtitles_to_video_tool",
    "create_slideshow_tool",
    "extract_video_frames_tool",
]

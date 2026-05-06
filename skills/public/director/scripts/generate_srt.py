#!/usr/bin/env python3
"""
generate_srt.py — Auto-generate an SRT subtitle file from a timed narration list.

Usage (run via bash tool inside the DeerFlow sandbox):
    python3 /mnt/skills/public/director/scripts/generate_srt.py \
        --output /mnt/user-data/workspace/subtitles.srt \
        --narration '[{"text": "Welcome.", "start": 0.0, "duration": 3.0}, ...]'

Or import and call generate_srt() directly from a Python code block.

Input format (JSON list):
    [
        {"text": "Line of narration.", "start": 0.0, "duration": 4.5},
        {"text": "Second line.", "start": 5.0, "duration": 3.0},
        ...
    ]
"""

import argparse
import json
import sys
from pathlib import Path


def seconds_to_srt_time(seconds: float) -> str:
    """Convert float seconds to SRT timestamp: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(narration: list[dict], output_path: str) -> str:
    """
    Generate an SRT file from a list of timed narration entries.

    Args:
        narration: List of dicts with keys:
            - text (str): The subtitle text
            - start (float): Start time in seconds
            - duration (float): Duration in seconds
        output_path: Path to write the .srt file

    Returns:
        The SRT content as a string.
    """
    lines = []
    for i, entry in enumerate(narration, start=1):
        text = entry.get("text", "").strip()
        start = float(entry.get("start", 0))
        duration = float(entry.get("duration", 3))
        end = start + duration

        lines.append(str(i))
        lines.append(f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}")
        # Split long lines at 42 chars
        words = text.split()
        current_line = []
        srt_lines = []
        for word in words:
            if len(" ".join(current_line + [word])) > 42 and current_line:
                srt_lines.append(" ".join(current_line))
                current_line = [word]
            else:
                current_line.append(word)
        if current_line:
            srt_lines.append(" ".join(current_line))
        # Max 2 lines per entry
        lines.extend(srt_lines[:2])
        lines.append("")  # blank line separator

    content = "\n".join(lines)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(content, encoding="utf-8")
    print(f"SRT written to: {output_path}")
    print(f"Entries: {len(narration)}")
    return content


def main():
    parser = argparse.ArgumentParser(description="Generate SRT file from timed narration JSON")
    parser.add_argument("--output", required=True, help="Output .srt file path")
    parser.add_argument("--narration", required=True, help="JSON string of narration entries")
    args = parser.parse_args()

    try:
        narration = json.loads(args.narration)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    content = generate_srt(narration, args.output)
    print("--- Preview ---")
    print(content[:500])


if __name__ == "__main__":
    main()

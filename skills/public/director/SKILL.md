---
name: director
description: >
  End-to-end media production skill for the Director Agent. Guides through:
  1) Creative briefing and ideation, 2) Script and storyboard design,
  3) Image generation for each scene, 4) Video clip generation (Kling / RunwayML / Wan2.1 / Luma),
  5) Video editing and assembly (FFmpeg), 6) Audio mixing and subtitle addition,
  7) Final delivery. Trigger when the user asks to create a video, film, animation,
  image series, storyboard, or any visual production workflow.
---

# Director Skill — Media Production Workflow

You are operating as the **Director Agent**. Load this skill at the start of every
media production task and follow the structured workflow below.

## Structure

```
director/
├── SKILL.md                              ← You are here
├── references/
│   ├── storyboard_guide.md               ← Shot list templates and storyboard format
│   └── video_production_sop.md           ← Standard operating procedure for API usage
└── scripts/
    └── generate_srt.py                   ← Helper: auto-generate SRT from timed narration
```

---

## Phase 0 — Load References

Before starting any production, read the references:
```python
read_file("/mnt/skills/public/director/references/storyboard_guide.md")
read_file("/mnt/skills/public/director/references/video_production_sop.md")
```

---

## Phase 1 — BRIEF (ALWAYS first)

Use `ask_clarification` to gather the following before writing any script or
generating any asset. Do NOT skip this phase.

**Required information:**
- **Content**: What is the subject / message / story?
- **Format**: Duration (15s, 30s, 60s, 3min…), aspect ratio (16:9, 9:16, 1:1)
- **Style**: Realistic, 3D animated, illustrated, documentary, cinematic, AI-art
- **Tone**: Inspirational, educational, commercial, artistic, narrative
- **Audience**: Who will watch this?
- **Output**: Where will it be published? (YouTube, Instagram Reels, TikTok, website)
- **Audio**: Does the user have narration audio? Should you write a script for TTS?
  Should it be music-only?
- **References**: Any URLs, images, or examples to match the visual style?

---

## Phase 2 — SCRIPT & STORYBOARD

### 2.1 Write the Script

Structure the script as a table with these columns:
| # | Scene | Narration / Dialogue | Duration |
|---|-------|---------------------|----------|
| 1 | Opening | "Welcome to..." | 5s |

### 2.2 Write the Shot List

For each scene, define:
```
Scene N: [Scene Name]
- Shot Type: WS / MS / CU / ECU / OTS / aerial
- Action: What happens on screen
- Camera: static / slow pan left / dolly in / tracking
- Lighting: natural daylight / golden hour / studio / neon
- Color Palette: warm / cool / desaturated / vibrant
- Duration: Xs
- Image Prompt: [Full detailed prompt for generate_image]
- Video Prompt: [Motion description for generate_video_from_image]
- Audio Notes: [What happens in the audio at this point]
```

Read the shot list template:
```python
read_file("/mnt/skills/public/director/references/storyboard_guide.md")
```

**Checkpoint**: Present the script and shot list to the user. Get explicit approval
before Phase 3. Use `ask_clarification` if revisions are needed.

---

## Phase 3 — STORYBOARD PREVIEW (Image Generation)

### 3.1 Generate Key Frame Images

For each scene, call `generate_image` with the full image prompt from the shot list.

**Image prompt anatomy** (always include all elements):
```
[Subject + action], [setting + environment], [lighting], [camera angle], 
[color palette], [mood], [visual style], [quality suffix]
```

Example:
```
"A confident woman in a tailored suit walks through a glass-walled modern office,
golden afternoon light streaming through floor-to-ceiling windows, medium shot,
warm amber tones, aspirational corporate mood, cinematic 4K, photorealistic"
```

**Best practices:**
- Search for references first: `image_search(query="...")`
- Generate images in batches of 2–3 before showing user
- Use `view_image` to inspect each result
- If an image misses the mark, refine the prompt — don't just regenerate identically

### 3.2 Create Storyboard Preview

After all scene images are generated, build a slideshow animatic:
```python
create_slideshow(
    image_paths=[...all scene image paths...],
    duration_per_image=3.0,
    transition="fade",
    output_filename="storyboard_preview.mp4"
)
```

**Checkpoint**: Present the storyboard preview. Get user approval before video generation.

---

## Phase 4 — VIDEO PRODUCTION

Read the SOP before making API calls:
```python
read_file("/mnt/skills/public/director/references/video_production_sop.md")
```

### 4.1 Submit Video Generation Jobs

For each approved scene:

**Option A — Animate the storyboard image (recommended for consistency):**
```python
generate_video_from_image(
    image_path="/mnt/user-data/outputs/scene_01.png",
    prompt="[motion description from shot list]",
    duration=5,
    aspect_ratio="16:9",
    mode="std",
    wait_for_completion=False,  # Always async
)
```

**Option B — Text-to-video (when no image is needed):**
```python
generate_video_from_text(
    prompt="[full scene description]",
    duration=5,
    aspect_ratio="16:9",
    wait_for_completion=False,
)
```

Save all returned `task_id` and `provider` values in a tracking table:
| Scene | Task ID | Provider | Status |
|-------|---------|----------|--------|
| 1 | abc123 | kling | pending |

**Notify the user**: "I've submitted [N] video generation jobs. 
These will take approximately 2–5 minutes each. 
I'll continue working on the narration script / SRT / audio while we wait."

### 4.2 While Waiting — Parallel Work

While video jobs are processing, continue with:
- Write narration script for TTS (if audio is needed)
- Create SRT subtitle file (use the script from Phase 2)
- Download reference audio / music if user provided URLs
- Run `get_video_info` on any already-completed clips

### 4.3 Poll for Completion

After 2–3 minutes, poll each pending job:
```python
check_media_task(
    task_id="abc123",
    provider="kling",
    download_on_complete=True,
    output_filename="scene_01.mp4"
)
```

Repeat until all jobs are complete. Track status in the table above.

---

## Phase 5 — ASSEMBLY & POST-PRODUCTION

### 5.1 Inspect Clips

```python
get_video_info(video_path="/mnt/user-data/outputs/scene_01.mp4")
```

Check resolution and codec consistency before merging.

### 5.2 Trim Clips

```python
trim_video(
    input_path="/mnt/user-data/outputs/scene_01.mp4",
    start_time="0",
    end_time="4.5",
    output_filename="scene_01_trimmed.mp4"
)
```

### 5.3 Merge All Clips

```python
merge_videos(
    input_paths=[
        "/mnt/user-data/outputs/scene_01_trimmed.mp4",
        "/mnt/user-data/outputs/scene_02_trimmed.mp4",
        # ...
    ],
    output_filename="rough_cut.mp4",
    normalize_resolution=True,
    target_resolution="1920x1080"
)
```

### 5.4 Add Audio

```python
add_audio_to_video(
    video_path="/mnt/user-data/outputs/rough_cut.mp4",
    audio_path="/mnt/user-data/uploads/narration.mp3",
    output_filename="with_audio.mp4",
    mode="replace"  # or "mix" for background music + narration
)
```

### 5.5 Add Subtitles (Optional)

First, write the SRT file to workspace using `write_file`:
```
1
00:00:00,000 --> 00:00:04,500
Welcome to the future of work.

2
00:00:05,000 --> 00:00:09,000
Where technology and humanity converge.
```

Then burn subtitles:
```python
add_subtitles_to_video(
    video_path="/mnt/user-data/outputs/with_audio.mp4",
    subtitles_path="/mnt/user-data/workspace/subtitles.srt",
    output_filename="final_with_subs.mp4",
    font_size=28,
    font_color="white",
    outline=True
)
```

---

## Phase 6 — DELIVERY

```python
present_files(
    files=["/mnt/user-data/outputs/final_with_subs.mp4"],
    description="Final video — [Project Name]"
)
```

Provide a production summary to the user:
- Total scenes: N
- Total duration: Xs
- File size: X MB
- APIs used: [list providers]
- Output file: filename

---

## Troubleshooting Quick Reference

| Problem | Solution |
|---------|----------|
| Image looks wrong | Refine prompt: add/remove style keywords, change lighting description |
| Video clip is shaky | Add "smooth motion, stable camera" to video prompt |
| Merge fails with codec error | Set `normalize_resolution=True` in merge_videos |
| Audio out of sync | Use `trim_video` to adjust clip lengths before merging |
| Subtitles not rendering | Verify FFmpeg has libass: `bash -c "ffmpeg -version \| grep ass"` |
| Task polling returns "processing" | Wait 30–60 more seconds, Kling/RunwayML can take 3–8 min |
| Video task failed | Check the `error` field in check_media_task result; retry with different prompt |

# Video Production SOP — Director Agent API Reference

Standard Operating Procedure for using video generation APIs in the Director Agent.

---

## Provider Comparison Matrix

| Capability | Kling v1 | RunwayML Gen-3 | Wan2.1 | Luma Dream Machine |
|------------|----------|----------------|--------|-------------------|
| Text-to-video | ✅ | ✅ | ✅ | ✅ |
| Image-to-video | ✅ | ✅ | ❌ | ✅ |
| Max duration | 10s | 10s | 8s | ~5s |
| Aspect ratios | 16:9, 9:16, 1:1 | 1280:768, 768:1280 | 1280×720, 720×1280, 720×720 | 16:9, 9:16, 1:1, 4:3 |
| Quality modes | std / pro | turbo | turbo | standard |
| Avg gen time | 3–6 min | 2–5 min | 1–3 min | 1–4 min |
| Required ENV | KLING_ACCESS_KEY, KLING_SECRET_KEY | RUNWAY_API_KEY | ALIBABA_DASHSCOPE_API_KEY | LUMAAI_API_KEY |

---

## Image Generation Provider Comparison

| Capability | DALL-E 3 | Stability AI | Kling Image |
|------------|----------|-------------|-------------|
| Text-to-image | ✅ | ✅ | ✅ |
| Image-to-image | ❌ | ✅ | ❌ |
| Max resolution | 1792×1024 | 1024×1024 | 1:1, 16:9, 9:16 |
| Avg gen time | 15–30s | 20–40s | 30–60s |
| Required ENV | OPENAI_API_KEY | STABILITY_API_KEY | KLING_ACCESS_KEY + KLING_SECRET_KEY |

---

## Environment Variables Setup

Required environment variables (set in `.env` or system environment):

```bash
# Image Generation
OPENAI_API_KEY=sk-...          # DALL-E 3 image generation
STABILITY_API_KEY=sk-...       # Stability AI (image-to-image + text-to-image)

# Video Generation
KLING_ACCESS_KEY=...           # Kling text/image-to-video + image generation
KLING_SECRET_KEY=...           # Kling JWT secret
RUNWAY_API_KEY=...             # RunwayML Gen-3 video generation
ALIBABA_DASHSCOPE_API_KEY=...  # Wan2.1 text-to-video (Alibaba Cloud)
LUMAAI_API_KEY=...             # Luma Dream Machine video generation

# Rate limiting (optional tuning)
DIRECTOR_MAX_MEDIA_CALLS_PER_THREAD=20
DIRECTOR_MEDIA_PROGRESS_ENABLED=1
```

---

## Task Lifecycle (Async Video APIs)

All video generation APIs are asynchronous. Follow this lifecycle:

```
1. Submit job
   └─ Tool: generate_video_from_text / generate_video_from_image
   └─ Returns: { task_id, provider, poll_endpoint }
   └─ Action: Save task_id and provider

2. Work on other tasks while waiting
   └─ Typical wait: Kling 3–6 min, RunwayML 2–5 min, Wan2.1 1–3 min

3. Poll for status
   └─ Tool: check_media_task(task_id=..., provider=..., download_on_complete=True)
   └─ Returns: { status: "processing" | "completed" | "failed", video_url, local_path }
   └─ If "processing": wait 30–60s, poll again
   └─ If "completed": video is downloaded to local_path
   └─ If "failed": check error field, revise prompt, resubmit

4. Process completed video
   └─ Tools: trim_video, merge_videos, add_audio_to_video, etc.
```

---

## Prompt Engineering Best Practices

### For Kling (Best Results)

**Text-to-video prompts:**
```
[Main subject + action] + [environment] + [camera movement] + [visual style] + [mood]

Good: "A chef carefully plates a dish, golden kitchen lighting, 
medium close-up, smooth dolly right, cinematic food photography style, warm tones"

Avoid: Very short prompts, abstract concepts without grounding, conflicting styles
```

**Image-to-video motion prompts:**
```
Focus on: what moves, direction of movement, camera motion, atmosphere changes

Good: "The character turns slowly to look at the camera, 
slight smile forming, background city lights twinkling, gentle camera pull-back"

Avoid: Describing the image itself (it already knows); only describe what CHANGES
```

**Camera control (Kling Pro mode only):**
```python
camera_control = '{"type": "zoom_in"}'    # Zoom in
camera_control = '{"type": "pan_left"}'   # Pan left
camera_control = '{"type": "tilt_up"}'    # Tilt up
camera_control = '{"type": "truck_right"}' # Lateral move right
```

### For RunwayML Gen-3

```
Emphasize motion and cinematic quality:
"[Subject + motion description], [environment], [lighting], [quality keywords]"

Good: "A falcon diving at high speed through mountain clouds, 
aerial tracking shot, dramatic overcast lighting, 8K wildlife documentary"
```

### For Wan2.1

```
Works best with clear, concrete subjects and actions:
"[Specific action] + [clear environment] + [simple motion]"

Note: Wan2.1 is text-to-video only (no image-to-video via standard API)
Best for: Nature scenes, simple actions, abstract motion, architectural reveals
```

### For Luma Dream Machine

```
Responds well to cinematic and narrative descriptions:
"[Scene description with narrative context] + [atmosphere] + [camera work]"

Good: "A woman discovers a hidden garden through a stone archway,
sunlight streaming through leaves, she steps forward in wonder,
handheld camera slowly follows her, magical realism aesthetic"
```

---

## FFmpeg Operations Reference

### Checking FFmpeg Installation

```bash
# In bash tool:
ffmpeg -version
ffprobe -version
# Verify libass for subtitles:
ffmpeg -version 2>&1 | grep -E "libass|enable-libass"
```

### Installing FFmpeg (if missing)

```bash
# Ubuntu/Debian (sandbox):
apt-get install -y ffmpeg

# With libass for subtitles:
apt-get install -y ffmpeg libass-dev
```

### Common FFmpeg Patterns

**Re-encode for compatibility:**
```
-c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k
```

**Normalize for merge (when resolutions differ):**
```
-vf scale=1920:1080:force_original_aspect_ratio=decrease,
     pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1
```

**Check codec compatibility before merge:**
```python
get_video_info(video_path="scene_01.mp4")
# All clips must have same: width, height, fps, codec for stream-copy merge
# Different resolutions → use normalize_resolution=True in merge_videos
```

---

## Cost Management Guidelines

### API Cost Tiers (approximate, verify with provider pricing)

| Operation | Provider | Approximate Cost |
|-----------|----------|-----------------|
| Image (1024×1024) | DALL-E 3 | ~$0.04 |
| Image (HD) | DALL-E 3 | ~$0.08 |
| Image | Stability AI | ~$0.002–0.01 |
| Video (5s std) | Kling | ~$0.14 |
| Video (10s pro) | Kling | ~$0.56 |
| Video (5s) | RunwayML | ~$0.50 |
| Video (5s) | Luma | ~$0.02 |
| Video (720p) | Wan2.1 | ~$0.01–0.08 |

### Cost Reduction Strategies

1. **Iterate with images first** — Generate and approve all scene images ($0.04 each)
   before committing to video generation ($0.14–0.56 per clip)

2. **Use create_slideshow for previews** — A slideshow costs nothing (FFmpeg is local)
   and gives the user a chance to reject before expensive video calls

3. **Start with std quality** — Only upgrade to "pro" mode for the final approved version

4. **Shorter clips during development** — Use 5s clips during iteration; 10s only for finals

5. **Batch similar prompts** — If two scenes have similar style, generate them together
   rather than individually to check consistency

6. **Reuse generated assets** — A good base image can be reused with different motion prompts

---

## Error Handling Playbook

| Error | Cause | Resolution |
|-------|-------|-----------|
| `KLING_ACCESS_KEY not set` | Missing env var | Set env var; check `.env` file |
| Task status = "failed" | Prompt rejected or API error | Check error message; revise prompt |
| `ffmpeg: command not found` | FFmpeg not installed | Run `apt-get install -y ffmpeg` in bash tool |
| Merge fails (codec mismatch) | Different codecs/resolutions | Set `normalize_resolution=True` |
| Video too large | Long video or high quality | Reduce duration; use CRF 28 instead of 23 |
| Subtitle encoding error | Special characters in SRT | Encode SRT file as UTF-8 without BOM |
| Poll returns "processing" for >15 min | API issue or queue overload | Retry once; if still failing, resubmit job |
| Image download fails | URL expired | Most generation URLs expire in 1h; download immediately |

---

## Rate Limits (Approximate)

| Provider | Concurrent Jobs | Requests/min |
|----------|----------------|--------------|
| Kling | 3 | 10 |
| RunwayML | 5 | 20 |
| Wan2.1 | 10 | 30 |
| Luma | 3 | 10 |
| DALL-E 3 | 1 | 7 (tier 1) |
| Stability AI | 10 | 150 |

**Best practice:** Submit no more than 3 video jobs simultaneously.
Use the task tracking table in Phase 4 to manage job state.

# Storyboard Guide — Director Agent Reference

## Shot Type Reference

| Code | Name | Framing | Best For |
|------|------|---------|----------|
| EWS | Extreme Wide Shot | Entire environment, subject tiny | Establishing location, scale |
| WS | Wide Shot | Full subject + environment | Setting the scene |
| MS | Medium Shot | Waist up | Dialogue, character introduction |
| MCU | Medium Close-Up | Chest to head | Emotional moments |
| CU | Close-Up | Face / object | Emotion, product detail |
| ECU | Extreme Close-Up | Eyes / specific feature | Tension, intimacy |
| OTS | Over the Shoulder | Behind one subject toward another | Conversations |
| POV | Point of View | Camera = character's eyes | Immersive perspective |
| Aerial | Bird's Eye / Drone | Looking straight down or obliquely | Scale, geography |
| Dutch | Dutch Angle | Camera tilted | Unease, disorientation |

---

## Camera Movement Reference

| Movement | Description | Prompt Keywords |
|----------|-------------|-----------------|
| Static | Camera doesn't move | "static shot, locked-off camera" |
| Pan | Horizontal pivot | "slow pan left/right" |
| Tilt | Vertical pivot | "tilt up/down to reveal" |
| Dolly | Camera moves forward/backward | "dolly in/out" |
| Tracking | Camera moves parallel to subject | "tracking shot, following the subject" |
| Crane / Jib | Vertical arc | "crane shot rising up" |
| Handheld | Slight natural wobble | "handheld camera, slight shake, documentary" |
| Zoom | Optical zoom (not dolly) | "slow zoom in/out" |
| Drone | Aerial movement | "drone shot, aerial reveal" |

---

## Standard Shot List Template

Copy and fill this template for each production:

```markdown
## Production: [PROJECT NAME]
## Format: [16:9 / 9:16 / 1:1] | Duration: [total runtime]
## Style: [Realistic / Animated / Cinematic / Documentary]

---

### Scene 1: [Scene Name]
- Shot Type: [WS / MS / CU / etc.]
- Action: [What happens on screen]
- Camera: [static / pan / dolly / etc.]
- Lighting: [natural / golden hour / studio / neon / etc.]
- Color Palette: [warm / cool / vibrant / desaturated / etc.]
- Duration: [Xs]
- Image Prompt:
  ```
  [Full prompt for generate_image — include: subject, action, environment,
   lighting, camera angle, color, mood, style, quality keywords]
  ```
- Video Prompt:
  ```
  [Motion description for generate_video_from_image — describe what moves,
   camera movement, speed, atmosphere dynamics]
  ```
- Narration: "[Voiceover text at this scene]"
- SRT Timing: [00:00:00,000 --> 00:00:04,500]
- Music Notes: [Build / hold / fade / silence]

---

### Scene 2: [Scene Name]
[... repeat ...]
```

---

## Image Prompt Construction Formula

A strong image prompt has 7 components (all optional but recommended):

```
[SUBJECT + ACTION], [ENVIRONMENT + SETTING], [LIGHTING], [CAMERA ANGLE],
[COLOR PALETTE], [MOOD / ATMOSPHERE], [VISUAL STYLE], [QUALITY KEYWORDS]
```

### Quality Keywords by Style

**Photorealistic:**
```
cinematic 4K, photorealistic, high detail, professional photography,
sharp focus, natural light, ARRI Alexa, anamorphic lens
```

**Cinematic / Film:**
```
cinematic, film grain, anamorphic bokeh, shallow depth of field,
movie still, theatrical lighting, Kodak Portra, IMAX quality
```

**Animated / 3D:**
```
3D render, Pixar style, Unreal Engine 5, octane render,
subsurface scattering, global illumination, 4K render, artstation
```

**Illustration:**
```
digital illustration, concept art, painterly, loose brushstrokes,
color study, editorial illustration, gouache, Moebius style
```

**Documentary:**
```
documentary photography, candid, reportage, natural light,
handheld, grainy, photojournalism, authentic
```

### Negative Prompt Template

```
blurry, out of focus, watermark, text, logo, low quality, jpeg artifacts,
overexposed, underexposed, distorted, deformed, extra limbs, bad anatomy,
duplicate, low resolution
```

---

## SRT Subtitle Format

Standard SubRip format (.srt):

```
1
00:00:00,000 --> 00:00:04,500
First subtitle text.
Can span multiple lines.

2
00:00:05,000 --> 00:00:09,000
Second subtitle text.

3
00:00:09,500 --> 00:00:14,000
Third subtitle.
```

**Rules:**
- Index starts at 1
- Timestamps: `HH:MM:SS,mmm` (hours:minutes:seconds,milliseconds)
- Leave a blank line between entries
- Keep lines under 42 characters for readability
- Maximum 2 lines per subtitle entry

---

## Video Motion Prompt Guide

Good motion prompts describe what moves, how it moves, and at what pace:

**Camera-led motion:**
- "The camera slowly pulls back from a close-up of the flower, revealing the entire garden"
- "A smooth dolly shot gliding through the hallway, depth of field shifting"
- "Aerial drone rising above the cityscape, revealing the full skyline"

**Subject-led motion:**
- "The character walks confidently toward the camera, crowd blurring behind"
- "Hands pour steaming coffee into a white cup, steam curling upward"
- "Leaves rustling gently in a breeze, dappled sunlight dancing"

**Atmospheric motion:**
- "Clouds drift slowly across the sky, time-lapse style"
- "Rain falls softly, each drop catching the street lights"
- "Neon signs flicker and reflect in the wet pavement"

**Negative motion keywords (add to avoid):**
- "no shaky camera, smooth motion, no jitter, cinematic stability"

---

## Common Production Formats

| Platform | Ratio | Resolution | Duration | Notes |
|----------|-------|------------|----------|-------|
| YouTube | 16:9 | 1920×1080 | Any | Standard |
| Instagram Feed | 1:1 | 1080×1080 | ≤60s | Square |
| Instagram Reels | 9:16 | 1080×1920 | 15–90s | Vertical |
| TikTok | 9:16 | 1080×1920 | 15s–3min | Vertical |
| LinkedIn | 16:9 or 1:1 | 1280×720+ | 3s–30min | Professional |
| Twitter/X | 16:9 | 1280×720 | ≤2:20 | |
| Website hero | 16:9 | 1920×1080 | 15–30s | Loop-friendly |

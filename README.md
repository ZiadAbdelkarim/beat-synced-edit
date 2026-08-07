# Beat Synced Edits Pipeline

Automatic beat-synced video editing: drop in a song and raw footage, get a
beat-locked edit with zero manual cutting.

## Two ways to use it

**1. Pure CLI (deterministic, no AI).** Run the four stages below yourself.
Same inputs, same edit, every time.

**2. As a Claude Code skill (conversational).** The repo ships a skill at
`.claude/skills/beat-sync-edit/SKILL.md` — open this folder in
[Claude Code](https://claude.com/claude-code) and just describe the edit you
want:

> "cut my footage to the chorus, white flash on every drop, then make it 9:16"

Claude runs the same pipeline for you and layers ffmpeg effects at
beat-accurate timestamps — white flashes, stretch punches, hue shifts, RGB
split/glitch, speed ramps, shakes, color grades (full effects cookbook lives
in the skill file). You get the pipeline's determinism with natural-language
control over the creative layer.

## How it works — four deterministic stages

```
song.mp3 ──► beat_map.py ──► beats, energy curve, peaks/valleys (JSON)
clips.mp4 ─► clip_tag.py ──► scenes tagged by motion/energy/brightness (JSON)
both ──────► plan_edit.py ─► edit decision list: which clip hits which beat
EDL ───────► render_edit.py ► final MP4 (ffmpeg extract → concat → mux audio)
```

- **beat_map.py** — librosa audio analysis: beat timestamps, tempo, energy
  over time, energy peaks/valleys, best highlight segments.
- **clip_tag.py** — PySceneDetect scene detection + per-clip motion/energy/
  brightness scoring; `--thumbs` exports a labeled contact sheet.
- **plan_edit.py** — the matcher: high-energy clips land on energy peaks,
  calm clips on valleys, with anti-repetition, source-spacing, and
  black-frame filtering. Supports manual overrides (`--exclude/--lead/--pin`).
- **render_edit.py** — ffmpeg assembly; `--overunder` emits a stacked
  960x1080 variant.
- **vertical_style.py** — fits 16:9 output into 9:16 with a stylized squeeze
  + grade for TikTok/Reels/Shorts.

## Quickstart

```bash
pip install -r requirements.txt
python3 beat_map.py song.mp3
python3 clip_tag.py footage.mp4 --thumbs
python3 plan_edit.py song_beatmap.json footage_clips.json --html
python3 render_edit.py footage_edl.json -a song.mp3 -v footage.mp4
```

<!-- TODO before publishing: demo GIF here, license (MIT), rename repo -->

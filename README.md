# Beat-Synced Edit — Claude Code Automation

Automatic beat-synced video editing.

Feed it a song and raw footage. It analyzes the beats, maps the energy, tags every scene, and cuts a ready-to-post edit — zero manual editing.

## Demos

<!-- EMBED STEP (once, in GitHub's web editor): click the pencil on this README,
     then for each cell below: select the PASTE-VIDEO-HERE line and drag the
     matching file from examples/ onto it. GitHub uploads the video and inserts
     a user-attachments URL that renders as an inline player. Keep the blank
     lines around each URL — without them the player won't render. -->

<table>
<tr>
<td width="55%" align="center">

https://github.com/user-attachments/assets/60be3f2a-6e7d-48ef-8455-f08f0387a8b2

<em>1:1 montage — white-flash transitions + punch-ins, built via the bundled skill</em>

</td>
<td width="45%" align="center">

https://github.com/user-attachments/assets/45679a8b-d434-4d84-86c4-c80a53e2fa4a

<em>9:16 beat-synced edit — blue-strong grade, stock footage + my own single</em>

</td>
</tr>
</table>

Full-quality versions of both demos live in [`examples/`](examples/).

---

## Two ways to use it

### 1. Pure CLI — deterministic, no AI

Run the four stages yourself. Same inputs, same edit, every time.

### 2. Claude Code skill — conversational

The repo ships a skill at `.claude/skills/beat-sync-edit/SKILL.md`. Open this folder in [Claude Code](https://claude.com/claude-code) and describe the edit you want:

> "cut my footage to the chorus, white flash on every drop, space the cuts out so the shots breathe, then make it 9:16"

Claude runs the same pipeline and layers ffmpeg effects at beat-accurate timestamps — white flashes, stretch punches, hue shifts, RGB split, speed ramps, shakes, color grades. The full effects cookbook lives in the skill file.

In conversation you can also dictate:

- **Aspect ratio** — 9:16 vertical, 1:1 square, stacked over-under, or leave it 16:9
- **Cut density** — "a cut on every beat" vs "spaced out, let the shots breathe"
- **Hue / tint by reference** — point Claude at any other video on your machine ("grade it like this one") and it will sample frames from the reference and build a matching color grade; with the Claude-in-Chrome extension it can even study a look from a video on the web

---


## How it works

```
song.mp3  ──►  beat_map.py    ──►  beats, energy curve, peaks/valleys (JSON)
clips.mp4 ──►  clip_tag.py    ──►  scenes tagged by motion/energy/brightness (JSON)
both      ──►  plan_edit.py   ──►  edit decision list: which clip hits which beat
EDL       ──►  render_edit.py ──►  final MP4 (extract → concat → mux audio)
```

| Stage | What it does |
|---|---|
| `beat_map.py` | librosa audio analysis — beat timestamps, tempo, energy over time, peaks/valleys, best highlight segments |
| `clip_tag.py` | PySceneDetect scene detection + per-clip motion/energy/brightness scoring; `--thumbs` exports a labeled contact sheet |
| `plan_edit.py` | the matcher — high-energy clips land on energy peaks, calm clips on valleys, with anti-repetition, source spacing, and black-frame filtering |
| `render_edit.py` | ffmpeg assembly; `--overunder` emits a stacked 960×1080 variant |
| `vertical_style.py` | fits 16:9 output into 9:16 with a stylized squeeze + grade for TikTok / Reels / Shorts |

---

## Quickstart

```bash
pip install -r requirements.txt   # ffmpeg must be on PATH (brew install ffmpeg)

python3 beat_map.py song.mp3
python3 clip_tag.py footage.mp4 --thumbs
python3 plan_edit.py song_beatmap.json footage_clips.json --html
python3 render_edit.py footage_edl.json -a song.mp3 -v footage.mp4
```

---

## Controlling the cut

All creative control lives in `plan_edit.py`:

| Flag | Effect |
|---|---|
| `--beat-stride N` | Cut density. `1` = a cut on every beat (default). `2`+ keeps every Nth beat — fewer, longer cuts that breathe, for slow or contemplative footage |
| `--full` | Edit the whole song instead of the best-scoring segment |
| `--segment 2` | Use the second (or third) best highlight segment |
| `--exclude '1,6,0-30'` | Drop clips by id or source time range |
| `--lead '2:18,5'` | Force the opening cuts, in order |
| `--pin '8=138,peak2=22'` | Pin a clip to a specific beat, peak, or valley |

A useful convention when comparing densities: render both and suffix them `_beat-full` and `_beat-thinned`.

---

## Requirements

- Python 3.10+
- ffmpeg on PATH
- `pip install -r requirements.txt` — librosa, PySceneDetect, OpenCV, NumPy

---

## License

[MIT](LICENSE)

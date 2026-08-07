---
name: beat-sync-edit
description: Turn a song + raw footage into a beat-synced edit. Runs the four-stage pipeline (beat analysis, scene tagging, EDL planning, render) and applies user-described ffmpeg effects — white flashes, stretch punches, hue shifts, speed ramps — at beat-accurate timestamps.
---

# Beat-Sync Edit

Drive the deterministic pipeline conversationally. The user describes the edit
they want ("cut my footage to the chorus, white flash on every drop, make it
9:16"); you run the stages, apply effects, and deliver the file.

## The pipeline (run in order)

```
python3 beat_map.py <song>                       # beats, energy, peaks/valleys → <song>_beatmap.json
python3 clip_tag.py <footage> --html --thumbs    # scenes + motion/energy tags → <footage>_clips.json
python3 plan_edit.py <beatmap> <clips> --html    # energy-matched EDL → <name>_edl.json
python3 render_edit.py <edl> -a <song> -v <footage>   # final MP4
python3 vertical_style.py <mp4>                  # optional 9:16 squeeze + grade
```

- Read the beatmap's `peaks`/`valleys` and the EDL before adding effects —
  effects belong ON beat timestamps, not at arbitrary times.
- `plan_edit.py` overrides: `--exclude '1,6,0-30'`, `--lead '2:18,5'`,
  `--pin '8=138,peak2=22'` — use them when the user dislikes a cut.
- `plan_edit.py --beat-stride N` — cut density. 1 = a cut on every beat
  (default); N>1 keeps every Nth beat: fewer, longer cuts that breathe, for
  slow/contemplative footage. Naming convention for variants:
  `<name>_beat-full` (stride 1) vs `<name>_beat-thinned` (stride 2+).
- `plan_edit.py --full` uses the whole song instead of the best segment;
  `--segment 2|3` picks the second/third-best highlight segment.
- `render_edit.py --overunder` emits the stacked 960x1080 "3D" variant.

## What the user can ask for (translate words → workflow)

- "punchier / more cuts" → `--beat-stride 1` (default), or lower clip_tag
  `--threshold` for finer scenes
- "calmer / spaced out / longer scenes / let shots breathe" →
  `--beat-stride 2` (or 4 for very slow footage); when comparing, render both
  and suffix the outputs `_beat-full` / `_beat-thinned`
- "start on the best moment" → `--lead` with the highest-energy clip
- "make it vertical / TikTok-ready" → vertical_style.py after render

## Effects cookbook (apply with ffmpeg per segment, then re-concat)

Apply to individual extracted segments between the extract and concat steps
(re-encode the segment with `-vf "<filter>"`), or to the final file. Time
effects to beat timestamps from the beatmap.

| User says | ffmpeg filter |
|---|---|
| white flash (on the beat/drop) | `fade=t=in:st=0:d=0.07:color=white` on the segment starting at that beat |
| black dip | `fade=t=in:st=0:d=0.07:color=black` |
| stretch / punch-in | `scale=iw*1.15:ih*1.15,crop=iw/1.15:ih/1.15,setsar=1` (hold ~2 frames, then normal) |
| horizontal stretch hit | `scale=iw*1.25:ih,crop=iw/1.25:ih,setsar=1` |
| hue shift / psychedelic | static: `hue=h=60` · animated: `hue=h='mod(t*180,360)'` |
| RGB split / glitch | `rgbashift=rh=6:bh=-6` |
| speed ramp | `setpts=0.5*PTS` (2x) · `setpts=2*PTS` (half speed; add `minterpolate` for smoothness) |
| shake | `crop=iw-20:ih-20:'10+8*sin(t*40)':'10+8*cos(t*37)'` |
| strobe invert | `negate=enable='lt(mod(t,0.25),0.04)'` |
| dreamy glow | `gblur=sigma=8,blend=all_mode=screen,all_opacity=0.35` (via split) |
| grade: warm | `colorbalance=rm=.12:bm=-.08` · cool: `colorbalance=bm=.12:rm=-.06` |

Rules of thumb: flashes/punches on energy PEAKS only (over-flashing reads
amateur); one signature effect per edit + one grade; always `-pix_fmt yuv420p`
and `setsar=1` when re-encoding segments so concat stays valid.

## Workflow when the user asks for an edit

1. Run beat_map + clip_tag (with `--thumbs`; view the contact sheet to know
   the footage).
2. plan_edit → review the EDL against their description; apply overrides.
3. render_edit → if effects were requested, re-extract the affected segments
   with filters at the right beats, re-concat, re-mux audio.
4. Optional vertical_style for 9:16. Deliver the file path + one-line summary
   of cut count, duration, and effects used.

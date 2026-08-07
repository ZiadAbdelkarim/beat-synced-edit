#!/usr/bin/env python3
"""
vertical_style.py — fit a (usually 16:9) edit into a vertical 9:16 frame with a
stylistic "squeeze" and an optional color grade. Square pixels are forced
(setsar=1) so it always DISPLAYS 9:16 (no fake-wide SAR bug).

--fit
  squeeze[:S]  partial vertical stretch to height S, then scale-to-fill + center
               crop. Fills the frame, keeps the middle, isn't fully flattened.
               Bigger S = more squish, less side-crop. Default S = 1500 (for 1920 tall).
  cover        scale-to-fill + center crop, NO squeeze (max side-crop).
  contain      letterbox (fit inside + black bars, no crop, no squeeze).
  square[:S]   1:1 SxS (default 1080x1080) scale-to-fill + center crop — for 1:1
               lyric videos (overrides --size).

--grade
  pink   soft magenta/pink tint (the "Crave You" look)
  pink-strong / pink-max   progressively heavier magenta wash
  blue   soft cool blue-violet tint (channel-mirror of pink)
  blue-strong / blue-max   progressively heavier blue wash (mirror pink ladder)
  warm   warm nostalgic lift
  teal-orange  cinematic teal shadows / orange skin
  bw     desaturated
  none   no grade

Audio: keeps the source audio by default. --audio <file> swaps it in (-shortest).

Usage:
  python3 vertical_style.py in.mp4                       # squeeze:1500 + pink (defaults)
  python3 vertical_style.py in.mp4 --fit squeeze:1600 --grade pink -o out.mp4
  python3 vertical_style.py in.mp4 --audio higher/lyric_sync/higher_17-33.wav
"""
import argparse
import os
import subprocess
import sys

GRADES = {
    "none": "",
    "pink": "colorbalance=rm=0.15:gm=-0.05:bm=0.08:rh=0.10:bh=0.06,eq=saturation=1.06:contrast=1.03",
    "pink-strong": "colorbalance=rs=0.08:bs=0.05:rm=0.25:gm=-0.12:bm=0.15:rh=0.20:gh=-0.06:bh=0.12,eq=saturation=1.08:contrast=1.03",
    "pink-max": "colorbalance=rs=0.14:gs=-0.06:bs=0.10:rm=0.34:gm=-0.20:bm=0.24:rh=0.30:gh=-0.12:bh=0.20,eq=saturation=1.12:contrast=1.04",
    "blue": "colorbalance=bm=0.15:gm=0.02:rm=-0.08:bh=0.10:rh=-0.05:bs=0.06,eq=saturation=1.06:contrast=1.03",
    "blue-strong": "colorbalance=bs=0.10:rs=-0.05:bm=0.25:gm=0.04:rm=-0.15:bh=0.20:gh=0.02:rh=-0.10,eq=saturation=1.08:contrast=1.03",
    "blue-max": "colorbalance=bs=0.16:gs=0.04:rs=-0.10:bm=0.34:gm=0.08:rm=-0.22:bh=0.30:gh=0.06:rh=-0.16,eq=saturation=1.12:contrast=1.04",
    "warm": "colorbalance=rm=0.10:bm=-0.06:rh=0.06,eq=saturation=1.05:gamma_r=1.03",
    "teal-orange": "colorbalance=rs=-0.10:bs=0.10:rh=0.10:bh=-0.06,eq=saturation=1.10:contrast=1.05",
    "bw": "hue=s=0,eq=contrast=1.08",
}


def parse_size(s):
    w, h = s.lower().split("x")
    return int(w), int(h)


def fit_filter(fit, w, h):
    if fit == "cover":
        return (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},setsar=1")
    if fit == "contain":
        return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")
    if fit == "squeeze" or fit.startswith("squeeze:"):
        s = int(fit.split(":", 1)[1]) if ":" in fit else int(h * 0.78)
        return (f"scale={w}:{s},scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},setsar=1")
    if fit == "square" or fit.startswith("square:"):
        return (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},setsar=1")
    raise SystemExit(f"unknown --fit '{fit}' (use squeeze[:S] | cover | contain | square[:S])")


def main():
    ap = argparse.ArgumentParser(description="Vertical fit (squeeze) + color grade for edits")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--fit", default="squeeze:1500")
    ap.add_argument("--grade", default="pink", choices=list(GRADES.keys()))
    ap.add_argument("--size", default="1080x1920", help="WxH (default 1080x1920)")
    ap.add_argument("--audio", default=None, help="replace audio with this file (-shortest)")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"Error: not found: {args.input}")
    w, h = parse_size(args.size)
    if args.fit == "square" or args.fit.startswith("square:"):
        s = int(args.fit.split(":", 1)[1]) if ":" in args.fit else 1080
        w = h = s
    out = args.output or f"{os.path.splitext(args.input)[0]}_{args.fit.replace(':','')}_{args.grade}.mp4"

    vf = fit_filter(args.fit, w, h)
    if GRADES[args.grade]:
        vf += "," + GRADES[args.grade]

    cmd = ["ffmpeg", "-y", "-i", args.input]
    if args.audio:
        cmd += ["-i", args.audio]
    cmd += ["-vf", vf, "-c:v", "libx264", "-crf", "18", "-preset", "slow",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if args.audio:
        cmd += ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "256k", "-shortest"]
    else:
        cmd += ["-c:a", "copy"]
    cmd += [out]

    print(f"{args.fit} + {args.grade} -> {out} ({w}x{h})")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit("ffmpeg failed")
    print("✓ done:", out)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Over-under duplicate ("3D" look) transform.

Replicates the aesthetic of a 3D over-under stereo video (like the Red Bull
free-fall source): the SAME view stacked top and bottom to make a square-ish
frame. Default output is 960x1080 (each half 960x540 = 16:9), matching the
Red Bull edit exactly.

- 16:9 sources fill each half with NO crop.
- Other aspect ratios are scaled-to-cover and center-cropped to the half
  (no distortion) -- this is the "crop to fit the height" step.

Usage:
    python3 overunder_stack.py <input> [-o OUTPUT] [--size WxH]

Example:
    python3 overunder_stack.py clip.mp4                 # -> clip_overunder.mp4 (960x1080)
    python3 overunder_stack.py clip.mp4 --size 1080x1080
"""
import argparse
import os
import subprocess
import sys


def parse_size(size_str):
    """Parse 'WxH' -> (w, h). Height must be even (it is halved)."""
    try:
        w, h = size_str.lower().split("x")
        w, h = int(w), int(h)
    except Exception:
        raise argparse.ArgumentTypeError(f"--size must be WxH (e.g. 960x1080), got: {size_str}")
    if w <= 0 or h <= 0 or h % 2 != 0:
        raise argparse.ArgumentTypeError(f"--size WxH needs positive dims and an even height, got: {size_str}")
    return w, h


def overunder_filter(width, height):
    """Build the filtergraph that stacks the same (cropped/scaled) view top+bottom."""
    half = height // 2
    return (
        f"[0:v]scale={width}:{half}:force_original_aspect_ratio=increase,"
        f"crop={width}:{half},setsar=1,split=2[a][b];"
        f"[a][b]vstack=inputs=2[v]"
    )


def make_overunder(input_path, output_path, width=960, height=1080):
    """Render an over-under duplicated version of input_path -> output_path."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-filter_complex", overunder_filter(width, height),
        "-map", "[v]",
        "-map", "0:a?",          # keep audio if present, optional
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "slow",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return False
    return True


def default_output(input_path):
    stem, _ = os.path.splitext(input_path)
    return f"{stem}_overunder.mp4"


def main():
    parser = argparse.ArgumentParser(description="Over-under duplicate (3D look) transform")
    parser.add_argument("input", help="Input video file")
    parser.add_argument("-o", "--output", default=None, help="Output path (default: <input>_overunder.mp4)")
    parser.add_argument("--size", type=parse_size, default=(960, 1080),
                        help="Output WxH (default: 960x1080; height is split into two equal halves)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: input not found: {args.input}")
        sys.exit(1)

    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except Exception:
        print("Error: FFmpeg not found. Install with: brew install ffmpeg")
        sys.exit(1)

    output_path = args.output or default_output(args.input)
    w, h = args.size

    print(f"Over-under stacking {args.input} -> {output_path} ({w}x{h}, each half {w}x{h // 2})")
    if make_overunder(args.input, output_path, w, h):
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"✓ Done: {output_path} ({size_mb:.1f} MB)")
    else:
        print("✗ Render failed (see ffmpeg error above)")
        sys.exit(1)


if __name__ == "__main__":
    main()

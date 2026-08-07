#!/usr/bin/env python3
"""
Render Edit - Assemble final video from EDL using FFmpeg

Takes an edit decision list (EDL) and renders the final video by:
1. Extracting each clip segment from source video
2. Concatenating clips in order
3. Adding audio track (trimmed to segment)
4. Outputting final video

Usage:
    python3 render_edit.py <edl.json> -a <audio_file> -v <video_file> [--output output.mp4]
"""

import sys
import os
import json
import argparse
import subprocess
import tempfile
import shutil
from datetime import datetime


def load_json(path):
    """Load a JSON file."""
    with open(path, 'r') as f:
        return json.load(f)


def check_ffmpeg():
    """Check if FFmpeg is available."""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: FFmpeg not found. Install with: brew install ffmpeg")
        return False


def extract_clip(video_path, start, end, output_path, temp_dir):
    """Extract a clip segment from video using FFmpeg."""
    duration = end - start

    cmd = [
        'ffmpeg', '-y',
        '-ss', str(start),
        '-i', video_path,
        '-t', str(duration),
        '-c:v', 'libx264',
        '-preset', 'slow',
        '-crf', '18',
        '-an',  # No audio for individual clips
        '-avoid_negative_ts', 'make_zero',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: FFmpeg error: {result.stderr[:200]}")
        return False
    return True


def extract_audio_segment(audio_path, start, end, output_path):
    """Extract audio segment using FFmpeg."""
    duration = end - start

    cmd = [
        'ffmpeg', '-y',
        '-ss', str(start),
        '-i', audio_path,
        '-t', str(duration),
        '-c:a', 'aac',
        '-b:a', '192k',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: Audio extraction error: {result.stderr[:200]}")
        return False
    return True


def concatenate_clips(clip_paths, output_path, temp_dir):
    """Concatenate video clips using FFmpeg concat demuxer."""
    # Create concat file
    concat_file = os.path.join(temp_dir, 'concat.txt')
    with open(concat_file, 'w') as f:
        for path in clip_paths:
            # Escape single quotes in path
            escaped_path = path.replace("'", "'\\''")
            f.write(f"file '{escaped_path}'\n")

    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat',
        '-safe', '0',
        '-i', concat_file,
        '-c:v', 'libx264',
        '-preset', 'slow',
        '-crf', '18',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: Concat error: {result.stderr[:200]}")
        return False
    return True


def add_audio_to_video(video_path, audio_path, output_path):
    """Combine video and audio tracks."""
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', audio_path,
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-shortest',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: Audio merge error: {result.stderr[:200]}")
        return False
    return True


def render_edl(edl, audio_path, video_path, output_path, temp_dir):
    """Render the full video from EDL."""

    edits = edl['edits']
    total_edits = len(edits)

    print(f"\nRendering {total_edits} clips...")

    # Step 1: Extract each clip
    clip_paths = []
    for i, edit in enumerate(edits):
        clip_file = os.path.join(temp_dir, f"clip_{i:04d}.mp4")

        # Determine source video (might be different for each clip)
        source_video = video_path
        if 'clip_source' in edit and edit['clip_source']:
            # Check if it's a full path or just filename
            if os.path.isfile(edit['clip_source']):
                source_video = edit['clip_source']

        print(f"  [{i+1}/{total_edits}] Extracting {edit['clip_start']}s - {edit['clip_end']}s ({edit['beat_type']})")

        success = extract_clip(
            source_video,
            edit['clip_start'],
            edit['clip_end'],
            clip_file,
            temp_dir
        )

        if success and os.path.exists(clip_file):
            clip_paths.append(clip_file)
        else:
            print(f"    Skipping failed clip")

    if not clip_paths:
        print("Error: No clips extracted successfully")
        return False

    print(f"\nExtracted {len(clip_paths)} clips")

    # Step 2: Concatenate clips
    print("Concatenating clips...")
    concat_video = os.path.join(temp_dir, "concat.mp4")
    if not concatenate_clips(clip_paths, concat_video, temp_dir):
        return False

    # Step 3: Extract audio segment
    print("Extracting audio segment...")
    audio_segment = os.path.join(temp_dir, "audio_segment.m4a")

    if edl.get('audio_segment'):
        audio_start = edl['audio_segment']['start']
        audio_end = edl['audio_segment']['end']
    else:
        audio_start = 0
        audio_end = edl['timeline_duration']

    if not extract_audio_segment(audio_path, audio_start, audio_end, audio_segment):
        return False

    # Step 4: Combine video and audio
    print("Adding audio to video...")
    if not add_audio_to_video(concat_video, audio_segment, output_path):
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Render final video from EDL")
    parser.add_argument("edl", help="Edit decision list JSON file from /plan-edit")
    parser.add_argument("-a", "--audio", required=True, help="Audio file path")
    parser.add_argument("-v", "--video", required=True, help="Source video file path")
    parser.add_argument("-o", "--output", help="Output video file path", default=None)
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary files")
    parser.add_argument("--overunder", action="store_true",
                        help="Also output an over-under 'duplicated view' (3D-style) version: the same "
                             "view stacked top+bottom. Writes <output>_overunder.mp4 alongside the normal render.")
    parser.add_argument("--overunder-size", default="960x1080",
                        help="Size for --overunder output as WxH (default: 960x1080, matching the Red Bull edit).")

    args = parser.parse_args()

    # Check FFmpeg
    if not check_ffmpeg():
        sys.exit(1)

    # Load EDL
    print(f"Loading EDL: {args.edl}")
    edl = load_json(args.edl)

    print(f"\nEDL Info:")
    print(f"  Audio: {edl['audio_source']}")
    print(f"  Timeline: {edl['timeline_duration']}s")
    print(f"  Edits: {edl['edit_count']}")

    if edl.get('audio_segment'):
        seg = edl['audio_segment']
        print(f"  Audio segment: {seg['start']}s - {seg['end']}s")

    # Check input files exist
    if not os.path.exists(args.audio):
        print(f"Error: Audio file not found: {args.audio}")
        sys.exit(1)

    if not os.path.exists(args.video):
        print(f"Error: Video file not found: {args.video}")
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_path = f"output_{date_str}.mp4"

    # Create temp directory
    temp_dir = tempfile.mkdtemp(prefix="render_edit_")
    print(f"\nTemp directory: {temp_dir}")

    try:
        # Render
        success = render_edl(edl, args.audio, args.video, output_path, temp_dir)

        if success:
            # Get file size
            file_size = os.path.getsize(output_path) / (1024 * 1024)  # MB

            print(f"\n✓ Render complete!")
            print(f"  Output: {output_path}")
            print(f"  Size: {file_size:.1f} MB")
            print(f"  Duration: ~{edl['timeline_duration']}s")

            # Optional over-under "duplicated view" (3D-style) version
            if args.overunder:
                from overunder_stack import make_overunder, parse_size, default_output
                ou_w, ou_h = parse_size(args.overunder_size)
                ou_path = default_output(output_path)
                print(f"\nCreating over-under version: {ou_path} ({ou_w}x{ou_h})")
                if make_overunder(output_path, ou_path, ou_w, ou_h):
                    print(f"  ✓ Over-under output: {ou_path}")
                else:
                    print(f"  ✗ Over-under render failed")
        else:
            print(f"\n✗ Render failed")
            sys.exit(1)

    finally:
        # Cleanup temp files
        if not args.keep_temp:
            shutil.rmtree(temp_dir)
            print(f"\nCleaned up temp files")
        else:
            print(f"\nTemp files kept at: {temp_dir}")


if __name__ == "__main__":
    main()

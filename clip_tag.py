#!/usr/bin/env python3
"""
Clip Tag - Scene detection and clip tagging for video editing

Analyzes a video file (or scene pack) to:
1. Detect scene cuts and extract timestamps
2. Analyze each clip for motion/energy
3. Output tagged clips as JSON (no file splitting)

Usage:
    python3 clip_tag.py <video_file_or_zip> [--output clips.json]
"""

import sys
import os
import json
import argparse
import zipfile
import tempfile
import shutil

# Suppress OpenCV/ffmpeg warnings
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"

try:
    import cv2
    import numpy as np
except ImportError:
    print("Error: opencv-python not installed. Run: pip3 install opencv-python")
    sys.exit(1)

try:
    from scenedetect import detect, ContentDetector, AdaptiveDetector
except ImportError:
    print("Error: scenedetect not installed. Run: pip3 install scenedetect[opencv]")
    sys.exit(1)


def find_video_files(path):
    """Find all video files in a directory."""
    video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.wmv'}
    videos = []

    if os.path.isfile(path):
        if os.path.splitext(path)[1].lower() in video_extensions:
            return [path]
        return []

    for root, dirs, files in os.walk(path):
        for f in files:
            if os.path.splitext(f)[1].lower() in video_extensions:
                videos.append(os.path.join(root, f))

    return sorted(videos)


def detect_scenes(video_path, threshold=27.0):
    """
    Detect scene cuts in a video.
    Returns list of (start_time, end_time) tuples in seconds.
    """
    print(f"Detecting scenes in: {video_path}")

    # Suppress ffmpeg stderr warnings (h264 mmco messages) at file descriptor level
    stderr_fd = sys.stderr.fileno()
    old_stderr_fd = os.dup(stderr_fd)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, stderr_fd)
    try:
        scene_list = detect(video_path, ContentDetector(threshold=threshold))
    finally:
        os.dup2(old_stderr_fd, stderr_fd)
        os.close(devnull)
        os.close(old_stderr_fd)

    scenes = []
    for scene in scene_list:
        start_time = scene[0].get_seconds()
        end_time = scene[1].get_seconds()
        scenes.append({
            "start": round(start_time, 3),
            "end": round(end_time, 3),
            "duration": round(end_time - start_time, 3)
        })

    print(f"Found {len(scenes)} scenes")
    return scenes


def analyze_clip_motion(video_path, start_time, end_time, sample_frames=10):
    """
    Analyze motion level in a clip segment.
    Returns motion score (0-1) and category (static/slow/medium/fast).
    """
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)

        if fps <= 0:
            return 0.5, "medium"

        duration = end_time - start_time
        frame_interval = max(1, int((duration * fps) / sample_frames))

        # Seek to start
        cap.set(cv2.CAP_PROP_POS_MSEC, start_time * 1000)

        prev_frame = None
        motion_scores = []

        for i in range(sample_frames):
            ret, frame = cap.read()
            if not ret:
                break

            # Convert to grayscale and resize for faster processing
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (160, 90))
            # Blur before differencing: film grain, flicker, and VHS-style
            # overlay effects change every pixel every frame and read as fast
            # motion; blur wipes that out while structural motion survives
            gray = cv2.GaussianBlur(gray, (9, 9), 0)

            if prev_frame is not None:
                # Calculate frame difference
                diff = cv2.absdiff(prev_frame, gray)
                motion_score = np.mean(diff) / 255.0
                motion_scores.append(motion_score)

            prev_frame = gray

            # Skip frames
            for _ in range(frame_interval - 1):
                cap.read()
    finally:
        cap.release()

    if not motion_scores:
        return 0.5, "medium"

    avg_motion = np.mean(motion_scores)

    # Classify motion level
    if avg_motion < 0.02:
        category = "static"
    elif avg_motion < 0.05:
        category = "slow"
    elif avg_motion < 0.10:
        category = "medium"
    else:
        category = "fast"

    # Normalize to 0-1 scale (cap at 0.2 for normalization)
    normalized = min(avg_motion / 0.15, 1.0)

    return round(normalized, 3), category


def analyze_clip_brightness(video_path, start_time, end_time, sample_frames=5):
    """
    Analyze average brightness/energy of a clip.
    Returns brightness score (0-1).
    """
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)

        if fps <= 0:
            return 0.5

        duration = end_time - start_time
        frame_interval = max(1, int((duration * fps) / sample_frames))

        cap.set(cv2.CAP_PROP_POS_MSEC, start_time * 1000)

        brightness_scores = []

        for i in range(sample_frames):
            ret, frame = cap.read()
            if not ret:
                break

            # Calculate mean brightness
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness = np.mean(gray) / 255.0
            brightness_scores.append(brightness)

            # Skip frames
            for _ in range(frame_interval - 1):
                cap.read()
    finally:
        cap.release()

    if not brightness_scores:
        return 0.5

    return round(np.mean(brightness_scores), 3)


def get_video_duration(video_path):
    """Get video duration in seconds."""
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    finally:
        cap.release()

    if fps > 0:
        return frame_count / fps
    return 0


def process_video(video_path, scene_threshold=27.0):
    """
    Process a video file: detect scenes and tag each clip.
    """
    print(f"\nProcessing: {video_path}")

    duration = get_video_duration(video_path)
    print(f"Duration: {duration:.2f}s")

    # Detect scenes
    scenes = detect_scenes(video_path, threshold=scene_threshold)

    # If no scenes detected (single continuous video), treat whole video as one clip
    if not scenes:
        scenes = [{
            "start": 0,
            "end": round(duration, 3),
            "duration": round(duration, 3)
        }]

    # Analyze each scene/clip
    print(f"Analyzing {len(scenes)} clips...")
    clips = []

    for i, scene in enumerate(scenes):
        print(f"  Clip {i+1}/{len(scenes)}: {scene['start']}s - {scene['end']}s", end="")

        motion_score, motion_category = analyze_clip_motion(
            video_path, scene['start'], scene['end']
        )
        brightness = analyze_clip_brightness(
            video_path, scene['start'], scene['end']
        )

        # Calculate visual energy (combination of motion and brightness variance)
        energy = round((motion_score * 0.7 + brightness * 0.3), 3)

        clip = {
            "id": i + 1,
            "start": scene['start'],
            "end": scene['end'],
            "duration": scene['duration'],
            "motion_score": motion_score,
            "motion": motion_category,
            "brightness": brightness,
            "energy": energy
        }
        clips.append(clip)

        print(f" → {motion_category} (energy: {energy})")

    return {
        "source": os.path.basename(video_path),
        "source_path": video_path,
        "duration": round(duration, 3),
        "clip_count": len(clips),
        "clips": clips
    }


def extract_thumbnails_all(clips, src_paths, default_source, thumbs_dir):
    """Write one representative (midpoint) JPG per clip and set clip['thumb'].

    Additive: enables context-aware VISUAL review of every scene at once
    (used by the segment-reels workflow). Does not affect other fields.
    """
    os.makedirs(thumbs_dir, exist_ok=True)
    caps = {}
    try:
        for clip in clips:
            src = clip.get("source", default_source)
            vp = src_paths.get(src)
            if not vp:
                continue
            cap = caps.get(vp)
            if cap is None:
                cap = cv2.VideoCapture(vp)
                caps[vp] = cap
            mid = (clip["start"] + clip["end"]) / 2.0
            cap.set(cv2.CAP_PROP_POS_MSEC, mid * 1000.0)
            ok, frame = cap.read()
            if not ok:
                continue
            name = f"clip_{clip['id']:03d}_{mid:.1f}s.jpg"
            path = os.path.join(thumbs_dir, name)
            cv2.imwrite(path, frame)
            clip["thumb"] = path
    finally:
        for cap in caps.values():
            cap.release()
    return sum(1 for c in clips if c.get("thumb"))


def build_contact_sheet(clips, sheet_path, cols=6, cell_w=320):
    """Tile all clip thumbs into ONE labeled grid image (#id, time, motion) for
    quick review. Best-effort: silently skips if Pillow is unavailable."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    items = [c for c in clips if c.get("thumb") and os.path.exists(c["thumb"])]
    if not items:
        return None
    cells = []
    cell_h = 0
    for c in items:
        im = Image.open(c["thumb"]).convert("RGB")
        h = max(1, int(cell_w * im.height / im.width))
        cells.append((c, im.resize((cell_w, h))))
        cell_h = max(cell_h, h)
    label_h = 24
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * (cell_h + label_h)), (12, 12, 18))
    draw = ImageDraw.Draw(sheet)
    for idx, (c, im) in enumerate(cells):
        r, cc = divmod(idx, cols)
        x, y = cc * cell_w, r * (cell_h + label_h)
        sheet.paste(im, (x, y + label_h))
        draw.text((x + 5, y + 5),
                  f"#{c['id']}  {c['start']:.0f}-{c['end']:.0f}s  {c.get('motion','')}",
                  fill=(232, 232, 240))
    sheet.save(sheet_path, quality=88)
    return sheet_path


def main():
    parser = argparse.ArgumentParser(description="Detect scenes and tag clips in video")
    parser.add_argument("input", help="Video file or zip archive")
    parser.add_argument("-o", "--output", help="Output JSON file path", default=None)
    parser.add_argument("--threshold", type=float, default=27.0,
                        help="Scene detection threshold (lower = more sensitive, default: 27)")
    parser.add_argument("--html", action="store_true", help="Generate HTML visualization")
    parser.add_argument("--thumbs", action="store_true",
                        help="Export a representative JPG per scene (+ a labeled contact sheet) for "
                             "visual clip selection; adds a 'thumb' path to each clip.")

    args = parser.parse_args()

    input_path = args.input
    temp_dir = None

    # Handle zip files
    if input_path.endswith('.zip'):
        print(f"Extracting zip: {input_path}")
        temp_dir = tempfile.mkdtemp(prefix="clip_tag_")
        with zipfile.ZipFile(input_path, 'r') as zf:
            zf.extractall(temp_dir)
        input_path = temp_dir
        print(f"Extracted to: {temp_dir}")

    # Find video files
    videos = find_video_files(input_path)

    if not videos:
        print(f"Error: No video files found in {input_path}")
        if temp_dir:
            shutil.rmtree(temp_dir)
        sys.exit(1)

    print(f"Found {len(videos)} video file(s)")

    # Process each video
    all_results = []
    for video in videos:
        result = process_video(video, scene_threshold=args.threshold)
        all_results.append(result)

    # Combine results
    if len(all_results) == 1:
        output_data = all_results[0]
    else:
        # Multiple videos - combine all clips with source reference
        all_clips = []
        clip_id = 1
        for result in all_results:
            for clip in result['clips']:
                clip['source'] = result['source']
                clip['id'] = clip_id
                clip_id += 1
                all_clips.append(clip)

        output_data = {
            "sources": [r['source'] for r in all_results],
            "total_duration": round(sum(r['duration'] for r in all_results), 3),
            "clip_count": len(all_clips),
            "clips": all_clips
        }

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        base = os.path.splitext(os.path.basename(args.input))[0]
        output_path = f"{base}_clips.json"

    # Optional: export per-scene thumbnails + a labeled contact sheet for visual selection
    if args.thumbs:
        thumbs_dir = os.path.splitext(output_path)[0] + "_thumbs"
        src_paths = {r['source']: r['source_path'] for r in all_results}
        n = extract_thumbnails_all(output_data['clips'], src_paths,
                                   output_data.get('source'), thumbs_dir)
        sheet = build_contact_sheet(output_data['clips'],
                                    os.path.splitext(output_path)[0] + "_thumbs.jpg")
        print(f"  Thumbnails: {n} → {thumbs_dir}/" + (f"  (sheet: {sheet})" if sheet else ""))

    # Write JSON
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"\nClip tags saved to: {output_path}")

    # Summary
    print(f"\nSummary:")
    if 'sources' in output_data:
        print(f"  Sources: {len(output_data['sources'])}")
    print(f"  Total clips: {output_data['clip_count']}")

    # Motion breakdown
    motion_counts = {"static": 0, "slow": 0, "medium": 0, "fast": 0}
    for clip in output_data['clips']:
        motion_counts[clip['motion']] += 1

    print(f"  Motion breakdown:")
    for motion, count in motion_counts.items():
        if count > 0:
            print(f"    {motion}: {count}")

    # Warn when energy barely varies across clips - tags won't discriminate
    # and peak/valley matching in plan-edit becomes effectively arbitrary
    energies = [c['energy'] for c in output_data['clips']]
    if len(energies) >= 5 and (np.std(energies) < 0.08 or
                               motion_counts['fast'] > 0.7 * len(energies)):
        print(f"\n  WARNING: energy distribution is suspiciously flat "
              f"(std: {np.std(energies):.3f}, fast: {motion_counts['fast']}/{len(energies)}).")
        print(f"  Source may have grain/flicker/overlay effects inflating motion scores.")

    # Top 5 highest energy clips
    sorted_clips = sorted(output_data['clips'], key=lambda x: x['energy'], reverse=True)
    print(f"\n  Top 5 highest energy clips:")
    for clip in sorted_clips[:5]:
        src = clip.get('source', output_data.get('source', ''))
        print(f"    #{clip['id']}: {clip['start']}s-{clip['end']}s ({clip['duration']}s) - {clip['motion']} - energy: {clip['energy']}")

    # Generate HTML if requested
    if args.html:
        html_path = output_path.replace('.json', '.html')
        generate_html(output_data, html_path)
        print(f"\nVisualization saved to: {html_path}")

    # Cleanup temp dir
    if temp_dir:
        shutil.rmtree(temp_dir)
        print(f"\nCleaned up temp files")


def generate_html(data, output_path):
    """Generate HTML visualization of clip tags."""

    clips = data['clips']
    source = data.get('source', data.get('sources', ['Multiple'])[0] if 'sources' in data else 'Unknown')

    # Build clip cards
    clip_cards = []
    for clip in clips:
        motion_color = {
            "static": "#6366f1",
            "slow": "#8b5cf6",
            "medium": "#a78bfa",
            "fast": "#f472b6"
        }.get(clip['motion'], "#888")

        energy_width = int(clip['energy'] * 100)

        card = f'''
        <div class="clip-card" data-motion="{clip['motion']}">
            <div class="clip-header">
                <span class="clip-id">#{clip['id']}</span>
                <span class="motion-badge" style="background: {motion_color}">{clip['motion'].upper()}</span>
            </div>
            <div class="clip-time">{clip['start']}s → {clip['end']}s</div>
            <div class="clip-duration">{clip['duration']}s duration</div>
            <div class="energy-bar">
                <div class="energy-fill" style="width: {energy_width}%"></div>
            </div>
            <div class="energy-label">Energy: {clip['energy']}</div>
        </div>
        '''
        clip_cards.append(card)

    # Count by motion type
    motion_counts = {"static": 0, "slow": 0, "medium": 0, "fast": 0}
    for clip in clips:
        motion_counts[clip['motion']] += 1

    html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Clip Tags: {source}</title>
    <style>
        body {{
            background: #0e0e0e;
            color: #e0e0e0;
            font-family: -apple-system, sans-serif;
            padding: 2rem;
            margin: 0;
        }}
        h1 {{ color: #a78bfa; margin-bottom: 0.5rem; }}
        .subtitle {{ color: #888; margin-bottom: 1.5rem; }}
        .stats {{
            display: flex;
            gap: 1rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
        }}
        .stat {{
            background: #1a1a1a;
            padding: 0.75rem 1rem;
            border-radius: 8px;
        }}
        .stat-value {{
            font-size: 1.5rem;
            color: #a78bfa;
            font-weight: bold;
        }}
        .filters {{
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1rem;
        }}
        .filter-btn {{
            background: #1a1a1a;
            border: 1px solid #333;
            color: #888;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            cursor: pointer;
        }}
        .filter-btn.active {{
            background: #a78bfa;
            color: #0e0e0e;
            border-color: #a78bfa;
        }}
        .clips-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 1rem;
        }}
        .clip-card {{
            background: #1a1a1a;
            border-radius: 8px;
            padding: 1rem;
        }}
        .clip-card.hidden {{ display: none; }}
        .clip-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }}
        .clip-id {{
            color: #a78bfa;
            font-weight: 600;
        }}
        .motion-badge {{
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 600;
            color: #fff;
        }}
        .clip-time {{
            font-size: 1.1rem;
            color: #fff;
            margin-bottom: 0.25rem;
        }}
        .clip-duration {{
            color: #888;
            font-size: 0.85rem;
            margin-bottom: 0.5rem;
        }}
        .energy-bar {{
            background: #333;
            height: 8px;
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 0.25rem;
        }}
        .energy-fill {{
            background: linear-gradient(90deg, #a78bfa, #f472b6);
            height: 100%;
        }}
        .energy-label {{
            font-size: 0.8rem;
            color: #888;
        }}
    </style>
</head>
<body>
    <h1>Clip Tags</h1>
    <p class="subtitle">Source: {source}</p>

    <div class="stats">
        <div class="stat">
            <div class="stat-value">{data['clip_count']}</div>
            <div>Total Clips</div>
        </div>
        <div class="stat">
            <div class="stat-value">{data.get('duration', data.get('total_duration', 0))}s</div>
            <div>Duration</div>
        </div>
        <div class="stat">
            <div class="stat-value">{motion_counts['fast']}</div>
            <div>Fast</div>
        </div>
        <div class="stat">
            <div class="stat-value">{motion_counts['medium']}</div>
            <div>Medium</div>
        </div>
        <div class="stat">
            <div class="stat-value">{motion_counts['slow']}</div>
            <div>Slow</div>
        </div>
        <div class="stat">
            <div class="stat-value">{motion_counts['static']}</div>
            <div>Static</div>
        </div>
    </div>

    <div class="filters">
        <button class="filter-btn active" onclick="filterClips('all')">All</button>
        <button class="filter-btn" onclick="filterClips('fast')">Fast</button>
        <button class="filter-btn" onclick="filterClips('medium')">Medium</button>
        <button class="filter-btn" onclick="filterClips('slow')">Slow</button>
        <button class="filter-btn" onclick="filterClips('static')">Static</button>
    </div>

    <div class="clips-grid">
        {"".join(clip_cards)}
    </div>

    <script>
        function filterClips(motion) {{
            document.querySelectorAll('.filter-btn').forEach(btn => {{
                btn.classList.remove('active');
                if (btn.textContent.toLowerCase() === motion || (motion === 'all' && btn.textContent === 'All')) {{
                    btn.classList.add('active');
                }}
            }});

            document.querySelectorAll('.clip-card').forEach(card => {{
                if (motion === 'all' || card.dataset.motion === motion) {{
                    card.classList.remove('hidden');
                }} else {{
                    card.classList.add('hidden');
                }}
            }});
        }}
    </script>
</body>
</html>'''

    with open(output_path, 'w') as f:
        f.write(html)


if __name__ == "__main__":
    main()

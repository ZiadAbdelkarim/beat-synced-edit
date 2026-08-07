#!/usr/bin/env python3
"""
Beat Map - Audio analysis for beat-synced video editing

Analyzes an audio file and outputs:
- Beat timestamps
- Energy levels over time
- Tempo (BPM)
- Energy peaks (hills) and valleys

Usage:
    python3 beat_map.py <audio_file> [--output beat_map.json]
"""

import sys
import os
import json
import argparse
import numpy as np

try:
    import librosa
except ImportError:
    print("Error: librosa not installed. Run: pip3 install librosa")
    sys.exit(1)


def find_top_segments(times, energy, target_duration=15.0, num_segments=3):
    """
    Find the top N most energetic non-overlapping segments.

    Uses a sliding window approach with exclusion zones to find windows with
    highest average energy that don't overlap with each other.
    Returns list of segments sorted by energy (highest first).
    """
    if len(times) < 2:
        return [{"rank": 1, "start": 0, "end": 0, "duration": 0, "avg_energy": 0}]

    # Calculate time step between samples
    time_step = times[1] - times[0] if len(times) > 1 else 0.1
    window_size = int(target_duration / time_step)

    # If audio too short for even one segment, return the whole thing
    if window_size >= len(energy):
        return [{
            "rank": 1,
            "start": round(float(times[0]), 2),
            "end": round(float(times[-1]), 2),
            "duration": round(float(times[-1] - times[0]), 2),
            "avg_energy": round(float(np.mean(energy)), 3)
        }]

    segments = []
    used_ranges = []
    cumsum = np.cumsum(energy)

    for seg_num in range(num_segments):
        best_start_idx = None
        best_avg_energy = 0

        for i in range(len(energy) - window_size):
            window_start = times[i]
            window_end = times[min(i + window_size, len(times) - 1)]

            # Check overlap with already used ranges
            overlaps = any(
                not (window_end <= used_start or window_start >= used_end)
                for used_start, used_end in used_ranges
            )
            if overlaps:
                continue

            # Calculate avg energy using cumsum
            if i == 0:
                window_sum = cumsum[window_size - 1]
            else:
                window_sum = cumsum[i + window_size - 1] - cumsum[i - 1]
            avg_energy = window_sum / window_size

            if avg_energy > best_avg_energy:
                best_avg_energy = avg_energy
                best_start_idx = i

        if best_start_idx is None:
            break  # No more non-overlapping segments fit

        start_time = times[best_start_idx]
        end_idx = min(best_start_idx + window_size, len(times) - 1)
        end_time = times[end_idx]
        used_ranges.append((start_time, end_time))

        segments.append({
            "rank": len(segments) + 1,
            "start": round(float(start_time), 2),
            "end": round(float(end_time), 2),
            "duration": round(float(end_time - start_time), 2),
            "avg_energy": round(float(best_avg_energy), 3)
        })

    return segments


def analyze_audio(audio_path, hop_length=512, segment_duration=15.0):
    """
    Analyze audio file for beats, tempo, and energy.

    Returns dict with:
    - tempo: BPM
    - beats: list of beat timestamps in seconds
    - energy: list of (time, energy_level) tuples
    - peaks: list of energy peak timestamps (hills)
    - valleys: list of energy valley timestamps
    - best_segment: most energetic window of ~segment_duration seconds
    """
    print(f"Loading audio: {audio_path}")

    # Load audio file
    y, sr = librosa.load(audio_path)
    duration = librosa.get_duration(y=y, sr=sr)

    print(f"Duration: {duration:.2f}s, Sample rate: {sr}Hz")

    # Detect tempo and beats
    print("Detecting beats...")
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)

    # Handle tempo as array or scalar
    if hasattr(tempo, '__len__'):
        tempo = float(tempo[0])
    else:
        tempo = float(tempo)

    print(f"Tempo: {tempo:.1f} BPM, {len(beat_times)} beats detected")

    # Calculate RMS energy over time
    print("Calculating energy curve...")
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=hop_length)

    # Normalize energy to 0-1 range
    rms_normalized = (rms - rms.min()) / (rms.max() - rms.min() + 1e-10)

    # Find energy peaks (hills) and valleys
    print("Finding peaks and valleys...")

    # Smooth the energy curve for peak detection
    from scipy.ndimage import gaussian_filter1d
    rms_smooth = gaussian_filter1d(rms_normalized, sigma=5)

    # Find local maxima (peaks/hills)
    peaks = []
    valleys = []

    window = 10  # frames to look around
    threshold_high = 0.6  # energy level for peaks
    threshold_low = 0.3   # energy level for valleys

    for i in range(window, len(rms_smooth) - window):
        local_max = rms_smooth[i] == max(rms_smooth[i-window:i+window+1])
        local_min = rms_smooth[i] == min(rms_smooth[i-window:i+window+1])

        if local_max and rms_smooth[i] > threshold_high:
            peaks.append({
                "time": round(float(times[i]), 3),
                "energy": round(float(rms_smooth[i]), 3)
            })
        elif local_min and rms_smooth[i] < threshold_low:
            valleys.append({
                "time": round(float(times[i]), 3),
                "energy": round(float(rms_smooth[i]), 3)
            })

    # Downsample energy curve for output (every 0.1 seconds)
    sample_interval = int(0.1 * sr / hop_length)
    energy_curve = [
        {
            "time": round(float(times[i]), 2),
            "energy": round(float(rms_normalized[i]), 3)
        }
        for i in range(0, len(times), max(1, sample_interval))
    ]

    # Find the top 3 most energetic ~20 second segments (non-overlapping)
    print(f"Finding top 3 {segment_duration}s segments...")
    top_segments = find_top_segments(
        np.array(times),
        rms_smooth,  # Use smoothed energy for more stable results
        target_duration=segment_duration,
        num_segments=3
    )

    for i, seg in enumerate(top_segments):
        print(f"  Segment #{i+1}: {seg['start']}s - {seg['end']}s (avg energy: {seg['avg_energy']})")

    # Get beats for each segment
    top_segment_beats = []
    for seg in top_segments:
        seg_beats = [
            round(float(t), 3) for t in beat_times
            if seg['start'] <= t <= seg['end']
        ]
        top_segment_beats.append(seg_beats)

    # Backwards compatible - best_segment is the top segment
    best_segment = top_segments[0] if top_segments else {"start": 0, "end": 0, "duration": 0, "avg_energy": 0}
    best_segment_beats = top_segment_beats[0] if top_segment_beats else []

    return {
        "file": audio_path,
        "duration": round(duration, 2),
        "tempo": round(tempo, 1),
        "beat_count": len(beat_times),
        "beats": [round(float(t), 3) for t in beat_times],
        "energy_curve": energy_curve,
        "peaks": peaks,
        "valleys": valleys,
        "peak_count": len(peaks),
        "valley_count": len(valleys),
        # Backwards compatible fields
        "best_segment": best_segment,
        "best_segment_beats": best_segment_beats,
        "best_segment_beat_count": len(best_segment_beats),
        # New fields for multiple segments
        "top_segments": top_segments,
        "top_segment_beats": top_segment_beats
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze audio for beat-synced editing")
    parser.add_argument("audio_file", help="Path to audio file (mp3, wav, etc.)")
    parser.add_argument("-o", "--output", help="Output JSON file path", default=None)
    parser.add_argument("--html", action="store_true", help="Also generate HTML visualization")

    args = parser.parse_args()

    # Analyze audio
    result = analyze_audio(args.audio_file)

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        base = args.audio_file.rsplit(".", 1)[0]
        output_path = f"{base}_beatmap.json"

    # Write JSON output
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nBeat map saved to: {output_path}")
    print(f"\nSummary:")
    print(f"  Duration: {result['duration']}s")
    print(f"  Tempo: {result['tempo']} BPM")
    print(f"  Beats: {result['beat_count']}")
    print(f"  Peaks (hills): {result['peak_count']}")
    print(f"  Valleys: {result['valley_count']}")

    # Top segments info
    print(f"\n⚡ Top {len(result['top_segments'])} Segments (most energetic ~15s, non-overlapping):")
    for i, seg in enumerate(result['top_segments']):
        beat_count = len(result['top_segment_beats'][i]) if i < len(result['top_segment_beats']) else 0
        print(f"  #{i+1}: {seg['start']}s - {seg['end']}s | Energy: {seg['avg_energy']} | Beats: {beat_count}")

    # Print first few beats
    print(f"\nFirst 10 beats (seconds):")
    print(f"  {result['beats'][:10]}")

    # Print some peaks
    print(f"\nFirst 5 energy peaks:")
    for peak in result['peaks'][:5]:
        print(f"  {peak['time']}s (energy: {peak['energy']})")

    # Generate HTML visualization if requested
    if args.html:
        html_path = output_path.replace(".json", ".html")
        generate_html_viz(result, html_path)
        print(f"\nVisualization saved to: {html_path}")


def generate_html_viz(data, output_path):
    """Generate an HTML visualization of the beat map with multiple segments."""

    # Prepare data for chart
    energy_times = [p["time"] for p in data["energy_curve"]]
    energy_values = [p["energy"] for p in data["energy_curve"]]

    # Get all top segments (may be 1, 2, or 3)
    top_segments = data.get("top_segments", [])
    top_segment_beats = data.get("top_segment_beats", [])

    # Segment colors
    seg_colors = ['#f472b6', '#a78bfa', '#6366f1']  # Pink, Purple, Indigo
    seg_bg_colors = ['rgba(244, 114, 182, 0.15)', 'rgba(167, 139, 250, 0.15)', 'rgba(99, 102, 241, 0.15)']

    # Build segment info boxes HTML
    segment_boxes_html = ""
    for i, seg in enumerate(top_segments):
        beat_count = len(top_segment_beats[i]) if i < len(top_segment_beats) else 0
        color = seg_colors[i] if i < len(seg_colors) else '#888'
        label = "Most Energetic" if i == 0 else f"#{i+1} Most Energetic"
        segment_boxes_html += f'''
        <div class="segment-info" style="border-color: {color};">
            <h3 style="color: {color};">⚡ Segment #{i+1} ({label})</h3>
            <div class="time-range">{seg['start']}s → {seg['end']}s</div>
            <div style="margin-top: 0.5rem; color: #888;">
                Duration: {seg['duration']}s · Avg Energy: {seg['avg_energy']} · Beats: {beat_count}
            </div>
            <button class="play-btn" id="segBtn{i}" style="background: {color};" onclick="playSegment({i})">▶ Play Segment {i+1}</button>
        </div>
        '''

    # Build segment beats display HTML
    segment_beats_html = ""
    for i, seg in enumerate(top_segments):
        beats = top_segment_beats[i] if i < len(top_segment_beats) else []
        beat_count = len(beats)
        color_class = ['peak', 'beat', 'valley'][i] if i < 3 else 'beat'
        segment_beats_html += f'''
        <h2>Segment #{i+1} Beats ({beat_count} beats from {seg['start']}s to {seg['end']}s)</h2>
        <div class="beats-list">
            {"".join(f'<span class="beat {color_class}">{t}s</span>' for t in beats)}
        </div>
        '''

    # Build chart annotations for all segments
    annotations_js = ""
    for i, seg in enumerate(top_segments):
        color = seg_colors[i] if i < len(seg_colors) else '#888'
        bg_color = seg_bg_colors[i] if i < len(seg_bg_colors) else 'rgba(136, 136, 136, 0.15)'
        annotations_js += f'''
                            segment{i}: {{
                                type: 'box',
                                xMin: {seg['start']},
                                xMax: {seg['end']},
                                yMin: 0,
                                yMax: 1,
                                backgroundColor: '{bg_color}',
                                borderColor: '{color}',
                                borderWidth: 2,
                                label: {{
                                    display: true,
                                    content: 'Segment #{i+1}',
                                    position: 'start',
                                    color: '{color}',
                                    font: {{ weight: 'bold' }}
                                }}
                            }},'''

    # Build segments array for JavaScript
    segments_js = json.dumps([{"start": s["start"], "end": s["end"]} for s in top_segments])

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Beat Map: {data['file']}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation"></script>
    <style>
        body {{
            background: #0e0e0e;
            color: #e0e0e0;
            font-family: -apple-system, sans-serif;
            padding: 2rem;
        }}
        h1 {{ color: #a78bfa; }}
        h2 {{ color: #888; margin-top: 2rem; }}
        .stats {{
            display: flex;
            gap: 2rem;
            margin: 1rem 0;
            flex-wrap: wrap;
        }}
        .stat {{
            background: #1a1a1a;
            padding: 1rem;
            border-radius: 8px;
        }}
        .stat-value {{
            font-size: 2rem;
            color: #a78bfa;
            font-weight: bold;
        }}
        .segments-container {{
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            margin: 1rem 0;
        }}
        .segment-info {{
            background: linear-gradient(135deg, #1a1a1a, #2a1a2a);
            border: 1px solid;
            border-radius: 8px;
            padding: 1rem;
            flex: 1;
            min-width: 250px;
        }}
        .segment-info h3 {{
            margin: 0 0 0.5rem 0;
        }}
        .segment-info .time-range {{
            font-size: 1.25rem;
            color: #fff;
            font-weight: bold;
        }}
        .play-btn {{
            color: #0e0e0e;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 0.75rem;
            font-size: 0.9rem;
        }}
        .play-btn:hover {{
            opacity: 0.8;
        }}
        .audio-controls {{
            display: flex;
            align-items: center;
            gap: 1rem;
            margin: 1rem 0;
            flex-wrap: wrap;
        }}
        .time-display {{
            color: #a78bfa;
            font-family: monospace;
            font-size: 0.9rem;
        }}
        .chart-container {{
            background: #1a1a1a;
            border-radius: 8px;
            padding: 1rem;
            margin: 1rem 0;
        }}
        .beats-list {{
            background: #1a1a1a;
            padding: 1rem;
            border-radius: 8px;
            max-height: 200px;
            overflow-y: auto;
        }}
        .beat {{
            display: inline-block;
            background: #a78bfa;
            color: #0e0e0e;
            padding: 0.2rem 0.5rem;
            margin: 0.2rem;
            border-radius: 4px;
            font-size: 0.8rem;
        }}
        .peak {{ background: #f472b6; }}
        .valley {{ background: #6366f1; color: #fff; }}
    </style>
</head>
<body>
    <h1>Beat Map Analysis</h1>
    <p>File: {data['file']}</p>

    <div class="stats">
        <div class="stat">
            <div class="stat-value">{data['duration']}s</div>
            <div>Duration</div>
        </div>
        <div class="stat">
            <div class="stat-value">{data['tempo']}</div>
            <div>BPM</div>
        </div>
        <div class="stat">
            <div class="stat-value">{data['beat_count']}</div>
            <div>Beats</div>
        </div>
        <div class="stat">
            <div class="stat-value">{data['peak_count']}</div>
            <div>Peaks</div>
        </div>
        <div class="stat">
            <div class="stat-value">{data['valley_count']}</div>
            <div>Valleys</div>
        </div>
    </div>

    <h2>⚡ Top Segments ({len(top_segments)} most energetic ~15s windows)</h2>
    <div class="segments-container">
        {segment_boxes_html}
    </div>

    <div class="audio-controls">
        <button class="play-btn" style="background: #a78bfa;" onclick="playFullTrack()">▶ Play Full Track</button>
        <span class="time-display" id="timeDisplay">0:00 / 0:00</span>
    </div>
    <audio id="audioPlayer" style="display: none;">
        <source src="{os.path.basename(data['file'])}" type="audio/{data['file'].rsplit('.', 1)[-1].lower()}">
    </audio>

    <div class="chart-container">
        <canvas id="energyChart"></canvas>
    </div>

    {segment_beats_html}

    <h2>All Beat Timestamps</h2>
    <div class="beats-list">
        {"".join(f'<span class="beat">{t}s</span>' for t in data['beats'])}
    </div>

    <h2>Energy Peaks (Hills)</h2>
    <div class="beats-list">
        {"".join(f'<span class="beat peak">{p["time"]}s ({p["energy"]})</span>' for p in data['peaks'])}
    </div>

    <h2>Energy Valleys</h2>
    <div class="beats-list">
        {"".join(f'<span class="beat valley">{v["time"]}s ({v["energy"]})</span>' for v in data['valleys'])}
    </div>

    <script>
        // Convert to x/y points for proper numeric x-axis
        const energyData = {json.dumps([{"x": t, "y": e} for t, e in zip(energy_times, energy_values)])};

        const ctx = document.getElementById('energyChart').getContext('2d');
        new Chart(ctx, {{
            type: 'line',
            data: {{
                datasets: [{{
                    label: 'Energy',
                    data: energyData,
                    borderColor: '#a78bfa',
                    backgroundColor: 'rgba(167, 139, 250, 0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    x: {{
                        type: 'linear',
                        title: {{ display: true, text: 'Time (seconds)', color: '#888' }},
                        ticks: {{ color: '#888' }},
                        grid: {{ color: '#333' }},
                        min: 0,
                        max: {data['duration']}
                    }},
                    y: {{
                        title: {{ display: true, text: 'Energy', color: '#888' }},
                        ticks: {{ color: '#888' }},
                        grid: {{ color: '#333' }},
                        min: 0,
                        max: 1
                    }}
                }},
                plugins: {{
                    legend: {{ labels: {{ color: '#888' }} }},
                    annotation: {{
                        annotations: {{{annotations_js}
                        }}
                    }}
                }}
            }}
        }});

        // Audio playback controls for multiple segments
        const audio = document.getElementById('audioPlayer');
        const timeDisplay = document.getElementById('timeDisplay');
        const segments = {segments_js};
        let currentSegment = -1;

        function formatTime(seconds) {{
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return mins + ':' + secs.toString().padStart(2, '0');
        }}

        function updateButtons() {{
            for (let i = 0; i < segments.length; i++) {{
                const btn = document.getElementById('segBtn' + i);
                if (btn) {{
                    btn.textContent = (currentSegment === i && !audio.paused)
                        ? '⏸ Pause'
                        : '▶ Play Segment ' + (i + 1);
                }}
            }}
        }}

        function playSegment(index) {{
            if (currentSegment === index && !audio.paused) {{
                // Same segment playing - pause it
                audio.pause();
                currentSegment = -1;
            }} else {{
                // Start this segment
                currentSegment = index;
                audio.currentTime = segments[index].start;
                audio.play();
            }}
            updateButtons();
        }}

        function playFullTrack() {{
            currentSegment = -1;
            if (audio.paused) {{
                audio.currentTime = 0;
                audio.play();
            }} else {{
                audio.pause();
                audio.currentTime = 0;
            }}
            updateButtons();
        }}

        audio.addEventListener('timeupdate', function() {{
            timeDisplay.textContent = formatTime(audio.currentTime) + ' / ' + formatTime(audio.duration || 0);

            // Auto-pause at segment end if playing a segment
            if (currentSegment >= 0 && audio.currentTime >= segments[currentSegment].end) {{
                audio.pause();
                currentSegment = -1;
                updateButtons();
            }}
        }});

        audio.addEventListener('pause', updateButtons);

        audio.addEventListener('ended', function() {{
            currentSegment = -1;
            updateButtons();
        }});
    </script>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)


if __name__ == "__main__":
    main()

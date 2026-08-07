#!/usr/bin/env python3
"""
Plan Edit - Match clips to beats for automated video editing

Takes beat map JSON and clip tags JSON, outputs an edit decision list (EDL)
that maps which clip goes where, synced to audio beats/energy.

Usage:
    python3 plan_edit.py <beatmap.json> <clips.json> [--output edl.json]
"""

import sys
import os
import json
import argparse
import random


def load_json(path):
    """Load a JSON file."""
    with open(path, 'r') as f:
        return json.load(f)


def parse_time(tok):
    """Parse a token as seconds. Accepts '138', '138.5', or 'M:SS'."""
    tok = tok.strip()
    if ':' in tok:
        m, s = tok.split(':')
        return int(m) * 60 + float(s)
    return float(tok)


def resolve_clip_token(tok, clips, default_dur=4.0):
    """Resolve an override token to a clip dict.

    - integer string -> the detected clip with that id
    - time string (secs or M:SS) -> a synthetic clip sourced from that exact
      time, inheriting energy/motion from the detected scene containing it.
    Returns None if an id isn't found.
    """
    tok = tok.strip()
    if tok.lstrip('-').isdigit():
        cid = int(tok)
        for c in clips:
            if c['id'] == cid:
                return dict(c)
        return None
    t = parse_time(tok)
    host = next((c for c in clips if c['start'] <= t <= c['end']), None)
    return {
        'id': f"t{tok}",
        'start': t,
        'end': t + default_dur,
        'duration': default_dur,
        'motion': host['motion'] if host else 'medium',
        'motion_score': host.get('motion_score', 0) if host else 0,
        'brightness': host.get('brightness', 0.5) if host else 0.5,
        'energy': host['energy'] if host else 0.5,
        '_exact': True,  # sample from exactly this time, not mid-scene
    }


def parse_exclude(spec, clips):
    """Parse --exclude into a set of clip ids to drop.

    Tokens: 'N' = clip id; 'a-b' (secs or M:SS) = drop clips whose midpoint
    falls in that source-time range.
    """
    drop = set()
    if not spec:
        return drop
    for tok in spec.split(','):
        tok = tok.strip()
        if not tok:
            continue
        if '-' in tok and not tok.lstrip('-').isdigit():
            a, b = tok.split('-', 1)
            lo, hi = parse_time(a), parse_time(b)
            for c in clips:
                mid = (c['start'] + c['end']) / 2
                if lo <= mid <= hi:
                    drop.add(c['id'])
        else:
            drop.add(int(tok))
    return drop


def match_clips_to_beats(beatmap, clips_data, use_best_segment=True, segment_index=0,
                         exclude=None, lead=None, pin=None, beat_stride=1):
    """
    Match clips to beat timestamps based on energy levels.

    Strategy:
    - High energy beats → high energy/fast clips
    - Low energy moments → slow/static clips
    - Peaks → most impactful clips
    - Valleys → transition/breathing room clips

    Manual overrides (all optional, auto-fill handles the rest):
        exclude: --exclude spec string (clip ids and/or 'a-b' time ranges)
        lead: list of tokens (clip id or time) forced as the first cuts, in order
        pin: dict {'8' or 'peak2'/'valley1': token} pinning a clip to a beat index
             or to the Nth peak/valley
        segment_index: Which segment to use (0=best, 1=second, 2=third)
    """

    # Get the time range to work with
    segment = None
    if use_best_segment:
        # Try top_segments array first (new format)
        if 'top_segments' in beatmap:
            if segment_index < len(beatmap['top_segments']):
                segment = beatmap['top_segments'][segment_index]
                print(f"  Using segment #{segment_index + 1}: {segment['start']}s - {segment['end']}s")
            else:
                # Requested segment doesn't exist, use highest available
                print(f"  Warning: Only {len(beatmap['top_segments'])} segments available, using segment #{len(beatmap['top_segments'])}")
                segment = beatmap['top_segments'][-1]
        # Fallback to best_segment (old format)
        elif 'best_segment' in beatmap:
            if segment_index > 0:
                print(f"  Warning: This beat-map only has 1 segment (regenerate with updated beat_map.py for multiple segments)")
            segment = beatmap['best_segment']

    if segment:
        start_time = segment['start']
        end_time = segment['end']
        duration = segment['duration']
        # Filter beats to segment
        beats = [b for b in beatmap['beats'] if start_time <= b <= end_time]
        # Adjust beat times to be relative to segment start
        beats_relative = [round(b - start_time, 3) for b in beats]
    else:
        start_time = 0
        end_time = beatmap['duration']
        duration = beatmap['duration']
        beats = beatmap['beats']
        beats_relative = beats

    # Get clips sorted by energy
    clips = clips_data['clips']
    all_clips = list(clips)  # keep full list for resolving override tokens

    # Manual exclude (clip ids and/or time ranges)
    drop_ids = parse_exclude(exclude, clips) if exclude else set()
    if drop_ids:
        print(f"  Excluding {len(drop_ids)} clip(s) by override: {sorted(drop_ids, key=str)}")
        clips = [c for c in clips if c['id'] not in drop_ids]

    # Skip near-black clips (fade-ins, title cards, black intro screens)
    MIN_BRIGHTNESS = 0.04
    dark = [c for c in clips if c.get('brightness', 1.0) < MIN_BRIGHTNESS]
    if dark:
        print(f"  Skipping {len(dark)} near-black clip(s): {[c['id'] for c in dark]}")
        clips = [c for c in clips if c.get('brightness', 1.0) >= MIN_BRIGHTNESS]
    high_energy_clips = sorted([c for c in clips if c['energy'] >= 0.5],
                                key=lambda x: x['energy'], reverse=True)
    low_energy_clips = sorted([c for c in clips if c['energy'] < 0.5],
                               key=lambda x: x['energy'])

    # Get peaks and valleys within our segment
    peaks = []
    valleys = []

    if 'peaks' in beatmap:
        if use_best_segment and 'best_segment' in beatmap:
            peaks = [p for p in beatmap['peaks']
                     if start_time <= p['time'] <= end_time]
            # Adjust to relative time
            peaks = [{'time': round(p['time'] - start_time, 3), 'energy': p['energy']}
                     for p in peaks]
        else:
            peaks = beatmap['peaks']

    if 'valleys' in beatmap:
        if use_best_segment and 'best_segment' in beatmap:
            valleys = [v for v in beatmap['valleys']
                       if start_time <= v['time'] <= end_time]
            valleys = [{'time': round(v['time'] - start_time, 3), 'energy': v['energy']}
                       for v in valleys]
        else:
            valleys = beatmap['valleys']

    # Build edit decision list
    edl = []
    used_clips = set()

    # Consecutive cuts prefer source moments at least this far apart, so
    # shot/reverse-shot dialogue scenes don't produce visually identical cuts
    MIN_SOURCE_GAP = 15.0

    # Fill in beats with appropriate clips (each clip used only once)
    current_time = 0
    last_source_center = None

    # Pre-classify beats so regular beats can be spread across the full
    # source video instead of clustering at its start
    beat_types = []
    for bt in beats_relative:
        p = any(abs(bt - pk['time']) < 0.5 for pk in peaks)
        v = any(abs(bt - vl['time']) < 0.5 for vl in valleys)
        beat_types.append('peak' if p else ('valley' if v else 'beat'))

    # Optional cut thinning: keep every Nth beat so slow/contemplative footage
    # gets fewer, longer cuts that breathe, instead of one cut per beat. Peaks
    # are NOT force-kept — in high-energy windows nearly every beat is a peak,
    # which would defeat the thinning; even spacing is what "breathe" needs.
    if beat_stride and beat_stride > 1:
        keep = list(range(0, len(beats_relative), beat_stride))
        beats_relative = [beats_relative[i] for i in keep]
        beat_types = [beat_types[i] for i in keep]
        print(f"  Beat stride {beat_stride}: thinned to {len(beats_relative)} cuts")

    src_duration = max(c['end'] for c in clips)
    n_regular = beat_types.count('beat')
    regular_targets = [(k + 0.5) * src_duration / n_regular
                       for k in range(n_regular)] if n_regular else []
    regular_idx = 0

    # --- Resolve manual overrides into forced[beat_index] = clip ---
    # Beat indices used are the actual placement positions; the loop skips beats
    # whose time precedes current_time, so we map onto the sequential beats list.
    forced = {}            # beat_index -> resolved clip dict
    forced_clip_ids = set()

    def _resolve(tok):
        c = resolve_clip_token(tok, all_clips)
        if c is None:
            print(f"  WARNING: override clip id '{tok}' not found, skipping")
        return c

    # lead: first N beats (in order)
    for k, tok in enumerate(lead or []):
        c = _resolve(tok)
        if c is not None:
            forced[k] = c
            if isinstance(c['id'], int):
                forced_clip_ids.add(c['id'])

    # pin: explicit beat index or peakN / valleyN
    peak_idx = [i for i, t in enumerate(beat_types) if t == 'peak']
    valley_idx = [i for i, t in enumerate(beat_types) if t == 'valley']
    for key, tok in (pin or {}).items():
        key = str(key).strip().lower()
        bi = None
        if key.startswith('peak'):
            n = int(key[4:] or 1) - 1
            bi = peak_idx[n] if n < len(peak_idx) else None
        elif key.startswith('valley'):
            n = int(key[6:] or 1) - 1
            bi = valley_idx[n] if n < len(valley_idx) else None
        else:
            bi = int(key)
        if bi is None:
            print(f"  WARNING: pin target '{key}' out of range, skipping")
            continue
        c = _resolve(tok)
        if c is not None:
            forced[bi] = c
            if isinstance(c['id'], int):
                forced_clip_ids.add(c['id'])
    if forced:
        print(f"  Forced placements: " +
              ", ".join(f"beat{bi}=clip{forced[bi]['id']}" for bi in sorted(forced)))

    def spaced(pool):
        """Prefer clips far from the previous cut's source position."""
        if last_source_center is None:
            return pool
        far = [c for c in pool
               if abs((c['start'] + c['end']) / 2 - last_source_center) >= MIN_SOURCE_GAP]
        return far if far else pool

    for i, beat_time in enumerate(beats_relative):
        if beat_time < current_time:
            continue

        # Determine if this is a peak, valley, or regular beat
        is_peak = beat_types[i] == 'peak'
        is_valley = beat_types[i] == 'valley'

        # Manual override: a forced clip for this beat wins over auto-matching
        if i in forced:
            clip = forced[i]
        else:
            # Get ALL unused clips - stop if none available (skip forced ids)
            unused = [c for c in clips
                      if c['id'] not in used_clips and c['id'] not in forced_clip_ids]
            if not unused:
                break  # No more clips available - stop the edit

            # Select appropriate clip from unused pool
            if is_peak:
                # Highest energy clip, preferring high-energy pool then spacing
                pool = spaced([c for c in unused if c['energy'] >= 0.5] or unused)
                clip = max(pool, key=lambda c: c['energy'])
            elif is_valley:
                # Lowest energy clip, preferring low-energy pool then spacing
                pool = spaced([c for c in unused if c['energy'] < 0.5] or unused)
                clip = min(pool, key=lambda c: c['energy'])
            else:
                # Regular beat - nearest clip to this beat's spread target, so
                # quiet cuts sample the whole video and follow its narrative arc
                target = regular_targets[min(regular_idx, n_regular - 1)]
                pool = spaced(unused)
                clip = min(pool, key=lambda c: abs((c['start'] + c['end']) / 2 - target))
                regular_idx += 1

        used_clips.add(clip['id'])
        last_source_center = (clip['start'] + clip['end']) / 2

        # Calculate clip duration (until next beat or end)
        if i + 1 < len(beats_relative):
            clip_duration = min(beats_relative[i + 1] - beat_time, clip['duration'])
        else:
            clip_duration = min(duration - beat_time, clip['duration'])

        # Ensure minimum clip duration
        clip_duration = max(clip_duration, 0.2)

        # Sample from the middle of the scene, not the start, so visually
        # similar shots at least show different action. Exception: a forced
        # time-clip samples from exactly the requested moment.
        if clip.get('_exact'):
            src_start = clip['start']
        else:
            src_start = clip['start'] + max(0.0, (clip['duration'] - clip_duration) / 2)

        edl.append({
            "timeline_start": round(beat_time, 3),
            "timeline_end": round(beat_time + clip_duration, 3),
            "clip_id": clip['id'],
            "clip_source": clip.get('source', clips_data.get('source', '')),
            "clip_start": round(src_start, 3),
            "clip_end": round(min(src_start + clip_duration, clip['end']), 3),
            "clip_duration": round(clip_duration, 3),
            "clip_motion": clip['motion'],
            "clip_energy": clip['energy'],
            "beat_type": "peak" if is_peak else ("valley" if is_valley else "beat")
        })

        current_time = beat_time + clip_duration

    # Calculate actual duration based on edits (may be shorter if clips ran out)
    actual_duration = edl[-1]['timeline_end'] if edl else 0

    return {
        "audio_source": beatmap['file'],
        "video_source": clips_data.get('source', clips_data.get('sources', ['unknown'])),
        "timeline_duration": round(actual_duration, 3),
        "audio_segment": {
            "start": start_time,
            "end": round(start_time + actual_duration, 3),
            "duration": round(actual_duration, 3)
        } if use_best_segment else None,
        "tempo": beatmap['tempo'],
        "edit_count": len(edl),
        "edits": edl
    }


def main():
    parser = argparse.ArgumentParser(description="Match clips to beats for video editing")
    parser.add_argument("beatmap", help="Beat map JSON file from /beat-map")
    parser.add_argument("clips", help="Clip tags JSON file from /clip-tag")
    parser.add_argument("-o", "--output", help="Output EDL JSON file path", default=None)
    parser.add_argument("--full", action="store_true",
                        help="Use full audio duration instead of best segment")
    parser.add_argument("--segment", type=int, default=1, choices=[1, 2, 3],
                        help="Which segment to use: 1=best (default), 2=second, 3=third")
    parser.add_argument("--html", action="store_true", help="Generate HTML visualization")
    parser.add_argument("--exclude", default=None,
                        help="Drop clips: ids and/or time ranges, e.g. '1,6,0-30,1:00-1:05'")
    parser.add_argument("--lead", default=None,
                        help="Force first cuts in order: clip ids or times, e.g. '2:18,5,1:05'")
    parser.add_argument("--pin", default=None,
                        help="Pin clip to beat: 'beat=token' comma-list, e.g. '8=138,peak2=22' "
                             "(left: beat index or peakN/valleyN; right: clip id or time)")
    parser.add_argument("--beat-stride", type=int, default=1,
                        help="Cut density: 1 = every beat (default). N>1 keeps every Nth beat "
                             "(fewer, longer cuts that breathe — for slow/contemplative footage)")

    args = parser.parse_args()

    lead = [t.strip() for t in args.lead.split(',')] if args.lead else None
    pin = {}
    if args.pin:
        for pair in args.pin.split(','):
            if '=' in pair:
                k, v = pair.split('=', 1)
                pin[k.strip()] = v.strip()
    pin = pin or None

    # Convert segment to 0-indexed
    segment_index = args.segment - 1

    # Load input files
    print(f"Loading beat map: {args.beatmap}")
    beatmap = load_json(args.beatmap)

    print(f"Loading clip tags: {args.clips}")
    clips_data = load_json(args.clips)

    print(f"\nAudio: {beatmap['file']}")
    print(f"  Duration: {beatmap['duration']}s")
    print(f"  Tempo: {beatmap['tempo']} BPM")
    print(f"  Beats: {beatmap['beat_count']}")

    if not args.full:
        # Show available segments
        if 'top_segments' in beatmap:
            print(f"  Available segments: {len(beatmap['top_segments'])}")
            for i, seg in enumerate(beatmap['top_segments']):
                marker = "→" if i == segment_index else " "
                print(f"    {marker} #{i+1}: {seg['start']}s - {seg['end']}s (energy: {seg['avg_energy']})")
        elif 'best_segment' in beatmap:
            seg = beatmap['best_segment']
            print(f"  Best segment: {seg['start']}s - {seg['end']}s ({seg['duration']}s)")

    print(f"\nClips: {clips_data['clip_count']} available")

    # Match clips to beats
    print("\nMatching clips to beats...")
    edl = match_clips_to_beats(beatmap, clips_data,
                               use_best_segment=not args.full,
                               segment_index=segment_index,
                               exclude=args.exclude, lead=lead, pin=pin,
                               beat_stride=args.beat_stride)

    if args.exclude or lead or pin:
        edl["overrides"] = {"exclude": args.exclude, "lead": lead, "pin": pin}

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        base = os.path.splitext(os.path.basename(args.beatmap))[0].replace('_beatmap', '')
        output_path = f"{base}_edl.json"

    # Write EDL
    with open(output_path, 'w') as f:
        json.dump(edl, f, indent=2)

    print(f"\nEdit decision list saved to: {output_path}")

    # Summary
    print(f"\nSummary:")
    print(f"  Timeline duration: {edl['timeline_duration']}s")
    print(f"  Total edits: {edl['edit_count']}")

    # Count by beat type
    beat_types = {"peak": 0, "valley": 0, "beat": 0}
    for edit in edl['edits']:
        beat_types[edit['beat_type']] += 1

    print(f"  Peak cuts: {beat_types['peak']}")
    print(f"  Valley cuts: {beat_types['valley']}")
    print(f"  Regular beats: {beat_types['beat']}")

    # Show first few edits
    print(f"\nFirst 5 edits:")
    for edit in edl['edits'][:5]:
        print(f"  {edit['timeline_start']}s: Clip #{edit['clip_id']} ({edit['clip_motion']}) [{edit['beat_type']}]")

    # Generate HTML if requested
    if args.html:
        html_path = output_path.replace('.json', '.html')
        generate_html(edl, beatmap, clips_data, html_path)
        print(f"\nVisualization saved to: {html_path}")


def generate_html(edl, beatmap, clips_data, output_path):
    """Generate HTML visualization of the edit plan."""

    # Build timeline visualization
    timeline_items = []
    for edit in edl['edits']:
        beat_color = {
            "peak": "#f472b6",
            "valley": "#6366f1",
            "beat": "#a78bfa"
        }.get(edit['beat_type'], "#888")

        motion_label = edit['clip_motion'].upper()

        width_pct = (edit['clip_duration'] / edl['timeline_duration']) * 100
        left_pct = (edit['timeline_start'] / edl['timeline_duration']) * 100

        timeline_items.append(f'''
            <div class="timeline-clip" style="left: {left_pct}%; width: {width_pct}%; background: {beat_color};"
                 title="Clip #{edit['clip_id']} | {edit['timeline_start']}s - {edit['timeline_end']}s | {motion_label}">
                <span class="clip-label">#{edit['clip_id']}</span>
            </div>
        ''')

    # Build edit list
    edit_rows = []
    for edit in edl['edits']:
        beat_badge = {
            "peak": '<span class="badge peak">PEAK</span>',
            "valley": '<span class="badge valley">VALLEY</span>',
            "beat": '<span class="badge beat">BEAT</span>'
        }.get(edit['beat_type'], '')

        edit_rows.append(f'''
            <tr>
                <td>{edit['timeline_start']}s</td>
                <td>#{edit['clip_id']}</td>
                <td>{edit['clip_motion']}</td>
                <td>{edit['clip_energy']}</td>
                <td>{edit['clip_duration']}s</td>
                <td>{beat_badge}</td>
            </tr>
        ''')

    html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Edit Plan: {edl['audio_source']}</title>
    <style>
        body {{
            background: #0e0e0e;
            color: #e0e0e0;
            font-family: -apple-system, sans-serif;
            padding: 2rem;
            margin: 0;
        }}
        h1 {{ color: #a78bfa; margin-bottom: 0.5rem; }}
        h2 {{ color: #888; margin-top: 2rem; }}
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
        .timeline-container {{
            background: #1a1a1a;
            border-radius: 8px;
            padding: 1rem;
            margin: 1rem 0;
            position: relative;
            height: 60px;
        }}
        .timeline-track {{
            position: relative;
            height: 40px;
            background: #333;
            border-radius: 4px;
            overflow: hidden;
        }}
        .timeline-clip {{
            position: absolute;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.7rem;
            font-weight: 600;
            color: #fff;
            border-right: 1px solid #0e0e0e;
            cursor: pointer;
            transition: opacity 0.2s;
        }}
        .timeline-clip:hover {{
            opacity: 0.8;
        }}
        .clip-label {{
            text-shadow: 0 1px 2px rgba(0,0,0,0.5);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #1a1a1a;
            border-radius: 8px;
            overflow: hidden;
        }}
        th, td {{
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid #333;
        }}
        th {{
            background: #252525;
            color: #a78bfa;
        }}
        .badge {{
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 600;
        }}
        .badge.peak {{ background: #f472b6; color: #0e0e0e; }}
        .badge.valley {{ background: #6366f1; color: #fff; }}
        .badge.beat {{ background: #a78bfa; color: #0e0e0e; }}
        .legend {{
            display: flex;
            gap: 1rem;
            margin-top: 0.5rem;
            font-size: 0.85rem;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .legend-color {{
            width: 12px;
            height: 12px;
            border-radius: 2px;
        }}
    </style>
</head>
<body>
    <h1>Edit Plan</h1>
    <p class="subtitle">Audio: {edl['audio_source']} | Clips: {clips_data.get('source', 'Multiple sources')}</p>

    <div class="stats">
        <div class="stat">
            <div class="stat-value">{edl['timeline_duration']}s</div>
            <div>Duration</div>
        </div>
        <div class="stat">
            <div class="stat-value">{edl['tempo']}</div>
            <div>BPM</div>
        </div>
        <div class="stat">
            <div class="stat-value">{edl['edit_count']}</div>
            <div>Cuts</div>
        </div>
        <div class="stat">
            <div class="stat-value">{clips_data['clip_count']}</div>
            <div>Available Clips</div>
        </div>
    </div>

    <h2>Timeline</h2>
    <div class="timeline-container">
        <div class="timeline-track">
            {"".join(timeline_items)}
        </div>
    </div>
    <div class="legend">
        <div class="legend-item"><div class="legend-color" style="background: #f472b6;"></div> Peak</div>
        <div class="legend-item"><div class="legend-color" style="background: #a78bfa;"></div> Beat</div>
        <div class="legend-item"><div class="legend-color" style="background: #6366f1;"></div> Valley</div>
    </div>

    <h2>Edit List</h2>
    <table>
        <thead>
            <tr>
                <th>Time</th>
                <th>Clip</th>
                <th>Motion</th>
                <th>Energy</th>
                <th>Duration</th>
                <th>Type</th>
            </tr>
        </thead>
        <tbody>
            {"".join(edit_rows)}
        </tbody>
    </table>
</body>
</html>'''

    with open(output_path, 'w') as f:
        f.write(html)


if __name__ == "__main__":
    main()

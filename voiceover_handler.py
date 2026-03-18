"""
voiceover_handler.py

Manages voiceover generation for commentary segments.
Supports TTS (via ai33_tts.py) and manual upload/recording.
"""

import json
import os
import subprocess
from typing import Optional

from config import VOICEOVER_DIR
from ai33_tts import generate_voiceover
from clip_extractor import get_clip_duration

os.makedirs(VOICEOVER_DIR, exist_ok=True)


def generate_tts_voiceovers(
    script: dict,
    voice: str = "21m00Tcm4TlvDq8ikWAM",
    model_id: str = "eleven_multilingual_v2",
    progress_callback=None,
    output_dir: str = None,
) -> dict:
    """
    Generate TTS voiceover for all VO segments in the script.

    Returns:
    {
        "voiceover_segments": [
            {
                "segment_id": int,
                "type": str,
                "audio_path": str,
                "duration_sec": float,
                "vo_text": str,
            }
        ],
        "total_vo_duration_sec": float,
    }
    """
    vo_dir = output_dir or VOICEOVER_DIR
    os.makedirs(vo_dir, exist_ok=True)

    segments = script.get("segments", [])
    vo_segments = [s for s in segments if s["type"].endswith("_voiceover")]

    results = []
    total_duration = 0.0

    for i, seg in enumerate(vo_segments):
        seg_id = seg["segment_id"]
        vo_text = seg.get("vo_text", "")
        if not vo_text:
            continue

        output_path = os.path.join(vo_dir, f"vo_seg_{seg_id:03d}.mp3")

        if progress_callback:
            progress_callback(f"Generating VO {i + 1}/{len(vo_segments)}: {vo_text[:40]}...")

        print(f"  [VO] Generating segment {seg_id}: {vo_text[:50]}...")
        audio_path = generate_voiceover(
            text=vo_text,
            output_path=output_path,
            voice_id=voice,
            model_id=model_id,
        )

        if audio_path and os.path.exists(audio_path):
            duration = get_clip_duration(audio_path)
            total_duration += duration
            results.append({
                "segment_id": seg_id,
                "type": seg["type"],
                "audio_path": audio_path,
                "duration_sec": duration,
                "vo_text": vo_text,
            })
            print(f"  [VO] Segment {seg_id}: {duration:.1f}s")
        else:
            print(f"  [VO] Failed to generate segment {seg_id}")

    print(f"[VO] Total: {len(results)} segments, {total_duration:.1f}s")
    return {
        "voiceover_segments": results,
        "total_vo_duration_sec": total_duration,
    }


def register_uploaded_voiceover(
    segment_id: int,
    file_path: str,
    vo_text: str = "",
    output_dir: str = None,
) -> Optional[dict]:
    """
    Register a manually uploaded/recorded voiceover file.

    Returns segment info dict, or None if file is invalid.
    """
    if not os.path.exists(file_path):
        return None

    duration = get_clip_duration(file_path)
    if duration <= 0:
        return None

    # Copy to standard location
    vo_dir = output_dir or VOICEOVER_DIR
    os.makedirs(vo_dir, exist_ok=True)
    output_path = os.path.join(vo_dir, f"vo_seg_{segment_id:03d}.mp3")
    if file_path != output_path:
        import shutil
        shutil.copy2(file_path, output_path)

    return {
        "segment_id": segment_id,
        "type": "voiceover",
        "audio_path": output_path,
        "duration_sec": duration,
        "vo_text": vo_text,
    }


def get_vo_for_segment(segment_id: int, output_dir: str = None) -> Optional[str]:
    """Check if a voiceover file exists for a segment."""
    vo_dir = output_dir or VOICEOVER_DIR
    path = os.path.join(vo_dir, f"vo_seg_{segment_id:03d}.mp3")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    return None

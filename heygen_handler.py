"""
heygen_handler.py

HeyGen Avatar III integration for commentary video generation.
Sends VO text to HeyGen API → gets back MP4 with avatar speaking.
Uses API key auth; Avatar III is free/unlimited on web plans.
"""

import json
import os
import time
import requests
from typing import Optional

from config import HEYGEN_API_KEY, OUTPUT_DIR

HEYGEN_BASE = "https://api.heygen.com"
HEYGEN_CLIPS_DIR = os.path.join(OUTPUT_DIR, "heygen_clips")
os.makedirs(HEYGEN_CLIPS_DIR, exist_ok=True)


def _headers():
    return {
        "X-Api-Key": HEYGEN_API_KEY,
        "Content-Type": "application/json",
    }


def list_avatars() -> list:
    """List all available avatars (free only)."""
    resp = requests.get(f"{HEYGEN_BASE}/v2/avatars", headers=_headers(), timeout=30)
    data = resp.json()
    avatars = data.get("data", {}).get("avatars", [])

    # Deduplicate and filter free only
    seen = set()
    result = []
    for a in avatars:
        aid = a["avatar_id"]
        if aid in seen:
            continue
        seen.add(aid)
        if not a.get("premium", False):
            result.append({
                "avatar_id": aid,
                "avatar_name": a.get("avatar_name", "Unknown"),
                "gender": a.get("gender", "unknown"),
                "preview_image_url": a.get("preview_image_url", ""),
                "preview_video_url": a.get("preview_video_url", ""),
            })

    return sorted(result, key=lambda x: x["avatar_name"])


def list_voices(language: str = "en") -> list:
    """List available English voices."""
    resp = requests.get(f"{HEYGEN_BASE}/v2/voices", headers=_headers(), timeout=30)
    data = resp.json()
    voices = data.get("data", {}).get("voices", [])

    result = []
    for v in voices:
        lang = v.get("language", "")
        if not lang.lower().startswith(language):
            continue
        result.append({
            "voice_id": v.get("voice_id", ""),
            "display_name": v.get("display_name", v.get("name", "Unknown")),
            "gender": v.get("gender", "unknown"),
            "language": lang,
            "preview_audio": v.get("preview_audio", ""),
        })

    return sorted(result, key=lambda x: x["display_name"])


def generate_avatar_video(
    text: str,
    avatar_id: str,
    voice_id: str,
    segment_id: int,
    progress_callback=None,
    output_dir: str = None,
) -> Optional[str]:
    """
    Generate an Avatar III video for a single commentary segment.

    Args:
        text: The commentary VO text
        avatar_id: HeyGen avatar ID
        voice_id: HeyGen voice ID
        segment_id: Segment number (for filename)
        progress_callback: Optional progress function

    Returns:
        Path to downloaded MP4, or None on failure.
    """

    def progress(msg):
        if progress_callback:
            progress_callback(msg)
        print(f"  [HeyGen] {msg}")

    # Step 1: Submit video generation
    payload = {
        "video_inputs": [
            {
                "character": {
                    "type": "avatar",
                    "avatar_id": avatar_id,
                    "avatar_style": "normal",
                },
                "voice": {
                    "type": "text",
                    "input_text": text,
                    "voice_id": voice_id,
                    "speed": 1.0,
                },
                "background": {
                    "type": "color",
                    "value": "#1a1a2e",
                },
            }
        ],
        "dimension": {
            "width": 1920,
            "height": 1080,
        },
    }

    progress(f"Segment {segment_id}: Submitting to HeyGen...")

    try:
        resp = requests.post(
            f"{HEYGEN_BASE}/v2/video/generate",
            headers=_headers(),
            json=payload,
            timeout=60,
        )
        result = resp.json()
    except Exception as e:
        progress(f"Segment {segment_id}: Request failed: {e}")
        return None

    if result.get("error"):
        progress(f"Segment {segment_id}: API error: {result['error']}")
        return None

    video_id = result.get("data", {}).get("video_id")
    if not video_id:
        progress(f"Segment {segment_id}: No video_id returned")
        return None

    progress(f"Segment {segment_id}: Video queued (ID: {video_id}), polling...")

    # Step 2: Poll for completion
    clips_dir = output_dir or HEYGEN_CLIPS_DIR
    os.makedirs(clips_dir, exist_ok=True)
    output_path = os.path.join(clips_dir, f"heygen_seg_{segment_id:03d}.mp4")
    max_wait = 600  # 10 minutes max
    poll_interval = 10  # seconds

    elapsed = 0
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval

        try:
            status_resp = requests.get(
                f"{HEYGEN_BASE}/v1/video_status.get",
                headers=_headers(),
                params={"video_id": video_id},
                timeout=30,
            )
            status_data = status_resp.json()
        except Exception as e:
            progress(f"Segment {segment_id}: Status check failed: {e}")
            continue

        status = status_data.get("data", {}).get("status", "unknown")

        if status == "completed":
            video_url = status_data["data"].get("video_url")
            if not video_url:
                progress(f"Segment {segment_id}: Completed but no video_url")
                return None

            progress(f"Segment {segment_id}: Completed! Downloading...")

            # Step 3: Download the video
            try:
                dl_resp = requests.get(video_url, timeout=120, stream=True)
                with open(output_path, "wb") as f:
                    for chunk in dl_resp.iter_content(chunk_size=8192):
                        f.write(chunk)

                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    progress(f"Segment {segment_id}: Downloaded ({size_mb:.1f} MB)")
                    return output_path
                else:
                    progress(f"Segment {segment_id}: Download produced empty file")
                    return None
            except Exception as e:
                progress(f"Segment {segment_id}: Download failed: {e}")
                return None

        elif status == "failed":
            error = status_data.get("data", {}).get("error", "Unknown error")
            progress(f"Segment {segment_id}: Generation failed: {error}")
            return None

        elif status in ("processing", "pending"):
            if elapsed % 30 == 0:  # Log every 30s
                progress(f"Segment {segment_id}: Still {status}... ({elapsed}s)")
        else:
            progress(f"Segment {segment_id}: Unknown status: {status}")

    progress(f"Segment {segment_id}: Timed out after {max_wait}s")
    return None


def generate_all_commentary_segments(
    script: dict,
    avatar_id: str,
    voice_id: str,
    progress_callback=None,
    output_dir: str = None,
) -> dict:
    """
    Generate HeyGen avatar videos for all commentary/hook VO segments in the script.

    Returns dict with heygen_segments list mapping segment_id -> local MP4 path.
    """
    segments = script.get("segments", [])
    vo_segments = [s for s in segments if s["type"].endswith("_voiceover")]

    results = []
    for seg in vo_segments:
        seg_id = seg["segment_id"]
        vo_text = seg.get("vo_text", "")
        if not vo_text:
            continue

        mp4_path = generate_avatar_video(
            text=vo_text,
            avatar_id=avatar_id,
            voice_id=voice_id,
            segment_id=seg_id,
            progress_callback=progress_callback,
            output_dir=output_dir,
        )

        results.append({
            "segment_id": seg_id,
            "type": seg["type"],
            "vo_text": vo_text,
            "heygen_video_path": mp4_path,
            "success": mp4_path is not None,
        })

    successful = sum(1 for r in results if r["success"])
    total = len(results)

    return {
        "heygen_segments": results,
        "total": total,
        "successful": successful,
        "failed": total - successful,
    }

"""
ai33_tts.py

TTS voiceover generation via ai33.pro API (ElevenLabs-compatible).

Usage:
    audio_path = generate_voiceover(
        text="LeBron James just dropped 42 points tonight.",
        output_path="output/voiceover_seg0.mp3",
        voice_id="21m00Tcm4TlvDq8ikWAM",
    )
"""

import os
import time
import requests
from typing import Optional

from config import AI33_API_KEY

API_BASE = "https://api.ai33.pro"

# In-memory cache for voices
_voices_cache = None
_voices_cache_time = 0
VOICES_CACHE_TTL = 300  # 5 minutes


def _headers() -> dict:
    return {
        "xi-api-key": AI33_API_KEY,
        "Content-Type": "application/json",
    }


def list_voices() -> list:
    """Fetch available voices from ai33.pro API. Cached for 5 minutes."""
    global _voices_cache, _voices_cache_time

    if _voices_cache and (time.time() - _voices_cache_time) < VOICES_CACHE_TTL:
        return _voices_cache

    try:
        r = requests.get(
            f"{API_BASE}/v2/voices?page_size=100",
            headers={"xi-api-key": AI33_API_KEY},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            # API may return {"voices": [...]} or just [...]
            voices = data.get("voices", data) if isinstance(data, dict) else data
            _voices_cache = voices
            _voices_cache_time = time.time()
            print(f"  [AI33] Fetched {len(voices)} voices")
            return voices
        else:
            print(f"  [AI33] Failed to fetch voices: HTTP {r.status_code}")
            return []
    except Exception as e:
        print(f"  [AI33] Error fetching voices: {e}")
        return []


def search_voices(query: str, page_size: int = 25) -> list:
    """Search the full ai33.pro / ElevenLabs voice library."""
    try:
        r = requests.get(
            f"{API_BASE}/v1/shared-voices",
            headers={"xi-api-key": AI33_API_KEY},
            params={"search": query, "page_size": page_size},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            voices = data.get("voices", [])
            # Normalize fields to match /v2/voices format
            result = []
            for v in voices:
                result.append({
                    "voice_id": v.get("voice_id", ""),
                    "name": v.get("name", "Unknown"),
                    "preview_url": v.get("preview_url", ""),
                    "category": v.get("category", ""),
                    "labels": {
                        "accent": v.get("accent", ""),
                        "gender": v.get("gender", ""),
                        "age": v.get("age", ""),
                        "descriptive": v.get("descriptive", ""),
                        "use_case": v.get("use_case", ""),
                    },
                    "description": v.get("description", ""),
                    "source": "library",
                })
            return result
        else:
            print(f"  [AI33] Voice search failed: HTTP {r.status_code}")
            return []
    except Exception as e:
        print(f"  [AI33] Voice search error: {e}")
        return []


def _poll_task(task_id: str, timeout: int = 180, interval: int = 3) -> Optional[dict]:
    """Poll GET /v1/task/{task_id} until done or timeout."""
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            r = requests.get(
                f"{API_BASE}/v1/task/{task_id}",
                headers={"xi-api-key": AI33_API_KEY},
                timeout=15,
            )
            if r.status_code == 200:
                task = r.json()
                status = task.get("status", "")
                if status == "done":
                    print(f"  [AI33] Task {task_id} completed")
                    return task
                elif status in ("failed", "error"):
                    err = task.get("error_message", "unknown error")
                    print(f"  [AI33] Task {task_id} failed: {err}")
                    return None
                # still processing — keep polling
            else:
                print(f"  [AI33] Poll HTTP {r.status_code} for task {task_id}")
        except Exception as e:
            print(f"  [AI33] Poll error: {e}")

        time.sleep(interval)

    print(f"  [AI33] Polling timed out after {timeout}s for task {task_id}")
    return None


def generate_voiceover(
    text: str,
    output_path: str,
    voice_id: str = "21m00Tcm4TlvDq8ikWAM",
    model_id: str = "eleven_multilingual_v2",
    timeout: int = 180,
) -> Optional[str]:
    """
    Generate a voiceover audio file via ai33.pro TTS API.

    Returns path to the downloaded audio file, or None on failure.
    """
    if not AI33_API_KEY:
        print("  [AI33] ERROR: AI33_API_KEY not set")
        return None

    print(f"  [AI33] Generating TTS (voice={voice_id}, model={model_id}): {text[:60]}...")

    # Step 1: Submit TTS task
    try:
        r = requests.post(
            f"{API_BASE}/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
            headers=_headers(),
            json={
                "text": text,
                "model_id": model_id,
            },
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  [AI33] TTS submit failed: HTTP {r.status_code} — {r.text[:200]}")
            return None

        data = r.json()
        if not data.get("success"):
            print(f"  [AI33] TTS submit error: {data}")
            return None

        task_id = data.get("task_id")
        credits = data.get("ec_remain_credits", "?")
        print(f"  [AI33] Task submitted: {task_id} (credits remaining: {credits})")
    except Exception as e:
        print(f"  [AI33] TTS submit error: {e}")
        return None

    # Step 2: Poll for completion
    task = _poll_task(task_id, timeout=timeout)
    if not task:
        return None

    # Step 3: Download audio
    metadata = task.get("metadata", {})
    audio_url = metadata.get("audio_url")
    if not audio_url:
        print(f"  [AI33] No audio_url in task metadata: {list(metadata.keys())}")
        return None

    try:
        print(f"  [AI33] Downloading audio: {audio_url[:80]}...")
        r = requests.get(audio_url, timeout=60)
        if r.status_code == 200 and len(r.content) > 1000:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(r.content)
            size_kb = len(r.content) / 1024
            print(f"  [AI33] Saved {size_kb:.0f} KB → {output_path}")
            return output_path
        else:
            print(f"  [AI33] Audio download failed: HTTP {r.status_code}, size={len(r.content)}")
            return None
    except Exception as e:
        print(f"  [AI33] Download error: {e}")
        return None


if __name__ == "__main__":
    result = generate_voiceover(
        text="LeBron James just dropped 42 points tonight. His highest of the season.",
        output_path="output/test_vo.mp3",
    )
    print(f"Result: {result}")

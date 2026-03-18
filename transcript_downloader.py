"""
transcript_downloader.py

Downloads transcript + metadata from a YouTube video.
Primary: youtube-transcript-api (timestamped captions)
Fallback: yt-dlp auto-generated subtitles
"""

import json
import os
import re
import subprocess
from typing import Optional
from urllib.parse import parse_qs, urlparse


def extract_video_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/")
    if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith(("/embed/", "/v/", "/live/", "/shorts/")):
            return parsed.path.split("/")[2]
    return None


def get_video_metadata(video_id: str) -> dict:
    """Fetch video metadata using yt-dlp --dump-json."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            return {
                "video_id": video_id,
                "title": data.get("title", ""),
                "duration_seconds": data.get("duration", 0),
                "channel": data.get("channel", data.get("uploader", "")),
                "description": data.get("description", "")[:2000],
                "thumbnail": data.get("thumbnail", ""),
            }
    except Exception as e:
        print(f"  [Metadata] Error: {e}")
    return {
        "video_id": video_id,
        "title": "",
        "duration_seconds": 0,
        "channel": "",
        "description": "",
        "thumbnail": "",
    }


def download_transcript_api(video_id: str) -> Optional[list]:
    """Primary method: youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id, languages=["en"])
        return [
            {
                "text": snippet.text,
                "start": snippet.start,
                "duration": snippet.duration,
            }
            for snippet in transcript
        ]
    except Exception as e:
        print(f"  [Transcript API] Failed: {e}")
        return None


def download_transcript_ytdlp(video_id: str) -> Optional[list]:
    """Fallback: yt-dlp auto-generated subtitles."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)
    out_tmpl = os.path.join(out_dir, f"subs_{video_id}")

    cmd = [
        "yt-dlp",
        "--write-auto-sub",
        "--sub-lang", "en",
        "--sub-format", "json3",
        "--skip-download",
        "--no-playlist",
        "--quiet",
        "-o", out_tmpl,
        url,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
        # Find the generated subtitle file
        sub_file = f"{out_tmpl}.en.json3"
        if not os.path.exists(sub_file):
            # Try alternate naming
            for ext in [".en.json3", ".json3"]:
                candidate = out_tmpl + ext
                if os.path.exists(candidate):
                    sub_file = candidate
                    break

        if os.path.exists(sub_file):
            with open(sub_file) as f:
                data = json.load(f)
            os.remove(sub_file)

            entries = []
            for event in data.get("events", []):
                text_parts = []
                for seg in event.get("segs", []):
                    t = seg.get("utf8", "").strip()
                    if t and t != "\n":
                        text_parts.append(t)
                if text_parts:
                    start_ms = event.get("tStartMs", 0)
                    dur_ms = event.get("dDurationMs", 0)
                    entries.append({
                        "text": " ".join(text_parts),
                        "start": start_ms / 1000.0,
                        "duration": dur_ms / 1000.0,
                    })
            if entries:
                return entries
    except Exception as e:
        print(f"  [yt-dlp subs] Error: {e}")
    return None


def download_transcript(youtube_url: str) -> dict:
    """
    Main entry point. Downloads transcript + metadata.

    Returns:
    {
        "video_id": str,
        "title": str,
        "duration_seconds": int,
        "channel": str,
        "description": str,
        "thumbnail": str,
        "transcript": [{"text": str, "start": float, "duration": float}, ...],
        "full_text": str,
    }
    """
    video_id = extract_video_id(youtube_url)
    if not video_id:
        return {"error": f"Could not extract video ID from URL: {youtube_url}"}

    print(f"[Transcript] Downloading for video: {video_id}")

    # Get metadata
    metadata = get_video_metadata(video_id)
    print(f"  Title: {metadata['title']}")
    print(f"  Duration: {metadata['duration_seconds']}s")

    # Get transcript (try API first, then yt-dlp fallback)
    transcript = download_transcript_api(video_id)
    if not transcript:
        print("  Trying yt-dlp fallback...")
        transcript = download_transcript_ytdlp(video_id)

    if not transcript:
        return {**metadata, "error": "Could not download transcript", "transcript": [], "full_text": ""}

    # Build full text
    full_text = " ".join(entry["text"] for entry in transcript)
    print(f"  Transcript: {len(transcript)} segments, {len(full_text)} chars")

    return {
        **metadata,
        "transcript": transcript,
        "full_text": full_text,
    }


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    result = download_transcript(url)
    print(json.dumps(result, indent=2)[:2000])

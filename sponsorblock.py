"""
sponsorblock.py

Fetches sponsor/ad segment data from the SponsorBlock API.
Used to skip sponsored sections during video assembly.

API docs: https://wiki.sponsor.ajay.app/w/API_Docs
"""

import json
import urllib.request
import urllib.error
from typing import Optional


SPONSORBLOCK_API = "https://sponsor.ajay.app/api/skipSegments"

# Categories to skip (all ad-like content)
SKIP_CATEGORIES = [
    "sponsor",           # Paid promotion
    "selfpromo",         # Unpaid self-promotion
    "interaction",       # "Like and subscribe" reminders
    "intro",             # Animated intro/outro with no content
    "outro",             # Credits/end cards
    "preview",           # Preview of what's coming later
]


def fetch_sponsor_segments(video_id: str) -> list:
    """
    Fetch skip segments from SponsorBlock for a given video.

    Returns list of:
        {
            "start": float,
            "end": float,
            "category": str,
            "duration": float,
        }

    Returns empty list if no segments found or API unavailable.
    """
    categories_param = "&".join(f'category={c}' for c in SKIP_CATEGORIES)
    url = f"{SPONSORBLOCK_API}?videoID={video_id}&{categories_param}"

    print(f"[SponsorBlock] Fetching segments for {video_id}...")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CommentaryTool/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        segments = []
        for entry in data:
            seg = entry.get("segment", [])
            if len(seg) == 2:
                start, end = seg
                segments.append({
                    "start": round(float(start), 2),
                    "end": round(float(end), 2),
                    "category": entry.get("category", "sponsor"),
                    "duration": round(float(end) - float(start), 2),
                })

        # Sort by start time
        segments.sort(key=lambda s: s["start"])

        total_ad_time = sum(s["duration"] for s in segments)
        print(f"  Found {len(segments)} ad/sponsor segments ({total_ad_time:.0f}s total)")
        for s in segments:
            m1, s1 = divmod(int(s["start"]), 60)
            m2, s2 = divmod(int(s["end"]), 60)
            print(f"    {s['category']}: {m1}:{s1:02d} - {m2}:{s2:02d} ({s['duration']:.0f}s)")

        return segments

    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("  No sponsor segments found for this video")
        else:
            print(f"  SponsorBlock API error: {e.code}")
        return []
    except Exception as e:
        print(f"  SponsorBlock error: {e}")
        return []


def overlaps_ad(start_sec: float, end_sec: float, ad_segments: list) -> Optional[dict]:
    """
    Check if a time range overlaps with any ad segment.

    Returns the overlapping ad segment dict, or None if no overlap.
    """
    for ad in ad_segments:
        # Overlap if ranges intersect
        if start_sec < ad["end"] and end_sec > ad["start"]:
            return ad
    return None


def get_clean_ranges(start_sec: float, end_sec: float, ad_segments: list) -> list:
    """
    Given a time range and ad segments, return the non-ad sub-ranges.

    Example:
        range: 100-200
        ad: 130-150
        result: [(100, 130), (150, 200)]

    Returns list of (start, end) tuples representing clean (ad-free) ranges.
    """
    if not ad_segments:
        return [(start_sec, end_sec)]

    # Filter to only ads that overlap our range
    relevant_ads = []
    for ad in ad_segments:
        if ad["start"] < end_sec and ad["end"] > start_sec:
            relevant_ads.append(ad)

    if not relevant_ads:
        return [(start_sec, end_sec)]

    # Sort by start time
    relevant_ads.sort(key=lambda a: a["start"])

    clean = []
    cursor = start_sec

    for ad in relevant_ads:
        ad_start = max(ad["start"], start_sec)
        ad_end = min(ad["end"], end_sec)

        if cursor < ad_start:
            clean.append((cursor, ad_start))
        cursor = max(cursor, ad_end)

    if cursor < end_sec:
        clean.append((cursor, end_sec))

    return clean


def find_clean_video_range(
    start_sec: float,
    desired_duration: float,
    video_duration: float,
    ad_segments: list,
) -> tuple:
    """
    Find a clean (ad-free) video range starting near start_sec.

    If the desired range contains an ad, shift forward past the ad.
    Returns (adjusted_start, adjusted_end).
    """
    end_sec = start_sec + desired_duration

    if not ad_segments:
        return (start_sec, min(end_sec, video_duration))

    # Check if our range hits an ad
    for ad in ad_segments:
        if start_sec < ad["end"] and end_sec > ad["start"]:
            # Our range overlaps an ad — shift start to after the ad
            if start_sec >= ad["start"]:
                # We start inside the ad, jump past it
                start_sec = ad["end"] + 0.5
                end_sec = start_sec + desired_duration
            elif end_sec > ad["start"]:
                # Ad starts during our range — truncate before ad or skip past
                # If most of our content is before the ad, truncate
                clean_before = ad["start"] - start_sec
                if clean_before >= desired_duration * 0.6:
                    end_sec = ad["start"] - 0.5
                else:
                    # Skip past the ad
                    start_sec = ad["end"] + 0.5
                    end_sec = start_sec + desired_duration

    return (max(0, start_sec), min(end_sec, video_duration))


if __name__ == "__main__":
    import sys
    vid = sys.argv[1] if len(sys.argv) > 1 else "dQw4w9WgXcQ"
    segments = fetch_sponsor_segments(vid)
    print(json.dumps(segments, indent=2))

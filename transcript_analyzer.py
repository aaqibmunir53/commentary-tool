"""
transcript_analyzer.py

Uses Claude to analyze a video transcript:
- Identify speakers and their roles
- Break into topic segments with timestamps
- Generate stance options for the user
"""

import json
from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY


def analyze_transcript(transcript_data: dict) -> dict:
    """
    Analyze a transcript to identify speakers, topics, and stance options.

    Args:
        transcript_data: Output from transcript_downloader.download_transcript()

    Returns:
        {
            "speakers": [{"name": str, "role": str}, ...],
            "topics": [{"topic_id": int, "title": str, "start_sec": float, "end_sec": float,
                         "summary": str, "speaker_positions": {name: position}}, ...],
            "stance_options": [{"id": str, "label": str, "description": str}, ...],
            "video_type": str,  # "interview" | "press_conference" | "debate" | "panel" | "monologue"
            "estimated_final_duration_minutes": int,
        }
    """
    title = transcript_data.get("title", "")
    channel = transcript_data.get("channel", "")
    duration = transcript_data.get("duration_seconds", 0)
    description = transcript_data.get("description", "")[:1000]
    transcript = transcript_data.get("transcript", [])

    # Build timestamped transcript text
    transcript_text = _build_timestamped_text(transcript)

    prompt = f"""You are a video content analyst. Analyze this YouTube video transcript and extract structured information.

VIDEO TITLE: {title}
CHANNEL: {channel}
DURATION: {duration} seconds ({duration // 60} minutes)
DESCRIPTION: {description}

TIMESTAMPED TRANSCRIPT:
{transcript_text}

INSTRUCTIONS:
1. Identify all distinct speakers by their REAL FULL NAMES. Research the title, description, channel name, and
   transcript context to determine actual names. NEVER use generic labels like "Tucker's guest", "the guest",
   "the interviewer", "Speaker 1". If this is a Tucker Carlson interview with Elon Musk, the speakers are
   "Tucker Carlson" and "Elon Musk", not "Tucker Carlson" and "Tucker's guest".
   Assign roles: "host", "guest", "interviewer", "interviewee", "panelist", "commentator"

2. Break the transcript into 3-8 major TOPIC SEGMENTS. Each topic should be a distinct subject or theme discussed.
   Include precise start_sec and end_sec timestamps from the transcript.
   Summarize each topic in 1-2 sentences.
   For each topic, describe each speaker's position/stance on that topic.

3. Generate STANCE OPTIONS the user can choose from for their commentary.
   IMPORTANT: Analyze whether speakers AGREE or DISAGREE with each other.

   IF speakers are on OPPOSING sides (debate, contentious interview):
   - For EACH speaker, create TWO hardliner stances:
     "strongly_for_SPEAKERNAME" — Aggressively defending this speaker
     "strongly_against_SPEAKERNAME" — Aggressively criticizing this speaker
   - Include a "balanced" option

   IF speakers are on the SAME side (friendly interview, podcast, allies):
   - Create stances based on their SHARED POSITION vs opposing views:
     "strongly_support_both" — Champion both speakers' shared narrative aggressively
     "strongly_against_both" — Criticize and debunk their shared narrative
   - For EACH speaker individually, still create for/against:
     "strongly_for_SPEAKERNAME" — This speaker made the strongest points
     "strongly_against_SPEAKERNAME" — This speaker was wrong or weak
   - Also create TOPIC-BASED stances for the key issues discussed:
     "pro_TOPIC" — Aggressively support this position
     "anti_TOPIC" — Aggressively oppose this position
   - Include a "balanced" option

   Make descriptions vivid and opinionated — these are commentary stances, not academic positions.
   Example: "Expose every contradiction in X's argument" or "X absolutely destroyed Y in this interview"
   The user can select MULTIPLE stances, so make each one distinct and combinable.

4. Classify the video_type: "interview", "press_conference", "debate", "panel", or "monologue"

5. Estimate the ideal final commentary video duration in minutes (between 9-25 min).
   Use roughly 40% of the source video duration as a guideline.

Return ONLY valid JSON with this exact structure:
{{
    "speakers": [
        {{"name": "Speaker Name", "role": "host/guest/etc"}}
    ],
    "topics": [
        {{
            "topic_id": 0,
            "title": "Topic title",
            "start_sec": 0.0,
            "end_sec": 120.0,
            "summary": "Brief summary of this topic segment",
            "speaker_positions": {{
                "Speaker Name": "Their position on this topic"
            }}
        }}
    ],
    "stance_options": [
        {{"id": "strongly_for_speaker_0", "label": "Strongly FOR Speaker Name", "description": "Defend their position aggressively, highlight their wins"}},
        {{"id": "strongly_against_speaker_0", "label": "Strongly AGAINST Speaker Name", "description": "Criticize their arguments, expose contradictions"}},
        {{"id": "strongly_for_speaker_1", "label": "Strongly FOR Speaker 2", "description": "Champion their perspective"}},
        {{"id": "strongly_against_speaker_1", "label": "Strongly AGAINST Speaker 2", "description": "Dismantle their claims"}},
        {{"id": "balanced", "label": "Balanced analysis", "description": "Present both sides fairly"}}
    ],
    "video_type": "interview",
    "estimated_final_duration_minutes": 15
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print("[Analyzer] Analyzing transcript with Claude...")
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        # Extract JSON from response (handle markdown code blocks)
        text = _extract_json(text)
        result = json.loads(text)

        n_speakers = len(result.get("speakers", []))
        n_topics = len(result.get("topics", []))
        n_stances = len(result.get("stance_options", []))
        print(f"  Found {n_speakers} speakers, {n_topics} topics, {n_stances} stance options")
        print(f"  Video type: {result.get('video_type', 'unknown')}")

        return result

    except json.JSONDecodeError as e:
        print(f"  [Analyzer] JSON parse error: {e}")
        print(f"  Raw response: {text[:500]}")
        return _fallback_analysis(transcript_data)
    except Exception as e:
        print(f"  [Analyzer] Error: {e}")
        return _fallback_analysis(transcript_data)


def _build_timestamped_text(transcript: list, max_chars: int = 150000) -> str:
    """Build a readable timestamped transcript string."""
    lines = []
    total_chars = 0
    for entry in transcript:
        start = entry["start"]
        mins = int(start // 60)
        secs = int(start % 60)
        line = f"[{mins:02d}:{secs:02d}] {entry['text']}"
        total_chars += len(line)
        if total_chars > max_chars:
            lines.append("[... transcript truncated ...]")
            break
        lines.append(line)
    return "\n".join(lines)


def _extract_json(text: str) -> str:
    """Extract JSON from a response that may be wrapped in markdown code blocks."""
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines)
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end])
    # Try to find JSON object
    brace_start = text.find("{")
    if brace_start > 0:
        text = text[brace_start:]
    # Find matching closing brace
    depth = 0
    for i, c in enumerate(text):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[:i + 1]
    return text


def _fallback_analysis(transcript_data: dict) -> dict:
    """Minimal fallback if Claude analysis fails."""
    duration = transcript_data.get("duration_seconds", 600)
    return {
        "speakers": [{"name": "Speaker 1", "role": "unknown"}],
        "topics": [{
            "topic_id": 0,
            "title": transcript_data.get("title", "Full Video"),
            "start_sec": 0,
            "end_sec": duration,
            "summary": "Full video content",
            "speaker_positions": {},
        }],
        "stance_options": [
            {"id": "speaker_0", "label": "Side with Speaker 1", "description": "Agree with the main speaker"},
            {"id": "balanced", "label": "Balanced analysis", "description": "Present both sides fairly"},
        ],
        "video_type": "interview",
        "estimated_final_duration_minutes": min(25, max(9, int(duration / 60 * 0.4))),
    }

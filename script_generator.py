"""
script_generator.py

Uses Claude to generate a commentary script with:
- Hook voiceover (15-20s)
- Alternating real clips (1:30-2:00) and commentary (20-45s)
- Stance-aware commentary with supporting facts
"""

import json
from typing import Optional

import anthropic

from config import (
    ANTHROPIC_API_KEY,
    REAL_CLIP_MIN_SEC,
    REAL_CLIP_MAX_SEC,
    COMMENTARY_VO_MIN_SEC,
    COMMENTARY_VO_MAX_SEC,
    HOOK_MIN_SEC,
    HOOK_MAX_SEC,
    FINAL_VIDEO_MIN_MIN,
    FINAL_VIDEO_MAX_MIN,
)

TONE_PRESETS = {
    "neutral_news": {
        "label": "Neutral News (Philip DeFranco style)",
        "instruction": "Write in a neutral, news-anchor style. Present facts objectively, use phrases like 'here's what we know', 'let's break this down'. Be informative but engaging. Avoid taking strong sides — let the facts speak. Use a calm, measured tone with occasional dry humor."
    },
    "casual_conversational": {
        "label": "Casual Conversational (Joe Rogan style)",
        "instruction": "Write like you're having a casual conversation with a friend. Use natural language, occasional tangents, phrases like 'dude, think about this', 'that's wild', 'here's the thing though'. Be genuinely curious and open-minded. Mix in personal reactions and rhetorical questions."
    },
    "rapid_fire": {
        "label": "Rapid-Fire Debate (Ben Shapiro style)",
        "instruction": "Write in a fast-paced, logic-heavy debate style. Use rapid rhetorical questions, cite facts quickly, use phrases like 'let's look at the facts', 'here's the problem with that argument', 'and by the way'. Be assertive, direct, and intellectually aggressive. Build logical chains."
    },
    "drama_commentary": {
        "label": "Drama Commentary (Tea Channel style)",
        "instruction": "Write with high energy and drama. Use phrases like 'you won't believe what happened next', 'this is where it gets crazy', 'I need everyone to pay attention to this part'. Build suspense, use cliffhangers between segments. React with shock and emphasis. Keep viewers on edge."
    },
    "investigative": {
        "label": "Investigative Deep-Dive",
        "instruction": "Write like an investigative journalist uncovering a story. Use phrases like 'here's what they don't want you to know', 'when you dig deeper', 'follow the evidence'. Be methodical, connect dots between facts, build a compelling case. Maintain a serious, authoritative tone."
    },
    "comedic_roast": {
        "label": "Comedic Roast",
        "instruction": "Write with sharp wit and humor. Use clever analogies, sarcasm, and comedic timing. Make fun of absurd statements while still making substantive points. Use phrases like 'imagine thinking...', 'the audacity', 'I can't make this up'. Balance humor with actual analysis."
    },
}


def generate_script(
    transcript_data: dict,
    analysis: dict,
    stance_id: str,  # Can be single ID or comma-separated IDs
    facts: list = None,
    target_duration_minutes: int = None,
    selected_topic_ids: list = None,
    custom_stances: list = None,
    tone_preset: str = None,
) -> dict:
    """
    Generate a commentary script.

    Args:
        transcript_data: Full transcript data from transcript_downloader
        analysis: Analysis from transcript_analyzer
        stance_id: Chosen stance ID (e.g. "speaker_0", "balanced")
        facts: List of fact dicts from fact_searcher
        target_duration_minutes: Target video length (auto-calculated if None)

    Returns:
        {
            "title": str,
            "total_estimated_duration_sec": int,
            "segments": [
                {
                    "segment_id": int,
                    "type": "hook_voiceover" | "real_clip" | "commentary_voiceover",
                    "vo_text": str (for VO segments),
                    "clip_start_sec": float (for clip segments),
                    "clip_end_sec": float (for clip segments),
                    "clip_duration_sec": float (for clip segments),
                    "transcript_excerpt": str (for clip segments),
                    "estimated_duration_sec": int (for VO segments),
                    "supporting_facts": list (for commentary segments),
                    "notes": str,
                }
            ]
        }
    """
    # Find the chosen stance(s) — supports multiple comma-separated IDs
    stance_ids = [s.strip() for s in stance_id.split(",") if s.strip()]
    stance_labels = []
    stance_descs = []
    for sid in stance_ids:
        for opt in analysis.get("stance_options", []):
            if opt["id"] == sid:
                stance_labels.append(opt["label"])
                stance_descs.append(opt.get("description", ""))
                break
    if custom_stances:
        for cs in custom_stances:
            stance_labels.append(f"Custom: {cs}")
            stance_descs.append(cs)
    if not stance_labels:
        stance_labels = ["Balanced analysis"]
        stance_descs = ["Present both sides fairly"]
    stance_label = " + ".join(stance_labels)
    stance_desc = " | ".join(stance_descs)

    # Build custom stances instruction for the prompt
    custom_stances_text = ""
    if custom_stances:
        custom_stances_text = "\n\nUSER'S CUSTOM DIRECTIONS (IMPORTANT — follow these closely):\n"
        for i, cs in enumerate(custom_stances, 1):
            custom_stances_text += f"  {i}. {cs}\n"
        custom_stances_text += "\nThese are the user's own angles/perspectives. Integrate them throughout your commentary.\n"

    # Build tone instruction
    tone_instruction = ""
    if tone_preset and tone_preset in TONE_PRESETS:
        tone_instruction = f"\n\nCOMMENTARY TONE/STYLE (CRITICAL — follow this closely):\n{TONE_PRESETS[tone_preset]['instruction']}\n"

    # Auto-calculate target duration
    source_duration = transcript_data.get("duration_seconds", 600)
    if not target_duration_minutes:
        target_duration_minutes = min(
            FINAL_VIDEO_MAX_MIN,
            max(FINAL_VIDEO_MIN_MIN, int(source_duration / 60 * 0.4))
        )

    # Build context strings
    title = transcript_data.get("title", "")
    channel = transcript_data.get("channel", "")
    speakers_text = "\n".join(
        f"- {s['name']} ({s['role']})" for s in analysis.get("speakers", [])
    )
    # Filter topics if user selected specific ones
    all_topics = analysis.get("topics", [])
    if selected_topic_ids is not None:
        all_topics = [t for t in all_topics if t.get("topic_id") in selected_topic_ids]
    if not all_topics:
        all_topics = analysis.get("topics", [])

    topics_text = "\n".join(
        f"- [{t['start_sec']:.0f}s-{t['end_sec']:.0f}s] {t['title']}: {t['summary']}"
        for t in all_topics
    )
    transcript_text = _build_timestamped_text(transcript_data.get("transcript", []))

    # Format facts
    facts_text = ""
    if facts:
        facts_text = "\n\nSUPPORTING FACTS FROM NEWS — YOU MUST USE THESE IN YOUR COMMENTARY:\n"
        for i, f in enumerate(facts[:15]):
            facts_text += f"[FACT {i+1}] {f['title']}: {f['snippet'][:250]}\n"
        facts_text += "\nCRITICAL: Weave these facts DIRECTLY into vo_text. Do NOT just list them in supporting_facts.\n"
        facts_text += "Example: Instead of generic commentary, say 'According to [source], [specific fact]. This proves that...'\n"
        facts_text += "Each commentary segment should cite at least 1-2 specific facts from above IN the vo_text itself.\n"

    prompt = f"""You are a professional YouTube commentary scriptwriter. You create engaging commentary videos on interviews, press conferences, and podcasts.

ORIGINAL VIDEO: "{title}"
CHANNEL: {channel}
SOURCE DURATION: {source_duration // 60} minutes
VIDEO TYPE: {analysis.get("video_type", "interview")}

SPEAKERS:
{speakers_text}

USER'S CHOSEN STANCE: {stance_label}
STANCE DESCRIPTION: {stance_desc}
{custom_stances_text}{tone_instruction}
TOPIC SEGMENTS:
{topics_text}
{facts_text}

FULL TIMESTAMPED TRANSCRIPT:
{transcript_text}

YOUR TASK: Write a commentary video script.

STRUCTURE RULES:

1. HOOK (segment_id 0, type "hook_voiceover"):
   - {HOOK_MIN_SEC}-{HOOK_MAX_SEC} seconds of voiceover commentary (40-60 words)
   - Create instant curiosity or controversy
   - Reference the most shocking/interesting moment from the video
   - Pattern: "[Bold claim]. [Tease what's coming]. [Why viewer should care]."

2. REAL CLIPS (type "real_clip"):
   - Duration: {REAL_CLIP_MIN_SEC}-{REAL_CLIP_MAX_SEC} seconds each (0:25 to 1:00)
   - Choose duration INTELLIGENTLY based on the content:
     * Short clips (25-35s): single punchy statement, quick reaction, or one-liner
     * Medium clips (35-50s): a back-and-forth exchange or one complete argument
     * Long clips (50-60s): a complex point that needs full context to land
   - Each clip must be a COMPLETE thought — never cut mid-sentence or mid-argument
   - clip_start_sec and clip_end_sec MUST be exact timestamps from the transcript
   - Start at natural sentence beginnings, end at natural pauses
   - Include 6-12 real clips depending on source length
   - Clips should progress the narrative arc

3. COMMENTARY (type "commentary_voiceover"):
   - Duration: {COMMENTARY_VO_MIN_SEC}-{COMMENTARY_VO_MAX_SEC} seconds each (50-120 words)
   - Placed BETWEEN every real clip
   - Must reference what was just shown
   - MUST weave in SPECIFIC FACTS from the "SUPPORTING FACTS" section above
   - Do NOT write generic opinions — cite real data, stats, quotes, and news
   - Example: "What he's not telling you is that according to Reuters, [specific fact]. That completely undermines his argument because..."
   - Support the chosen stance(s) with:
     * Direct fact citations woven naturally into the commentary
     * Historical context with specific dates/events
     * Logical arguments backed by evidence
   - Tone: conversational, confident, slightly provocative but FACT-BASED
   - Every commentary must add value beyond the clip
   - Use ALL speakers' real full names, NEVER say "the guest" or "the host"

4. PATTERN: Hook VO → Clip 1 → Commentary 1 → Clip 2 → Commentary 2 → ... → Final Commentary

5. TARGET DURATION: {target_duration_minutes} minutes total
   - Real clips: ~50-60% of total duration
   - Commentary: ~40-50% of total duration

6. NARRATIVE ARC:
   - Build from context → controversy → evidence → conclusion
   - Each clip+commentary pair should escalate
   - Final commentary: strong closing statement

Return ONLY valid JSON:
{{
    "title": "Compelling video title supporting the chosen stance",
    "total_estimated_duration_sec": {target_duration_minutes * 60},
    "segments": [
        {{
            "segment_id": 0,
            "type": "hook_voiceover",
            "vo_text": "Hook text here...",
            "estimated_duration_sec": 18,
            "notes": "Why this hook works"
        }},
        {{
            "segment_id": 1,
            "type": "real_clip",
            "clip_start_sec": 120.5,
            "clip_end_sec": 230.8,
            "clip_duration_sec": 110.3,
            "transcript_excerpt": "First 50 words of what's said in this clip...",
            "notes": "Why this clip matters"
        }},
        {{
            "segment_id": 2,
            "type": "commentary_voiceover",
            "vo_text": "Commentary reacting to the clip...",
            "estimated_duration_sec": 35,
            "supporting_facts": ["Fact 1", "Fact 2"],
            "notes": "What this commentary adds"
        }}
    ]
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print(f"[ScriptGen] Generating script (stance: {stance_label}, target: {target_duration_minutes} min)...")
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        text = _extract_json(text)
        result = json.loads(text)

        n_segments = len(result.get("segments", []))
        n_clips = sum(1 for s in result.get("segments", []) if s["type"] == "real_clip")
        n_commentary = sum(1 for s in result.get("segments", []) if s["type"] == "commentary_voiceover")
        print(f"  Generated: {n_segments} segments ({n_clips} clips, {n_commentary} commentary)")
        print(f"  Title: {result.get('title', '')}")

        # Post-process: snap clip timestamps to sentence boundaries
        transcript = transcript_data.get("transcript", [])
        if transcript:
            import re
            # Build sentence boundary list: (sentence_end_sec, next_sentence_start_sec)
            sentence_bounds = []
            for i, entry in enumerate(transcript):
                text = entry.get("text", "").strip()
                if text and re.search(r'[.!?]["\']?\s*$', text):
                    entry_end = entry["start"] + entry.get("duration", 0)
                    next_start = transcript[i + 1]["start"] if i + 1 < len(transcript) else entry_end
                    sentence_bounds.append((entry_end, next_start))

            if sentence_bounds:
                for seg in result.get("segments", []):
                    if seg.get("type") != "real_clip":
                        continue
                    orig_start = seg["clip_start_sec"]
                    orig_end = seg["clip_end_sec"]

                    # Snap start: latest sentence boundary start <= orig_start
                    snapped_start = orig_start
                    for end_ts, next_ts in sentence_bounds:
                        if next_ts <= orig_start:
                            snapped_start = next_ts
                        else:
                            break

                    # Snap end: earliest sentence boundary end >= orig_end
                    snapped_end = orig_end
                    for end_ts, next_ts in sentence_bounds:
                        if end_ts >= orig_end:
                            snapped_end = end_ts
                            break

                    # Guard duration: allow 10s grace over max, 5s under min
                    duration = snapped_end - snapped_start
                    if duration > REAL_CLIP_MAX_SEC + 10:
                        # Contract: use last sentence boundary before orig_end
                        for end_ts, next_ts in reversed(sentence_bounds):
                            if end_ts <= orig_end:
                                snapped_end = end_ts
                                break
                    elif duration < REAL_CLIP_MIN_SEC - 5:
                        # Expand: use next sentence boundary after orig_end
                        for end_ts, next_ts in sentence_bounds:
                            if end_ts > orig_end:
                                snapped_end = end_ts
                                break

                    seg["clip_start_sec"] = round(snapped_start, 2)
                    seg["clip_end_sec"] = round(snapped_end, 2)
                    seg["clip_duration_sec"] = round(snapped_end - snapped_start, 2)

        # Post-process: fix transcript_excerpt to match actual timestamps (uses snapped timestamps)
        if transcript:
            for seg in result.get("segments", []):
                if seg.get("type") == "real_clip":
                    start = seg.get("clip_start_sec", 0)
                    end = seg.get("clip_end_sec", 0)
                    clip_texts = []
                    for entry in transcript:
                        entry_start = entry.get("start", 0)
                        entry_end = entry_start + entry.get("duration", 0)
                        if entry_end > start and entry_start < end:
                            clip_texts.append(entry["text"])
                    if clip_texts:
                        seg["transcript_excerpt"] = " ".join(clip_texts)

        return result

    except json.JSONDecodeError as e:
        print(f"  [ScriptGen] JSON parse error: {e}")
        return {"error": str(e), "segments": []}
    except Exception as e:
        print(f"  [ScriptGen] Error: {e}")
        return {"error": str(e), "segments": []}


def _build_timestamped_text(transcript: list, max_chars: int = 150000) -> str:
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
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines)
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end])
    brace_start = text.find("{")
    if brace_start > 0:
        text = text[brace_start:]
    depth = 0
    for i, c in enumerate(text):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[:i + 1]
    return text


def regenerate_single_segment(
    transcript_data: dict,
    analysis: dict,
    script: dict,
    segment: dict,
    facts: list = None,
    instructions: str = None,
) -> dict:
    """Regenerate a single VO segment with optional user instructions."""

    title = transcript_data.get("title", "")
    seg_type = segment["type"]
    seg_id = segment["segment_id"]
    current_text = segment.get("vo_text", "")

    # Find surrounding context
    segments = script.get("segments", [])
    prev_clip = None
    next_clip = None
    for s in segments:
        if s["type"] == "real_clip" and s["segment_id"] < seg_id:
            prev_clip = s
        if s["type"] == "real_clip" and s["segment_id"] > seg_id and not next_clip:
            next_clip = s

    context = f"VIDEO: \"{title}\"\n"
    if prev_clip:
        context += f"PREVIOUS CLIP ({prev_clip.get('clip_start_sec',0):.0f}s-{prev_clip.get('clip_end_sec',0):.0f}s): {prev_clip.get('transcript_excerpt', '')}\n"
    if next_clip:
        context += f"NEXT CLIP ({next_clip.get('clip_start_sec',0):.0f}s-{next_clip.get('clip_end_sec',0):.0f}s): {next_clip.get('transcript_excerpt', '')}\n"

    facts_text = ""
    if facts:
        facts_text = "\nAVAILABLE FACTS:\n"
        for i, f in enumerate(facts[:10]):
            facts_text += f"[{i+1}] {f['title']}: {f['snippet'][:200]}\n"

    user_instruction = ""
    if instructions:
        user_instruction = f"\n\nUSER'S SPECIFIC INSTRUCTIONS: {instructions}\nFollow these instructions closely when rewriting."

    prompt = f"""You are rewriting a single {seg_type.replace('_', ' ')} segment for a YouTube commentary video.

{context}
{facts_text}

CURRENT TEXT (rewrite this):
"{current_text}"
{user_instruction}

RULES:
- Keep the same approximate duration ({segment.get('estimated_duration_sec', 30)} seconds, {len(current_text.split()) if current_text else 50}-{len(current_text.split())+20 if current_text else 70} words)
- Write fresh, different text — don't just rephrase the same sentences
- Weave in specific facts from the AVAILABLE FACTS section
- Use speakers' real names, never "the guest" or "the host"
- Be conversational and engaging

Return ONLY valid JSON:
{{
    "segment_id": {seg_id},
    "type": "{seg_type}",
    "vo_text": "Your rewritten text here...",
    "estimated_duration_sec": {segment.get('estimated_duration_sec', 30)},
    "supporting_facts": ["fact1", "fact2"],
    "notes": "What changed in this version"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = _extract_json(text)
        result = json.loads(text)
        print(f"  [ScriptGen] Regenerated segment {seg_id}")
        return result
    except Exception as e:
        print(f"  [ScriptGen] Regen error: {e}")
        return {"error": str(e)}


def generate_hook_variants(
    transcript_data: dict,
    analysis: dict,
    stance_id: str,
    facts: list = None,
) -> list:
    """Generate 3 different hook options for the user to choose from."""

    title = transcript_data.get("title", "")
    channel = transcript_data.get("channel", "")

    speakers_text = "\n".join(
        f"- {s['name']} ({s['role']})" for s in analysis.get("speakers", [])
    )
    topics_text = "\n".join(
        f"- {t['title']}: {t['summary']}" for t in analysis.get("topics", [])[:5]
    )

    # Get stance label
    stance_label = stance_id
    for opt in analysis.get("stance_options", []):
        if opt["id"] == stance_id:
            stance_label = opt["label"]
            break

    facts_text = ""
    if facts:
        facts_text = "\nKEY FACTS:\n"
        for i, f in enumerate(facts[:5]):
            facts_text += f"- {f['title']}: {f['snippet'][:150]}\n"

    prompt = f"""Generate 3 VERY DIFFERENT hook options for a YouTube commentary video.

VIDEO: "{title}"
CHANNEL: {channel}
SPEAKERS: {speakers_text}
KEY TOPICS: {topics_text}
STANCE: {stance_label}
{facts_text}

Each hook should be 15-20 seconds (40-60 words) and use a DIFFERENT approach:

Hook 1: CONTROVERSY — Lead with the most shocking/controversial moment
Hook 2: CURIOSITY — Ask a compelling question that makes viewers need to watch
Hook 3: BOLD CLAIM — Start with a strong, opinionated statement

Return ONLY valid JSON:
{{
    "hooks": [
        {{
            "id": 1,
            "style": "controversy",
            "vo_text": "Hook text here...",
            "estimated_duration_sec": 18
        }},
        {{
            "id": 2,
            "style": "curiosity",
            "vo_text": "Hook text here...",
            "estimated_duration_sec": 18
        }},
        {{
            "id": 3,
            "style": "bold_claim",
            "vo_text": "Hook text here...",
            "estimated_duration_sec": 18
        }}
    ]
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = _extract_json(text)
        result = json.loads(text)
        return result.get("hooks", [])
    except Exception as e:
        print(f"  [ScriptGen] Hook variants error: {e}")
        return []

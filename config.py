import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PO_TOKEN = os.getenv("PO_TOKEN", "")
VISITOR_DATA = os.getenv("VISITOR_DATA", "")

# TTS config (ai33.pro API)
AI33_API_KEY = os.getenv("AI33_API_KEY", "")

# HeyGen Avatar III config
HEYGEN_API_KEY = os.getenv("HEYGEN_API_KEY", "")

# Clip duration limits (seconds)
MAX_CLIP_DURATION = 75           # 1:15 max per clip
REAL_CLIP_MIN_SEC = 25           # 0:25 minimum real clip
REAL_CLIP_MAX_SEC = 60           # 1:00 maximum real clip
COMMENTARY_VO_MIN_SEC = 15       # minimum commentary duration
COMMENTARY_VO_MAX_SEC = 45       # maximum commentary duration
HOOK_MIN_SEC = 15
HOOK_MAX_SEC = 20
FINAL_VIDEO_MIN_MIN = 9          # 9 minutes minimum final video
FINAL_VIDEO_MAX_MIN = 25         # 25 minutes maximum final video

# Output paths (absolute, relative to this file's directory)
_BASE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_BASE, "output")
CLIPS_DIR = os.path.join(_BASE, "output", "clips")
VOICEOVER_DIR = os.path.join(_BASE, "output", "voiceovers")
NORMALIZED_DIR = os.path.join(_BASE, "output", "normalized")


# Per-session directory helpers
def get_session_dirs(session_id: str) -> dict:
    """Return session-namespaced output directories."""
    session_dir = os.path.join(OUTPUT_DIR, session_id)
    return {
        "session_dir": session_dir,
        "clips_dir": os.path.join(session_dir, "clips"),
        "voiceover_dir": os.path.join(session_dir, "voiceovers"),
        "normalized_dir": os.path.join(session_dir, "normalized"),
        "heygen_clips_dir": os.path.join(session_dir, "heygen_clips"),
    }


def ensure_session_dirs(session_id: str) -> dict:
    """Create session directories and return paths dict."""
    dirs = get_session_dirs(session_id)
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs

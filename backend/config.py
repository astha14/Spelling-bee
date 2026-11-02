"""Read credentials on the server only."""
import os
from dotenv import load_dotenv
load_dotenv()
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
CARTESIA_STT_MODEL = os.getenv("CARTESIA_STT_MODEL", "ink-whisper")
CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

# Timing settings are seconds. These defaults favor pauses over fast grading.
from dataclasses import dataclass

@dataclass(frozen=True)
class CompletionSettings:
    vad_confidence: float = 0.7
    vad_start: float = 0.08
    vad_stop: float = 0.2
    smart_enabled: bool = True
    smart_cpu_count: int = 1
    smart_audio_seconds: float = 8.0
    minimum_silence: float = 1.0
    # Silence only starts a confirmation prompt; it never grades by itself.
    completion_timeout: float = 5.0
    maximum_timeout: float = 5.0
    stt_final_wait: float = 2.5
    pause_margin: float = 0.6
    adaptive_maximum: float = 4.0
    debug: bool = False

    def __post_init__(self):
        import math
        values = (self.vad_start, self.vad_stop, self.smart_audio_seconds,
                  self.minimum_silence, self.completion_timeout, self.maximum_timeout,
                  self.stt_final_wait, self.pause_margin, self.adaptive_maximum)
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("Spelling timing settings must be positive finite numbers.")
        if not 0 < self.vad_confidence <= 1 or self.smart_cpu_count < 1:
            raise ValueError("Invalid VAD confidence or Smart Turn CPU count.")
        if not self.minimum_silence <= self.completion_timeout <= self.maximum_timeout:
            raise ValueError("Require minimum silence <= completion timeout <= maximum timeout.")

COMPLETION = CompletionSettings(
    vad_confidence=float(os.getenv("VAD_CONFIDENCE", "0.7")),
    vad_start=float(os.getenv("VAD_START_SECS", "0.08")),
    vad_stop=float(os.getenv("VAD_STOP_SECS", "0.2")),
    smart_enabled=os.getenv("SMART_TURN_ENABLED", "true").lower() == "true",
    smart_cpu_count=int(os.getenv("SMART_TURN_CPU_COUNT", "1")),
    smart_audio_seconds=float(os.getenv("SMART_TURN_AUDIO_SECS", "8")),
    minimum_silence=float(os.getenv("SPELLING_MIN_SILENCE_SECS", "1")),
    completion_timeout=float(os.getenv("SPELLING_COMPLETION_SECS", "5.0")),
    maximum_timeout=float(os.getenv("SPELLING_MAX_COMPLETION_SECS", "5.0")),
    stt_final_wait=float(os.getenv("STT_FINAL_WAIT_SECS", "2.5")),
    pause_margin=float(os.getenv("SPELLING_PAUSE_MARGIN_SECS", "0.6")),
    adaptive_maximum=float(os.getenv("SPELLING_ADAPTIVE_MAX_SECS", "4")),
    debug=os.getenv("SPELLING_DEBUG", "false").lower() == "true",
)

"""One cancellable silence timer per attempt; no STT, LLM, or grading here.

All mutations happen on the asyncio event loop. The owner must recheck `due`
and call `claim` while holding the same lock used to process speech events.
Expected word is metadata only: neither its length nor spelling affects timing.
"""
import asyncio
import logging
import time
from enum import StrEnum
from uuid import uuid4
from backend.config import CompletionSettings

log = logging.getLogger(__name__)


class CompletionState(StrEnum):
    WAITING_FOR_WORD = "WAITING_FOR_WORD"
    LISTENING = "LISTENING"
    POSSIBLY_COMPLETE = "POSSIBLY_COMPLETE"
    VALIDATING = "VALIDATING"
    FEEDBACK = "FEEDBACK"


class SpellingCompletion:
    def __init__(self, on_due, settings=None, clock=time.monotonic):
        self.settings = settings or CompletionSettings()
        self.clock = clock
        self.on_due = on_due
        self.timer = None
        self.attempt_id = ""
        self.generation = 0
        # Keep the player's observed pace across words, not across audio sessions.
        self.longest_pause = 0.0
        self.letters = ""
        self.state = CompletionState.WAITING_FOR_WORD
        self.speaking = False
        self.heard_speech = False
        self.last_speech = None
        self.listening_since = None
        self.pending_final = False
        self.smart_complete = False
        self.submitted = False
        self.blocked = False
        self.unclear_segment = False
        self.clarification_requested = False

    def debug(self, event, **fields):
        if self.settings.debug:
            # Log player letters only; never log the target word or TTS text.
            log.info("t=%.6f [%s] attempt=%s %s", self.clock(), event, self.attempt_id[:8], fields)

    @property
    def token(self):
        return self.attempt_id, self.generation

    @property
    def active(self):
        return self.state in {CompletionState.LISTENING, CompletionState.POSSIBLY_COMPLETE}

    def cancel_timer(self):
        task, self.timer = self.timer, None
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
            self.debug("TIMER cancelled")

    def begin(self, _expected_word=None):
        self.pause()
        self.attempt_id = uuid4().hex
        self.letters = ""
        self.last_speech = None
        self.submitted = self.blocked = False
        self.unclear_segment = False
        self.clarification_requested = False

    def pause(self):
        self.cancel_timer()
        self.generation += 1
        self.state = CompletionState.WAITING_FOR_WORD
        self.speaking = self.heard_speech = self.pending_final = False
        self.smart_complete = False
        self.listening_since = None

    def listen(self):
        if not self.submitted:
            self.state = CompletionState.LISTENING
            self.listening_since = self.clock()
            if self.letters and self.last_speech is None:
                self.last_speech = self.listening_since
            # Retained/corrected letters can complete after a command response.
            # Fresh VAD is still required to accept additional STT text.
            self.schedule()

    def speech_started(self):
        if not self.active or self.submitted:
            return
        if self.heard_speech and not self.speaking and self.last_speech is not None:
            gap = self.clock() - self.last_speech
            self.longest_pause = max(self.longest_pause, gap)
        self.cancel_timer()
        self.generation += 1
        self.speaking = self.heard_speech = self.pending_final = True
        self.smart_complete = False
        self.last_speech = self.clock()
        self.state = CompletionState.LISTENING
        self.debug("VAD started")

    def speech_stopped(self):
        if not self.active or not self.speaking:
            return  # Duplicate stops must not restart the silence clock.
        self.speaking = False
        # VAD reports stop after vad_stop seconds of silence have already elapsed.
        self.last_speech = max(self.last_speech, self.clock() - self.settings.vad_stop)
        self.debug("VAD stopped", last_speech=self.last_speech)
        self.schedule()

    def interim(self):
        if self.active and self.heard_speech and not self.pending_final:
            self.pending_final = True
            self.schedule()

    def final(self, letters):
        if not self.active or not self.heard_speech:
            return
        self.pending_final = False
        self.letters = letters
        self.debug("STT letters updated", letters=letters)
        self.schedule()

    def smart_result(self, token, complete):
        if token != self.token or not self.active or self.speaking:
            return
        self.smart_complete = complete
        self.debug("SMART_TURN prediction", complete=complete)
        self.schedule()

    def deadline(self):
        if (not self.active or self.speaking or self.submitted or self.blocked
                or self.last_speech is None):
            return None
        if not self.letters and not self.pending_final and not self.unclear_segment:
            return None
        delay = (self.settings.completion_timeout if self.smart_complete
                 else self.settings.maximum_timeout)
        # Slower observed spelling extends the window; fast spelling avoids the
        # old unconditional four-second fallback. Never use the expected answer.
        pace_delay = min(self.settings.adaptive_maximum,
                         self.longest_pause + self.settings.pause_margin) if self.longest_pause else 0
        delay = max(self.settings.minimum_silence, delay, pace_delay)
        if self.pending_final:
            delay += self.settings.stt_final_wait
        # Host playback is not an opportunity for the player to continue.
        return max(self.last_speech, self.listening_since or self.last_speech) + delay

    def due(self, token):
        deadline = self.deadline()
        if token != self.token or deadline is None or self.clock() < deadline:
            return None
        if self.pending_final:
            return "recognition_timeout"
        if self.unclear_segment:
            return "clarify"
        # This means the silence window elapsed. The game processor turns it
        # into a confirmation prompt; it does not grade or advance a round.
        return "submit" if self.letters else None

    def claim(self, token):
        if self.due(token) != "submit":
            return False
        self.submitted = True
        self.state = CompletionState.VALIDATING
        self.cancel_timer()
        self.debug("SUBMIT", letters=self.letters)
        return True

    def schedule(self):
        self.cancel_timer()
        deadline = self.deadline()
        if deadline is None:
            return
        self.state = CompletionState.POSSIBLY_COMPLETE
        token = self.token
        self.debug("TIMER started", seconds=max(0, deadline - self.clock()))

        async def wait():
            try:
                await asyncio.sleep(max(0, deadline - self.clock()))
                self.debug("TIMER timeout reached")
                await self.on_due(token)
            except asyncio.CancelledError:
                pass

        self.timer = asyncio.create_task(wait(), name="spelling-completion")

    async def close(self):
        task = self.timer
        self.pause()
        if task and task is not asyncio.current_task():
            await asyncio.gather(task, return_exceptions=True)

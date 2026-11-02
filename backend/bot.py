"""Pipecat audio adapter. Final STT segments accumulate until conservative automatic completion."""
import asyncio
import time
import re
from collections import deque
from pipecat.frames.frames import (TranscriptionFrame, TTSSpeakFrame, Frame,
    BotStartedSpeakingFrame, BotStoppedSpeakingFrame, ErrorFrame,
    VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame, InterimTranscriptionFrame)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker, PipelineParams
from pipecat.workers.runner import WorkerRunner
from backend.stt import CartesiaSTTService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from backend import config
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from backend.completion import SpellingCompletion, CompletionState
from backend.smart_turn import SmartTurnSignals
from backend.host import Host, Phase
from backend.spelling_parser import parse_spelling
from backend.latency import TTSLatencyProbe, InputAudioProbe
from backend.conversation import local_intent, conversational_candidate, interpret

class GameProcessor(FrameProcessor):
    def __init__(self, connection, host, settings=None):
        super().__init__()
        self.connection, self.host = connection, host
        self.lock = asyncio.Lock()
        self.last_input = time.monotonic()
        self.speaking = False
        self.user_speaking = False
        self.overlapping_speech = False
        self.heard_user = False
        self.completion = SpellingCompletion(self.completion_due, settings or config.COMPLETION)
        self.smart = None
        self.word_key = None
        self.playback_epoch = 0
        self.seen_final_ids = set()
        self.final_id_order = deque()
        self.feedback_trace = None
        self.conversation_task = None
        self.ambiguous_choice = False
        self.unclear_position = None

    @property
    def transcript_token(self):
        # Pauses invalidate timers, not final transcripts within the same attempt.
        return self.completion.attempt_id, self.playback_epoch

    def publish(self, **extra):
        self.connection.send_app_message({"type": "state", **self.host.state(),
            **({"interaction": "CONVERSATION"} if self.conversation_task else {}), **extra})

    def sync_attempt(self, reset=False):
        key = (id(self.host.game), self.host.game.index)
        if self.host.phase == Phase.SPELLING and not self.host.paused:
            if key != self.word_key or reset:
                self.completion.begin()
                self.word_key = key
                if self.smart:
                    self.smart.reset_audio()
            self.completion.letters = self.host.letters
        else:
            self.completion.pause()

    def prepare_speech(self):
        # Close the collection gate before requesting TTS, not only when audio starts.
        self.speaking = True
        self.playback_epoch += 1
        self.completion.pause()
        if self.smart:
            self.smart.reset_audio()

    async def deliver(self, speech):
        if not speech:
            return
        self.prepare_speech()
        self.trace_feedback("TTS requested")
        await self.push_frame(TTSSpeakFrame(speech))

    def trace_feedback(self, event):
        if self.feedback_trace is not None:
            attempt, last_speech, submitted = self.feedback_trace
            now = self.completion.clock()
            self.completion.debug(event, feedback_attempt=attempt[:8],
                since_speech_ms=round((now - last_speech) * 1000, 1),
                since_submission_ms=round((now - submitted) * 1000, 1))
        else:
            self.completion.debug(event)

    def duplicate_final(self, frame):
        # Identity, not text: two separate P finals in APPLE must both survive.
        if frame.id in self.seen_final_ids:
            return True
        self.seen_final_ids.add(frame.id)
        self.final_id_order.append(frame.id)
        if len(self.final_id_order) > 512:
            self.seen_final_ids.remove(self.final_id_order.popleft())
        return False

    def cancel_conversation(self):
        if self.conversation_task:
            self.conversation_task.cancel()
            self.conversation_task = None
            if not self.host.paused:
                self.completion.listen()

    def start_conversation(self, text):
        self.cancel_conversation()
        self.completion.pause()
        self.completion.last_speech = None
        token = self.transcript_token
        self.publish(notice="Thinking about your question…")

        async def answer():
            intent, reply = await interpret(text, self.host.name,
                (self.host.game.current.text if not self.host.game.finished else ""), self.completion.debug)
            # A final STT segment can arrive before the VAD stop event.
            while self.user_speaking:
                await asyncio.sleep(.05)
            async with self.lock:
                if self.conversation_task is not asyncio.current_task() or token != self.transcript_token:
                    return
                self.conversation_task = None
                if intent in {'repeat', 'hint', 'sentence', 'score'}:
                    speech = self.host.handle(action=intent)
                else:
                    speech = self.host.chat(intent, reply)
                self.sync_attempt()
                self.publish()
                await self.deliver(speech)

        self.conversation_task = asyncio.create_task(answer(), name="host-conversation")

    async def respond(self, text="", action=None, attempt_token=None):
        async with self.lock:
            if attempt_token is not None and attempt_token != self.transcript_token:
                return  # A queued transcript must not mutate a newer attempt.
            self.last_input = time.monotonic()
            # Punctuation-only STT chunks carry no letters and are not a failed
            # spelling segment. Do not clear pending recognition on this noise.
            if not action and text.strip() and re.fullmatch(r"[\s.,!?;:…-]+", text):
                return
            parsed = parse_spelling(text)
            letters_before = self.host.letters
            routed = action or parsed.command or (local_intent(text) if not parsed.letters else None)
            if routed:
                self.cancel_conversation()
            confirming = self.host.phase == Phase.CONFIRMING_ANSWER and routed == "confirm"
            previous_result_count = len(self.host.game.results)
            if confirming:
                submitted_at = self.completion.clock()
                self.feedback_trace = (self.completion.attempt_id,
                    self.completion.last_speech or submitted_at, submitted_at)
            if (self.host.phase != Phase.IDLE and not routed and not parsed.letters
                    and conversational_candidate(text)):
                self.start_conversation(text)
                return
            if routed in {'pause', 'resume', 'rules', 'nervous', 'joke', 'encouragement'}:
                self.completion.last_speech = None  # A chat reply does not finish saved letters.
            if (self.host.phase == Phase.SPELLING and not routed and not self.host.paused
                    and parsed.uncertain and not parsed.letters):
                # Do not start TTS halfway through a spelling because one segment
                # is unclear. Keep listening, then request a retry after silence.
                self.sync_attempt()
                self.ambiguous_choice = bool(re.fullmatch(
                    r"(?:the letter )?[a-z] or [a-z]", text.strip().lower()))
                self.unclear_position = len(self.host.letters)
                self.completion.unclear_segment = True
                self.completion.final(self.host.letters)
                self.completion.debug("STT unclear segment; waiting for silence")
                return
            speech = self.host.handle(text, routed)
            if confirming and len(self.host.game.results) > previous_result_count:
                result = self.host.game.results[-1]
                self.completion.debug("VALIDATION completed", correct=result["correct"],
                                      answer=result["answer"])
            self.sync_attempt(reset=(action or parsed.command) == "clear")
            if self.host.phase == Phase.SPELLING:
                if not routed and parsed.uncertain and not parsed.letters:
                    self.completion.blocked = True
                elif ((parsed.letters or parsed.corrections)
                      and self.completion.clarification_requested):
                    # Insert the repeated unclear segment where it was heard,
                    # ahead of any later letters already collected.
                    if parsed.letters and self.unclear_position is not None:
                        base = self.host.letters[:-len(parsed.letters)]
                        prefix = base[:self.unclear_position]
                        suffix = base[self.unclear_position:]
                        self.host.letters = prefix + parsed.letters + suffix
                    self.unclear_position = None
                    self.completion.blocked = False
                    self.completion.unclear_segment = False
                    self.completion.clarification_requested = False
                self.completion.final(self.host.letters)
            self.completion.debug("GAME state transition", phase=self.host.phase.value,
                                  round=self.host.game.index + 1, score=self.host.game.score)
            self.publish()
            await self.deliver(speech)

    async def smart_prediction(self, token, complete):
        async with self.lock:
            self.completion.smart_result(token, complete)

    async def completion_due(self, token):
        async with self.lock:
            outcome = self.completion.due(token)
            self.completion.debug("ANSWER completion decision", outcome=outcome,
                                  letters=self.host.letters)
            if outcome == "clarify":
                self.completion.blocked = True
                self.completion.pause()
                ambiguous = self.ambiguous_choice
                speech = ("I heard two possible letters. Was that B or D?" if ambiguous
                          else "I missed part of that spelling. Could you repeat just that letter? Your earlier letters are saved.")
                self.ambiguous_choice = False
                self.completion.clarification_requested = True
                self.completion.debug("CLARIFICATION requested", alternatives=ambiguous)
                await self.deliver(speech)
                return
            if outcome == "recognition_timeout":
                self.completion.blocked = True
                self.completion.pause()
                self.publish(notice="Recognition is incomplete. Please retry your spelling.")
                await self.deliver("I didn't receive all the final letters. Please say let me try again and spell once more.")
                return
            if outcome != "submit":
                return
            if self.host.phase != Phase.SPELLING or not self.completion.claim(token):
                return
            self.feedback_trace = (self.completion.attempt_id,
                                   self.completion.last_speech,
                                   self.completion.clock())
            speech = self.host.complete_automatically()
            self.trace_feedback("VALIDATION finished")
            self.completion.state = CompletionState.FEEDBACK
            self.completion.debug("VALIDATION completed", correct=self.host.game.results[-1]["correct"])
            self.sync_attempt()
            self.publish()
            await self.deliver(speech)

    async def cleanup(self):
        task = self.conversation_task
        self.cancel_conversation()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        await self.completion.close()
        await super().cleanup()

    async def accept_transcript(self, text):
        """During host audio, only explicit commands with VAD evidence may interrupt.

        Ordinary transcripts during playback are ignored to avoid grading echo.
        Browser acoustic echo cancellation remains necessary for full duplex audio.
        """
        if self.speaking or self.overlapping_speech:
            command = parse_spelling(text).command
            if not self.heard_user or command not in {"repeat", "hint", "sentence", "score", "clear", "undo", "end", "pause", "resume", "rules"}:
                self.completion.debug("STT ignored during host/overlapping speech")
                return
            await self.broadcast_interruption()
            self.speaking = False
            self.overlapping_speech = False
        # Cartesia final frames have no attempt ID. A fresh VAD speech start is
        # required after playback before spelling can enter the next attempt.
        parsed = parse_spelling(text)
        if (self.host.phase == Phase.SPELLING and not parsed.command
                and (not self.completion.active or not self.completion.heard_speech)):
            self.completion.debug("STT ignored before fresh VAD speech")
            return
        if self.host.phase == Phase.SPELLING:
            self.completion.debug("STT final received", transcript=text)
        token = self.transcript_token if self.host.phase == Phase.SPELLING else None
        await self.respond(text, attempt_token=token)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStartedSpeakingFrame):
            async with self.lock:
                self.cancel_conversation()
                self.user_speaking = True
                self.completion.blocked = False
                self.heard_user = True
                self.overlapping_speech = self.speaking
                self.last_input = time.monotonic()
                if not self.speaking:
                    self.completion.speech_started()
                self.publish(user_speaking=True)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            async with self.lock:
                self.user_speaking = False
                self.completion.speech_stopped()
                if self.smart and self.completion.active:
                    self.smart.predict(self.completion.token)
                self.publish(user_speaking=False)
        elif isinstance(frame, BotStartedSpeakingFrame):
            async with self.lock:
                self.trace_feedback("TRANSPORT audio started (not browser audibility)")
                self.feedback_trace = None
                self.prepare_speech()
                self.heard_user = self.user_speaking
                self.publish(speaking=True)
        elif isinstance(frame, BotStoppedSpeakingFrame):
            async with self.lock:
                self.speaking = False
                self.last_input = time.monotonic()
                if self.host.phase == Phase.SPELLING and not self.host.paused:
                    self.sync_attempt()
                    self.completion.listen()
                self.publish(speaking=False)
        elif isinstance(frame, ErrorFrame):
            self.completion.pause()
            self.publish(error="Voice service error. Check backend logs and API settings; reconnect to retry.")
        if isinstance(frame, InterimTranscriptionFrame):
            self.completion.debug("STT interim transcript", transcript=frame.text)
            async with self.lock:
                if not self.speaking:
                    self.completion.interim()
            return  # Revised partials never append letters.
        if isinstance(frame, TranscriptionFrame):
            self.completion.debug("STT final transcript", transcript=frame.text,
                                  confidence=(frame.result or {}).get("confidence"))
            if self.duplicate_final(frame):
                self.completion.debug("STT duplicate frame ignored")
                return
            if frame.text.strip():
                await self.accept_transcript(frame.text)
            return
        await self.push_frame(frame, direction)

async def run_bot(connection, difficulty):
    transport = SmallWebRTCTransport(connection, TransportParams(audio_in_enabled=True, audio_out_enabled=True))
    processor = GameProcessor(connection, Host(difficulty))
    settings = config.COMPLETION
    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(
        confidence=settings.vad_confidence, start_secs=settings.vad_start,
        stop_secs=settings.vad_stop)))
    analyzer = None
    if settings.smart_enabled:
        # Loading the bundled model also stays off the audio/event-loop thread.
        analyzer = await asyncio.to_thread(
            LocalSmartTurnAnalyzerV3, cpu_count=settings.smart_cpu_count,
            params=SmartTurnParams(max_duration_secs=settings.smart_audio_seconds))
    smart = SmartTurnSignals(analyzer, processor.completion, processor.smart_prediction)
    processor.smart = smart
    stt = CartesiaSTTService(api_key=config.CARTESIA_API_KEY, report=processor.completion.debug)
    tts = CartesiaTTSService(api_key=config.CARTESIA_API_KEY,
        settings=CartesiaTTSService.Settings(voice=config.CARTESIA_VOICE_ID))
    worker = PipelineWorker(Pipeline([transport.input(), InputAudioProbe(processor.completion), vad, smart, stt, processor, tts, TTSLatencyProbe(processor.trace_feedback), transport.output()]),
                            params=PipelineParams(), idle_timeout_secs=300, enable_rtvi=False)
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    @worker.event_handler("on_pipeline_error")
    async def pipeline_error(worker, frame):
        processor.publish(error="Speech service failed. Check API credentials, credits, and server logs; then reconnect.")

    @worker.event_handler("on_idle_timeout")
    async def idle_timeout(worker):
        processor.publish(error="Session closed after five minutes without activity. Press Start Game to reconnect.")

    @transport.event_handler("on_client_connected")
    async def connected(transport, client):
        welcome = processor.host.begin()
        processor.prepare_speech()
        processor.publish()
        await worker.queue_frames([TTSSpeakFrame(welcome)])

    @transport.event_handler("on_app_message")
    async def message(transport, message, sender):
        if not isinstance(message, dict):
            return
        action = message.get("action")
        if action in {"repeat", "hint", "submit", "confirm", "clear", "undo", "end"}:
            await processor.respond(action=action)
        elif action == "name" and processor.host.phase == "WELCOME":
            await processor.respond(str(message.get("text", ""))[:40])

    @transport.event_handler("on_client_disconnected")
    async def disconnected(transport, client):
        await runner.cancel()

    async def silence_watch():
        while True:
            await asyncio.sleep(5)
            if not processor.speaking and not processor.user_speaking and time.monotonic() - processor.last_input > 30:
                processor.publish(notice="Spell at your own pace. I will check your answer after a pause. Say play again after a game ends.")
                processor.last_input = time.monotonic()

    watcher = asyncio.create_task(silence_watch())
    try:
        await runner.run()
    finally:
        task = processor.conversation_task
        processor.cancel_conversation()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        await processor.completion.close()
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)

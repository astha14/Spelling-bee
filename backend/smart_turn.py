"""Audio-only Smart Turn adapter: predictions are signals, never submissions.

One inference task handles immutable snapshots, so inference cannot clear audio
from a newer segment. Pipecat runs ONNX inference in its own executor thread.
"""
import asyncio
from collections import deque
from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState
from pipecat.frames.frames import InputAudioRawFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection


class SmartTurnSignals(FrameProcessor):
    def __init__(self, analyzer, completion, on_prediction):
        super().__init__()
        self.analyzer = analyzer
        self.completion = completion
        self.on_prediction = on_prediction
        self.chunks = deque()
        self.size = 0
        self.sample_rate = 16000
        self.pending = None
        self.inference = None
        self.closed = False

    def reset_audio(self):
        self.chunks.clear()
        self.size = 0
        self.pending = None

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if (direction == FrameDirection.DOWNSTREAM and isinstance(frame, InputAudioRawFrame)
                and self.analyzer and self.completion.active and frame.num_channels == 1):
            self.sample_rate = frame.sample_rate
            self.chunks.append(frame.audio)
            self.size += len(frame.audio)
            limit = int(self.sample_rate * 2 * self.completion.settings.smart_audio_seconds)
            while self.chunks and self.size > limit:
                self.size -= len(self.chunks.popleft())
        await self.push_frame(frame, direction)

    def predict(self, token):
        if not self.analyzer or not self.chunks or self.closed:
            return
        self.pending = (token, b"".join(self.chunks), self.sample_rate)
        if self.inference is None or self.inference.done():
            self.inference = asyncio.create_task(self._predict(), name="spelling-smart-turn")

    async def _predict(self):
        while self.pending and not self.closed:
            token, audio, sample_rate = self.pending
            self.pending = None
            try:
                self.analyzer.clear()
                self.analyzer.set_sample_rate(sample_rate)
                # The adapter owns silence timing. Do not use append_audio's
                # built-in silence timeout as a second completion controller.
                self.analyzer.append_audio(audio, is_speech=True)
                prediction, metrics = await self.analyzer.analyze_end_of_turn()
                await self.on_prediction(token, prediction == EndOfTurnState.COMPLETE)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.completion.debug("SMART_TURN unavailable; using silence fallback")
                await self.on_prediction(token, False)

    async def cleanup(self):
        self.closed = True
        self.reset_audio()
        if self.inference:
            self.inference.cancel()
            await asyncio.gather(self.inference, return_exceptions=True)
        if self.analyzer:
            await self.analyzer.cleanup()
        await super().cleanup()

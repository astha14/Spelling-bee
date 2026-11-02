"""Observe Cartesia responses using the installed Pipecat 1.14 adapter.

Keep the same model, audio streaming, finalization and transcription behavior.
The base adapter does not forward empty transcripts, so observe them here.
"""
import time
from backend import config
from websockets.protocol import State
from pipecat.services.cartesia.stt import CartesiaSTTService as BaseCartesiaSTTService


class CartesiaSTTService(BaseCartesiaSTTService):
    def __init__(self, *, report, **kwargs):
        kwargs.setdefault("settings", self.Settings(model=config.CARTESIA_STT_MODEL))
        super().__init__(**kwargs)
        self.report = report
        self.audio_bytes = 0
        self.disconnected_bytes = 0
        self.audio_log_at = time.monotonic()

    async def run_stt(self, audio):
        self.audio_bytes += len(audio)
        if not self._websocket or self._websocket.state is not State.OPEN:
            self.disconnected_bytes += len(audio)
        now = time.monotonic()
        if now - self.audio_log_at >= 1:
            self.report('STT audio input', bytes=self.audio_bytes,
                        disconnected_bytes=self.disconnected_bytes)
            self.audio_bytes = self.disconnected_bytes = 0
            self.audio_log_at = now
        async for frame in super().run_stt(audio):
            yield frame

    async def _on_transcript(self, data):
        text = data.get('text', '')
        self.report('STT provider final' if data.get('is_final') else 'STT provider partial',
                    characters=len(text), empty=not text.strip())
        await super()._on_transcript(data)

    async def _process_response(self, data):
        if data.get('type') == 'flush_done':
            self.report('STT flush acknowledged')
        await super()._process_response(data)

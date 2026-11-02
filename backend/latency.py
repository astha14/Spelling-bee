"""Observe server TTS milestones without buffering audio or exposing spoken text."""
from pipecat.frames.frames import TTSStartedFrame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection


class TTSLatencyProbe(FrameProcessor):
    def __init__(self, report):
        super().__init__()
        self.report = report
        self.first_audio = False

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, TTSStartedFrame):
                self.first_audio = True
                self.report('TTS synthesis started')
            elif isinstance(frame, TTSAudioRawFrame) and self.first_audio:
                self.first_audio = False
                self.report('TTS first audio generated')
        await self.push_frame(frame, direction)


class InputAudioProbe(FrameProcessor):
    """Aggregate server-received audio levels once per second; no recordings.

    This distinguishes absent/quiet WebRTC input from a later STT failure. It
    cannot prove the browser captured a particular spoken phoneme.
    """
    def __init__(self, completion):
        super().__init__()
        self.completion = completion
        self.samples = 0
        self.energy = 0
        self.started = completion.clock()

    async def process_frame(self, frame, direction):
        from pipecat.frames.frames import InputAudioRawFrame
        from array import array
        import sys
        await super().process_frame(frame, direction)
        if (self.completion.settings.debug and direction == FrameDirection.DOWNSTREAM
                and isinstance(frame, InputAudioRawFrame)):
            pcm = array('h')
            pcm.frombytes(frame.audio[:len(frame.audio) // 2 * 2])
            if sys.byteorder != 'little':
                pcm.byteswap()
            self.samples += len(pcm)
            self.energy += sum(value * value for value in pcm)
            now = self.completion.clock()
            if now - self.started >= 1:
                rms = (self.energy / max(self.samples, 1)) ** .5 / 32768
                self.completion.debug('AUDIO received', samples=self.samples,
                                      rms=round(rms, 5), vad_speaking=self.completion.speaking)
                self.samples = self.energy = 0
                self.started = now
        await self.push_frame(frame, direction)

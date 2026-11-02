import asyncio
from unittest.mock import AsyncMock
from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.frames.frames import InputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection
from backend.completion import SpellingCompletion
from backend.smart_turn import SmartTurnSignals


def test_bundled_v3_model_loads_and_predicts_without_network():
    async def scenario():
        analyzer = await asyncio.to_thread(LocalSmartTurnAnalyzerV3, cpu_count=1)
        analyzer.set_sample_rate(16000)
        analyzer.append_audio(bytes(16000), is_speech=True)
        prediction, metrics = await analyzer.analyze_end_of_turn()
        assert prediction in {EndOfTurnState.COMPLETE, EndOfTurnState.INCOMPLETE}
        assert metrics is not None
        assert 0 <= metrics.probability <= 1
        await analyzer.cleanup()
    asyncio.run(scenario())


def test_background_inference_snapshot_does_not_block_audio_or_accept_stale_signal():
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        class Analyzer:
            def clear(self):
                pass
            def set_sample_rate(self, rate):
                assert rate == 16000
            def append_audio(self, audio, is_speech):
                self.audio = audio
            async def analyze_end_of_turn(self):
                started.set()
                await release.wait()
                return EndOfTurnState.COMPLETE, None
            async def cleanup(self):
                pass
        c = SpellingCompletion(AsyncMock())
        c.begin("ELEPHANT")
        c.listen()
        async def prediction(token, complete):
            c.smart_result(token, complete)
        adapter = SmartTurnSignals(Analyzer(), c, prediction)
        adapter.push_frame = AsyncMock()
        await adapter.process_frame(InputAudioRawFrame(bytes(640), 16000, 1), FrameDirection.DOWNSTREAM)
        c.speech_started()
        c.final("ELE")
        c.speech_stopped()
        token = c.token
        adapter.predict(token)
        await asyncio.wait_for(started.wait(), 1)
        c.speech_started()  # Inference is pending, but user has already resumed.
        await asyncio.wait_for(adapter.process_frame(
            InputAudioRawFrame(bytes(640), 16000, 1), FrameDirection.DOWNSTREAM), .2)
        assert adapter.size == 1280
        assert len(adapter.analyzer.audio) == 640  # Immutable old snapshot.
        release.set()
        await adapter.inference
        assert not c.smart_complete
        await adapter.cleanup()
        await c.close()
    asyncio.run(scenario())

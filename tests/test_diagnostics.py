import asyncio
from unittest.mock import AsyncMock, Mock
import pytest
from backend.latency import TTSLatencyProbe
from backend.stt import CartesiaSTTService
from pipecat.frames.frames import TTSStartedFrame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection


def test_first_audio_is_logged_once_without_buffering():
    async def scenario():
        report = Mock()
        probe = TTSLatencyProbe(report)
        probe.push_frame = AsyncMock()
        frames = [TTSStartedFrame(), TTSAudioRawFrame(b'\0' * 320, 16000, 1),
                  TTSAudioRawFrame(b'\0' * 320, 16000, 1)]
        for frame in frames:
            await probe.process_frame(frame, FrameDirection.DOWNSTREAM)
        assert [call.args[0] for call in report.call_args_list] == [
            'TTS synthesis started', 'TTS first audio generated']
        assert [call.args[0] for call in probe.push_frame.call_args_list] == frames
    asyncio.run(scenario())


@pytest.mark.parametrize('letter', list('ABCDEFGPTVZMNJS'))
def test_cartesia_final_letter_frames_and_empty_diagnostics(letter):
    # Provider-response fixture, NOT an acoustic recognition test.
    async def scenario():
        report = Mock()
        stt = CartesiaSTTService(api_key='unused', report=report)
        stt.push_frame = AsyncMock()
        stt.emit_stt_usage_metrics = AsyncMock()
        stt._handle_transcription = AsyncMock()
        await stt._on_transcript({'text': letter, 'is_final': True})
        assert stt.push_frame.call_args.args[0].text == letter
        stt.push_frame.reset_mock()
        await stt._on_transcript({'text': '', 'is_final': True})
        stt.push_frame.assert_not_called()
        assert report.call_args.kwargs['empty'] is True
    asyncio.run(scenario())


@pytest.mark.parametrize('amplitude', [0, 20, 5000])
def test_audio_probe_reports_quiet_and_normal_input_without_dropping_frames(amplitude):
    from array import array
    from dataclasses import replace
    from backend.latency import InputAudioProbe
    from backend.completion import SpellingCompletion
    from backend.config import CompletionSettings
    from pipecat.frames.frames import InputAudioRawFrame
    async def scenario():
        now = [10.0]
        completion = SpellingCompletion(AsyncMock(), replace(CompletionSettings(), debug=True), clock=lambda: now[0])
        completion.debug = Mock()
        probe = InputAudioProbe(completion)
        probe.push_frame = AsyncMock()
        frame = InputAudioRawFrame(array('h', [amplitude] * 320).tobytes(), 16000, 1)
        now[0] += 1.1
        await probe.process_frame(frame, FrameDirection.DOWNSTREAM)
        probe.push_frame.assert_awaited_once_with(frame, FrameDirection.DOWNSTREAM)
        assert completion.debug.call_args.kwargs['samples'] == 320
        assert completion.debug.call_args.kwargs['rms'] == pytest.approx(amplitude / 32768, abs=.00001)
    asyncio.run(scenario())


def test_stt_disconnected_audio_is_visible_in_diagnostics():
    async def scenario():
        report = Mock()
        stt = CartesiaSTTService(api_key='unused', report=report)
        stt.audio_log_at = 0
        frames = [frame async for frame in stt.run_stt(b'\0' * 320)]
        assert frames == [None]
        assert report.call_args.args[0] == 'STT audio input'
        assert report.call_args.kwargs['disconnected_bytes'] == 320
    asyncio.run(scenario())


def test_stt_keeps_existing_model_unless_explicitly_configured(monkeypatch):
    from backend import config
    monkeypatch.setattr(config, 'CARTESIA_STT_MODEL', 'ink-whisper')
    stt = CartesiaSTTService(api_key='unused', report=Mock())
    assert stt._settings.model == 'ink-whisper'

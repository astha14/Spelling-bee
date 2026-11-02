import asyncio
from unittest.mock import AsyncMock, Mock
from backend.bot import GameProcessor
from backend.host import Host
from backend import config

def test_adapter_speaks_without_sending_target_text(monkeypatch):
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', '')
    async def scenario():
        connection = Mock()
        host = Host()
        processor = GameProcessor(connection, host)
        processor.push_frame = AsyncMock()
        host.begin()
        await processor.respond('Alex')
        await processor.respond('easy mode')
        word = host.game.current.text
        assert word in processor.push_frame.call_args.args[0].text
        assert word not in str(connection.send_app_message.call_args.args[0])
        processor.push_frame.reset_mock()
        for letter in word:
            await processor.respond(letter)
        processor.push_frame.assert_not_called()
        await processor.respond(action='submit')
        assert host.game.score == 0
        await processor.respond(action='confirm')
        assert host.game.score == 10
    asyncio.run(scenario())


def test_interruptions_require_vad_and_only_accept_commands():
    async def scenario():
        host = Host()
        host.begin()
        host.handle('start game')
        host.handle('easy mode')
        processor = GameProcessor(Mock(), host)
        processor.push_frame = AsyncMock()
        processor.broadcast_interruption = AsyncMock()
        processor.speaking = True
        await processor.accept_transcript('repeat the word')
        processor.broadcast_interruption.assert_not_called()
        processor.heard_user = True
        await processor.accept_transcript('C A T')
        assert host.letters == ''
        processor.broadcast_interruption.assert_not_called()
        host.handle('B B')
        await processor.accept_transcript('repeat the word')
        processor.broadcast_interruption.assert_awaited_once()
        assert host.letters == 'BB'
        assert host.game.index == 0
        # Late echo arriving after playback is still rejected for an overlapping turn.
        processor.overlapping_speech = True
        await processor.accept_transcript('C A T')
        assert host.letters == 'BB'
    asyncio.run(scenario())


def test_vad_silence_never_submits():
    from pipecat.frames.frames import VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection
    async def scenario():
        host = Host()
        host.begin()
        host.handle('start game')
        host.handle('easy mode')
        host.handle('A B')
        processor = GameProcessor(Mock(), host)
        processor.push_frame = AsyncMock()
        await processor.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await processor.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        assert host.letters == 'AB'
        assert host.pending is None
        assert host.game.index == 0
    asyncio.run(scenario())


def test_feedback_does_not_wait_for_openrouter(monkeypatch):
    import httpx
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', 'test-key')
    client = Mock(side_effect=AssertionError('Feedback must not call an LLM'))
    monkeypatch.setattr(httpx, 'AsyncClient', client)
    async def scenario():
        host = Host()
        host.begin()
        host.handle('start game')
        host.handle('easy mode')
        processor = GameProcessor(Mock(), host)
        processor.push_frame = AsyncMock()
        await processor.respond(' '.join(host.game.current.text.upper()))
        await processor.respond(action='submit')
        await processor.respond(action='confirm')
        assert host.game.score == 10
        speech = processor.push_frame.call_args.args[0].text
        assert 'Correct!' in speech
        assert 'practice' not in speech.lower()
        client.assert_not_called()
        await processor.completion.close()
    asyncio.run(scenario())

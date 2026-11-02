import asyncio
import json
from unittest.mock import AsyncMock, Mock
import pytest
from backend.host import Host
from backend.bot import GameProcessor
from backend import config, bot
from backend.conversation import interpret
from pipecat.frames.frames import BotStoppedSpeakingFrame, VADUserStartedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection


def ready():
    h = Host()
    h.begin()
    h.handle('Alex')
    h.handle('easy mode')
    h.handle('F R')
    return h


@pytest.mark.parametrize('utterance', [
    'Can you repeat the word?', 'Wait, can you repeat the word?',
    'Can you use it in a sentence?', 'What is the definition?',
    "I'm nervous", 'This sounds difficult!', 'Tell me a joke', "Okay, let's try.", 'This is hard!',
    "What's my score?", 'What are the rules?', 'I love this game',
])
def test_conversation_preserves_attempt(utterance):
    async def scenario():
        h = ready()
        p = GameProcessor(Mock(), h)
        p.push_frame = AsyncMock()
        p.sync_attempt()
        token = p.completion.attempt_id
        word = h.game.current
        await p.respond(utterance)
        assert h.game.current == word
        assert h.game.index == h.game.score == 0
        assert h.letters == 'FR'
        assert p.completion.attempt_id == token
        assert not p.completion.unclear_segment
        assert p.push_frame.call_args.args[0].text
        await p.completion.close()
    asyncio.run(scenario())


def test_pause_resume_and_spelling_after_chat():
    async def scenario():
        h = ready()
        p = GameProcessor(Mock(), h)
        p.push_frame = AsyncMock()
        p.sync_attempt()
        token = p.completion.attempt_id
        await p.respond('pause the contest')
        await p.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        assert h.paused and not p.completion.active
        await p.respond('O G')
        assert h.letters == 'FR'
        assert p.completion.deadline() is None
        await p.respond('resume the contest')
        await p.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await p.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await p.accept_transcript('O G')
        assert h.letters == 'FROG'
        assert token == p.completion.attempt_id
        await p.completion.close()
    asyncio.run(scenario())


def test_llm_conversation_is_cancellable_and_never_grades(monkeypatch):
    async def scenario():
        wait = asyncio.Event()
        async def slow(*args):
            await wait.wait()
            return 'conversation', 'Happy to chat!'
        monkeypatch.setattr(bot, 'interpret', slow)
        h = ready()
        p = GameProcessor(Mock(), h)
        p.push_frame = AsyncMock()
        p.sync_attempt()
        await p.respond('Can you tell me something interesting?')
        task = p.conversation_task
        assert task and p.completion.deadline() is None
        await asyncio.sleep(0)
        await p.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled()
        await p.accept_transcript('O D')
        assert h.letters == 'FROD'
        assert h.game.index == 0
        await p.completion.close()
    asyncio.run(scenario())


def test_generated_reply_preserves_letters_and_score(monkeypatch):
    async def scenario():
        monkeypatch.setattr(bot, 'interpret', AsyncMock(return_value=('conversation', 'That sounds fun!')))
        h = ready()
        p = GameProcessor(Mock(), h)
        p.push_frame = AsyncMock()
        p.sync_attempt()
        await p.respond('Can we talk about bees?')
        await p.conversation_task
        assert h.letters == 'FR'
        assert h.game.score == h.game.index == 0
        assert p.push_frame.call_args.args[0].text == 'That sounds fun!'
        await p.completion.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('output, expected', [
    ({'intent': 'score', 'reply': 'You have 100 points'}, ('score', '')),
    ({'intent': 'grade', 'reply': 'Correct'}, ('clarify', '')),
    ({'intent': 'conversation', 'reply': 'Your answer is correct!'}, ('clarify', '')),
    ({'intent': 'conversation', 'reply': 'F-R-O-G'}, ('clarify', '')),
    ({'intent': 'conversation', 'reply': 'Bees are fascinating!'}, ('conversation', 'Bees are fascinating!')),
])
def test_llm_boundaries(monkeypatch, output, expected):
    import httpx
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', 'test')
    response = Mock()
    response.json.return_value = {'choices': [{'message': {'content': json.dumps(output)}}]}
    client = AsyncMock()
    client.post.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(httpx, 'AsyncClient', Mock(return_value=context))
    result = asyncio.run(interpret('Can we talk?', 'Alex', 'frog', Mock()))
    assert result == expected
    payload = client.post.call_args.kwargs['json']
    assert 'frog' not in json.dumps(payload).lower()


def test_letters_never_call_llm(monkeypatch):
    async def scenario():
        model = AsyncMock(side_effect=AssertionError('Letters are not conversation'))
        monkeypatch.setattr(bot, 'interpret', model)
        h = ready()
        p = GameProcessor(Mock(), h)
        p.push_frame = AsyncMock()
        for text in ['F', 'R', 'O', 'G', 'B for bravo', 'M N', 'P T']:
            await p.respond(text)
        model.assert_not_called()
        assert h.letters == 'FRFROGBMNPT'
        await p.completion.close()
    asyncio.run(scenario())


def test_end_game_cancels_pending_conversation(monkeypatch):
    async def scenario():
        pending = asyncio.Event()
        async def delayed(*args):
            await pending.wait()
            return 'conversation', 'Hello!'
        monkeypatch.setattr(bot, 'interpret', delayed)
        p = GameProcessor(Mock(), ready())
        p.push_frame = AsyncMock()
        p.sync_attempt()
        await p.respond('Can we talk about bees?')
        task = p.conversation_task
        await p.respond('end game')
        await asyncio.gather(task, return_exceptions=True)
        assert p.host.state()['finished']
        assert p.conversation_task is None
        assert 'Hello!' not in str(p.push_frame.call_args_list)
        await p.completion.close()
    asyncio.run(scenario())


def test_no_key_ambiguous_question_falls_back_without_network(monkeypatch):
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', '')
    assert asyncio.run(interpret('Can you help?', 'Alex', 'frog', Mock())) == ('clarify', '')


def test_nervous_phonetic_is_not_misrouted():
    h = ready()
    reply = h.handle('B for nervous')
    assert 'clear letters' in reply
    assert h.letters == 'FR'


def test_question_before_name_does_not_become_player_name(monkeypatch):
    async def scenario():
        monkeypatch.setattr(bot, 'interpret', AsyncMock(return_value=('conversation', 'Happy to meet you!')))
        h = Host()
        h.begin()
        p = GameProcessor(Mock(), h)
        p.push_frame = AsyncMock()
        await p.respond('How are you today?')
        await p.conversation_task
        assert h.name == ''
        assert h.phase.value == 'WELCOME'
        await p.completion.close()
    asyncio.run(scenario())

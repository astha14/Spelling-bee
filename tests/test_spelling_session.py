"""Stage 1 integration checks for pause-safe, player-confirmed spelling."""
import asyncio
from unittest.mock import AsyncMock, Mock

from backend.bot import GameProcessor
from backend.completion import SpellingCompletion
from backend.config import CompletionSettings
from backend.host import Host, Phase
from backend.word_bank import Word
from pipecat.frames.frames import BotStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection


class Clock:
    now = 100.0
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += seconds


def ready():
    host = Host()
    host.begin()
    host.handle("start game")
    host.handle("easy mode")
    host.game.words = (Word("frog", "An amphibian that hops."),)
    host.game.index = 0
    processor = GameProcessor(Mock(), host)
    processor.push_frame = AsyncMock()
    clock = Clock()
    processor.completion.clock = clock
    processor.sync_attempt()
    processor.completion.listen()
    return host, processor, clock


async def say_segment(host, processor, clock, transcript, duration=.3):
    processor.completion.speech_started()
    clock.advance(duration)
    await processor.respond(transcript)
    clock.advance(.2)
    processor.completion.speech_stopped()


def test_paused_spelling_accumulates_and_wrong_letter_is_not_repaired():
    async def scenario():
        host, processor, clock = ready()
        for segment in ("F", "R", "O", "D"):
            await say_segment(host, processor, clock, segment)
            clock.advance(1)
        assert host.letters == "FROD"
        assert host.game.index == 0
        await processor.completion.close()
    asyncio.run(scenario())


def test_three_second_pause_preserves_letters_and_silence_only_asks():
    async def scenario():
        host, processor, clock = ready()
        await say_segment(host, processor, clock, "F R")
        token = processor.completion.token
        clock.advance(3)
        assert processor.completion.due(token) is None
        await say_segment(host, processor, clock, "O G")
        clock.advance(6)
        assert processor.completion.due(processor.completion.token) == "submit"
        await processor.completion_due(processor.completion.token)
        assert host.letters == "FROG"
        assert host.phase == Phase.CONFIRMING_ANSWER
        assert host.game.index == host.game.score == 0
        await processor.respond("yes")
        assert host.game.results[0]["answer"] == "FROG"
        assert host.game.score == 10
        await processor.completion.close()
    asyncio.run(scenario())


def test_explicit_confirmation_is_the_only_path_to_grading():
    async def scenario():
        host, processor, _ = ready()
        host.letters = "FROD"
        assert host.request_confirmation()
        await processor.respond("yes")
        assert host.game.index == 1
        assert host.game.score == 0
        assert host.game.results[0]["answer"] == "FROD"
        await processor.completion.close()
    asyncio.run(scenario())


def test_conversation_and_repeat_preserve_letters_and_round():
    async def scenario():
        host, processor, _ = ready()
        host.letters = "FR"
        await processor.respond("This word is really hard")
        assert host.letters == "FR"
        assert host.game.index == 0
        await processor.respond("Sorry, what was the word again?")
        assert host.letters == "FR"
        assert host.game.index == 0
        assert processor.push_frame.call_args.args[0].text.lower().find("frog") >= 0
        await processor.completion.close()
    asyncio.run(scenario())


def test_ambiguous_letter_waits_for_clarification_and_keeps_prefix():
    async def scenario():
        host, processor, clock = ready()
        await say_segment(host, processor, clock, "F R O")
        await say_segment(host, processor, clock, "B or D")
        clock.advance(6)
        await processor.completion_due(processor.completion.token)
        assert "B or D" in processor.push_frame.call_args.args[0].text
        assert host.letters == "FRO"
        assert host.game.index == 0
        await processor.completion.close()
    asyncio.run(scenario())


def test_repeated_unclear_letter_is_inserted_before_later_letters():
    async def scenario():
        host, processor, clock = ready()
        processor.completion.speech_started()
        await processor.respond("F R")
        await processor.respond("unclear audio")
        await processor.respond("G")
        processor.completion.speech_stopped()
        clock.advance(6)
        await processor.completion_due(processor.completion.token)
        assert host.letters == "FRG"
        await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        processor.completion.speech_started()
        await processor.respond("O")
        assert host.letters == "FROG"
        assert host.game.index == 0
        await processor.completion.close()
    asyncio.run(scenario())


def test_inline_self_correction_replaces_one_letter_and_keeps_suffix():
    async def scenario():
        host, processor, clock = ready()
        await say_segment(host, processor, clock, "F R O wait I meant A G")
        assert host.letters == "FRAG"
        assert host.game.index == 0
        await processor.completion.close()
    asyncio.run(scenario())


def test_silence_without_letters_never_submits():
    async def scenario():
        host, processor, clock = ready()
        token = processor.completion.token
        clock.advance(30)
        assert processor.completion.due(token) is None
        await processor.completion_due(token)
        assert host.game.index == 0
        assert host.phase == Phase.SPELLING
        await processor.completion.close()
    asyncio.run(scenario())

"""Deterministic clock tests exercise timing without waiting real seconds."""
import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, Mock
import pytest
from backend.completion import SpellingCompletion, CompletionState
from backend.config import CompletionSettings
from backend.bot import GameProcessor
from backend.host import Host, Phase
from pipecat.frames.frames import (
    InterimTranscriptionFrame, TranscriptionFrame, BotStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection


class Clock:
    now = 100.0
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += seconds


def setup_controller():
    clock = Clock()
    submitted = []
    async def due(token):
        if controller.claim(token):
            submitted.append(controller.letters)
    controller = SpellingCompletion(due, settings=CompletionSettings(
        completion_timeout=2.5, maximum_timeout=4.0), clock=clock)
    controller.begin("ELEPHANT")
    controller.listen()
    return controller, clock, submitted


def segment(controller, clock, letters):
    controller.speech_started()
    clock.advance(.5)
    controller.final(letters)
    clock.advance(.2)
    controller.speech_stopped()


@pytest.mark.parametrize("letters", ["ELEPHANT", "ELEFANT", "ELE", "ELEPHANTT"])
@pytest.mark.parametrize("smart", [True, False])
def test_continuous_spelling_any_length_and_correctness(letters, smart):
    async def scenario():
        c, clock, submitted = setup_controller()
        segment(c, clock, letters)
        c.smart_result(c.token, smart)
        clock.advance(.7)
        assert c.due(c.token) is None  # Even an early positive cannot submit.
        clock.advance(4)
        token = c.token
        await c.on_due(token)
        await c.on_due(token)
        c.speech_stopped()
        assert submitted == [letters]
        assert c.submitted
        await c.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("pause", [.2, .8, 1.5, 2.1])
def test_short_pauses_and_midword_resume(pause):
    async def scenario():
        c, clock, submitted = setup_controller()
        segment(c, clock, "ELE")
        stale = c.token
        c.smart_result(stale, True)
        clock.advance(pause)
        assert c.due(stale) is None
        c.speech_started()
        assert c.timer is None
        c.smart_result(stale, True)
        assert not c.smart_complete
        clock.advance(.5)
        c.final("ELEPHANT")
        clock.advance(.2)
        c.speech_stopped()
        clock.advance(4)
        await c.on_due(stale)
        assert submitted == []
        await c.on_due(c.token)
        assert submitted == ["ELEPHANT"]
        await c.close()
    asyncio.run(scenario())


def test_duplicate_stops_do_not_extend_silence_or_duplicate_submission():
    async def scenario():
        c, clock, submitted = setup_controller()
        segment(c, clock, "AB")
        deadline = c.deadline()
        clock.advance(1)
        c.speech_stopped()
        c.speech_stopped()
        assert c.deadline() == deadline
        clock.advance(4)
        await asyncio.gather(c.on_due(c.token), c.on_due(c.token))
        assert submitted == ["AB"]
        await c.close()
    asyncio.run(scenario())


def test_missing_smart_signal_uses_four_second_fallback():
    async def scenario():
        c, clock, submitted = setup_controller()
        segment(c, clock, "AB")
        clock.advance(2.5)
        assert c.due(c.token) is None
        clock.advance(1.5)
        await c.on_due(c.token)
        assert submitted == ["AB"]
        await c.close()
    asyncio.run(scenario())


def test_delayed_final_waits_then_uses_actual_final():
    async def scenario():
        c, clock, submitted = setup_controller()
        c.speech_started()
        c.interim()
        clock.advance(.5)
        c.speech_stopped()
        clock.advance(4)
        assert c.due(c.token) is None  # Pending result gets bounded grace.
        c.final("ELEFANT")
        await c.on_due(c.token)
        assert submitted == ["ELEFANT"]
        await c.close()
    asyncio.run(scenario())


def test_final_never_arrives_does_not_grade_old_prefix():
    async def scenario():
        c, clock, submitted = setup_controller()
        segment(c, clock, "ELE")
        c.speech_started()
        c.interim()
        clock.advance(.5)
        c.speech_stopped()
        clock.advance(c.settings.maximum_timeout + c.settings.stt_final_wait + .5)
        assert c.due(c.token) == "recognition_timeout"
        assert not c.claim(c.token)
        assert submitted == []
        await c.close()
    asyncio.run(scenario())


def test_silence_without_letters_and_old_attempt_callbacks():
    async def scenario():
        c, clock, submitted = setup_controller()
        clock.advance(30)
        assert c.deadline() is None
        segment(c, clock, "ELE")
        old_token = c.token
        c.begin("BEAUTIFUL")
        assert c.state == CompletionState.WAITING_FOR_WORD
        c.listen()
        clock.advance(20)
        await c.on_due(old_token)
        c.smart_result(old_token, True)
        assert not c.smart_complete
        assert submitted == []
        segment(c, clock, "ABC")
        clock.advance(5)
        await c.on_due(old_token)
        assert submitted == []
        await c.on_due(c.token)
        assert submitted == ["ABC"]
        await c.close()
    asyncio.run(scenario())


def test_queued_timeout_rechecks_after_resumed_speech():
    async def scenario():
        c, clock, submitted = setup_controller()
        segment(c, clock, "ELE")
        token = c.token
        clock.advance(4)
        assert c.due(token) == "submit"
        # A timer is ready, but speech resumes before it acquires the owner lock.
        c.speech_started()
        await c.on_due(token)
        assert submitted == []
        await c.close()
    asyncio.run(scenario())


def test_real_async_timer_runs_once_and_close_cancels():
    async def scenario():
        submitted = []
        ready = asyncio.Event()
        async def due(token):
            if c.claim(token):
                submitted.append(c.letters)
                ready.set()
        settings = replace(CompletionSettings(), vad_stop=.005,
            minimum_silence=.01, completion_timeout=.02, maximum_timeout=.03)
        c = SpellingCompletion(due, settings)
        c.begin("A")
        c.listen()
        c.speech_started()
        c.final("BB")
        c.speech_stopped()
        await asyncio.wait_for(ready.wait(), 1)
        assert submitted == ["BB"]
        c.begin("NEXT")
        c.listen()
        c.speech_started()
        c.final("C")
        c.speech_stopped()
        await c.close()
        await asyncio.sleep(.04)
        assert submitted == ["BB"]
    asyncio.run(scenario())


@pytest.mark.parametrize("changes", [
    {"vad_stop": 0}, {"vad_confidence": 2}, {"minimum_silence": 6},
    {"maximum_timeout": 1}, {"stt_final_wait": -1}, {"completion_timeout": float("nan")},
])
def test_invalid_settings_fail_early(changes):
    with pytest.raises(ValueError):
        replace(CompletionSettings(), **changes)


def test_revised_partials_only_final_appended_and_auto_grades(monkeypatch):
    async def scenario():
        host = Host()
        host.begin()
        host.handle("start game")
        host.handle("easy mode")
        processor = GameProcessor(Mock(), host)
        processor.push_frame = AsyncMock()
        clock = Clock()
        processor.completion.clock = clock
        async def send(frame):
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        processor.sync_attempt()
        processor.prepare_speech()
        await send(TranscriptionFrame("B B", "u", ""))
        assert host.letters == ""  # Prompt and feedback cannot become answers.
        await send(BotStoppedSpeakingFrame())
        await send(TranscriptionFrame("B B", "u", ""))
        assert host.letters == ""  # Late old-word final, before fresh VAD.
        await send(VADUserStartedSpeakingFrame())
        await send(InterimTranscriptionFrame("B", "u", ""))
        await send(InterimTranscriptionFrame("B D", "u", ""))
        assert host.letters == ""
        await send(TranscriptionFrame("B P", "u", ""))
        assert host.letters == "BP"
        clock.advance(.5)
        await send(VADUserStoppedSpeakingFrame())
        clock.advance(1)
        await send(VADUserStartedSpeakingFrame())
        await send(TranscriptionFrame("P", "u", ""))
        assert host.letters == "BPP"  # Repeated final letter is legitimate.
        clock.advance(.5)
        await send(VADUserStoppedSpeakingFrame())
        token = processor.completion.token
        clock.advance(5)
        await processor.completion_due(token)
        await processor.completion_due(token)
        assert host.game.index == 0
        assert host.phase == Phase.CONFIRMING_ANSWER
        await processor.respond("yes")
        assert host.game.index == 1
        assert host.game.results[0]["answer"] == "BPP"
        assert host.game.score == 0
        assert host.phase == Phase.SPELLING
        assert processor.completion.state == CompletionState.WAITING_FOR_WORD
        assert host.letters == ""
        assert "say done" not in processor.push_frame.call_args.args[0].text.lower()
        await processor.completion.close()
    asyncio.run(scenario())


def test_ten_automatic_rounds_and_replay_no_completion_phrase(monkeypatch):
    async def scenario():
        host = Host()
        host.begin()
        host.handle("start game")
        host.handle("easy mode")
        p = GameProcessor(Mock(), host)
        p.push_frame = AsyncMock()
        clock = Clock()
        p.completion.clock = clock
        for index in range(10):
            await p.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
            await p.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await p.accept_transcript(" ".join(host.game.current.text.upper()))
            clock.advance(.5)
            await p.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            token = p.completion.token
            clock.advance(5)
            await p.completion_due(token)
            assert host.phase == Phase.CONFIRMING_ANSWER
            await p.respond("yes")
            assert host.game.index == index + 1
            assert host.game.score == (index + 1) * 10
        assert host.phase == Phase.GAME_OVER
        await p.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await p.accept_transcript("play again")
        assert host.phase == Phase.DIFFICULTY_SELECTION
        assert host.game.score == 0
        await p.completion.close()
    asyncio.run(scenario())


def test_queued_old_transcript_rejected_after_new_attempt():
    async def scenario():
        host = Host()
        host.begin()
        host.handle("start game")
        host.handle("easy mode")
        p = GameProcessor(Mock(), host)
        p.sync_attempt()
        old = p.transcript_token
        p.completion.begin(host.game.current.text)
        await p.respond("B B", attempt_token=old)
        assert host.letters == ""
        await p.completion.close()
    asyncio.run(scenario())


def test_corrected_buffer_completes_after_host_response_without_more_speech(monkeypatch):
    async def scenario():
        host = Host()
        host.begin()
        host.handle("start game")
        host.handle("easy mode")
        p = GameProcessor(Mock(), host)
        p.push_frame = AsyncMock()
        clock = Clock()
        p.completion.clock = clock
        await p.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await p.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await p.accept_transcript("B B")
        clock.advance(.5)
        await p.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await p.respond("replace last letter with D")
        assert host.letters == "BD"
        clock.advance(10)  # No submission while host reads the correction.
        assert p.completion.deadline() is None
        await p.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        assert not p.completion.heard_speech
        token = p.completion.token
        clock.advance(1)
        assert p.completion.due(token) is None
        clock.advance(4)
        await p.completion_due(token)
        assert host.phase == Phase.CONFIRMING_ANSWER
        await p.respond("yes")
        assert host.game.results[0]["answer"] == "BD"
        await p.completion.close()
    asyncio.run(scenario())


def test_unclear_segment_does_not_interrupt_or_discard_following_letters(monkeypatch):
    async def scenario():
        h = Host()
        h.begin()
        h.handle("start game")
        h.handle("easy mode")
        p = GameProcessor(Mock(), h)
        p.push_frame = AsyncMock()
        clock = Clock()
        p.completion.clock = clock
        async def send(frame):
            await p.process_frame(frame, FrameDirection.DOWNSTREAM)
        await send(BotStoppedSpeakingFrame())
        await send(VADUserStartedSpeakingFrame())
        await p.accept_transcript("B E")
        p.push_frame.reset_mock()
        await p.accept_transcript("unclear audio")
        p.push_frame.assert_not_called()  # No TTS while the player continues.
        await p.accept_transcript("A U T I F U L")
        assert h.letters == "BEAUTIFUL"
        assert not p.speaking
        clock.advance(.5)
        await send(VADUserStoppedSpeakingFrame())
        clock.advance(5)
        await p.completion_due(p.completion.token)
        assert h.game.index == 0  # Unknown segment cannot be silently omitted.
        assert "missed part" in p.push_frame.call_args.args[0].text
        await send(BotStoppedSpeakingFrame())
        await p.respond("let me try again")
        assert not p.completion.unclear_segment
        assert h.letters == ""
        await send(BotStoppedSpeakingFrame())
        await send(VADUserStartedSpeakingFrame())
        await p.accept_transcript("B E A U T I F U L")
        clock.advance(.5)
        await send(VADUserStoppedSpeakingFrame())
        clock.advance(5)
        await p.completion_due(p.completion.token)
        assert h.phase == Phase.CONFIRMING_ANSWER
        await p.respond("yes")
        assert h.game.index == 1
        assert h.game.results[0]["answer"] == "BEAUTIFUL"
        await p.completion.close()
    asyncio.run(scenario())


def test_final_arrives_more_than_one_second_after_fallback_timeout():
    async def scenario():
        c, clock, submitted = setup_controller()
        c.speech_started()
        c.interim()
        clock.advance(.5)
        c.speech_stopped()
        clock.advance(5.5)
        assert c.due(c.token) is None
        c.final("ELEPHANT")
        await c.on_due(c.token)
        assert submitted == ["ELEPHANT"]
        await c.close()
    asyncio.run(scenario())


def test_queued_final_survives_next_speech_segment_in_same_attempt():
    async def scenario():
        host = Host()
        host.begin()
        host.handle('start game')
        host.handle('easy mode')
        p = GameProcessor(Mock(), host)
        p.push_frame = AsyncMock()
        p.sync_attempt()
        p.completion.listen()
        p.completion.speech_started()
        token = p.transcript_token
        p.completion.speech_stopped()
        async with p.lock:
            queued = asyncio.create_task(p.respond('E L E', attempt_token=token))
            await asyncio.sleep(0)
            p.completion.speech_started()
        await queued
        await p.respond('P H A N T', attempt_token=p.transcript_token)
        assert host.letters == 'ELEPHANT'
        assert host.game.index == 0
        await p.completion.close()
    asyncio.run(scenario())


def test_queued_final_rejected_after_host_playback():
    async def scenario():
        host = Host()
        host.begin()
        host.handle('start game')
        host.handle('easy mode')
        p = GameProcessor(Mock(), host)
        p.sync_attempt()
        token = p.transcript_token
        p.prepare_speech()
        await p.respond('B B', attempt_token=token)
        assert host.letters == ''
        await p.completion.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('smart, delay', [(True, 5.0), (False, 5.0)])
def test_fast_defaults_shorten_actual_silence_deadline(smart, delay):
    async def scenario():
        c, clock, submitted = setup_controller()
        c.settings = CompletionSettings()
        segment(c, clock, 'ELEFANT')
        c.smart_result(c.token, smart)
        assert c.deadline() - c.last_speech == pytest.approx(5.0)
        clock.advance(delay)
        await c.on_due(c.token)
        assert submitted == ['ELEFANT']  # No expected-word or length shortcut.
        await c.close()
    asyncio.run(scenario())


def test_observed_pauses_extend_fast_window_and_survive_new_word():
    async def scenario():
        c, clock, submitted = setup_controller()
        c.settings = CompletionSettings()
        segment(c, clock, 'E')
        clock.advance(1.5)  # 1.7 seconds since speech ended, including VAD silence.
        c.speech_started()
        clock.advance(.4)
        c.final('EL')
        c.speech_stopped()
        c.smart_result(c.token, True)
        assert c.deadline() - c.last_speech == pytest.approx(5.0)
        clock.advance(1.5)
        assert c.due(c.token) is None
        assert submitted == []
        c.begin('BOOK')
        c.listen()
        segment(c, clock, 'B')
        c.smart_result(c.token, True)
        assert c.deadline() - c.last_speech == pytest.approx(5.0)
        await c.close()
    asyncio.run(scenario())


def test_grouped_letter_finals_across_pauses_do_not_force_retry():
    async def scenario():
        host = Host()
        host.begin()
        host.handle('start game')
        host.handle('easy mode')
        p = GameProcessor(Mock(), host)
        p.push_frame = AsyncMock()
        clock = Clock()
        p.completion.clock = clock
        await p.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        for text in ('E LE', 'P H ANT'):
            p.completion.speech_started()
            clock.advance(.4)
            await p.accept_transcript(text)
            await p.accept_transcript('.')
            p.completion.speech_stopped()
            clock.advance(.8)
        assert host.letters == 'ELEPHANT'
        assert not p.completion.unclear_segment
        clock.advance(6)
        await p.completion_due(p.completion.token)
        assert host.phase == Phase.CONFIRMING_ANSWER
        await p.respond('yes')
        assert host.game.results[0]['answer'] == 'ELEPHANT'
        assert host.game.index == 1
        await p.completion.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('segments', [('A P P L E',), ('A P', 'P L', 'E'), ('A', 'P', 'P', 'L', 'E')])
def test_apple_segments_revised_partials_and_duplicate_frames(segments):
    async def scenario():
        host = Host()
        host.begin()
        host.handle('start game')
        host.handle('easy mode')
        p = GameProcessor(Mock(), host)
        p.push_frame = AsyncMock()
        clock = Clock()
        p.completion.clock = clock
        async def send(frame):
            await p.process_frame(frame, FrameDirection.DOWNSTREAM)
        await send(BotStoppedSpeakingFrame())
        attempt = p.completion.attempt_id
        for text in segments:
            await send(VADUserStartedSpeakingFrame())
            await send(InterimTranscriptionFrame('wrong partial', 'u', ''))
            await send(InterimTranscriptionFrame(text, 'u', ''))
            final = TranscriptionFrame(text, 'u', '')
            await send(final)
            await send(final)  # Same event re-delivered, not another spoken P.
            clock.advance(.3)
            await send(VADUserStoppedSpeakingFrame())
            p.completion.smart_result(p.completion.token, True)
            clock.advance(.7)
            assert p.completion.attempt_id == attempt
            assert host.game.index == 0
        assert host.letters == 'APPLE'
        clock.advance(6)
        await p.completion_due(p.completion.token)
        assert host.phase == Phase.CONFIRMING_ANSWER
        await p.respond('yes')
        assert host.game.results[0]['answer'] == 'APPLE'
        assert host.game.index == 1
        await p.completion.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('gap', [.5, 1, 2, 3])
@pytest.mark.parametrize('slow', [False, True])
def test_frog_pause_tolerance_is_explicit(gap, slow):
    async def scenario():
        c, clock, submitted = setup_controller()
        c.settings = (CompletionSettings(completion_timeout=3.5, maximum_timeout=4)
                      if slow else CompletionSettings())
        accumulated = ''
        for letter in 'FROG':
            if accumulated:
                # Include the configured VAD start detection delay.
                clock.now = c.last_speech + gap + c.settings.vad_start
                if c.due(c.token) == 'submit':
                    await c.on_due(c.token)
                    break
            c.speech_started()
            clock.advance(.3)
            accumulated += letter
            c.final(accumulated)
            clock.advance(c.settings.vad_stop)
            c.speech_stopped()
            c.smart_result(c.token, True)  # Worst case: early completion every time.
        if slow or gap <= 3:
            assert c.letters == 'FROG'
            assert not submitted
            clock.advance(5)
            await c.on_due(c.token)
            assert submitted == ['FROG']
        else:
            # Documented limit: no claim that thinking pauses can be inferred.
            assert submitted == []
        await c.close()
    asyncio.run(scenario())

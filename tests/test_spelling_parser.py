import pytest
from backend.spelling_parser import parse_spelling

@pytest.mark.parametrize("text, letters", [("B - E - A - U - T - I - F - U - L", "BEAUTIFUL"), ("bee dee pee tee em en", "BDPTMN"), ("L L", "LL"), ("bravo delta papa tango mike november", "BDPTMN"), ("double you eye en", "WIN"), ("CAT", "CAT")])
def test_letters(text, letters):
    assert parse_spelling(text).letters == letters

@pytest.mark.parametrize("text", ["I like cats", "beautiful", "can you help me", "", "B potato D"])
def test_not_spelling(text):
    assert parse_spelling(text).uncertain
    assert not parse_spelling(text).letters

@pytest.mark.parametrize("text, command", [("repeat the word", "repeat"), ("give me a hint", "hint"), ("I'm done.", "submit"), ("change my answer", "clear")])
def test_commands(text, command):
    assert parse_spelling(text).command == command

def test_letters_and_done():
    parsed = parse_spelling("C A T, I'm done.")
    assert parsed.letters == "CAT"
    assert parsed.command == "submit"

@pytest.mark.parametrize("text, letters", [
    ("A for Apple, B for Ball", "AB"),
    ("bee for ball, dee as in dog", "BD"),
    ("B for bravo, D for delta, P for papa", "BDP"),
    ("L L, finished", "LL"),
    ("C A T, that's my answer", "CAT"),
])
def test_voice_spelling_phrases(text, letters):
    assert parse_spelling(text).letters == letters

@pytest.mark.parametrize("text", ["B for dog", "P as in tiger"])
def test_conflicting_phonetics_need_clarification(text):
    result = parse_spelling(text)
    assert result.uncertain
    assert not result.letters

@pytest.mark.parametrize("text, command", [
    ("start game", "start"), ("Easy mode", "easy"), ("medium mode", "medium"),
    ("hard mode", "hard"), ("finished", "submit"), ("that's my answer", "submit"),
    ("let me try again", "clear"), ("next word", "next"),
    ("what's my score?", "score"), ("play again", "replay"),
    ("use it in a sentence", "sentence"), ("what does it mean?", "hint"),
])
def test_all_voice_commands(text, command):
    assert parse_spelling(text).command == command


def test_last_letter_correction():
    parsed = parse_spelling("replace last letter with B for bravo")
    assert parsed.command == "replace_last"
    assert parsed.replacement == "B"

@pytest.mark.parametrize("text, letters", [
    ("be ee ay you tea eye eff you ell", "BEAUTIFUL"),
    ("A double P L E", "APPLE"), ("B double O K", "BOOK"),
    ("triple S", "SSS"), ("double u eye en", "WIN"),
    ("CAT.", "CAT"), ("CAT, done", "CAT"),
    ("E.L.E.P.H.A.N.T.", "ELEPHANT"),
])
def test_additional_stt_letter_renderings(text, letters):
    assert parse_spelling(text).letters == letters


@pytest.mark.parametrize('text, letters', [
    ('E LE P H ANT', 'ELEPHANT'), ('BE AU T I F UL.', 'BEAUTIFUL'),
    ('EL E F ANT', 'ELEFANT'), ('B B OO K', 'BBOOK'),
])
def test_uppercase_letter_chunks_preserve_actual_spelling(text, letters):
    assert parse_spelling(text).letters == letters


@pytest.mark.parametrize('text', ['please help me', 'E le please', 'I need a hint'])
def test_mixed_conversation_is_not_expanded_into_letters(text):
    assert not parse_spelling(text).letters

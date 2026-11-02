import random
import pytest
from backend.game_logic import Game

def test_score_and_privacy():
    game = Game(rng=random.Random(1))
    assert "word" not in game.public_state()
    answer = " - ".join(game.current.text)
    assert game.submit(answer)["correct"]
    assert game.score == 10
    game.submit("ZZZZ")
    assert game.score == 10
    assert game.index == 2

def test_finish():
    game = Game(length=1)
    game.submit(game.current.text)
    assert game.finished
    assert game.public_state()["percentage"] == 100
    with pytest.raises(ValueError):
        game.submit("A")

@pytest.mark.parametrize("answer", ["", "---", "12", "a!", "é"])
def test_invalid_answer_does_not_advance(answer):
    game = Game()
    with pytest.raises(ValueError):
        game.submit(answer)
    assert game.index == 0

@pytest.mark.parametrize("level", ["easy", "medium", "hard"])
def test_words_unique(level):
    game = Game(level)
    assert len({word.text for word in game.words}) == 10

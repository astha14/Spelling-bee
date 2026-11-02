"""Pure Python game state. No network, microphone, or LLM required."""
import random
from backend.word_bank import WORD_BANK
from backend.spelling_parser import normalize_spelling

class Game:
    def __init__(self, difficulty="easy", length=10, rng=None):
        if difficulty not in WORD_BANK:
            raise ValueError("Choose easy, medium, or hard.")
        if not 1 <= length <= len(WORD_BANK[difficulty]):
            raise ValueError("Invalid game length.")
        self.words = (rng or random).sample(WORD_BANK[difficulty], length)
        self.index = 0
        self.score = 0
        self.results = []

    @property
    def finished(self):
        return self.index >= len(self.words)

    @property
    def current(self):
        if self.finished:
            raise ValueError("The game is finished.")
        return self.words[self.index]

    def submit(self, answer):
        normalized = normalize_spelling(answer)
        if not normalized or not normalized.isascii() or not normalized.isalpha():
            raise ValueError("Please provide letters before submitting.")
        word = self.current.text
        correct = normalized == word.upper()
        self.score += 10 if correct else 0
        result = {"word": word, "answer": normalized, "correct": correct}
        self.results.append(result)
        self.index += 1
        return result

    def public_state(self):
        return {"score": self.score, "question": min(self.index + 1, len(self.words)),
                "total": len(self.words), "finished": self.finished,
                "percentage": round(self.score / (len(self.words) * 10) * 100),
                "answered": len(self.results)}

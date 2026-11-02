"""Deterministic conversation state: only Python can grade or change rounds."""
from enum import StrEnum
from backend.game_logic import Game
from backend.player_name import extract_name
from backend.spelling_parser import parse_spelling
from backend.conversation import local_intent


class Phase(StrEnum):
    IDLE = "IDLE"
    WELCOME = "WELCOME"
    DIFFICULTY_SELECTION = "DIFFICULTY_SELECTION"
    ASKING_WORD = "ASKING_WORD"
    SPELLING = "SPELLING"
    CONFIRMING_ANSWER = "CONFIRMING_ANSWER"
    VALIDATING = "VALIDATING"
    FEEDBACK = "FEEDBACK"
    NEXT_WORD = "NEXT_WORD"
    GAME_OVER = "GAME_OVER"


class Host:
    def __init__(self, difficulty="easy"):
        self.difficulty = difficulty
        self.game = Game(difficulty)
        self.name = ""
        self.phase = Phase.IDLE
        self.transitions = [self.phase]
        self.letters = ""
        self.pending = None
        self.ended = False
        self.paused = False
        self.chat_count = 0

    def transition(self, phase):
        self.phase = phase
        self.transitions.append(phase)
        self.transitions = self.transitions[-100:]

    def begin(self):
        self.transition(Phase.WELCOME)
        return "Hey! Welcome to the Spelling Bee Challenge! What is your name? Or say start game."

    def state(self):
        # Never serialize Word, host speech, STT transcripts, or result history.
        return {**self.game.public_state(), "phase": self.phase.value,
                "name": self.name, "paused": self.paused,
                "interaction": ("PAUSED" if self.paused else
                    "SPELLING_IN_PROGRESS" if self.phase == Phase.SPELLING and self.letters else
                    "WAITING_FOR_SPELLING" if self.phase == Phase.SPELLING else self.phase.value),
                "finished": self.phase == Phase.GAME_OVER}

    def prompt(self):
        return f"Your word is: {self.game.current.text}. Please spell it."

    def ask_word(self):
        self.transition(Phase.ASKING_WORD)
        speech = self.prompt()
        self.transition(Phase.SPELLING)
        return speech

    def score(self):
        return f"Your score is {self.game.score} out of {len(self.game.words) * 10}."

    def restart(self):
        self.game = Game(self.difficulty)
        self.paused = False
        self.letters, self.pending, self.ended = "", None, False
        self.transition(Phase.DIFFICULTY_SELECTION)
        return "Let's play! Choose easy mode, medium mode, or hard mode."

    def handle(self, text="", action=None):
        parsed = parse_spelling(text)
        command = action or parsed.command or (local_intent(text) if not parsed.letters else None)
        if command in {'rules', 'pause', 'resume', 'nervous', 'joke', 'encouragement', 'clarify', 'conversation'}:
            return self.chat(command)
        if self.paused and command not in {'end', 'score', 'repeat', 'hint', 'sentence'}:
            return "We're paused. Say resume when you're ready; your letters are saved."
        if command == "score":
            return self.score()
        if command == "end":
            self.ended = True
            self.transition(Phase.GAME_OVER)
            return self.score() + " Thanks for playing! Say play again for another game."
        if self.phase == Phase.GAME_OVER:
            if command in {"replay", "start"}:
                return self.restart()
            return "Say play again to start a new game, or ask what's my score."
        if command == "replay":
            return "Say end game first if you want to start over."
        if self.phase == Phase.IDLE:
            return self.begin()
        if self.phase == Phase.WELCOME:
            if command in {"easy", "medium", "hard"}:
                self.transition(Phase.DIFFICULTY_SELECTION)
                return self.handle(text)
            if command not in {"start", "confirm"}:
                if command:
                    return "Tell me your name, or say start game."
                self.name = extract_name(text)
                if not self.name:
                    return "What is your name?"
            self.transition(Phase.DIFFICULTY_SELECTION)
            return f"Hi, {self.name or 'player'}! Choose easy mode, medium mode, or hard mode."
        if self.phase == Phase.DIFFICULTY_SELECTION:
            if command in {"easy", "medium", "hard"}:
                self.difficulty = command
                self.game = Game(command)
                return "Ten words, ten points for each correct spelling. Spell at your pace; I check after silence. Say pause if you need thinking time. " + self.ask_word()
            return "Say easy mode, medium mode, or hard mode."
        if command == "repeat":
            return self.prompt()
        if command == "hint":
            return self.game.current.definition
        if command == "sentence":
            return self.game.current.sentence
        if command == "next":
            return "We move on after grading. Finish this spelling, or say let me try again."
        if command in {"easy", "medium", "hard", "start"}:
            return "A game is already running. Say end game to finish it first."
        if command == "clear":
            self.letters, self.pending = "", None
            self.transition(Phase.SPELLING)
            return "Answer cleared. Try spelling it again."
        if command in {"undo", "replace_last"}:
            if not self.letters:
                return "There are no letters to change yet."
            self.letters = self.letters[:-1] + (parsed.replacement or "")
            self.pending = None
            self.transition(Phase.SPELLING)
            return "Your letters are: " + ", ".join(self.letters) + ". Continue spelling when ready."
        if self.phase == Phase.CONFIRMING_ANSWER:
            if command != "confirm":
                return "Say confirm to grade, or let me try again to change your spelling."
            return self.validate_answer(self.pending)
        if command == "confirm":
            return "Spell your answer first. I will wait for you to finish."
        if not action and parsed.uncertain and not parsed.letters:
            return "I couldn't identify clear letters. Please repeat that part, or say B for bravo. Your answer is unchanged."
        if parsed.letters:
            self.letters += parsed.letters
        if command == "submit":
            if not self.letters:
                return "I haven't heard any letters yet. Please spell the word first."
            self.pending = self.letters
            self.transition(Phase.CONFIRMING_ANSWER)
            return "I heard: " + ", ".join(self.letters) + ". Say confirm to grade, or let me try again."
        return ""


    def chat(self, intent, reply=""):
        """Replies preserve round, letters, pending confirmation and score."""
        self.chat_count += 1
        if intent == 'pause':
            self.paused = True
            return "Take your time. We're paused, and your letters are saved. Say resume when you're ready."
        if intent == 'resume':
            self.paused = False
            return "Go ahead. I'm listening." if self.phase == Phase.SPELLING else "Ready! " + (
                "Choose easy, medium, or hard mode." if self.phase == Phase.DIFFICULTY_SELECTION else "Tell me what you'd like to do next.")
        if intent == 'rules':
            return "Ten words, ten points each. Spell aloud, and I'll check after silence. Ask for a repeat, definition or sentence anytime. Say pause for thinking time, then resume."
        if intent == 'nervous':
            return (f"No pressure{', ' + self.name if self.name else ''}. One letter at a time. You can say pause whenever you need a moment.")
        if intent == 'joke':
            jokes = ("Why did the bee bring a pencil? It wanted to improve its spelling!",
                     "My alphabet jokes are letter-perfect. My delivery? Still a work in progress!")
            return jokes[self.chat_count % len(jokes)] + " Ready when you are."
        if intent == 'encouragement':
            return "I'm glad you're here! Take your time; I'm listening."
        if intent == 'conversation' and reply:
            return reply
        return "Were you spelling, or asking me something? Your letters are saved. You can ask for a repeat, a hint, or the rules."


    def complete_automatically(self):
        """Called only after the controller atomically claims this attempt."""
        if self.paused or self.phase != Phase.SPELLING or not self.letters:
            return ""
        return self.validate_answer(self.letters)

    def validate_answer(self, answer):
        """Shared deterministic grading; no completion policy or LLM here."""
        self.transition(Phase.VALIDATING)
        result = self.game.submit(answer)
        self.pending, self.letters = None, ""
        self.transition(Phase.FEEDBACK)
        correct_lines = ("Excellent! Correct! You earned 10 points!",
                         "Beautifully done! Correct! Ten more points!",
                         "You got it! Correct! That's ten points!")
        wrong_lines = ("Nice try!", "That was a tricky one!", "Not quite this time; let's keep going!")
        feedback = (correct_lines[(self.game.index - 1) % len(correct_lines)] if result['correct'] else
                    wrong_lines[(self.game.index - 1) % len(wrong_lines)] +
                    " The correct spelling is " + ", ".join(result['word'].upper()) + ".")
        if result['correct'] and len(self.game.results) >= 3 and all(r['correct'] for r in self.game.results[-3:]):
            feedback += " Three in a row! You're on a roll!"
        if self.game.finished:
            self.transition(Phase.GAME_OVER)
            return feedback + " " + self.score() + " Say play again for a fresh challenge."
        self.transition(Phase.NEXT_WORD)
        return feedback + " " + self.ask_word()

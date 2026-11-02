"""Conservative parsing: never consult the answer to repair recognition."""
import re
from dataclasses import dataclass

ALIASES = dict(zip(
    "ay bee see dee ee ef gee aitch eye jay kay el em en oh pee cue ar ess tee you vee doubleyou ex why zee zed".split(),
    "A B C D E F G H I J K L M N O P Q R S T U V W X Y Z Z".split(),
))
# Common textual renderings of spoken letter names (not target-based repairs).
ALIASES.update({"be": "B", "cee": "C", "eff": "F", "jee": "G", "haitch": "H",
                "ell": "L", "emm": "M", "enn": "N", "pea": "P", "queue": "Q",
                "ess": "S", "tea": "T"})
# NATO words let a player disambiguate similar-sounding letters explicitly.
NATO = dict(zip("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu".split(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
COMMANDS = {
    "repeat": {"repeat", "repeat the word", "say it again"},
    "hint": {"hint", "give me a hint", "definition", "give me a definition", "what does it mean"},
    "submit": {"i'm done", "im done", "i am done", "done", "submit", "submit answer", "finished", "that's my answer"},
    "clear": {"clear", "start over", "change my answer", "retry", "let me try again", "no"},
    "undo": {"undo", "delete last letter"},
    "confirm": {"yes", "correct", "confirm", "that's right"},
    "start": {"start game", "let's start", "i'm ready"},
    "replay": {"play again", "new game"},
    "easy": {"easy", "easy mode"},
    "medium": {"medium", "medium mode"},
    "hard": {"hard", "hard mode"},
    "sentence": {"use it in a sentence", "example sentence"},
    "score": {"what's my score", "what is my score", "my score"},
    "next": {"next word"},
    "end": {"end game", "stop game"},
}

# Natural requests remain deterministic; no model is needed for these.
COMMANDS['repeat'].update({'can you repeat that', 'can you repeat the word', 'could you repeat the word', 'wait can you repeat the word', 'wait, can you repeat the word'})
COMMANDS['hint'].update({'what does that mean', 'can you give me a hint', 'can you define it', 'what is the definition'})
COMMANDS['sentence'].update({'can you use it in a sentence', 'could you use it in a sentence'})
COMMANDS['score'].update({'how am i doing', 'can you tell me my score'})
COMMANDS['pause'] = {'pause', 'pause the contest', 'pause game', 'wait', 'give me a moment', 'i need more time'}
COMMANDS['resume'] = {'resume', 'resume the contest', 'continue', 'continue the game', 'okay let me try', 'okay, let me try'}
COMMANDS['rules'] = {'rules', 'what are the rules', 'how do i play', 'explain the rules'}


@dataclass(frozen=True)
class Parsed:
    letters: str = ""
    command: str | None = None
    uncertain: bool = False
    replacement: str | None = None


def parse_spelling(text: str) -> Parsed:
    original = text.strip().replace("’", "'")
    clean = original.lower()
    clean = re.sub(r"[.!?,]+$", "", clean)
    for command, phrases in COMMANDS.items():
        if clean in phrases:
            return Parsed(command=command)
    correction = re.fullmatch(r"(?:replace|change) (?:the )?last letter (?:with|to) (.+)", clean)
    if correction:
        parsed = parse_spelling(correction[1])
        if len(parsed.letters) == 1 and not parsed.uncertain:
            return Parsed(command="replace_last", replacement=parsed.letters)
        return Parsed(uncertain=True)
    # A final completion phrase may accompany letters in one STT result.
    for ending in sorted(COMMANDS["submit"], key=len, reverse=True):
        if clean.endswith(" " + ending):
            parsed = parse_spelling(original[:len(clean)-len(ending)].strip(" ,.-"))
            return Parsed(parsed.letters, "submit", parsed.uncertain)
    clean = clean.replace("double you", "doubleyou").replace("double u", "doubleyou").replace("x-ray", "xray")
    def repeated_letter(match):
        count, token = match.groups()
        letter = token.upper() if len(token) == 1 else (ALIASES | NATO).get(token)
        return " ".join([letter.lower()] * (2 if count == "double" else 3)) if letter else match[0]
    clean = re.sub(r"\b(double|triple)\s+([a-z]+)\b", repeated_letter, clean)
    # Treat "A for apple" as A only when both pieces agree. Never guess.
    ambiguous = False
    def phonetic(match):
        nonlocal ambiguous
        letter, example = match.group(1), match.group(2)
        value = letter.upper() if len(letter) == 1 else (ALIASES | NATO).get(letter)
        if not value or example[0].upper() != value:
            ambiguous = True
        return value.lower() if value else "unknown"
    clean = re.sub(r"\b([a-z]+) (?:for|as in) ([a-z]+)\b", phonetic, clean)
    if ambiguous:
        return Parsed(uncertain=True)
    tokens = re.findall(r"[a-z]+", clean)
    if not tokens:
        return Parsed(uncertain=True)
    letters = []
    for token in tokens:
        if len(token) == 1:
            letters.append(token.upper())
        elif token in ALIASES or token in NATO:
            letters.append((ALIASES | NATO)[token])
        else:
            # Accept visibly spelled compact uppercase sequences, not ordinary words.
            if re.fullmatch(r"[A-Z][A-Z\s,.!?-]*", original):
                return Parsed("".join(re.findall(r"[A-Z]", original)), uncertain=True)
            return Parsed(uncertain=True)
    return Parsed("".join(letters))


def normalize_spelling(text: str) -> str:
    return re.sub(r"[\s-]", "", text).upper()

"""Extract a spoken name without repeating the player's introduction."""
import re


def extract_name(text: str) -> str:
    name = text.strip().replace("’", "'")
    name = re.sub(r"^(?:hi|hello|hey)(?:\s+there)?\b[\s,!.:-]*", "", name, flags=re.I)
    name = re.sub(r"^(?:my\s+name\s+is|my\s+name's|i\s+am|i'm|this\s+is|you\s+can\s+call\s+me|call\s+me)\b[\s,:-]*", "", name, flags=re.I)
    # Keep multi-part names, apostrophes and hyphens; remove sentence punctuation.
    return re.sub(r"\s+", " ", name).strip(" \t\n.,!?;:\"")[:40]

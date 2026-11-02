"""Words stay on the server until a round has been graded."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Word:
    text: str
    definition: str

    @property
    def sentence(self):
        return SENTENCES[self.text]

WORD_BANK = {
    "easy": [Word(*w) for w in [
        ("cat", "A small pet that meows."), ("sun", "The star that lights our day."),
        ("book", "Pages bound together for reading."), ("fish", "An animal that lives in water and has gills."),
        ("tree", "A tall plant with a trunk."), ("milk", "A drink produced by mammals."),
        ("bird", "An animal with feathers."), ("rain", "Water falling from clouds."),
        ("frog", "An amphibian that hops."), ("star", "A glowing object in the night sky.")]],
    "medium": [Word(*w) for w in [
        ("beautiful", "Very pleasing to look at."), ("elephant", "A large mammal with a trunk."),
        ("garden", "A place where flowers and vegetables grow."), ("journey", "A trip from one place to another."),
        ("library", "A place to borrow books."), ("mountain", "A very high natural landform."),
        ("bicycle", "A vehicle with two wheels and pedals."), ("weather", "The condition of the atmosphere."),
        ("dolphin", "An intelligent marine mammal."), ("umbrella", "Something held overhead to keep rain off.")]],
    "hard": [Word(*w) for w in [
        ("accommodate", "To provide space or lodging."), ("conscientious", "Careful to do work thoroughly and well."),
        ("rhythm", "A repeated pattern of sounds or movements."), ("miscellaneous", "Of various different kinds."),
        ("pronunciation", "The way a word is spoken."), ("entrepreneur", "Someone who starts a business."),
        ("maintenance", "Work to keep something in good condition."), ("questionnaire", "A written set of survey questions."),
        ("perseverance", "Continued effort despite difficulty."), ("silhouette", "A dark outline against a light background.")]],
}

SENTENCES = {
    "cat": "The cat slept beside the window.",
    "sun": "The sun warmed our faces.",
    "book": "She borrowed a book from the library.",
    "fish": "A fish swam beneath the boat.",
    "tree": "We rested beneath a tall tree.",
    "milk": "He poured milk into his cereal.",
    "bird": "A bird landed on the fence.",
    "rain": "The rain filled the puddles.",
    "frog": "A frog jumped into the pond.",
    "star": "One bright star appeared in the sky.",
    "beautiful": "The garden looked beautiful in spring.",
    "elephant": "The elephant lifted its trunk.",
    "garden": "We planted carrots in the garden.",
    "journey": "Our journey began early in the morning.",
    "library": "The library has a quiet reading room.",
    "mountain": "Snow covered the mountain.",
    "bicycle": "She rode her bicycle to school.",
    "weather": "The weather was perfect for a picnic.",
    "dolphin": "A dolphin leaped beside the boat.",
    "umbrella": "I opened my umbrella when it began to rain.",
    "accommodate": "This room can accommodate six guests.",
    "conscientious": "The conscientious student checked every answer.",
    "rhythm": "We clapped along to the rhythm.",
    "miscellaneous": "The drawer contained miscellaneous tools.",
    "pronunciation": "She practiced the pronunciation of the new word.",
    "entrepreneur": "The entrepreneur opened a small bakery.",
    "maintenance": "The bridge needs regular maintenance.",
    "questionnaire": "Please complete the questionnaire after the lesson.",
    "perseverance": "His perseverance helped him finish the race.",
    "silhouette": "We saw her silhouette against the sunset.",
}

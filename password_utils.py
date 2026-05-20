import random
import secrets

WORDS1 = [
    "big",
    "small",
    "large",
    "little",
    "full",
    "empty",
    "good",
    "nice",
    "fine",
    "easy",
    "hard",
    "strong",
    "clean",
    "new",
    "bright",
    "wet",
    "dry",
    "fast",
    "quick",
    "early",
    "quiet",
    "happy",
    "glad",
    "kind",
    "nice",
    "polite",
    "brave",
    "funny",
    "serious",
    "honest",
    "black",
    "white",
    "red",
    "blue",
    "green",
    "yellow",
    "tall",
    "short",
    "long",
    "tiny",
]

WORDS2 = [
    "river",
    "forest",
    "mountain",
    "ocean",
    "koala",
    "wattle",
    "sunrise",
    "galaxy",
    "comet",
    "Tiger",
    "Lion",
    "Elephant",
    "Dog",
    "Cat",
    "Bird",
    "Fish",
    "Bear",
    "Whale",
    "Kangaroo",
    "Koala",
    "Wombat",
    "Platypus",
    "Echidna",
    "Quokka",
    "Wallaby",
    "Dingo",
    "Emu",
    "Lion",
    "Tiger",
    "Bear",
    "Zebra",
    "Giraffe",
    "Monkey",
    "Wolf",
    "Panda",
    "Kangaroo",
    "Hippo",
    "Deer",
    "Fox",
    "Eagle",
    "Owl",
    "Parrot",
    "Sparrow",
    "Penguin",
    "Crow",
    "Duck",
    "Pigeon",
]


def _pick_word1() -> str:
    word = secrets.choice(WORDS1)
    return word.capitalize()


def _pick_word2() -> str:
    word = random.choice(WORDS2)
    return word.capitalize()


def generate_kid_password() -> str:
    """Generate a kid-friendly password."""
    w1 = _pick_word1()
    w2 = _pick_word2()
    # num = random.randint(1, 99)
    num = secrets.randbelow(99) + 1
    return f"{w1}{w2}{num:02d}?"


def generate_adult_password() -> str:
    """Generate a stronger temporary password for adults/staff."""
    import string

    letters = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    digits = "23456789"
    specials = "?@#%+=_"
    alphabet = letters + digits + specials

    while True:
        raw = "".join(secrets.choice(alphabet) for _ in range(14))
        if (
            any(ch in string.ascii_uppercase for ch in raw)
            and any(ch in string.ascii_lowercase for ch in raw)
            and any(ch in digits for ch in raw)
            and any(ch in specials for ch in raw)
        ):
            return f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}{raw[12:]}"


def generate_password(kind: str = "kid") -> str:
    kind = (kind or "kid").strip().lower()

    if kind in {"kid", "child", "student", "school"}:
        return generate_kid_password()

    if kind in {"adult", "staff", "strong"}:
        return generate_adult_password()

    raise ValueError(f"Unknown password kind: {kind!r}")


def generate_username(given_name: str, family_name: str) -> str:
    """Generate a username using given name plus first letter of family name."""
    given = "".join(ch for ch in given_name.strip().lower() if ch.isalpha())
    family = "".join(ch for ch in family_name.strip().lower() if ch.isalpha())
    family_part = family[:1] if len(family) >= 2 else family
    return f"{given}{family_part}"

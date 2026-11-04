"""Deterministic, non-destructive Persian preprocessing without model downloads."""

import re
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from hazm import WordTokenizer

Profile = Literal["lexical", "semantic"]
SocialPolicy = Literal["keep", "strip", "remove"]
ZWNJPolicy = Literal["preserve", "space", "remove"]

ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"})
_DIACRITICS = re.compile("[\u064b-\u0652\u0670]")
_URL = re.compile(r"(?i)(?:https?://|www\.)[^\s<>\"«»،؛؟]+")
_URL_TRAILING = ".,;:!?"
_SOCIAL = re.compile(r"(?<![\w@])(?P<marker>[#@])(?P<body>[\w\u200c]+)")
_NUMBER = r"(?<!\w)[+\-−]?\d+(?:[/.٫٬,:\-]\d+)*(?:[%٪])?"
_PROTECTED = re.compile(
    rf"{_URL.pattern}|(?<![\w@])[#@][\w\u200c]+|{_NUMBER}", re.IGNORECASE
)
_WORD_OR_PUNCT = re.compile(r"[\w\u200c\u064b-\u0652\u0670]+|[^\w\s]")
DEFAULT_STOPWORDS = frozenset(
    {"از", "به", "با", "برای", "در", "را", "و", "یا", "این", "آن"}
)
_NEGATIONS = frozenset(
    {"نه", "نیست", "نیستند", "نبود", "نبودند", "بدون", "هرگز", "عدم", "غیر", "بی"}
)
_NEGATIVE_PREFIXES = (
    "نمی",
    "نخواهد",
    "نخواه",
    "نشد",
    "نشده",
    "نکن",
    "نکرد",
    "ندارد",
    "نداشت",
)


@dataclass(frozen=True)
class PreprocessingOptions:
    unicode_form: Literal["NFC", "NFKC"] | None = "NFKC"
    normalize_arabic_letters: bool = True
    normalize_whitespace: bool = True
    zwnj: ZWNJPolicy = "preserve"
    remove_formatting: bool = True
    remove_diacritics: bool = True
    remove_tatweel: bool = True
    urls: Literal["keep", "remove"] = "remove"
    hashtags: SocialPolicy = "strip"
    mentions: SocialPolicy = "remove"
    keep_punctuation: bool = False
    remove_stopwords: bool = False
    stopwords: frozenset[str] = DEFAULT_STOPWORDS
    tokenizer: Literal["builtin", "hazm"] = "builtin"

    def __post_init__(self) -> None:
        choices = {
            "unicode_form": {None, "NFC", "NFKC"},
            "zwnj": {"preserve", "space", "remove"},
            "urls": {"keep", "remove"},
            "hashtags": {"keep", "strip", "remove"},
            "mentions": {"keep", "strip", "remove"},
            "tokenizer": {"builtin", "hazm"},
        }
        for name, allowed in choices.items():
            if getattr(self, name) not in allowed:
                raise ValueError(f"Invalid preprocessing option: {name}.")
        if isinstance(self.stopwords, str) or any(
            not isinstance(word, str) or not word.strip() for word in self.stopwords
        ):
            raise ValueError("stopwords must contain nonempty strings.")
        object.__setattr__(self, "stopwords", frozenset(self.stopwords))

    @classmethod
    def for_profile(cls, profile: Profile, **overrides) -> "PreprocessingOptions":
        if profile == "lexical":
            options = cls()
        elif profile == "semantic":
            options = cls(
                unicode_form="NFC",
                remove_diacritics=False,
                urls="keep",
                hashtags="keep",
                mentions="keep",
                keep_punctuation=True,
            )
        else:
            raise ValueError("profile must be 'lexical' or 'semantic'.")
        return replace(options, **overrides)


@dataclass(frozen=True)
class PreprocessedText:
    original_text: str | None
    normalized_text: str
    tokens: tuple[str, ...]
    urls: tuple[str, ...]
    profile: Profile
    tokenizer: str


def _clean_controls(text: str) -> str:
    result = []
    for character in text:
        category = unicodedata.category(character)
        if character == "\u200b":  # A word boundary, never glue adjacent words.
            result.append(" ")
        elif character in {"\u200c", "\u200d"}:
            result.append(character)  # Keep half-spaces and emoji joiners.
        elif category in {"Cc", "Cs"}:
            result.append(" ")
        elif category != "Cf":
            result.append(character)
    return "".join(result)


def _trim_url(value: str) -> str:
    """Exclude sentence punctuation, preserving balanced parentheses in URLs."""
    while value:
        if value[-1] in _URL_TRAILING:
            value = value[:-1]
        elif value[-1] in ")]}":
            opening = {")": "(", "]": "[", "}": "{"}[value[-1]]
            if value.count(value[-1]) <= value.count(opening):
                break
            value = value[:-1]
        else:
            break
    return value


@lru_cache(maxsize=1)
def _hazm_tokenizer() -> "WordTokenizer":
    try:
        from hazm import WordTokenizer
    except ImportError:
        raise ValueError(
            "Hazm tokenizer requires Python 3.12–3.13 and the 'persian' extra: "
            "pip install -e '.[persian]'"
        ) from None
    return WordTokenizer(
        join_verb_parts=False,
        replace_links=False,
        replace_ids=False,
        replace_numbers=False,
        replace_hashtags=False,
    )


def _tokens(text: str, backend: str) -> list[str]:
    """Protect dates, signed numbers, URLs and social identifiers before splitting."""
    split = (
        _WORD_OR_PUNCT.findall if backend == "builtin" else _hazm_tokenizer().tokenize
    )
    tokens = []
    end = 0
    for match in _PROTECTED.finditer(text):
        tokens.extend(split(text[end : match.start()]))
        value = match.group()
        if value.lower().startswith(("http://", "https://", "www.")):
            url = _trim_url(value)
            tokens.append(url)
            tokens.extend(split(value[len(url) :]))
        else:
            tokens.append(value)
        end = match.end()
    tokens.extend(split(text[end:]))
    return tokens


def _protected_from_stopwords(token: str) -> bool:
    compact = token.replace("\u200c", "")
    return (
        any(character.isdigit() for character in token)
        or compact in _NEGATIONS
        or compact.startswith(_NEGATIVE_PREFIXES)
        or token.startswith(("#", "@", "http://", "https://", "www."))
    )


class PersianPreprocessor:
    def __init__(
        self, profile: Profile = "lexical", options: PreprocessingOptions | None = None
    ) -> None:
        if profile not in {"lexical", "semantic"}:
            raise ValueError("profile must be 'lexical' or 'semantic'.")
        self.profile = profile
        self.options = options or PreprocessingOptions.for_profile(profile)

    def process(self, text: str | None) -> PreprocessedText:
        if text is not None and not isinstance(text, str):
            raise TypeError("Text must be a string or None; decode bytes explicitly.")
        original = text
        text = text or ""
        options = self.options
        text = _clean_controls(text) if options.remove_formatting else text
        # Extract before normalization so URLs retain their original spelling.
        urls = tuple(_trim_url(match.group()) for match in _URL.finditer(text))
        kept_urls: dict[str, str] = {}
        placeholder = "PNSURLTOKEN"
        collision_text = (
            unicodedata.normalize(options.unicode_form, text)
            if options.unicode_form
            else text
        )
        while placeholder in collision_text:
            placeholder += "X"

        def protect_url(match: re.Match[str]) -> str:
            value = _trim_url(match.group())
            marker = f"{placeholder}{len(kept_urls)}END"
            kept_urls[marker] = value
            return marker + match.group()[len(value) :]

        if options.urls == "remove":
            text = _URL.sub(
                lambda match: " " + match.group()[len(_trim_url(match.group())) :],
                text,
            )
        else:
            text = _URL.sub(protect_url, text)
        if options.unicode_form:
            text = unicodedata.normalize(options.unicode_form, text)
        if options.normalize_arabic_letters:
            text = text.translate(ARABIC_TO_PERSIAN)
        if options.remove_diacritics:
            text = _DIACRITICS.sub("", text)
        if options.remove_tatweel:
            text = text.replace("ـ", "")

        def social(match: re.Match[str]) -> str:
            policy = options.hashtags if match["marker"] == "#" else options.mentions
            if policy == "keep":
                return match.group()
            return match["body"] if policy == "strip" else " "

        # URLs stay protected until normalization and social handling finish.
        text = _SOCIAL.sub(social, text)
        if options.zwnj == "space":
            text = text.replace("\u200c", " ")
        elif options.zwnj == "remove":
            text = text.replace("\u200c", "")
        else:
            text = re.sub("\u200c+", "\u200c", text)
            text = re.sub(
                r"(?<![\w\u064b-\u0652\u0670])\u200c|"
                r"\u200c(?![\w\u064b-\u0652\u0670])",
                "",
                text,
            )
        if options.normalize_whitespace:
            text = " ".join(text.split())
        for marker, url in kept_urls.items():
            text = text.replace(marker, url)
        tokens = _tokens(text, options.tokenizer)
        if not options.keep_punctuation:
            tokens = [token for token in tokens if any(c.isalnum() for c in token)]
        if options.remove_stopwords:
            stopwords = {
                word.translate(ARABIC_TO_PERSIAN) for word in options.stopwords
            }
            tokens = [
                token
                for token in tokens
                if token not in stopwords or _protected_from_stopwords(token)
            ]
        return PreprocessedText(
            original, text, tuple(tokens), urls, self.profile, options.tokenizer
        )


def preprocess_text(text: str | None, profile: Profile = "lexical") -> PreprocessedText:
    return PersianPreprocessor(profile).process(text)

# Persian preprocessing (Phase 1.2)

The pipeline is independent of Telegram, SQLAlchemy and SQLite. It accepts a
string or `None` and returns an immutable `PreprocessedText` with
`original_text`, `normalized_text`, ordered `tokens`, extracted `urls`, profile
and tokenizer name. The original value is retained verbatim. No database field
is updated and collection still stores original text.

## Profiles

| Operation | `lexical` | `semantic` |
| --- | --- | --- |
| Unicode normalization | NFKC | NFC |
| Arabic letters | `ي`/`ى` → `ی`, `ك` → `ک` | Same |
| Whitespace | Collapse Unicode whitespace and strip edges | Same |
| Half-space / ZWNJ | Preserve internal U+200C; collapse repeats and remove dangling marks | Same |
| Formatting | Remove bidi/BOM/control noise; zero-width space becomes a boundary | Same |
| Arabic vowel marks | Remove U+064B–U+0652 and U+0670 | Preserve |
| Tatweel / kashida | Remove | Remove |
| URLs | Extract and remove from normalized text | Extract and keep original URL spelling |
| Hashtags | Strip `#`, keep body and underscores | Keep |
| Mentions | Remove | Keep |
| Punctuation in tokens | Exclude punctuation-only tokens | Keep |
| Stopwords | Disabled | Disabled |
| Stem/lemma/verb joining | Disabled | Disabled |

For future lexical analysis, use `tokens`; for multilingual embeddings, use
`normalized_text`. Stopword filtering and punctuation filtering affect the token
list, not normalized prose. Neither profile translates, rounds, masks or unifies
ordinary ASCII/Persian/Arabic-Indic digits. Thus dates, signed numbers, time
values, decimal separators and percent values remain explicit. NFKC may change
compatibility characters (such as full-width digits); use NFC for stricter
character preservation.

Names and locations are not stemmed or removed by default. Negative verbs are
never lemmatized into positive roots. A small, explicit stopword set contains
only `از به با برای در را و یا این آن`. Optional filtering protects numeric
tokens and common negations/negative verb prefixes, including `نه`, `نیست`,
`هرگز`, `بدون`, `عدم`, `نمی...`, `نخواهد...`, `نشد...` and `نکرد...`.
It does not make arbitrary custom stopword lists linguistically safe: do not
put meaningful names, locations or unlisted negative forms in your custom list.

Control cleaning preserves U+200D for emoji sequences and U+200C for Persian
half-spaces. Invalid surrogate code points and C0/C1 controls become word
boundaries. Other formatting controls are dropped. No missing half-spaces are
invented and no dictionary-driven spelling/spacing correction is applied.

## Python API

```python
from news_similarity.preprocessing import (
    PersianPreprocessor,
    PreprocessingOptions,
    preprocess_text,
)

result = preprocess_text("علي در كاشان نمی‌رود؛ تاریخ ۱۴۰۵/۰۷/۱۰ است.")
assert result.original_text.startswith("علي")
assert "نمی‌رود" in result.tokens
assert "۱۴۰۵/۰۷/۱۰" in result.tokens

options = PreprocessingOptions.for_profile(
    "lexical",
    zwnj="preserve",
    hashtags="keep",
    mentions="strip",
    remove_stopwords=True,
)
result = PersianPreprocessor("lexical", options).process("در قم خبری نیست.")
```

All operations are configurable with `PreprocessingOptions`; set `unicode_form`
to `None` to disable Unicode normalization. `zwnj` accepts `preserve`, `space`
or `remove`; the latter two are explicit user choices that can change token
boundaries. Social policies accept `keep`, `strip` (marker only) or `remove`.
URLs accept `keep` or `remove`, and are always extracted in encounter order,
including repeats. Custom stopwords are copied into a frozen set.

`None`, an empty string or formatting-only text produces no content tokens.
Other input types raise a clear `TypeError`, rather than silently converting
bytes, numbers or containers into news text. Decode bytes explicitly first.

## Tokenization and Hazm

The default `builtin` tokenizer is deterministic and dependency-free. It keeps
half-space words together and protects dates, times, signed/decimal/grouped
numbers, URL spans, hashtags and mentions before splitting punctuation.

The optional, explicitly selected `hazm` backend uses Hazm 0.12.1's
`WordTokenizer(join_verb_parts=False)`, with link/number/ID replacement disabled.
The same protected spans bypass Hazm so that its numeric/punctuation splitting
does not fragment dates or convert numerical evidence into placeholders.
It uses local resources only. No tagger, lemmatizer, embeddings, transformers,
model downloads or NLTK corpus downloads are invoked.

Hazm 0.12.1 requires Python 3.12–3.13 according to its
[release metadata](https://pypi.org/project/hazm/0.12.1/). Keeping it optional
preserves the core application's Python 3.11+ support. Its
[tokenizer implementation](https://github.com/roshan-research/hazm/blob/v0.12.1/hazm/word_tokenizer.py)
documents the verb-joining and replacement switches used here. The default
Hazm normalizer is not applied because this phase needs explicit control over
spacing, numeric spelling and other changes.

Select a backend explicitly and record it with any future experiment. There
is no automatic backend switching based on which package happens to be installed.
The two backends can differ on unprotected punctuation and mixed-script text.

## CLI and reproduction

From Windows PowerShell in the project directory:

```powershell
.\.venv\Scripts\python.exe -m news_similarity.cli preprocess --text 'كاشان در ۱۴۰۵/۰۷/۱۰؛ تعطیل نیست.'
.\.venv\Scripts\python.exe -m news_similarity.cli preprocess --profile semantic --text 'خَبَر #خبر_فوری @news'
.\.venv\Scripts\python.exe -m news_similarity.cli preprocess --text '#خبر @news' --hashtags strip --mentions remove --remove-stopwords
.\.venv\Scripts\python.exe -m pip install -e '.[dev,persian]'
.\.venv\Scripts\python.exe -m news_similarity.cli preprocess --tokenizer hazm --text 'منفی -۵؛ ساعت ۱۰:۳۰'
.\.venv\Scripts\python.exe -m pytest tests/test_preprocessing.py tests/test_preprocessing_cli.py -q
```

The CLI also exposes `--zwnj` and `--urls`. Neither new command reads `.env` or
opens SQLite, even when database or Telegram environment settings are invalid.

## Limits

This is deterministic surface preprocessing, not linguistic understanding or
entity recognition. It cannot resolve ambiguous names, infer dates, verify
facts, detect sarcasm or determine whether negation changes a real event.
URL extraction covers HTTP(S) and `www.` forms with heuristic punctuation
boundaries, not arbitrary RFC-valid URLs, bare domains or HTML parsing. Do not
use it as a security validator. Explicit social/ZWNJ/diacritic settings may
discard information; the original text remains available.

Record Python's Unicode database version, options and backend when comparing
experiments across runtimes. Exact output is deterministic for the same input,
configuration and dependency/runtime versions, not promised across future
Unicode or Hazm releases.

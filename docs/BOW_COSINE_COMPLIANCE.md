# Bag of Words + Cosine Similarity compliance review

Date: 2026-11-05. Requirement reviewed: **count-based Bag of Words + Cosine
Similarity**, with strict compatibility for existing models and application flows.

## Findings before this addition

No `CountVectorizer` or true raw-count BoW similarity baseline existed in the
production package. The word and character implementations used
`TfidfVectorizer`, with sublinear term-frequency/IDF weighting and L2 normalization.
That is a weighted vector-space model and does not by itself meet the explicit
raw-count baseline requirement.

Cosine similarity already existed in these exact places:

| Implementation | Location and calculation |
| --- | --- |
| Word/character TF-IDF vectorization | `src/news_similarity/tfidf.py`, `TfidfConfig.vectorizer`: word or `char_wb` analyzer, `smooth_idf=True`, `norm="l2"` |
| Word/character TF-IDF similarity | Same file, `TfidfSimilarity.compare_batch`: `left.multiply(right).sum(axis=1)` equals cosine because each nonzero row has unit L2 norm; zero/OOV rows score 0 |
| MiniLM vectorization | `src/news_similarity/semantic.py`, `SemanticSimilarity.encode`: `normalize_embeddings=True`, followed by explicit normalization using `np.linalg.norm` |
| MiniLM cosine | Same file, `SemanticSimilarity.compare_batch`: `np.sum(values[::2] * values[1::2], axis=1)`, clipped to [-1,1] |
| Hybrid | `src/news_similarity/hybrid.py`, `fused_score`/`assess_scores`: existing weighted fusion of component scores and event-evidence penalty/rules; the hybrid output is not itself a raw count cosine |

These implementations, weights, thresholds, artifacts and behavior are unchanged.

## Isolated additive implementation

`src/news_similarity/bow.py` adds `BagOfWordsSimilarity`:

- Reuses the existing `preprocess_text(..., "lexical")` output without modifying
  preprocessing. Uses its builtin tokenization and joined tokens.
- Creates a fresh `CountVectorizer` for each pair with `tokenizer=str.split`,
  `token_pattern=None`, `lowercase=False`, `ngram_range=(1,1)`, `binary=False`.
- `fit_transform` produces two integer frequency rows on the vocabulary union.
  There is no IDF transform, learned model artifact, binary presence conversion,
  event rule, or new classification threshold.
- Calls scikit-learn `cosine_similarity(counts[0], counts[1])` explicitly.
  Floating-point round-off is bounded to the mathematical [0,1] count-cosine range.
- `compare` returns the real scalar score. `analyze` also returns vocabulary and
  both original integer count rows for an inspectable demonstration.
- Empty/zero vectors score 0 by documented convention. Core `None` inputs are
  empty; malformed non-string inputs raise `TypeError`. Existing UI input limits
  and empty-text validation remain unchanged.
- Pair-local vocabulary construction does not fit or alter any saved model or
  evaluate/tune on either labeled dataset. No quality claims are made.

The README provides the count-vector definition, cosine equation, a worked
Persian example (0.5), and a frequency-sensitive example (0.8).

## Streamlit integration and compatibility

The only modified existing Python file is
`src/news_similarity/ui/pages/comparison.py`. A method selector is added inside
the existing comparison-action area; the page columns, navigation, news panels,
theme and existing Hybrid result renderer are unchanged. The first/default
method is **Hybrid**. No existing method-selection behavior was replaced.

New UI modules handle only the opt-in baseline:

- `ui/services/bow_comparison.py` reuses existing read/validation interfaces and
  checks cross-platform/different-record constraints. Existing facade comparison
  methods are untouched. The BoW implementation is imported only when invoked.
- `ui/components/bow_result.py` uses existing result CSS/container conventions,
  clearly labels **Bag of Words + Cosine Similarity**, displays the actual cosine,
  and exposes the count vectors/JSON. It does not inject a fake Hybrid score,
  event decision, evidence or threshold.

Stored and manual BoW results use separate session keys from Hybrid. A method
change does not trigger inference. News/method selection survives in-app
navigation. Switching back restores the existing Hybrid result without rerunning
or changing its models. Stored pair fingerprints prevent displaying a cached BoW
result for different texts. Neither path changes collection or acknowledgements.

## Files created or modified

Created:

- `src/news_similarity/bow.py`
- `src/news_similarity/ui/services/bow_comparison.py`
- `src/news_similarity/ui/components/bow_result.py`
- `tests/test_bow.py`
- `tests/test_ui_bow.py`
- `docs/BOW_COSINE_COMPLIANCE.md`

Modified:

- `src/news_similarity/ui/pages/comparison.py`: opt-in method dispatch only.
- `README.md`: method instructions and presentation-ready mathematics.

No existing regression test is edited. No dependency is added; scikit-learn is
already installed as a project dependency. The existing TF-IDF, MiniLM, Hybrid,
preprocessing, collectors, database schema, news records, model resources,
thresholds, dataset and evaluation artifacts are not modified.

## Verification

New tests cover identical, partial-overlap and unrelated Persian texts, repeated
word counts, empty/zero vectors, character variants, deterministic per-call
vocabulary, manual/stored UI score binding, default Hybrid selection, zero Hybrid
inference in BoW mode, strict record guards and session/method isolation.

Focused tests: **60 passed in 14.18 seconds**, including existing UI regressions.
Complete suite: **720 passed in 56.43 seconds**, including all prior 709 cases
unchanged and 11 new cases, with the existing cached MiniLM integration test
enabled in offline mode. No test was skipped in that run.

Ruff lint passed; Ruff formatting reported **121 files already formatted**.
Dependency validation reported **No broken requirements found**.

The pre-change SHA-256 snapshot confirms **121 existing source, test, data and
artifact files unchanged**. The only changed pre-existing Python file is the
comparison page for the method selector/dispatch. Existing tests, collectors,
SQLite data/schema, preprocessing, TF-IDF/MiniLM/Hybrid implementations, freezes
and evaluation artifacts match their previous hashes. No live API calls or
database writes were performed.

To demonstrate, launch normally:

```powershell
Set-Location -LiteralPath 'D:\University\داده کاوی\PersianNewsSimilarity'
.\.venv\Scripts\python.exe -m streamlit run src/news_similarity/ui/app.py
```

Choose **Bag of Words + Cosine Similarity** under **روش مقایسه**, then compare.
Hybrid remains the default. No collector or live API operation is needed.

## Compliance conclusion

The professor's stated computational requirement is implemented directly and
inspectably: **raw word counts from CountVectorizer + explicit cosine_similarity**.
Existing model behavior and defaults are preserved. This satisfies that stated
baseline requirement; it is not a claim that BoW reliably identifies news events
or fulfills any additional unstated grading criterion.

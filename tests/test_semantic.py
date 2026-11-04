import os
from dataclasses import asdict

import numpy as np
import pytest

from news_similarity.semantic import (
    SemanticConfig,
    SemanticModelError,
    SemanticSimilarity,
)


class FakeEncoder:
    max_seq_length = 128

    def __init__(self):
        self.calls = []

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, sentences, **kwargs):
        self.calls.append((list(sentences), kwargs))
        values = {"الف": [3.0, 0.0, 0.0], "ب": [0.0, 4.0, 0.0], "ج": [-2.0, 0.0, 0.0]}
        return np.array([values.get(text, [1.0, 1.0, 1.0]) for text in sentences])


@pytest.fixture
def semantic_model():
    encoder = FakeEncoder()
    calls = []

    def factory(config):
        calls.append(asdict(config))
        return encoder, "cpu", "mocked-local-cache"

    model = SemanticSimilarity(factory=factory)
    return model, encoder, calls


def test_lazy_loading_and_embedding_normalization(semantic_model):
    model, encoder, calls = semantic_model
    assert calls == []
    values = model.encode(["الف", "ب", "الف"])
    np.testing.assert_allclose(np.linalg.norm(values, axis=1), 1)
    assert len(calls) == 1
    assert encoder.calls[0][0] == ["الف", "ب"]
    assert encoder.calls[0][1]["normalize_embeddings"] is True
    assert model.encode([]).shape == (0, 3)
    values[0] *= 10
    assert model.compare("الف", "الف") == pytest.approx(1)
    assert len(encoder.calls) == 1


@pytest.mark.parametrize("text", ["", " \n", None, "\ufeff\u200b"])
def test_empty_inputs_rejected_before_loading(semantic_model, text):
    model, _, calls = semantic_model
    with pytest.raises(ValueError, match="nonempty"):
        model.compare(text, "الف")
    assert calls == []


def test_batch_negative_cosines_and_ranking(semantic_model):
    model, _, _ = semantic_model
    assert model.compare_batch(
        [("الف", "الف"), ("الف", "ب"), ("الف", "ج")]
    ) == pytest.approx([1, 0, -1])
    assert model.compare_batch([]) == []
    ranked = model.rank("الف", ["ج", "ب", "الف", "الف"])
    assert [row.index for row in ranked] == [2, 3, 1, 0]
    assert len(model.rank("الف", ["الف", "ب"], 1)) == 1
    assert model.rank("الف", []) == []


def test_small_lru_batch_does_not_lose_evicted_rows():
    encoder = FakeEncoder()
    model = SemanticSimilarity(
        SemanticConfig(embedding_cache_size=1),
        factory=lambda _: (encoder, "cpu", "test"),
    )
    assert model.compare_batch([("الف", "ب"), ("ج", "الف")]) == pytest.approx([0, -1])
    assert model.compare("الف", "الف") == pytest.approx(1)


def test_semantic_profile_preserves_prose_entities_dates_and_negation(semantic_model):
    model, encoder, _ = semantic_model
    raw = "علي در كاشان نمی‌رود؛ ۱۴۰۵/۰۷/۱۰ و ۱۲ نفر!"
    model.encode([raw])
    assert encoder.calls[0][0] == ["علی در کاشان نمی‌رود؛ ۱۴۰۵/۰۷/۱۰ و ۱۲ نفر!"]
    assert raw.startswith("علي")
    metadata = model.metadata()
    assert metadata["embedding_dimension"] == 3
    assert metadata["execution_device"] == "cpu"
    assert metadata["configuration"]["revision"]
    assert metadata["fine_tuned"] is False


def test_model_load_failure_is_safe():
    def fail(_):
        raise OSError("private token 12345")

    with pytest.raises(SemanticModelError, match="loading failed") as caught:
        SemanticSimilarity(factory=fail).compare("الف", "ب")
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "values", [np.zeros((1, 3)), np.array([[float("nan"), 1, 1]]), np.ones((1, 7))]
)
def test_invalid_encoder_output(values):
    encoder = FakeEncoder()
    encoder.encode = lambda *args, **kwargs: values
    with pytest.raises(SemanticModelError):
        SemanticSimilarity(factory=lambda _: (encoder, "cpu", "test")).encode(["الف"])


def test_repeat_inference_within_tolerance(semantic_model):
    model, _, _ = semantic_model
    first = model.compare_batch([("الف", "ب"), ("الف", "الف")])
    np.testing.assert_allclose(
        first, model.compare_batch([("الف", "ب"), ("الف", "الف")]), atol=1e-12
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"device": "mps"},
        {"batch_size": 0},
        {"revision": "main"},
        {"embedding_cache_size": -1},
    ],
)
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        SemanticConfig(**kwargs)


@pytest.mark.semantic_integration
@pytest.mark.skipif(
    os.environ.get("RUN_SEMANTIC_INTEGRATION") != "1",
    reason="Opt in to actual local pretrained inference.",
)
def test_actual_pinned_cpu_model():
    model = SemanticSimilarity()
    text = "این متن آزمایشی فارسی است."
    assert model.compare(text, text) == pytest.approx(1, abs=1e-5)
    assert model.metadata()["execution_device"] == "cpu"
    assert model.metadata()["embedding_dimension"] > 0


def test_loader_reuses_cached_snapshot_and_cuda_falls_back(monkeypatch, tmp_path):
    import sys
    from types import ModuleType, SimpleNamespace

    from news_similarity import semantic

    snapshot = (
        tmp_path
        / ("models--" + semantic.MODEL_ID.replace("/", "--"))
        / "snapshots"
        / semantic.MODEL_REVISION
    )
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(b"test placeholder, never loaded")
    (snapshot / "modules.json").write_text("[]")
    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False),
        float32="float32",
        manual_seed=lambda _: None,
        set_num_threads=lambda _: None,
        use_deterministic_algorithms=lambda _: None,
    )
    encoder = FakeEncoder()
    encoder.eval = lambda: None
    calls = []
    module = ModuleType("sentence_transformers")

    def constructor(path, **kwargs):
        calls.append((path, kwargs))
        return encoder

    module.SentenceTransformer = constructor
    hub = ModuleType("huggingface_hub")
    hub.snapshot_download = lambda *args, **kwargs: pytest.fail(
        "Cached weights must not download."
    )
    constants = ModuleType("huggingface_hub.constants")
    constants.HF_HUB_CACHE = str(tmp_path)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", constants)
    _, device, _ = semantic._load_encoder(SemanticConfig(device="cuda"))
    assert device == "cpu"
    assert calls[0][1]["trust_remote_code"] is False
    assert calls[0][1]["local_files_only"] is True
    assert calls[0][1]["model_kwargs"]["use_safetensors"] is True

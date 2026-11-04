"""Lazy, frozen multilingual sentence embeddings, independent of persistence."""

import hashlib
import re
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import numpy as np

from news_similarity.preprocessing import preprocess_text
from news_similarity.tfidf import preprocessing_fingerprint

MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"


class SemanticModelError(RuntimeError):
    """A safe, actionable model/runtime failure, without private API payloads."""


class Encoder(Protocol):
    max_seq_length: int

    def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray: ...

    def get_sentence_embedding_dimension(self) -> int: ...


@dataclass(frozen=True)
class SemanticConfig:
    model_id: str = MODEL_ID
    revision: str = MODEL_REVISION
    device: str = "cpu"
    batch_size: int = 16
    cache_folder: str | None = None
    local_files_only: bool = True
    embedding_cache_size: int = 4096
    seed: int = 42
    cpu_threads: int = 2

    def __post_init__(self) -> None:
        if self.model_id != MODEL_ID or not re.fullmatch(
            r"[a-f0-9]{40}", self.revision
        ):
            raise ValueError(
                "Use the required model ID and an explicit "
                "40-character commit revision."
            )
        if self.device not in {"cpu", "cuda", "auto"}:
            raise ValueError("Device must be cpu, cuda or auto.")
        if any(
            type(value) is not int or value < 1
            for value in (self.batch_size, self.embedding_cache_size, self.cpu_threads)
        ):
            raise ValueError(
                "Batch size, cache size and CPU thread count must be positive integers."
            )


def _load_encoder(config: SemanticConfig) -> tuple[Encoder, str, str]:
    try:
        import torch
        from huggingface_hub import snapshot_download
        from huggingface_hub.constants import HF_HUB_CACHE
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise SemanticModelError(
            "Install the semantic extra: pip install -e '.[semantic]'."
        ) from None
    device = "cuda" if config.device != "cpu" and torch.cuda.is_available() else "cpu"
    torch.manual_seed(config.seed)
    torch.set_num_threads(config.cpu_threads)
    torch.use_deterministic_algorithms(True)
    repository = "models--" + config.model_id.replace("/", "--")
    candidates = (
        [Path(config.cache_folder)]
        if config.cache_folder
        else [Path(HF_HUB_CACHE), Path("artifacts/semantic/model-cache")]
    )
    snapshot = next(
        (
            root / repository / "snapshots" / config.revision
            for root in candidates
            if (
                root / repository / "snapshots" / config.revision / "model.safetensors"
            ).is_file()
            and (
                root / repository / "snapshots" / config.revision / "modules.json"
            ).is_file()
        ),
        None,
    )
    if snapshot is None:
        if config.local_files_only:
            raise SemanticModelError(
                "Pinned model weights are not cached. Use --allow-download "
                "or provide a valid --cache-folder."
            )
        folder = config.cache_folder or "artifacts/semantic/model-cache"
        snapshot = Path(
            snapshot_download(
                config.model_id,
                revision=config.revision,
                cache_dir=folder,
                token=False,
                allow_patterns=[
                    "*.json",
                    "model.safetensors",
                    "sentencepiece.bpe.model",
                    "1_Pooling/config.json",
                ],
            )
        )
    # Official pinned local files only; never execute custom remote model code.
    model = SentenceTransformer(
        str(snapshot),
        device=device,
        local_files_only=True,
        trust_remote_code=False,
        model_kwargs={"use_safetensors": True, "dtype": torch.float32},
    )
    model.eval()
    return model, device, str(snapshot)


Factory = Callable[[SemanticConfig], tuple[Encoder, str, str]]


@dataclass(frozen=True)
class RankedSimilarity:
    index: int
    text: str
    score: float


class SemanticSimilarity:
    def __init__(
        self, config: SemanticConfig | None = None, *, factory: Factory | None = None
    ) -> None:
        self.config = config or SemanticConfig()
        self._factory = factory or _load_encoder
        self._encoder: Encoder | None = None
        self._dimension: int | None = None
        self._device: str | None = None
        self._snapshot: str | None = None
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self.encoded_documents = 0
        self.load_seconds = 0.0
        self.inference_seconds = 0.0

    @staticmethod
    def prepare(text: str | None) -> str:
        normalized = preprocess_text(text, "semantic").normalized_text
        if not normalized.strip():
            raise ValueError(
                "Semantic inference requires nonempty text after preprocessing."
            )
        return normalized

    def _load(self) -> Encoder:
        if self._encoder is None:
            started = perf_counter()
            try:
                encoder, device, snapshot = self._factory(self.config)
                dimension_getter = getattr(encoder, "get_embedding_dimension", None)
                dimension = (
                    dimension_getter()
                    if dimension_getter is not None
                    else encoder.get_sentence_embedding_dimension()
                )
                if not isinstance(dimension, int) or dimension < 1:
                    raise SemanticModelError(
                        "Encoder did not provide a valid embedding dimension."
                    )
                self._encoder, self._device, self._snapshot = encoder, device, snapshot
                self._dimension = dimension
                self.load_seconds = perf_counter() - started
            except SemanticModelError:
                raise
            except (OSError, RuntimeError, ValueError, ImportError) as error:
                raise SemanticModelError(
                    f"Semantic model loading failed ({type(error).__name__}); "
                    "check the pinned cache and runtime."
                ) from None
        return self._encoder

    def encode(self, texts: Sequence[str | None]) -> np.ndarray:
        prepared = [self.prepare(text) for text in texts]
        if not prepared:
            return np.empty((0, self._dimension or 0), dtype=np.float64)
        encoder = self._load()
        unique = list(dict.fromkeys(prepared))
        missing = [text for text in unique if text not in self._cache]
        current: dict[str, np.ndarray] = {}
        if missing:
            started = perf_counter()
            try:
                values = np.asarray(
                    encoder.encode(
                        missing,
                        batch_size=self.config.batch_size,
                        convert_to_numpy=True,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    ),
                    dtype=np.float64,
                )
            except (OSError, RuntimeError, ValueError) as error:
                raise SemanticModelError(
                    f"Semantic inference failed ({type(error).__name__})."
                ) from None
            if (
                values.shape != (len(missing), self._dimension)
                or not np.isfinite(values).all()
            ):
                raise SemanticModelError(
                    "Encoder returned invalid shape or non-finite embeddings."
                )
            norms = np.linalg.norm(values, axis=1, keepdims=True)
            if np.any(norms == 0):
                raise SemanticModelError(
                    "Encoder returned a zero embedding for nonempty text."
                )
            values /= norms
            current.update(zip(missing, values, strict=True))
            self.encoded_documents += len(missing)
            self.inference_seconds += perf_counter() - started
        # Copy cached rows before eviction so a batch larger than the LRU stays correct.
        for text in unique:
            if text in self._cache:
                current[text] = self._cache[text]
        for text in unique:
            self._cache[text] = current[text]
            self._cache.move_to_end(text)
            while len(self._cache) > self.config.embedding_cache_size:
                self._cache.popitem(last=False)
        return np.stack([current[text] for text in prepared]).copy()

    def compare_batch(
        self, pairs: Sequence[tuple[str | None, str | None]]
    ) -> list[float]:
        if not pairs:
            return []
        values = self.encode([text for pair in pairs for text in pair])
        return np.clip(np.sum(values[::2] * values[1::2], axis=1), -1, 1).tolist()

    def compare(self, text_a: str | None, text_b: str | None) -> float:
        return self.compare_batch([(text_a, text_b)])[0]

    def rank(
        self, query: str, collection: Sequence[str], top_k: int | None = None
    ) -> list[RankedSimilarity]:
        self.prepare(query)
        if top_k is not None and (type(top_k) is not int or top_k < 1):
            raise ValueError("top_k must be a positive integer or None.")
        scores = self.compare_batch([(query, text) for text in collection])
        ranked = sorted(
            (
                RankedSimilarity(index, text, score)
                for index, (text, score) in enumerate(
                    zip(collection, scores, strict=True)
                )
            ),
            key=lambda row: (-row.score, row.index),
        )
        return ranked if top_k is None else ranked[:top_k]

    def metadata(self) -> dict[str, Any]:
        self._load()
        runtime = {}
        for name in (
            "sentence-transformers",
            "transformers",
            "torch",
            "numpy",
            "safetensors",
            "tokenizers",
            "huggingface-hub",
        ):
            try:
                runtime[name] = version(name)
            except PackageNotFoundError:
                runtime[name] = "not-installed (injected test encoder)"
        return {
            "configuration": asdict(self.config),
            "runtime": runtime,
            "execution_device": self._device,
            "cuda_fell_back_to_cpu": self.config.device == "cuda"
            and self._device == "cpu",
            "snapshot": self._snapshot,
            "embedding_dimension": self._dimension,
            "max_seq_length": self._encoder.max_seq_length,
            "preprocessing": "semantic profile; normalized prose; no stopword removal",
            "preprocessing_fingerprint": hashlib.sha256(
                (preprocessing_fingerprint() + ":semantic:normalized-prose:v1").encode()
            ).hexdigest(),
            "normalized_embeddings": True,
            "fine_tuned": False,
            "encoded_documents": self.encoded_documents,
            "load_seconds": self.load_seconds,
            "inference_seconds": self.inference_seconds,
        }

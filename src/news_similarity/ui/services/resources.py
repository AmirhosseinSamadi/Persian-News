"""Cache one CPU matcher per artifact identity; serialize its mutable LRU access."""

from threading import RLock

import streamlit as st

from news_similarity.ui.services.ui_facade import UiConfig, UiError


def resource_stamp(config: UiConfig) -> tuple:
    result = []
    for path in config.model_files():
        try:
            stat = path.stat()
            result.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            result.append((str(path), None, None))
    return tuple(result)


class ModelResource:
    def __init__(self, matcher):
        self.matcher = matcher
        self.lock = RLock()

    def compare(self, *args):
        with self.lock:
            return self.matcher.compare(*args)

    def rank(self, *args, **kwargs):
        with self.lock:
            return self.matcher.rank(*args, **kwargs)


@st.cache_resource(max_entries=2, show_spinner=False)
def model_resource(config: UiConfig, stamp: tuple) -> ModelResource:
    if not all(path.is_file() for path in config.model_files()):
        raise UiError(
            "فایل‌های مدل آماده نیستند. مدل‌های ذخیره‌شده و تنظیمات ثابت "
            "فازهای پیشین را در پوشهٔ artifacts قرار دهید؛ رابط مدل را آموزش نمی‌دهد."
        )
    from news_similarity.hybrid_evaluation import load_hybrid_matcher
    from news_similarity.semantic import SemanticConfig, SemanticSimilarity

    semantic = SemanticSimilarity(
        SemanticConfig(
            device="cpu", cache_folder=config.cache_folder, local_files_only=True
        )
    )
    matcher = load_hybrid_matcher(
        semantic,
        baseline_directory=config.artifacts / "tfidf",
        semantic_freeze=config.artifacts / "semantic/freeze.json",
        freeze_path=config.artifacts / "hybrid/hybrid.freeze.json",
    )
    return ModelResource(matcher)

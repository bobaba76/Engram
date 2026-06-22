"""Tests for indexing/embeddings.py — fallback embeddings, device resolution, batching."""
from __future__ import annotations

import hashlib

import pytest

from indexing.embeddings import (
    EMBEDDER_VERSION,
    EmbeddingNotReadyError,
    _fallback_embedding,
    _resolve_device,
    _token_aware_batches,
    embed_texts,
    embedding_backend_name,
    embedding_cache_namespace,
    estimate_tokens,
    get_embedding_runtime_info,
)


# --- Fallback embedding -------------------------------------------------------

def test_fallback_embedding_produces_correct_dimensions() -> None:
    vec = _fallback_embedding("hello world", dimensions=32)
    assert len(vec) == 32
    assert all(0.0 <= v <= 1.0 for v in vec)


def test_fallback_embedding_is_deterministic() -> None:
    a = _fallback_embedding("same text", dimensions=64)
    b = _fallback_embedding("same text", dimensions=64)
    assert a == b


def test_fallback_embedding_differs_for_different_text() -> None:
    a = _fallback_embedding("text a", dimensions=32)
    b = _fallback_embedding("text b", dimensions=32)
    assert a != b


def test_fallback_embedding_handles_empty_string() -> None:
    vec = _fallback_embedding("", dimensions=16)
    assert len(vec) == 16


# --- Device resolution --------------------------------------------------------

def test_resolve_device_returns_cpu_when_torch_unavailable() -> None:
    # When torch is None (not loaded), always returns cpu
    from indexing import embeddings
    if embeddings.torch is None:
        assert _resolve_device("cuda") == "cpu"
        assert _resolve_device("auto") == "cpu"
        assert _resolve_device("mps") == "cpu"


def test_resolve_device_defaults_to_cpu_for_unknown() -> None:
    from indexing import embeddings
    if embeddings.torch is None:
        assert _resolve_device("tpu") == "cpu"
        assert _resolve_device("") == "cpu"


# --- Runtime info -------------------------------------------------------------

def test_runtime_info_fallback_when_no_torch() -> None:
    from indexing import embeddings
    if not embeddings._load_embedding_dependencies():
        info = get_embedding_runtime_info("jinaai/jina-embeddings-v2-base-code", "auto")
        assert info["backend"] == "deterministic_fallback"
        assert info["resolved_device"] == "cpu"
        assert info["dependencies_loaded"] is False


def test_runtime_info_non_jina_model() -> None:
    info = get_embedding_runtime_info("some-other-model", "cpu")
    assert info["backend"] == "deterministic_fallback"
    assert "not handled" in info["reason"]


# --- Backend name --------------------------------------------------------------

def test_embedding_backend_name_fallback_for_non_jina() -> None:
    assert embedding_backend_name("other-model") == "deterministic_fallback"


def test_embedding_backend_name_fallback_when_no_torch() -> None:
    from indexing import embeddings
    if not embeddings._load_embedding_dependencies():
        assert embedding_backend_name("jinaai/jina-embeddings-v2-base-code") == "deterministic_fallback"


# --- Cache namespace ----------------------------------------------------------

def test_cache_namespace_includes_version_and_model() -> None:
    ns = embedding_cache_namespace("jinaai/jina-embeddings-v2-base-code", 512, "cpu")
    assert f"v{EMBEDDER_VERSION}" in ns
    assert "jinaai/jina-embeddings-v2-base-code" in ns
    assert "maxlen=512" in ns
    assert "device=cpu" in ns


def test_cache_namespace_normalizes_device() -> None:
    ns1 = embedding_cache_namespace("model", 256, "CUDA")
    ns2 = embedding_cache_namespace("model", 256, "cuda")
    assert ns1 == ns2


def test_cache_namespace_defaults_device_to_auto() -> None:
    ns = embedding_cache_namespace("model", 256, "")
    assert "device=auto" in ns


# --- Token estimation ---------------------------------------------------------

def test_estimate_tokens_char_fallback() -> None:
    assert estimate_tokens("a" * 40) == 10  # 40 chars / 4 = 10
    assert estimate_tokens("") == 1  # min 1
    assert estimate_tokens(None) == 1


def test_estimate_tokens_with_tokenizer() -> None:
    class FakeTokenizer:
        def encode(self, text, add_special_tokens=True, truncation=False):
            return str(text).split()
    assert estimate_tokens("one two three", tokenizer=FakeTokenizer()) == 3


# --- Token-aware batching -----------------------------------------------------

def test_token_aware_batches_respects_batch_size() -> None:
    texts = ["a", "b", "c", "d"]
    batches = _token_aware_batches(texts, batch_size=2, max_batch_tokens=10000)
    assert len(batches) == 2
    assert batches[0] == ["a", "b"]
    assert batches[1] == ["c", "d"]


def test_token_aware_batches_respects_token_budget() -> None:
    class FakeTokenizer:
        def encode(self, text, add_special_tokens=True, truncation=False):
            return list(text)  # 1 token per char
    texts = ["aaaa", "bbbb", "cccc"]
    batches = _token_aware_batches(
        texts, batch_size=10, max_batch_tokens=5, tokenizer=FakeTokenizer()
    )
    # Each text is 4 tokens, so two fit per batch (4+4=8 > 5? no, 4 <= 5, 4+4=8 > 5)
    # First batch: ["aaaa"] (4 tokens), next would be 4+4=8 > 5, so new batch
    assert len(batches) >= 2


def test_token_aware_batches_empty_input() -> None:
    batches = _token_aware_batches([], batch_size=10, max_batch_tokens=100)
    assert batches == []


def test_token_aware_batches_single_item() -> None:
    batches = _token_aware_batches(["only"], batch_size=10, max_batch_tokens=100)
    assert batches == [["only"]]


# --- embed_texts fallback behavior --------------------------------------------

def test_embed_texts_raises_when_model_not_ready() -> None:
    """embed_texts should raise EmbeddingNotReadyError by default, not silently fall back."""
    with pytest.raises(EmbeddingNotReadyError):
        embed_texts(["hello"], model_name="jinaai/nonexistent-model-that-will-not-load")


def test_embed_texts_fallback_when_allowed() -> None:
    """embed_texts with allow_fallback=True should return hash-based embeddings."""
    result = embed_texts(
        ["hello world"],
        model_name="jinaai/jina-embeddings-v2-base-code",
        allow_fallback=True,
    )
    assert len(result) == 1
    assert len(result[0]) > 0


def test_embed_texts_raises_for_non_jina_without_fallback() -> None:
    """Non-jina models should also raise without allow_fallback."""
    with pytest.raises(EmbeddingNotReadyError):
        embed_texts(["hello"], model_name="some-other-model")

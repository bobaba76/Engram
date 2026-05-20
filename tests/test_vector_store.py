import json

from indexing.embeddings import _token_aware_batches, estimate_tokens
from storage.vector_store import _is_vector_dimension_error
from storage.vector_store import VectorStore


def test_detects_lancedb_vector_dimension_error() -> None:
    error = ValueError("lance error: LanceError(Arrow): Cast error: Cannot cast to FixedSizeList(32): value at index 0 has length 768")

    assert _is_vector_dimension_error(error) is True


def test_ignores_unrelated_vector_store_errors() -> None:
    assert _is_vector_dimension_error(ValueError("table locked")) is False


def test_vector_store_persists_embedding_cache_in_sqlite(tmp_path) -> None:
    store = VectorStore(tmp_path)
    store.cache_embeddings({"hash-a": [0.1, 0.2], "hash-b": [0.3, 0.4]})
    store.close()

    assert not (tmp_path / "embedding_cache.json").exists()
    assert (tmp_path / "embedding_cache.sqlite").exists()

    reopened = VectorStore(tmp_path)

    assert reopened.get_cached_vectors(["hash-a", "missing"]) == {"hash-a": [0.1, 0.2]}
    reopened.close()


def test_vector_store_migrates_legacy_json_embedding_cache(tmp_path) -> None:
    legacy_path = tmp_path / "embedding_cache.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(json.dumps({"legacy-hash": [0.5, 0.6]}), encoding="utf-8")

    store = VectorStore(tmp_path)

    assert store.get_cached_vectors(["legacy-hash"]) == {"legacy-hash": [0.5, 0.6]}
    assert not legacy_path.exists()
    assert (tmp_path / "embedding_cache.sqlite").exists()
    store.close()


def test_embedding_token_estimate_prefers_tokenizer_when_available() -> None:
    class _Tokenizer:
        def encode(self, text, add_special_tokens=True, truncation=False):
            return str(text).split()

    assert estimate_tokens("one two three", tokenizer=_Tokenizer()) == 3


def test_token_aware_batches_use_tokenizer_counts() -> None:
    class _Tokenizer:
        def encode(self, text, add_special_tokens=True, truncation=False):
            return str(text).split()

    batches = _token_aware_batches(["one two", "three four", "five"], batch_size=10, max_batch_tokens=4, tokenizer=_Tokenizer())

    assert batches == [["one two", "three four"], ["five"]]

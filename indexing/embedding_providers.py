from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from typing import Iterable, Protocol

from indexing.embeddings import (
    embed_texts,
    embedding_backend_name,
    embedding_cache_namespace,
    get_embedding_runtime_info,
)


@dataclass(slots=True)
class EmbeddingRequest:
    model_name: str
    provider_name: str = "local"
    batch_size: int = 24
    max_length: int = 512
    device: str = "cpu"
    max_batch_tokens: int = 12000
    api_key: str = ""
    base_url: str = ""
    retry_attempts: int = 3
    retry_backoff_seconds: float = 1.0
    max_concurrent_batches: int = 4


class EmbeddingProvider(Protocol):
    provider_name: str

    def cache_namespace(self, request: EmbeddingRequest) -> str:
        ...

    def runtime_info(self, request: EmbeddingRequest) -> dict[str, object]:
        ...

    def recommended_batch_size(self, request: EmbeddingRequest) -> int:
        ...

    def embed(self, texts: Iterable[str], request: EmbeddingRequest) -> list[list[float]]:
        ...


class LocalJinaEmbeddingProvider:
    provider_name = "local-jina"

    def cache_namespace(self, request: EmbeddingRequest) -> str:
        return embedding_cache_namespace(
            request.model_name,
            max_length=request.max_length,
            device=request.device,
        )

    def runtime_info(self, request: EmbeddingRequest) -> dict[str, object]:
        info = get_embedding_runtime_info(request.model_name, request.device)
        info["provider"] = self.provider_name
        return info

    def recommended_batch_size(self, request: EmbeddingRequest) -> int:
        requested = int(request.batch_size or 0)
        if requested > 0:
            return requested
        device = (request.device or "").lower()
        return 24 if device == "cuda" else 8

    def embed(self, texts: Iterable[str], request: EmbeddingRequest) -> list[list[float]]:
        return embed_texts(
            texts,
            model_name=request.model_name,
            batch_size=request.batch_size,
            max_length=request.max_length,
            device=request.device,
            max_batch_tokens=request.max_batch_tokens,
        )


class DeterministicFallbackEmbeddingProvider(LocalJinaEmbeddingProvider):
    provider_name = "deterministic-fallback"


class OpenAICompatibleEmbeddingProvider:
    provider_name = "openai-compatible"

    def cache_namespace(self, request: EmbeddingRequest) -> str:
        base_url = request.base_url.strip() or "openai"
        return f"v2:{self.provider_name}:{base_url}:{request.model_name}:maxlen={request.max_length}"

    def runtime_info(self, request: EmbeddingRequest) -> dict[str, object]:
        return {
            "provider": self.provider_name,
            "model_name": request.model_name,
            "backend": "openai_compatible",
            "base_url": request.base_url or "default",
            "dependencies_loaded": self._openai_available(),
            "reason": "configured" if self._openai_available() else "openai package unavailable",
            "recommended_batch_size": self.recommended_batch_size(request),
            "recommended_concurrency": max(int(request.max_concurrent_batches or 1), 1),
        }

    def recommended_batch_size(self, request: EmbeddingRequest) -> int:
        requested = int(request.batch_size or 0)
        if requested > 0:
            return requested
        model = request.model_name.lower()
        if "qwen3-embedding-0.6b" in model:
            return 256
        if "qwen3-embedding-4b" in model:
            return 128
        if "qwen3-embedding-8b" in model:
            return 64
        if "text-embedding" in model:
            return 100
        return 64

    def embed(self, texts: Iterable[str], request: EmbeddingRequest) -> list[list[float]]:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI package is required for CODER_EMBED_PROVIDER=openai") from exc
        client_kwargs = {}
        if request.api_key:
            client_kwargs["api_key"] = request.api_key
        if request.base_url:
            client_kwargs["base_url"] = request.base_url
        client = OpenAI(**client_kwargs)
        text_list = list(texts)
        batch_size = max(self.recommended_batch_size(request), 1)
        batches = [
            (index, text_list[index:index + batch_size])
            for index in range(0, len(text_list), batch_size)
        ]

        def embed_batch(index: int, batch: list[str]) -> tuple[int, list[list[float]]]:
            attempts = max(int(request.retry_attempts or 1), 1)
            backoff = max(float(request.retry_backoff_seconds or 0.0), 0.0)
            last_error: Exception | None = None
            for attempt in range(attempts):
                try:
                    response = client.embeddings.create(model=request.model_name, input=batch)
                    return index, [item.embedding for item in response.data]
                except Exception as exc:  # API providers raise several typed exceptions.
                    last_error = exc
                    if attempt + 1 >= attempts:
                        break
                    time.sleep(backoff * (2 ** attempt))
            raise RuntimeError(f"embedding batch failed after {attempts} attempts") from last_error

        if len(batches) <= 1:
            return embed_batch(0, text_list)[1] if text_list else []

        results: dict[int, list[list[float]]] = {}
        max_workers = max(min(int(request.max_concurrent_batches or 1), len(batches)), 1)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(embed_batch, index, batch) for index, batch in batches]
            for future in as_completed(futures):
                index, vectors = future.result()
                results[index] = vectors
        vectors_out: list[list[float]] = []
        for index, _ in batches:
            vectors_out.extend(results[index])
        return vectors_out

    def _openai_available(self) -> bool:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True


def build_embedding_provider(provider_name: str, model_name: str = "") -> EmbeddingProvider:
    normalized = (provider_name or "local").strip().lower()
    if normalized in {"openai", "openai-compatible"}:
        return OpenAICompatibleEmbeddingProvider()
    if model_name.startswith("jinaai/"):
        return LocalJinaEmbeddingProvider()
    return DeterministicFallbackEmbeddingProvider()


def embedding_runtime_info(request: EmbeddingRequest) -> dict[str, object]:
    return build_embedding_provider(request.provider_name, request.model_name).runtime_info(request)


def embedding_provider_name(provider_name: str, model_name: str) -> str:
    provider = build_embedding_provider(provider_name, model_name)
    backend = embedding_backend_name(model_name)
    return f"{provider.provider_name}:{backend}"

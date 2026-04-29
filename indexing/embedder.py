import hashlib

from indexing.embedding_providers import EmbeddingRequest, build_embedding_provider
from models.entity_models import ChunkRecord
from storage.vector_store import VectorStore


def _approx_token_count(text: str) -> int:
    stripped = str(text or "").strip()
    if not stripped:
        return 0
    return max(len(stripped) // 4, 1)


def embed_chunks(
    vector_store: VectorStore,
    chunks: list[ChunkRecord],
    model_name: str,
    batch_size: int = 24,
    max_length: int = 512,
    device: str = "cpu",
    max_batch_tokens: int = 12000,
    provider_name: str = "local",
    api_key: str = "",
    base_url: str = "",
    retry_attempts: int = 3,
    retry_backoff_seconds: float = 1.0,
    max_concurrent_batches: int = 4,
) -> dict[str, object]:
    request = EmbeddingRequest(
        model_name=model_name,
        provider_name=provider_name,
        batch_size=batch_size,
        max_length=max_length,
        device=device,
        max_batch_tokens=max_batch_tokens,
        api_key=api_key,
        base_url=base_url,
        retry_attempts=retry_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        max_concurrent_batches=max_concurrent_batches,
    )
    provider = build_embedding_provider(provider_name, model_name)
    request.batch_size = provider.recommended_batch_size(request)
    namespace = provider.cache_namespace(request)
    content_hashes = [
        f"{namespace}:{hashlib.sha256(chunk.content.encode('utf-8')).hexdigest()}"
        for chunk in chunks
    ]
    cached_vectors = vector_store.get_cached_vectors(content_hashes)
    unique_content_hash_count = len(set(content_hashes))
    duplicate_content_reuse_count = max(len(content_hashes) - unique_content_hash_count, 0)
    missing_content_by_hash: dict[str, str] = {}
    for chunk, content_hash in zip(chunks, content_hashes, strict=False):
        if content_hash in cached_vectors or content_hash in missing_content_by_hash:
            continue
        missing_content_by_hash[content_hash] = chunk.content
    missing_hashes = list(missing_content_by_hash)
    missing_token_estimate = sum(_approx_token_count(missing_content_by_hash[content_hash]) for content_hash in missing_hashes)
    requested_batch_size = max(request.batch_size, 1)
    token_budget = max(request.max_batch_tokens, 1)
    planned_batch_count = max((len(missing_hashes) + requested_batch_size - 1) // requested_batch_size, 1) if missing_hashes else 0
    token_budget_batch_estimate = max((missing_token_estimate + token_budget - 1) // token_budget, 1) if missing_hashes else 0
    missing_embeddings = (
        provider.embed(
            (missing_content_by_hash[content_hash] for content_hash in missing_hashes),
            request=request,
        )
        if missing_hashes
        else []
    )
    vector_store.cache_embeddings(
        {content_hash: embedding for content_hash, embedding in zip(missing_hashes, missing_embeddings, strict=False)}
    )
    fresh_vectors = {content_hash: embedding for content_hash, embedding in zip(missing_hashes, missing_embeddings, strict=False)}
    rows = []
    for chunk, content_hash in zip(chunks, content_hashes, strict=False):
        embedding = cached_vectors.get(content_hash) or fresh_vectors.get(content_hash)
        rows.append(
            {
                "chunk_id": chunk.chunk_id,
                "file_path": chunk.file_path,
                "symbol_name": chunk.symbol_name,
                "chunk_kind": chunk.chunk_kind,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content": chunk.content,
                "content_hash": chunk.content_hash,
                "source_hash": chunk.source_hash,
                "parser_name": chunk.parser_name,
                "chunking_version": chunk.chunking_version,
                "vector": embedding,
            }
        )
    vector_store.add_items(rows)
    return {
        "chunk_count": len(chunks),
        "reused_embedding_count": sum(1 for content_hash in content_hashes if content_hash in cached_vectors),
        "new_embedding_count": len(fresh_vectors),
        "unique_content_hash_count": unique_content_hash_count,
        "cache_hit_count": len(cached_vectors),
        "cache_miss_count": len(missing_hashes),
        "duplicate_content_reuse_count": duplicate_content_reuse_count,
        "requested_batch_size": requested_batch_size,
        "max_batch_tokens": token_budget,
        "planned_batch_count": planned_batch_count,
        "token_budget_batch_estimate": token_budget_batch_estimate,
        "approx_missing_token_count": missing_token_estimate,
        "provider": provider.provider_name,
    }

import hashlib

from models.entity_models import ChunkRecord
from indexing.embeddings import embed_texts
from storage.vector_store import VectorStore


def embed_chunks(
    vector_store: VectorStore,
    chunks: list[ChunkRecord],
    model_name: str,
    batch_size: int = 24,
    max_length: int = 512,
    device: str = "cpu",
) -> None:
    content_hashes = [hashlib.sha256(chunk.content.encode("utf-8")).hexdigest() for chunk in chunks]
    cached_vectors = vector_store.get_cached_vectors(content_hashes)
    missing_content_by_hash: dict[str, str] = {}
    for chunk, content_hash in zip(chunks, content_hashes, strict=False):
        if content_hash in cached_vectors or content_hash in missing_content_by_hash:
            continue
        missing_content_by_hash[content_hash] = chunk.content
    missing_hashes = list(missing_content_by_hash)
    missing_embeddings = (
        embed_texts(
            (missing_content_by_hash[content_hash] for content_hash in missing_hashes),
            model_name=model_name,
            batch_size=batch_size,
            max_length=max_length,
            device=device,
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
                "vector": embedding,
            }
        )
    vector_store.add_items(rows)

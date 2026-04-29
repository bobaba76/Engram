from models.entity_models import ChunkRecord
from indexing.chunker import diff_chunk_ids


def test_incremental_chunk_diff_keeps_unchanged_chunks() -> None:
    previous = [
        {"chunk_id": "file.py:a:1-3:old"},
        {"chunk_id": "file.py:b:4-8:same"},
    ]
    current = [
        ChunkRecord(
            chunk_id="file.py:b:4-8:same",
            file_path="file.py",
            start_line=4,
            end_line=8,
            chunk_kind="function",
            symbol_name="b",
            qualified_name="b",
            content="def b(): pass",
        ),
        ChunkRecord(
            chunk_id="file.py:c:9-12:new",
            file_path="file.py",
            start_line=9,
            end_line=12,
            chunk_kind="function",
            symbol_name="c",
            qualified_name="c",
            content="def c(): pass",
        ),
    ]

    diff = diff_chunk_ids(previous, current)
    assert diff["stale"] == {"file.py:a:1-3:old"}
    assert diff["unchanged"] == {"file.py:b:4-8:same"}
    assert diff["new"] == {"file.py:c:9-12:new"}

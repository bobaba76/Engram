from pathlib import Path

from indexing.chunker import CHUNKING_VERSION, build_chunks
from models.entity_models import SymbolRecord


def test_build_chunks_records_versioned_metadata(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("def load_customer():\n    return 1\n", encoding="utf-8")
    symbol = SymbolRecord(
        name="load_customer",
        qualified_name="load_customer",
        kind="function",
        start_line=1,
        end_line=2,
        metadata={"parser": "ast"},
    )

    chunks = build_chunks(tmp_path, "service.py", [symbol])

    assert len(chunks) == 1
    chunk = chunks[0]
    assert f":v{CHUNKING_VERSION}:" in chunk.chunk_id
    assert chunk.content_hash
    assert chunk.source_hash
    assert chunk.parser_name == "ast"
    assert chunk.chunking_version == CHUNKING_VERSION
    assert chunk.metadata["identity"] == "load_customer"

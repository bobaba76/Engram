from storage.vector_store import _is_vector_dimension_error


def test_detects_lancedb_vector_dimension_error() -> None:
    error = ValueError("lance error: LanceError(Arrow): Cast error: Cannot cast to FixedSizeList(32): value at index 0 has length 768")

    assert _is_vector_dimension_error(error) is True


def test_ignores_unrelated_vector_store_errors() -> None:
    assert _is_vector_dimension_error(ValueError("table locked")) is False

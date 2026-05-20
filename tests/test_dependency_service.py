from services.dependency_service import get_dependencies


class _Kuzu:
    def __init__(self) -> None:
        self.by_target_file = {
            "include/global.h": [
                {
                    "source": "app_main",
                    "source_file": "src/main.c",
                    "relation": "INCLUDES",
                    "target": "GLOBAL_FLAG",
                    "target_file": "include/global.h",
                },
                {
                    "source": "uart_init",
                    "source_file": "src/uart.c",
                    "relation": "INCLUDES",
                    "target": "GLOBAL_FLAG",
                    "target_file": "include/global.h",
                },
            ]
        }
        self.by_target_symbol = {
            "app_main": [
                {
                    "source": "system_start",
                    "source_file": "src/startup.c",
                    "relation": "INCLUDES",
                    "target": "app_main",
                    "target_file": "src/main.c",
                }
            ]
        }

    def edges_for_target(self, target: str, relation: str | None = None):
        return []

    def edges_for_source(self, target: str, relation: str | None = None):
        return []

    def symbol_edges_for_target_file(self, file_path: str, relation: str, limit: int | None = None):
        return self.by_target_file.get(file_path, [])[:limit]

    def symbol_edges_for_target_symbol(self, target: str, relation: str, limit: int | None = None):
        return self.by_target_symbol.get(target, [])[:limit]


def test_get_dependencies_summarizes_native_header_blast_radius() -> None:
    payload = get_dependencies(_Kuzu(), "include/global.h")

    blast = payload["native_header_blast_radius"]
    assert blast["risk"] == "HIGH"
    assert blast["direct_include_count"] == 2
    assert blast["direct_including_files"] == ["src/main.c", "src/uart.c"]
    assert blast["indirect_include_count"] == 1
    assert blast["indirect_including_files"] == ["src/startup.c"]
    assert "public/native header surface" in blast["risk_factors"]
    assert payload["compact_summary"]["native_header_blast_radius"]["direct_include_count"] == 2

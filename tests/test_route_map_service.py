from pathlib import Path

from services.route_map_service import route_map


class _FilesRepo:
    def fetch_all(self):
        return [{"path": "src/page.tsx"}]


class _Store:
    files = _FilesRepo()

    def fetch_symbols_for_file(self, file_path):
        return [{"qualified_name": "page.component"}]


def test_route_map_uses_indexed_files_before_repo_walk(tmp_path: Path) -> None:
    indexed = tmp_path / "src" / "page.tsx"
    indexed.parent.mkdir()
    indexed.write_text("const apiClient = { get: () => null };\napiClient.get('/api/regional/company-overview')\n", encoding="utf-8")

    noisy = tmp_path / "node_modules" / "pkg" / "noise.js"
    noisy.parent.mkdir(parents=True)
    noisy.write_text("fetch('/api/regional/company-overview')\n", encoding="utf-8")

    payload = route_map(tmp_path, _Store(), route="/api/regional/company-overview")

    assert payload["total"] == 1
    route_payload = payload["routes"][0]
    assert [consumer["file_path"] for consumer in route_payload["consumers"]] == ["src/page.tsx"]


from services.search_ranking import rerank_search_results
from services.semantic_search import _expanded_regex_candidates, _neighboring_chunk_candidates, _public_result_payload, _task_variants


def test_hybrid_ranking_uses_source_and_content_signals() -> None:
    results = [
        {
            "file_path": "backend/repositories/customers.py",
            "symbol_name": "get_customers",
            "qualified_name": "get_customers",
            "chunk_kind": "function",
            "start_line": 10,
            "end_line": 20,
            "content": "def get_customers(): return customer_totals",
            "_distance": 0.05,
            "retrieval_sources": ["regex", "symbol"],
        },
        {
            "file_path": "scripts/internal_tool.py",
            "symbol_name": "helper",
            "qualified_name": "helper",
            "chunk_kind": "function",
            "start_line": 1,
            "end_line": 2,
            "content": "def helper(): pass",
            "_distance": 0.2,
            "retrieval_sources": ["vector"],
        },
    ]

    ranked = rerank_search_results("customer totals backend", results, limit=2)

    assert ranked[0]["file_path"] == "backend/repositories/customers.py"
    assert "regex retrieval" in ranked[0]["relevance"]


class _DiscoveryStore:
    def search_chunks_content(self, query, limit=20):
        if query == "resolveCustomer":
            return [
                {
                    "file_path": "backend/services/customer_service.py",
                    "symbol_name": "resolveCustomer",
                    "qualified_name": "backend.services.customer_service.resolveCustomer",
                    "chunk_kind": "function",
                    "start_line": 20,
                    "end_line": 36,
                    "content": "def resolveCustomer(customer_id): return fetch_customer(customer_id)",
                    "token_hits": 2,
                }
            ]
        return []

    def fetch_chunks_for_file_range(self, file_path, start_line=None, end_line=None, limit=5):
        return [
            {
                "file_path": file_path,
                "symbol_name": "customerTotals",
                "qualified_name": "backend.services.customer_service.customerTotals",
                "chunk_kind": "function",
                "start_line": max(int(start_line or 1), 1),
                "end_line": int(end_line or 1),
                "content": "def customerTotals(): return compute_totals()",
            }
        ]


def test_expanded_regex_candidates_use_symbols_from_seed_results() -> None:
    store = _DiscoveryStore()
    seed_results = [
        {
            "file_path": "backend/api/customers.py",
            "symbol_name": "resolveCustomer",
            "qualified_name": "backend.api.customers.resolveCustomer",
            "start_line": 10,
            "end_line": 18,
        }
    ]

    expanded = _expanded_regex_candidates(store, "customer lookup", seed_results, limit=3)

    assert expanded
    assert expanded[0]["retrieval_source"] == "regex_expanded"
    assert expanded[0]["symbol_name"] == "resolveCustomer"


def test_neighboring_chunk_candidates_expand_around_seed_ranges() -> None:
    store = _DiscoveryStore()
    seed_results = [
        {
            "file_path": "backend/services/customer_service.py",
            "symbol_name": "resolveCustomer",
            "qualified_name": "backend.services.customer_service.resolveCustomer",
            "start_line": 40,
            "end_line": 55,
        }
    ]

    windowed = _neighboring_chunk_candidates(store, seed_results, limit=3, window_lines=20)

    assert windowed
    assert windowed[0]["retrieval_source"] == "window"
    assert windowed[0]["file_path"] == "backend/services/customer_service.py"


def test_task_variants_include_rewritten_queries_for_natural_language_tasks() -> None:
    variants = _task_variants("where is resolveCustomer handled in /api/customers")

    assert variants
    assert variants[0] == "where is resolveCustomer handled in /api/customers"
    assert any("resolveCustomer" in variant for variant in variants)
    assert any("/api/customers" in variant for variant in variants)


def test_task_variants_respects_single_variant_limit() -> None:
    variants = _task_variants("where is defaultView behavior handled", limit=1)

    assert variants == ["where is defaultView behavior handled"]


def test_public_result_payload_omits_embedding_vectors() -> None:
    payload = _public_result_payload({"file_path": "app/main.py", "vector": [0.1, 0.2]})

    assert payload == {"file_path": "app/main.py"}


def test_hybrid_ranking_boosts_graph_backed_frontend_implementation_paths() -> None:
    results = [
        {
            "file_path": "frontend/components/CustomerView.tsx",
            "symbol_name": "CustomerView",
            "qualified_name": "frontend.components.CustomerView.CustomerView",
            "chunk_kind": "component",
            "start_line": 4,
            "end_line": 28,
            "content": "export function CustomerView() { const customer = useCustomer(); return <div /> }",
            "_distance": 0.04,
            "retrieval_sources": ["graph", "vector"],
            "graph_relation": "CALLS",
            "graph_distance": 1,
        },
        {
            "file_path": "scripts/customer_helper.py",
            "symbol_name": "customer_helper",
            "qualified_name": "customer_helper",
            "chunk_kind": "function",
            "start_line": 1,
            "end_line": 4,
            "content": "def customer_helper(): pass",
            "_distance": 0.08,
            "retrieval_sources": ["vector"],
        },
    ]

    ranked = rerank_search_results("customer view frontend behavior", results, limit=2)

    assert ranked[0]["file_path"] == "frontend/components/CustomerView.tsx"
    assert "graph-backed frontend path" in ranked[0]["relevance"]

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lightrag import source_quality as quality


@pytest.fixture
def policy(monkeypatch, tmp_path):
    path = tmp_path / "quality.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspaces": {
                    "w": {"doc_ids": ["doc-bad"], "chunk_ids": ["chunk-bad"]}
                },
            }
        )
    )
    monkeypatch.setenv("LIGHTRAG_QUALITY_QUARANTINE_FILE", str(path))
    return path


@pytest.mark.parametrize(
    "row",
    [
        {"id": "chunk-bad"},
        {"chunk_id": "chunk-bad"},
        {"doc_id": "doc-bad"},
        {"full_doc_id": "doc-bad"},
        {"source_id": "chunk-good<SEP>chunk-bad"},
        {"source_id": ["chunk-good", "chunk-bad"]},
        {"chunk_ids": ["chunk-bad"]},
    ],
)
def test_exact_source_and_mixed_graph_evidence_are_blocked(policy, row):
    assert quality.row_blocked("w", row)
    assert not quality.row_blocked("other", row)


def test_unknown_substrings_are_not_matched(policy):
    assert not quality.row_blocked("w", {"id": "chunk-bad-extra"})
    assert quality.filter_rows("w", [{"id": "chunk-bad"}, {"id": "chunk-good"}]) == [
        {"id": "chunk-good"}
    ]


def test_old_agent_evidence_needs_source_provenance(policy):
    rows = [
        {"id": "entity-name", "description": "untracked"},
        {"entity_name": "safe", "source_id": "chunk-good"},
        {"chunk_id": "chunk-good", "content": "safe"},
        {"entity_name": "bad", "source_id": "chunk-bad"},
    ]
    assert quality.filter_rows("w", rows, require_provenance=True) == rows[1:3]


def test_missing_active_registry_and_invalid_registry_fail_closed(policy):
    assert quality.cache_key("w")
    policy.unlink()
    with pytest.raises(RuntimeError):
        quality.cache_key("w")
    policy.write_text("{broken")
    with pytest.raises(ValueError):
        quality.cache_key("w")


def test_atomic_registry_update_changes_only_affected_cache_namespace(policy):
    before = quality.cache_key("w")
    assert quality.cache_key("other") == ()
    new = policy.with_suffix(".new")
    new.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspaces": {
                    "w": {"doc_ids": ["doc-bad", "doc-new"], "chunk_ids": ["chunk-bad"]}
                },
            }
        )
    )
    new.replace(policy)
    assert quality.cache_key("w") != before
    assert quality.cache_key("other") == ()
    assert quality.blocked_id("w", "doc-new", "document")


def test_explicit_empty_registry_is_a_reversible_rollback(policy):
    assert quality.cache_key("w")
    policy.write_text(json.dumps({"schema_version": 1, "workspaces": {}}))
    assert quality.cache_key("w") == ()
    assert not quality.row_blocked("w", {"id": "chunk-bad"})


def test_graph_index_merge_reads_are_preserved_query_reads_are_filtered(policy):
    class Graph:
        workspace = "w"

        @quality.graph_read_guard
        async def get_nodes_batch(self, ids):
            return {
                "good": {"source_id": "chunk-good"},
                "mixed": {"source_id": "chunk-good<SEP>chunk-bad"},
            }

    graph = Graph()
    assert len(asyncio.run(graph.get_nodes_batch([]))) == 2

    @quality.query_guard
    async def query():
        return await graph.get_nodes_batch([])

    assert asyncio.run(query()) == {"good": {"source_id": "chunk-good"}}
    assert len(asyncio.run(graph.get_nodes_batch([]))) == 2


def test_agent_sql_results_follow_the_same_workspace_policy(policy):
    @quality.agent_result_guard
    async def search(rag):
        return [{"doc_id": "doc-bad"}, {"doc_id": "doc-good"}]

    assert asyncio.run(search(SimpleNamespace(workspace="w"))) == [
        {"doc_id": "doc-good"}
    ]
    assert len(asyncio.run(search(SimpleNamespace(workspace="other")))) == 2


def test_pg_single_reads_refuse_bad_source_without_querying_database(policy):
    from lightrag.kg.postgres_impl import PGKVStorage

    storage = object.__new__(PGKVStorage)
    storage.workspace = "w"
    storage.namespace = "text_chunks"
    storage.db = SimpleNamespace(query=AsyncMock())
    assert asyncio.run(storage.get_by_id("chunk-bad")) is None
    storage.db.query.assert_not_called()
    storage.namespace = "full_docs"
    assert asyncio.run(storage.get_by_id("doc-bad")) is None
    storage.db.query.assert_not_called()


def test_pg_bulk_reads_preserve_order_and_none_positions(policy):
    from lightrag.kg.postgres_impl import PGKVStorage

    storage = object.__new__(PGKVStorage)
    storage.workspace = "w"
    storage.namespace = "text_chunks"
    storage.db = SimpleNamespace(
        query=AsyncMock(
            return_value=[
                {
                    "id": "chunk-good",
                    "content": "correct text",
                    "full_doc_id": "doc-good",
                }
            ]
        )
    )
    rows = asyncio.run(storage.get_by_ids(["chunk-bad", "chunk-good", "missing"]))
    assert rows[0] is None and rows[1]["content"] == "correct text" and rows[2] is None
    assert storage.db.query.call_args.args[1][1] == ["chunk-good", "missing"]


def test_pg_retry_selection_omits_quarantined_document_without_updating_it(policy):
    from lightrag.kg.postgres_impl import PGDocStatusStorage
    from lightrag.base import DocStatus

    storage = object.__new__(PGDocStatusStorage)
    storage.workspace = "w"
    storage.db = SimpleNamespace(query=AsyncMock(return_value=[{"id": "doc-bad"}]))
    assert asyncio.run(storage.get_docs_by_status(DocStatus.FAILED)) == {}
    assert storage.db.query.call_count == 1


def test_doc_qa_answers_are_filtered_by_parent_document(policy):
    from lightrag.qa_extraction import get_doc_qa_pairs_by_ids

    db = SimpleNamespace(
        query=AsyncMock(
            return_value=[
                {"id": "qa-bad", "doc_id": "doc-bad"},
                {"id": "qa-good", "doc_id": "doc-good"},
            ]
        )
    )
    result = asyncio.run(
        get_doc_qa_pairs_by_ids(db=db, workspace="w", qa_ids=["qa-bad", "qa-good"])
    )
    assert [r["id"] for r in result] == ["qa-good"]


def test_unprovenanced_assistant_history_is_not_used_as_current_evidence(policy):
    history = [
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "Old potentially polluted answer"},
    ]
    assert quality.safe_history("w", history) == history[:1]
    assert quality.safe_history("other", history) == history


def test_public_status_contains_no_source_identifiers(policy):
    status = quality.public_status()
    assert status["enabled"] and len(status["revision"]) == 64
    assert "doc-bad" not in json.dumps(status)


def test_naive_query_filters_real_context_and_scopes_answer_cache(policy, monkeypatch):
    from lightrag import operate
    from lightrag.base import QueryParam

    class Tokenizer:
        def encode(self, value):
            return [ord(c) for c in value]

        def decode(self, values):
            return "".join(chr(c) for c in values)

    source = [
        {
            "id": "chunk-bad",
            "chunk_id": "chunk-bad",
            "content": "BAD_SOURCE_TEXT",
            "file_path": "bad.pdf",
        },
        {
            "id": "chunk-good",
            "chunk_id": "chunk-good",
            "content": "GOOD_SOURCE_TEXT",
            "file_path": "good.pdf",
        },
    ]
    monkeypatch.setattr(operate, "_get_vector_context", AsyncMock(return_value=source))
    model = AsyncMock(side_effect=AssertionError("No real inference in this test"))
    config = {"tokenizer": Tokenizer(), "llm_model_func": model}
    chunks = SimpleNamespace(workspace="w", global_config=config)
    param = QueryParam(
        mode="naive",
        only_need_context=True,
        enable_rerank=False,
        max_total_tokens=10000,
    )
    result = asyncio.run(
        operate.naive_query("methodology", SimpleNamespace(), chunks, param, config)
    )
    assert (
        "GOOD_SOURCE_TEXT" in result.content and "BAD_SOURCE_TEXT" not in result.content
    )
    assert "BAD_SOURCE_TEXT" not in json.dumps(result.raw_data)
    model.assert_not_called()
    # Cache lookup must use a new namespace while a quarantine is active.
    monkeypatch.setattr(operate, "compute_args_hash", lambda *args: args)

    async def cached(storage, key, *args, **kwargs):
        return (
            "CLEAN_CACHE"
            if key[-1] == quality.cache_key("w")[0]
            else "OLD_POLLUTED_CACHE",
            None,
        )

    monkeypatch.setattr(operate, "handle_cache", cached)
    param.only_need_context = False
    result = asyncio.run(
        operate.naive_query("methodology", SimpleNamespace(), chunks, param, config)
    )
    assert result.content == "CLEAN_CACHE"
    model.assert_not_called()


def test_kg_context_filters_before_truncation_and_after_chunk_merge(
    policy, monkeypatch
):
    from lightrag import operate
    from lightrag.base import QueryParam

    search = {
        "final_entities": [
            {"entity_name": "mixed", "source_id": "chunk-good<SEP>chunk-bad"},
            {"entity_name": "good", "source_id": "chunk-good"},
        ],
        "final_relations": [{"source_id": "chunk-bad"}],
        "vector_chunks": [{"id": "chunk-bad"}],
        "chunk_tracking": {"chunk-bad": {}, "chunk-good": {}},
        "query_embedding": None,
    }
    monkeypatch.setattr(operate, "_perform_kg_search", AsyncMock(return_value=search))

    async def truncate(result, *args):
        assert [row["entity_name"] for row in result["final_entities"]] == ["good"]
        assert result["final_relations"] == [] and result["vector_chunks"] == []
        assert list(result["chunk_tracking"]) == ["chunk-good"]
        return {
            "filtered_entities": result["final_entities"],
            "filtered_relations": [],
            "entities_context": ["good"],
            "relations_context": [],
            "entity_id_to_original": {},
            "relation_id_to_original": {},
        }

    monkeypatch.setattr(operate, "_apply_token_truncation", truncate)
    monkeypatch.setattr(
        operate,
        "_merge_all_chunks",
        AsyncMock(return_value=[{"id": "chunk-bad"}, {"id": "chunk-good"}]),
    )

    async def context(**kwargs):
        assert kwargs["merged_chunks"] == [{"id": "chunk-good"}]
        assert kwargs["preserved_entities"] == []
        assert kwargs["preserved_chunks"] == []
        return "SAFE_CONTEXT", {"data": {"chunks": []}}, "SAFE_CONTEXT"

    monkeypatch.setattr(operate, "_build_context_str", context)
    result = asyncio.run(
        operate._build_query_context(
            "q",
            "low",
            "high",
            None,
            None,
            None,
            SimpleNamespace(workspace="w", global_config={}),
            QueryParam(mode="hybrid"),
            agent_context={
                "entities": [{"entity_name": "old untracked"}],
                "chunks": [{"id": "chunk-bad"}],
            },
        )
    )
    assert result.context == "SAFE_CONTEXT"


def test_deletion_reads_do_not_disable_query_or_other_workspace_isolation(policy):
    value = json.loads(policy.read_text())
    value["workspaces"]["other"] = {"doc_ids": ["doc-bad"], "chunk_ids": ["chunk-bad"]}
    policy.write_text(json.dumps(value))

    @quality.query_guard
    async def query():
        assert quality.blocked_id("w", "doc-bad", "document")
        assert quality.blocked_id("w", "chunk-bad", "chunk")

    @quality.deletion_guard
    async def remove(rag):
        assert not quality.blocked_id("w", "doc-bad", "document")
        assert not quality.blocked_id("w", "chunk-bad", "chunk")
        assert quality.blocked_id("other", "chunk-bad", "chunk")
        await query()
        assert not quality.blocked_id("w", "chunk-bad", "chunk")

    asyncio.run(remove(SimpleNamespace(workspace="w")))
    assert quality.blocked_id("w", "chunk-bad", "chunk")


def test_deletion_scope_is_restored_after_failure(policy):
    @quality.deletion_guard
    async def remove(rag):
        assert not quality.blocked_id("w", "doc-bad", "document")
        raise RuntimeError("fixture failure")

    with pytest.raises(RuntimeError):
        asyncio.run(remove(SimpleNamespace(workspace="w")))
    assert quality.blocked_id("w", "doc-bad", "document")


def test_parallel_query_remains_isolated_during_deletion(policy):
    async def run():
        entered, finish = asyncio.Event(), asyncio.Event()

        @quality.deletion_guard
        async def remove(rag):
            entered.set()
            await finish.wait()
            assert not quality.blocked_id("w", "chunk-bad", "chunk")

        task = asyncio.create_task(remove(SimpleNamespace(workspace="w")))
        await entered.wait()
        assert quality.blocked_id("w", "chunk-bad", "chunk")
        finish.set()
        await task

    asyncio.run(run())

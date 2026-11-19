import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from lightrag.base import QueryParam
from lightrag.operate import _get_vector_context
from lightrag.utils import process_chunks_unified


def test_recall_can_reach_beyond_final_limit_then_rerank():
    async def run():
        vectors = SimpleNamespace(cosine_better_than_threshold=.1,
                                  query=AsyncMock(return_value=[{"id":str(i)} for i in range(30)]))
        storage = SimpleNamespace(get_by_ids=AsyncMock(return_value=[{"content":str(i)} for i in range(30)]))
        param = QueryParam(candidate_top_k=30, chunk_top_k=2, enable_rerank=True)
        candidates = await _get_vector_context("query", vectors, storage, param)
        assert vectors.query.call_args.kwargs["top_k"] == 30
        async def rerank(**kwargs):
            assert len(kwargs["documents"]) == 30 and kwargs["top_n"] == 2
            return [{"index":29,"relevance_score":.99},{"index":0,"relevance_score":.8}]
        final = await process_chunks_unified("query", candidates, param, {"rerank_model_func":rerank})
        assert [c["chunk_id"] for c in final] == ["29","0"]
        assert param.retrieval_stats["vector_candidates"] == 30
        assert param.retrieval_stats["final_chunks"] == 2
        assert param.retrieval_stats["rerank_scored"]
    asyncio.run(run())


def test_data_only_wrapper_preserves_candidate_pool(monkeypatch):
    import importlib
    mod = importlib.import_module("lightrag.lightrag")
    monkeypatch.setattr(mod, "asdict", lambda _: {})
    param = QueryParam(mode="naive", candidate_top_k=30, chunk_top_k=10)
    seen = []
    async def query(text, vectors, storage, data_param, config, **kwargs):
        seen.append(data_param)
        data_param.retrieval_stats["vector_candidates"] = 30
        from lightrag.base import QueryResult
        return QueryResult(content="", raw_data={"status":"success","data":{"chunks":[]},"metadata":{}})
    monkeypatch.setattr(mod, "naive_query", query)
    fake = SimpleNamespace(chunks_vdb=None, text_chunks=None, llm_response_cache=None, doc_status=None,
                           query_doc_qa_pairs_for_refs=AsyncMock(return_value=[]),
                           _format_query_ref_doc_qa_rows=lambda rows: rows, _query_done=AsyncMock())
    asyncio.run(mod.LightRAG.aquery_data(fake, "original query", param=param))
    assert seen[0].candidate_top_k == 30
    assert seen[0].chunk_top_k == 10 and seen[0].only_need_context
    assert param.retrieval_stats["vector_candidates"] == 30

"""Offline regressions through the real LLM queue and OpenAI binding."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from test_translate_chunk import _FakeRAG, _load_translate_chunk_to_cn


@pytest.fixture(autouse=True)
def capture_lightrag_logs(caplog):
    _load_translate_chunk_to_cn()
    from lightrag.utils import logger

    logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)


def _finish_metrics(caplog):
    return [
        json.loads(record.getMessage().split(" finish ", 1)[1])
        for record in caplog.records
        if record.getMessage().startswith("chunk_translation finish ")
    ]


def _binding(monkeypatch, *, fail_first=False, base_url="https://api.deepseek.com/v1"):
    _load_translate_chunk_to_cn()
    from lightrag.llm import openai
    from lightrag.utils import priority_limit_async_func_call
    from tenacity import wait_none

    calls = []
    shared_body = {"thinking": {"type": "enabled"}, "custom_setting": "preserved"}

    async def create(**kwargs):
        assert "_chunk_translation_trace" not in kwargs
        calls.append(kwargs)
        if fail_first and len(calls) == 1:
            raise openai.InvalidResponseError("synthetic retry")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="translation"))],
            usage=SimpleNamespace(
                completion_tokens=12,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
            ),
        )

    async def close():
        pass

    monkeypatch.setattr(
        openai,
        "create_openai_async_client",
        lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
            close=close,
        ),
    )
    complete = openai.openai_complete_if_cache.retry_with(wait=wait_none())

    async def binding(prompt, **kwargs):
        # The production optimized wrapper merges global options at this boundary.
        kwargs.update(extra_body=shared_body, reasoning_effort="high")
        return await complete("deepseek-v4-flash", prompt, base_url=base_url, **kwargs)

    return (
        priority_limit_async_func_call(1, max_execution_timeout=2)(binding),
        calls,
        shared_body,
    )


def test_translation_disables_thinking_at_sdk_and_preserves_other_calls(
    monkeypatch, caplog
):
    caplog.set_level("INFO", logger="lightrag")
    translate = _load_translate_chunk_to_cn()

    async def run():
        queued, calls, shared_body = _binding(monkeypatch)
        rag = _FakeRAG({"content": "source", "full_doc_id": "doc-1"})
        rag.workspace = "workspace-one"
        rag.llm_model_func = queued
        try:
            assert await translate(rag, "chunk-1") == ("translation", False)
            assert await queued("normal QA") == "translation"
            assert await translate(rag, "chunk-1") == ("translation", True)
            assert len(calls) == 2
            assert calls[0]["extra_body"] == {
                "thinking": {"type": "disabled"},
                "custom_setting": "preserved",
            }
            assert "reasoning_effort" not in calls[0]
            assert calls[1]["extra_body"]["thinking"]["type"] == "enabled"
            assert calls[1]["reasoning_effort"] == "high"
            assert shared_body["thinking"]["type"] == "enabled"
        finally:
            await queued.shutdown()

    asyncio.run(run())
    first, cached = _finish_metrics(caplog)
    assert first["status"] == "ok" and first["thinking_disabled"] is True
    assert first["workspace"] == "workspace-one"
    assert first["queue_ms"] >= 0 and first["lookup_ms"] >= 0 and first["save_ms"] >= 0
    assert first["llm_ms"] >= first["api_ms"] > 0
    assert first["model_attempts"] == 1 and first["completion_tokens"] == 12
    assert cached["cached"] is True and cached["model_attempts"] == 0


def test_retry_preserves_translation_policy_and_counts_attempts(monkeypatch, caplog):
    caplog.set_level("INFO", logger="lightrag")
    translate = _load_translate_chunk_to_cn()

    async def run():
        queued, calls, _ = _binding(monkeypatch, fail_first=True)
        rag = _FakeRAG({"content": "source"})
        rag.llm_model_func = queued
        try:
            assert await translate(rag, "chunk-retry") == ("translation", False)
            assert len(calls) == 2
            assert all(
                call["extra_body"]["thinking"]["type"] == "disabled" for call in calls
            )
        finally:
            await queued.shutdown()

    asyncio.run(run())
    assert _finish_metrics(caplog)[0]["model_attempts"] == 2


def test_other_provider_translation_keeps_original_options(monkeypatch):
    translate = _load_translate_chunk_to_cn()

    async def run():
        queued, calls, _ = _binding(monkeypatch, base_url="https://other.example/v1")
        rag = _FakeRAG({"content": "source"})
        rag.llm_model_func = queued
        try:
            await translate(rag, "chunk-other")
            assert calls[0]["extra_body"]["thinking"]["type"] == "enabled"
            assert calls[0]["reasoning_effort"] == "high"
        finally:
            await queued.shutdown()

    asyncio.run(run())


def test_queue_wait_is_measured_and_context_isolated():
    _load_translate_chunk_to_cn()
    from lightrag.utils import priority_limit_async_func_call
    from lightrag.utils_chunk_translation import (
        ChunkTranslationTrace,
        active_chunk_translation,
    )
    from time import perf_counter

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        seen = []

        async def model(prompt):
            if prompt == "blocker":
                entered.set()
                await release.wait()
            trace = active_chunk_translation.get()
            seen.append((prompt, trace.chunk_id if trace else None))
            if prompt == "failure":
                raise ValueError("synthetic")
            return prompt

        queued = priority_limit_async_func_call(1, max_execution_timeout=2)(model)
        try:
            blocker = asyncio.create_task(queued("blocker"))
            await entered.wait()
            trace = ChunkTranslationTrace("chunk-wait", "workspace")
            trace.queued = perf_counter()
            translation = asyncio.create_task(
                queued("translation", _chunk_translation_trace=trace)
            )
            await asyncio.sleep(0.03)
            release.set()
            await asyncio.gather(blocker, translation)
            assert trace.queue_ms >= 20
            trace.queued = perf_counter()
            with pytest.raises(ValueError):
                await queued("failure", _chunk_translation_trace=trace)
            await queued("normal")
            assert seen == [
                ("blocker", None),
                ("translation", "chunk-wait"),
                ("failure", "chunk-wait"),
                ("normal", None),
            ]
            assert active_chunk_translation.get() is None
        finally:
            await queued.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize("failed_stage", ["lookup", "llm", "save"])
def test_stage_errors_are_logged_without_content(failed_stage, caplog):
    caplog.set_level("INFO", logger="lightrag")
    translate = _load_translate_chunk_to_cn()
    from lightrag.utils import priority_limit_async_func_call

    async def run():
        rag = _FakeRAG({"content": "PRIVATE_SOURCE"})

        async def fail(*args, **kwargs):
            raise RuntimeError("PRIVATE_ERROR")

        original = rag.llm_model_func
        queued = priority_limit_async_func_call(1)(
            fail if failed_stage == "llm" else original
        )
        rag.llm_model_func = queued
        if failed_stage == "lookup":
            rag.text_chunks.get_by_id = fail
        if failed_stage == "save":
            rag.text_chunks.upsert = fail
        try:
            with pytest.raises(RuntimeError):
                await translate(rag, "chunk-fail")
        finally:
            await queued.shutdown()

    asyncio.run(run())
    metrics = _finish_metrics(caplog)[0]
    assert metrics["stage"] == failed_stage
    assert metrics["status"] == "failed" and metrics["error_type"] == "RuntimeError"
    assert "PRIVATE" not in json.dumps(metrics)


def test_worker_timeout_does_not_leak_translation_context():
    _load_translate_chunk_to_cn()
    from lightrag.utils import priority_limit_async_func_call
    from lightrag.utils_chunk_translation import (
        ChunkTranslationTrace,
        active_chunk_translation,
    )
    from time import perf_counter

    async def run():
        async def model(prompt):
            if prompt == "slow":
                await asyncio.sleep(5)
            assert active_chunk_translation.get() is None
            return prompt

        queued = priority_limit_async_func_call(1, max_execution_timeout=0.02)(model)
        trace = ChunkTranslationTrace("chunk-timeout", "workspace")
        trace.queued = perf_counter()
        try:
            with pytest.raises(TimeoutError, match="Worker execution timeout"):
                await queued("slow", _chunk_translation_trace=trace)
            assert await queued("normal") == "normal"
        finally:
            await queued.shutdown()

    asyncio.run(run())

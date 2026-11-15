import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from lightrag.kg.milvus_impl import MilvusVectorDBStorage


def make_store(embed, write, batch_size=2):
    return SimpleNamespace(
        _ensure_collection_loaded=lambda: None,
        _get_lightweight_meta_fields=lambda: set(),
        _build_embedding_inputs=lambda data: [r["content"] for r in data.values()],
        _max_batch_size=batch_size,
        embedding_func=embed,
        _client=SimpleNamespace(upsert=write),
        final_namespace="isolated_chunks",
    )


def test_upsert_writes_each_batch_before_embedding_the_next():
    events = []

    async def embed(contents):
        events.append(("embed", contents))
        return np.array([[int(value), 1] for value in contents])

    def write(*, collection_name, data):
        assert collection_name == "isolated_chunks"
        events.append(("write", [r["id"] for r in data]))
        for row in data:
            assert row["vector"].tolist() == [int(row["id"]), 1]

    store = make_store(embed, write)
    asyncio.run(
        MilvusVectorDBStorage.upsert(
            store, {str(i): {"content": str(i)} for i in range(5)}
        )
    )
    assert events == [
        ("embed", ["0", "1"]),
        ("write", ["0", "1"]),
        ("embed", ["2", "3"]),
        ("write", ["2", "3"]),
        ("embed", ["4"]),
        ("write", ["4"]),
    ]


def test_embedding_failure_preserves_only_completed_batches():
    writes = []

    async def embed(contents):
        if contents == ["2", "3"]:
            raise RuntimeError("temporary GPU failure")
        return np.ones((len(contents), 2))

    store = make_store(embed, lambda **kwargs: writes.extend(r["id"] for r in kwargs["data"]))
    with pytest.raises(RuntimeError, match="GPU failure"):
        asyncio.run(
            MilvusVectorDBStorage.upsert(
                store, {str(i): {"content": str(i)} for i in range(5)}
            )
        )
    assert writes == ["0", "1"]


def test_multimodal_batch_embeds_images_one_at_a_time():
    calls = []
    inputs = [{"text": "caption", "image": "data:image/png;base64,example"}, {"text": "body"}]

    async def embed(items):
        calls.append(items)
        return np.ones((len(items), 2))

    store = make_store(embed, lambda **kwargs: None)
    store._build_embedding_inputs = lambda _data: inputs
    asyncio.run(
        MilvusVectorDBStorage.upsert(store, {"image": {"content": "caption"}, "text": {"content": "body"}})
    )
    assert calls == [[inputs[0]], [inputs[1]]]

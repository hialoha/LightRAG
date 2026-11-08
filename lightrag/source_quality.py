"""Reversible source quarantine, scoped by workspace and exact provenance IDs.

The registry is maintained by the service account. It contains identifiers only;
source text, vectors, graph data and extraction caches remain untouched.
"""

import functools
import hashlib
import json
import os
import threading
from contextvars import ContextVar
from pathlib import Path

_query_scope = ContextVar("source_quality_query", default=False)
_deletion_workspace = ContextVar("source_quality_deletion_workspace", default=None)
_cache_lock = threading.Lock()
_cache = {}


def _policy():
    path = Path(
        os.environ.get("LIGHTRAG_QUALITY_QUARANTINE_FILE")
        or Path(__file__).resolve().parents[1]
        / "data/literature-quality-quarantine.json"
    )
    with _cache_lock:
        previous = _cache.get(str(path))
        try:
            stat = path.stat()
        except FileNotFoundError:
            if previous and previous[1]["workspaces"]:
                raise RuntimeError("Active source quarantine registry disappeared")
            return {"workspaces": {}, "revision": ""}
        signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if previous and previous[0] == signature:
            return previous[1]
        raw = path.read_bytes()
        value = json.loads(raw)
        if value.get("schema_version") != 1 or not isinstance(
            value.get("workspaces"), dict
        ):
            raise RuntimeError("Invalid source quarantine registry")
        workspaces = {}
        for workspace, item in value["workspaces"].items():
            if not isinstance(workspace, str) or not isinstance(item, dict):
                raise RuntimeError("Invalid quarantine workspace")
            docs, chunks = item.get("doc_ids"), item.get("chunk_ids")
            if (
                not isinstance(docs, list)
                or not isinstance(chunks, list)
                or not all(isinstance(v, str) and v for v in docs + chunks)
            ):
                raise RuntimeError("Invalid quarantine source identifiers")
            workspaces[workspace] = {
                "docs": frozenset(docs),
                "chunks": frozenset(chunks),
                "banned": frozenset(docs + chunks),
            }
        result = {"workspaces": workspaces, "revision": hashlib.sha256(raw).hexdigest()}
        _cache[str(path)] = (signature, result)
        return result


def scope(workspace):
    return _policy()["workspaces"].get(
        workspace, {"docs": frozenset(), "chunks": frozenset(), "banned": frozenset()}
    )


def cache_key(workspace):
    policy = _policy()
    return (policy["revision"],) if workspace in policy["workspaces"] else ()


def blocked_id(workspace, identifier, kind=None):
    deletion_workspace = _deletion_workspace.get()
    if (
        deletion_workspace is not None
        and deletion_workspace == workspace
        and not _query_scope.get()
    ):
        return False
    policy = scope(workspace)
    if kind == "document":
        return identifier in policy["docs"]
    if kind == "chunk":
        return identifier in policy["chunks"]
    return identifier in policy["docs"] or identifier in policy["chunks"]


def _identifiers(value):
    if isinstance(value, str):
        return value.split("<SEP>")
    if isinstance(value, (list, tuple, set)):
        return [item for value_item in value for item in _identifiers(value_item)]
    return []


def row_blocked(workspace, row):
    if not isinstance(row, dict):
        return False
    policy = scope(workspace)
    banned = policy["banned"]
    return any(
        identifier in banned
        for field in (
            "id",
            "chunk_id",
            "doc_id",
            "full_doc_id",
            "source_doc_id",
            "source_id",
            "source_ids",
            "chunk_ids",
        )
        for identifier in _identifiers(row.get(field))
    )


def filter_rows(workspace, rows, *, require_provenance=False):
    if not cache_key(workspace):
        return rows
    return [
        row
        for row in rows
        if isinstance(row, dict)
        and not row_blocked(workspace, row)
        and (
            not require_provenance
            or any(
                row.get(key)
                for key in (
                    "chunk_id",
                    "doc_id",
                    "full_doc_id",
                    "source_id",
                    "source_ids",
                    "chunk_ids",
                )
            )
            or isinstance(row.get("id"), str)
            and row["id"].startswith(("chunk-", "doc-"))
        )
    ]


def deletion_guard(function):
    """Let authenticated deletion rebuild dependencies without changing query isolation.

    The scope is task-local, limited to the deleting RAG workspace, and never
    overrides an explicit query scope. No quarantine registry is changed.
    """

    @functools.wraps(function)
    async def guarded(rag, *args, **kwargs):
        workspace = getattr(rag, "workspace", None)
        if not isinstance(workspace, str):
            raise ValueError("Document deletion requires an explicit workspace")
        token = _deletion_workspace.set(workspace)
        try:
            return await function(rag, *args, **kwargs)
        finally:
            _deletion_workspace.reset(token)

    return guarded


def query_guard(function):
    @functools.wraps(function)
    async def guarded(*args, **kwargs):
        token = _query_scope.set(True)
        try:
            return await function(*args, **kwargs)
        finally:
            _query_scope.reset(token)

    return guarded


def graph_read_guard(function):
    """Filter graph evidence during queries; indexing retains original merge reads."""

    @functools.wraps(function)
    async def guarded(storage, *args, **kwargs):
        result = await function(storage, *args, **kwargs)
        workspace = getattr(storage, "workspace", "")
        if not _query_scope.get() or not cache_key(workspace):
            return result
        if function.__name__ in ("get_nodes_batch", "get_edges_batch"):
            return {
                key: row
                for key, row in result.items()
                if not row_blocked(workspace, row)
            }
        return None if row_blocked(workspace, result) else result

    return guarded


def agent_result_guard(function):
    """Agent SQL reads return lists and must share the same evidence policy."""

    @functools.wraps(function)
    async def guarded(rag, *args, **kwargs):
        token = _query_scope.set(True)
        try:
            rows = await function(rag, *args, **kwargs)
            workspace = getattr(rag, "workspace", "")
            return filter_rows(workspace, rows)
        finally:
            _query_scope.reset(token)

    return guarded


def safe_history(workspace, history):
    # Earlier assistant messages do not carry source-quality provenance.
    # Keep users' questions for continuity; regenerate evidence from current data.
    if cache_key(workspace):
        return [
            message
            for message in history or []
            if isinstance(message, dict) and message.get("role") == "user"
        ]
    return history


def public_status():
    policy = _policy()
    return {
        "enabled": bool(policy["workspaces"]),
        "revision": policy["revision"],
        "policy_version": 1,
    }

"""Per-call policy and timing for citation translations, isolated from other LLM work."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4


@dataclass
class ChunkTranslationTrace:
    chunk_id: str
    workspace: str
    request_id: str = field(default_factory=lambda: uuid4().hex)
    started: float = field(default_factory=perf_counter)
    queued: float | None = None
    queue_ms: float | None = None
    lookup_ms: float = 0.0
    llm_ms: float = 0.0
    api_ms: float = 0.0
    save_ms: float = 0.0
    model_attempts: int = 0
    reasoning_tokens: int = 0
    completion_tokens: int = 0
    source_chars: int = 0
    translated_chars: int = 0
    thinking_disabled: bool = False
    stage: str = "validation"
    cached: bool = False

    @contextmanager
    def measure(self, stage):
        self.stage = stage
        started = perf_counter()
        try:
            yield
        finally:
            setattr(self, f"{stage}_ms", (perf_counter() - started) * 1000)

    def metrics(self):
        return {
            key: round(value, 2) if isinstance(value, float) else value
            for key, value in {
                **vars(self),
                "total_ms": (perf_counter() - self.started) * 1000,
            }.items()
            if key not in {"started", "queued"}
        }


active_chunk_translation: ContextVar[ChunkTranslationTrace | None] = ContextVar(
    "active_chunk_translation", default=None
)


async def run_chunk_translation_llm(trace, func, args, kwargs):
    """Enter context inside the queue worker; never inherit the first caller's trace."""
    trace.queue_ms = (perf_counter() - trace.queued) * 1000
    token = active_chunk_translation.set(trace)
    try:
        with trace.measure("llm"):
            return await func(*args, **kwargs)
    finally:
        active_chunk_translation.reset(token)


def apply_chunk_translation_options(kwargs, base_url, use_azure=False):
    """Override only official DeepSeek requests made for citation translation."""
    trace = active_chunk_translation.get()
    if trace is None:
        return None
    trace.model_attempts += 1
    if not use_azure and urlsplit(str(base_url or "")).hostname == "api.deepseek.com":
        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body["thinking"] = {"type": "disabled"}
        kwargs["extra_body"] = extra_body
        kwargs.pop("reasoning_effort", None)
        trace.thinking_disabled = True
    return trace

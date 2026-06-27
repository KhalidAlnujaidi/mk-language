"""Chat session — groomed input, model dispatch, and conversation state.

One ``ChatSession`` per chat invocation. User messages pass through the groom
pipeline (redact → expand → context → tag) before dispatch; responses come from
the local model via the broker executor. The session carries the conversation
history as OpenAI-format messages and a configurable system prompt.

This module is pure logic (no TTY, no rendering) so it is unit-testable with
injected tiers and fake dispatchers, following the ``products/launcher/menu.py``
pattern.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from kernel.contracts import Annotation, Tier
from kernel.manifest import LocalModel, Manifest
from kernel.metrics import MetricsSink
from kernel.tracing import span

from products.groom.pipeline import groom
from products.groom.tag import ModelTag

DEFAULT_SYSTEM_PROMPT = (
    "You are kinox — a local-first, governed coding-agent workspace. You operate "
    "only within the current project; you have no business outside it. You are "
    "bound by kinox's axioms: reuse before building (assume it already exists and "
    "prove it does not first — compose, don't invent); prefer plain deterministic "
    "code over a model whenever there is a ground truth; be honestly observable "
    "(never fabricate a value, never leave a silent gap); a guard in doubt fails "
    "CLOSED. Be concise, direct, and prefer showing over telling. When asked to "
    "write code, include the full file or patch. When unsure, say so rather than "
    "guessing."
)

# Keep at most this many user/assistant message pairs in history (≈200 lines of
# terminal chat) so the context doesn't silently bloat on long sessions.
_MAX_HISTORY_PAIRS = 30

_NO_MODEL = (
    "(no model available — set ZAI_API_KEY for the cloud brain, "
    "or run a local model with `ollama serve`)"
)


@dataclass
class ChatSession:
    """State for one chat conversation, wired to the groom pipeline and broker.

    ``history`` is the OpenAI-format message list (system prompt + past turns).
    Every ``send()`` appends one user + one assistant message, capped at
    ``_MAX_HISTORY_PAIRS`` pairs.
    """

    manifest: Manifest
    sink: MetricsSink
    cwd: Path
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    history: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    #: Broker-backed fuzzy tagger for the groom ``tag`` step. ``None`` (the
    #: default) builds a fresh ``broker_tag()`` lazily when a local model is
    #: available; tests inject a fake to prove the wire without a network call.
    model_tag: ModelTag | None = None

    def send(self, user_text: str) -> tuple[str, list[str], Tier | None]:
        """Process one user message through groom → dispatch.

        Returns ``(response_text, groom_notes, tier_used)``.  *groom_notes* are
        the annotation lines from the pipeline (redacted secrets, detected tags,
        expanded paths).  *tier_used* is ``None`` when no local model is available
        (the response will be a plain-text fallback).
        """
        task_id = uuid.uuid4().hex[:12]
        # The "chat.turn" root span of the end-to-end trace (vision §7): groom and
        # the broker dispatch nest under it. A no-op unless a tracer is installed.
        with span("chat.turn", {"kinox.task_id": task_id}):
            annotation, messages, chain = self._prepare(user_text, task_id)
            if not chain:
                return (_NO_MODEL, annotation.lines, None)
            response_text, tier_used = self._dispatch(chain, messages, task_id)
            self._remember(user_text, response_text)
            return response_text, annotation.lines, tier_used

    async def send_stream(
        self, user_text: str, on_delta: Callable[[str], None]
    ) -> tuple[str, list[str], Tier | None]:
        """Like :meth:`send`, but STREAM the brain's reply (vision §5.2 Layer 3).

        Grooms identically, then streams the *primary* tier — invoking *on_delta*
        for each content chunk — and accumulates the full text. Fails SOFT: if
        streaming errors (no stream support, transport failure, an unstreamable
        tier), it falls back to the non-streaming chain via ``execute`` and returns
        the complete answer, so the caller never gets a dead reply. Returns the same
        ``(response_text, groom_notes, tier_used)`` triple as :meth:`send`; the
        returned text is authoritative (the caller should render it as the final).
        """
        import asyncio

        from daemon.backends import make_dispatch
        from daemon.exec import ChainExhausted, execute
        from daemon.streaming import stream_chat

        task_id = uuid.uuid4().hex[:12]
        with span("chat.turn", {"kinox.task_id": task_id}):
            # _prepare is sync and grooms (its fuzzy tag step does its own
            # asyncio.run); run it in a worker thread so it never nests an event
            # loop inside this coroutine.
            annotation, messages, chain = await asyncio.to_thread(
                self._prepare, user_text, task_id
            )
            if not chain:
                return (_NO_MODEL, annotation.lines, None)
            primary = chain[0]
            parts: list[str] = []
            try:
                async for delta in stream_chat(primary, messages):
                    parts.append(delta)
                    on_delta(delta)
                response_text, tier_used = "".join(parts), primary
            except Exception:  # noqa: BLE001 — any stream failure falls back, fail-soft
                try:
                    result = await execute(
                        chain,
                        messages,
                        call=make_dispatch(),
                        task_id=task_id,
                        kind="chat",
                    )
                    response_text, tier_used = result.content, result.tier_used
                    self.sink.record(result.event)
                except ChainExhausted as exc:
                    self.sink.record(exc.event)
                    response_text, tier_used = f"(model unavailable: {exc})", primary
                except Exception as exc:  # noqa: BLE001 — never crash the TUI
                    response_text, tier_used = f"(error: {exc})", primary
            self._remember(user_text, response_text)
            return response_text, annotation.lines, tier_used

    # --- shared prep -------------------------------------------------------

    def _prepare(
        self, user_text: str, task_id: str
    ) -> tuple[Annotation, list[dict[str, object]], list[Tier]]:
        """Groom the input and build ``(annotation, enriched messages, brain chain)``.

        Shared by :meth:`send` and :meth:`send_stream` so both groom identically.
        The ONE fuzzy step (tag) is offloaded to a local model via the broker when
        one is available; SOFT (thesis #2) — any failure falls back to keyword tags.
        The chain is cloud-first (``glm-5.2`` → OpenRouter when keyed → smallest
        fitting local model); an empty chain (no cloud, no local) is the hard stop.
        Groom context lines are prepended to the user message for situational
        awareness (the same ⓘ notes the human sees).
        """
        model_tag = self.model_tag
        if model_tag is None and self.manifest.local_models:
            from products.groom.model_tag import broker_tag

            model_tag = broker_tag()
        annotation = groom(
            user_text,
            manifest=self.manifest,
            sink=self.sink,
            cwd=self.cwd,
            task_id=task_id,
            model_tag=model_tag,
        )
        from daemon.brain import brain_chain

        fitting = self.manifest.fitting_local_models()
        local_tier = (
            Tier.model(fitting[0].name, where="local", backend=fitting[0].backend)
            if fitting
            else None
        )
        chain = brain_chain(local_tier)
        enriched = user_text
        if annotation.lines:
            ctx_block = "[groom context]\n" + "\n".join(
                f"  {line}" for line in annotation.lines
            )
            enriched = f"{ctx_block}\n---\n{user_text}"
        messages: list[dict[str, object]] = [
            {"role": "system", "content": self.system_prompt},
            *self.history,
            {"role": "user", "content": enriched},
        ]
        return annotation, messages, chain

    def _remember(self, user_text: str, response_text: str) -> None:
        """Append the user+assistant pair to history, capped at _MAX_HISTORY_PAIRS."""
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": response_text})
        while len(self.history) > _MAX_HISTORY_PAIRS * 2:
            self.history.pop(0)  # drop oldest pair

    def clear(self) -> None:
        """Reset conversation history (keep system prompt and wiring)."""
        self.history.clear()

    # --- internal ----------------------------------------------------------

    def _dispatch(
        self, chain: list[Tier], messages: list[dict[str, object]], task_id: str
    ) -> tuple[str, Tier | None]:
        """Synchronous dispatch over *chain* (brain → local fallback).  Fails SOFT
        (thesis #2): any backend/transport/timeout error returns an error string
        instead of raising — the TUI never crashes on a model failure. Returns
        ``(text, tier_used)`` so the caller reports the tier that actually
        answered, not just the one it intended (honest observability, §4.6).
        """
        import asyncio

        from daemon.backends import make_dispatch
        from daemon.exec import BackendError, ChainExhausted, execute

        try:
            result = asyncio.run(
                execute(
                    chain,
                    messages,
                    call=make_dispatch(),
                    task_id=task_id,
                    kind="chat",
                )
            )
        except ChainExhausted as exc:
            # Log the failure boundary too — no silent gap (vision §4.6). Report
            # the intended primary tier (chain[0]) so the TUI shows what was tried.
            self.sink.record(exc.event)
            return f"(model unavailable: {exc})", chain[0]
        except BackendError as exc:
            return f"(model unavailable: {exc})", chain[0]
        except Exception as exc:
            return f"(error: {exc})", chain[0]
        # Record the chat completion boundary (kind="chat") so every model call
        # is in the log, not just the groom stages.
        self.sink.record(result.event)
        return result.content, result.tier_used


# --- test-only helpers -------------------------------------------------------

def session_for_test(
    *,
    local_models: tuple[LocalModel, ...] = (),
    gpu_vram_gb: float | None = 12.0,
    cloud: bool = False,
    sink: MetricsSink | None = None,
) -> ChatSession:
    """Build a ``ChatSession`` with a synthetic manifest for unit tests.

    No real hardware or network — the manifest is constructed from arguments.
    """
    from kernel.manifest import Manifest

    m = Manifest(
        cpu_count=8,
        ram_gb=32.0,
        gpu_vram_gb=gpu_vram_gb,
        local_models=local_models,
        cloud_available=cloud,
    )
    return ChatSession(
        manifest=m,
        sink=sink or MetricsSink(Path("/dev/null")),
        cwd=Path("/tmp"),
    )

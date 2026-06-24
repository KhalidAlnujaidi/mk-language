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
from dataclasses import dataclass, field
from pathlib import Path

from kernel.contracts import Tier
from kernel.manifest import LocalModel, Manifest
from kernel.metrics import MetricsSink

from products.groom.pipeline import groom
from products.groom.tag import ModelTag

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful coding assistant running inside kinox — a local-first, "
    "governed coding-agent workspace. Be concise, direct, and prefer showing "
    "over telling. When asked to write code, include the full file or patch. "
    "When unsure, say so rather than guessing."
)

# Keep at most this many user/assistant message pairs in history (≈200 lines of
# terminal chat) so the context doesn't silently bloat on long sessions.
_MAX_HISTORY_PAIRS = 30


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
        models = self.manifest.local_models

        # Step 1: Groom the input (redact → expand → context → tag). The ONE
        # fuzzy step (tag) is offloaded to a local model via the broker when one
        # is available — so the boundary record logs ``tier: model:local`` rather
        # than ``deterministic``. SOFT (thesis #2): any backend failure falls
        # back to deterministic keyword tags; no model means no offload at all.
        model_tag = self.model_tag
        if model_tag is None and models:
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

        # Step 2: Use the first available local model (Ollama manages memory).
        if not models:
            return (
                "(no local model available — run `ollama serve` and pull a model)",
                annotation.lines,
                None,
            )
        tier = Tier.model(
            models[0].name, where="local", backend=models[0].backend
        )

        # Step 3: Build the messages payload, with groom context pre-injected.
        # Context lines (redacted secrets, expanded paths, git/fs state, tags)
        # are prepended to the user message so the model has situational
        # awareness — the same information the human sees as ⓘ notes.
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

        # Step 4: Dispatch to the model via the broker executor.
        response_text = self._dispatch(tier, messages, task_id)

        # Step 5: Update history, capped at _MAX_HISTORY_PAIRS pairs.
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": response_text})
        while len(self.history) > _MAX_HISTORY_PAIRS * 2:
            self.history.pop(0)  # drop oldest pair

        return response_text, annotation.lines, tier

    def clear(self) -> None:
        """Reset conversation history (keep system prompt and wiring)."""
        self.history.clear()

    # --- internal ----------------------------------------------------------

    def _dispatch(
        self, tier: Tier, messages: list[dict[str, object]], task_id: str
    ) -> str:
        """Synchronous dispatch to the local model.  Fails SOFT (thesis #2):
        any backend/transport/timeout error returns an error string instead of
        raising — the TUI never crashes on a model failure.
        """
        import asyncio

        from daemon.backends import make_dispatch
        from daemon.exec import BackendError, ChainExhausted, execute

        try:
            result = asyncio.run(
                execute(
                    [tier],
                    messages,
                    call=make_dispatch(),
                    task_id=task_id,
                    kind="chat",
                )
            )
        except ChainExhausted as exc:
            # Log the failure boundary too — no silent gap (vision §4.6).
            self.sink.record(exc.event)
            return f"(model unavailable: {exc})"
        except BackendError as exc:
            return f"(model unavailable: {exc})"
        except Exception as exc:
            return f"(error: {exc})"
        # Record the chat completion boundary (kind="chat") so every model call
        # is in the log, not just the groom stages.
        self.sink.record(result.event)
        return result.content


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

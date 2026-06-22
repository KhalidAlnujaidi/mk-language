# Broker brick 1 — minimal real Model Control Plane

**Status:** approved design (2026-06-22) · **Branch:** `m1-broker` · **Milestone:** M1, brick 1
**Traces to vision:** §5.3 (the broker), §5.4 (ground-truth taxonomy), §4.6 (honest observability), thesis #1 (asymmetry), thesis #2 (fail-direction).

## 1. Purpose

A `daemon/` service that *executes* a chat request on the best available local
model, with a fallback chain, one model at a time, on a Unix domain socket,
emitting one `EventRecord` per call.

This is the **smallest broker that is real**: it forces the kernel's
`Manifest` / `Tier` / `EventRecord` contracts to be honest under a live
execution path, without building the full §5.3 control plane.

It consumes kernel contracts; the kernel never imports it. The existing
`tests/test_architecture.py` guard ("`kernel/` imports nothing from
`products/`, `adapters/`") is extended in spirit: `daemon/` may import
`kernel/`, never the reverse.

## 2. Scope

### In
- OpenAI-compatible `POST /v1/chat/completions` over a **Unix domain socket**.
- A **fallback chain** derived from the machine manifest: preferred/smallest
  local model → smaller local models → cloud (if a key exists).
- **Single-slot serialization**: only one inference in flight at a time
  (kinox-side), complementing Ollama's `OLLAMA_MAX_LOADED_MODELS=1`.
- **Honest observability**: one `EventRecord` (existing kernel contract) per
  call, appended as JSONL; tokens exact from Ollama, VRAM-delta best-effort and
  labeled, `None` on failure.
- `GET /broker/status` and `GET /broker/route` (debug, no execution).

### Out (deferred — named, not silently dropped)
Capability canary / quarantine · semantic cache · priority queue (brick 1 is
**FIFO**) · vLLM / llama.cpp backend adapters · **the vast.ai swarm remote
tier** (slots in later as a `where="remote"` Tier in the same chain) ·
OpenTelemetry trace propagation (that is the *observability* brick).

## 3. Dependencies

Added in `daemon/` **only** — the kernel stays stdlib-only (Rule Zero exception
for the pure core; the dependency is pushed to the outer layer):
- `fastapi` + `uvicorn` — reuse, not a hand-rolled HTTP server. `uvicorn`'s
  `--uds` gives the Unix socket bind for free.
- `httpx` — the async HTTP client to Ollama's `/v1`.

Backend: **Ollama**, which is already OpenAI-compatible at `/v1/chat/completions`.
No LiteLLM in brick 1 — with a single backend the fallback loop is ~40 lines and
fully ours. LiteLLM is reconsidered only when a 2nd backend (vLLM / cloud)
actually appears.

## 4. Components

Each is independently testable; the I/O boundary is injected so no live Ollama
is required for the unit tests.

### 4.1 `daemon/fallback.py` — chain builder (pure)
```
build_chain(manifest: Manifest, preferred: str | None) -> list[Tier]
```
- Reuses `manifest.available_tiers()` (already ordered: deterministic first,
  then local models smallest-VRAM-first, then cloud).
- Filters to **model tiers** (drops `Tier.deterministic()`).
- If `preferred` is given and present in the list, the chain **starts at it**,
  then continues with the remaining tiers in manifest order (smaller locals,
  then cloud).
- If `preferred` is absent/unknown, the chain is the full model-tier list as-is
  (smallest local first → cloud).
- Returns `[]` when no model tier exists (caller fails soft — see §6).
- Pure function, zero I/O → exhaustively unit-testable.

### 4.2 `daemon/exec.py` — executor (I/O injected)
```
async execute(chain, messages, *, call, task_id) -> ExecResult
```
- `call: Callable[[Tier, list[dict]], Awaitable[BackendResponse]]` is the
  injected transport (real one wraps httpx → Ollama; tests pass a fake).
- Walks `chain`: try a tier → on a **retryable** failure (OOM / timeout /
  HTTP 5xx / connection error) fall to the next tier; on success return.
- Returns `ExecResult(content, tier_used, event)` where `event` is an
  `EventRecord`:
  - `tokens_in` / `tokens_out` taken **exact** from Ollama's response →
    `tokens_exact=True`. A cloud tier would set `False` (estimate).
  - `latency_ms` measured around the successful call.
  - `correction_of=None` here (the correction detector stamps it elsewhere).
- If the chain is exhausted, raises `ChainExhausted` (the server turns this into
  a soft OpenAI-shape error — §6).

### 4.3 `daemon/serializer.py` — single-slot guard
- An `asyncio.Semaphore(1)` wrapper so only one inference runs at a time.
- Tested by firing concurrent calls at a slow fake backend and asserting they
  execute strictly one-at-a-time (observed max-concurrency == 1).

### 4.4 `daemon/server.py` — FastAPI app + Unix socket
- `POST /v1/chat/completions` — OpenAI-shape request in, OpenAI-shape completion
  out. Optional `model` field pins the preferred tier; absent/`"auto"` → smallest
  local. Acquires the serializer slot, builds the chain from a fresh
  `manifest.probe()`, calls `execute`, appends the `EventRecord`, returns.
- `GET /broker/status` — `{manifest summary, last_tier_used, recent_events[]}`.
- `GET /broker/route?model=…` — returns the computed fallback chain **without
  executing** (debug / test aid).
- Launch: `uvicorn daemon.server:app --uds /run/kinox/broker.sock` (socket path
  configurable via env; parent dir created if absent).

### 4.5 Observability glue
- Reuses `kernel/metrics.py` to append each `EventRecord` as JSONL.
- VRAM-delta: best-effort sample around the call reusing the manifest's
  `nvidia-smi` pattern; **labeled and `None` on failure** — never a fabricated
  zero (§4.6 / honest observability). Carried as an extra obs field, not forced
  into the frozen `EventRecord` contract if it would require a kernel change;
  if a field is needed it is added to `EventRecord` deliberately and tested.

## 5. Data flow

```
OpenAI client ──(Unix socket)──▶ POST /v1/chat/completions
   │
   ├─ serializer.acquire()              # one slot
   ├─ manifest.probe()                  # fresh machine snapshot (kernel)
   ├─ build_chain(manifest, preferred)  # daemon/fallback.py  (pure)
   ├─ execute(chain, messages, call=httpx_ollama, task_id)   # daemon/exec.py
   │     └─ for tier in chain: try call(tier) → success | next
   ├─ metrics.append(event)             # kernel/metrics.py → JSONL
   └─ return OpenAI-shape completion
```

## 6. Error handling & fail-direction

The broker is an **optimizer, not a guard → it fails SOFT** (thesis #2):
- A single tier failing is absorbed by the fallback walk.
- A fully-exhausted chain returns a clean OpenAI-shape **error response**
  (HTTP 503 + OpenAI `error` object), never an unhandled crash that takes down
  the caller.
- `manifest.probe()` already never raises; an empty chain yields the same soft
  error.
- All failure paths still emit an `EventRecord` (with the failing/last tier and
  `tokens_*=None`) so the log never has a silent gap.

## 7. Test plan (TDD — red first, no live Ollama)

| Layer | Tests |
|---|---|
| `fallback.py` | preferred-pinned ordering; preferred-absent ordering; preferred-unknown falls back to full list; empty manifest → `[]`; cloud appended last |
| `exec.py` | success on first tier; fall-through on injected OOM/timeout/5xx; exact-token capture; `ChainExhausted` on all-fail; `EventRecord` shape on success **and** failure |
| `serializer.py` | concurrent calls serialize (max observed concurrency == 1); slot released on exception |
| `server.py` | FastAPI `TestClient` over Unix socket with a **stub backend**: happy path returns OpenAI shape; exhausted chain → 503 error object; `/broker/route` returns chain without executing; `/broker/status` shape |
| architecture | `daemon/` imports `kernel/`; `kernel/` still imports nothing outward (extend existing `test_architecture.py`) |

All backend I/O is injected, so the suite runs offline in CI (no GPU, no Ollama).

## 8. Build order (for the plan)

1. `daemon/fallback.py` (pure, no deps) — TDD first; unblocks everything.
2. `daemon/exec.py` (injected `call`) — TDD with fakes.
3. `daemon/serializer.py` — TDD with a slow fake.
4. `daemon/server.py` — wire 1–3 + httpx→Ollama transport; TestClient tests.
5. Observability glue + architecture-test extension.
6. `pyproject.toml`: add `fastapi`, `uvicorn`, `httpx` to the daemon extra/group.

Components 1–3 are independent and can be fanned out to parallel subagents;
4–5 integrate them.

## 9. Out-of-scope confirmation

This brick does **not** touch: the groom pipeline, the claude_code adapter, the
correction detector, or the cloud-key handling beyond what `manifest.probe()`
already reports. It adds a new top-level `daemon/` surface and nothing else.

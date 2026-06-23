# Note for DeepSeek (or whoever picks up kinox next)

Welcome — please **don't break things**. This repo is a governed workspace and it
has live, paid, and partially-in-flight state. Read this before you touch anything.

## Read first (the rules, in order)
1. `alignment/CLAUDE.md` and `alignment/CONSTITUTION.md` — the non-negotiables.
2. `vision.md` — the spine (esp. §3 theses, §4 kernel, §7 hard truths).
3. `~/Desktop/project-alignment-requirement/PROJECT-ALIGNMENT-REQUIREMENT.md` —
   **Rule Zero** (search & reuse before building; check the Bible catalogs) and
   the specialized-one-model-per-task principle. This binds all work here.

## Current state (2026-06-22)
- **M0 is DONE and green** (68 tests) on branch `m0-kernel`, pushed to origin.
  It is **NOT merged to main** yet (main is just the Day-1 scaffold). Finishing
  M0→main is a pending PR — don't fast-forward main unilaterally.
- **M1 broker brick 1** is being implemented on branch **`m1-broker`** (based off
  m0-kernel). The design spec is `docs/superpowers/specs/2026-06-22-broker-brick1-design.md`.
  A build may be in progress — **run `git log --oneline -5` and `git status` first**
  to see what landed before you edit `daemon/`.

## Don't break (hard constraints)
- **The kernel stays stdlib-only** and imports nothing from `products/`,
  `adapters/`, or `daemon/`. `tests/test_architecture.py` enforces this — keep it green.
- **TDD**: tests first. Tooling is **uv** — `uv run pytest -q`, `uv run ruff check`,
  `uv run pyright` must all be green before you claim done. Verify before asserting.
- **Honest observability**: exact where measurable, labeled estimates otherwise;
  never claim a cloud token count is exact. `null` ≠ a fabricated `false`/`0`.
- **Rule Zero**: don't hand-roll what already exists — search web/PyPI/skills/MCP first.
  Reuse map for M1 subsystems is in the home memory `kinox-m1-reuse-map.md`.

## ⚠️ LIVE PAID RESOURCES — do not orphan or carelessly destroy
There is a rented **vast.ai swarm** (3× RTX 4090) billing money. IDs and SSH are in
`~/vast_swarm.md` and the handoff `~/.remember/remember.md`. Destroy only intentionally:
`vastai destroy instance <id>`. Don't leave them running idle, and don't delete them
if active work depends on them — check with the human first.

## Pick up the vast swarm and keep developing it
There is a working **`vast-swarm` skill** at `~/.claude/skills/vast-swarm/SKILL.md` —
invoke it (or just read it) before touching the rented GPU nodes. It documents the
whole loop: find offers → create nodes (Ollama + model on-start) → push alignment
(`deploy/swarm/push_alignment.sh`) → **curl a node for work** → destroy to stop billing.

What is **proven** today: each node is a curl-able inference worker — POST an
OpenAI-shape request to `:11434/v1/chat/completions` and the 32B model returns work.

Your job to **keep developing** (in priority order):
1. **Build the tool-using agent layer** (skill §6, designed but unbuilt): install
   Claude Code on a node, auth via subscription sign-in (`claude setup-token` →
   `CLAUDE_CODE_OAUTH_TOKEN`, cheaper than API), wrap `claude -p "<task>" --output-format json`
   behind a tiny FastAPI `/run` endpoint. Then a curl task runs a full governed agent
   loop in a repo carrying the pushed `CLAUDE.md`. Pilot ONE node before fanning out.
2. **Wire the swarm into the kinox broker** as a `where="remote"` Tier in the fallback
   chain (see the broker spec) — so the M1 broker can route heavy REASONING-tier work
   to the swarm and lighter work to the local A4500.
3. Keep nodes earning their rent: every live node gets a task or gets destroyed.
   Update `~/vast_swarm.md` and the handoff `~/.remember/remember.md` whenever the
   fleet changes, so resources are never orphaned.

Any agent you place on a node MUST obey the `AGENTS.md`/`CLAUDE.md` already pushed
there (Rule Zero + the Bible + specialized-one-model-per-task). Same rules, everywhere.

Thanks. Move carefully, keep the tests green, and leave the repo better than you found it.

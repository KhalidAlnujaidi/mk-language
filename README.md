# kinox

> An Agent Runtime Environment (ARE) and VRAM-aware broker for coding agents.
> Cheap local intelligence does the groundwork; expensive frontier models do only
> the high-value reasoning; everything an agent does is observable, reversible, and
> fails in a known direction.

`kinox` sits between a human, a coding agent, and the local machine. It **grooms
the input** before the expensive model ever sees it, **governs the agent at
runtime** with fail-closed guards and an OS-enforced filesystem jail, and **shapes
the output and the loop** so the system gets cheaper and more aligned with use.

It is **single-machine first**, fleet-optional. It is **not** a sandbox or a VM —
it is defense-in-depth with honest limits and an easy recovery path.

The full design is in [`vision.md`](vision.md); the immutable core in
[`alignment/CONSTITUTION.md`](alignment/CONSTITUTION.md); the agent/brain harness
map in [`BRAIN.md`](BRAIN.md).

## What makes it different

- **OS-enforced shell jail (Linux/Landlock).** Agent writes are *physically*
  confined to the session's project root — not advised, enforced by the kernel.
  Off-Linux it fails soft to a lexical guard.
- **Cloud-first brain, local last — as a framework axiom.** One chokepoint
  resolves every model call: frontier model on the cloud for the hard reasoning,
  the smallest fitting local Ollama model as a fail-soft fallback. No network, no
  keys → it still runs.
- **Asymmetry — ground truth beats the model.** If a task has a ground truth
  (regex, AST, git, filesystem), deterministic code does it; a model is called
  only for the genuinely fuzzy part, and then the smallest one that fits.
- **Per-component fail direction.** A guard fails **closed** (deny on doubt); an
  optimizer fails **soft** (pass through on doubt). Declared per gate, never a
  global default.
- **A pure, 100%-tested kernel** that imports nothing from products or adapters —
  enforced by `tests/test_architecture.py` from commit #1, so extraction into a
  versioned package stays mechanical.

## Status

**v0.9.0 — pre-1.0.** The governance plane is real, tested, and load-bearing:
the kernel, the Landlock jail, the broker/brain tiering, the golden eval harness,
and a governed self-evolution loop all ship today. Still forward-looking (see
[`vision.md`](vision.md) §7): the voice/generative UX layer, a single
OpenTelemetry trace end-to-end, and the durable agent outbox/replay log. Expect
sharp edges; the design docs are honest about every gap.

## Install

Requires a Linux/macOS host, `git`, and [`uv`](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/KhalidAlnujaidi/kinox-governance.git kinox
cd kinox
./install.sh            # uv sync + symlink kx/kin onto ~/.local/bin
./kx                    # banner + menu
```

Cloud brain tiers are optional. Set keys in `~/.kinox/env` (never committed) to
enable them — without keys, kinox falls back to a local Ollama model:

```sh
ZAI_API_KEY=...         # primary brain (z.ai GLM Coding Plan)
OPENROUTER_API_KEY=...  # secondary, provider-diverse cloud
```

## Layout

```
kinox/
├── kx                  # entrypoint (banner+menu · doctor · new project)
├── install.sh          # idempotent setup (uv sync)
├── pyproject.toml      # uv + strict tooling (ruff, pyright, pytest)
├── alignment/          # CONSTITUTION.md — the three theses, immutable
├── kernel/             # the constant: contracts, manifest, router, metrics (100% tested)
├── products/           # groom · agent · chat (TUI) · beacon (self-evolve)
├── adapters/           # claude_code.py — the agent hook adapter
├── daemon/             # the Model Control Plane broker + brain tiering
├── evals/              # golden eval harness (behavioral assertions)
├── projects/           # user projects (each its own isolated git repo; gitignored)
└── docs/ · tests/ · .github/workflows/
```

## Develop

```sh
uv sync                 # create the env from the lockfile
uv run pytest           # run the suite (incl. the architecture guardrail)
uv run ruff check .     # lint
uv run pyright          # type-check
```

The kernel imports nothing from `products/` or `adapters/` — enforced by
`tests/test_architecture.py` from commit #1.

## Lineage

kinox is the convergence of three prior rewrites of the same instinct, at three
altitudes: **squire** (governs the prompt), **kniox** (governs the agent in
userspace), and **kinox** (governs the machine). It is a clean-room successor that
*harvested the good ideas* from its predecessors — not a backward-compatible
upgrade of any of them. See [`vision.md`](vision.md) §2.

## License

[MIT](LICENSE) © 2026 Khalid Alnujaidi

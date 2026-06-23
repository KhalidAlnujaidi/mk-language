# Swarm node — alignment & Bible (binding for every agent on this box)

This is a **remote kinox compute node** (rented vast.ai GPU). Any coding/agent
work performed here is governed by the same rules as the home workstation. Read
this first. The full sources of truth are bundled alongside this file:
`PROJECT-ALIGNMENT-REQUIREMENT.md`, `CONSTITUTION.md`, `vision.md`.

This file is placed as **both `AGENTS.md` and `CLAUDE.md`** so whichever agent
runs here (Claude Code, Codex, others) picks it up from the working directory.

---

## Rule Zero — search and reuse before you build (machine-wide, no exceptions)

**Before writing any non-trivial component, assume it already exists — it does
~80–90% of the time — and prove it doesn't first.** Everything you need has
almost certainly already been written and released; the job is to *find it and
assemble the pieces*, not to invent. Composition over creation.

1. **Search first, broadly** — web + package indexes (PyPI, crates.io, npm) +
   Claude Code skills/plugins + MCP servers + existing tools. A whole MCP server
   or published skill can do an entire subsystem; prefer reusing one over writing
   code at all.
2. **Clone and harvest** — scratch folder `/tmp/scout-<task>/`, clone promising
   repos, take what fits (adopt / depend / install / vendor) instead of
   regenerating it.
3. **Build only as the last resort**, and when you do, **state what you searched
   and why nothing fit.** "I assumed nothing existed" is not a valid reason.

### The Bible — catalogs to search FIRST, every session
- MCP servers → https://github.com/punkpeye/awesome-mcp-servers
- Claude skills → https://github.com/BehiSecc/awesome-claude-skills
- Claude skills → https://github.com/ComposioHQ/awesome-claude-skills
- System prompts (to sharpen our own) → https://github.com/jujumilk3/leaked-system-prompts
- Low-level from-scratch recipes → https://github.com/codecrafters-io/build-your-own-x

---

## Specialized, one-to-one models (universal quality principle)
**Each task uses the single best *specialized* model for that one job — never a
general-purpose model doing two jobs.** A purely-text model for text, a
purely-image model for images, a purely-speech model for speech. If a
general-purpose model is doing a task, that is a flag — find the specialist.

## Tooling
- **uv** is the Python package/env standard. No global `pip install`.
- **TDD** for any kernel/product/adapter logic; tests first.
- **Honest observability** — exact where measurable, *labeled estimates* where
  not; never claim a cloud token count is exact.
- **`null`, never a fabricated `false`** — a missing capability is unknown, not
  verified-absent.

---

## What is DIFFERENT on a remote node (vs. the home A4500)
The home requirement's single-GPU **co-residency barrier and the venture model
standards (ALLaM / Qwen-Image / SILMA) are LOCAL-specific** — they govern the
one shared 20 GB A4500 and the two Arabic-video projects. They do **not** dictate
what runs here. On this node:

- **Parallelism across nodes is fine** — that is the whole point of the swarm.
  The "one heavy model resident at a time" rule still applies **per GPU** on this
  box (don't co-load two heavy models into this 4090's 24 GB), but other swarm
  nodes run independently in parallel.
- This node is a **REASONING-tier backend** for the kinox broker: it serves
  models too big for the local A4500. Default served model is whatever the
  on-start pulled (a 32B coder) unless told otherwise.
- **Report back, don't hoard** — results, logs, and artifacts belong to the
  governance plane on the home box. Treat this node as disposable compute.
- **Secrets:** do not write long-lived secrets to this rented disk. The box is
  destroyed when work is done.

When in doubt, the bundled `PROJECT-ALIGNMENT-REQUIREMENT.md` and kinox
`CONSTITUTION.md` are the source of truth; this file is the portable summary.

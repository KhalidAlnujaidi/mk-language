# CHEAT CODE — Natural-language → OS-operations abstraction layer (AIOS + CoRE corpus)

> Prime directive (Axiom 2, REUSE DON'T REINVENT): you are NOT inventing from zero.
> A proven corpus exists. ADOPT its structures and compose them. Build from scratch
> only what the corpus does not already give you, and say why.

## What you are designing (scope & purpose)
A small, **deterministic** abstraction layer: a *structured* natural-language interface
to a computer's operating system. **Not** a from-scratch general programming language,
and **not** a compiler — an **interpreter** that turns structured human *intent* into
**safe, verifiable OS operations** (files, directories, text, processes). The minimal
"AI-agent OS" interface: a human states intent in a constrained, unambiguous form; the
layer maps it to deterministic system operations and runs them in a sandbox.

The test of done is NOT a vote on prose. It is: a program of intents **executes to the
expected OS outcome** (a file exists with the right bytes, a listing matches, …). Ground
truth beats model.

## Corpus A — AIOS: AI Agent Operating System
Repo: https://github.com/agiresearch/AIOS · Paper: arXiv:2403.16971
Install (the reference cheat code): https://docs.aios.foundation/aios-docs/getting-started/installation
MCP docs: https://docs.aios.foundation/aios-docs/~gitbook/mcp

- **LLM-as-OS.** Three layers — application / kernel / hardware — mirroring a real OS.
  Agents are *applications*; they never touch resources directly.
- **System calls behind managers.** Agent intent decomposes into typed **syscalls**
  dispatched to kernel managers:
  - Scheduler (queue + fair dispatch), Context Manager (snapshot/restore state),
    Memory Manager, Storage Manager (files / versions / vector store), Tool Manager,
    and **Access Manager — privilege control that REQUESTS USER CONFIRMATION FOR
    IRREVERSIBLE OPERATIONS.**
- **LLM wrapped as a "core"** (like a CPU core) so any backend plugs in uniformly.
- Install shape: `git clone …/AIOS`, venv, `uv pip install -r requirements.txt`, then
  the Cerebrum SDK (`…/Cerebrum`, `uv pip install -e .`).

**Lesson for us:** model the OS as a *small set of typed syscalls* behind managers.
Make every irreversible op (delete, overwrite) require explicit confirmation —
fail-CLOSED. Keep agent logic separate from resource access.

## Corpus B — CoRE: LLM as interpreter of natural-language programs
Paper: arXiv:2405.06907 · (see also SSRN 6467298)

- **Natural language is the source; an interpreter executes it.** Ambiguity is defeated
  by *structure*, not by hoping the model guesses right.
- **The structured intent unit** (adopt this shape):
  `Step Name ::: Step Type ::: Step Instruction ::: Step Connection`
  - Step Type ∈ { **Process** (do a thing), **Decision** (branch), **Terminal** (end) }.
  - Connection names the next step(s) → this gives you control flow for free.
- **Control flow from steps:** Sequence (point forward), Selection (Decision branches),
  Iteration (Decision points backward).
- **Per-step execution loop:** Observation Retrieval (recall prior results from memory)
  → Input/Plan construction → Output/Tool analysis (invoke a tool if needed) →
  Branching analysis (pick the next step).
- **Principle — human-in-the-loop:** humans *write* the intent program; the layer
  *interprets* it. It does not fabricate solutions.

**Lesson for us:** define a DETERMINISTIC structured-intent schema (like the 4-field
step), parse it into a logic graph, then execute. Determinism means identical intent →
identical OS effect → verifiable.

## The structural axioms for the intent layer (the brief)
1. **Deterministic Intent Schemas.** Structured intent blocks (declared inputs, expected
   outputs, constraints) — never raw free text. Identical input → mathematically
   equivalent, verifiable output.
2. **Abstract Syntax Graph (ASG) intermediate layer.** Parse intent into a logic /
   data-flow graph independent of any target syntax; validate the graph; THEN compile or
   execute it. Never translate English straight to a code string.
3. **Bi-Directional Synchronization.** The generated implementation and the intent spec
   are one shared state. A hand edit to the code reverse-updates the intent. No orphaned
   artifacts.
4. **Intent-Level Optimization.** Optimize logic, not loops: choose the implementation
   from the data/context (small set → a simple in-memory op; large → a vectorized /
   parallel / batched path).

## What any "language" needs (PL-theory pointers)
A language = **syntax** (grammar) + **semantics** (meaning) + a **type/validation**
discipline. Keep the core minimal; compose, don't special-case.
- https://en.wikipedia.org/wiki/Programming_language
- https://en.wikipedia.org/wiki/Engineered_language
- https://en.wikipedia.org/wiki/Computer_program
- https://en.wikipedia.org/wiki/List_of_programming_languages

## Non-negotiable governance (unchanged)
- **Ground truth beats model** — done = it RUNS to the expected OS outcome.
- **Minimal core**; **fail-CLOSED** on anything irreversible; everything **sandboxed**
  to a working directory (no path escape, no network, no host mutation).

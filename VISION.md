# North Star — the compressed one-to-one translator stack

> Added 2026-06-26 from the operator's far-vision. Recorded here because it has real
> validity *and* a real caveat — both are written down honestly so the project builds
> toward the strong version, not the hand-wavy one.

## The vision (as stated)

Instead of one giant general LLM with a huge input/output latent space, build **many
tiny one-to-one translators** — `English → SQL`, `English → shell`, `English → Python`,
`English → HTTP call` — each a small encoder/decoder that does *one* bounded mapping.
Train each on a **near-infinite, execution-verified dataset** the project can generate
itself. Then **stack them under an agent (a planner)** so the composite "brain" executes
domain work far faster and more accurately than a monolithic model, because its
knowledge — and therefore its latent space — is *hugely compressed*: it knows the
tech domain and nothing about history, medicine, theology, etc.

## What is SOLID (build toward this)

1. **The verifier is a near-infinite data engine — correct, and it's our superpower.**
   Because "done = it executes to the expected output" (ground truth beats model), we
   own a deterministic oracle. That means we can *generate* `(English intent, command,
   verified output)` triples at scale and **keep only the ones that actually run**
   (rejection-sampling / execution-filtered synthetic data — the same trick that
   bootstraps strong code & SQL models). The ASG is the canonical middle, so we can
   generate in *both* directions (intent→command and command→intent). This is real and
   it is the cheapest moat we have.

2. **A small specialist beats a giant generalist *on its domain*, per unit of compute —
   correct.** Narrow domain ⇒ smaller hypothesis space ⇒ less capacity needed ⇒ far
   lower latency and cost. For a tight one-to-one translation (short in → short out) a
   sub-billion-parameter translator can match or beat a 100B+ general model on the task,
   and run an order of magnitude faster. Removing irrelevant knowledge doesn't hurt a
   SQL translator; concentrating capacity on the domain can *raise* on-domain accuracy.

3. **Compression → speed and on-distribution accuracy — largely correct.** A compressed,
   domain-only model is cheaper to run and, *within its training distribution*, can be
   more accurate than a general model that's hedging across all of human knowledge.

## What needs a CAVEAT (so we build the strong version)

1. **"One-to-one" is the load-bearing assumption — and not every task is one-to-one.**
   Translation is fast and accurate when the mapping is *local and compositional*
   (clause → command). But **"build me a web app" is not a translation** — it's
   open-ended planning, architecture, cross-file coherence, and ambiguity resolution.
   So the honest architecture is: the tiny translators are **execution organs**, and you
   still need a **reasoning planner** that decomposes a fuzzy goal into a DAG of bounded,
   *translatable* sub-intents. The stack is only as good as that decomposition.

2. **The speedup is biggest where it's translation-bound, not reasoning-bound.** For
   high-volume, low-ambiguity throughput (10,000 NL→SQL queries) the win is enormous.
   For one open-ended creative build, the bottleneck is *reasoning/iteration*, not
   translation latency — so "10× faster than Gemini/Claude on a whole web app" holds for
   the translation steps, not necessarily the end-to-end task. Claim the win where it's
   real; it's still a large win.

3. **Small models generalize worse out-of-distribution.** A tiny translator is more
   brittle on phrasings it never saw. The mitigation is exactly what we already have —
   **the execution verifier catches the miss, and a repair loop (or escalation to a
   bigger model for that one step) fixes it.** Verification is what makes small-and-fast
   *safe*.

## How this extends THIS project (the roadmap it implies)

The project already embodies the first half — execution-gated, ASG-centered, one-to-one,
governed by "ground truth beats model." The vision is the continuation:

- **v02** — NL→OS interpreter (done, 11/11).
- **v03** — NL→**terminal** translator (running): the first true one-to-one *emitter*.
- **v0x — more translators:** NL→**Python**, NL→**SQL**, NL→**HTTP/API**. Each a backend
  off the same ASG. Each gets the execution-verified data generator for free.
- **Distill:** once a translator + its verifier are solid, **mass-generate verified data
  and distill a tiny specialist model** for that one mapping (the "compressed
  encoder/decoder"). The council/verifier is the teacher; the small model is the student.
- **Compose:** a lightweight **planner** decomposes a natural-language goal into a DAG of
  sub-intents and routes each to the right specialist translator — *the stacked brain*.
  Every step is execution-verified; failures repair locally or escalate. This is the
  agent that is mostly small, fast, and domain-compressed, with a thin reasoning layer
  on top.

## Grounding: the Principle of Least Generation (what MK *is*)

The operator's own principle ([Principle of Least Generation](
https://khalidalnujaidi.github.io/concepts/principle-of-least-generation/index.html)) is
the governing law this project should be built on: **"Route first, generate last."** Most
"AI generation" is retrieval in a costume; for bounded, known-shape tasks a cheap gate +
deterministic slot-fill beats a language model on cost, speed, AND safety, at **zero
generated tokens** (WikiSQL: 99.99% exact match, 0 tokens; the gate routes in ~40 ms).

This pins down the question "what do I map MK to?":

- **MK is not a generator. MK is the route-target.** MK ("machine code, with a K") is the
  bounded command vocabulary / ASG that English is *routed into* — PLG's retrieval tier
  made into a language. English → gate → **MK template (retrieved + slot-filled)** →
  execute. Generation is the rare fallback for a genuinely novel intent, not the default.
- **The four tiers map cleanly onto what we have:**
  1. **gate** — is this intent templatable? (a cheap classifier; see "computing context").
  2. **retrieve / slot-fill** — the MK template table → exact command, 0 tokens.
  3. **small assembler** — constrained decode for partial novelty.
  4. **big model / the council** — last resort, and our *teacher* (see below).
- **Built upon computing context.** The gate/router is a context lookup — recognizing
  which template an intent belongs to is an embedding classification. The Context-
  Computing result (real embeddings live in ~3 effective dimensions) is exactly what
  makes that routing cheap, compressed, and robust. So "build MK on computing context"
  = the gate is an embedding router over a low-rank context space.
- **The verifier is the data engine that MINES the templates.** Generation isn't the
  product; it's the one-time teacher. The council generates-and-verifies to discover the
  handful of patterns that cover the domain (PLG's "1082%... use a handful of patterns"),
  then PLG *retrieves* them forever. Our execution oracle turns generation into a table.
- **Safety is structural, not prompted.** A decoder told "output only SQL" still appends
  `rm -rf`; a router *structurally cannot* (PLG Finding 2). Our fail-CLOSED safety rungs
  are this exact property — and the MK terminal cell proves it: a hostile intent's payload
  is emitted as **quoted data**, never as a reachable command.

**Proof on our own domain (`plg_terminal.py`):** the council *generated* a v03 interpreter
to pass the 11 terminal rungs in ~12 min of frontier tokens. The PLG cell passes the
**same 11/11 with ZERO generated tokens, 31/31 intents routed, 0.033 ms/program**, and is
injection-proof by construction. The generated interpreter was never the point — it was
the teacher that showed the templates exist.

## One-line thesis

**Generation is a teacher, not a worker. Use the big model (the council) once to mint
execution-verified templates; then ROUTE English into MK and retrieve — least generation,
most certainty. Grow a planner that knows how to ask, over a library of tiny route-first
cells that each know one domain perfectly, on a compressed computing-context substrate.**

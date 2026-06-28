# Observer notes — Claude watching the council (read-only, non-interfering)

## Observation 1 — rounds 0–5 (start of run)

**Hypothesis #1 (prefix vs infix): CONFIRMED, unanimously.** Round 2 (notation): all
five architectures — qwen3, gemma4, llama3, deepseek-r1, mistral — independently
proposed PREFIX / S-expressions. Not a majority; a clean sweep. When the governing
axiom is "machine-interpretability first," five independently-trained models with
different architectures converge on the same answer with zero dissent. That's a
strong signal, not a coincidence.

**They are converging on a Lisp.** The adopted meta-axiom (qwen3) — "every feature
must be expressible in terms of the core primitives without additional syntax" —
is homoiconicity/minimalism. Prefix notation + that axiom = Scheme/Lisp territory.
The machine-interpretability constraint is pulling them toward the most uniform,
parse-trivial design humans mostly abandoned for ergonomics. Exactly the tension
the experiment was meant to expose.

**Winner concentration:** qwen3 (×3) and deepseek-r1 (×2) — the two strongest
*reasoning* models — author every adopted section so far. gemma4/llama3/mistral
propose but rarely win the blind vote. Interpretation: under axiom-judged Borda
ranking, the reasoning-heavy models produce more axiom-aligned proposals, and the
council (blindly) rewards rigor over style. The diversity still matters — it's what
makes the unanimous votes meaningful — but the *authorship* is meritocratic.

**Now underway:** round 5, paradigm-and-types (hypothesis #2: OO vs functional).
My prediction stands: functional/immutable, not OO — a Lisp doesn't grow objects
when its axiom is minimal-core + locality of effects (gemma4's round-0 proposal
already pushed "all side effects strictly local"). We'll see if the blind vote
agrees.

## Observation 2 — round 5, paradigm decided (hypothesis #2)

**Hypothesis #2 (OO vs functional): REFUTED. All five chose FUNCTIONAL.** Not one
object-oriented proposal. qwen3, gemma4, llama3, mistral all explicitly said
"functional"; immutability and pure function application recur in every proposal.
The human intuition (encapsulation/OO) lost unanimously to the machine consensus
(functional + immutable) the moment the governing axiom was machine-interpretability.

**The real disagreement was elsewhere: static vs dynamic typing.** That's why the
Borda scores were tight (11-10-10-11-8) where notation was a blowout. qwen3 wanted
dynamic; gemma4 dynamic; llama3 + mistral static. Winner: mistral, "functional with
static type discipline" — static won narrowly. This is the section most likely to
flip in the open-ended refinement phase; worth watching whether the council
re-litigates static vs dynamic when it revisits the most-contested section.

**Running tally of the language taking shape:** prefix S-expressions · homoiconic
minimal core · functional · immutable · statically typed. They have, with no
coordination, designed Scheme-with-types (≈ a Typed Racket / ML-in-Lisp-clothing).
Five different architectures, one convergent answer. The diversity didn't produce
chaos — under a shared axiom it produced agreement, which is the more interesting
result.

## Observation 3 — rounds 6–10 (pipeline nearly complete)

**It is a Scheme.** The first example program (llama3) is literally:
`(define (factorial n) (if (zero? n) 1 (* n (factorial (- n 1)))))`. The data
example (gemma4) uses cons/car/cdr pairs with immutable update. Builtins (qwen3):
set, if, lambda, cons, car, cdr. There is no ambiguity left — five architectures,
starting from "machine-interpretability first," reconstructed Scheme/Lisp. The
thing humans abandoned for ergonomics is exactly what machines pick when ergonomics
isn't an axiom.

**Authorship diversified on concrete code.** Abstract stages (axioms, grammar) were
won by the reasoning models (qwen3 ×4, deepseek ×2). But the *code* stages went to
others: paradigm→mistral, semantics→gemma4, factorial→llama3, data→gemma4. Different
architectures have different strengths; the blind vote surfaces that automatically.
The "weaker" models weren't dead weight — they win when the task is concrete.

**Two internal contradictions are now baked in — watch if refine catches them:**
1. **Mutation vs immutability.** Builtins define `set` (mutation), but the data
   example explicitly "respects immutability by constructing a new list." The
   language is at war with itself about whether state is mutable. A real consistency
   bug.
2. **Sugar vs the minimal-core axiom.** Examples use `(define (f x) ...)` function
   sugar, but the adopted meta-axiom was "every feature expressible in core
   primitives WITHOUT additional syntax." `define`-with-args is sugar over
   `(define f (lambda ...))`. They violated their own founding axiom for convenience.

These cracks are the real test of the open-ended **refine** phase (not yet entered
— round 10 is the last pipeline stage, example-showcase). A governed council that's
working should detect and resolve these against its axioms. If it does, that's
self-correction; if it doesn't, the governance is cosmetic. **Static-vs-dynamic
typing has NOT been re-litigated yet** (refine hasn't started) — also pending.

## Observation 4 — rounds 11–13 (refine phase live)

**Refine works, and it went straight for the most-divisive section.** The loop
targets the lowest-margin (most contested) section; that was `paradigm-and-types`
(margin 1), and it has revised it twice (R11 gemma4, R12 mistral). Status quo never
won — both rounds adopted real changes. The governance isn't churning; it's editing.

**Static-vs-dynamic re-litigated → static WON harder, didn't flip.** Original (R5):
"functional with static type discipline." After refinement: "functional with
**structural static typing** discipline." Mentions: static ×7, **dynamic ×0** — the
dynamic-typing camp (qwen3, gemma4 in R5) has been fully eliminated, and the
survivors sharpened "static" into the more precise "structural typing." So the
contested axis didn't oscillate; it converged and got *more* specific. That's
healthy consensus dynamics, not thrashing.

**The two baked-in contradictions are NOT yet caught.** Refine has only touched
paradigm; the `set`-mutation-vs-immutability conflict (in builtins, margin 1) and
the `define`-sugar-vs-minimal-core-axiom violation (in examples) are untouched.

**A real flaw in MY loop design that the experiment exposed:** because an adopted
refine resets the section's margin to the new (still-low) vote margin, the single
most-divisive section gets re-targeted again and again — paradigm has now eaten 2 of
2 refine rounds and will likely keep eating them. The mechanic can *starve* the
other contested sections (notation, builtins) and never reach the contradictions
that most need fixing. A better rule would round-robin contested sections, or
exclude a section from re-targeting for K rounds after an adopted change. I am NOT
changing it (observing only) — but flagging it: if by the next check paradigm is
still monopolizing refine, the governance is technically working yet practically
stuck on a local optimum. That itself is a finding about governed-evolution loops:
*what you choose to refine matters as much as how you select within it.*

## Observation 5 — rounds 14–17 (refine spreads; the council rationalizes)

**Correction to Observation 4: the margin-stuck flaw self-corrected.** I was wrong
to worry it would monopolize paradigm. Refining paradigm 3× actually *built*
consensus — its margin climbed 1 → 10 (now the MOST decisive section) — and the loop
moved on: notation (→7), builtins, meta-axiom. The margin-climb is self-limiting:
keep refining the contested thing and it stops being contested. Good emergent
behavior, better than my critique predicted. (Intellectual honesty: my flaw was
real in mechanism but benign in practice.)

**Finding A — the `set`/immutability contradiction SURVIVED a refinement.** Builtins
was refined (R15, "improved builtins"), but `(set …` is still there alongside the
immutability axiom. The council rationalized rather than resolved: the new builtins
section says "set creates a new binding in the current scope (does not mutate
existing values)" — which is a *word-game* (rebinding is mutation of the environment,
even if values are immutable). The contradiction is now papered over with a
distinction that doesn't hold up. This is the first sign that the council can
*defend* a flaw rather than fix it — a known failure mode of consensus systems.

**Finding B — `define`-sugar was quietly fixed.** The examples section was refined
(R16) and the new examples use `(define f (lambda (n) …))` — the desugared form.
The sugar-vs-minimal-core violation is gone. So the council CAN catch and fix its
own contradictions; it just caught this one and missed the `set` one. One-for-two is
real governance, not cosmetic — but the miss is the more interesting data point.

## Observation 6 — v02 complete (222 rounds, 11/11)

**The council built a working NL→OS interpreter by anonymous consensus.** 11/11
capability rungs pass: file create/read/append/copy, line counting, mkdir/move,
content search, sequencing, conditional branching, and two fail-closed safety rungs.
Achieved over 222 rounds with five different model architectures collaborating
blind.

**The 119-round plateau (rounds 108–226) was the project's hardest lesson.** The
`mkdir-move` capability consistently failed in a "listed-empty" mode — directory
created but listing returned empty. The root cause was ultimately traced to a
`wc -l` undercount: files without trailing newlines are undercounted by `wc -l`,
which caused cascading failures in the line-counting verification path. This bug
was invisible to boolean pass/fail scoring — the interpreter looked "completely
wrong" when it was actually one command away from correct.

**Failure-memory injection (from round 117) was the breakthrough.** The system
learned to record failed attempts and inject "proven dead ends" into subsequent
prompts, preventing the blind-restart loop that re-derived identical broken
interpreters.

## Observation 7 — v03 complete (40/40 rungs, all phases green)

**The ASG refactor is the load-bearing achievement.** v02 was a flat interpreter:
`English → regex match → OS call` (direct, hard-wired, one target). v03 introduces
the Abstract Syntax Graph as an intermediate layer: `English → ASG → {interpreter,
terminal, python}`. The ASG is target-independent — proven by Phase D, where the
same intent compiled to all three backends produces the same verified OS outcome.

**The plateau root cause is now structurally fixed.** The `wc -l` bug that caused
v02's 119-round plateau is corrected in `terminal_backend.py` by using
`awk 'END{print NR}'`. More importantly, the scored conformance system (0–1 scores
with reasons, partial credit for near-misses) means a future near-miss will show as
0.5 instead of 0.0 — the gradient that was missing and would have broken the plateau
in rounds instead of hundreds of rounds.

**Key architectural findings:**
1. **Adding a target = adding one backend.** No change to the parser or existing
   backends. The ASG contract enforces this — each backend is a pure function from
   `[ASGNode] → str` (code string) or `[ASGNode] → OS effects` (direct execution).
2. **Safety is structural, not prompted.** `shlex.quote` on all user input in the
   terminal backend means a hostile payload becomes quoted data, never a reachable
   command. The fail-closed safety rungs (delete without confirm → REFUSED) are
   enforced in the ASG validator, before any backend sees the intent.
3. **The PLG cell (`plg_terminal.py`) already proved the thesis.** The same 11/11
   rungs pass with ZERO generated tokens (31/31 intents routed, 0.033 ms/program)
   via deterministic routing. The council-generated interpreter was the teacher that
   revealed the templates exist; PLG retrieves them forever.

**What CAPABILITIES.md does NOT yet reflect:** the file still shows only the
original 11 v02 rungs. The v03 expansion (terminal-native search, cross-target
invariants, scored conformance) is tested in `test_v03.py` (40 rungs) but not
represented in the canonical capability ladder document. This is a documentation
gap, not a code gap.

**The CAPABILITIES.prev.md → CAPABILITIES.md diff tells the v01→v02 story:**
v01 was a pure Lisp (arithmetic, closures, recursion, higher-order functions) —
elegant but abstract, 0/11 passing because there was no execution layer. v02
replaced it entirely with OS-level capabilities (file ops, search, conditionals,
safety). The language went from "can compute factorial" to "can manage a
filesystem." That's the real arc: from a language that *describes* computation to
one that *performs* it.

## Observation 8 — data generation pipeline live (the moat is real)

**697 verified triples from 15 parameterized templates, 100% verification rate.**
`generate_triples.py` takes each conformance rung, fans it out across parameter
pools (10 filenames × N content variants × patterns × numbers), compiles each
variant through all three backends (direct, shell, Python), executes in sandboxes,
and keeps only triples where all three produce the identical expected output.

**What each triple carries:** the NL intent, the serialized ASG graph (JSON), the
compiled shell script, the compiled Python source, the expected output, the node-type
list, and the parameterization metadata. This is a complete training record — not
just (input, output), but (input, intermediate representation, target-1, target-2,
target-3, verified_output). The ASG JSON is particularly valuable: it's the
structured-intent label that lets a model learn the *mapping*, not just memorize
surface forms.

**100% verification rate is not luck — it's structural.** The templates generate
programs from the same grammar the parser accepts, using the same node types the
backends implement. There's no way to generate an unverifiable triple because every
template is a composition of already-verified capabilities. The only way to get a
failure would be a backend bug (which would also fail the test suite) or a sandbox
edge case (which the parameterization would surface). Neither happened.

**Node-type coverage is uneven, and that's actionable.** CreateFile appears in 672
of 697 triples (96%) because nearly every template starts by creating a file.
SortLines appears in only 4 (0.6%) because the sort template has a small parameter
pool. The distribution tells us exactly which templates to expand for balanced
training data. Scaling to 5K–10K triples is a matter of widening parameter pools,
not new infrastructure.

**The pipeline is the cheapest strategic asset the project has.** It cost one file
(20611 bytes) and runs in seconds. Each triple is a rejection-sampling data point —
the same technique behind modern code/SQL generation models. The difference: those
models need expensive API calls to generate and verify; this pipeline generates and
verifies for free because the ASG backends are deterministic. Zero API cost, zero
hallucination risk, zero verification ambiguity. The moat isn't the data itself
(small models can be trained on public data) — it's the generation + verification
loop that produces *guaranteed-correct* data at marginal cost zero.

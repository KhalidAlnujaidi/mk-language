"""The council — five distinct-architecture models design a language by anonymous
Borda consensus, governed by axioms.

Loop: each model drafts a proposal (high temperature, for diversity) → proposals
are anonymized and shuffled → every model ranks them blind by the axioms (low
temperature, for disciplined judgment) → Borda tally picks the winner → the
winner is appended to the growing spec → checkpoint. After the fixed pipeline it
switches to open-ended refinement: pick the most-contested section, let the
council propose improvements *against the status quo*, and adopt a change only if
it out-votes "keep current" — so the spec converges and never degrades.

Robust for an unattended overnight run: every model call is fail-soft (retry,
then forfeit the round), every round is checkpointed (resumable), and a STOP
sentinel file halts it gracefully.

Self-contained — talks to Ollama's native /api/chat directly (sync, one model
resident at a time). No kinox imports, so it can run detached from the framework.
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
OLLAMA = "http://127.0.0.1:11434/api/chat"
DUMP = HERE / "dump.log"


def dump(section: str, body: str = "") -> None:
    """Append-only, fsync'd record of EVERY process step — prompts, raw model
    reasoning, ballots, tallies, errors. Flushed to disk immediately so even a
    hard kill mid-round loses nothing already generated."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with DUMP.open("a", encoding="utf-8") as fh:
        fh.write(f"\n===== [{ts}] {section} =====\n")
        if body:
            fh.write(body.rstrip() + "\n")
        fh.flush()
        os.fsync(fh.fileno())

# Five distinct architecture families — the diversity IS the experiment.
ROSTER: tuple[str, ...] = (
    "qwen3:8b",        # Qwen3   — Alibaba
    "gemma4:latest",   # Gemma   — Google
    "llama3:latest",   # Llama   — Meta
    "deepseek-r1:8b",  # DeepSeek
    "mistral:7b",      # Mistral
)

PROPOSE_TEMP = 0.9   # diversity in generation
VOTE_TEMP = 0.2      # consistency in judgment
TIMEOUT_S = 240.0
KEEP_ALIVE = "8m"
SPEC_CTX_CAP = 7000  # chars of spec fed back into prompts
MAX_ROUNDS = 400     # overnight safety backstop
PLATEAU_PATIENCE = 6  # build rounds with no capability gain → trigger a fresh start

AXIOMS = """\
1. MACHINE-INTERPRETABILITY FIRST. Prefer forms a machine parses and reasons about
   unambiguously over forms that merely read nicely to humans.
2. REUSE, DON'T REINVENT. Adopt the simplest construct that already works; do not
   add a second way to do the same thing.
3. DON'T BREAK WHAT WORKS. A change is adopted only if it is strictly better than
   the status quo under these axioms; when in doubt, keep what stands.
4. EVERYTHING IS TESTABLE. Every construct must have a clear, checkable meaning —
   a program's behavior must be decidable from its text.
5. MINIMAL CORE. Fewer primitives, composed; not many features, special-cased.
"""

# The fixed pipeline; after it, the loop goes open-ended (refine the weakest part).
STAGES: tuple[tuple[str, str], ...] = (
    ("meta-axiom",
     "Propose ONE additional governing axiom for this experiment of collaboratively "
     "designing a programming language. State it in a single sentence."),
    ("design-goals",
     "Propose the 3-5 top design goals for the language, ranked. One line each."),
    ("notation",
     "Choose the surface notation: PREFIX (S-expression), INFIX, or POSTFIX. "
     "Justify strictly in terms of machine-interpretability and parsing simplicity. "
     "State the choice in the first line."),
    ("lexical-grammar",
     "Define the lexical grammar: tokens, literals, identifiers, comments. Be concrete."),
    ("core-grammar",
     "Define the core grammar in EBNF, consistent with the chosen notation."),
    ("paradigm-and-types",
     "Choose the core paradigm and type discipline: functional, object-oriented, or "
     "other; static or dynamic; how data and behavior relate. Justify by the axioms. "
     "State the choice in the first line."),
    ("semantics",
     "Define evaluation semantics: how expressions reduce, scoping rules, evaluation order."),
    ("builtins",
     "Define the minimal set of built-in primitives and core operations."),
    ("example-factorial",
     "Write example program #1 — factorial — in the language exactly as specified so far."),
    ("example-data",
     "Write example program #2 — define a small data structure and operations on it."),
    ("example-showcase",
     "Write example program #3 — a program that showcases the language's chosen paradigm."),
)


# --- model client ------------------------------------------------------------


def chat(model: str, system: str, user: str, *, temperature: float, tag: str = "") -> str:
    """One sync chat completion via Ollama native API. Fail-soft: returns "" after
    retries so a flaky model forfeits the round rather than crashing the night.

    Records the prompt and the FULL raw reply (reasoning included) to the dump
    before returning the cleaned answer the spec/voting use — so nothing the model
    thought is ever lost, even though <think> blocks are stripped downstream.
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": temperature},
    }
    dump(f"PROMPT model={model} tag={tag} temp={temperature}",
         f"--- system ---\n{system}\n--- user ---\n{user}")
    for attempt in range(3):
        try:
            r = httpx.post(OLLAMA, json=payload, timeout=TIMEOUT_S)
            r.raise_for_status()
            raw = (r.json().get("message", {}).get("content") or "").strip()
            dump(f"RAW REPLY model={model} tag={tag} attempt={attempt}",
                 raw or "(empty)")
            # Strip <think>…</think> reasoning (deepseek-r1, qwen3) for downstream
            # use; the full reasoning is already preserved in the dump above.
            cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            if cleaned:
                return cleaned
        except Exception as exc:
            dump(f"ERROR model={model} tag={tag} attempt={attempt}", repr(exc))
            time.sleep(2.0 * (attempt + 1))
    return ""


# --- consensus mechanics -----------------------------------------------------


@dataclass
class RoundLog:
    index: int
    title: str
    options: list[dict[str, str]] = field(default_factory=list[dict[str, str]])
    ballots: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    scores: dict[str, int] = field(default_factory=dict[str, int])
    winner_author: str = ""
    winner_text: str = ""
    note: str = ""


def _anonymize(
    options: list[tuple[str, str]], seed: int
) -> tuple[list[str], dict[str, tuple[str, str]]]:
    """Shuffle (author, text) options into blind labels P1..Pn."""
    order = list(options)
    random.Random(seed).shuffle(order)
    labels = [f"P{i + 1}" for i in range(len(order))]
    return labels, dict(zip(labels, order, strict=True))


def _parse_ranking(reply: str, labels: list[str]) -> list[str]:
    """Pull an ordered, de-duplicated P-label ranking from a voter's reply.
    Missing labels are appended (partial credit); empty reply → no ballot."""
    found: list[str] = []
    for tok in re.findall(r"\bP\d+\b", reply):
        if tok in labels and tok not in found:
            found.append(tok)
    if not found:
        return []
    for lab in labels:  # append any the model omitted, so Borda is well-formed
        if lab not in found:
            found.append(lab)
    return found


def _borda(
    ballots: dict[str, list[str]], labels: list[str]
) -> tuple[str, dict[str, int]]:
    """Sum Borda points (first place = n-1 … last = 0); tie → most first-places,
    then lowest label. Returns (winner_label, scores)."""
    n = len(labels)
    scores = dict.fromkeys(labels, 0)
    firsts = dict.fromkeys(labels, 0)
    for ranking in ballots.values():
        if not ranking:
            continue
        for pos, lab in enumerate(ranking):
            if lab in scores:
                scores[lab] += (n - 1) - pos
        firsts[ranking[0]] += 1
    winner = max(labels, key=lambda x: (scores[x], firsts[x], -labels.index(x)))
    return winner, scores


def gather_proposals(question: str, spec: str, extra: str = "") -> list[tuple[str, str]]:
    """Each model drafts a proposal (high temp). Forfeits silently on failure."""
    system = (
        "You are a member of a five-model council designing a programming language. "
        "Decide strictly by these axioms:\n" + AXIOMS +
        "\nBe concrete and concise. Do not identify yourself."
    )
    spec_ctx = spec[-SPEC_CTX_CAP:] if spec else "(nothing decided yet)"
    user = (
        f"SPEC SO FAR:\n{spec_ctx}\n\n{extra}\nTASK: {question}\n\n"
        "Give only your proposal — no preamble."
    )
    out: list[tuple[str, str]] = []
    for model in ROSTER:
        text = chat(model, system, user, temperature=PROPOSE_TEMP, tag="propose")
        if text:
            out.append((model, text))
    return out


def run_consensus(
    index: int, title: str, options: list[tuple[str, str]], axioms: str, seed: int
) -> RoundLog:
    """Anonymize options, collect blind Borda ballots from all models, tally."""
    log = RoundLog(index=index, title=title)
    if len(options) < 2:
        log.note = f"insufficient proposals ({len(options)}) — round skipped"
        if options:
            log.winner_author, log.winner_text = options[0]
        return log

    labels, mapping = _anonymize(options, seed)
    log.options = [
        {"label": lab, "author": mapping[lab][0], "text": mapping[lab][1]}
        for lab in labels
    ]
    block = "\n\n".join(f"=== {lab} ===\n{mapping[lab][1]}" for lab in labels)
    system = (
        "You are judging anonymous proposals for a programming-language decision. "
        "Judge ONLY by these axioms, not by writing style:\n" + axioms
    )
    user = (
        f"DECISION: {title}\n\nPROPOSALS:\n{block}\n\n"
        f"Rank ALL of {', '.join(labels)} from best to worst. "
        "Output the ranking on ONE line exactly as:\n"
        "RANKING: P?,P?,...\n"
        "Then one short line per proposal explaining your reasoning."
    )
    for voter in ROSTER:
        reply = chat(voter, system, user, temperature=VOTE_TEMP, tag=f"vote:{title}")
        log.ballots[voter] = _parse_ranking(reply, labels)

    winner, scores = _borda(log.ballots, labels)
    log.scores = scores
    log.winner_author, log.winner_text = mapping[winner]
    dump(
        f"TALLY round={index} title={title}",
        f"labels->authors: { {lab: mapping[lab][0] for lab in labels} }\n"
        f"ballots: {log.ballots}\nscores: {scores}\n"
        f"WINNER: {winner} = {log.winner_author}",
    )
    return log


# --- phase 3: build a real, executable interpreter ---------------------------
#
# The pipeline produced a *design* (prose + example programs). It was never run, so
# "complete" was decided by a vote on prose — violating Axiom 4 (everything testable)
# and the project thesis (ground truth beats model). Phase 3 fixes that: the council
# authors the language's reference interpreter in Python, and a capability is "done"
# ONLY when a program using it actually executes to the expected output. Variation =
# the council's high-temp proposals; selection = execution score (the verifier is the
# engine). A proposal is adopted iff it passes strictly MORE of the ladder than the
# incumbent and breaks nothing already green — Axiom 3 (don't break what works),
# enforced by running code, not opinion. The run terminates at a real milestone.

# The strategic goal made decidable: a complete language runs every one of these.
# display semantics (Scheme-style): numbers bare, strings WITHOUT quotes, lists as
# space-separated atoms in parentheses, e.g. (1 4 9).
CONFORMANCE: tuple[tuple[str, str, str], ...] = (
    ("arithmetic", "(display (+ 2 (* 3 4)))", "14"),
    ("store-variable", "(define x 10) (display x)", "10"),
    ("recall-variable", "(define x 10) (display (+ x 5))", "15"),
    ("print-string", '(display "hello")', "hello"),
    ("conditional",
     '(define x 10) (display (if (< x 100) "small" "big"))', "small"),
    ("function",
     "(define (square n) (* n n)) (display (square 7))", "49"),
    ("closure",
     "(define (adder n) (lambda (m) (+ n m))) "
     "(define add5 (adder 5)) (display (add5 3))", "8"),
    ("recursion",
     "(define (fact n) (if (< n 2) 1 (* n (fact (- n 1))))) (display (fact 5))",
     "120"),
    ("local-binding", "(display (let ((a 2) (b 3)) (+ a b)))", "5"),
    ("higher-order-list",
     "(define (square n) (* n n)) (display (map square (list 1 2 3)))",
     "(1 4 9)"),
    ("string-append", '(display (string-append "a" "b"))', "ab"),
)

INTERP_CONTRACT = """\
Write a COMPLETE, self-contained Python 3 program that interprets OUR language.

HARD CONTRACT (your code is rejected if you break this):
- Define a function named EXACTLY `run` at the TOP LEVEL of the file (module scope —
  NOT inside a class, NOT inside `if __name__ == "__main__"`). Signature: `run(source)`,
  taking the whole program text as one string.
- `run` must PRINT (to stdout) exactly what the program's `(display ...)` calls produce.
  Returning that text from `run` is also accepted. Do NOT print anything else.
- display semantics: numbers print bare (14); strings print WITHOUT quotes (hello);
  a list prints space-separated inside parentheses, e.g. (1 4 9).

Support at least: integers, strings, booleans; (define name expr); (define (f a..) body);
lambda; if; let; the operators + - * < ; and the builtins display, list, map, string-append.
No input(), no network, no file or os access. Pure and deterministic.

Output ONE ```python code block — the full runnable file defining top-level `run(source)` —
and NOTHING else (no usage example, no second block)."""

SANDBOX = HERE / "_sandbox_run.py"


def _normalize(s: str) -> str:
    return " ".join(s.split())


_ENTRY_NAMES = ("run", "main", "interpret", "interpreter", "evaluate",
                "execute", "repl", "run_interpreter", "run_program")


def extract_code(text: str) -> str:
    """Pull the interpreter source from a model reply. Replies often contain several
    fenced blocks (the interpreter + a usage example); pick the block that actually
    defines an entry point, falling back to the longest code-looking block. Fence
    labels are matched case-insensitively (```Python, ```py, bare ```)."""
    blocks = re.findall(
        r"```[ \t]*[A-Za-z0-9_+.-]*[ \t]*\r?\n(.*?)```", text, flags=re.DOTALL
    )
    code = [b.strip() for b in blocks if re.search(r"\bdef \w+\(|\bimport ", b)]
    if not code:
        code = [b.strip() for b in blocks if b.strip()]
    if code:
        for b in sorted(code, key=len, reverse=True):
            if any(re.search(rf"\bdef {n}\b", b) for n in _ENTRY_NAMES):
                return b
        return max(code, key=len)
    # Fallback: a bare reply that already looks like a Python file.
    if re.search(r"\bdef \w+\(", text):
        return text.strip()
    return ""


def score_interpreter(
    src: str, suite: tuple[tuple[str, str, str], ...]
) -> tuple[list[str], dict[str, str]]:
    """Ground truth: execute a candidate interpreter against the conformance suite in
    an isolated subprocess (wall-clock timeout + the runner's CPU/mem rlimits). Returns
    (names_passed, per-capability detail). This is the verifier — it never trusts a
    model's claim that something is 'optimal'; it runs the code and checks the output."""
    passing: list[str] = []
    details: dict[str, str] = {}
    if not src.strip():
        return passing, {name: "no code" for name, _, _ in suite}
    fd, interp_path = tempfile.mkstemp(suffix=".py", dir=str(HERE))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(src)
        for name, program, expected in suite:
            try:
                proc = subprocess.run(
                    [sys.executable, str(SANDBOX), interp_path],
                    input=program,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    cwd=str(HERE),
                )
                out = _normalize(proc.stdout)
                ok = proc.returncode == 0 and out == _normalize(expected)
                if ok:
                    passing.append(name)
                    details[name] = "PASS"
                else:
                    err = (proc.stderr or "").strip().splitlines()
                    tail = err[-1] if err else ""
                    details[name] = f"got={proc.stdout!r} err={tail[:140]}"
            except subprocess.TimeoutExpired:
                details[name] = "timeout"
            except Exception as exc:  # pragma: no cover - defensive
                details[name] = f"runner-error: {exc!r}"[:160]
    finally:
        with contextlib.suppress(OSError):
            os.unlink(interp_path)
    return passing, details


def gather_interpreters(
    spec: str, incumbent_src: str, inc_details: dict[str, str],
    suite: tuple[tuple[str, str, str], ...], reference: str = "",
    fresh_start: bool = False
) -> list[tuple[str, str]]:
    """Each model proposes a full interpreter (high temp). The prompt carries the
    council's ANONYMOUS institutional memory (`reference` — every milestone reached,
    no identities) so progress is never lost, plus either the current best to extend
    (normal mode) or a license to re-derive from scratch toward the agreed goal
    (fresh_start, fired on a plateau to escape a dead-end local optimum)."""
    suite_txt = "\n".join(
        f"; {n}\n{prog}\n; expected: {exp}" for n, prog, exp in suite
    )
    proven = [n for n, _, _ in suite if inc_details.get(n) == "PASS"]
    next_failing = next((n for n, _, _ in suite if n not in proven), "")
    mem = (
        f"INSTITUTIONAL MEMORY — what the council has already proven works "
        f"(anonymous, no identities):\n{reference[-3000:]}\n\n" if reference else ""
    )
    if fresh_start and incumbent_src:
        cur = (
            f"THE COUNCIL HAS PLATEAUED at {len(proven)}/{len(suite)} — many rounds with "
            "no gain. By consensus these capabilities are PROVEN reachable; treat them as "
            "the agreed goal and the motivator, NOT a template. START FRESH: re-derive a "
            "clean interpreter FROM SCRATCH that still passes every proven capability AND "
            f"breaks the plateau by also passing `{next_failing}`. Rethink the whole "
            "structure — do not merely tweak the old code.\n"
            f"PROVEN capabilities you must keep passing: {proven}\n"
            f"Plateau-breaking target: {next_failing}"
        )
    elif incumbent_src:
        n_pass = len(proven)
        results = "\n".join(f"- {k}: {v[:160]}" for k, v in inc_details.items())
        cur = (
            f"CURRENT BEST INTERPRETER (passes {n_pass}/{len(suite)}):\n"
            f"```python\n{incumbent_src}\n```\n"
            f"Per-capability result:\n{results}\n\n"
            f"Improve it: pass MORE capabilities (aim next at `{next_failing}`) without "
            "breaking any already-passing one."
        )
    else:
        cur = "No interpreter exists yet — write the first one."
    system = (
        "You are one of five models implementing the reference interpreter for the "
        "programming language your council designed. Decide by these axioms:\n" + AXIOMS
    )
    user = (
        f"OUR LANGUAGE SPEC (your council designed this):\n{spec[-SPEC_CTX_CAP:]}\n\n"
        f"{mem}"
        f"CONFORMANCE SUITE — your interpreter must reproduce each expected output:\n"
        f"{suite_txt}\n\n{cur}\n\n{INTERP_CONTRACT}"
    )
    out: list[tuple[str, str]] = []
    for model in ROSTER:
        code = extract_code(
            chat(model, system, user, temperature=PROPOSE_TEMP, tag="interp")
        )
        if code:
            out.append((model, code))
    return out


def _vote_best_interpreter(
    candidates: list[dict[str, object]], seed: int
) -> dict[str, object]:
    """Tie-break among EQUALLY-CORRECT interpreters: the council ranks them blind by the
    axioms (minimal core, machine-interpretability, clarity). Execution decides
    correctness; the vote only chooses the most elegant among equals."""
    opts = [(str(c["author"]), str(c["code"])) for c in candidates]
    labels, mapping = _anonymize(opts, seed)
    block = "\n\n".join(
        f"=== {lab} ===\n```python\n{mapping[lab][1][:4000]}\n```" for lab in labels
    )
    system = (
        "Rank these interpreters — they all pass the SAME tests, so judge ONLY by the "
        "axioms (minimal core, machine-interpretability, clarity):\n" + AXIOMS
    )
    user = (
        f"All are equally correct. Choose the most minimal/elegant.\n"
        f"Rank ALL of {', '.join(labels)} best-to-worst as:\nRANKING: P?,P?,...\n\n{block}"
    )
    ballots: dict[str, list[str]] = {}
    for voter in ROSTER:
        ballots[voter] = _parse_ranking(
            chat(voter, system, user, temperature=VOTE_TEMP, tag="interp-vote"), labels
        )
    win, _ = _borda(ballots, labels)
    wa = mapping[win][0]
    for c in candidates:
        if c["author"] == wa:
            return c
    return candidates[0]


def run_build_round(
    index: int, spec: str, incumbent_src: str, incumbent_passing: list[str],
    suite: tuple[tuple[str, str, str], ...], seed: int, reference: str = "",
    fresh_start: bool = False
) -> tuple[RoundLog, str, list[str]]:
    """One variation+selection cycle. Returns (log, new_incumbent_src, new_passing).

    Normal rounds adopt a proposal only if it passes STRICTLY MORE capabilities than
    the incumbent (the monotonic don't-break-what-works ratchet). A plateau-breaking
    `fresh_start` round additionally accepts an EQUAL-scoring re-derivation — a
    deliberate sideways move onto a different foundation, so a dead-end local optimum
    can be escaped without ever dropping below what the council already proved."""
    title = "build:fresh-start" if fresh_start else "build:interpreter"
    log = RoundLog(index=index, title=title)
    inc_details: dict[str, str] = {}
    if incumbent_src:
        _, inc_details = score_interpreter(incumbent_src, suite)
    props = gather_interpreters(
        spec, incumbent_src, inc_details, suite, reference, fresh_start
    )

    scored: list[dict[str, object]] = []
    for author, code in props:
        passing, details = score_interpreter(code, suite)
        scored.append(
            {"author": author, "code": code, "passing": passing, "n": len(passing)}
        )
        dump(
            f"BUILD eval model={author} round={index} mode={title}",
            f"score={len(passing)}/{len(suite)} passing={passing}\n"
            + "\n".join(f"{k}: {v[:200]}" for k, v in details.items()),
        )

    inc_n = len(incumbent_passing)
    log.options = [
        {"label": f"P{i + 1}", "author": str(s["author"]),
         "text": f"score {s['n']}/{len(suite)} :: {s['passing']}"}
        for i, s in enumerate(scored)
    ]
    log.scores = {str(s["author"]): int(s["n"]) for s in scored}  # type: ignore[misc]

    if not scored:
        log.note = "no proposals this round"
        return log, incumbent_src, incumbent_passing

    best_n = max(int(s["n"]) for s in scored)
    # Adoption bar: strictly better normally; >= on a fresh-start (sideways escape).
    adopt = best_n > inc_n or (fresh_start and best_n == inc_n and best_n > 0)
    if adopt:
        top = [s for s in scored if int(s["n"]) == best_n]
        win = top[0] if len(top) == 1 else _vote_best_interpreter(top, seed)
        win_src = str(win["code"])
        # On a sideways move, only switch foundations if the code actually differs.
        if best_n == inc_n and win_src.strip() == incumbent_src.strip():
            log.note = f"fresh start returned the same foundation at {inc_n}/{len(suite)}"
            return log, incumbent_src, incumbent_passing
        log.winner_author = str(win["author"])
        log.winner_text = win_src
        verb = "re-seeded at" if best_n == inc_n else f"adopted: {inc_n} ->"
        log.note = f"{verb} {best_n}/{len(suite)}"
        dump(
            f"BUILD ADOPT round={index} mode={title}",
            f"new incumbent {win['author']} score {best_n}/{len(suite)} "
            f"passing={win['passing']}",
        )
        return log, win_src, list(win["passing"])  # type: ignore[arg-type]

    log.note = f"status quo held at {inc_n}/{len(suite)} (no proposal beat it)"
    return log, incumbent_src, incumbent_passing


# --- persistent state --------------------------------------------------------


@dataclass
class Section:
    stage: str
    text: str
    author: str
    margin: int  # winning Borda margin over runner-up (low = contested)


@dataclass
class State:
    round: int = 0
    stage_index: int = 0
    phase: str = "pipeline"  # pipeline | build | done
    sections: list[Section] = field(default_factory=list[Section])
    # Phase 3 (build): the council's own reference interpreter + which conformance
    # capabilities it currently executes correctly. Selection is by execution, so the
    # winning interpreter source IS the checkpoint — resumable like everything else.
    incumbent_src: str = ""
    incumbent_passing: list[str] = field(default_factory=list[str])
    stall_count: int = 0  # build rounds since the last capability gain (plateau gauge)

    @classmethod
    def load(cls, path: Path) -> State:
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        secs = [Section(**s) for s in raw.get("sections", [])]
        phase = raw.get("phase", "pipeline")
        # Migration: the old aimless "refine" phase is replaced by the verifier-gated
        # "build" phase — a resumed run continues by building a real interpreter.
        if phase == "refine":
            phase = "build"
        return cls(
            round=raw.get("round", 0),
            stage_index=raw.get("stage_index", 0),
            phase=phase,
            sections=secs,
            incumbent_src=raw.get("incumbent_src", ""),
            incumbent_passing=list(raw.get("incumbent_passing", [])),
            stall_count=raw.get("stall_count", 0),
        )

    def save(self, path: Path) -> None:
        # Atomic write (tmp + replace) so even a hard kill mid-save can never
        # corrupt the checkpoint — the resume contract the overnight run depends on.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "round": self.round,
                    "stage_index": self.stage_index,
                    "phase": self.phase,
                    "sections": [asdict(s) for s in self.sections],
                    "incumbent_src": self.incumbent_src,
                    "incumbent_passing": self.incumbent_passing,
                    "stall_count": self.stall_count,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    def spec_text(self) -> str:
        return "\n\n".join(f"## {s.stage}\n{s.text}" for s in self.sections)


def _margin(scores: dict[str, int], winner_text_author: str) -> int:
    vals = sorted(scores.values(), reverse=True)
    return (vals[0] - vals[1]) if len(vals) >= 2 else vals[0] if vals else 0

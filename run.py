"""Overnight driver for the language council.

Runs consensus rounds until a STOP sentinel appears or MAX_ROUNDS is hit. Phase 1
walks the fixed STAGES pipeline; phase 2 refines the most-contested section
against the status quo. Every round is checkpointed (resumable) and written to
human-readable SPEC.md + TRANSCRIPT.md and machine-readable rounds/round-NNN.json.

Launch detached:   nohup .venv/bin/python projects/language/run.py &
Watch:             tail -f projects/language/TRANSCRIPT.md   (and SPEC.md)
Stop gracefully:   touch projects/language/STOP
"""

from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import asdict
from pathlib import Path
from types import FrameType

from council import (
    ACTIVE_GOAL,
    AXIOMS,
    CONFORMANCE,
    LANG_VERSIONS,
    MAX_ROUNDS,
    PLATEAU_PATIENCE,
    ROSTER,
    STAGES,
    RoundLog,
    Section,
    State,
    _margin,
    dump,
    gather_proposals,
    run_build_round,
    run_consensus,
    write_versions,
)

# Graceful stop: a signal (Ctrl-C / kill / kill -TERM) sets a flag; the current
# round runs to completion and checkpoints, THEN we exit — so a stop never loses
# progress. A hard `kill -9` still loses nothing already written (the dump is
# fsync'd per model call and state.json is saved per round → resume re-does at
# most the interrupted round).
_STOP = {"flag": False}


def _on_signal(signum: int, _frame: FrameType | None) -> None:
    _STOP["flag"] = True
    print(f"signal {signum} received — finishing this round, then stopping.",
          flush=True)
    dump(f"SIGNAL {signum}", "graceful stop requested — will checkpoint and exit")

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
STOP = HERE / "STOP"
SPEC = HERE / "SPEC.md"
TRANSCRIPT = HERE / "TRANSCRIPT.md"
ROUNDS = HERE / "rounds"
PROGRESS = HERE / "PROGRESS.md"
CHEATCODE = HERE / "cheatcode_aios_nl_os.md"

# The current build target, chosen by the active language version (KINOX_LANG_VERSION).
# When state.goal differs (e.g. resuming after a version bump), the build phase archives
# the prior version's artifacts and starts this goal fresh — the in-place reframe,
# carrying the anonymized memory forward without losing the prior record.
GOAL = ACTIVE_GOAL


def scope_text() -> str:
    """The corpus seed (cheat code) fed to the council as what to build FROM."""
    try:
        return CHEATCODE.read_text(encoding="utf-8")
    except OSError:
        return ""

_PROGRESS_HEADER = """\
# Council build log — anonymized progress reference

The council's shared institutional memory. It records, ANONYMOUSLY (no model identities),
every capability milestone reached and every plateau — so progress is never lost. This
file is fed back into every build prompt: the council builds on what it has proven, and
when it plateaus it restarts from the agreed foundation toward the goal it already showed
was reachable. Identities live only in dump.log (our private audit), never here.

"""


def append_progress(entry: str) -> None:
    """Append an anonymous milestone/plateau line to the shared reference (the file the
    council reads as institutional memory). Append-only, like the dump — never rewrites
    history, so a stop loses nothing."""
    if not PROGRESS.exists():
        PROGRESS.write_text(_PROGRESS_HEADER, encoding="utf-8")
    with PROGRESS.open("a", encoding="utf-8") as fh:
        fh.write(entry.rstrip() + "\n")


def write_spec(state: State) -> None:
    lines = [
        "# The Council Language — living specification",
        "",
        "_Designed by anonymous Borda consensus of five distinct-architecture models:_",
        "_" + ", ".join(ROSTER) + "._",
        "",
        "## Governing axioms",
        "```",
        AXIOMS.rstrip(),
        "```",
        "",
    ]
    for s in state.sections:
        lines += [
            f"## {s.stage}",
            f"_adopted from {s.author} · consensus margin {s.margin}_",
            "",
            s.text,
            "",
        ]
    SPEC.write_text("\n".join(lines), encoding="utf-8")


def write_capabilities(state: State) -> None:
    """The capability ladder as a decidable scoreboard — read by the dashboard and a
    human-readable CAPABILITIES.md. This is the definition of 'complete': every box
    green means a program using that feature actually executed to the expected output."""
    names = [n for n, _, _ in CONFORMANCE]
    passing = set(state.incumbent_passing)
    score = len(passing & set(names))
    (HERE / "capabilities.json").write_text(
        json.dumps(
            {"all": names, "passing": sorted(passing),
             "score": score, "total": len(names)},
            indent=2,
        ),
        encoding="utf-8",
    )
    lines = [
        "# The Council Language — capability ladder (executed, not voted)",
        "",
        f"**{score}/{len(names)} capabilities pass** under the council's own "
        "reference interpreter (`interpreter.py`).",
        "",
    ]
    for name, program, expected in CONFORMANCE:
        mark = "✅" if name in passing else "⬜"
        lines += [f"- {mark} **{name}** — `{program}` → `{expected}`"]
    (HERE / "CAPABILITIES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_final(state: State) -> None:
    """On completion, freeze the finished language: spec + interpreter + a verified
    program gallery (each conformance program with its real, executed output)."""
    write_capabilities(state)
    lines = [
        "# The Council NL→OS abstraction layer — COMPLETE",
        "",
        "Every intent program below executed to its expected OS outcome under the "
        "interpreter the five models wrote by anonymous consensus (`interpreter.py`).",
        "",
        "## Verified program gallery",
        "",
    ]
    for name, program, expected in CONFORMANCE:
        lines += [f"### {name}", "```text", program, "```",
                  f"→ `{expected}`", ""]
    (HERE / "COMPLETE.md").write_text("\n".join(lines), encoding="utf-8")
    dump("LAYER COMPLETE",
         f"all {len(CONFORMANCE)} capabilities pass at round {state.round}")


def append_transcript(state: State, log: RoundLog) -> None:
    parts = [
        f"\n### Round {log.index} — {log.title}",
        f"- winner: **{log.winner_author}**" + (f"  ({log.note})" if log.note else ""),
        f"- Borda scores: {log.scores}",
    ]
    for opt in log.options:
        first = opt["text"].splitlines()[0] if opt["text"] else ""
        parts.append(f"  - {opt['label']} = {opt['author']}: {first[:90]}")
    with TRANSCRIPT.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(parts) + "\n")


def main() -> None:
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    ROUNDS.mkdir(exist_ok=True)
    state = State.load(STATE)
    if not TRANSCRIPT.exists():
        TRANSCRIPT.write_text("# Council transcript\n", encoding="utf-8")
    write_versions(GOAL)
    print(f"resuming at round {state.round}, phase {state.phase}, goal {GOAL}", flush=True)
    dump("RUN START", f"round={state.round} phase={state.phase} goal={GOAL} roster={ROSTER}")

    while state.round < MAX_ROUNDS:
        if STOP.exists() or _STOP["flag"]:
            print("stop requested — halting gracefully (progress saved).", flush=True)
            break

        seed = 1000 + state.round
        t0 = time.monotonic()

        if state.phase == "pipeline" and state.stage_index < len(STAGES):
            stage, question = STAGES[state.stage_index]
            proposals = gather_proposals(question, state.spec_text())
            log = run_consensus(state.round, stage, proposals, AXIOMS, seed)
            if log.winner_text:
                state.sections.append(
                    Section(stage, log.winner_text, log.winner_author,
                            _margin(log.scores, log.winner_author))
                )
            state.stage_index += 1
            if state.stage_index >= len(STAGES):
                state.phase = "build"  # design done → build a real interpreter

        elif state.phase == "build":
            # In-place reframe: if the incumbent was built for a different goal, retire it
            # and start the new goal from zero — but keep the old record (archive its
            # progress log + interpreter) so nothing is lost.
            if state.goal != GOAL:
                dump("GOAL SWITCH", f"{state.goal or '(scheme)'} -> {GOAL}")
                # Version-stamp the outgoing artifacts so each version's record is kept
                # (e.g. interpreter.v02.py), not overwritten by a single .prev slot.
                out_ver = next((v["id"] for v in LANG_VERSIONS
                                if v["goal"] == state.goal), "prev")
                for old in ("PROGRESS.md", "interpreter.py", "CAPABILITIES.md"):
                    p = HERE / old
                    if p.exists():
                        p.replace(HERE / f"{p.stem}.{out_ver}{p.suffix}")
                state.incumbent_src = ""
                state.incumbent_passing = []
                state.stall_count = 0
                state.goal = GOAL

            prev_pass = list(state.incumbent_passing)
            reference = PROGRESS.read_text(encoding="utf-8") if PROGRESS.exists() else ""
            # Plateau → fresh start: many rounds with no gain means the current
            # foundation is a dead end. Restart from the proven floor toward the agreed
            # goal, carrying the anonymized memory — exactly the user's "begin again from
            # what worked" loop.
            fresh = state.stall_count >= PLATEAU_PATIENCE
            log, new_src, new_pass = run_build_round(
                state.round, scope_text(), state.incumbent_src,
                state.incumbent_passing, CONFORMANCE, seed, reference, fresh,
            )
            state.incumbent_src = new_src
            state.incumbent_passing = new_pass
            if new_src:
                (HERE / "interpreter.py").write_text(new_src, encoding="utf-8")
            write_capabilities(state)

            gained = sorted(set(new_pass) - set(prev_pass))
            if gained:  # a real capability milestone — record it, reset the plateau gauge
                append_progress(
                    f"- Round {log.index}: reached **{len(new_pass)}/{len(CONFORMANCE)}**. "
                    f"Newly working: {', '.join(gained)}."
                )
                state.stall_count = 0
            elif fresh:  # plateau breaker fired — document the agreed goal, reset gauge
                nxt = next((n for n, _, _ in CONFORMANCE if n not in new_pass), "—")
                append_progress(
                    f"- Round {log.index}: PLATEAU at {len(new_pass)}/{len(CONFORMANCE)} "
                    f"after {state.stall_count} rounds with no gain. Agreed foundation "
                    f"passes: {new_pass or '[]'}. Fresh-start goal: `{nxt}`."
                )
                state.stall_count = 0
            else:  # no gain this round — inch toward the plateau threshold
                state.stall_count += 1

            if len(new_pass) >= len(CONFORMANCE):
                state.phase = "done"
                append_progress(
                    f"- Round {log.index}: **COMPLETE — {len(new_pass)}/"
                    f"{len(CONFORMANCE)}.** The council built a working NL→OS layer."
                )
                # Finish this round's checkpoint below, then exit the loop.

        else:  # phase == "done" (or no work left)
            print("language complete — all capabilities pass. stopping.", flush=True)
            break

        # Checkpoint everything (resumable + auditable).
        (ROUNDS / f"round-{log.index:04d}.json").write_text(
            json.dumps(asdict(log), indent=2), encoding="utf-8"
        )
        append_transcript(state, log)
        write_spec(state)
        state.round += 1
        state.save(STATE)
        dt = time.monotonic() - t0
        print(f"round {log.index} done: {log.title} -> {log.winner_author} "
              f"({dt:.0f}s)", flush=True)

    if state.phase == "done":
        write_final(state)
        print("LANGUAGE COMPLETE — see COMPLETE.md", flush=True)
    print(f"finished at round {state.round}.", flush=True)


if __name__ == "__main__":
    main()

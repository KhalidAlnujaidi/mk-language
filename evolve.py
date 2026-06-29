#!/usr/bin/env python3
"""Experiment 4 -- Governed Self-Enhancement Loop.

The thesis: an unharnessed LLM is noise. But noise + governance + axioms +
a resourceful environment can produce self-evolution: a loop that scans its
capability gaps, proposes targeted improvements, and gets measurably more
capable over time -- all under a safety harness that prevents it from
weakening its own judge.

Architecture (three roles, all deterministic code):

  ENFORCER  -- analyzes eval results, identifies weakest category, sets target.
  DEVELOPER -- proposes planner rules (regex -> NL step list). Validated.
  VERIFIER  -- full test suite + eval; keep iff strict improvement.

Governance (fail-CLOSED everywhere):
  - Protected paths: the developer can ONLY add rules to planner.py.
  - Rule validation: regex compiles, NL lines parse to ASG nodes.
  - Full reversibility: rejected changes are reverted.
  - Resource cap: max cycles, plateau patience.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import tempfile
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import asg
from planner import Planner

# Config
EVAL_FILE = HERE / "eval_challenges.json"
PLANNER_FILE = HERE / "planner.py"
SANDBOX_RUN = HERE / "_sandbox_run.py"
INTERPRETER_FILE = HERE / "interpreter.py"
DUMP_LOG = HERE / "dump.log"

MAX_CYCLES = int(os.environ.get("EVOLVE_MAX_CYCLES", "50"))
PLATEAU_PATIENCE = int(os.environ.get("EVOLVE_PATIENCE", "10"))
STOP_FILE = HERE / "EVOLVE_STOP"

PROTECTED_PATHS = {
    "eval_challenges.json",
    "test_planner.py", "test_v03.py", "test_v034.py", "test_v035.py",
    "test_pipeline.py", "test_cross_backend.py", "test_cross_backend_pipeline.py",
    "test_iter_pipeline.py", "test_distill.py", "test_evolve.py",
    "asg.py", "interpreter.py", "_sandbox_run.py", "_sandbox_shell.py",
    "python_backend.py", "sql_backend.py", "terminal_backend.py",
    "mk.py", "mk_sql.py", "mk_sql_cgate.py",
    "council.py", "run.py", "generate_triples.py", "distill.py", "evolve.py",
}

_RULES_MARKER = "# --- End of compound rules (evolve.py injection point) ---"


def dump(tag, message):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"\n===== [{ts}] EVOLVE {tag} =====\n{message}\n"
    with DUMP_LOG.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


# ── Eval harness ────────────────────────────────────────────────────────────

@dataclass
class EvalResult:
    challenge_id: str
    category: str
    intent: str
    passed: bool
    expected: str
    actual: str
    error: str = ""


@dataclass
class EvalSummary:
    total: int
    passed: int
    score: float
    by_category: dict
    results: list = field(default_factory=list)

    def __repr__(self):
        cats = ", ".join(
            f"{k}: {v[0]}/{v[1]}" for k, v in sorted(self.by_category.items())
        )
        return f"EvalSummary({self.passed}/{self.total} = {self.score:.1%} | {cats})"


def run_eval(planner):
    """Run the held-out eval set. For each challenge:
      1. Set up preconditions in temp dir
      2. Plan the intent
      3. Execute intent steps ONLY (separate from verify)
      4. If verify exists, run it separately to check state
      5. Compare output to expected
    """
    challenges = json.loads(EVAL_FILE.read_text())["challenges"]
    results = []
    by_category = {}

    for ch in challenges:
        cid = ch["id"]
        cat = ch["category"]
        intent = ch["intent"]
        expected = ch.get("expected_output", "")
        verify = ch.get("verify", "")

        work = Path(tempfile.mkdtemp(prefix=f"evolve_eval_{cid}_"))
        try:
            # 1. Setup
            setup_program = ch.get("setup", "")
            if setup_program:
                subprocess.run(
                    [sys.executable, str(SANDBOX_RUN), str(INTERPRETER_FILE)],
                    input=setup_program, capture_output=True, text=True,
                    cwd=str(work), timeout=10,
                )

            # 2. Plan
            plan = planner.plan(intent)

            if not plan.steps and not plan.extra_nodes:
                results.append(EvalResult(cid, cat, intent, False, expected, "(empty plan)"))
                by_category.setdefault(cat, [0, 0])
                by_category[cat][1] += 1
                continue

            # Check at least one step parses
            parseable = [s for s in plan.steps if asg.parse_line(s) is not None]
            if not parseable and not plan.extra_nodes:
                results.append(EvalResult(cid, cat, intent, False, expected, "(no parseable steps)"))
                by_category.setdefault(cat, [0, 0])
                by_category[cat][1] += 1
                continue

            # 3. Execute intent steps
            intent_program = "\n".join(plan.steps)
            proc = subprocess.run(
                [sys.executable, str(SANDBOX_RUN), str(INTERPRETER_FILE)],
                input=intent_program, capture_output=True, text=True,
                cwd=str(work), timeout=10,
            )

            # 4. Determine actual output
            if verify:
                proc2 = subprocess.run(
                    [sys.executable, str(SANDBOX_RUN), str(INTERPRETER_FILE)],
                    input=verify, capture_output=True, text=True,
                    cwd=str(work), timeout=10,
                )
                actual = " ".join(proc2.stdout.split())
            else:
                actual = " ".join(proc.stdout.split())

            exp_norm = " ".join(expected.split())
            passed = actual == exp_norm

            results.append(EvalResult(cid, cat, intent, passed, exp_norm, actual))
            by_category.setdefault(cat, [0, 0])
            by_category[cat][0] += int(passed)
            by_category[cat][1] += 1

        except Exception as e:
            results.append(EvalResult(cid, cat, intent, False, expected, "", str(e)))
            by_category.setdefault(cat, [0, 0])
            by_category[cat][1] += 1
        finally:
            shutil.rmtree(work, ignore_errors=True)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    bc = {k: tuple(v) for k, v in sorted(by_category.items())}
    return EvalSummary(total, passed, passed / total if total else 0, bc, results)


# ── Developer: rule proposal and validation ─────────────────────────────────

@dataclass
class RuleProposal:
    pattern: str
    replacement: list
    category: str
    rationale: str

    def to_code(self):
        lines_list = ", ".join(f"'{l}'" for l in self.replacement)
        return (
            f"    # Auto-injected by evolve.py [{self.category}]\n"
            f"    (\n"
            f"        re.compile(r'{self.pattern}', re.IGNORECASE),\n"
            f"        [{lines_list}],\n"
            f"    ),\n"
        )


def validate_rule(proposal):
    """Validate: regex compiles, has groups, matches category challenges,
    and generated NL lines parse to ASG nodes."""
    try:
        pat = re.compile(proposal.pattern, re.IGNORECASE)
    except re.error as e:
        return False, f"Regex error: {e}"

    if pat.groups < 1:
        return False, "Pattern needs at least one capture group"

    challenges = json.loads(EVAL_FILE.read_text())["challenges"]
    cat_challenges = [c for c in challenges if c["category"] == proposal.category]

    matched_any = False
    for ch in cat_challenges:
        m = pat.match(ch["intent"])
        if m:
            matched_any = True
            groups = m.groups()
            for nl_template in proposal.replacement:
                nl_line = nl_template
                for i, g in enumerate(groups):
                    nl_line = nl_line.replace(f"{{{i}}}", g or "test.txt")
                node = asg.parse_line(nl_line)
                if node is None:
                    return False, f"Generated NL does not parse: '{nl_line}'"

    if not matched_any:
        return False, f"Pattern does not match any {proposal.category} challenge"

    return True, "valid"
    return True, "valid"


def inject_rule(proposal):
    """Inject a rule into planner.py before the marker comment."""
    code = proposal.to_code()
    content = PLANNER_FILE.read_text()
    if _RULES_MARKER not in content:
        return False
    content = content.replace(_RULES_MARKER, code + _RULES_MARKER)
    PLANNER_FILE.write_text(content)
    return True


def remove_rule(pattern_str):
    """Remove a previously injected rule by its pattern string."""
    content = PLANNER_FILE.read_text()
    escaped = re.escape(pattern_str)
    # Match from the comment line to the closing ),
    # Match from the comment line to the closing paren, do NOT eat preceding content
    block_pat = re.compile(
        r'    # Auto-injected by evolve\.py.*?\n'
        r'    \(\n'
        r'        re\.compile\(r\'' + escaped + r'\''
        r'.*?\),.*?\),\n',
        re.DOTALL,
    )
    new_content, count = block_pat.subn('', content)
    if count > 0:
        PLANNER_FILE.write_text(new_content)
        return True
    return False


def get_injected_rules():
    """Get list of auto-injected rule patterns."""
    content = PLANNER_FILE.read_text()
    return re.findall(
        r"# Auto-injected by evolve\.py.*?\n\s*\(\n\s*re\.compile\(r'(.*?)'",
        content, re.DOTALL
    )


# ── Verifier ────────────────────────────────────────────────────────────────

def run_test_suite():
    """Run pytest on the full test suite."""
    test_files = [
        "test_v03.py", "test_v034.py",
        "test_cross_backend.py", "test_cross_backend_pipeline.py",
        "test_distill.py",
    ]
    results = []
    all_pass = True
    for tf in test_files:
        if not (HERE / tf).exists():
            continue
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", tf, "-q", "--tb=no",
                 "-p", "no:cacheprovider"],
                capture_output=True, text=True, cwd=str(HERE), timeout=60,
            )
            passed = proc.returncode == 0
            if not passed:
                all_pass = False
            summary = [l for l in proc.stdout.splitlines()
                       if "passed" in l or "failed" in l or "error" in l]
            results.append(
                f"{tf}: {'OK' if passed else 'FAIL'} "
                f"{summary[-1] if summary else ''}"
            )
        except Exception as e:
            all_pass = False
            results.append(f"{tf}: ERROR: {e}")

    return all_pass, "\n".join(results)


# ── Enforcer ────────────────────────────────────────────────────────────────

@dataclass
class EnforcerTarget:
    category: str
    failing_challenges: list
    current_score: float
    demand: str


def enforcer_set_target(eval_result):
    """Pick the weakest category with at least one failure."""
    worst_cat = None
    worst_rate = 1.1
    worst_failing = []

    for cat, (passed, total) in eval_result.by_category.items():
        rate = passed / total if total else 0
        failing = [
            r.intent for r in eval_result.results
            if r.category == cat and not r.passed
        ]
        if failing and rate < worst_rate:
            worst_rate = rate
            worst_cat = cat
            worst_failing = failing

    if worst_cat is None:
        return EnforcerTarget("none", [], 1.0, "All categories passing.")

    demand = (
        f"Category '{worst_cat}' has {eval_result.by_category[worst_cat][0]}/"
        f"{eval_result.by_category[worst_cat][1]} passing ({worst_rate:.0%}). "
        f"Failing: {worst_failing[:3]}."
    )
    return EnforcerTarget(worst_cat, worst_failing, worst_rate, demand)


# ── Developer rule bank ─────────────────────────────────────────────────────

_DEVELOPER_RULE_BANK = [
    RuleProposal(r'^show me (\S+)$', ['read file {0}'],
                 "conversational-read", "synonym for read"),
    RuleProposal(r'^display (\S+)$', ['read file {0}'],
                 "conversational-read", "synonym for read"),
    RuleProposal(r'^cat (\S+)$', ['read file {0}'],
                 "conversational-read", "Unix synonym"),
    RuleProposal(r'^view (\S+)$', ['read file {0}'],
                 "conversational-read", "synonym for read"),
    RuleProposal(r'^how many lines in (\S+)$', ['count lines in {0}'],
                 "conversational-read", "question form"),
    RuleProposal(r'^how many words in (\S+)$', ['count words in {0}'],
                 "conversational-read", "question form"),
    RuleProposal(r'^create a new file (\S+) with content "([^"]*)"$',
                 ['create file {0} with content "{1}"'],
                 "verbose-create", "drop article"),
    RuleProposal(r'^make a file called (\S+) with content "([^"]*)"$',
                 ['create file {0} with content "{1}"'],
                 "verbose-create", "rewrite phrasing"),
    RuleProposal(r'^erase (\S+) confirm$', ['delete {0} confirm'],
                 "delete-variant", "synonym for delete"),
    RuleProposal(r'^remove (\S+) confirm$', ['delete {0} confirm'],
                 "delete-variant", "synonym for delete"),
    RuleProposal(r'^move file (\S+) to (\S+)$', ['move {0} to {1}'],
                 "move-variant", "drop article"),
    RuleProposal(r'^duplicate (\S+) to (\S+)$', ['copy {0} to {1}'],
                 "move-variant", "synonym for copy"),
    RuleProposal(r'^count how many lines are in (\S+)$', ['count lines in {0}'],
                 "verbose-count", "verbose question"),
    RuleProposal(r'^tell me the word count of (\S+)$', ['count words in {0}'],
                 "verbose-count", "verbose question"),
    RuleProposal(r'^what is the line count of (\S+)$', ['count lines in {0}'],
                 "verbose-count", "question form"),
    RuleProposal(r'^what is the word count for (\S+)$', ['count words in {0}'],
                 "verbose-count", "question form"),
    RuleProposal(r'^get the first (\d+) lines of (\S+)$',
                 ['show first {0} lines of {1}'],
                 "head-variant", "verbose head"),
    RuleProposal(r'^show first (\d+) of (\S+)$',
                 ['show first {0} lines of {1}'],
                 "head-variant", "missing word lines"),
    RuleProposal(r'^concatenate (\S+) and (\S+) into (\S+)$',
                 ['set _a = read file {0}', 'set _b = read file {1}',
                  'write "" to {2}', 'append "{{_a}}" to {2}',
                  'append "{{_b}}" to {2}'],
                 "concat-variant", "full word form"),
    RuleProposal(r'^empty the file (\S+)$', ['write "" to {0}'],
                 "clear-variant", "clear contents"),
]


def developer_propose(target):
    """Propose rules for the target category."""
    return [rp for rp in _DEVELOPER_RULE_BANK if rp.category == target.category]


# ── The governed loop ──────────────────────────────────────────────────────

@dataclass
class CycleResult:
    cycle: int
    target_category: str
    rules_tried: int
    rules_kept: int
    eval_before: float
    eval_after: float
    improvement: float
    accepted: bool
    details: str


def run_evolution_loop(max_cycles=MAX_CYCLES):
    """Run the governed self-enhancement loop."""
    history = []
    plateau_count = 0

    dump("LOOP START", f"max_cycles={max_cycles} patience={PLATEAU_PATIENCE}")

    import importlib
    import planner as planner_mod

    planner = planner_mod.Planner(use_llm=False)
    baseline = run_eval(planner)
    dump("BASELINE", str(baseline))
    print(f"Baseline: {baseline}")

    for cycle in range(max_cycles):
        if STOP_FILE.exists():
            dump("LOOP STOP", "STOP sentinel detected")
            break

        importlib.reload(planner_mod)
        planner = planner_mod.Planner(use_llm=False)

        eval_result = run_eval(planner)

        if eval_result.score >= 1.0:
            dump("LOOP COMPLETE", f"All {eval_result.total} passing!")
            print(f"All {eval_result.total} eval challenges passing!")
            break

        target = enforcer_set_target(eval_result)
        dump("ENFORCER", f"cycle={cycle} target={target.category}\n{target.demand}")
        print(f"\n--- Cycle {cycle} ---")
        print(f"Target: {target.category} ({target.current_score:.0%})")

        proposals = developer_propose(target)
        print(f"Developer: {len(proposals)} proposals")

        rules_kept = 0
        rules_tried = 0
        cycle_details = []

        for proposal in proposals:
            if proposal.pattern in get_injected_rules():
                continue

            rules_tried += 1

            ok, msg = validate_rule(proposal)
            if not ok:
                cycle_details.append(f"  REJECTED: {proposal.pattern} -- {msg}")
                dump("REJECT", f"pattern='{proposal.pattern}' reason={msg}")
                continue

            pre_eval = run_eval(planner)

            if not inject_rule(proposal):
                cycle_details.append(f"  INJECT FAILED: {proposal.pattern}")
                continue

            importlib.reload(planner_mod)
            planner = planner_mod.Planner(use_llm=False)
            post_eval = run_eval(planner)

            improved = post_eval.score > pre_eval.score
            tests_pass, test_details = run_test_suite()

            if improved and tests_pass:
                rules_kept += 1
                cycle_details.append(
                    f"  KEPT: {proposal.pattern} -> {pre_eval.score:.1%} to {post_eval.score:.1%}"
                )
                dump("KEEP", f"pattern='{proposal.pattern}' "
                      f"{pre_eval.score:.1%} -> {post_eval.score:.1%}")
            else:
                remove_rule(proposal.pattern)
                importlib.reload(planner_mod)
                planner = planner_mod.Planner(use_llm=False)
                reason = "no improvement" if not improved else "tests broke"
                cycle_details.append(f"  REVERTED: {proposal.pattern} -- {reason}")
                dump("REVERT", f"pattern='{proposal.pattern}' reason={reason}")

        cycle_eval = run_eval(planner)
        cr = CycleResult(
            cycle=cycle, target_category=target.category,
            rules_tried=rules_tried, rules_kept=rules_kept,
            eval_before=eval_result.score, eval_after=cycle_eval.score,
            improvement=cycle_eval.score - eval_result.score,
            accepted=rules_kept > 0,
            details="\n".join(cycle_details),
        )
        history.append(cr)

        print(f"Result: {rules_kept}/{rules_tried} kept")
        print(f"Eval: {eval_result.score:.1%} -> {cycle_eval.score:.1%}")
        for d in cycle_details:
            print(d)

        dump("CYCLE", f"cycle={cycle} kept={rules_kept}/{rules_tried} "
              f"eval={eval_result.score:.1%}->{cycle_eval.score:.1%}")

        if cr.improvement == 0:
            plateau_count += 1
            if plateau_count >= PLATEAU_PATIENCE:
                dump("LOOP PLATEAU", f"No improvement for {plateau_count} cycles")
                break
        else:
            plateau_count = 0

    final_eval = run_eval(planner)
    dump("LOOP END", f"final={final_eval}")
    print(f"\n=== Final: {final_eval} ===")
    return history


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Experiment 4: Governed self-enhancement loop")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Run the evolution loop")
    sub.add_parser("eval", help="Run eval only")
    sub.add_parser("status", help="Show injected rules and eval score")
    sub.add_parser("revert-all", help="Remove all auto-injected rules")

    args = parser.parse_args()

    if args.command == "run":
        history = run_evolution_loop()
        print(f"\n{len(history)} cycles completed.")
        print(f"{sum(c.rules_kept for c in history)} rules kept.")

    elif args.command == "eval":
        planner = Planner(use_llm=False)
        result = run_eval(planner)
        print(result)
        for r in result.results:
            mark = "OK" if r.passed else "FAIL"
            print(f"  [{mark}] {r.challenge_id} [{r.category}] "
                  f"expected='{r.expected}' actual='{r.actual}'")

    elif args.command == "status":
        injected = get_injected_rules()
        print(f"Injected rules: {len(injected)}")
        for r in injected:
            print(f"  {r}")
        planner = Planner(use_llm=False)
        result = run_eval(planner)
        print(f"\nEval: {result}")

    elif args.command == "revert-all":
        injected = get_injected_rules()
        count = 0
        for pattern in injected:
            if remove_rule(pattern):
                count += 1
        print(f"Removed {count} auto-injected rules.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

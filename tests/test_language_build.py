"""Verify the verifier — the execution gate the overnight build phase trusts.

The whole build convergence hinges on `score_interpreter` executing council-written
code and honestly reporting which capabilities pass. If the scorer is wrong, the
overnight run optimises noise. So: a known-correct interpreter for our natural-language
→ OS abstraction layer must score 11/11, a crippled one (broken fail-closed safety) must
score strictly less, and junk must score 0. Offline, no models, sandboxed per test.
"""

from __future__ import annotations

import sys
from pathlib import Path

LANG = Path(__file__).resolve().parent.parent / "projects" / "language"
sys.path.insert(0, str(LANG))

from council import CONFORMANCE, extract_code, score_interpreter  # noqa: E402

# A deliberately minimal, correct interpreter for the structured-NL → OS layer the
# council is building (per the AIOS/CoRE cheat code). Used ONLY to test the scorer.
GOOD = r'''
import os
import re
import shutil
import sys

def _exec(line, out):
    line = line.strip()
    if not line:
        return
    m = re.match(r'if (\S+) exists then (.+?) otherwise (.+)$', line)
    if m:
        tgt, then_c, else_c = m.groups()
        _exec(then_c if os.path.exists(tgt) else else_c, out)
        return
    m = re.match(r'create file (\S+) with content "(.*)"$', line)
    if m:
        with open(m.group(1), "w") as f:
            f.write(m.group(2))
        return
    m = re.match(r'read file (\S+)$', line)
    if m:
        with open(m.group(1)) as f:
            out.append(f.read())
        return
    m = re.match(r'append "(.*)" to (\S+)$', line)
    if m:
        with open(m.group(2), "a") as f:
            f.write("\n" + m.group(1))
        return
    m = re.match(r'count lines in (\S+)$', line)
    if m:
        with open(m.group(1)) as f:
            out.append(str(len(f.read().splitlines())))
        return
    m = re.match(r'copy (\S+) to (\S+)$', line)
    if m:
        shutil.copy(m.group(1), m.group(2))
        return
    m = re.match(r'make directory (\S+)$', line)
    if m:
        os.makedirs(m.group(1), exist_ok=True)
        return
    m = re.match(r'move (\S+) to (\S+)$', line)
    if m:
        shutil.move(m.group(1), m.group(2))
        return
    m = re.match(r'list files in (\S+)$', line)
    if m:
        names = sorted(os.listdir(m.group(1)))
        out.append(" ".join(names) if names else "(empty)")
        return
    if line == "list files":
        names = sorted(os.listdir("."))
        out.append(" ".join(names) if names else "(empty)")
        return
    m = re.match(r'find files containing "(.*)"$', line)
    if m:
        hits = []
        for n in sorted(os.listdir(".")):
            if os.path.isfile(n):
                try:
                    if m.group(1) in open(n).read():
                        hits.append(n)
                except OSError:
                    pass
        out.append(" ".join(hits) if hits else "(none)")
        return
    m = re.match(r'delete (\S+)( confirm)?$', line)
    if m:
        if not m.group(2):
            out.append("REFUSED")
            return
        if os.path.exists(m.group(1)):
            os.remove(m.group(1))
        return
    out.append("UNKNOWN: " + line)

def run(source):
    out = []
    for line in source.splitlines():
        _exec(line, out)
    sys.stdout.write("\n".join(out))
'''

# Same interpreter, but the fail-closed safety rule is broken: delete always deletes,
# even without `confirm`. Must lose the "refuse irreversible" capability → score < 11.
_REFUSE_GUARD = (
    '        if not m.group(2):\n'
    '            out.append("REFUSED")\n'
    '            return\n'
)
CRIPPLED = GOOD.replace(_REFUSE_GUARD, "")


def test_known_good_passes_everything() -> None:
    passing, details = score_interpreter(GOOD, CONFORMANCE)
    assert len(passing) == len(CONFORMANCE), details
    assert set(passing) == {n for n, _, _ in CONFORMANCE}


def test_crippled_loses_failclosed_safety() -> None:
    passing, _ = score_interpreter(CRIPPLED, CONFORMANCE)
    assert "safety-refuse-irreversible" not in passing
    assert len(passing) < len(CONFORMANCE)


def test_junk_scores_zero() -> None:
    junk = "def run(s):\n    raise ValueError('nope')"
    passing, _ = score_interpreter(junk, CONFORMANCE)
    assert passing == []


def test_empty_source_scores_zero() -> None:
    assert score_interpreter("", CONFORMANCE)[0] == []


def test_extract_code_prefers_python_block() -> None:
    reply = "Here you go:\n```python\ndef run(s):\n    print(s)\n```\nDone."
    assert extract_code(reply) == "def run(s):\n    print(s)"


def test_extract_code_picks_the_block_with_an_entry_point() -> None:
    # A reply with a usage-example block first and the real interpreter second:
    # extract_code must return the one that defines an entry point.
    reply = (
        "Example:\n```python\nprint('demo')\n```\n"
        "Interpreter:\n```python\nimport sys\n"
        "def run(src):\n    sys.stdout.write('ok')\n```"
    )
    assert "def run(src)" in extract_code(reply)
    assert "print('demo')" not in extract_code(reply)


def _adoption_harness(monkeypatch, proposal_code: str, fresh: bool):
    """Drive run_build_round offline: stub the model call + scorer so only the
    adoption decision is exercised. Incumbent + any 'NEW' proposal each pass 3 caps."""
    import council

    names = [n for n, _, _ in council.CONFORMANCE]
    monkeypatch.setattr(council, "gather_interpreters",
                        lambda *a, **k: [("model-x", proposal_code)])

    def fake_score(src, suite):
        return (names[:3], {}) if ("OLD" in src or "NEW" in src) else ([], {})

    monkeypatch.setattr(council, "score_interpreter", fake_score)
    return council.run_build_round(
        1, "spec", "OLDCODE", names[:3], council.CONFORMANCE, 1, "", fresh
    )


def test_fresh_start_accepts_equal_rederivation(monkeypatch) -> None:
    log, src, _ = _adoption_harness(monkeypatch, "NEWCODE", fresh=True)
    assert src == "NEWCODE"  # sideways move onto a new foundation escapes the plateau
    assert "re-seeded" in log.note


def test_normal_round_rejects_equal_score(monkeypatch) -> None:
    log, src, _ = _adoption_harness(monkeypatch, "NEWCODE", fresh=False)
    assert src == "OLDCODE"  # never adopt a non-improvement in a normal round
    assert "status quo held" in log.note


def test_fresh_start_keeps_identical_foundation(monkeypatch) -> None:
    log, src, _ = _adoption_harness(monkeypatch, "OLDCODE", fresh=True)
    assert src == "OLDCODE"  # equal score AND identical code → no pointless switch
    assert "same foundation" in log.note

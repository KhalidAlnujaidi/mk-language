"""Verify the verifier — the execution gate the overnight build phase trusts.

The whole Phase-3 convergence hinges on `score_interpreter` executing council-written
code and honestly reporting which capabilities pass. If the scorer is wrong, the
overnight run optimises noise. So: a known-correct interpreter must score 11/11, a
crippled one must score strictly less, and junk must score 0. Offline, no models.
"""

from __future__ import annotations

import sys
from pathlib import Path

LANG = Path(__file__).resolve().parent.parent / "projects" / "language"
sys.path.insert(0, str(LANG))

from council import CONFORMANCE, extract_code, score_interpreter  # noqa: E402

# A deliberately minimal, correct tree-walking interpreter for the council's language
# (the canonical lispy shape — reuse, don't reinvent). Used ONLY to test the scorer.
GOOD = r'''
import sys
from math import prod

class Sym(str): pass

def tokenize(s):
    return s.replace("(", " ( ").replace(")", " ) ").split()

def atom(t):
    if t.startswith('"') and t.endswith('"'):
        return t[1:-1]
    try:
        return int(t)
    except ValueError:
        return Sym(t)

def read_from(toks):
    t = toks.pop(0)
    if t == "(":
        lst = []
        while toks[0] != ")":
            lst.append(read_from(toks))
        toks.pop(0)
        return lst
    return atom(t)

def parse_program(src):
    toks = tokenize(src)
    forms = []
    while toks:
        forms.append(read_from(toks))
    return forms

class Env(dict):
    def __init__(self, init=None, outer=None):
        super().__init__()
        if init:
            self.update(init)
        self.outer = outer
    def find(self, v):
        if v in self:
            return self
        if self.outer is None:
            raise NameError(v)
        return self.outer.find(v)

class Proc:
    def __init__(self, params, body, env):
        self.params, self.body, self.env = params, body, env
    def __call__(self, *args):
        return eval_(self.body, Env(dict(zip(self.params, args)), self.env))

def to_display(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "(" + " ".join(to_display(x) for x in v) + ")"
    return str(v)

def standard_env():
    e = Env()
    e.update({
        "+": lambda *a: sum(a),
        "-": lambda a, b: a - b,
        "*": lambda *a: prod(a),
        "<": lambda a, b: a < b,
        "list": lambda *a: list(a),
        "map": lambda f, l: [f(x) for x in l],
        "string-append": lambda *a: "".join(a),
    })
    return e

def eval_(x, env):
    if isinstance(x, Sym):
        if x == "true":
            return True
        if x == "false":
            return False
        return env.find(x)[x]
    if not isinstance(x, list):
        return x
    op = x[0]
    if isinstance(op, Sym):
        if op == "if":
            return eval_(x[2] if eval_(x[1], env) else x[3], env)
        if op == "define":
            if isinstance(x[1], list):
                env[x[1][0]] = Proc(x[1][1:], x[2], env)
            else:
                env[x[1]] = eval_(x[2], env)
            return None
        if op == "lambda":
            return Proc(x[1], x[2], env)
        if op == "let":
            local = Env(outer=env)
            for b in x[1]:
                local[b[0]] = eval_(b[1], local)
            return eval_(x[2], local)
        if op == "display":
            sys.stdout.write(to_display(eval_(x[1], env)))
            return None
    proc = eval_(op, env)
    return proc(*[eval_(a, env) for a in x[1:]])

def run(source):
    env = standard_env()
    for form in parse_program(source):
        eval_(form, env)
'''

# Same interpreter, but closures are broken (lambda captures nothing) — must score < 11.
CRIPPLED = GOOD.replace(
    "        if op == \"lambda\":\n            return Proc(x[1], x[2], env)",
    "        if op == \"lambda\":\n            return Proc(x[1], x[2], standard_env())",
)


def test_known_good_passes_everything() -> None:
    passing, details = score_interpreter(GOOD, CONFORMANCE)
    assert len(passing) == len(CONFORMANCE), details
    assert set(passing) == {n for n, _, _ in CONFORMANCE}


def test_crippled_interpreter_loses_closure() -> None:
    passing, _ = score_interpreter(CRIPPLED, CONFORMANCE)
    assert "closure" not in passing
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

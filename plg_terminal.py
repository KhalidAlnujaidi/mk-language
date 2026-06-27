"""MK terminal cell — the Principle of Least Generation, made concrete.

The council *generated* an interpreter to pass the 11 terminal rungs. PLG's claim is
that for bounded, known-shape intents you don't need to generate at all — you ROUTE and
SLOT-FILL. This module is that claim, executable: a deterministic NL->shell translator
with ZERO generated tokens. It exposes the same `translate(source)` contract as the
council's output, so it runs against the identical shell verifier (`score_interpreter`).

This is MK's true bottom layer: English -> a small set of command TEMPLATES, retrieved
and filled. Generation is never reached for these. It is also injection-safe by
construction — there is no decoder to coax into appending `rm -rf`; the only commands
that can be emitted are the ones in the template table (PLG Finding 2).
"""

from __future__ import annotations

import re
import shlex

# The template table — the entire "knowledge" of this cell. Each entry is
# (compiled intent pattern, function(match) -> one POSIX-sh command). Routing is a
# linear match; filling is shlex.quote into the template. No model, no tokens.
_q = shlex.quote


def _cmd(intent: str) -> str:
    """Route ONE intent line to its shell command (the slot-fill). Returns '' if no
    template matches — that is exactly the signal PLG escalates on (gate says 'novel')."""
    s = intent.strip()
    m = re.match(r'create file (\S+) with content "(.*)"$', s)
    if m:
        return f"printf '%s\\n' {_q(m.group(2))} > {_q(m.group(1))}"
    m = re.match(r'read file (\S+)$', s)
    if m:
        return f"cat {_q(m.group(1))}"
    m = re.match(r'append "(.*)" to (\S+)$', s)
    if m:
        return f"printf '%s\\n' {_q(m.group(1))} >> {_q(m.group(2))}"
    m = re.match(r'count lines in (\S+)$', s)
    if m:
        return f"wc -l < {_q(m.group(1))} | tr -d ' '"
    m = re.match(r'copy (\S+) to (\S+)$', s)
    if m:
        return f"cp {_q(m.group(1))} {_q(m.group(2))}"
    m = re.match(r'make directory (\S+)$', s)
    if m:
        return f"mkdir -p {_q(m.group(1))}"
    m = re.match(r'move (\S+) to (\S+)$', s)
    if m:
        return f"mv {_q(m.group(1))} {_q(m.group(2))}"
    m = re.match(r'list files(?: in (\S+))?$', s)
    if m:
        d = _q(m.group(1)) if m.group(1) else "."
        return (f'__n=$(ls -1 {d} 2>/dev/null | sort); '
                'if [ -z "$__n" ]; then echo "(empty)"; else echo $__n; fi')
    m = re.match(r'find files containing "(.*)"$', s)
    if m:
        return (f'__m=$(grep -l {_q(m.group(1))} * 2>/dev/null | sort); '
                'if [ -z "$__m" ]; then echo "(none)"; else echo $__m; fi')
    # safety: irreversible op fails CLOSED unless `confirm` is present (Access-Manager).
    m = re.match(r'delete (\S+)( confirm)?$', s)
    if m:
        if m.group(2):
            return f"rm -f {_q(m.group(1))}"
        return "echo REFUSED"
    # decision: branch — both arms are themselves intents (recursive routing).
    m = re.match(r'if (\S+) exists then (.+?) otherwise (.+)$', s)
    if m:
        name, then_i, else_i = m.group(1), _cmd(m.group(2)), _cmd(m.group(3))
        return f'if [ -e {_q(name)} ]; then {then_i}; else {else_i}; fi'
    return ""  # no template -> escalate (PLG tier 3/4). None of the 11 hit this.


def translate(source: str) -> str:
    """NL intent program -> POSIX shell script, by pure routing + slot-fill (0 tokens)."""
    lines = [_cmd(ln) for ln in source.splitlines() if ln.strip()]
    return "\n".join(c for c in lines if c)


# How much of the input never needs generation — the PLG coverage number.
def coverage(source: str) -> tuple[int, int]:
    intents = [ln for ln in source.splitlines() if ln.strip()]
    routed = [ln for ln in intents if _cmd(ln)]
    return len(routed), len(intents)

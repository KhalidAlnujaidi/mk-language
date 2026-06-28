"""Planner/Composer — decomposes complex NL intents into ASG-parseable steps.

The thesis (from V03-PLAN.md §3): the ASG parser handles single-line intents with
rigid phrasing. The planner bridges the gap between how a human naturally describes
a multi-step task and the structured NL the parser expects.

Architecture (asymmetry thesis — ground truth beats model):
  1. Deterministic rules handle common compound intents (fast, no model).
  2. LLM fallback (Ollama) decomposes novel complex requests into structured NL.
  3. The existing parser + backends handle execution — the planner never executes.

Deterministic patterns:
  - Conjunction splitting: "create X and read X" → two lines
  - Sequential: "create X then read X" → two lines
  - Common compound intents: "backup NAME", "file info NAME", "init project NAME"
  - Pipeline: "read NAME, count lines, and sort" → ordered steps

LLM fallback:
  - Prompted with the 16-node ASG vocabulary and their exact NL syntax
  - Returns one intent per line, each matching a known parse pattern
  - Output is validated: every line must parse to a non-None ASG node
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Import for execution
import asg
from interpreter import execute

# Ollama client (same pattern as council.py)
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
PLANNER_MODEL = os.environ.get("PLANNER_MODEL", "qwen3:8b")
PLANNER_TIMEOUT = 120.0


# ---------------------------------------------------------------------------
# ASG vocabulary — the exact NL syntax the parser accepts
# ---------------------------------------------------------------------------

ASG_VOCABULARY = """\
The following intent types are ALL the parser understands. Every line you output
MUST match exactly one of these patterns (substitute actual values for the
uppercase placeholders):

  create file NAME with content "TEXT"      — create a new file (refuses overwrite)
  read file NAME                            — print file contents
  append "TEXT" to NAME                     — append text as new line
  count lines in NAME                       — print line count
  count words in NAME                       — print word count
  sort lines in NAME                        — print lines sorted alphabetically
  show first N lines of NAME                — print first N lines
  sum numbers in NAME                       — print sum of all integers in file
  extract lines matching "PATTERN" from NAME — print matching lines
  copy SRC to DEST                          — copy file (refuses if dest exists)
  make directory NAME                       — create directory
  move SRC to DEST                          — move file or into directory
  list files                                — list files in current dir
  list files in DIR                         — list files in a directory
  find files containing "TEXT"              — find files containing text
  delete NAME                               — refused unless confirmed
  delete NAME confirm                       — delete with confirmation
  if NAME exists then INTENT otherwise INTENT — conditional execution
"""


# ---------------------------------------------------------------------------
# Deterministic decomposition rules
# ---------------------------------------------------------------------------

# Conjunction patterns that mean "do step A, then step B"
_CONJUNCTIONS = [
    r'\s+then\s+',
    r'\s+and then\s+',
    r'\s+after that\s+',
    r';\s*',
    r'\s+->\s+',
    r'\s+→\s+',
]


def _split_conjunctions(text: str) -> list[str]:
    """Split a compound sentence on conjunctions. Returns parts that are
    each potentially valid single-line intents."""
    parts = [text.strip()]
    for pattern in _CONJUNCTIONS:
        new_parts = []
        for p in parts:
            new_parts.extend(re.split(pattern, p))
        parts = [p.strip() for p in new_parts if p.strip()]
    return parts


# Compound intent templates: regex → list of NL lines (with {placeholders})
_COMPOUND_RULES: list[tuple[re.Pattern, list[str]]] = [
    # "backup NAME" → copy NAME to backup of NAME
    (
        re.compile(r'^backup (\S+)$', re.IGNORECASE),
        ['copy {0} to backup_{0}'],
    ),
    # "backup NAME to DEST" → copy
    (
        re.compile(r'^backup (\S+) to (\S+)$', re.IGNORECASE),
        ['copy {0} to {1}'],
    ),
    # "file info NAME" → count lines + count words
    (
        re.compile(r'^file info(?:rmation)? for (\S+)$', re.IGNORECASE),
        ['count lines in {0}', 'count words in {0}'],
    ),
    # "stats for NAME" → count lines + count words
    (
        re.compile(r'^stats for (\S+)$', re.IGNORECASE),
        ['count lines in {0}', 'count words in {0}'],
    ),
    # "init project NAME" → mkdir + create readme
    (
        re.compile(r'^init(?:ialize)? project (\S+)$', re.IGNORECASE),
        ['make directory {0}', 'create file {0}/README.txt with content "Project: {0}"'],
    ),
    # "create and read NAME with TEXT" → create + read
    (
        re.compile(r'^create and read (\S+) with content "([^"]*)"$', re.IGNORECASE),
        ['create file {0} with content "{1}"', 'read file {0}'],
    ),
    # "duplicate NAME" → copy to a backup name
    (
        re.compile(r'^duplicate (\S+)$', re.IGNORECASE),
        ['copy {0} to copy_of_{0}'],
    ),
    # "safe delete NAME" → delete with confirm
    (
        re.compile(r'^safe delete (\S+)$', re.IGNORECASE),
        ['delete {0} confirm'],
    ),
    # "inspect NAME" → read + count lines + count words
    (
        re.compile(r'^inspect (\S+)$', re.IGNORECASE),
        ['read file {0}', 'count lines in {0}', 'count words in {0}'],
    ),
    # "search for TEXT" → find files containing TEXT
    (
        re.compile(r'^search for "([^"]*)"$', re.IGNORECASE),
        ['find files containing "{0}"'],
    ),
    # "grep TEXT in NAME" → extract lines matching TEXT from NAME
    (
        re.compile(r'^grep "([^"]*)" in (\S+)$', re.IGNORECASE),
        ['extract lines matching "{0}" from {1}'],
    ),
    # "head NAME" → show first 10 lines
    (
        re.compile(r'^head (\S+)$', re.IGNORECASE),
        ['show first 10 lines of {0}'],
    ),
    # "head N NAME" → show first N lines
    (
        re.compile(r'^head (\d+) (\S+)$', re.IGNORECASE),
        ['show first {0} lines of {1}'],
    ),
    # "total NAME" → sum numbers
    (
        re.compile(r'^total (\S+)$', re.IGNORECASE),
        ['sum numbers in {0}'],
    ),
    # "sort NAME" → sort lines
    (
        re.compile(r'^sort (\S+)$', re.IGNORECASE),
        ['sort lines in {0}'],
    ),
    # "wordcount NAME" → count words
    (
        re.compile(r'^wordcount (\S+)$', re.IGNORECASE),
        ['count words in {0}'],
    ),
    # "wc NAME" → count lines + count words
    (
        re.compile(r'^wc (\S+)$', re.IGNORECASE),
        ['count lines in {0}', 'count words in {0}'],
    ),
]


def _try_compound_rules(text: str) -> Optional[list[str]]:
    """Try matching against compound intent rules. Returns list of NL lines or None."""
    for pattern, template_lines in _COMPOUND_RULES:
        m = pattern.match(text.strip())
        if m:
            groups = m.groups()
            return [tpl.format(*groups) for tpl in template_lines]
    return None


def _validate_steps(steps: list[str]) -> list[str]:
    """Filter out steps that don't parse to valid ASG nodes."""
    valid = []
    for step in steps:
        if asg.parse_line(step) is not None:
            valid.append(step)
    return valid


# ---------------------------------------------------------------------------
# LLM-based decomposition (Ollama fallback)
# ---------------------------------------------------------------------------

_LLM_SYSTEM = """\
You are a PLANNER for the MK NL→OS translation system. Your job: take a complex \
natural-language request and decompose it into a sequence of SIMPLE single-line \
intents that the MK parser can handle.

Rules:
1. Output ONLY intent lines — one per line. No explanations, no markdown, no \
commentary.
2. Every line MUST match one of the documented intent patterns EXACTLY.
3. Use realistic filenames and content derived from the request.
4. If the request involves a safety-sensitive operation (delete), include \
`confirm` if the user clearly wants it done, or omit it if they're just asking \
about it (the system will refuse, which is correct).
5. Preserve the LOGICAL ORDER of operations (create before read, etc.).
6. If the request is ambiguous, make a reasonable interpretation and decompose \
it. Do not ask questions.
"""

_LLM_USER_TEMPLATE = """\
Decompose this request into MK intent lines:

REQUEST: {request}

{vocabulary}

Output the intent lines ONLY (one per line, no numbering, no explanations):\
"""


def _call_ollama(request: str) -> list[str]:
    """Call Ollama to decompose a complex request. Returns raw lines."""
    import urllib.request

    payload = json.dumps({
        "model": PLANNER_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM},
            {"role": "user", "content": _LLM_USER_TEMPLATE.format(
                request=request, vocabulary=ASG_VOCABULARY)},
        ],
        "options": {
            "temperature": 0.3,
            "num_predict": 512,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=PLANNER_TIMEOUT) as resp:
        data = json.loads(resp.read())
        text = data.get("message", {}).get("content", "")

    # Strip markdown fences, blank lines, and numbering
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("```"):
            continue
        # Strip leading numbering like "1. " or "1) "
        line = re.sub(r'^\d+[\.\)]\s*', '', line)
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Planner API
# ---------------------------------------------------------------------------

@dataclass
class Plan:
    """A decomposition plan: the original request and the resulting steps."""
    request: str
    steps: list[str]
    source: str = "deterministic"  # "deterministic" | "llm" | "passthrough"
    notes: str = ""

    def to_program(self) -> str:
        """Convert to NL source text (newline-joined) for asg.parse()."""
        return "\n".join(self.steps)

    def to_nodes(self) -> list[asg.ASGNode]:
        """Parse steps into ASG nodes."""
        return asg.parse(self.to_program())

    def __repr__(self) -> str:
        return (f"Plan({len(self.steps)} steps, source={self.source})\n"
                + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(self.steps)))


class Planner:
    """The planner/composer — decomposes complex NL into ASG-parseable steps.

    Strategy (fail-soft): try deterministic rules first (fast, no model), then
    fall back to LLM decomposition (Ollama). If both fail, return the original
    text as a single step (passthrough) — the parser will try it directly.
    """

    def __init__(self, use_llm: bool = True, validate: bool = True):
        self.use_llm = use_llm
        self.validate = validate

    def plan(self, request: str) -> Plan:
        """Decompose a complex NL request into simple ASG-parseable steps.

        Args:
            request: Natural-language request (may be compound/multi-step).

        Returns:
            Plan with the decomposition steps.
        """
        request = request.strip()
        if not request:
            return Plan(request=request, steps=[], source="empty")

        # Pass 1: Try deterministic compound rules first
        compound = _try_compound_rules(request)
        if compound:
            steps = compound if not self.validate else _validate_steps(compound)
            if steps:
                return Plan(request=request, steps=steps, source="deterministic")

        # Pass 2: Try conjunction splitting
        parts = _split_conjunctions(request)
        if len(parts) > 1:
            steps = parts if not self.validate else _validate_steps(parts)
            if steps:
                return Plan(request=request, steps=steps, source="deterministic")

        # Pass 3: Check if the original line already parses
        if asg.parse_line(request) is not None:
            return Plan(request=request, steps=[request], source="passthrough")

        # Pass 4: LLM fallback (if enabled)
        if self.use_llm:
            try:
                raw_lines = _call_ollama(request)
                steps = raw_lines if not self.validate else _validate_steps(raw_lines)
                if steps:
                    return Plan(
                        request=request, steps=steps, source="llm",
                        notes=f"LLM proposed {len(raw_lines)} lines, "
                              f"{len(steps)} validated",
                    )
            except Exception as e:
                return Plan(
                    request=request, steps=[request], source="passthrough",
                    notes=f"LLM failed: {e}",
                )

        # Last resort: passthrough (parser will likely return None)
        return Plan(request=request, steps=[request], source="passthrough")

    def plan_and_execute(self, request: str) -> str:
        """Plan a request, then execute it through the ASG interpreter.

        Returns the execution output (stdout from terminal ops).
        """
        plan = self.plan(request)
        if not plan.steps:
            return ""
        nodes = plan.to_nodes()
        return execute(nodes)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="MK Planner — decompose complex NL into executable steps")
    parser.add_argument("request", help="Natural-language request to plan")
    parser.add_argument("--execute", "-e", action="store_true",
                        help="Execute the plan after decomposing")
    parser.add_argument("--no-llm", action="store_true",
                        help="Disable LLM fallback (deterministic only)")
    parser.add_argument("--json", action="store_true",
                        help="Output plan as JSON")
    args = parser.parse_args()

    planner = Planner(use_llm=not args.no_llm)
    plan = planner.plan(args.request)

    if args.json:
        print(json.dumps({
            "request": plan.request,
            "steps": plan.steps,
            "source": plan.source,
            "notes": plan.notes,
        }, indent=2))
    else:
        print(f"Source: {plan.source}")
        if plan.notes:
            print(f"Notes: {plan.notes}")
        print(f"Steps ({len(plan.steps)}):")
        for i, step in enumerate(plan.steps, 1):
            print(f"  {i}. {step}")

    if args.execute:
        print("\n--- Execution output ---")
        output = planner.plan_and_execute(args.request)
        if output:
            print(output)
        else:
            print("(no output)")


if __name__ == "__main__":
    main()

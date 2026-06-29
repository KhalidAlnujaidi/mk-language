#!/usr/bin/env python3
"""Distillation router — fast embedding-based intent routing for the planner.

The thesis (Experiment 3): replace LLM reasoning (~2s) with embedding retrieval
(~0.05ms) for intent classification. This module wires that thesis into the
planner's fallback path.

Architecture:
  1. Deterministic rules in planner.py handle known compound patterns (fast).
  2. THIS MODULE sits between rules and the LLM:
     a. Embed the user's novel request via nomic-embed-text
     b. Retrieve top-k nearest verified triples from the distillation index
     c. If confidence > threshold → identify the template
     d. Extract parameters from the user's request (template-specific regex)
     e. Generate NL steps with the user's actual parameters
  3. If routing fails (low confidence, extraction fails, index missing) →
     the planner falls through to the LLM fallback. Fail-soft.

Fail-soft contract: every method returns None on any failure. The caller
(planner) treats None as "router can't help, try LLM."
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import re
import sys
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np

HERE = Path(__file__).resolve().parent

OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

INDEX_DIR = HERE / "distill_index"
EMB_FILE = INDEX_DIR / "embeddings.npy"
META_FILE = INDEX_DIR / "metadata.jsonl"
EMB_CACHE_FILE = HERE / ".emb_cache_nomic.pkl"

DEFAULT_THRESHOLD = float(os.environ.get("MK_DISTILL_THRESHOLD", "0.70"))
DEFAULT_TOP_K = 3

# ---------------------------------------------------------------------------
# Embedding (with disk cache)
# ---------------------------------------------------------------------------

_emb_cache: dict[str, list[float]] = {}


def _load_cache():
    global _emb_cache
    if _emb_cache is None:
        return
    if not _emb_cache and EMB_CACHE_FILE.exists():
        try:
            with open(EMB_CACHE_FILE, "rb") as f:
                _emb_cache = pickle.load(f)
        except Exception:
            _emb_cache = {}
    elif not _emb_cache:
        _emb_cache = {}


def _save_cache():
    try:
        with open(EMB_CACHE_FILE, "wb") as f:
            pickle.dump(_emb_cache, f)
    except Exception:
        pass


def embed_text(text: str) -> Optional[list[float]]:
    """Embed text via Ollama nomic-embed-text, with disk cache."""
    _load_cache()
    key = hashlib.sha256(text.encode()).hexdigest()
    if key in _emb_cache:
        return _emb_cache[key]
    data = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        emb = json.loads(resp.read())["embedding"]
        _emb_cache[key] = emb
        _save_cache()
        return emb
    except Exception as e:
        print(f"  [distill_router] embed error: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Compound-request guard
# ---------------------------------------------------------------------------

_COMPOUND_MARKERS = re.compile(
    r'\b(?:then|and then|after that)\b|;|->|→',
    re.IGNORECASE,
)


def _is_compound_request(text: str) -> bool:
    """True if the request has multi-step conjunctions."""
    return bool(_COMPOUND_MARKERS.search(text))


# ---------------------------------------------------------------------------
# Parameter extractors
# ---------------------------------------------------------------------------

def _extract_filename(text: str) -> Optional[str]:
    """Extract a filename from natural language."""
    for pattern in [
        r'(?:in|of|from|for)\s+(?:file\s+)?([\'"]?[\w./-]+\.\w+[\'"]?)',
        r'(?:file|called|named)\s+([\'"]?[\w./-]+\.\w+[\'"]?)',
        r'([\'"]?[\w./-]+\.\w+[\'"]?)\s+(?:file|contains|has|does)',
        r'\b([\w./-]+\.\w{1,5})\b',  # bare filename (last resort)
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip('\'"')
    return None


def _extract_filename_and_count(text: str) -> Optional[tuple[str, int]]:
    """Extract (filename, count) for head/tail operations."""
    count = None
    for pat in [r'\b(\d+)\s+lines?\b', r'\bfirst\s+(\d+)\b', r'\blast\s+(\d+)\b']:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            count = int(m.group(1))
            break
    if count is None:
        return None
    fname = _extract_filename(text)
    if fname is None:
        return None
    return (fname, count)


def _extract_filename_and_content(text: str) -> Optional[tuple[str, str]]:
    """Extract (filename, content) for create operations."""
    m = re.search(
        r'(?:with|containing|put)\s+(?:content\s+)?["\']([^"\']+)["\']',
        text, re.IGNORECASE)
    if m:
        content = m.group(1)
        fname = _extract_filename(text)
        if fname:
            return (fname, content)
    m = re.search(
        r'(?:with|containing|put)\s+(.+?)(?:\s+(?:then|and|after)|$)',
        text, re.IGNORECASE)
    if m:
        content = m.group(1).strip().rstrip('.')
        if 0 < len(content) < 200:
            fname = _extract_filename(text)
            if fname:
                return (fname, content)
    return None


def _extract_pattern_and_filename(text: str) -> Optional[tuple[str, str]]:
    """Extract (pattern, filename) for extract/grep operations."""
    m = re.search(
        r'(?:matching|containing|for|grep|search)\s+["\']([^"\']+)["\']',
        text, re.IGNORECASE)
    if m:
        pattern = m.group(1)
        fname = _extract_filename(text)
        if fname:
            return (pattern, fname)
    m = re.search(
        r'(?:matching|containing|for)\s+(\S+?)(?:\s+in\s+|\s+from\s+)',
        text, re.IGNORECASE)
    if m:
        pattern = m.group(1).strip()
        fname = _extract_filename(text)
        if fname:
            return (pattern, fname)
    return None


def _extract_search_text(text: str) -> Optional[str]:
    """Extract search text for find-files operations."""
    m = re.search(
        r'(?:containing|with|having)\s+(?:text\s+)?["\']([^"\']+)["\']',
        text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(
        r'find\s+(?:files?\s+)?(?:containing|with|having)\s+(.+?)(?:\s+in\s+|\s*$)',
        text, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip('.')
    return None


# ---------------------------------------------------------------------------
# Step generators
# ---------------------------------------------------------------------------

def _extract_filename_and_count_last(text: str) -> Optional[tuple[str, int]]:
    """Extract (filename, count) for tail operations — looks for 'last N'."""
    count = None
    for pat in [r'\blast\s+(\d+)\s+lines?', r'\bbottom\s+(\d+)\b', r'\bend\s+(\d+)\b', r'\blast\s+(\d+)\b', r'\b(\d+)\s+lines?']:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            count = int(m.group(1))
            break
    if count is None:
        return None
    fname = _extract_filename(text)
    if fname is None:
        return None
    return (fname, count)

def _extract_transform_case(text: str) -> Optional[tuple[str, str]]:
    """Extract (direction, filename) for case transformation."""
    direction = None
    if re.search(r'\b(upper|uppercase|to upper|capitalize|all caps|all uppercase)\b', text, re.IGNORECASE):
        direction = 'upper'
    elif re.search(r'\b(lower|lowercase|to lower|all lowercase|all lower)\b', text, re.IGNORECASE):
        direction = 'lower'
    if direction is None:
        return None
    fname = _extract_filename(text)
    if fname is None:
        return None
    return (direction, fname)

def _extract_replace_pairs(text: str) -> Optional[tuple[str, str, str]]:
    """Extract (old, new, filename) for replace operations."""
    # Handle quoted pairs with various verbs: replace, swap, substitute, change, overwrite, turn
    m = re.search(
        r'(?:replace|swap|substitute|change|overwrite|turn)\s+["\']([^"\']+)["\']\s+(?:with|by|into|to)\s+["\']([^"\']+)["\']',
        text, re.IGNORECASE)
    if m:
        old, new = m.group(1), m.group(2)
        fname = _extract_filename(text)
        if fname:
            return (old, new, fname)
    # Unquoted variants
    m = re.search(
        r'(?:replace|swap|substitute|change|overwrite|turn)\s+(\S+)\s+(?:with|by|into|to)\s+(\S+?)(?:\s+in\s+|\s*$)',
        text, re.IGNORECASE)
    if m:
        old, new = m.group(1), m.group(2).rstrip('.')
        fname = _extract_filename(text)
        if fname:
            return (old, new, fname)
    # 'find X replace with Y' pattern
    m = re.search(
        r'find\s+["\']([^"\']+)["\']\s+replace\s+with\s+["\']([^"\']+)["\']',
        text, re.IGNORECASE)
    if m:
        old, new = m.group(1), m.group(2)
        fname = _extract_filename(text)
        if fname:
            return (old, new, fname)
    return None

def _gen_count_lines(p):
    return [f'count lines in {p}']

def _gen_count_words(p):
    return [f'count words in {p}']

def _gen_sum_numbers(p):
    return [f'sum numbers in {p}']

def _gen_sort_lines(p):
    return [f'sort lines in {p}']

def _gen_head_lines(p):
    fname, count = p
    return [f'show first {count} lines of {fname}']

def _gen_extract_pattern(p):
    pattern, fname = p
    return [f'extract lines matching "{pattern}" from {fname}']

def _gen_find_content(p):
    return [f'find files containing "{p}"']

def _gen_create_read(p):
    fname, content = p
    return [f'create file {fname} with content "{content}"', f'read file {fname}']

def _gen_append_read(p):
    fname, content = p
    return [f'create file {fname} with content ""', f'append "{content}" to {fname}', f'read file {fname}']


# ---------------------------------------------------------------------------

def _gen_tail_lines(p):
    fname, count = p
    return [f'show last {count} lines of {fname}']

def _gen_reverse_lines(p):
    return [f'reverse lines in {p}']

def _gen_unique_lines(p):
    return [f'unique lines in {p}']

def _gen_transform_case(p):
    direction, fname = p
    if direction == 'upper':
        return [f'uppercase {fname}']
    return [f'lowercase {fname}']

def _gen_replace_text(p):
    old, new, fname = p
    return [f'replace "{old}" with "{new}" in {fname}']

# Template routing table
# ---------------------------------------------------------------------------

TEMPLATE_HANDLERS: dict[str, tuple] = {
    'count-lines':      (_extract_filename,               _gen_count_lines),
    'count-words':      (_extract_filename,               _gen_count_words),
    'sum-numbers':      (_extract_filename,               _gen_sum_numbers),
    'sort-lines':       (_extract_filename,               _gen_sort_lines),
    'head-lines':       (_extract_filename_and_count,     _gen_head_lines),
    'extract-pattern':  (_extract_pattern_and_filename,   _gen_extract_pattern),
    'find-content':     (_extract_search_text,            _gen_find_content),
    'create-read':      (_extract_filename_and_content,   _gen_create_read),
    'append-read':      (_extract_filename_and_content,   _gen_append_read),
    # v3 new templates
    'tail-lines':       (_extract_filename_and_count_last, _gen_tail_lines),
    'reverse-lines':    (_extract_filename,               _gen_reverse_lines),
    'unique-lines':     (_extract_filename,               _gen_unique_lines),
    'transform-case':   (_extract_transform_case,         _gen_transform_case),
    'replace-text':     (_extract_replace_pairs,          _gen_replace_text),
}


# ---------------------------------------------------------------------------
# DistillationRouter
# ---------------------------------------------------------------------------

class DistillationRouter:
    """Fast embedding-based intent router for the planner.

    Sits between deterministic rules and the LLM fallback. Fail-soft:
    returns None on any failure — the planner falls through to LLM.
    """

    def __init__(self, threshold: float = DEFAULT_THRESHOLD, top_k: int = DEFAULT_TOP_K):
        self.threshold = threshold
        self.top_k = top_k
        self._emb_matrix: Optional[np.ndarray] = None
        self._metadata: Optional[list[dict]] = None
        self._loaded = False
        self._load_error: Optional[str] = None

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return self._emb_matrix is not None
        self._loaded = True
        try:
            if not EMB_FILE.exists():
                self._load_error = f"Index not found: {EMB_FILE}"
                return False
            self._emb_matrix = np.load(EMB_FILE)
            self._metadata = []
            with open(META_FILE) as f:
                for line in f:
                    self._metadata.append(json.loads(line))
            return True
        except Exception as e:
            self._load_error = str(e)
            return False

    def _retrieve(self, query: str) -> list[dict]:
        if not self._ensure_loaded():
            return []
        q_emb = embed_text(query)
        if q_emb is None:
            return []
        q_arr = np.array(q_emb, dtype=np.float32)
        q_norm = np.linalg.norm(q_arr)
        if q_norm > 0:
            q_arr = q_arr / q_norm
        sims = self._emb_matrix @ q_arr
        top_indices = np.argsort(sims)[-self.top_k:][::-1]
        results = []
        for idx in top_indices:
            m = self._metadata[idx].copy()
            m["similarity"] = float(sims[idx])
            results.append(m)
        return results

    def route(self, request: str) -> Optional[list[str]]:
        """Try to route a request via embedding retrieval + param extraction.

        Returns NL steps if routing succeeds, or None.
        """
        if _is_compound_request(request):
            return None

        results = self._retrieve(request)
        if not results:
            return None

        top = results[0]
        confidence = top["similarity"]
        if confidence < self.threshold:
            return None

        template = top["template"]
        if template not in TEMPLATE_HANDLERS:
            return None

        extractor, generator = TEMPLATE_HANDLERS[template]
        try:
            params = extractor(request)
            if params is None:
                return None
            steps = generator(params)
            return steps if steps else None
        except Exception:
            return None

    def route_with_meta(self, request: str) -> Optional[dict]:
        """Route and return metadata for debugging/logging."""
        if _is_compound_request(request):
            return {
                "steps": None, "template": None, "confidence": 0.0,
                "routed": False, "reason": "compound request — deferred to LLM",
                "top3": [],
            }

        results = self._retrieve(request)
        if not results:
            return None

        top = results[0]
        confidence = top["similarity"]
        template = top["template"]

        steps = None
        if confidence >= self.threshold and template in TEMPLATE_HANDLERS:
            extractor, generator = TEMPLATE_HANDLERS[template]
            try:
                params = extractor(request)
                if params is not None:
                    steps = generator(params)
            except Exception:
                pass

        return {
            "steps": steps,
            "template": template,
            "confidence": confidence,
            "routed": bool(steps),
            "top3": [
                {"template": r["template"], "similarity": r["similarity"]}
                for r in results[:3]
            ],
        }

    @property
    def available(self) -> bool:
        return self._ensure_loaded()

    @property
    def error(self) -> Optional[str]:
        return self._load_error


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    p = argparse.ArgumentParser(
        description="Distillation router — test embedding-based intent routing")
    p.add_argument("request", help="Natural-language request to route")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    router = DistillationRouter(threshold=args.threshold)
    if not router.available:
        print(f"Router unavailable: {router.error}", file=sys.stderr)
        sys.exit(1)

    result = router.route_with_meta(args.request)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result is None:
            print("No results.")
            return
        print(f"Template:   {result['template']}")
        print(f"Confidence: {result['confidence']:.4f}")
        print(f"Routed:     {result['routed']}")
        for r in result['top3']:
            print(f"  {r['similarity']:.4f}  {r['template']}")
        if result['steps']:
            print(f"\nSteps ({len(result['steps'])}):")
            for i, step in enumerate(result['steps'], 1):
                print(f"  {i}. {step}")
        else:
            print("\n(Not routed — would fall through to LLM)")


if __name__ == "__main__":
    main()

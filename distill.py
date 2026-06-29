#!/usr/bin/env python3
"""Model distillation: compress 12.7K verified triples into an embedding-based
retrieval router.

The thesis: "replace reasoning with lookup/routing." Instead of calling an LLM
to decompose NL into ASG, we embed the NL, find the nearest verified triple,
and reuse its ASG. The embedding index IS the distilled model — no gradient
descent, no fine-tuning, just semantic similarity over verified executions.

Usage:
  python3 distill.py embed     # Build embedding index from triples.jsonl
  python3 distill.py query "count lines in data.txt"   # Test retrieval
  python3 distill.py eval      # Evaluate retrieval accuracy (held-out split)
  python3 distill.py report    # Print stats about the index
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TRIPLES = HERE / "triples.jsonl"
INDEX_DIR = HERE / "distill_index"
EMB_FILE = INDEX_DIR / "embeddings.npy"
META_FILE = INDEX_DIR / "metadata.jsonl"

OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768

MAX_PER_TEMPLATE = 200


def embed_text(text: str) -> list[float] | None:
    """Embed a single text via Ollama's nomic-embed-text model."""
    data = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())["embedding"]
    except Exception as e:
        print(f"  embed error: {e}", file=sys.stderr)
        return None


def load_triples() -> list[dict]:
    """Load all verified triples from triples.jsonl."""
    triples = []
    with open(TRIPLES) as f:
        for line in f:
            t = json.loads(line)
            if t.get("verified"):
                triples.append(t)
    return triples


def stratified_sample(triples: list[dict], max_per: int = MAX_PER_TEMPLATE) -> list[dict]:
    """Stratified sample across templates — ensures balanced coverage."""
    import random

    by_template: dict[str, list[dict]] = defaultdict(list)
    for t in triples:
        tmpl = t.get("params", {}).get("template", "?")
        by_template[tmpl].append(t)

    random.seed(42)
    sampled = []
    for tmpl, items in sorted(by_template.items()):
        n = min(len(items), max_per)
        sampled.extend(random.sample(items, n))
    return sampled


def build_index():
    """Embed a stratified sample of triples and build a numpy similarity index."""
    INDEX_DIR.mkdir(exist_ok=True)

    print("Loading triples...")
    triples = load_triples()
    print(f"  {len(triples)} verified triples loaded")

    print(f"Stratified sampling (max {MAX_PER_TEMPLATE}/template)...")
    sampled = stratified_sample(triples)
    print(f"  {len(sampled)} triples selected for embedding")

    embeddings = []
    metadata = []
    n = len(sampled)
    start = time.time()

    for i, t in enumerate(sampled):
        intent = t["intent"]
        emb = embed_text(intent)
        if emb is None:
            print(f"  [{i+1}/{n}] SKIP (embed failed): {intent[:60]}")
            continue

        embeddings.append(emb)
        meta = {
            "idx": len(embeddings) - 1,
            "id": t.get("id", ""),
            "intent": intent,
            "template": t.get("params", {}).get("template", "?"),
            "node_types": t.get("node_types", []),
            "asg_json": t.get("asg_json", []),
            "expected_output": t.get("expected_output", ""),
        }
        metadata.append(meta)

        if (i + 1) % 50 == 0 or i == n - 1:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            eta = (n - i - 1) / rate if rate > 0 else 0
            print(
                f"  [{i+1}/{n}] {rate:.1f}/s  ETA {eta:.0f}s  "
                f"({metadata[-1]['template']})"
            )

    emb_array = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    emb_normalized = emb_array / norms

    np.save(EMB_FILE, emb_normalized)
    print(f"\nSaved {len(embeddings)} embeddings: {EMB_FILE}")
    print(f"  shape: {emb_normalized.shape}")

    with open(META_FILE, "w") as f:
        for m in metadata:
            f.write(json.dumps(m) + "\n")
    print(f"Saved metadata: {META_FILE}")

    dist = Counter(m["template"] for m in metadata)
    print("\nTemplate distribution in index:")
    for k, v in dist.most_common():
        print(f"  {k}: {v}")

    return emb_normalized, metadata


def load_index() -> tuple[np.ndarray, list[dict]]:
    """Load the embedding index and metadata."""
    if not EMB_FILE.exists():
        raise FileNotFoundError(
            f"Index not found at {EMB_FILE}. Run: python3 distill.py embed"
        )
    emb = np.load(EMB_FILE)
    metadata = []
    with open(META_FILE) as f:
        for line in f:
            metadata.append(json.loads(line))
    return emb, metadata


def retrieve(
    query: str, emb_matrix: np.ndarray, metadata: list[dict], top_k: int = 3
) -> list[dict]:
    """Find the top-k nearest triples by cosine similarity."""
    q_emb = embed_text(query)
    if q_emb is None:
        return []

    q_arr = np.array(q_emb, dtype=np.float32)
    q_norm = np.linalg.norm(q_arr)
    if q_norm > 0:
        q_arr = q_arr / q_norm

    sims = emb_matrix @ q_arr
    top_indices = np.argsort(sims)[-top_k:][::-1]

    results = []
    for idx in top_indices:
        m = metadata[idx].copy()
        m["similarity"] = float(sims[idx])
        results.append(m)
    return results


def do_query(query: str):
    """Test retrieval for a single query."""
    emb, meta = load_index()
    results = retrieve(query, emb, meta, top_k=3)

    print(f"\nQuery: {query!r}")
    print(f"{'Score':>8}  {'Template':<25} {'Intent':<60}")
    print("-" * 95)
    for r in results:
        print(
            f"{r['similarity']:8.4f}  {r['template']:<25} "
            f"{r['intent'][:60]:<60}"
        )

    if results:
        print(f"\nTop-1 ASG nodes: {results[0]['node_types']}")
        print(f"Top-1 expected output: {results[0].get('expected_output', '?')}")


def do_eval():
    """Evaluate retrieval accuracy on held-out triples."""
    import random

    print("Loading index...")
    emb, meta = load_index()
    print(f"  {len(meta)} triples in index")

    print("Loading full corpus for held-out evaluation...")
    triples = load_triples()

    indexed_intents = set(m["intent"] for m in meta)
    held_out = [t for t in triples if t["intent"] not in indexed_intents]
    random.seed(123)
    eval_sample = random.sample(held_out, min(300, len(held_out)))
    print(f"  {len(eval_sample)} held-out triples for evaluation")

    correct_template = 0
    correct_nodes = 0
    top1_templates = []
    sims = []

    for i, t in enumerate(eval_sample):
        results = retrieve(t["intent"], emb, meta, top_k=1)
        if not results:
            continue

        top = results[0]
        true_template = t.get("params", {}).get("template", "?")
        pred_template = top["template"]

        sims.append(top["similarity"])
        top1_templates.append(pred_template)

        if pred_template == true_template:
            correct_template += 1
        if tuple(sorted(top["node_types"])) == tuple(sorted(t.get("node_types", []))):
            correct_nodes += 1

        if (i + 1) % 50 == 0:
            print(
                f"  [{i+1}/{len(eval_sample)}] "
                f"template_acc={correct_template/(i+1):.1%}  "
                f"node_acc={correct_nodes/(i+1):.1%}"
            )

    n = len(eval_sample)
    print(f"\n{'='*60}")
    print(f"RETRIEVAL EVALUATION RESULTS ({n} held-out triples)")
    print(f"{'='*60}")
    print(f"Template accuracy (top-1): {correct_template}/{n} = {correct_template/n:.1%}")
    print(f"Node-type accuracy (top-1): {correct_nodes}/{n} = {correct_nodes/n:.1%}")
    print(f"Mean similarity score: {np.mean(sims):.4f}")
    print(f"Median similarity: {np.median(sims):.4f}")
    print(f"Min/Max similarity: {np.min(sims):.4f} / {np.max(sims):.4f}")

    by_tmpl = defaultdict(lambda: {"correct": 0, "total": 0})
    for t, pred in zip(eval_sample, top1_templates):
        true_t = t.get("params", {}).get("template", "?")
        by_tmpl[true_t]["total"] += 1
        if pred == true_t:
            by_tmpl[true_t]["correct"] += 1

    print(f"\nPer-template accuracy:")
    print(f"  {'Template':<25} {'Acc':>6} {'Count':>6}")
    for tmpl in sorted(by_tmpl):
        s = by_tmpl[tmpl]
        acc = s["correct"] / s["total"] if s["total"] > 0 else 0
        print(f"  {tmpl:<25} {acc:>5.1%} {s['total']:>6}")

    return correct_template / n


def do_report():
    """Print stats about the distillation index."""
    emb, meta = load_index()

    print(f"\n{'='*60}")
    print(f"DISTILLATION INDEX REPORT")
    print(f"{'='*60}")
    print(f"Embeddings: {emb.shape}")
    print(f"Embedding dim: {emb.shape[1]}")
    print(f"Model: {EMBED_MODEL}")

    templates = Counter(m["template"] for m in meta)
    print(f"\nTemplates covered: {len(templates)}")
    for k, v in templates.most_common():
        print(f"  {k}: {v}")

    node_types = Counter()
    for m in meta:
        for nt in m["node_types"]:
            node_types[nt] += 1
    print(f"\nNode types in index: {len(node_types)}")
    for k, v in node_types.most_common():
        print(f"  {k}: {v}")

    print(f"\nComputing intra/inter-template similarity...")
    by_tmpl: dict[str, list[int]] = defaultdict(list)
    for i, m in enumerate(meta):
        by_tmpl[m["template"]].append(i)

    intra_sims = []
    inter_sims = []
    n_samples = min(500, len(meta))

    for _ in range(n_samples):
        i, j = np.random.randint(0, len(meta), 2)
        if i == j:
            continue
        sim = float(emb[i] @ emb[j])
        if meta[i]["template"] == meta[j]["template"]:
            intra_sims.append(sim)
        else:
            inter_sims.append(sim)

    if intra_sims and inter_sims:
        print(f"  Intra-template (same pattern):  mean={np.mean(intra_sims):.4f}")
        print(f"  Inter-template (diff pattern):  mean={np.mean(inter_sims):.4f}")
        print(f"  Separation: {np.mean(intra_sims) - np.mean(inter_sims):.4f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "embed":
        build_index()
    elif cmd == "query":
        if len(sys.argv) < 3:
            print("Usage: python3 distill.py query 'some NL text'")
            sys.exit(1)
        do_query(sys.argv[2])
    elif cmd == "eval":
        do_eval()
    elif cmd == "report":
        do_report()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)

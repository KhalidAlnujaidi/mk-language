# Agentic Workflow Features

This document catalogs the agentic workflow features extracted from the `cheatcodes/` directory, referencing the fruitful repositories and folders that contain these patterns. It serves as a resource for adopting, depending on, or vendoring established agentic patterns into the main project.

## 1. Evaluation & Quality Assurance (`deepeval/`)

The `deepeval` framework provides a mature spine for evaluating LLM behaviors, extending beyond simple boolean assertions.

| Feature | Description | Value |
|---------|-------------|-------|
| **Scored Metrics** | Graduated scoring (0-1) with thresholds and reasoning, replacing binary pass/fail checks to detect partial regressions. | ⭐ High |
| **Cost & Token Accounting** | Tallies LLM spend and token counts on every eval as a first-class metric, gating local/frontier budget enforcement. | ⭐ Critical |
| **G-Eval (LLM-as-judge)** | Auto-expands plain-English criteria into Chain-of-Thought evaluation steps to score subjective outputs (e.g. "Did the agent groom sensibly?"). | ⭐ High |
| **Decision-Graph (DAG) Verdicts** | Turns fuzzy judgments into reproducible, inspectable decision trees (deep acyclic graphs) for reproducible guard flows. | ⭐ High |
| **Agent-Specific Metrics** | Measures tool correctness, task completion, and plan adherence without needing an LLM (deterministic set/order scoring). | ⭐ High |
| **PII-Leakage Metric** | Regression-tests the redactor to ensure secrets don't leak back out in responses. | ⭐ Medium |
| **Task Synthesizer** | Mutates existing contexts to auto-generate adversarial fuzzing tasks for the guard/redactor. | ⭐ Medium |
| **Adversarial Red-Teaming** | Automated prompt injection and obfuscated command tests targeting the security boundaries. | ⭐ High |
| **Trace `@observe`** | Auto-instruments handlers with span-based observability to log the request→route→guard→dispatch flow. | ⭐ Medium |

## 2. Core Agentic Control Loop & Capabilities

Features related to the central Perception-Cognition-Action loop, mined from `CodeWhale`, `AgentFarm`, `ECC/skills`, and others.

| Feature | Source Repository | Description | Value |
|---------|-------------------|-------------|-------|
| **Agent Loop Structure** | `AgentFarm`, Skills | Implements Observation → Perception → Cognition → Action cycle. Stops on no-tool-call or max-turns (fail-CLOSED). | ⭐ Critical |
| **Arity-Aware Command Safety** | `CodeWhale` | Classifies terminal commands by positional tokens (e.g. `git status` vs `git push`) to block catastrophic actions (e.g. `rm -rf`) regardless of path jails. | ⭐ Critical |
| **Layered Permission Rulesets** | `CodeWhale` | Tri-layer (Builtin < Agent < User) permission hierarchy mapping actions to ALLOW, ASK, or DENY with fail-closed precedence. | ⭐ High |
| **Per-Run Token Budgets** | `CodeWhale` | Enforces a hard budget (limit) per run with a fail-soft early exit once exhausted, avoiding runaway API spend. | ⭐ Critical |
| **Job-Retry with Backoff** | `CodeWhale` | Exponential backoff for transient errors (e.g., 5xx, 429) to keep the agent on the preferred LLM tier during blips. | ⭐ High |
| **Live Status-Line Chips** | `CodeWhale` | Fast-path UI rendering for declarative status chips (model, cost, tokens, context %), giving honest, real-time observability. | ⭐ High |
| **Claude Code Skill Corpus** | `ECC/skills` | A massive library of 270+ invokable capabilities, ready for dynamic agent tool-use ingestion. | ⭐ High |

## 3. Execution Pipeline & Tools

Stages in the grooming and execution pipelines, extracted from targeted utilities.

| Feature | Source Repository | Description | Value |
|---------|-------------------|-------------|-------|
| **Deterministic Deslop** | `stop-slop` | Pure, model-free detector mapping LLM conversational "filler/slop" phrases, gating output quality without rewriting. | ⭐ Medium |
| **Rate-Limit Ledger** | `freellmapi` | Sliding RPM/TPM ledger allowing proactive tracking of limits to avoid round trips for `429 Retry-After`. | ⭐ High |
| **Backend Reachability Doctor**| `Agent-Reach` | Per-channel probe/health checks to gracefully fail-soft and route around temporarily offline backend tiers. | ⭐ Medium |
| **Document Ingestion** | `markitdown` | Converts arbitrary files (PDF, DOCX, XLSX) to markdown context to feed the Perception stage. | ⭐ Medium |
| **Session Checkpointing** | `orca`, `herdr` | Suspends thread state to disk allowing undo, replay, and resumed sessions. *(Tier-3)* | ⭐ Medium |
| **MinHash Similarity** | `codebase-memory-mcp` | Deduplicates tasks and context using Locality Sensitive Hashing (LSH) for efficiency. *(Tier-3)* | ⭐ Low |

---

> **Note**: This summary is derived from `/Volumes/Home/kinox/cheatcodes/cheats.md`. The design philosophy relies heavily on borrowing *patterns and ground-truths* deterministically, avoiding redundant logic, and maintaining a fail-closed, cost-aware agent kernel.

# Council corpus — index

Faithful re-tagging of `dump.log` → `council_corpus.jsonl`.
Every prompt, raw reply, ballot, build-eval and error, tagged and queryable.

- **records:** 4181
- **total text:** 25,803,522 chars (~6,450,880 tokens)
- **rounds covered:** 0–220 (221 rounds)

## by kind
- `PROMPT` — 1485
- `RAW REPLY` — 1437
- `BUILD eval` — 833
- `ERROR` — 290
- `TALLY` — 68
- `BUILD ADOPT` — 56
- `RUN START` — 8
- `SIGNAL 15` — 2
- `GOAL SWITCH` — 1
- `LAYER COMPLETE` — 1

## by model (calls logged)
- `deepseek-r1:8b` — 893
- `qwen3:8b` — 749
- `gemma4:latest` — 744
- `llama3:latest` — 742
- `mistral:7b` — 734
- `model-x` — 156
- `qwen/qwen-2.5-72b-instruct` — 7
- `anthropic/claude-sonnet-4` — 5
- `openai/gpt-4o` — 5
- `deepseek/deepseek-r1` — 5
- `mistralai/mistral-large` — 5

## by tag (phase of deliberation)
- `interp` — 1763
- `propose` — 716
- `vote:refine:builtins` — 205
- `vote:refine:example-data` — 81
- `vote:refine:design-goals` — 81
- `vote:refine:semantics` — 73
- `vote:refine:meta-axiom` — 54
- `vote:refine:paradigm-and-types` — 32
- `vote:refine:example-showcase` — 24
- `vote:refine:lexical-grammar` — 20
- `vote:paradigm-and-types` — 17
- `vote:refine:example-factorial` — 14
- `interp-vote` — 12
- `vote:meta-axiom` — 10
- `vote:design-goals` — 10
- `vote:notation` — 10
- `vote:lexical-grammar` — 10
- `vote:core-grammar` — 10
- `vote:semantics` — 10
- `vote:builtins` — 10
- `vote:example-factorial` — 10
- `vote:example-data` — 10
- `vote:example-showcase` — 10
- `vote:refine:notation` — 10

## query examples
```bash
# every interpreter proposal from the cloud council, round 220:
jq 'select(.kind=="RAW REPLY" and .round=="220" and (.model|test("/")))' \
   corpus/council_corpus.jsonl
# every blind ballot:
jq 'select(.tag|test("vote"))' corpus/council_corpus.jsonl
```

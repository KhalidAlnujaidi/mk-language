# Council build log — anonymized progress reference

The council's shared institutional memory. It records, ANONYMOUSLY (no model identities),
every capability milestone reached and every plateau — so progress is never lost. This
file is fed back into every build prompt: the council builds on what it has proven, and
when it plateaus it restarts from the agreed foundation toward the goal it already showed
was reachable. Identities live only in dump.log (our private audit), never here.

- Round 78: reached **1/11**. Newly working: list-dir.
- Round 85: PLATEAU at 1/11 after 6 rounds with no gain. Agreed foundation passes: ['list-dir']. Fresh-start goal: `create-and-read`.
- Round 89: reached **8/11**. Newly working: copy, create-and-read, decision, safety-confirm-irreversible, safety-refuse-irreversible, search-content, sequence.
- Round 96: PLATEAU at 8/11 after 6 rounds with no gain. Agreed foundation passes: ['create-and-read', 'list-dir', 'copy', 'search-content', 'sequence', 'decision', 'safety-refuse-irreversible', 'safety-confirm-irreversible']. Fresh-start goal: `append`.
- Round 101: reached **10/11**. Newly working: append, count-lines.
- Round 108: PLATEAU at 10/11 after 6 rounds with no gain. Agreed foundation passes: ['create-and-read', 'list-dir', 'append', 'count-lines', 'copy', 'search-content', 'sequence', 'decision', 'safety-refuse-irreversible', 'safety-confirm-irreversible']. Fresh-start goal: `mkdir-move`.
- Round 115–213: PLATEAU at 10/11 (repeated). Agreed foundation passes: same 10. Fresh-start goal: `mkdir-move`.
- Round 220: reached **11/11**. Newly working: mkdir-move.
- Round 220: **COMPLETE — 11/11.** The council built a working NL→OS layer.

## Post-council engineering (outside the council loop)

- v03 ASG layer: 30 node types, 4 backends (direct/shell/python/sql), 89 rungs.
- Planner/composer: 93 rules (42 compound + 16 iteration + 11 iteration+pipeline + 5 vars + 19 pipeline/conjunction).
- Iteration+pipeline composition with pre-step initialization (e.g., "for each *.txt, count lines and append to summary" → writes summary file, then iterates).
- Cross-backend equivalence: 74 rungs proving same NL → same output across all 4 backends.
- Model distillation (Experiment 3): 2,527-vector embedding index, 79.7% top-1, 86% top-3, 40,000× faster than LLM.
- Governed self-enhancement (Experiment 4): design complete, 33-test safety suite green.
- Fixed: iteration+pipeline planner bug (KeyError on template variables in _safe_format).
- Total: **493 test rungs** across 11 suites, ALL GREEN.

#!/bin/bash
cd "$(dirname "$0")"
echo "Starting triple generation at $(date)" > gen_progress.log
python3 generate_triples.py --out triples_v3.jsonl 2>> gen_progress.log
echo "Exit code: $?" >> gen_progress.log
echo "Finished at $(date)" >> gen_progress.log
wc -l triples_v3.jsonl >> gen_progress.log

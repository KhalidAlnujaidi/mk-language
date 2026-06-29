#!/bin/bash
cd "$(dirname "$0")"
rm -f triples_v3.jsonl
python3 generate_triples.py --out triples_v3.jsonl > gen_v3.log 2>&1
echo "DONE exit=$?" >> gen_v3.log

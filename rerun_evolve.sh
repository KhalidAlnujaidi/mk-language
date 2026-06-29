#!/bin/bash
cd "$(dirname "$0")"
python evolve.py revert-all 2>/dev/null
echo "" > dump.log
EVOLVE_MAX_CYCLES=50 EVOLVE_PATIENCE=10 python evolve.py run
echo "---"
grep -c "Auto-injected" planner.py
python evolve.py eval

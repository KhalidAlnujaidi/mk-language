#!/bin/bash
# Experiment 4: Governed Self-Enhancement Loop
# Runs the full evolution loop and captures output

cd "$(dirname "$0")"

echo "============================================"
echo "MK Experiment 4 — Governed Self-Enhancement"
echo "Started: $(date)"
echo "============================================"

# Clean slate
python evolve.py revert-all 2>/dev/null || true

# Run the evolution loop with generous limits
EVOLVE_MAX_CYCLES=50 EVOLVE_PATIENCE=10 python evolve.py run 2>&1

echo ""
echo "============================================"
echo "Post-experiment eval:"
echo "============================================"
python evolve.py eval 2>&1

echo ""
echo "============================================"
echo "Injected rules:"
echo "============================================"
python evolve.py status 2>&1

echo ""
echo "============================================"
echo "Test suite verification:"
echo "============================================"
python _verify_all.py 2>&1 | tail -2
python test_planner.py 2>&1 | tail -2
python test_v03.py 2>&1 | tail -2
python test_evolve.py 2>&1 | tail -2

echo ""
echo "Finished: $(date)"
echo "============================================"

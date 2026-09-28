#!/bin/bash
# CI entry point: the selftest is the regression suite.
set -e
cd "$(dirname "$0")"
python3 gate1_pregate.py --selftest
echo "Gate 1 regression suite: PASS"

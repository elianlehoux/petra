#!/usr/bin/env bash
set -e

echo "=== Running Compiled AI Router Automated Test Suite ==="

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_DIR="${PROJECT_ROOT}/python"
DEPS_DIR="${PROJECT_ROOT}/vendor_deps"

export PYTHONPATH="${DEPS_DIR}:${PYTHON_DIR}:${PYTHONPATH}"

echo ""
echo "Running pytest unit & integration tests..."
python3 -m pytest "${PYTHON_DIR}/tests" -v --tb=short

echo ""
echo "Running CLI benchmark demo..."
python3 -m compiled_ai_router.cli benchmark --iterations 20

echo ""
echo "--------------------------------------------------------"
echo "✅ All Compiled AI Router E2E verification checks passed!"
echo "--------------------------------------------------------"
exit 0

#!/usr/bin/env bash
# Corre el benchmark REAL de la CLI (no números hardcodeados).
# Nota: en modo `demo` la latencia de "passthrough" todavía está simulada;
# los números honestos de costo/latencia llegan con la Fase 1 del ROADMAP.
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${PROJECT_ROOT}/vendor_deps:${PROJECT_ROOT}/python:${PYTHONPATH}"

ITERATIONS="${1:-100}"

echo "Running real benchmark (${ITERATIONS} iterations)..."
python3 -m compiled_ai_router.cli benchmark --iterations "${ITERATIONS}"

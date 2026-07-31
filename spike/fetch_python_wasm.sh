#!/usr/bin/env bash
# Fetch a CPython-3.12 WASI build (python.wasm, ~25 MB) from VMware Wasm Labs.
# The binary is intentionally NOT committed (too large for git).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)/wasm"
mkdir -p "$DIR"
URL="https://github.com/vmware-labs/webassembly-language-runtimes/releases/download/python%2F3.12.0%2B20231211-040d5a6/python-3.12.0.wasm"
echo "Downloading python.wasm -> $DIR/python.wasm"
curl -sSL -o "$DIR/python.wasm" "$URL"
file "$DIR/python.wasm"
echo "Done. Now: spike/venv/bin/python spike/bench.py"

"""SPIKE prototype: WasmExecutor -- drop-in shape for LocalExecutor.

Runs an artifact *as Python source* inside a sandboxed CPython-on-WASI module
(python.wasm), passing input via stdin and reading output from stdout, with
fuel-based CPU limiting and zero host filesystem/network access by default.

Interface parity with LocalExecutor:
    execute_artifact(script_path: str, input_data: str) -> (Optional[str], float)

NOTE: This is a feasibility prototype, not production code. See
docs/wasm-sandbox-spike.md for measured latency and the honest verdict
(naive CPython-in-WASM boot is ~2x slower than subprocess; needs Wizer
pre-initialization to win, OR compile artifacts directly to WASM).

Requires: pip install wasmtime ; a python.wasm at wasm/python.wasm
(see spike/fetch_python_wasm.sh).
"""
import os
import time
import tempfile
from typing import Optional, Tuple

from wasmtime import Engine, Config, Module, Store, Linker, WasiConfig

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_WASM = os.path.join(_HERE, "wasm", "python.wasm")
_FUEL = 5_000_000_000  # CPU budget; tune per artifact capability contract.


class WasmExecutor:
    def __init__(self, python_wasm: str = _DEFAULT_WASM):
        # Compile ONCE at construction (or load a cached .cwasm via
        # Module.deserialize_file for ~5ms instead of ~800ms).
        cfg = Config()
        cfg.consume_fuel = True  # required for store.set_fuel() CPU limiting
        self._engine = Engine(cfg)
        self._module = Module.from_file(self._engine, python_wasm)
        self._linker = Linker(self._engine)
        self._linker.define_wasi()

    def execute_artifact(self, script_path: str, input_data: str) -> Tuple[Optional[str], float]:
        script_dir = os.path.dirname(os.path.abspath(script_path))
        script_name = os.path.basename(script_path)
        start = time.perf_counter()
        try:
            with tempfile.NamedTemporaryFile(delete=False) as inf, \
                 tempfile.NamedTemporaryFile(delete=False) as outf:
                inf.write(input_data.encode())
                in_path, out_path = inf.name, outf.name

            store = Store(self._engine)
            store.set_fuel(_FUEL)  # deterministic CPU cap (kills infinite loops)

            wasi = WasiConfig()
            wasi.argv = ["python", "/" + script_name]
            # Grant read-only-ish access to ONLY the artifact dir; nothing else.
            wasi.preopen_dir(script_dir, "/")
            wasi.stdin_file = in_path
            wasi.stdout_file = out_path
            wasi.inherit_stderr()
            store.set_wasi(wasi)

            instance = self._linker.instantiate(store, self._module)
            instance.exports(store)["_start"](store)

            duration_ms = (time.perf_counter() - start) * 1000
            with open(out_path) as fh:
                output = fh.read().strip()
            os.unlink(in_path)
            os.unlink(out_path)
            return output, duration_ms
        except Exception as e:  # Trap on fuel exhaustion, WASI error, etc.
            duration_ms = (time.perf_counter() - start) * 1000
            return None, duration_ms


if __name__ == "__main__":
    ex = WasmExecutor()
    demo = os.path.join(_HERE, "..", "python", "compiled_ai_router",
                        "demo_artifacts", "csv_to_json.py")
    out, ms = ex.execute_artifact(os.path.abspath(demo),
                                  '{"csv_data": "a,b\\n1,2\\n3,4"}')
    print(f"out={out!r}  {ms:.1f} ms")

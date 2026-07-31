"""SPIKE benchmark: subprocess python3 vs wasmtime WASM execution.

Measures per-execution latency for:
  1. Baseline: subprocess.run(["python3", script]) -- current LocalExecutor.
  2. wasmtime: instantiate + call a pure-compute WASM module (no WASI, no I/O).
  3. wasmtime + WASI: run a WASM module that reads stdin and writes stdout
     (the realistic artifact I/O contract), using temp files for stdin/stdout.
  4. (optional) python.wasm: full CPython compiled to WASI, if the binary is present.

Run: spike/venv/bin/python spike/bench.py
"""
import os
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
N = 50
INPUT_JSON = '{"csv_data": "a,b\\n1,2\\n3,4"}'


def stats(samples):
    samples = sorted(samples)
    return {
        "n": len(samples),
        "mean_ms": round(statistics.mean(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples[int(len(samples) * 0.95) - 1], 3),
        "min_ms": round(min(samples), 3),
        "max_ms": round(max(samples), 3),
    }


# --- 1. Baseline: subprocess python3 -------------------------------------
def bench_subprocess():
    script = os.path.join(
        HERE, "..", "python", "compiled_ai_router", "demo_artifacts", "csv_to_json.py"
    )
    script = os.path.abspath(script)
    # warmup
    subprocess.run(["python3", script], input=INPUT_JSON, text=True, capture_output=True)
    samples = []
    for _ in range(N):
        t = time.perf_counter()
        proc = subprocess.run(
            ["python3", script], input=INPUT_JSON, text=True, capture_output=True
        )
        samples.append((time.perf_counter() - t) * 1000)
    return stats(samples), proc.stdout.strip()


# --- 2. wasmtime pure compute (WAT) --------------------------------------
COMPUTE_WAT = r"""
(module
  (func (export "add") (param i32 i32) (result i32)
    local.get 0
    local.get 1
    i32.add))
"""


def bench_wasmtime_compute():
    from wasmtime import Engine, Store, Module, Instance

    engine = Engine()
    # Compile once (this is what artifact caching would amortize).
    t = time.perf_counter()
    module = Module(engine, COMPUTE_WAT)
    compile_ms = (time.perf_counter() - t) * 1000

    # Per-execution: new Store + Instance + call (fresh isolation each run).
    samples = []
    out = None
    for _ in range(N):
        t = time.perf_counter()
        store = Store(engine)
        instance = Instance(store, module, [])
        add = instance.exports(store)["add"]
        out = add(store, 40, 2)
        samples.append((time.perf_counter() - t) * 1000)
    return stats(samples), compile_ms, out


# --- 3. wasmtime + WASI stdin/stdout -------------------------------------
# WASI module compiled from a tiny Rust/C would be ideal, but to stay
# dependency-free we use a WAT module that calls fd_read/fd_write via WASI
# preview1. Writing that by hand is verbose; instead we test the WASI
# *plumbing overhead* by running a WASI command module that just exits,
# plus stdin/stdout wiring through temp files, to measure the host cost.
ECHO_WAT = r"""
(module
  (import "wasi_snapshot_preview1" "fd_write"
    (func $fd_write (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_read"
    (func $fd_read (param i32 i32 i32 i32) (result i32)))
  (memory (export "memory") 1)
  (func (export "_start")
    ;; iovec at addr 0: {buf=16, len=64}
    (i32.store (i32.const 0) (i32.const 16))
    (i32.store (i32.const 4) (i32.const 64))
    ;; read up to 64 bytes from stdin(fd 0) into buf@16, nread at 8
    (drop (call $fd_read (i32.const 0) (i32.const 0) (i32.const 1) (i32.const 8)))
    ;; iovec for write: {buf=16, len=nread}
    (i32.store (i32.const 0) (i32.const 16))
    (i32.store (i32.const 4) (i32.load (i32.const 8)))
    ;; write to stdout(fd 1)
    (drop (call $fd_write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 12)))))
"""


def bench_wasmtime_wasi_echo():
    from wasmtime import Engine, Store, Module, Instance, Linker, WasiConfig

    engine = Engine()
    module = Module(engine, ECHO_WAT)
    linker = Linker(engine)
    linker.define_wasi()

    samples = []
    last_out = None
    for _ in range(N):
        in_f = tempfile.NamedTemporaryFile(delete=False)
        out_f = tempfile.NamedTemporaryFile(delete=False)
        in_f.write(INPUT_JSON.encode())
        in_f.close()
        out_f.close()
        t = time.perf_counter()
        store = Store(engine)
        wasi = WasiConfig()
        wasi.stdin_file = in_f.name
        wasi.stdout_file = out_f.name
        wasi.inherit_stderr()
        store.set_wasi(wasi)
        instance = linker.instantiate(store, module)
        start = instance.exports(store)["_start"]
        start(store)
        samples.append((time.perf_counter() - t) * 1000)
        with open(out_f.name, "rb") as fh:
            last_out = fh.read().decode(errors="replace")
        os.unlink(in_f.name)
        os.unlink(out_f.name)
    return stats(samples), last_out


# --- 4. python.wasm (full CPython to WASI), if available -----------------
def bench_python_wasm():
    py_wasm = os.path.join(HERE, "wasm", "python.wasm")
    if not os.path.exists(py_wasm):
        return None, "python.wasm not present (download step skipped/failed)"
    from wasmtime import Engine, Store, Module, Linker, WasiConfig

    engine = Engine()
    t = time.perf_counter()
    module = Module.from_file(engine, py_wasm)
    compile_ms = (time.perf_counter() - t) * 1000
    linker = Linker(engine)
    linker.define_wasi()

    script = os.path.join(HERE, "wasm", "hello.py")
    with open(script, "w") as fh:
        fh.write("import sys,json\n"
                 "d=json.loads(sys.stdin.read())\n"
                 "print(json.dumps({'rows': d['csv_data'].count(chr(10))}))\n")

    samples = []
    last_out = None
    for _ in range(min(N, 20)):  # python.wasm is heavy; fewer iters
        in_f = tempfile.NamedTemporaryFile(delete=False)
        out_f = tempfile.NamedTemporaryFile(delete=False)
        in_f.write(INPUT_JSON.encode()); in_f.close(); out_f.close()
        t = time.perf_counter()
        store = Store(engine)
        wasi = WasiConfig()
        wasi.argv = ["python", "/hello.py"]
        wasi.preopen_dir(os.path.join(HERE, "wasm"), "/")
        wasi.stdin_file = in_f.name
        wasi.stdout_file = out_f.name
        wasi.inherit_stderr()
        store.set_wasi(wasi)
        instance = linker.instantiate(store, module)
        try:
            instance.exports(store)["_start"](store)
        except Exception as e:
            last_out = f"exec error: {e}"
        samples.append((time.perf_counter() - t) * 1000)
        with open(out_f.name, "rb") as fh:
            last_out = fh.read().decode(errors="replace") or last_out
        os.unlink(in_f.name); os.unlink(out_f.name)
    return (stats(samples), compile_ms), last_out


if __name__ == "__main__":
    print(f"N={N} iterations, input={INPUT_JSON!r}\n")

    s1, out1 = bench_subprocess()
    print("1) subprocess python3   :", s1)
    print("   output:", out1)

    s2, comp2, out2 = bench_wasmtime_compute()
    print("\n2) wasmtime pure compute:", s2)
    print(f"   module compile once: {comp2:.3f} ms ; add(40,2)={out2}")

    try:
        s3, out3 = bench_wasmtime_wasi_echo()
        print("\n3) wasmtime + WASI echo :", s3)
        print("   echoed output:", repr(out3))
    except Exception as e:
        print("\n3) wasmtime + WASI echo : FAILED ->", repr(e))

    res4, out4 = bench_python_wasm()
    if res4 is None:
        print("\n4) python.wasm (CPython):", out4)
    else:
        s4, comp4 = res4
        print("\n4) python.wasm (CPython):", s4)
        print(f"   module compile once: {comp4:.3f} ms")
        print("   output:", repr(out4))

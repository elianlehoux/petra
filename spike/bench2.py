"""SPIKE part 2: attribute the python.wasm cost and test AOT precompile."""
import os, time, tempfile, statistics
from wasmtime import Engine, Store, Module, Linker, WasiConfig, Config

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "wasm", "python.wasm")
CWASM = os.path.join(HERE, "wasm", "python.cwasm")
INPUT = b'{"csv_data": "a,b\\n1,2\\n3,4"}'


def st(s):
    s = sorted(s)
    return {"mean_ms": round(statistics.mean(s), 2), "median_ms": round(statistics.median(s), 2),
            "p95_ms": round(s[int(len(s)*0.95)-1], 2), "min_ms": round(min(s), 2)}


# AOT: precompile module to native code, serialize, measure deserialize load.
cfg = Config()
engine = Engine(cfg)
t = time.perf_counter()
mod = Module.from_file(engine, PY)
print(f"cold compile python.wasm : {(time.perf_counter()-t)*1000:.1f} ms")
t = time.perf_counter()
serialized = mod.serialize()
open(CWASM, "wb").write(serialized)
print(f"serialize (.cwasm write) : {(time.perf_counter()-t)*1000:.1f} ms ; size={len(serialized)//1024} KB")

# Fresh engine: load precompiled (this is what a warm server does at startup).
engine2 = Engine(Config())
t = time.perf_counter()
mod2 = Module.deserialize_file(engine2, CWASM)
print(f"deserialize .cwasm (AOT) : {(time.perf_counter()-t)*1000:.1f} ms   <- one-time at server boot")

linker = Linker(engine2)
linker.define_wasi()

# (a) instantiate ONLY (no _start) -> pure instance creation cost
inst_only = []
for _ in range(20):
    t = time.perf_counter()
    store = Store(engine2)
    w = WasiConfig(); w.inherit_stderr()
    store.set_wasi(w)
    linker.instantiate(store, mod2)
    inst_only.append((time.perf_counter()-t)*1000)
print(f"\ninstantiate only (no run): {st(inst_only)}   <- fresh isolated instance")

# (b) full run: instantiate + _start (boots CPython + runs script)
script = os.path.join(HERE, "wasm", "hello.py")
open(script, "w").write(
    "import sys,json\nd=json.loads(sys.stdin.read())\nprint(json.dumps({'rows': d['csv_data'].count(chr(10))}))\n")
full = []
out = None
for _ in range(20):
    inf = tempfile.NamedTemporaryFile(delete=False); outf = tempfile.NamedTemporaryFile(delete=False)
    inf.write(INPUT); inf.close(); outf.close()
    t = time.perf_counter()
    store = Store(engine2)
    w = WasiConfig(); w.argv = ["python", "/hello.py"]; w.preopen_dir(os.path.join(HERE, "wasm"), "/")
    w.stdin_file = inf.name; w.stdout_file = outf.name; w.inherit_stderr()
    store.set_wasi(w)
    inst = linker.instantiate(store, mod2)
    inst.exports(store)["_start"](store)
    full.append((time.perf_counter()-t)*1000)
    out = open(outf.name).read(); os.unlink(inf.name); os.unlink(outf.name)
print(f"full run (boot+script)   : {st(full)}   out={out!r}")
print("\n=> CPython interpreter boot inside WASM is the dominant per-exec cost.")

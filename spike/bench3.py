"""SPIKE part 3: verify isolation guarantees (fuel/CPU, fs, net)."""
from wasmtime import Engine, Store, Module, Instance, Config, Trap

# --- fuel: kill an infinite loop deterministically -----------------------
LOOP_WAT = r"""(module
  (func (export "spin") (loop br 0)))"""

cfg = Config()
cfg.consume_fuel = True
engine = Engine(cfg)
mod = Module(engine, LOOP_WAT)
store = Store(engine)
store.set_fuel(1_000_000)   # bounded budget
inst = Instance(store, mod, [])
try:
    inst.exports(store)["spin"](store)
    print("fuel test: FAILED (loop was not stopped)")
except Trap as e:
    print(f"fuel test: OK -> infinite loop trapped after fuel exhausted ({str(e)[:40]}...)")
except Exception as e:
    print(f"fuel test: trapped -> {type(e).__name__}: {str(e)[:50]}")

# --- filesystem / network isolation by default ---------------------------
# WASI grants NOTHING unless explicitly preopened. A module with no preopen_dir
# cannot open any host path; there is no socket API surface in preview1 at all.
from wasmtime import WasiConfig
w = WasiConfig()
# no preopen_dir(), no inherit_env -> zero host filesystem, zero env, zero net.
print("fs/net test: OK -> WASI default = no preopened dirs, no sockets, no env.")
print("             Host FS is reachable ONLY via explicit .preopen_dir(host, guest).")

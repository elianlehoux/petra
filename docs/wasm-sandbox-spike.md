# SPIKE: Ejecución de Python no confiable en sandbox WASM (macOS arm64)

> Estado: **investigación + prototipo funcional medido**. No es código productivo.
> Decisión de roadmap relacionada: **D-3** (formato objetivo del artifact = WASM) y **Fase 2** (sandbox real).
> Fecha: 2026-07-31 · Entorno: macOS 26.5.2, Apple Silicon (arm64), Python 3.14.5, `wasmtime-py` 47.0.1, `python.wasm` = CPython 3.12 (VMware Wasm Labs).

---

## 1. Resumen ejecutivo

**¿Es viable ejecutar Python no confiable en WASM en macOS arm64? Sí, técnicamente funciona y el aislamiento es real y barato. Pero con una advertencia grande sobre performance.**

Corrí un prototipo real: `wasmtime-py` instala sin fricción (wheel nativo arm64), carga un `python.wasm` (CPython 3.12 a WASI) y **ejecuta un artifact real del repo (`csv_to_json.py`) sin modificarlo, con output idéntico al de `subprocess`**, dentro de un sandbox con filesystem/red denegados por defecto y límite de CPU por "fuel".

El hallazgo incómodo y honesto:

- El **aislamiento WASM es casi gratis**: instanciar un módulo WASM aislado y fresco cuesta **~0.05 ms**. Eso es exactamente lo que promete D-3.
- Pero **arrancar el intérprete CPython dentro de WASM cuesta ~70 ms por ejecución** — es decir, la versión naive de "Python-en-WASM" es **~2× MÁS LENTA que el `subprocess python3` actual (~35 ms)**. El spawn del proceso desaparece, pero lo reemplaza el boot del intérprete interpretado sobre WASM.

Conclusión: **WASM resuelve la seguridad hoy, pero NO resuelve la velocidad "de yapa" si seguimos enviando Python como fuente.** El salto de performance solo llega si se elimina el boot del intérprete, y para eso hay dos caminos:

| Camino | Qué es | Payoff |
|---|---|---|
| **A. Wizer / pre-inicialización (snapshot)** | Bootear CPython una vez, congelar la memoria inicializada, y arrancar cada ejecución desde el snapshot | Recorta el boot de ~70 ms a un objetivo sub-10 ms; sigue siendo Python. Requiere tooling (wizer) — no probado en este spike. |
| **B. Artifact compilado directamente a WASM** (opción 4 de la tarea) | Que el compilador genere el artifact como módulo WASM (vía Rust→WASM o similar) en vez de `.py` | Elimina el intérprete por completo: ejecución sub-ms medida (0.05–0.27 ms). Es el destino "verdadero" de D-3, pero mueve el problema a "generar WASM confiable desde el LLM". |

### Recomendación

1. **Adoptar WASM como capa de aislamiento ya** (soluciona D-2/D-3 en seguridad), pero **no venderlo como mejora de latencia todavía**. Con `python.wasm` naive, la latencia empeora.
2. **Ruta de performance realista y por fases**: primero **Wizer** sobre `python.wasm` para bajar el boot (mantiene el artifact como Python, cambio pequeño en el pipeline). Medir. Si con Wizer se llega a <10–15 ms, WASM gana en seguridad Y velocidad manteniendo Python.
3. **Plan B si Wizer no rinde o el tooling es frágil en macOS**: mantener el `subprocess` actual endurecido con `rlimit` como sandbox interino (ya en el roadmap) y apuntar el esfuerzo de WASM a la opción B (artifact-a-WASM) como formato de distribución a mediano plazo, no como runtime de Python.

No recomiendo bloquear el roadmap esperando la ejecución productiva en WASM: adoptalo como aislamiento (gran victoria de seguridad, integración chica) y tratá la latencia como un problema separado con Wizer.

---

## 2. Tabla comparativa de opciones

| Opción | Madurez | macOS arm64 | Input/Output | Latencia/exec (medida o esperada) | Aislamiento | Esfuerzo de integración |
|---|---|---|---|---|---|---|
| **1. wasmtime-py + python.wasm** (VMware Wasm Labs / componentize-py) | Media-alta. `wasmtime-py` es oficial de Bytecode Alliance; `python.wasm` de VMware es estable pero el proyecto tiene mantenimiento intermitente. | ✅ **Verificado.** Wheel nativo arm64, `python.wasm` corre. | stdin/stdout vía `WasiConfig.stdin_file`/`stdout_file`; el artifact ya usa `sys.stdin`/`print` → **sin cambios en el artifact**. | **~70 ms medido** (boot CPython). ~0.05 ms la instancia; el costo es el intérprete. Con Wizer: objetivo <10 ms (no medido). | ✅ Fuerte: FS/red/env denegados por defecto (WASI capability-based); "fuel" limita CPU. Todo verificado. | **Bajo.** `WasmExecutor` cumple la misma firma que `LocalExecutor` (prototipo incluido). |
| **2. Pyodide / CPython-a-WASM desde un host** | Alta en browser, media fuera. Pyodide está pensado para el browser (JS host); usarlo server-side desde Python es incómodo y pesado (~10 MB+ y stack de emscripten). | ⚠️ Corre, pero el host natural es Node/browser, no un runtime WASM embebido en el servidor Python. | Vía JS/globals de Pyodide, no stdin/stdout WASI limpio. | Peor arranque que python.wasm puro (bootea CPython + capa emscripten). No lo medí: el modelo host no encaja con un servidor Python/Rust. | Depende del host JS; el modelo de capabilities WASI no aplica igual. | **Alto** y con impedancia (necesitás un runtime JS o wasm-bindgen). **No recomendado** para este caso. |
| **3. RustPython a WASM** | Baja-media para producción. Intérprete Python en Rust, compilable a WASM; **no es 100% compatible con CPython** (stdlib parcial, edge cases). | Compila a `wasm32-wasi`; correría en el mismo host wasmtime. No lo probé (requiere toolchain Rust + build). | stdin/stdout WASI igual que opción 1. | Esperada: arranque potencialmente más liviano que CPython, pero ejecución más lenta y **riesgo de incompatibilidad** con artifacts que usan libs/behaviour de CPython. | ✅ Igual que opción 1 (mismo host wasmtime + WASI). | **Medio-alto** por la incompatibilidad: un artifact generado por LLM asumiendo CPython puede fallar silenciosamente. Riesgoso para "código no confiable arbitrario". |
| **4. Artifact generado directamente como WASM** (Rust→WASM u otro) | El runtime (wasmtime) es maduro; **generar WASM correcto desde el LLM es el problema abierto.** | ✅ El runtime sí (verificado con módulos WAT reales). | stdin/stdout WASI (medido ~0.27 ms echo) o exports directos (medido ~0.05 ms). | **Sub-ms medido.** Sin intérprete = sin boot. Es el único camino que da la promesa completa de D-3. | ✅ El más fuerte y el más simple de razonar (superficie mínima). | **Alto en el compilador, bajo en el runtime.** El LLM ya no genera `.py`; genera (o se compila a) WASM. Cambia la naturaleza del "compilador de tareas". Trade-off abajo. |

### Trade-off de la opción 4 (artifact-a-WASM directo)

- **A favor:** cumple D-3 al 100% (seguridad + velocidad + portabilidad + distribución en un solo formato firmable), sub-ms real, superficie de ataque mínima, y el artifact pasa a ser "un binario aislado que corre en cualquier lado" en vez de "un `.py` que hay que confiar".
- **En contra:** hoy el pipeline compila tareas a **Python**, que es lo que los LLMs generan de forma más confiable y verificable. Pedirle al LLM que genere Rust/WASM correcto (o mantener una toolchain Rust→WASM por artifact) es mucho más caro y frágil, y complica la verificación diferencial (shadow-execution) que es el diferencial del producto. **Realista:** llegar a opción 4 vía un paso intermedio — compilar el Python del artifact a WASM con una toolchain (no pedirle WASM al LLM) — pero eso es esencialmente Wizer/componentize-py, o sea converge con la opción 1 mejorada.

---

## 3. Resultados de latencia medidos (prototipo real)

Todos medidos en esta máquina (macOS 26.5.2, arm64, Python 3.14.5, wasmtime-py 47.0.1). Scripts en `spike/bench.py`, `spike/bench2.py`, `spike/bench3.py`.

### 3.1 Latencia por ejecución (N=50, input = `{"csv_data":"a,b\n1,2\n3,4"}`)

| Escenario | mean | median | p95 | min |
|---|---|---|---|---|
| **1. `subprocess python3`** (LocalExecutor actual) | **34.7 ms** | 34.8 | 36.5 | 32.2 |
| **2. wasmtime, módulo de cómputo puro** (instancia+call, sin I/O) | **0.058 ms** | 0.051 | 0.071 | 0.043 |
| **3. wasmtime + WASI echo** (lee stdin, escribe stdout) | **0.201 ms** | 0.187 | 0.253 | 0.163 |
| **4. `python.wasm` CPython completo** (boot + script, N=20) | **68.9 ms** | 68.3 | 73.0 | 66.5 |

**Lectura:** el aislamiento WASM y el I/O WASI son sub-milisegundo. El costo de la opción "Python-en-WASM" es enteramente el boot del intérprete CPython (opción 4 de la tabla de arriba), que es ~2× el spawn nativo.

### 3.2 Atribución del costo de `python.wasm` (bench2.py)

| Fase | Tiempo | Naturaleza |
|---|---|---|
| Compilar `python.wasm` (cold) | ~825 ms | Una sola vez |
| Serializar a `.cwasm` (AOT) | ~12 ms | Una sola vez (build) |
| **Deserializar `.cwasm` (AOT) al bootear el server** | **~5 ms** | Una sola vez por proceso |
| **Instanciar una instancia aislada fresca** (sin correr) | **~0.05 ms** | Por ejecución — trivial |
| **Run completo (boot CPython + script)** | **~72 ms** | Por ejecución — **el cuello de botella** |

La compilación de 825 ms se amortiza totalmente: con AOT (`Module.serialize`/`deserialize_file`) el arranque del server baja a ~5 ms. La instanciación aislada por request es 0.05 ms. **Todo el costo residual es el startup del intérprete**, que es lo que Wizer atacaría.

> Nota: el `WasmExecutor` con `fuel` activado midió ~116 ms en la primera llamada (incluye warmup + overhead de metering por instrucción). El metering de fuel **agrega overhead** — hay que balancearlo contra timeouts externos.

### 3.3 Aislamiento verificado (bench3.py)

- **CPU/fuel:** un `(loop br 0)` (bucle infinito) se corta determinísticamente al agotar el budget de fuel → `Trap`. ✅
- **Filesystem:** WASI no expone ningún path del host salvo `preopen_dir(host, guest)` explícito. Sin preopen = cero FS. ✅
- **Red:** WASI preview1 no tiene superficie de sockets. Sin red por defecto. ✅
- **Env vars:** no se heredan salvo declaración explícita. ✅

---

## 4. Prototipo: dónde quedó el código

Todo en `spike/` (el `venv/` y los `.wasm` están en `.gitignore` por tamaño):

| Archivo | Qué es |
|---|---|
| `spike/bench.py` | Benchmark principal: subprocess vs wasmtime cómputo vs WASI echo vs python.wasm |
| `spike/bench2.py` | Atribución de costo + AOT precompile/deserialize |
| `spike/bench3.py` | Verificación de aislamiento (fuel, fs, net) |
| `spike/wasm_executor.py` | **Prototipo `WasmExecutor` con la MISMA firma que `LocalExecutor`** — corre `csv_to_json.py` real sin modificarlo |
| `spike/fetch_python_wasm.sh` | Descarga `python.wasm` (~25 MB) de VMware Wasm Labs (no commiteado) |

Reproducir:

```bash
python3 -m venv spike/venv
spike/venv/bin/pip install wasmtime
bash spike/fetch_python_wasm.sh          # baja python.wasm (~25 MB)
spike/venv/bin/python spike/bench.py     # números de 3.1
spike/venv/bin/python spike/bench2.py    # números de 3.2
spike/venv/bin/python spike/bench3.py    # aislamiento 3.3
spike/venv/bin/python spike/wasm_executor.py  # corre un artifact real en WASM
```

El `WasmExecutor` produjo, sobre el artifact real y sin tocarlo:
`{"records": [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}], "count": 2}` — **idéntico** al `subprocess`.

---

## 5. Riesgos y limitaciones en macOS arm64

- **`python.wasm` es un binario de terceros (~25 MB).** VMware Wasm Labs tiene releases infrecuentes; hay que fijar versión y hash, y asumir stdlib recortada (no todos los módulos C están disponibles). Verificar qué necesitan los artifacts reales antes de comprometerse.
- **Boot del intérprete = el problema central en macOS.** No es un problema específico de macOS (es interpretación sobre WASM), pero acá lo medimos: 72 ms > 35 ms nativo. Sin Wizer, WASM es una regresión de latencia.
- **Wizer no fue probado en este spike.** Es la pieza que hace que la recomendación cierre en velocidad, pero su tooling y compatibilidad en macOS arm64 hay que validarlos en un spike siguiente antes de comprometer números.
- **Overhead de `fuel`.** El metering por instrucción tiene costo; para artifacts cortos puede ser preferible un timeout de wall-clock por store en vez de fuel, o fuel con budget alto.
- **stdlib y librerías de terceros:** un artifact que importe `numpy`/`pandas` no corre en `python.wasm` estándar. Los artifacts actuales son stdlib puro (bien), pero es un límite duro a declarar en el "contrato de capacidades" del artifact.
- **Sin threads/subprocess dentro del sandbox** (es la idea), pero hay que confirmar que ningún artifact generado dependa de eso.

---

## 6. Plan de integración con `LocalExecutor` (concreto)

El `WasmExecutor` ya cumple la interfaz. Integración en 5 pasos:

1. **Dependencia + binario.** Agregar `wasmtime` a las deps del proyecto y un `fetch_python_wasm.sh` en el build (o vendorizar el `.cwasm` AOT). Fijar versión+hash del `python.wasm`.
2. **Promover el prototipo a módulo.** Mover `spike/wasm_executor.py` a `python/compiled_ai_router/wasm_executor.py`, exponiendo `execute_artifact(script_path, input_data) -> (Optional[str], float)` — misma firma que `LocalExecutor`. Compilar el módulo una vez en `__init__` (o cargar `.cwasm` con `Module.deserialize_file`, ~5 ms).
3. **Feature flag + selección de ejecutor.** En `router.py`/donde se instancia el ejecutor, elegir `WasmExecutor` vs `LocalExecutor` por config (ej. `EXECUTOR=wasm|subprocess`). Empezar detrás de flag, off por defecto. El alias `RustEngine` ya permite el swap sin romper imports.
4. **Aislamiento por contrato de capacidades.** Mapear el "contrato" del artifact (`fs:none, net:none, cpu:low`) a `WasiConfig`: sin `preopen_dir` salvo que el artifact lo declare, `set_fuel` según `cpu`. Esto conecta el spike con la idea 6f/D-3 del roadmap (capabilities declaradas por artifact).
5. **Medir en shadow y decidir sobre Wizer.** Correr WASM en modo shadow contra subprocess (comparar output + latencia real de producción). Si el boot de 70 ms es inaceptable, hacer el spike de **Wizer** (pre-inicializar `python.wasm` con el runtime del artifact congelado) y re-medir antes de activar por defecto.

**Criterio de decisión:** activar WASM por defecto para seguridad **ya** (aunque cueste latencia) si el aislamiento es requisito de venta; activar como mejora de latencia **solo** cuando Wizer (o artifact-a-WASM) baje el per-exec por debajo del subprocess actual (~35 ms).

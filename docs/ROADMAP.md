# Roadmap — Compiled AI Router

> Plan de trabajo para llevar el proyecto de prototipo a algo testeable y, eventualmente, comercializable.
> Basado en la investigación en [`docs/investigacion-ia-compilada.md`](investigacion-ia-compilada.md).
> Última actualización: 2026-07-31.

## Objetivo

Construir un producto sobre el concepto de **IA compilada**. La meta es comercializarlo, pero **primero hay que validar con datos reales** que la propuesta de valor existe. Hoy no se puede: las métricas están simuladas. Todo el plan apunta a poder responder, con números medidos, esta pregunta:

> Para tareas repetitivas, ¿compilar a código y ejecutarlo local es **medibly** más barato/rápido que llamar al LLM, con una **tasa de acierto** aceptable y **sin riesgo** de ejecución?

## Estado actual (honesto)

| Dimensión | Estado | Bloqueante para... |
|---|---|---|
| Concepto y arquitectura | ✅ Sólidos | — |
| Loop compilar→cachear→ejecutar | 🟡 Anda en modo `demo` | — |
| Path con LLM real | 🟡 Existe, poco probado | Validar acierto |
| **Métricas** | 🔴 Simuladas (`sleep`, tokens inventados) | **Validar el negocio** |
| **Sandbox de ejecución** | 🔴 Blocklist AST evadible; runtime sin sandbox | **Cualquier uso real** |
| Cache/similarity | 🟡 Scan O(n) + TF-IDF débil | Escala |
| Engine de Rust | 🔴 Código muerto (ver Decisión D-1) | — |

**Diagnóstico:** prototipo con buena base. Está a pocos pasos concretos de ser testeable en serio. No hay que reescribirlo — hay que hacerlo **honesto, medible y seguro**, en ese orden.

---

## Decisiones clave (ADR resumido)

Estas decisiones salen de la investigación y condicionan las fases. Detalle y fuentes en el doc de investigación.

- **D-1 · Rust no se usa para el orquestador.** El cuello de botella real es spawnear `python3` en cada ejecución (~30–50 ms de startup), no el lenguaje del router. Reescribir el orquestador en Rust ahorra microsegundos y no mueve la aguja. El `engine/` actual, además, también spawnea `python3`, así que no compra nada. → **Se retira de la ruta crítica.** Rust vuelve a aparecer, con sentido, solo como *runtime de sandbox WASM* (ver D-3).
- **D-2 · El sandbox no puede ser un blocklist de AST.** Siempre hay bypass (`open`, `getattr`, dunders). El análisis estático es *complemento*, no aislamiento. → Aislamiento real por capas: `rlimit`+subprocess (interino) → **WASM/wasmtime** (objetivo) → microVM/Firecracker o E2B (producción multi-tenant).
- **D-3 · WASM como capa de aislamiento: SÍ. Como mejora de latencia: no todavía** (revisado tras el spike, ver [`docs/wasm-sandbox-spike.md`](wasm-sandbox-spike.md)). Medido en esta máquina: el aislamiento WASM es casi gratis (instancia fresca ~0.05 ms, fuel/fs/red verificados), pero correr **CPython dentro de WASM cuesta ~70 ms/exec** — **~2× más lento que el subprocess actual (~35 ms)** porque el intérprete re-arranca en cada request. El salto de velocidad requiere **Wizer** (snapshot de pre-inicialización) o **artifact-compilado-a-WASM** (sub-ms medido, pero mueve el costo a "generar WASM confiable"). → Adoptar WASM por seguridad cuando el aislamiento sea requisito de venta; tratar la latencia como problema separado (spike de Wizer antes de prometer números).
- **D-4 · El moat es "programa por tarea", no "respuesta por input".** A diferencia de un caché semántico (GPTCache), el artifact generaliza a inputs nuevos de la misma clase. Hay que preservar y explotar esa distinción.
- **D-5 · El diferenciador comercial es la confianza medida en vivo** (shadow execution, ver Fase 4).

---

## Fases

Orden pensado para **validar antes de invertir**. No hace falta hacer todo; cada fase entrega algo usable.

### Fase 0 — Honestidad y limpieza ✅ (hecho / en curso)
Base para no engañarse con números falsos.
- [x] README alineado con lo que el código hace (sin claims de Rust sub-ms ni métricas fijas).
- [x] `Makefile` apuntando a comandos reales (antes referenciaba módulos inexistentes).
- [x] `examples/benchmark.sh` falso reemplazado por el benchmark real de la CLI.
- [x] `rust_bridge.py` limpiado: sin la pantomima de cargar una lib de Rust que nunca se usa.
- [x] `Dockerfile` reescrito (no compilaba: buscaba `Cargo.toml` en la raíz y arrancaba un módulo inexistente).
- [x] `engine/` (Rust muerto) eliminado — ver D-1. Repo inicializado con git; el código quedó en el historial (`git show HEAD~1:engine/...`).
- [ ] Seguridad mínima: CORS sin `allow_origins=["*"]`+credentials; bindear API a `127.0.0.1` por defecto.

### Fase 1 — Medición honesta ✅ (código listo; falta correrlo con API key real)
**Esto es lo que valida el negocio.** Sin números medidos no hay tesis ni pitch.
- [x] Latencia de passthrough **real**: `_passthrough` llama al LLM de verdad y mide (`sleep` eliminado; en demo queda flageado `measured=False`).
- [x] Tokens y costo **reales**: `pricing.py` + `response.usage`; `len(prompt)//4` degradado a estimación explícita solo en demo.
- [x] Instrumentar por tarea: latencia compilado vs passthrough, cache hit, `drift_events`/`recompilations`, costo, **break-even real** (`compile_cost / costo_por_request`).
- [x] Comando `measure` sobre un vertical (extracción de facturas): baseline real → compila → N cache hits → vuelca JSON. Dashboard marca MEDIDO vs SIMULADO.
- [x] **Primeros números REALES obtenidos** contra modelo local (Ollama `gemma4`, gratis, sin salir a internet) vía `LLM_BASE_URL`. Evidencia: [`docs/measurement-local-gemma4.json`](measurement-local-gemma4.json).
- [x] Soporte `LLM_BASE_URL` (endpoint OpenAI-compatible local) — permite medir sin gastar ni mandar datos afuera.
- **Entregable logrado.** Medición real (vertical facturas, gemma4 local, 3 baseline + 1 compile + 20 hits):

  | Métrica | Valor medido | Caveat honesto |
  |---|---|---|
  | Speedup | **220x** | Inflado: gemma4 local en Mac tarda ~11 s/call. Contra un modelo cloud (~1-2 s) sería ~20-40x. Igual enorme. |
  | Latencia compilado | **~51 ms** | Es el spawn de `python3`, no cómputo. Fase 2 lo baja a sub-ms. |
  | Latencia LLM | **~11.300 ms** | Local, lento. Real. |
  | Break-even | **~6.6 ejecuciones** | Con tarifas de config aplicadas a tokens reales (ref. "as-if-cloud"). |
  | Cache hit rate | 83% | Del workload de prueba. |

  **Conclusiones:** (1) el pipeline compila-y-ejecuta funciona end-to-end con un LLM real (incluso uno chico local); (2) el ahorro de latencia es real y grande; (3) el cuello del lado "compilado" es el spawn de intérprete → confirma la prioridad de Fase 2; (4) costo local ≈ $0 real, así que la historia de *ahorro de costo* hay que medirla contra precios cloud reales (correr `measure` con una key de OpenAI para el número comercial definitivo).

- [ ] **Opcional (tu OK — gasta $):** correr `measure` con `OPENAI_API_KEY` real para el número de ahorro de costo cloud definitivo.

### Fase 2 — Sandbox real
Bloqueante técnico #1. El fix de velocidad y el de seguridad son el mismo problema (eliminar el spawn).
- [x] **Interino:** ejecución con `resource.setrlimit` (CPU 10s, memoria 512MB best-effort, file 10MB, fds 64) + intérprete aislado `python -I` + env mínimo + cwd temporal + timeout wall 30s (`rust_bridge.py`).
- [x] **Revalidar SIEMPRE en runtime**: `security_check` corre antes de ejecutar cualquier artifact (defiende artifacts alterados en disco), no solo al compilar (`router.execute_artifact`).
- [x] Cerrar bypasses del gate estático: `open`, `getattr/setattr/delattr`, `globals/locals/vars`, y acceso a dunders peligrosos (`__class__`, `__bases__`, `__subclasses__`, `__globals__`, `__builtins__`, …). Bloqueo a nivel de nombre y de atributo (`validator.py`). Tests nuevos cubren cada bypass.
- [x] Seguridad de API: CORS sin `allow_origins=*`+credentials; `API_HOST` default `127.0.0.1` (contenedor setea `0.0.0.0`).
- [x] **Spike WASM completado** ([`docs/wasm-sandbox-spike.md`](wasm-sandbox-spike.md), prototipo en `spike/`): `WasmExecutor` con la misma firma que `LocalExecutor` corre un artifact real sin modificarlo, aislado (fs/red denegados, fuel corta bucles infinitos). **Conclusión:** aislamiento real y barato, pero Python-en-WASM naive es ~2× más lento que el subprocess → ver D-3.
- [ ] **Siguiente decisión (WASM):** spike de **Wizer** (pre-init de `python.wasm`) para bajar el boot de ~70 ms a <10-15 ms. Solo si rinde, WASM gana en seguridad *y* velocidad manteniendo Python. Plan B: subprocess+rlimit interino (ya hecho) + WASM solo cuando el aislamiento sea requisito de venta.
- [x] Análisis estático real al compilar: gate 2b con **Bandit** (SAST), como complemento del blocklist. Opcional — si no está instalado, se saltea con aviso (`validator.gate_2b_bandit`).
- [ ] **Limitación honesta pendiente:** aislamiento de RED. En macOS no hay namespaces; hoy la red se corta solo a nivel de blocklist estático (imports `socket/urllib/http/requests` prohibidos), no a nivel de OS. El corte real de red llega con WASM/microVM.

### Fase 3 — LLM real + validación por ejemplos
Cerrar el loop de compilación con rigor (idea robada de PROSE/FlashFill: exigir generalización, no que pase 1 ejemplo).
- [ ] Ejercitar y testear el path de compilación con LLM real (hoy solo `demo` está probado).
- [ ] Contrato de I/O documentado y testeado con casos borde.
- [ ] **Golden tests por clase de tarea:** set de input→output esperado; el gate semántico corre contra ejemplos *held-out*, no solo el de compilación.
- [ ] Regeneración automática ante fallo de validación (con límite de reintentos).

### Fase 4 — Diferenciador: confianza medida en vivo (shadow execution) ⭐
Lo que te separa de un "caché de LLM". Ver D-5.
- [ ] Para un % muestreado del tráfico (1–5%), ejecutar **artifact + LLM en paralelo** y comparar outputs (el usuario recibe el del artifact, sin latencia extra).
- [ ] Cada artifact acumula un **score de confianza vivo** = tasa de acuerdo con el LLM en muestras recientes.
- [ ] El routing usa ese score: si cae bajo umbral para una clase → auto-fallback al LLM + recompilación.
- [ ] Los shadow-runs alimentan el banco de ejemplos held-out de la Fase 3 (**flywheel de datos**).
- **Entregable:** métrica vendible ("98,x% de acuerdo con GPT-4, medido en vivo") + drift resuelto estadísticamente.

### Fase 5 — Cache y matching que escalen
- [ ] Reemplazar el scan lineal por índice `dict` por `prompt_hash`.
- [ ] Reemplazar el TF-IDF re-fiteado por par (débil y O(n)) por embeddings + índice vectorial (o al menos un vectorizer fiteado una vez).
- [ ] **Composición de artifacts** (idea de Voyager): componer skills existentes en pipelines sin recompilar.
- [ ] Estrategia de invalidación (versión de prompt, drift, TTL).

### Fase 6 — Camino a producto (cuando la tesis ya esté validada)
- [ ] **WASM como unidad de distribución** del artifact (D-3): módulos firmados, portables, con capacidades declaradas.
- [ ] Persistencia real (los artifacts en JSON sueltos no escalan) → DB.
- [ ] Multi-tenant: aislamiento de artifacts y sandbox por cliente (Firecracker/microVM o E2B como proveedor).
- [ ] Auth/API keys, rate limiting, quotas.
- [ ] Observabilidad (logs estructurados, trazas, alertas de drift).
- [ ] **Router económico** (idea de RouteLLM + amortización): predecir repetición esperada y compilar solo cuando `E[N] > break-even`.

---

## Qué NO hacer (todavía)

- No reescribir el orquestador en Rust (D-1).
- No pulir la UI ni agregar features antes de tener números reales (Fase 1).
- No construir infra de microVM propia al principio: si necesitás aislamiento fuerte para vender, empezá con E2B como proveedor.
- No compilar toda tarea: por debajo del break-even, el passthrough es más barato.

## Referencias

- Investigación completa del paradigma, sandboxing y Rust: [`docs/investigacion-ia-compilada.md`](investigacion-ia-compilada.md)

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
- **D-3 · El formato objetivo del artifact es WASM.** Un módulo WASM firmado resuelve *seguridad + velocidad + portabilidad + distribución* en una sola decisión, y elimina el spawn de intérprete. Es acá donde Rust (wasmtime como host) cobra sentido.
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
- [ ] **Pendiente (requiere tu OK — gasta $ y sale a OpenAI):** correr `OPENAI_API_KEY=... python -m compiled_ai_router.cli measure` para obtener los primeros números REALES.
- **Entregable:** primer número real de "cuánto ahorra esto en X". Con eso decidís si vale seguir.

### Fase 2 — Sandbox real
Bloqueante técnico #1. El fix de velocidad y el de seguridad son el mismo problema (eliminar el spawn).
- [ ] **Interino (bajo esfuerzo):** subprocess + `resource.setrlimit` (CPU/memoria) + sin red + timeout, y **revalidar SIEMPRE en runtime**, no solo al compilar.
- [ ] Cerrar los bypass del gate estático actual (`open`, `getattr`, dunders, `__builtins__`) — como complemento, no como única defensa.
- [ ] **Objetivo:** PoC de ejecución en **WASM (wasmtime)** — mide latencia real sin spawn y da aislamiento por diseño (WASI capabilities + fuel).
- [ ] Análisis estático de verdad al compilar (Bandit/Semgrep) en vez del blocklist casero.

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

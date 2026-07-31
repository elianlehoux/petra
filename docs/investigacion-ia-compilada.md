# Investigación: el paradigma de la "IA Compilada"

> Documento de aprendizaje para entender el paradigma antes de construir.
> Fecha: 2026-07-31. Autor de la investigación: Claude (para el proyecto Compiled AI Router).
>
> **Cómo leer esto:** las secciones 1–4 son para *entender el terreno*. La sección 5 (Rust) responde una pregunta concreta y práctica. La sección 6 (Innovación) es la que importa para diferenciarse: propone ideas que van más allá de lo que ya existe.

---

## 0. TL;DR (lo esencial en 10 líneas)

- El concepto **existe y tiene nombre en la literatura**: "compilar" tareas de LLM a código determinista que se ejecuta muchas veces sin volver a llamar al modelo. Hay hasta un paper titulado *"Compiled AI"* con números concretos (≈450× menos latencia, ≈40–57× menos costo, break-even ~17 ejecuciones).
- No estás inventando la categoría, pero **la categoría todavía no tiene un ganador claro de producto**. El diferencial no está en la idea sino en **la ejecución: sandbox real, medición honesta y detección de drift**.
- El **verdadero moat conceptual** de tu proyecto (que lo distingue de GPTCache y compañía): cacheás **programas** parametrizados por la *tarea*, no **respuestas** parametrizadas por el *input*. Un programa generaliza a inputs nuevos; una respuesta cacheada no.
- Sobre Rust: **no te sirve para reescribir el router** (el cuello de botella real es spawnear `python3` en cada ejecución, no el lenguaje del orquestador). Rust **sí te sirve** si lo usás como *runtime de sandbox* (wasmtime + artifacts en WASM). Pero el salto de performance más grande y barato es *dejar de spawnear un intérprete por ejecución*.
- La innovación defendible está en tratar cada artifact como una entidad con **confianza medida en vivo** (shadow-execution contra el LLM) que sabe cuándo degradarse — no como un caché estático.

---

## 1. Qué es el paradigma y de dónde viene

La idea central: en vez de mandar cada request al LLM, usás el LLM **una vez** (en "compile time") para generar un artefacto ejecutable (código, un pipeline optimizado, un plan), y después ejecutás ese artefacto **N veces** de forma determinista, barata y auditable ("runtime"). Cambiás flexibilidad en runtime por predictibilidad, costo y velocidad.

Esto no es una idea aislada: es la convergencia de **cuatro linajes** distintos de investigación que estaban resolviendo problemas parecidos por separado.

### Linaje A — Síntesis de programas / "Programming by Example" (pre-LLM, 2013+)
Antes de los LLM, Microsoft ya hacía "compilar intención a código": **FlashFill** (Excel 2013) y el framework **PROSE** sintetizan un programa a partir de ejemplos input→output. Un dato clave para vos: para 1–3 ejemplos puede haber **10²⁰ programas** que satisfacen el spec — el problema difícil no es *generar* uno, es que **generalice a inputs no vistos**. Esta es exactamente la trampa de tu proyecto: un artifact que anda con el ejemplo de compilación pero falla con datos reales. La lección de PROSE: separá el motor de búsqueda de la validación por ejemplos, y validá contra ejemplos *held-out*.

### Linaje B — LLM como compilador / declarativo (2023+)
- **DSPy** (Stanford, 2023): "programá, no promptees". Definís *signatures* y *modules* y DSPy **compila** eso a un pipeline de LLM optimizado (mejora 25–65% sobre prompt engineering; modelos chicos alcanzan a GPT-3.5). Es el antecedente directo de la palabra "compilar" en este contexto.
- **LLM+P** (2023): traduce lenguaje natural a PDDL y le pasa la ejecución a un planner clásico. Los LLM solos fallan en planificar; el híbrido funciona. → *La lógica dura va afuera del modelo.*
- **AlphaCodium** (2024): flujos estructurados con verificación suben GPT-4 de 19% → 44% de acierto. → *La verificación es parte del método, no un extra.*
- **Meta LLM Compiler** (2024): OJO, esto es *otra cosa* — es un modelo entrenado para optimización de compiladores (LLVM-IR). No confundir con "compilar IA a código". Relevante solo como nombre.

### Linaje C — Caching semántico (2023+)
- **GPTCache / GPT Semantic Cache**: cachean **respuestas** del LLM indexadas por *embedding de la query*. Reportan 61–69% de reducción de llamadas, >97% de precisión en los hits. Redis + embeddings.
- **Diferencia crítica con tu proyecto** (esto es tu tesis, subrayala): GPTCache cachea *la respuesta a un input concreto*. Si cambia el input, cache miss. **Vos cacheás el *programa* que resuelve la *clase de tarea*** — el mismo artifact sirve para infinitos inputs distintos de esa clase. Eso es estructuralmente más potente y es tu argumento de venta #1.

### Linaje D — Bibliotecas de skills en agentes (2023+)
- **Voyager** (Minecraft, 2023): el agente acumula una *skill library* de código ejecutable en una **base vectorial**; ante una tarea nueva, recupera skills por similitud de embedding y las **compone**. Es exactamente tu "similarity-based cache hit" pero con dos ideas que te faltan: (1) **composición** de artifacts, no solo recuperación 1-a-1; (2) mejora iterativa con feedback de errores de ejecución.
- Trabajos más nuevos (EvoSkill, SKILL-DISCO, 2026): destilan trazas de agentes en skills procedurales reutilizables. La categoría "biblioteca de habilidades compiladas" está muy viva.

### Linaje E — Routing de modelos (2024+)
- **RouteLLM** (LMSYS, 2024): un router liviano manda cada query al modelo más barato capaz de resolverla. 40% menos llamadas a GPT-4 con <5% de pérdida de calidad; con datos aumentados, 95% de calidad usando solo 14% de llamadas al modelo fuerte (~75% de ahorro).
- Para vos: tu router hoy decide "compilado vs LLM". RouteLLM decide "modelo barato vs modelo caro". **Son componibles**: podés tener un router de dos ejes (¿compilo? y si no, ¿a qué modelo mando?).

---

## 2. El paper que tenés que leer: *"Compiled AI"* (arXiv 2604.05150)

Hay un paper académico —*"Compiled AI: Deterministic Code Generation for LLM-Based Workflow Automation"*— que describe **casi exactamente tu arquitectura**, aplicada a workflows de salud. Es la mejor validación de que la idea es seria, y a la vez la vara contra la que te vas a comparar. Resumen de lo que hace y qué podés robarle:

**Pipeline (4 etapas):**
1. **Generación** con código *acotado a funciones chicas (20–50 líneas) dentro de templates validados* (no genera scripts libres — genera el "relleno" de plantillas pre-testeadas). ← idea fuerte que vos no tenés.
2. **Ensamblado** del código generado con templates y módulos pre-testeados.
3. **Validación** en 4 gates (seguridad, sintaxis, ejecución, accuracy) con **regeneración automática ante fallo**.
4. **Deploy** del artifact como código estático.

**Seguridad — patrón "Safety Sandwich"** (constreñir la parte probabilística entre validación de input y lógica determinista), con 3 gates:
- *Input gate*: detección de prompt injection (DeBERTa-v3) + escaneo de PII (Presidio).
- *Code gate*: análisis estático real (**Bandit, Semgrep**) — SQLi, command injection, path traversal.
- *Output gate*: canary tokens para detectar filtración de prompt.
- Y ejecución en **entorno sandboxeado** (no solo análisis estático).

**Números que reportan** (tu benchmark objetivo):
- Break-even vs LLM directo: **~17 transacciones**.
- **57×** menos tokens a 1.000 transacciones; **40–57×** menos costo (a 1M tx/mes: $555 vs $22.000 de TCO).
- Latencia: **4,5 ms P50** vs 2.004 ms del LLM directo → **~450×**.
- Confiabilidad: 96% de task completion; **las 16 fallas ocurrieron en compile-time** (detectables antes de deploy) → 100% de confiabilidad en workflows ya desplegados.
- Seguridad (135 casos): 95,8% recall en prompt injection (100% precisión); **75% recall en code safety** (ojo: 1 de cada 4 problemas de código se les escapa).

**Limitaciones que confiesan (y que son tus oportunidades):**
- Depende de specs YAML bien definidos; tareas creativas no compilan.
- 4% de fallo en compilación de function-calling.
- Complejidad ciclomática alta (23,8 vs 8 de código humano) — el código generado es feo/frágil.
- Evaluado en solo 2 tipos de tarea.

> **Conclusión de esta sección:** los números de tu README (600×, 450×) no son fantasía absurda — *están en el orden correcto* según la literatura. Pero en el paper esos números **están medidos**; en tu código están **hardcodeados**. Ese es todo el trabajo pendiente.

---

## 3. Mapa: ¿dónde está parado tu proyecto?

| Sistema | Qué cachea/compila | Sandbox | Métricas | Madurez |
|---|---|---|---|---|
| **Tu router (hoy)** | Programas por tarea | AST blocklist (evadible) | Simuladas | Prototipo |
| Paper "Compiled AI" | Relleno de templates | Bandit+Semgrep+sandbox | Medidas | Investigación |
| DSPy | Pipelines de prompts | N/A (no ejecuta código libre) | Medidas | Producción (Databricks) |
| GPTCache | Respuestas por input | N/A | Medidas | Producción |
| Voyager | Skills (código) componibles | Entorno del juego | N/A | Investigación |
| RouteLLM | Nada (rutea a modelo) | N/A | Medidas | Producción |

Tu posición: la idea correcta, la arquitectura razonable, pero **atrasado en las dos cosas que definen si esto es real: sandbox y medición**. La buena noticia es que nadie "ganó" esta categoría como producto todavía.

---

## 4. Sandboxing: el problema técnico duro (y cómo lo resuelve la industria)

Tu validador por AST **no es un sandbox** y ningún blocklist lo va a ser (siempre hay un bypass: `open()`, `getattr`, dunders, `__builtins__`). La industria ya convergió en una jerarquía clara. De menos a más aislamiento:

1. **Análisis estático (AST/Bandit/Semgrep)** — necesario pero *insuficiente solo*. Detecta lo obvio; no contiene la ejecución. El paper mismo solo logra 75% de recall acá.
2. **Contenedores (Docker)** — insuficientes solos para código adversario: comparten kernel. "Container-only isolation is generally not enough."
3. **gVisor** — kernel de usuario que intercepta syscalls. Buen punto medio.
4. **WebAssembly (wasmtime)** — 🟢 *el candidato más interesante para vos*. Sandbox por diseño: sin acceso a memoria externa, red ni FS salvo capabilities explícitas (modelo **WASI capability-based**). Tiene **"fuel"** (límite de cómputo, tipo gas de Ethereum) para matar loops infinitos. Existe `llm-wasm-sandbox` (Python/JS generado por LLM corriendo en WASM/WASI). Arranque casi instantáneo, sin spawn de proceso pesado.
5. **microVMs (Firecracker / E2B)** — 🟢 *el estándar de producción para código de agentes*. Aislamiento por hardware (KVM), kernel propio por sandbox. **Boot ≤125 ms, <5 MiB de overhead**; E2B logra init <200 ms y "elimina cold starts". Es lo que usa la industria (E2B, Daytona, Modal) para ejecutar código de LLM en serio.

**Recomendación práctica según etapa:**
- **Para validar (ahora):** subprocess + `resource.setrlimit` (CPU/memoria) + sin red + timeout. Piso mínimo decente, cero infra nueva.
- **Para el salto de performance + seguridad juntos:** **WASM (wasmtime embebido en Rust)**. Resuelve aislamiento *y* velocidad en un solo formato de artifact. Ver sección 6.
- **Para producción multi-tenant comercial:** **Firecracker/microVM** (o directamente E2B como proveedor, para no construir infra de aislamiento vos mismo al principio).

---

## 5. ¿Rust te sirve de verdad? (respuesta honesta)

**Tu intuición "Rust es más rápido" es correcta pero mal aplicada al lugar donde estás mirando.** Desglosemos.

### 5.1. Dónde está tu cuello de botella real hoy
Tu ejecución hace `subprocess.run(["python3", script_path])` **en cada request**. El costo dominante ahí **no es Python vs Rust**: es el **arranque de un intérprete de Python entero por ejecución** (~30–50 ms solo de startup del intérprete + import de módulos). Reescribir el *orquestador* en Rust te ahorraría **microsegundos** mientras el spawn de `python3` te cuesta **decenas de milisegundos**. Es optimizar lo que no importa.

Evidencia de la comunidad: en cargas **I/O-bound**, un microservicio FastAPI+PyO3(Rust) rindió **casi igual** que Python puro. Y en un caso real, "un speedup de 100× en el pattern-matching mejoró la latencia end-to-end solo ~2%" porque el sistema era I/O-bound. Rust paga **solo donde el cuello es CPU-bound o tail latency (p99)**, no en glue/orquestación.

### 5.2. La verdad incómoda sobre tu "engine" de Rust actual
El `engine/src/executor.rs` que tenés **también** hace `Command::new("python3")`. O sea: aunque conectaras el FFI de Rust, seguirías pagando el spawn del intérprete. **No te compraría nada.** Por eso hoy es código muerto que además vende una promesa falsa.

### 5.3. El fix de performance de verdad (no requiere Rust)
El salto grande es **eliminar el spawn por ejecución**, y hay tres formas, en orden de esfuerzo:
1. **Pool de workers persistentes** de Python que reciben el input por stdin/socket y ya tienen el intérprete caliente. Barato, gran mejora.
2. **Ejecución in-process** con aislamiento (arriesgado sin sandbox — no lo hagas sin WASM/subinterpreters).
3. **Compilar el artifact a WASM** y ejecutarlo en un runtime embebido → sin proceso nuevo, sub-ms real, y sandboxeado de yapa.

### 5.4. Dónde Rust SÍ gana (y vale la pena)
- **Como host del runtime WASM**: `wasmtime` es un runtime Rust de primera. Un servicio Rust que carga artifacts WASM y los ejecuta in-process te da **sub-ms + aislamiento + alta concurrencia con p99 apretado**. *Acá Rust brilla de verdad.*
- **Serving de alta concurrencia** con tail latency exigente (miles de req/s).
- **CPU-bound puro** dentro del hot path (parsing masivo, etc.) vía PyO3.

### 5.5. Veredicto
> **No reescribas el router en Rust.** No mueve la aguja y te frena. **Primero** matá el spawn de intérprete (pool de workers o WASM). **Si** vas a WASM, ahí Rust (wasmtime) se vuelve la elección natural del runtime y *ahí* cobra sentido todo el "engine". Rust es la respuesta a "¿con qué ejecuto artifacts WASM rápido y seguro?", no a "¿en qué lenguaje escribo el orquestador?".

---

## 6. Innovación: cómo diferenciarte (más allá de lo que ya existe)

Todo lo anterior es lo que *ya se hizo*. Acá van ideas para ir un paso más allá. Las separo en "combinaciones inteligentes de piezas existentes" y "genuinamente nuevo".

### 6.1. Combinaciones que casi nadie está juntando

**(a) Caché de dos niveles: respuesta + programa.**
GPTCache cachea respuestas (rápido pero frágil ante inputs nuevos). Vos cachés programas (robusto ante inputs nuevos). **Combiná ambos:** nivel 1 = respuesta exacta para inputs idénticos (0 ms), nivel 2 = artifact para misma-tarea-otro-input, nivel 3 = LLM. Nadie tiene esta jerarquía completa y limpia.

**(b) Composición de artifacts (robado de Voyager).**
Hoy recuperás *un* artifact por similitud. Voyager **compone** varios. Un artifact "extraer factura" + "convertir a CSV" debería componerse en un pipeline sin recompilar. Convertís tu store en un *álgebra de skills*, no una tabla de lookup.

**(c) Router económico que predice amortización.**
El break-even es ~17 ejecuciones. Entonces **no toda tarea conviene compilar**. Entrená un predictor liviano: "¿cuántas veces se va a repetir esta clase de tarea?". Solo compilás cuando `E[N] > break-even`. Compilar algo que se usa 2 veces es *más caro* que el passthrough. Esto es RouteLLM aplicado al eje compilar/no-compilar, y no lo vi como producto.

### 6.2. Genuinamente nuevo (tu posible moat)

**(d) Artifacts con confianza medida en vivo ("shadow execution").** ⭐ *La idea más fuerte.*
El problema no resuelto de todos estos sistemas: *¿cómo sabés que el artifact sigue estando bien cuando el mundo cambia?* (data drift). Propuesta:
- Para un % pequeño y muestreado del tráfico (ej. 1–5%), ejecutás **el artifact Y el LLM en paralelo** y comparás outputs (el usuario recibe el del artifact, sin latencia extra).
- Cada artifact acumula un **score de confianza vivo** = tasa de acuerdo con el LLM en las muestras recientes.
- Ese score **maneja el routing**: si la confianza cae bajo un umbral para una clase de tarea → auto-fallback al LLM + recompilación automática.
- **Beneficio doble:** (1) resolvés drift de forma estadística en vez de esperar a que el artifact crashee; (2) generás, gratis, un dataset de accuracy *real y continuo* — que es justo lo que necesitás para vender ("nuestros artifacts mantienen 98,3% de acuerdo con GPT-4, medido en vivo").
- Nadie combina "compile-once" con "verificación diferencial continua contra el modelo". Es defendible.

**(e) Flywheel de datos: los shadow-runs alimentan la validación (robado de PROSE).**
Cada shadow-run es un par input→output "verdad" del LLM. Acumulás un banco de ejemplos por clase de tarea. Al **recompilar**, exigís que el nuevo artifact **generalice sobre los ejemplos held-out** (rigor estilo FlashFill/PROSE), no solo que pase el ejemplo de compilación. Con el tiempo, tus artifacts se vuelven *más* confiables mientras corren — al revés que un caché, que se degrada.

**(f) WASM como *unidad de distribución* del artifact.** ⭐ *La idea más práctica.*
Compilá cada artifact a un **módulo WASM firmado**. Un solo formato que es: portable (corre en edge, browser, serverless, on-prem), sandboxeado por diseño (WASI capabilities), sub-ms (sin spawn), y verificable (hash/firma). Esto unifica *seguridad + velocidad + distribución* en una decisión. Convierte tu "artifact" de "un `.py` suelto que hay que confiar" en "un binario aislado que corre en cualquier lado". **Y responde la pregunta de Rust:** el runtime es wasmtime (Rust). Este es probablemente el "un paso más hacia la realidad" de mayor palanca.

**(g) Artifacts con capacidades declaradas (capability-scoped).**
Cada artifact declara qué necesita (`fs:none, net:none, cpu:low`). El sandbox concede *exactamente* eso (WASI). Un artifact de extracción de texto que declara `net:none, fs:none` puede correr por el camino más rápido y con confianza máxima; uno que pide red se marca como riesgoso y va a aislamiento fuerte. Convierte la seguridad de un blocklist reactivo a un *contrato* proactivo por artifact.

### 6.3. Síntesis: la tesis diferenciada de una línea
> No un "caché de LLM" (eso es GPTCache), sino un **compilador de tareas a artifacts WASM portables, sandboxeados y con confianza medida en vivo, que saben cuándo degradarse al LLM** — con un flywheel donde cada ejecución en producción mejora la próxima compilación.

Eso combina lo mejor de los 5 linajes y agrega dos cosas que nadie tiene junto: **verificación diferencial continua** + **artifact como binario WASM con contrato de capacidades**.

---

## 7. Implicancias directas para el roadmap

Cruzando esto con el plan previo:
- **Confirmado:** medición honesta primero (sección 2 — sin números medidos no tenés ni tesis ni pitch).
- **Confirmado:** el AST no alcanza como sandbox (sección 4).
- **Ajuste sobre Rust:** *no* reescribir el orquestador; el objetivo Rust correcto es "runtime WASM con wasmtime" — y recién después de matar el spawn de intérprete (sección 5).
- **Nuevo en el roadmap:** evaluar **WASM como formato de artifact** (6f) como el "paso a la realidad" de mayor palanca, y **shadow-execution** (6d) como el diferenciador comercial.

---

## Fuentes

- [Compiled AI: Deterministic Code Generation for LLM-Based Workflow Automation (arXiv)](https://arxiv.org/html/2604.05150v1)
- [DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines (arXiv)](https://arxiv.org/abs/2310.03714) · [DSPy en Stanford HAI](https://hai.stanford.edu/research/dspy-compiling-declarative-language-model-calls-into-state-of-the-art-pipelines) · [repo](https://github.com/stanfordnlp/dspy)
- [GPT Semantic Cache: Reducing LLM Costs and Latency via Semantic Embedding Caching (arXiv)](https://arxiv.org/abs/2411.05276)
- [Voyager: An Open-Ended Embodied Agent with Large Language Models](https://voyager.minedojo.org/)
- [RouteLLM: An Open-Source Framework for Cost-Effective LLM Routing (LMSYS)](https://www.lmsys.org/blog/2024-07-01-routellm/)
- [Meta Large Language Model Compiler (AI at Meta)](https://ai.meta.com/research/publications/meta-large-language-model-compiler-foundation-models-of-compiler-optimization/)
- [PROSE / FlashFill — Program Synthesis using Examples (Neural-Guided Deductive Search, arXiv)](https://arxiv.org/pdf/1804.01186)
- [Wasmtime — Security](https://docs.wasmtime.dev/security.html) · [Bytecode Alliance — Security and Correctness in Wasmtime](https://bytecodealliance.org/articles/security-and-correctness-in-wasmtime)
- [llm-wasm-sandbox (PyPI)](https://pypi.org/project/llm-wasm-sandbox/)
- [WebAssembly could solve AI agents' most dangerous security gap (The New Stack)](https://thenewstack.io/webassembly-sandboxing-ai-agents/)
- [Firecracker vs QEMU (E2B Blog)](https://e2b.dev/blog/firecracker-vs-qemu) · [AI Agent Code Execution Sandboxes: Containers to MicroVMs](https://addozhang.medium.com/ai-agent-code-execution-sandboxes-isolation-from-containers-to-microvms-e80848effea5)
- [Rust vs Python Performance 2026: Real Benchmarks & When It Matters](https://rustify.rs/articles/rust-vs-python-performance-2026) · [PyO3 performance analysis (issue)](https://github.com/PyO3/pyo3/issues/1607)

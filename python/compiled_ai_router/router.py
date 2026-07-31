import os
import json
import uuid
import time
import logging
from statistics import mean
from typing import Dict, Any, List, Tuple, Optional
import openai
from .models import TaskRequest, TaskResponse, CompiledArtifact, MetricsSummary
from .config import Settings
from .similarity import find_similar_artifact
from .compiler import compile_task, detect_task_type
from .rust_bridge import RustEngine
from .validator import security_check
from . import pricing

logger = logging.getLogger(__name__)

# Latencia de LLM SUPUESTA para modo demo (sin API key). NO es una medición.
# Solo existe para que el demo muestre algo; con measured=False se marca como tal.
ASSUMED_DEMO_LLM_LATENCY_MS = 150.0


class CompiledAIRouter:
    def __init__(self, config: Settings):
        self.config = config
        self.metrics = MetricsSummary()
        self.artifacts: Dict[str, CompiledArtifact] = {}
        self.rust_engine = RustEngine(config.RUST_ENGINE_PATH)

        # Muestras para medición honesta (Fase 1).
        self.passthrough_latencies: List[float] = []
        self.compiled_latencies: List[float] = []
        self.passthrough_tokens: List[int] = []   # baseline real de tokens por request
        self.passthrough_costs: List[float] = []   # baseline real de costo por request
        # Baseline por task_type: el ahorro de un cache hit solo es "medido" si esa
        # MISMA clase de tarea tuvo un passthrough real (no un promedio global cruzado).
        self.passthrough_tokens_by_type: Dict[str, List[int]] = {}
        self.passthrough_costs_by_type: Dict[str, List[float]] = {}
        self.compile_costs: List[float] = []       # costo real de cada compilación
        self.any_simulated = False                 # True si hubo passthrough simulado

        os.makedirs(self.config.ARTIFACT_DIR, exist_ok=True)
        self.load_artifacts()

    def load_artifacts(self):
        self.artifacts.clear()
        for filename in os.listdir(self.config.ARTIFACT_DIR):
            if filename.endswith(".json"):
                path = os.path.join(self.config.ARTIFACT_DIR, filename)
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                        artifact = CompiledArtifact(**data)
                        self.artifacts[artifact.id] = artifact
                        cc = artifact.metadata.get("compile_cost_usd")
                        if cc:
                            self.compile_costs.append(cc)
                except Exception as e:
                    logger.error(f"Failed to load artifact {path}: {e}")

    def save_artifact(self, artifact: CompiledArtifact):
        path = os.path.join(self.config.ARTIFACT_DIR, f"{artifact.id}.json")
        with open(path, 'w') as f:
            f.write(artifact.model_dump_json(indent=2))

        script_path = os.path.join(self.config.ARTIFACT_DIR, f"{artifact.id}.py")
        with open(script_path, 'w') as f:
            f.write(artifact.script_content)

        self.artifacts[artifact.id] = artifact

    def is_compilable(self, prompt: str) -> bool:
        lower = prompt.lower()
        non_compilable_keywords = ["chat", "discuss", "explain your reasoning", "tell me a joke", "what do you think"]
        if any(word in lower for word in non_compilable_keywords):
            return False
        return True

    def _has_real_key(self) -> bool:
        """True si podemos hacer llamadas reales al LLM: key real O endpoint local."""
        if self.config.LLM_BASE_URL:
            return True
        key = self.config.OPENAI_API_KEY
        return bool(key) and key != "demo"

    def execute_artifact(self, artifact: CompiledArtifact, input_data: Any) -> Tuple[Any, float, bool]:
        """Executes a compiled artifact. Returns (output, duration_ms, success)."""
        # Re-chequeo de seguridad en RUNTIME (no solo al compilar): defiende contra
        # artifacts alterados en disco. Ver docs/ROADMAP.md D-2 / Fase 2.
        ok, msg = security_check(artifact.script_content)
        if not ok:
            logger.error(f"Artifact {artifact.id} rechazado por seguridad en runtime: {msg}")
            return {"error": f"security check failed: {msg}"}, 0.0, False

        # Escribir SIEMPRE el contenido validado justo antes de ejecutar: garantiza
        # que los bytes ejecutados == los bytes validados por security_check (cierra
        # el TOCTOU / tamper del .py en disco). Antes solo se escribía si no existía,
        # así que un archivo alterado en disco se ejecutaba sin revalidar.
        script_path = os.path.join(self.config.ARTIFACT_DIR, f"{artifact.id}.py")
        with open(script_path, 'w') as f:
            f.write(artifact.script_content)

        input_str = json.dumps(input_data) if input_data is not None else "{}"

        output_str, duration = self.rust_engine.execute_artifact(script_path, input_str)

        if output_str is None:
            return None, duration, False

        try:
            output = json.loads(output_str) if output_str else None
            # Check for error payload
            if isinstance(output, dict) and "error" in output and len(output) == 1:
                return output, duration, False
        except Exception:
            output = {"raw": output_str}

        artifact.execution_count += 1
        n = artifact.execution_count
        artifact.avg_execution_time_ms = ((n - 1) * artifact.avg_execution_time_ms + duration) / n
        self.save_artifact(artifact)

        return output, duration, True

    def _passthrough(self, request: TaskRequest) -> Tuple[Any, float, int, float, bool]:
        """Ejecuta el fallback al LLM. Devuelve (output, latency_ms, tokens, cost_usd, measured).

        Con API key real: llama al LLM y mide latencia/tokens/costo REALES.
        En modo demo: NO llama al LLM; devuelve un resultado simulado marcado measured=False.
        """
        if not self._has_real_key():
            # Simulado. No representa un LLM real; queda flageado.
            self.any_simulated = True
            est_tokens = len(request.prompt) // 4 + 100
            est_cost = est_tokens * self.config.TOKEN_COST_INPUT
            output = {"result": f"[simulated passthrough] '{request.prompt[:40]}...'"}
            return output, ASSUMED_DEMO_LLM_LATENCY_MS, est_tokens, est_cost, False

        # Llamada REAL al LLM (OpenAI o endpoint local OpenAI-compatible).
        base_url = self.config.LLM_BASE_URL
        client = openai.Client(api_key=self.config.OPENAI_API_KEY or "local", base_url=base_url) if base_url \
            else openai.Client(api_key=self.config.OPENAI_API_KEY)
        start = time.perf_counter()
        response = client.chat.completions.create(
            model=self.config.LLM_MODEL,
            messages=[{"role": "user", "content": request.prompt}],
            temperature=0.0,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = prompt_tokens + completion_tokens
        cost = pricing.cost_usd(
            self.config.LLM_MODEL, prompt_tokens, completion_tokens,
            self.config.TOKEN_COST_INPUT, self.config.TOKEN_COST_OUTPUT,
        )
        # Registrar baseline real por request (global + por task_type).
        self.passthrough_tokens.append(total_tokens)
        self.passthrough_costs.append(cost)
        ttype = request.task_type or detect_task_type(request.prompt)
        self.passthrough_tokens_by_type.setdefault(ttype, []).append(total_tokens)
        self.passthrough_costs_by_type.setdefault(ttype, []).append(cost)
        return {"result": content}, latency_ms, total_tokens, cost, True

    def _estimate(self, prompt: str) -> Tuple[int, float]:
        """Estimación cruda de tokens/costo (heurística, NO medición)."""
        tokens = len(prompt) // 4 + 100
        cost = tokens * self.config.TOKEN_COST_INPUT
        return tokens, cost

    def _saved_baseline(self, prompt: str, task_type: str) -> Tuple[int, float, bool]:
        """Cuánto habría costado ir al LLM (ahorro de un cache hit) para ESTA clase de tarea.

        Devuelve (tokens, cost_usd, measured). measured=True SOLO si esa misma
        task_type tuvo un passthrough real medido — no un promedio global de otras
        tareas. Si no, estima y marca measured=False.
        """
        toks = self.passthrough_tokens_by_type.get(task_type)
        costs = self.passthrough_costs_by_type.get(task_type)
        if toks and costs:
            return round(mean(toks)), mean(costs), True
        # Sin baseline real para esta clase: estimamos (demo) y lo flageamos.
        self.any_simulated = True
        tokens, cost = self._estimate(prompt)
        return tokens, cost, False

    async def route(self, request: TaskRequest) -> TaskResponse:
        self.metrics.total_requests += 1
        prompt_hash = self.rust_engine.hash_prompt(request.prompt)

        # force_passthrough / force_compile deben saltear el cache.
        skip_cache = request.force_passthrough or request.force_compile

        # 1. Exact Cache Hit
        for artifact in ([] if skip_cache else list(self.artifacts.values())):
            if artifact.prompt_hash == prompt_hash:
                output, duration, success = self.execute_artifact(artifact, request.input_data)
                if success:
                    return self._on_compiled_hit(request, "compiled", output, duration, artifact)
                else:
                    logger.warning(f"Artifact {artifact.id} failed on input (Drift detected). Triggering re-compilation...")
                    self.metrics.drift_events += 1
                    new_artifact = compile_task(request, self.config.OPENAI_API_KEY, self.config.LLM_MODEL, self.config.LLM_BASE_URL)
                    new_artifact.id = artifact.id
                    new_artifact.prompt_hash = prompt_hash
                    self._track_compile_cost(new_artifact)
                    self.save_artifact(new_artifact)
                    output, duration, _ = self.execute_artifact(new_artifact, request.input_data)
                    self.metrics.compilations += 1
                    self.metrics.recompilations += 1
                    # Una recompilación GASTÓ tokens de LLM: NO es un ahorro ni un cache hit.
                    return self._on_compile(request, "recompiled", output, duration, new_artifact)

        # 2. Similarity-based Cache Hit
        if not request.force_compile and not request.force_passthrough:
            artifact_list = list(self.artifacts.values())
            best_match = find_similar_artifact(request.prompt, artifact_list, self.config.SIMILARITY_THRESHOLD)
            if best_match:
                output, duration, success = self.execute_artifact(best_match, request.input_data)
                if success:
                    return self._on_compiled_hit(request, "compiled", output, duration, best_match)

        # 3. Passthrough (force_compile NUNCA cae a passthrough)
        if request.force_passthrough or (not self.is_compilable(request.prompt) and not request.force_compile):
            self.metrics.passthroughs += 1
            output, duration, tokens, cost, measured = self._passthrough(request)
            self.passthrough_latencies.append(duration)
            return self._build_response(
                request, "passthrough", output, duration,
                tokens_used=tokens, cost_usd=cost, tokens_saved=0, cost_saved=0.0,
                measured=measured,
            )

        # 4. First-time Compile & Cache
        self.metrics.compilations += 1
        artifact = compile_task(request, self.config.OPENAI_API_KEY, self.config.LLM_MODEL, self.config.LLM_BASE_URL)
        # Reusar id si ya existe un artifact con el mismo prompt_hash (evita duplicados
        # con force_compile): se sobrescribe en vez de crear un uuid nuevo por cada compile.
        existing = next((a for a in self.artifacts.values() if a.prompt_hash == prompt_hash), None)
        if existing:
            artifact.id = existing.id
        self._track_compile_cost(artifact)
        self.save_artifact(artifact)
        output, duration, _ = self.execute_artifact(artifact, request.input_data)
        return self._on_compile(request, "compile_new", output, duration, artifact)

    def _track_compile_cost(self, artifact: CompiledArtifact):
        # Recalcula el costo con las tarifas de config (fallback para modelos
        # no listados en pricing, ej. modelos locales). Autoritativo.
        if not artifact.metadata.get("measured"):
            return
        pt = artifact.metadata.get("compile_prompt_tokens", 0)
        ct = artifact.metadata.get("compile_completion_tokens", 0)
        cost = pricing.cost_usd(
            self.config.LLM_MODEL, pt, ct,
            self.config.TOKEN_COST_INPUT, self.config.TOKEN_COST_OUTPUT,
        )
        artifact.metadata["compile_cost_usd"] = cost
        if cost:
            self.compile_costs.append(cost)

    def _on_compiled_hit(self, request: TaskRequest, route: str, output: Any, duration: float, artifact: CompiledArtifact) -> TaskResponse:
        """Cache hit real: 0 tokens gastados, ahorro = baseline de ESA task_type."""
        self.metrics.compiled_hits += 1
        self.compiled_latencies.append(duration)
        saved_tokens, saved_cost, measured = self._saved_baseline(request.prompt, artifact.task_type)
        return self._build_response(
            request, route, output, duration,
            tokens_used=0, cost_usd=0.0,
            tokens_saved=saved_tokens, cost_saved=saved_cost,
            measured=measured,
            artifact_id=artifact.id,
        )

    def _on_compile(self, request: TaskRequest, route: str, output: Any, duration: float, artifact: CompiledArtifact) -> TaskResponse:
        """Compilación (nueva o recompilación por drift): GASTÓ tokens de LLM.

        No es un ahorro ni un cache hit — no incrementa compiled_hits. Contabiliza
        el costo real de compilar (o una estimación flageada en modo demo).
        """
        self.compiled_latencies.append(duration)
        if artifact.metadata.get("measured"):
            tokens = artifact.metadata.get("compile_prompt_tokens", 0) + artifact.metadata.get("compile_completion_tokens", 0)
            cost = artifact.metadata.get("compile_cost_usd", 0.0)
            measured = True
        else:
            self.any_simulated = True
            tokens, cost = self._estimate(request.prompt)
            measured = False
        return self._build_response(
            request, route, output, duration,
            tokens_used=tokens, cost_usd=cost, tokens_saved=0, cost_saved=0.0,
            measured=measured, artifact_id=artifact.id,
        )

    def _build_response(self, request: TaskRequest, route: str, output: Any, latency: float,
                        tokens_used: int, cost_usd: float, tokens_saved: int, cost_saved: float,
                        measured: bool, artifact_id: str = None) -> TaskResponse:
        resp = TaskResponse(
            request_id=str(uuid.uuid4()),
            route=route,
            output=output,
            latency_ms=latency,
            tokens_used=tokens_used,
            tokens_saved=tokens_saved,
            cost_usd=cost_usd,
            cost_saved_usd=cost_saved,
            artifact_id=artifact_id,
            measured=measured,
        )

        self.metrics.total_tokens_saved += resp.tokens_saved
        self.metrics.total_cost_saved_usd += resp.cost_saved_usd
        if self.metrics.total_requests > 0:
            self.metrics.cache_hit_rate = self.metrics.compiled_hits / self.metrics.total_requests

        if self.compiled_latencies:
            self.metrics.avg_compiled_latency_ms = mean(self.compiled_latencies)
        if self.passthrough_latencies:
            self.metrics.avg_passthrough_latency_ms = mean(self.passthrough_latencies)
        if self.passthrough_tokens:
            self.metrics.avg_passthrough_tokens = mean(self.passthrough_tokens)

        if self.metrics.avg_compiled_latency_ms > 0 and self.metrics.avg_passthrough_latency_ms > 0:
            self.metrics.speedup_factor = self.metrics.avg_passthrough_latency_ms / self.metrics.avg_compiled_latency_ms

        # Break-even real: costo de compilar / costo por request al LLM.
        if self.compile_costs and self.passthrough_costs:
            per_req = mean(self.passthrough_costs)
            if per_req > 0:
                self.metrics.break_even_executions = mean(self.compile_costs) / per_req

        # measured del resumen: False si alguna vez hubo un número simulado.
        self.metrics.measured = not self.any_simulated

        return resp

    def get_metrics(self) -> MetricsSummary:
        return self.metrics

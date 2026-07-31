import os
import json
import uuid
import time
import logging
from typing import Dict, Any, List, Tuple
from .models import TaskRequest, TaskResponse, CompiledArtifact, MetricsSummary
from .config import Settings
from .similarity import find_similar_artifact
from .compiler import compile_task
from .rust_bridge import RustEngine

logger = logging.getLogger(__name__)

class CompiledAIRouter:
    def __init__(self, config: Settings):
        self.config = config
        self.metrics = MetricsSummary()
        self.artifacts: Dict[str, CompiledArtifact] = {}
        self.rust_engine = RustEngine(config.RUST_ENGINE_PATH)
        self.passthrough_latencies: List[float] = []
        self.compiled_latencies: List[float] = []
        
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

    def execute_artifact(self, artifact: CompiledArtifact, input_data: Any) -> Tuple[Any, float, bool]:
        """Executes a compiled artifact. Returns (output, duration_ms, success)."""
        script_path = os.path.join(self.config.ARTIFACT_DIR, f"{artifact.id}.py")
        if not os.path.exists(script_path):
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

    async def route(self, request: TaskRequest) -> TaskResponse:
        self.metrics.total_requests += 1
        prompt_hash = self.rust_engine.hash_prompt(request.prompt)
        
        # 1. Exact Cache Hit
        for artifact in list(self.artifacts.values()):
            if artifact.prompt_hash == prompt_hash:
                output, duration, success = self.execute_artifact(artifact, request.input_data)
                if success:
                    self.metrics.compiled_hits += 1
                    self.compiled_latencies.append(duration)
                    return self._build_response(request, "compiled", output, duration, artifact.id)
                else:
                    logger.warning(f"Artifact {artifact.id} failed on input (Drift detected). Triggering re-compilation...")
                    # Recompile on drift
                    new_artifact = compile_task(request, self.config.OPENAI_API_KEY, self.config.LLM_MODEL)
                    new_artifact.id = artifact.id  # Update existing artifact
                    new_artifact.prompt_hash = prompt_hash
                    self.save_artifact(new_artifact)
                    output, duration, _ = self.execute_artifact(new_artifact, request.input_data)
                    self.metrics.compilations += 1
                    self.compiled_latencies.append(duration)
                    return self._build_response(request, "recompiled", output, duration, new_artifact.id)

        # 2. Similarity-based Cache Hit
        if not request.force_compile and not request.force_passthrough:
            artifact_list = list(self.artifacts.values())
            best_match = find_similar_artifact(request.prompt, artifact_list, self.config.SIMILARITY_THRESHOLD)
            if best_match:
                output, duration, success = self.execute_artifact(best_match, request.input_data)
                if success:
                    self.metrics.compiled_hits += 1
                    self.compiled_latencies.append(duration)
                    return self._build_response(request, "compiled", output, duration, best_match.id)
                
        # 3. Passthrough
        if request.force_passthrough or not self.is_compilable(request.prompt):
            self.metrics.passthroughs += 1
            start = time.perf_counter()
            time.sleep(0.15)  # Simulate LLM API latency
            duration = (time.perf_counter() - start) * 1000
            self.passthrough_latencies.append(duration)
            output = {"result": f"Passthrough response for: '{request.prompt[:40]}...'"}
            return self._build_response(request, "passthrough", output, duration)

        # 4. First-time Compile & Cache
        self.metrics.compilations += 1
        artifact = compile_task(request, self.config.OPENAI_API_KEY, self.config.LLM_MODEL)
        self.save_artifact(artifact)
        
        output, duration, _ = self.execute_artifact(artifact, request.input_data)
        self.compiled_latencies.append(duration)
        return self._build_response(request, "compile_new", output, duration, artifact.id)
        
    def _build_response(self, request: TaskRequest, route: str, output: Any, latency: float, artifact_id: str = None) -> TaskResponse:
        tokens = len(request.prompt) // 4 + 100
        is_compiled = route in ("compiled", "recompiled")
        
        resp = TaskResponse(
            request_id=str(uuid.uuid4()),
            route=route,
            output=output,
            latency_ms=latency,
            tokens_used=0 if is_compiled else tokens,
            tokens_saved=tokens if is_compiled else 0,
            cost_usd=0.0 if is_compiled else (tokens * self.config.TOKEN_COST_INPUT),
            cost_saved_usd=(tokens * self.config.TOKEN_COST_INPUT) if is_compiled else 0.0,
            artifact_id=artifact_id
        )
        
        self.metrics.total_tokens_saved += resp.tokens_saved
        self.metrics.total_cost_saved_usd += resp.cost_saved_usd
        if self.metrics.total_requests > 0:
            self.metrics.cache_hit_rate = self.metrics.compiled_hits / self.metrics.total_requests
            
        if self.compiled_latencies:
            self.metrics.avg_compiled_latency_ms = sum(self.compiled_latencies) / len(self.compiled_latencies)
        if self.passthrough_latencies:
            self.metrics.avg_passthrough_latency_ms = sum(self.passthrough_latencies) / len(self.passthrough_latencies)
        else:
            self.metrics.avg_passthrough_latency_ms = 150.0  # Default benchmark baseline

        if self.metrics.avg_compiled_latency_ms > 0:
            self.metrics.speedup_factor = self.metrics.avg_passthrough_latency_ms / self.metrics.avg_compiled_latency_ms

        return resp
        
    def get_metrics(self) -> MetricsSummary:
        return self.metrics

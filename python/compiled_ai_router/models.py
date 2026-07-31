from datetime import datetime
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field

class TaskRequest(BaseModel):
    prompt: str
    input_data: Optional[Any] = None
    task_type: Optional[str] = None
    expected_output: Optional[str] = None
    force_compile: bool = False
    force_passthrough: bool = False

class TaskResponse(BaseModel):
    request_id: str
    route: str
    output: Any
    latency_ms: float
    tokens_used: int
    tokens_saved: int
    cost_usd: float
    cost_saved_usd: float
    artifact_id: Optional[str] = None
    # True = números medidos de una llamada real al LLM.
    # False = estimados/simulados (modo demo, sin API key).
    measured: bool = False

class ValidationResult(BaseModel):
    passed: bool
    gate_name: str
    message: str
    duration_ms: float

class CompiledArtifact(BaseModel):
    id: str
    prompt_hash: str
    original_prompt: str
    script_content: str
    task_type: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    validation_results: List[ValidationResult] = Field(default_factory=list)
    execution_count: int = 0
    avg_execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

class MetricsSummary(BaseModel):
    total_requests: int = 0
    compiled_hits: int = 0
    compilations: int = 0
    passthroughs: int = 0
    recompilations: int = 0       # artifacts recompilados por drift
    drift_events: int = 0         # ejecuciones que fallaron sobre input real
    cache_hit_rate: float = 0.0
    total_tokens_saved: int = 0
    total_cost_saved_usd: float = 0.0
    avg_compiled_latency_ms: float = 0.0
    avg_passthrough_latency_ms: float = 0.0
    avg_passthrough_tokens: float = 0.0   # baseline real por request (si se midió)
    speedup_factor: float = 0.0
    # False si algún número viene de passthrough simulado (modo demo).
    measured: bool = True
    # Ejecuciones necesarias para amortizar el costo de compilar. None si no medido.
    break_even_executions: Optional[float] = None

import pytest
import shutil
import tempfile
from compiled_ai_router.router import CompiledAIRouter
from compiled_ai_router.config import Settings
from compiled_ai_router.models import TaskRequest
from compiled_ai_router.validator import validate_script

@pytest.fixture
def temp_env():
    tmp_dir = tempfile.mkdtemp()
    settings = Settings(ARTIFACT_DIR=tmp_dir, OPENAI_API_KEY="demo")
    router = CompiledAIRouter(settings)
    yield router
    shutil.rmtree(tmp_dir)

@pytest.mark.asyncio
async def test_e2e_full_workflow(temp_env):
    router = temp_env
    
    # 1. Compile task for the first time
    req1 = TaskRequest(prompt="Extract invoice ID and amount", input_data={"text": "Invoice INV-100 for $250.00 dated 2026-05-01"})
    res1 = await router.route(req1)
    assert res1.route == "compile_new"
    assert res1.output["invoice_id"] == "INV-100"
    assert res1.output["amount"] == 250.0
    
    # 2. Repeated execution -> Cache Hit
    for _ in range(10):
        res = await router.route(TaskRequest(prompt="Extract invoice ID and amount", input_data={"text": "Invoice INV-200 for $99.00"}))
        assert res.route == "compiled"
        assert res.tokens_saved > 0
        assert res.latency_ms < 100.0
        
    # 3. Validation pipeline rejection of malicious script
    malicious_script = "import os\nos.system('echo hacked')"
    valid, results = validate_script(malicious_script)
    assert valid is False
    assert any("Forbidden" in r.message for r in results)
    
    # 4. Metrics Accuracy & O(1) Amortization Verification
    metrics = router.get_metrics()
    assert metrics.total_requests == 11
    assert metrics.compiled_hits == 10
    assert metrics.compilations == 1
    assert metrics.cache_hit_rate > 0.90
    assert metrics.total_tokens_saved > 0
    assert metrics.total_cost_saved_usd > 0.0
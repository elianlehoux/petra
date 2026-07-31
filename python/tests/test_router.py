import pytest
import shutil
import tempfile
from compiled_ai_router.router import CompiledAIRouter
from compiled_ai_router.config import Settings
from compiled_ai_router.models import TaskRequest

@pytest.fixture
def temp_router():
    tmp_dir = tempfile.mkdtemp()
    settings = Settings(ARTIFACT_DIR=tmp_dir, OPENAI_API_KEY="demo")
    router = CompiledAIRouter(settings)
    yield router
    shutil.rmtree(tmp_dir)

@pytest.mark.asyncio
async def test_router_compile_then_cache_hit(temp_router):
    req1 = TaskRequest(prompt="Extract invoice number from text", input_data={"text": "INV-5544"})
    res1 = await temp_router.route(req1)
    
    assert res1.route == "compile_new"
    assert res1.artifact_id is not None
    assert res1.tokens_used > 0
    
    # Second request: identical prompt -> Cache Hit
    req2 = TaskRequest(prompt="Extract invoice number from text", input_data={"text": "INV-9999"})
    res2 = await temp_router.route(req2)
    
    assert res2.route == "compiled"
    assert res2.artifact_id == res1.artifact_id
    assert res2.tokens_used == 0
    assert res2.tokens_saved > 0
    assert res2.latency_ms < 100.0  # Millisecond latency

@pytest.mark.asyncio
async def test_router_passthrough(temp_router):
    req = TaskRequest(prompt="What do you think about AI ethics?", force_passthrough=False)
    res = await temp_router.route(req)
    
    assert res.route == "passthrough"
    assert res.tokens_saved == 0
    assert res.tokens_used > 0
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
    assert res2.latency_ms < 1000.0  # ejecución local (no LLM); umbral robusto, no frágil

@pytest.mark.asyncio
async def test_router_passthrough(temp_router):
    req = TaskRequest(prompt="What do you think about AI ethics?", force_passthrough=False)
    res = await temp_router.route(req)

    assert res.route == "passthrough"
    assert res.tokens_saved == 0
    assert res.tokens_used > 0

@pytest.mark.asyncio
async def test_ondisk_tamper_has_no_effect(temp_router):
    # C3: alterar el .py en disco no cambia lo que se ejecuta (se sobrescribe con
    # el script_content validado antes de correr).
    import os
    res = await temp_router.route(TaskRequest(prompt="Extract invoice number from text", input_data={"text": "INV-1"}))
    art = temp_router.artifacts[res.artifact_id]
    path = os.path.join(temp_router.config.ARTIFACT_DIR, f"{art.id}.py")
    with open(path, "w") as f:
        f.write("import os\nos.system('echo pwned')\n")  # payload malicioso en disco
    out, dur, success = temp_router.execute_artifact(art, {"text": "INV-2"})
    assert success is True
    assert isinstance(out, dict) and "invoice_id" in out  # corrió el benigno, no el tamper

@pytest.mark.asyncio
async def test_force_compile_no_duplicates(temp_router):
    # M4: force_compile no debe crear artifacts duplicados con el mismo prompt_hash.
    p = "Extract invoice number from text"
    await temp_router.route(TaskRequest(prompt=p, input_data={"text": "INV-1"}, force_compile=True))
    await temp_router.route(TaskRequest(prompt=p, input_data={"text": "INV-2"}, force_compile=True))
    hashes = [a.prompt_hash for a in temp_router.artifacts.values()]
    assert len(temp_router.artifacts) == 1
    assert len(set(hashes)) == 1

@pytest.mark.asyncio
async def test_force_compile_does_not_fall_to_passthrough(temp_router):
    # M3: prompt "no compilable" + force_compile debe compilar igual, no passthrough.
    res = await temp_router.route(TaskRequest(prompt="explain your reasoning about invoices", force_compile=True))
    assert res.route != "passthrough"

def test_saved_baseline_is_per_task_type(temp_router):
    # M2: measured=True solo para la task_type que tuvo passthrough real medido.
    temp_router.passthrough_tokens_by_type["extraction"] = [100]
    temp_router.passthrough_costs_by_type["extraction"] = [0.01]
    _, _, measured_known = temp_router._saved_baseline("x", "extraction")
    _, _, measured_other = temp_router._saved_baseline("x", "transformation")
    assert measured_known is True
    assert measured_other is False

@pytest.mark.asyncio
async def test_runtime_revalidation_rejects_tampered_artifact(temp_router):
    # Compila un artifact legítimo...
    req = TaskRequest(prompt="Extract invoice number from text", input_data={"text": "INV-1"})
    res = await temp_router.route(req)
    artifact = temp_router.artifacts[res.artifact_id]

    # ...luego se lo "altera en disco" con código malicioso.
    artifact.script_content = "import os\nos.system('echo pwned')\n"
    output, duration, success = temp_router.execute_artifact(artifact, {"text": "INV-2"})

    # El re-chequeo de seguridad en runtime debe rechazarlo (no ejecutarlo).
    assert success is False
    assert isinstance(output, dict) and "security check failed" in output.get("error", "")
import pytest
from compiled_ai_router.compiler import compile_task, detect_task_type
from compiled_ai_router.models import TaskRequest, ExampleIO


def test_compile_demo_passes_with_matching_examples():
    # Fase 3: el script debe pasar los ejemplos held-out.
    ex = ExampleIO(input_data={"text": "INV-1 $5.00 2026-01-01"},
                   expected_output={"invoice_id": "INV-1", "amount": 5.0, "date": "2026-01-01", "status": "parsed"})
    req = TaskRequest(prompt="Extract invoice", input_data={"text": "INV-9 $9.00 2026-02-02"}, examples=[ex])
    artifact = compile_task(req, api_key="demo", model="gpt-4o-mini")
    gate5 = [r for r in artifact.validation_results if r.gate_name == "5_examples"][0]
    assert gate5.passed is True

class _FakeResp:
    def __init__(self, content):
        msg = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": msg})()]
        self.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 20})()

class _FakeClient:
    def __init__(self, scripts):
        self._scripts = scripts
        self._calls = 0
        create = self._create
        self.chat = type("Chat", (), {"completions": type("Comp", (), {"create": staticmethod(create)})()})()
    def _create(self, **kw):
        s = self._scripts[min(self._calls, len(self._scripts) - 1)]
        self._calls += 1
        return _FakeResp(s)

def test_compile_retries_on_validation_failure(monkeypatch):
    # Fase 3: 1er intento inválido (syntax), 2º válido -> compila en 2 intentos.
    bad = "```python\nthis is not valid python !!!\n```"
    good = "```python\nimport sys, json\nd = json.loads(sys.stdin.read() or '{}')\nprint(json.dumps({'ok': 1}))\n```"
    client = _FakeClient([bad, good])
    monkeypatch.setattr("compiled_ai_router.compiler.openai.Client", lambda *a, **k: client)
    req = TaskRequest(prompt="do something", input_data={})
    artifact = compile_task(req, api_key="sk-test", model="gpt-4o-mini")
    assert artifact.metadata["compile_attempts"] == 2
    assert all(r.passed for r in artifact.validation_results)
    # Tokens acumulados de ambos intentos (10+20 x2).
    assert artifact.metadata["compile_prompt_tokens"] == 20

def test_compile_demo_fails_unsatisfiable_examples():
    # Un ejemplo que el script no puede satisfacer -> la compilación falla (no cachea basura).
    ex = ExampleIO(input_data={"text": "INV-1 $5.00 2026-01-01"}, expected_output={"totally": "wrong"})
    req = TaskRequest(prompt="Extract invoice", input_data={"text": "INV-1 $5.00 2026-01-01"}, examples=[ex])
    with pytest.raises(ValueError):
        compile_task(req, api_key="demo", model="gpt-4o-mini")

def test_detect_task_type():
    assert detect_task_type("Extract invoice date from email") == "extraction"
    assert detect_task_type("Transform CSV to JSON") == "transformation"
    assert detect_task_type("Scrape prices from HTML table") == "scraping"
    assert detect_task_type("Fetch API endpoint and map payload") == "api_workflow"
    assert detect_task_type("Calculate fibonacci sequence") == "code_generation"

def test_compile_task_demo_mode():
    req = TaskRequest(prompt="Extract invoice number from text", input_data={"text": "INV-1234"})
    artifact = compile_task(req, api_key="demo", model="gpt-4o-mini")
    assert artifact.task_type == "extraction"
    assert "re.search" in artifact.script_content
    assert len(artifact.validation_results) == 6  # +gate 2b (bandit) +gate 5 (examples)
    assert all(vr.passed for vr in artifact.validation_results)
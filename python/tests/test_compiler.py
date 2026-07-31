import pytest
from compiled_ai_router.compiler import compile_task, detect_task_type
from compiled_ai_router.models import TaskRequest

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
    assert len(artifact.validation_results) == 5  # +gate 2b (bandit)
    assert all(vr.passed for vr in artifact.validation_results)
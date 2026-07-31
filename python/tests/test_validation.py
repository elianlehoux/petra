import pytest
from compiled_ai_router.validator import (
    gate_1_syntax,
    gate_2_security,
    gate_3_sandbox,
    gate_4_semantic,
    validate_script
)

def test_syntax_gate_pass():
    script = "import json, sys\nprint(json.dumps({'status': 'ok'}))"
    res = gate_1_syntax(script)
    assert res.passed is True
    assert res.gate_name == "1_syntax_ast"

def test_syntax_gate_fail():
    script = "import json sys\ndef main("
    res = gate_1_syntax(script)
    assert res.passed is False
    assert "SyntaxError" in res.message

def test_security_gate_pass():
    script = "import json, sys, re\nprint(json.dumps({'a': 1}))"
    res = gate_2_security(script)
    assert res.passed is True

def test_security_gate_fail_forbidden_import():
    script = "import os\nos.system('rm -rf /')"
    res = gate_2_security(script)
    assert res.passed is False
    assert "Forbidden module import" in res.message

def test_security_gate_fail_forbidden_call():
    script = "eval('1 + 1')"
    res = gate_2_security(script)
    assert res.passed is False
    assert "Forbidden function call" in res.message

def test_sandbox_gate_pass():
    script = "import json, sys\ndata = json.loads(sys.stdin.read() or '{}')\nprint(json.dumps({'echo': data}))"
    res = gate_3_sandbox(script, sample_input={"key": "value"})
    assert res.passed is True

def test_sandbox_gate_fail_runtime_exception():
    script = "raise RuntimeError('Crashing intentional')"
    res = gate_3_sandbox(script)
    assert res.passed is False
    assert "Runtime error" in res.message

def test_sandbox_gate_fail_non_json_output():
    script = "print('Hello non-json')"
    res = gate_3_sandbox(script)
    assert res.passed is False
    assert "not valid JSON" in res.message

def test_semantic_gate_pass():
    script = "import json\nprint(json.dumps({'val': 42}))"
    res = gate_4_semantic(script, input_data={}, expected_output='{"val": 42}')
    assert res.passed is True

def test_semantic_gate_fail_mismatch():
    script = "import json\nprint(json.dumps({'val': 100}))"
    res = gate_4_semantic(script, input_data={}, expected_output='{"val": 42}')
    assert res.passed is False
    assert "Output mismatch" in res.message

def test_full_pipeline_pass():
    script = "import json, sys\nprint(json.dumps({'result': 'success'}))"
    valid, results = validate_script(script)
    assert valid is True
    assert len(results) == 4

def test_full_pipeline_reject_malicious():
    script = "import subprocess\nsubprocess.run(['ls'])"
    valid, results = validate_script(script)
    assert valid is False
    assert any(not r.passed for r in results)
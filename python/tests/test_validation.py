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
    assert "eval" in res.message

def test_security_gate_blocks_open():
    # 'open' habilita lectura/escritura arbitraria de archivos: prohibido.
    res = gate_2_security("f = open('/etc/passwd')")
    assert res.passed is False
    assert "open" in res.message

def test_security_gate_blocks_dunder_escape():
    # Camino de escape clásico a builtins/os via dunders.
    res = gate_2_security("x = ().__class__.__bases__[0].__subclasses__()")
    assert res.passed is False

def test_security_gate_blocks_getattr_bypass():
    res = gate_2_security("getattr(__builtins__, 'ev' + 'al')('1')")
    assert res.passed is False

import pytest

@pytest.mark.parametrize("script", [
    "import posix\nposix.system('echo x')",          # posix == os
    "import builtins\nbuiltins.open('/etc/passwd')",  # reexpone open
    "import _socket",                                  # red
    "import ftplib",                                   # red
    "import pickle",                                   # deserialización
    "import codecs\ncodecs.open('x')",
    "import sqlite3",
    "from os import system",
])
def test_allowlist_blocks_equivalent_bypasses(script):
    # Antes evadibles con módulos no listados; el allowlist los corta.
    res = gate_2_security(script)
    assert res.passed is False

@pytest.mark.parametrize("script", [
    "import json, re, math",
    "import datetime, collections, itertools",
    "import base64, hashlib",
    "import sys\nsys.stdin.read()",
])
def test_allowlist_permits_safe_stdlib(script):
    res = gate_2_security(script)
    assert res.passed is True

def test_bandit_gate_graceful_and_clean():
    # Script limpio: pasa igual esté o no instalado Bandit (si no está, se saltea).
    from compiled_ai_router.validator import gate_2b_bandit
    res = gate_2b_bandit("import json, sys\nprint(json.dumps({'ok': True}))")
    assert res.passed is True
    assert res.gate_name == "2b_bandit"

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
    assert len(results) == 5  # syntax, security, bandit, sandbox, semantic

def test_full_pipeline_reject_malicious():
    script = "import subprocess\nsubprocess.run(['ls'])"
    valid, results = validate_script(script)
    assert valid is False
    assert any(not r.passed for r in results)
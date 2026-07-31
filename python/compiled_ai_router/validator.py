import ast
import json
import time
import subprocess
import tempfile
import sys
import logging
from typing import List, Optional, Any, Tuple
from .models import ValidationResult

logger = logging.getLogger(__name__)

# Dangerous AST nodes/names for Security Gate.
# NOTA: un blocklist de AST NO es un sandbox (ver docs/ROADMAP.md D-2). Es una
# primera capa. El aislamiento real lo dan el rlimit del executor + (objetivo) WASM.
FORBIDDEN_MODULES = {"os", "sys", "subprocess", "shutil", "socket", "http", "urllib", "requests", "ctypes", "importlib", "pathlib"}

# Nombres builtin prohibidos, tanto como llamada como referencia (x = open; x(...)).
# Se bloquea el camino de escape clásico: open, getattr/setattr, eval/exec, etc.
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "getattr", "setattr", "delattr", "globals", "locals", "vars",
    "memoryview", "__build_class__", "help", "exit", "quit",
}

# Dunders peligrosos: permiten navegar de un objeto inocente a builtins/os
# (ej. ().__class__.__bases__[0].__subclasses__()).
DANGEROUS_DUNDERS = {
    "__class__", "__base__", "__bases__", "__mro__", "__subclasses__",
    "__globals__", "__builtins__", "__code__", "__dict__", "__getattribute__",
    "__subclasshook__", "__init_subclass__", "__import__", "__loader__",
    "__spec__", "__closure__", "__func__", "__self__",
}


class SecurityVisitor(ast.NodeVisitor):
    def __init__(self):
        self.violations: List[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            module_name = alias.name.split('.')[0]
            # Allow sys ONLY for sys.stdin and sys.stdout
            if module_name in FORBIDDEN_MODULES and module_name != "sys":
                self.violations.append(f"Forbidden module import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            module_name = node.module.split('.')[0]
            if module_name in FORBIDDEN_MODULES and module_name != "sys":
                self.violations.append(f"Forbidden module import: {node.module}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        # Bloquea referencia a builtins peligrosos, no solo la llamada directa.
        if node.id in FORBIDDEN_NAMES:
            self.violations.append(f"Forbidden name: {node.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # Bloquea acceso a dunders peligrosos (camino de escape a builtins/os).
        if node.attr in DANGEROUS_DUNDERS:
            self.violations.append(f"Forbidden attribute access: {node.attr}")
        elif isinstance(node.value, ast.Name):
            if node.value.id == "os" and node.attr in {"system", "popen", "exec", "remove", "rmdir"}:
                self.violations.append(f"Forbidden call: os.{node.attr}")
            elif node.value.id == "sys" and node.attr not in {"stdin", "stdout", "stderr", "exit", "argv"}:
                self.violations.append(f"Forbidden sys attribute access: sys.{node.attr}")
        self.generic_visit(node)

def gate_1_syntax(script_content: str) -> ValidationResult:
    """Gate 1: Syntax & AST Validation"""
    start = time.perf_counter()
    try:
        ast.parse(script_content)
        dur = (time.perf_counter() - start) * 1000
        return ValidationResult(passed=True, gate_name="1_syntax_ast", message="Syntax valid", duration_ms=dur)
    except SyntaxError as e:
        dur = (time.perf_counter() - start) * 1000
        return ValidationResult(passed=False, gate_name="1_syntax_ast", message=f"SyntaxError: {e.msg} at line {e.lineno}", duration_ms=dur)

def gate_2_security(script_content: str) -> ValidationResult:
    """Gate 2: Security & Static Analysis"""
    start = time.perf_counter()
    try:
        tree = ast.parse(script_content)
        visitor = SecurityVisitor()
        visitor.visit(tree)
        dur = (time.perf_counter() - start) * 1000
        if visitor.violations:
            return ValidationResult(passed=False, gate_name="2_security", message=f"Security violation: {', '.join(visitor.violations)}", duration_ms=dur)
        return ValidationResult(passed=True, gate_name="2_security", message="Security check passed", duration_ms=dur)
    except Exception as e:
        dur = (time.perf_counter() - start) * 1000
        return ValidationResult(passed=False, gate_name="2_security", message=f"Security scan error: {e}", duration_ms=dur)

def security_check(script_content: str) -> Tuple[bool, str]:
    """Re-chequeo de seguridad rápido para runtime (defensa de artifacts alterados en disco).

    Corre el mismo gate estático que la compilación. Devuelve (ok, mensaje).
    """
    r = gate_2_security(script_content)
    return r.passed, r.message


def gate_3_sandbox(script_content: str, sample_input: Optional[Any] = None) -> ValidationResult:
    """Gate 3: Sandboxed Test Execution"""
    start = time.perf_counter()
    input_str = json.dumps(sample_input) if sample_input is not None else "{}"
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script_content)
        temp_path = f.name

    try:
        proc = subprocess.run(
            [sys.executable, temp_path],
            input=input_str,
            text=True,
            capture_output=True,
            timeout=5
        )
        dur = (time.perf_counter() - start) * 1000
        if proc.returncode != 0:
            return ValidationResult(passed=False, gate_name="3_sandbox", message=f"Runtime error (exit code {proc.returncode}): {proc.stderr.strip()}", duration_ms=dur)
        
        try:
            json.loads(proc.stdout.strip()) if proc.stdout.strip() else None
        except Exception:
            return ValidationResult(passed=False, gate_name="3_sandbox", message=f"Output is not valid JSON: {proc.stdout[:100]}", duration_ms=dur)

        return ValidationResult(passed=True, gate_name="3_sandbox", message="Sandbox execution successful", duration_ms=dur)
    except subprocess.TimeoutExpired:
        dur = (time.perf_counter() - start) * 1000
        return ValidationResult(passed=False, gate_name="3_sandbox", message="Execution timed out (>5s)", duration_ms=dur)
    finally:
        import os
        if os.path.exists(temp_path):
            os.remove(temp_path)

def gate_4_semantic(script_content: str, input_data: Any, expected_output: Optional[str] = None) -> ValidationResult:
    """Gate 4: Semantic Accuracy & Output Verification"""
    start = time.perf_counter()
    if not expected_output:
        dur = (time.perf_counter() - start) * 1000
        return ValidationResult(passed=True, gate_name="4_semantic", message="No expected output provided, skipped semantic gate", duration_ms=dur)

    input_str = json.dumps(input_data) if input_data is not None else "{}"
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script_content)
        temp_path = f.name

    try:
        proc = subprocess.run(
            [sys.executable, temp_path],
            input=input_str,
            text=True,
            capture_output=True,
            timeout=5
        )
        dur = (time.perf_counter() - start) * 1000
        output_str = proc.stdout.strip()
        
        try:
            actual = json.loads(output_str)
            expected = json.loads(expected_output)
            if actual == expected:
                return ValidationResult(passed=True, gate_name="4_semantic", message="Exact semantic match", duration_ms=dur)
            else:
                return ValidationResult(passed=False, gate_name="4_semantic", message=f"Output mismatch: got {actual}, expected {expected}", duration_ms=dur)
        except Exception:
            if expected_output.strip() == output_str:
                return ValidationResult(passed=True, gate_name="4_semantic", message="String match passed", duration_ms=dur)
            return ValidationResult(passed=False, gate_name="4_semantic", message="Semantic verification failed", duration_ms=dur)
    finally:
        import os
        if os.path.exists(temp_path):
            os.remove(temp_path)

def validate_script(script_content: str, sample_input: Optional[Any] = None, expected_output: Optional[str] = None) -> Tuple[bool, List[ValidationResult]]:
    """Runs all 4 gates on a compiled script artifact."""
    results = []
    
    r1 = gate_1_syntax(script_content)
    results.append(r1)
    if not r1.passed:
        return False, results

    r2 = gate_2_security(script_content)
    results.append(r2)
    if not r2.passed:
        return False, results

    r3 = gate_3_sandbox(script_content, sample_input)
    results.append(r3)
    if not r3.passed:
        return False, results

    r4 = gate_4_semantic(script_content, sample_input, expected_output)
    results.append(r4)
    if not r4.passed:
        return False, results

    return True, results

import ast
import os
import json
import time
import subprocess
import tempfile
import sys
import logging
from typing import List, Optional, Any, Tuple
from .models import ValidationResult
from .rust_bridge import run_sandboxed

logger = logging.getLogger(__name__)

# Static security gate.
# NOTA: esto NO es un sandbox (ver docs/ROADMAP.md D-2). Es defensa en profundidad,
# no una jaula. El aislamiento real (FS/red/procesos) lo da WASM/microVM (objetivo).
#
# ALLOWLIST de imports (no blocklist): un blocklist es whack-a-mole — `import posix`
# ES `os`, `import _socket` ES red, `import builtins` reexpone `open`/`eval`, etc.
# Solo se permiten módulos de stdlib seguros y sin I/O de red/FS/proceso.
ALLOWED_MODULES = {
    "sys",  # solo sys.stdin/stdout/stderr/exit/argv (ver visit_Attribute)
    "json", "re", "math", "cmath", "decimal", "fractions", "random", "statistics",
    "textwrap", "datetime", "time", "calendar", "zoneinfo",
    "collections", "itertools", "functools", "heapq", "bisect", "copy",
    "typing", "dataclasses", "enum", "numbers", "unicodedata",
    "base64", "binascii", "hashlib", "hmac", "uuid", "struct", "html",
}
# NOTA: `operator` y `string` se excluyen a propósito: `operator.attrgetter`/
# `methodcaller` y `string.Formatter().get_field` resuelven atributos por STRING
# (no como nodo AST literal) y evaden DANGEROUS_DUNDERS. Aun así, `str.format`
# (builtin, sin import) permite el mismo truco → el gate NO es un límite de
# seguridad. La contención real es el sandbox de OS del executor + WASM/microVM.

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
            if module_name not in ALLOWED_MODULES:
                self.violations.append(f"Forbidden module import: {alias.name} (no está en el allowlist)")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        # Import relativo (from . import x) o sin módulo: prohibido.
        if node.level and node.level > 0:
            self.violations.append("Forbidden relative import")
        module_name = (node.module or "").split('.')[0]
        if module_name not in ALLOWED_MODULES:
            self.violations.append(f"Forbidden module import: {node.module} (no está en el allowlist)")
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
    if not script_content or not script_content.strip():
        dur = (time.perf_counter() - start) * 1000
        return ValidationResult(passed=False, gate_name="1_syntax_ast", message="Script vacío", duration_ms=dur)
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

_BANDIT_AVAILABLE: Optional[bool] = None


def _bandit_available() -> bool:
    """Detecta (y cachea) si Bandit está instalado."""
    global _BANDIT_AVAILABLE
    if _BANDIT_AVAILABLE is None:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "bandit", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            _BANDIT_AVAILABLE = proc.returncode == 0
        except Exception:
            _BANDIT_AVAILABLE = False
    return _BANDIT_AVAILABLE


def gate_2b_bandit(script_content: str) -> ValidationResult:
    """Gate 2b: análisis estático real con Bandit (SAST).

    Complementa al blocklist de AST (que es fácil de evadir). Si Bandit no está
    instalado, se SALTEA con un aviso claro (no bloquea el flujo). Falla si Bandit
    reporta issues de severidad MEDIUM o HIGH.
    """
    start = time.perf_counter()
    if not _bandit_available():
        dur = (time.perf_counter() - start) * 1000
        return ValidationResult(passed=True, gate_name="2b_bandit",
                                message="Bandit no instalado — gate salteado (pip install bandit para SAST real)",
                                duration_ms=dur)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script_content)
        temp_path = f.name
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "bandit", "-f", "json", "-q", temp_path],
            capture_output=True, text=True, timeout=30,
        )
        dur = (time.perf_counter() - start) * 1000
        try:
            report = json.loads(proc.stdout or "{}")
        except Exception:
            return ValidationResult(passed=True, gate_name="2b_bandit",
                                    message="Bandit sin salida parseable — gate salteado", duration_ms=dur)
        results = report.get("results", [])
        blocking = [r for r in results if r.get("issue_severity") in ("MEDIUM", "HIGH")]
        if blocking:
            msgs = ", ".join(f"{r.get('test_id')}:{r.get('issue_text', '')[:50]}" for r in blocking[:3])
            return ValidationResult(passed=False, gate_name="2b_bandit",
                                    message=f"Bandit: {len(blocking)} issue(s) MEDIUM/HIGH: {msgs}", duration_ms=dur)
        return ValidationResult(passed=True, gate_name="2b_bandit",
                                message=f"Bandit OK ({len(results)} hallazgos bajos/nulos)", duration_ms=dur)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def security_check(script_content: str) -> Tuple[bool, str]:
    """Re-chequeo de seguridad rápido para runtime (defensa de artifacts alterados en disco).

    Corre el mismo gate estático que la compilación. Devuelve (ok, mensaje).
    """
    r = gate_2_security(script_content)
    return r.passed, r.message


def _coerce_expected(expected: Any) -> Any:
    """Si `expected` viene como string JSON, lo parsea (para comparar objeto vs objeto).
    Si no es JSON válido, se deja como string (comparación textual)."""
    if isinstance(expected, str):
        try:
            return json.loads(expected)
        except Exception:
            return expected
    return expected


def gate_3_sandbox(script_content: str, sample_input: Optional[Any] = None) -> ValidationResult:
    """Gate 3: ejecución de prueba en el sandbox (seatbelt + rlimits)."""
    start = time.perf_counter()
    input_str = json.dumps(sample_input) if sample_input is not None else "{}"
    rc, stdout, stderr, timed_out = run_sandboxed(script_content, input_str, timeout=5)
    dur = (time.perf_counter() - start) * 1000
    if timed_out:
        return ValidationResult(passed=False, gate_name="3_sandbox", message="Execution timed out (>5s)", duration_ms=dur)
    if rc != 0:
        return ValidationResult(passed=False, gate_name="3_sandbox", message=f"Runtime error (exit code {rc}): {stderr.strip()}", duration_ms=dur)
    # El contrato es escribir JSON a stdout. Un script sin salida (ej. 'pass',
    # solo comentarios/docstring) es basura degenerada: se rechaza (antes pasaba).
    if not stdout.strip():
        return ValidationResult(passed=False, gate_name="3_sandbox", message="El script no produjo salida JSON en stdout", duration_ms=dur)
    try:
        json.loads(stdout.strip())
    except Exception:
        return ValidationResult(passed=False, gate_name="3_sandbox", message=f"Output is not valid JSON: {stdout[:100]}", duration_ms=dur)
    return ValidationResult(passed=True, gate_name="3_sandbox", message="Sandbox execution successful", duration_ms=dur)


def gate_4_semantic(script_content: str, input_data: Any, expected_output: Optional[str] = None) -> ValidationResult:
    """Gate 4: verificación semántica contra un output esperado."""
    start = time.perf_counter()
    if not expected_output:
        dur = (time.perf_counter() - start) * 1000
        return ValidationResult(passed=True, gate_name="4_semantic", message="No expected output provided, skipped semantic gate", duration_ms=dur)

    input_str = json.dumps(input_data) if input_data is not None else "{}"
    rc, stdout, stderr, timed_out = run_sandboxed(script_content, input_str, timeout=5)
    dur = (time.perf_counter() - start) * 1000
    if timed_out:
        return ValidationResult(passed=False, gate_name="4_semantic", message="Execution timed out (>5s)", duration_ms=dur)
    output_str = stdout.strip()
    try:
        actual = json.loads(output_str)
        expected = json.loads(expected_output)
        if actual == expected:
            return ValidationResult(passed=True, gate_name="4_semantic", message="Exact semantic match", duration_ms=dur)
        return ValidationResult(passed=False, gate_name="4_semantic", message=f"Output mismatch: got {actual}, expected {expected}", duration_ms=dur)
    except Exception:
        if expected_output.strip() == output_str:
            return ValidationResult(passed=True, gate_name="4_semantic", message="String match passed", duration_ms=dur)
        return ValidationResult(passed=False, gate_name="4_semantic", message="Semantic verification failed", duration_ms=dur)

def gate_5_examples(script_content: str, examples: Optional[List[Any]] = None) -> ValidationResult:
    """Gate 5: Generalización — el script debe pasar TODOS los ejemplos held-out.

    `examples` es una lista de objetos con `.input_data` y `.expected_output`
    (ver models.ExampleIO). Rigor estilo PROSE: no basta con un ejemplo, tiene que
    generalizar. Si no hay ejemplos, se saltea.
    """
    start = time.perf_counter()
    if not examples:
        dur = (time.perf_counter() - start) * 1000
        return ValidationResult(passed=True, gate_name="5_examples", message="Sin ejemplos held-out, gate salteado", duration_ms=dur)

    for i, ex in enumerate(examples):
        input_str = json.dumps(ex.input_data) if ex.input_data is not None else "{}"
        rc, stdout, stderr, timed_out = run_sandboxed(script_content, input_str, timeout=5)
        dur = (time.perf_counter() - start) * 1000
        if timed_out:
            return ValidationResult(passed=False, gate_name="5_examples", message=f"Ejemplo {i}: timeout (>5s)", duration_ms=dur)
        if rc != 0:
            return ValidationResult(passed=False, gate_name="5_examples", message=f"Ejemplo {i}: runtime error: {stderr.strip()[:120]}", duration_ms=dur)
        try:
            actual = json.loads(stdout.strip())
        except Exception:
            # Fallback textual (consistente con gate_4): esperado como string no-JSON.
            if isinstance(ex.expected_output, str) and stdout.strip() == ex.expected_output.strip():
                continue
            return ValidationResult(passed=False, gate_name="5_examples", message=f"Ejemplo {i}: output no es JSON: {stdout[:80]}", duration_ms=dur)
        expected = _coerce_expected(ex.expected_output)  # BUG2: parsear si viene como string JSON
        if actual != expected:
            return ValidationResult(passed=False, gate_name="5_examples", message=f"Ejemplo {i}: got {actual}, expected {expected}", duration_ms=dur)

    dur = (time.perf_counter() - start) * 1000
    return ValidationResult(passed=True, gate_name="5_examples", message=f"Pasó los {len(examples)} ejemplos held-out", duration_ms=dur)


def validate_script(script_content: str, sample_input: Optional[Any] = None,
                    expected_output: Optional[str] = None, examples: Optional[List[Any]] = None) -> Tuple[bool, List[ValidationResult]]:
    """Corre el pipeline de gates sobre un script compilado."""
    results = []

    for gate in (
        lambda: gate_1_syntax(script_content),
        lambda: gate_2_security(script_content),
        lambda: gate_2b_bandit(script_content),
        lambda: gate_3_sandbox(script_content, sample_input),
        lambda: gate_4_semantic(script_content, sample_input, expected_output),
        lambda: gate_5_examples(script_content, examples),
    ):
        r = gate()
        results.append(r)
        if not r.passed:
            return False, results

    return True, results

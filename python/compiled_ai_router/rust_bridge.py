"""Ejecución local de artifacts.

NOTA (ver docs/ROADMAP.md, decisión D-1): hoy los artifacts se ejecutan
spawneando `python3` por cada request. Ese spawn (~30-50 ms de startup del
intérprete) es el verdadero cuello de botella, no el lenguaje del orquestador.
Por eso NO hay (ni conviene por ahora) un engine de Rust en la ruta crítica.

El plan de performance/seguridad es eliminar el spawn ejecutando los artifacts
en un runtime WASM embebido (wasmtime) — ahí sí Rust cobra sentido como host.
Hasta entonces, esta clase es un ejecutor local honesto y directo.
"""

import os
import sys
import shutil
import subprocess
import tempfile
import time
import hashlib
import logging
from typing import Optional, Tuple, List

try:
    import resource  # POSIX only
except ImportError:  # pragma: no cover - Windows
    resource = None

# Sandbox de OS en macOS (seatbelt). Contiene el DAÑO aunque el gate estático se
# evada (los gates de AST NO son un límite de seguridad — ver docs/ROADMAP.md D-2):
# confina la escritura de archivos al workdir temporal y DENIEGA la red.
# En Linux/producción el límite lo da el contenedor/microVM (o WASM).
# Limitación honesta: la LECTURA de archivos NO se restringe (python necesita leer
# su stdlib); confidencialidad fuerte requiere WASM/microVM con FS acotado.
_SANDBOX_EXEC = shutil.which("sandbox-exec") if sys.platform == "darwin" else None
# Señal honesta: el sandbox de OS (seatbelt) SOLO existe en macOS. En Linux/otros,
# `run_sandboxed`/`LocalExecutor` corren con rlimits best-effort pero NO confinan
# FS/red — la contención real allá la debe dar un contenedor/microVM (ROADMAP D-2/D-3).
SANDBOX_OS_ACTIVE = _SANDBOX_EXEC is not None
if not SANDBOX_OS_ACTIVE:
    logger.warning(
        "Sandbox de OS NO activo (no es macOS/sandbox-exec): la ejecución de código no "
        "confiable solo tiene rlimits best-effort, sin confinar FS/red. En Linux/producción, "
        "ejecutar dentro de un contenedor/microVM (ver docs/ROADMAP.md D-2/D-3)."
    )


def _seatbelt_profile(workdir_real: str) -> str:
    return (
        "(version 1)"
        "(deny default)"
        "(allow process*)"
        "(allow file-read*)"
        f'(allow file-write* (subpath "{workdir_real}"))'
        '(allow file-write-data (path "/dev/null"))'
        "(allow sysctl-read)"
        "(allow mach-lookup)"
        "(deny network*)"
    )


def _build_cmd(script_path: str, workdir_real: str) -> List[str]:
    base = [sys.executable, "-I", script_path]
    if _SANDBOX_EXEC:
        return [_SANDBOX_EXEC, "-p", _seatbelt_profile(workdir_real)] + base
    return base

logger = logging.getLogger(__name__)

# Límites del sandbox de ejecución (interino, ver docs/ROADMAP.md Fase 2).
# NO es aislamiento fuerte (para eso: WASM/microVM), pero acota daño y runaway.
_LIMIT_CPU_SECONDS = 10        # tiempo de CPU (no wall) del artifact
_LIMIT_ADDRESS_SPACE = 512 * 1024 * 1024   # 512 MB de memoria (best-effort en macOS)
_LIMIT_DATA = 512 * 1024 * 1024            # heap (RLIMIT_DATA), complemento de RLIMIT_AS
_LIMIT_FILE_SIZE = 10 * 1024 * 1024        # 10 MB máx de archivo escrito
_LIMIT_OPEN_FILES = 64
_LIMIT_PROCESSES = 64          # tope de procesos: mitiga fork bombs (best-effort)
_WALL_TIMEOUT_SECONDS = 30


def _apply_resource_limits():
    """preexec_fn: aplica rlimits en el proceso hijo antes de exec (POSIX).

    ADVERTENCIA (honesto): en macOS RLIMIT_AS/RLIMIT_DATA no se aplican de forma
    confiable (memoria NO contenida) y RLIMIT_NPROC cuenta procesos de todo el
    usuario. Estos límites son best-effort. La contención sólida de
    memoria/procesos/FS/red requiere WASM/microVM (ver docs/ROADMAP.md D-2/D-3).
    """
    if resource is None:
        return
    for res, soft in (
        (resource.RLIMIT_CPU, _LIMIT_CPU_SECONDS),
        (resource.RLIMIT_FSIZE, _LIMIT_FILE_SIZE),
        (resource.RLIMIT_NOFILE, _LIMIT_OPEN_FILES),
        (getattr(resource, "RLIMIT_NPROC", None), _LIMIT_PROCESSES),
        (getattr(resource, "RLIMIT_AS", None), _LIMIT_ADDRESS_SPACE),
        (getattr(resource, "RLIMIT_DATA", None), _LIMIT_DATA),
    ):
        if res is None:
            continue
        try:
            resource.setrlimit(res, (soft, soft))
        except (ValueError, OSError):
            # Varios límites no se aplican bien en macOS. Best-effort.
            pass


class LocalExecutor:
    """Ejecuta un artifact Python vía subprocess y devuelve (stdout, duración_ms)."""

    def __init__(self, lib_path: Optional[str] = None):
        # lib_path se mantiene por compatibilidad de firma; hoy no se usa.
        # Cuando exista el runtime WASM, este parámetro pasará a apuntarlo.
        if lib_path:
            logger.info(
                "RUST_ENGINE_PATH configurado pero ignorado: la ejecución nativa/WASM "
                "todavía no está implementada (ver docs/ROADMAP.md, Fase 2)."
            )

    def execute_artifact(self, script_path: str, input_data: str) -> Tuple[Optional[str], float]:
        start = time.perf_counter()
        # Entorno mínimo + intérprete aislado (-I: ignora PYTHON*, user site, cwd import).
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"}
        preexec = _apply_resource_limits if resource is not None else None
        try:
            with tempfile.TemporaryDirectory(prefix="carouter_exec_") as workdir:
                # realpath: seatbelt resuelve symlinks (/tmp -> /private/tmp).
                workdir_real = os.path.realpath(workdir)
                proc = subprocess.run(
                    _build_cmd(script_path, workdir_real),   # sandbox-exec en macOS
                    input=input_data,
                    text=True,
                    capture_output=True,
                    timeout=_WALL_TIMEOUT_SECONDS,
                    cwd=workdir_real,      # cwd descartable, no el del proyecto
                    env=env,
                    preexec_fn=preexec,    # rlimits (POSIX)
                )
            duration_ms = (time.perf_counter() - start) * 1000
            if proc.returncode != 0:
                logger.error(f"Script execution failed: {proc.stderr}")
                return None, duration_ms
            return proc.stdout.strip(), duration_ms
        except subprocess.TimeoutExpired:
            logger.error("Script execution timed out")
            return None, _WALL_TIMEOUT_SECONDS * 1000.0
        except Exception as e:
            logger.error(f"Script execution error: {e}")
            return None, 0.0

    def hash_prompt(self, prompt: str) -> str:
        return hashlib.sha256(prompt.encode()).hexdigest()


# Alias de compatibilidad: el router importa `RustEngine`. Se mantiene el nombre
# para no romper imports; renombrar es parte de la limpieza de la Fase 2.
RustEngine = LocalExecutor


def run_sandboxed(script_content: str, input_str: str, timeout: int = 5) -> Tuple[int, str, str, bool]:
    """Corre un script NO CONFIABLE bajo el mismo sandbox que el runtime (seatbelt +
    rlimits + intérprete aislado). Lo usan los gates de validación, que antes
    ejecutaban código generado por LLM SIN aislamiento de OS.

    Devuelve (returncode, stdout, stderr, timed_out).
    """
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"}
    preexec = _apply_resource_limits if resource is not None else None
    with tempfile.TemporaryDirectory(prefix="carouter_val_") as workdir:
        workdir_real = os.path.realpath(workdir)
        script_path = os.path.join(workdir_real, "candidate.py")
        with open(script_path, "w") as f:
            f.write(script_content)
        try:
            proc = subprocess.run(
                _build_cmd(script_path, workdir_real),
                input=input_str, text=True, capture_output=True,
                timeout=timeout, cwd=workdir_real, env=env, preexec_fn=preexec,
            )
            return proc.returncode, proc.stdout, proc.stderr, False
        except subprocess.TimeoutExpired:
            return -1, "", f"timeout (>{timeout}s)", True

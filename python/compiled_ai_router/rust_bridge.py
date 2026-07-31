"""Ejecución local de artifacts.

NOTA (ver docs/ROADMAP.md, decisión D-1): hoy los artifacts se ejecutan
spawneando `python3` por cada request. Ese spawn (~30-50 ms de startup del
intérprete) es el verdadero cuello de botella, no el lenguaje del orquestador.
Por eso NO hay (ni conviene por ahora) un engine de Rust en la ruta crítica.

El plan de performance/seguridad es eliminar el spawn ejecutando los artifacts
en un runtime WASM embebido (wasmtime) — ahí sí Rust cobra sentido como host.
Hasta entonces, esta clase es un ejecutor local honesto y directo.
"""

import subprocess
import time
import hashlib
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


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
        try:
            proc = subprocess.run(
                ["python3", script_path],
                input=input_data,
                text=True,
                capture_output=True,
                timeout=30,
            )
            duration_ms = (time.perf_counter() - start) * 1000
            if proc.returncode != 0:
                logger.error(f"Script execution failed: {proc.stderr}")
                return None, duration_ms
            return proc.stdout.strip(), duration_ms
        except subprocess.TimeoutExpired:
            logger.error("Script execution timed out")
            return None, 30000.0
        except Exception as e:
            logger.error(f"Script execution error: {e}")
            return None, 0.0

    def hash_prompt(self, prompt: str) -> str:
        return hashlib.sha256(prompt.encode()).hexdigest()


# Alias de compatibilidad: el router importa `RustEngine`. Se mantiene el nombre
# para no romper imports; renombrar es parte de la limpieza de la Fase 2.
RustEngine = LocalExecutor

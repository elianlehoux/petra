import os
import time
import uuid
import json
import hashlib
import logging
from datetime import datetime
from typing import Optional
import openai
from .models import TaskRequest, CompiledArtifact
from .validator import validate_script

logger = logging.getLogger(__name__)

# Reintentos de compilación con feedback del error de validación al LLM (Fase 3).
MAX_COMPILE_ATTEMPTS = 3

def detect_task_type(prompt: str) -> str:
    lower_prompt = prompt.lower()
    if "extract" in lower_prompt or "parse" in lower_prompt or "invoice" in lower_prompt or "email" in lower_prompt:
        return "extraction"
    elif "transform" in lower_prompt or "convert" in lower_prompt or "csv" in lower_prompt or "normalize" in lower_prompt:
        return "transformation"
    elif "scrape" in lower_prompt or "price" in lower_prompt or "html" in lower_prompt:
        return "scraping"
    elif "api" in lower_prompt or "pipeline" in lower_prompt or "fetch" in lower_prompt:
        return "api_workflow"
    else:
        return "code_generation"

def build_system_prompt(task_type: str) -> str:
    base = (
        "You are an expert AI Compiler. Write a PURE Python script that fulfills the user's request. "
        "The script MUST read JSON input from sys.stdin and write valid JSON output to sys.stdout. "
        "Use ONLY Python standard library modules (json, sys, re, math, datetime, urllib.parse, etc.). "
        "Do NOT import os, subprocess, socket, or requests. "
        "The script MUST be deterministic and self-contained. "
        "Format output as ```python <code here> ```."
    )
    if task_type == "extraction":
        base += " Focus on regex and text extraction into structured JSON key-value pairs."
    elif task_type == "transformation":
        base += " Focus on transforming data schemas or arrays into clean normalized JSON."
    elif task_type == "scraping":
        base += " Process raw HTML or text input to extract specific target fields using regex/string searching."
    elif task_type == "api_workflow":
        base += " Construct or transform payload structures for API workflows deterministically."
    return base

def get_demo_script(prompt: str, task_type: str) -> str:
    lower = prompt.lower()
    if "invoice" in lower or "email" in lower or task_type == "extraction":
        return (
            "import sys, json, re\n"
            "def main():\n"
            "    raw = sys.stdin.read()\n"
            "    data = json.loads(raw) if raw else {}\n"
            "    text = data.get('text', data.get('content', str(data)))\n"
            "    inv_match = re.search(r'INV-[0-9]+', text)\n"
            "    amt_match = re.search(r'\\$([0-9,]+\\.[0-9]{2})', text)\n"
            "    date_match = re.search(r'\\d{4}-\\d{2}-\\d{2}', text)\n"
            "    result = {\n"
            "        'invoice_id': inv_match.group(0) if inv_match else 'INV-UNKNOWN',\n"
            "        'amount': float(amt_match.group(1).replace(',', '')) if amt_match else 0.0,\n"
            "        'date': date_match.group(0) if date_match else '2026-01-01',\n"
            "        'status': 'parsed'\n"
            "    }\n"
            "    print(json.dumps(result))\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )
    elif "csv" in lower or "transform" in lower or task_type == "transformation":
        return (
            "import sys, json\n"
            "def main():\n"
            "    raw = sys.stdin.read()\n"
            "    data = json.loads(raw) if raw else {}\n"
            "    items = data.get('items', [])\n"
            "    transformed = []\n"
            "    for item in items:\n"
            "        transformed.append({\n"
            "            'id': item.get('id', '').strip().upper(),\n"
            "            'total': float(item.get('price', 0)) * int(item.get('qty', 1)),\n"
            "            'active': bool(item.get('active', True))\n"
            "        })\n"
            "    print(json.dumps({'transformed_count': len(transformed), 'items': transformed}))\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )
    else:
        return (
            "import sys, json\n"
            "def main():\n"
            "    raw = sys.stdin.read()\n"
            "    data = json.loads(raw) if raw else {}\n"
            "    result = {'status': 'processed', 'input_summary': str(data)[:50]}\n"
            "    print(json.dumps(result))\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )

def compile_task(request: TaskRequest, api_key: str, model: str, base_url: Optional[str] = None) -> CompiledArtifact:
    task_type = request.task_type or detect_task_type(request.prompt)
    prompt_hash = hashlib.sha256(request.prompt.encode()).hexdigest()

    artifact = CompiledArtifact(
        id=str(uuid.uuid4()),
        prompt_hash=prompt_hash,
        original_prompt=request.prompt,
        script_content="",
        task_type=task_type
    )

    # Modo demo solo si NO hay key real NI endpoint local.
    if (api_key == "demo" or not api_key) and not base_url:
        logger.info("Demo mode: Generating mock compiled artifact")
        artifact.script_content = get_demo_script(request.prompt, task_type)
        valid, validation_results = validate_script(
            artifact.script_content, request.input_data, request.expected_output, request.examples)
        artifact.validation_results = validation_results
        if not valid:
            raise ValueError(f"Compiled script failed validation: {validation_results[-1].message}")
        return artifact

    try:
        client = openai.Client(api_key=api_key or "local", base_url=base_url) if base_url \
            else openai.Client(api_key=api_key)
        messages = [
            {"role": "system", "content": build_system_prompt(task_type)},
            {"role": "user", "content": request.prompt},
        ]
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_latency_ms = 0.0
        script = ""
        validation_results = []

        # Loop de reintento: si la validación falla, se le devuelve el error al LLM
        # y se le pide corregir (hasta MAX_COMPILE_ATTEMPTS). Rigor sobre "un intento".
        for attempt in range(1, MAX_COMPILE_ATTEMPTS + 1):
            start = time.perf_counter()
            response = client.chat.completions.create(model=model, messages=messages, temperature=0.0)
            total_latency_ms += (time.perf_counter() - start) * 1000
            content = response.choices[0].message.content or ""
            script = content.split("```python")[1].split("```")[0].strip() if "```python" in content else content.strip()

            usage = getattr(response, "usage", None)
            total_prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            total_completion_tokens += getattr(usage, "completion_tokens", 0) or 0

            valid, validation_results = validate_script(
                script, request.input_data, request.expected_output, request.examples)
            if valid:
                break

            # Falló: feedback del error para el próximo intento.
            fail = validation_results[-1]
            logger.info(f"Compilación intento {attempt} falló en {fail.gate_name}: {fail.message}")
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content":
                f"El script falló el gate '{fail.gate_name}': {fail.message}. "
                f"Corregí el error y devolvé SOLO el código Python entre ```python ```."})

        artifact.script_content = script
        artifact.validation_results = validation_results
        artifact.metadata.update({
            "measured": True,
            "compile_model": model,
            "compile_prompt_tokens": total_prompt_tokens,      # suma de todos los intentos
            "compile_completion_tokens": total_completion_tokens,
            "compile_latency_ms": total_latency_ms,
            "compile_attempts": attempt,
        })
        if not (validation_results and all(r.passed for r in validation_results)):
            raise ValueError(
                f"Compiled script failed validation after {attempt} attempts: "
                f"{validation_results[-1].message if validation_results else 'sin resultados'}")
    except Exception as e:
        logger.error(f"Compilation failed: {e}")
        raise

    return artifact

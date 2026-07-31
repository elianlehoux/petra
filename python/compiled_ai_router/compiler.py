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
from . import pricing

logger = logging.getLogger(__name__)

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

def compile_task(request: TaskRequest, api_key: str, model: str) -> CompiledArtifact:
    task_type = request.task_type or detect_task_type(request.prompt)
    prompt_hash = hashlib.sha256(request.prompt.encode()).hexdigest()
    
    artifact = CompiledArtifact(
        id=str(uuid.uuid4()),
        prompt_hash=prompt_hash,
        original_prompt=request.prompt,
        script_content="",
        task_type=task_type
    )

    if api_key == "demo" or not api_key:
        logger.info("Demo mode: Generating mock compiled artifact")
        artifact.script_content = get_demo_script(request.prompt, task_type)
        valid, validation_results = validate_script(artifact.script_content, request.input_data, request.expected_output)
        artifact.validation_results = validation_results
        if not valid:
            raise ValueError(f"Compiled script failed validation: {validation_results[-1].message}")
        return artifact

    try:
        client = openai.Client(api_key=api_key)
        start = time.perf_counter()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": build_system_prompt(task_type)},
                {"role": "user", "content": request.prompt}
            ],
            temperature=0.0
        )
        compile_latency_ms = (time.perf_counter() - start) * 1000
        content = response.choices[0].message.content or ""
        if "```python" in content:
            script = content.split("```python")[1].split("```")[0].strip()
        else:
            script = content.strip()

        # Uso y costo REALES de la compilación (medidos, no estimados).
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        compile_cost = pricing.cost_usd(model, prompt_tokens, completion_tokens)
        artifact.metadata.update({
            "measured": True,
            "compile_model": model,
            "compile_prompt_tokens": prompt_tokens,
            "compile_completion_tokens": completion_tokens,
            "compile_cost_usd": compile_cost,
            "compile_latency_ms": compile_latency_ms,
        })

        artifact.script_content = script
        valid, validation_results = validate_script(artifact.script_content, request.input_data, request.expected_output)
        artifact.validation_results = validation_results
        if not valid:
            raise ValueError(f"Compiled script failed validation: {validation_results[-1].message}")
    except Exception as e:
        logger.error(f"Compilation failed: {e}")
        raise
        
    return artifact

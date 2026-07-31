import argparse
import asyncio
import json
import uvicorn
from .router import CompiledAIRouter
from .models import TaskRequest
from .config import settings
from .dashboard import generate_dashboard

def main():
    parser = argparse.ArgumentParser(description="Compiled AI Router CLI")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Route
    route_p = subparsers.add_parser("route", help="Route a request")
    route_p.add_argument("prompt", type=str)
    route_p.add_argument("--input", type=str, default="{}")
    
    # Compile
    compile_p = subparsers.add_parser("compile", help="Force compile")
    compile_p.add_argument("prompt", type=str)
    
    # Execute
    exec_p = subparsers.add_parser("execute", help="Execute artifact")
    exec_p.add_argument("id", type=str)
    exec_p.add_argument("--input", type=str, default="{}")
    
    # List
    subparsers.add_parser("list", help="List artifacts")
    
    # Metrics
    subparsers.add_parser("metrics", help="Show metrics dashboard")
    
    # Serve
    subparsers.add_parser("serve", help="Start REST API server")
    
    # Benchmark
    bench_p = subparsers.add_parser("benchmark", help="Run benchmark")
    bench_p.add_argument("--iterations", type=int, default=100)

    # Measure (Fase 1: números honestos con baseline real de LLM)
    measure_p = subparsers.add_parser("measure", help="Medir costo/latencia reales sobre un vertical")
    measure_p.add_argument("--iterations", type=int, default=50)
    measure_p.add_argument("--output", type=str, default="measurement.json")

    # Demo
    subparsers.add_parser("demo", help="Run built-in demo")
    
    args = parser.parse_args()
    router = CompiledAIRouter(settings)
    
    if args.command == "route":
        input_data = json.loads(args.input) if args.input else {}
        req = TaskRequest(prompt=args.prompt, input_data=input_data)
        resp = asyncio.run(router.route(req))
        print(resp.model_dump_json(indent=2))
        
    elif args.command == "compile":
        req = TaskRequest(prompt=args.prompt, force_compile=True)
        resp = asyncio.run(router.route(req))
        print(resp.model_dump_json(indent=2))
        
    elif args.command == "execute":
        if args.id not in router.artifacts:
            print("Artifact not found")
            return
        art = router.artifacts[args.id]
        input_data = json.loads(args.input) if args.input else {}
        out, dur, success = router.execute_artifact(art, input_data)
        print(json.dumps(out, indent=2))
        print(f"Duration: {dur:.2f}ms | Success: {success}")
        
    elif args.command == "list":
        print(f"Total compiled artifacts: {len(router.artifacts)}")
        for a in router.artifacts.values():
            print(f"  [{a.id[:8]}] {a.task_type:<15} | Executions: {a.execution_count:<4} | Prompt: {a.original_prompt[:45]}...")
            
    elif args.command == "metrics":
        print(generate_dashboard(router.get_metrics()))
        
    elif args.command == "serve":
        print(f"Starting Compiled AI Router API server on {settings.API_HOST}:{settings.API_PORT}...")
        uvicorn.run("compiled_ai_router.api:app", host=settings.API_HOST, port=settings.API_PORT)
        
    elif args.command == "demo" or args.command == "benchmark":
        asyncio.run(run_demo_benchmark(router, iterations=getattr(args, "iterations", 100)))

    elif args.command == "measure":
        asyncio.run(run_measurement(router, iterations=args.iterations, output=args.output))

    else:
        parser.print_help()

async def run_demo_benchmark(router: CompiledAIRouter, iterations: int = 100):
    print("🚀 Running Compiled AI Router Benchmark & Demo...\n")
    sample_prompts = [
        ("Parse invoice text to JSON", {"text": "Invoice INV-9821 for $1,450.50 dated 2026-03-15"}),
        ("Transform CSV items into structured array", {"items": [{"id": "a1", "price": 10, "qty": 2}]}),
        ("Extract user contact info", {"text": "Contact John Doe at john@example.com or 555-0199"}),
    ]
    
    # 1. First run (compilation)
    print("Step 1: First-time compilation of 3 tasks...")
    for prompt, inp in sample_prompts:
        resp = await router.route(TaskRequest(prompt=prompt, input_data=inp))
        print(f"  [{resp.route.upper()}] Latency: {resp.latency_ms:.2f}ms | ID: {resp.artifact_id[:8] if resp.artifact_id else 'N/A'}")
        
    # 2. Repeated runs (cache hits)
    print(f"\nStep 2: Executing {iterations} repeated requests via compiled cache...")
    for i in range(iterations):
        prompt, inp = sample_prompts[i % len(sample_prompts)]
        await router.route(TaskRequest(prompt=prompt, input_data=inp))
        
    print("\n" + generate_dashboard(router.get_metrics()))


async def run_measurement(router: CompiledAIRouter, iterations: int = 50, output: str = "measurement.json"):
    """Fase 1 — medición honesta sobre un vertical concreto (extracción de facturas).

    Paso A: establecer baseline REAL del LLM (force_passthrough → llamada real).
    Paso B: compilar una vez + ejecutar N cache hits.
    Paso C: volcar métricas medidas a JSON.

    Con API key/endpoint real, todos los números son medidos. En modo demo, quedan
    flageados como simulados (measured=False) y sirven solo para ver la forma del reporte.

    Corre siempre sobre un ARTIFACT_DIR temporal y limpio, para que runs previos no
    contaminen la medición ni ensucien el store real.
    """
    import json as _json
    import tempfile
    from .config import settings as _settings

    # Router aislado con store temporal (ignora el router pasado).
    tmp_dir = tempfile.mkdtemp(prefix="carouter_measure_")
    iso_settings = _settings.model_copy(update={"ARTIFACT_DIR": tmp_dir})
    router = CompiledAIRouter(iso_settings)

    real = router._has_real_key()
    print("🔬 MEDICIÓN — Compiled AI Router (Fase 1)\n")
    if not real:
        print("⚠️  Sin API key real (modo demo): los números serán SIMULADOS, no medidos.")
        print("    Para números reales: exportá OPENAI_API_KEY (tiene costo $ y sale a OpenAI).\n")
    else:
        print(f"✅ API key detectada. Modelo: {router.config.LLM_MODEL}. Llamadas reales al LLM.\n")

    # Vertical de prueba: extracción de facturas.
    task = "Extract invoice id, amount and date from the text into JSON"
    samples = [
        {"text": "Invoice INV-9821 for $1,450.50 dated 2026-03-15"},
        {"text": "INV-3310 total $89.00 on 2026-05-01"},
        {"text": "Billing INV-7777 amount $12,999.99 date 2026-06-30"},
    ]

    # Paso A: baseline real del LLM (una llamada passthrough por sample).
    print(f"Paso A: baseline LLM (passthrough real) sobre {len(samples)} inputs...")
    for inp in samples:
        await router.route(TaskRequest(prompt=task, input_data=inp, force_passthrough=True))

    # Paso B: compilar una vez + N cache hits.
    print(f"Paso B: compilar 1 vez + {iterations} ejecuciones cacheadas...")
    await router.route(TaskRequest(prompt=task, input_data=samples[0]))  # compila
    for i in range(iterations):
        await router.route(TaskRequest(prompt=task, input_data=samples[i % len(samples)]))

    metrics = router.get_metrics()
    print("\n" + generate_dashboard(metrics))

    # Paso C: volcar a JSON.
    payload = metrics.model_dump()
    payload["vertical"] = "invoice_extraction"
    payload["iterations"] = iterations
    with open(output, "w") as f:
        _json.dump(payload, f, indent=2)
    print(f"\n💾 Métricas guardadas en {output}")
    if not metrics.measured:
        print("⚠️  measured=False: estos números NO son una medición real.")


if __name__ == "__main__":
    main()

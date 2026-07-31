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

if __name__ == "__main__":
    main()

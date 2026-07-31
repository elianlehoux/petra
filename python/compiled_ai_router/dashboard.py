from .models import MetricsSummary

def generate_dashboard(metrics: MetricsSummary) -> str:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'
    
    total = metrics.total_requests
    compiled = metrics.compiled_hits
    compilations = metrics.compilations
    pass_ = metrics.passthroughs
    
    def draw_bar(val, m, width=30):
        if m == 0: return "░" * width
        filled = int((val / m) * width)
        return "█" * filled + "░" * (width - filled)

    RED = '\033[91m'
    max_req = max(compiled, compilations, pass_, 1)

    if metrics.measured:
        banner = f"{GREEN}✅ MEDIDO — números de llamadas reales al LLM{RESET}"
        llm_label = "Avg LLM Latency"
        speedup_label = "Speedup"
    else:
        banner = f"{RED}⚠️  SIMULADO — modo demo, sin API key. Números NO medidos.{RESET}"
        llm_label = "LLM Latency (supuesto)"
        speedup_label = "Speedup (no real)"

    be = metrics.break_even_executions
    be_str = f"{be:.1f} ejecuciones" if be is not None else "sin medir (falta baseline real)"

    dashboard = f"""
{CYAN}╔══════════════════════════════════════════════════════════════╗
║                COMPILED AI ROUTER DASHBOARD                  ║
╚══════════════════════════════════════════════════════════════╝{RESET}
{banner}

{YELLOW}📊 TRAFFIC SUMMARY{RESET}
Total Requests : {total}
Cache Hit Rate : {metrics.cache_hit_rate*100:.1f}%

{YELLOW}📈 EXECUTION ROUTES{RESET}
Compiled Hits  : [{GREEN}{draw_bar(compiled, max_req)}{RESET}] {compiled}
New Compiles   : [{CYAN}{draw_bar(compilations, max_req)}{RESET}] {compilations}
Passthroughs   : [{YELLOW}{draw_bar(pass_, max_req)}{RESET}] {pass_}
Recompiles(drift): {metrics.recompilations} (drift events: {metrics.drift_events})

{YELLOW}💰 SAVINGS{RESET}
Tokens Saved   : {metrics.total_tokens_saved:,}
Cost Saved     : ${metrics.total_cost_saved_usd:.4f}
Break-even     : {be_str}

{YELLOW}⚡ PERFORMANCE{RESET}
Avg Compiled Latency : {metrics.avg_compiled_latency_ms:.2f} ms
{llm_label:<20} : {metrics.avg_passthrough_latency_ms:.2f} ms
{speedup_label:<20} : {metrics.speedup_factor:.1f}x
"""
    return dashboard

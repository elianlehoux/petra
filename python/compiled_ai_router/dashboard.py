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

    max_req = max(compiled, compilations, pass_, 1)
    
    dashboard = f"""
{CYAN}╔══════════════════════════════════════════════════════════════╗
║                COMPILED AI ROUTER DASHBOARD                  ║
╚══════════════════════════════════════════════════════════════╝{RESET}

{YELLOW}📊 TRAFFIC SUMMARY{RESET}
Total Requests : {total}
Cache Hit Rate : {metrics.cache_hit_rate*100:.1f}%

{YELLOW}📈 EXECUTION ROUTES{RESET}
Compiled Hits  : [{GREEN}{draw_bar(compiled, max_req)}{RESET}] {compiled}
New Compiles   : [{CYAN}{draw_bar(compilations, max_req)}{RESET}] {compilations}
Passthroughs   : [{YELLOW}{draw_bar(pass_, max_req)}{RESET}] {pass_}

{YELLOW}💰 SAVINGS{RESET}
Tokens Saved   : {metrics.total_tokens_saved:,}
Cost Saved     : ${metrics.total_cost_saved_usd:.4f}

{YELLOW}⚡ PERFORMANCE{RESET}
Avg Compiled Latency : {metrics.avg_compiled_latency_ms:.2f} ms
Avg LLM Latency      : {metrics.avg_passthrough_latency_ms:.2f} ms
Estimated Speedup    : {metrics.speedup_factor:.1f}x
"""
    return dashboard

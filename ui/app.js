const API_BASE = "http://127.0.0.1:8080";

const templates = {
  invoice: {
    prompt: "Extract invoice number, total amount, and date into structured JSON",
    input: JSON.stringify({ text: "Invoice INV-2026-889 for $1,250.00 dated 2026-07-20" }, null, 2)
  },
  transform: {
    prompt: "Transform item array to normalized prices with calculated totals",
    input: JSON.stringify({ items: [{ id: "p101", price: 29.99, qty: 3 }, { id: "p102", price: 15.00, qty: 1 }] }, null, 2)
  },
  scrape: {
    prompt: "Extract product title and price from raw HTML text",
    input: JSON.stringify({ text: "<div class='product'><h1>MacBook Pro 16</h1><span class='price'>$2,499.00</span></div>" }, null, 2)
  },
  passthrough: {
    prompt: "What do you think about the future of AI compilers in 2030?",
    input: "{}"
  }
};

document.addEventListener("DOMContentLoaded", () => {
  fetchMetrics();
  fetchArtifacts();
  
  // Refresh stats every 5s
  setInterval(fetchMetrics, 5000);
});

function loadTemplate(key) {
  const tpl = templates[key];
  if (tpl) {
    document.getElementById("promptInput").value = tpl.prompt;
    document.getElementById("inputData").value = tpl.input;
  }
}

async function sendRouteRequest(forceCompile = false) {
  const prompt = document.getElementById("promptInput").value.trim();
  const inputStr = document.getElementById("inputData").value.trim();
  const consoleBox = document.getElementById("consoleOutput");
  
  if (!prompt) {
    alert("Please enter a prompt");
    return;
  }
  
  let inputData = {};
  try {
    inputData = inputStr ? JSON.parse(inputStr) : {};
  } catch (e) {
    alert("Invalid JSON in Input Data field: " + e.message);
    return;
  }
  
  consoleBox.innerHTML = `<span style="color: #9ca3af;">⚡ Routing request through Compiled AI Engine...</span>`;
  
  const payload = {
    prompt: prompt,
    input_data: inputData,
    force_compile: forceCompile
  };

  try {
    const start = performance.now();
    const res = await fetch(`${API_BASE}/route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    const duration = (performance.now() - start).toFixed(1);
    
    renderResponse(data, duration);
    fetchMetrics();
    fetchArtifacts();
  } catch (err) {
    // Demo fallback if local server is offline
    renderDemoFallback(payload, forceCompile);
  }
}

function renderResponse(data, clientDurationMs) {
  const consoleBox = document.getElementById("consoleOutput");
  const isCompiled = data.route === "compiled" || data.route === "recompiled";
  const badgeClass = data.route;
  
  let routeLabel = data.route.toUpperCase();
  if (data.route === "compiled") routeLabel = "⚡ CACHE HIT (COMPILED)";
  else if (data.route === "compile_new") routeLabel = "🔨 NEW COMPILED ARTIFACT";
  else if (data.route === "passthrough") routeLabel = "🔄 LLM PASSTHROUGH";

  consoleBox.innerHTML = `
    <div>
      <span class="route-badge ${badgeClass}">${routeLabel}</span>
      <span style="color: #9ca3af; margin-left: 10px;">Latency: <b>${data.latency_ms.toFixed(1)} ms</b></span>
    </div>
    
    <div style="margin-top: 8px; font-size: 0.8rem; color: #94a3b8;">
      Tokens Used: <b style="color: ${isCompiled ? '#10b981' : '#f59e0b'}">${data.tokens_used}</b> | 
      Tokens Saved: <b style="color: #10b981">${data.tokens_saved}</b> | 
      Cost Saved: <b style="color: #10b981">$${data.cost_saved_usd.toFixed(4)}</b>
    </div>

    <div style="margin-top: 12px; font-weight: 600; color: #f8fafc;">Output Data:</div>
    <pre style="color: #38bdf8; background: #0b1120; padding: 10px; border-radius: 6px; margin-top: 4px; overflow-x: auto;">${JSON.stringify(data.output, null, 2)}</pre>
  `;
}

function renderDemoFallback(payload, forceCompile) {
  const consoleBox = document.getElementById("consoleOutput");
  const isPassthrough = payload.prompt.toLowerCase().includes("think") || payload.prompt.toLowerCase().includes("chat");
  const route = forceCompile ? "compile_new" : (isPassthrough ? "passthrough" : "compiled");
  
  const mockResp = {
    request_id: "demo-" + Math.random().toString(36).substr(2, 9),
    route: route,
    output: {
      status: "success",
      extracted: payload.input_data.text ? { invoice: "INV-2026-889", total: 1250.00 } : payload.input_data,
      compiled_mode: !isPassthrough
    },
    latency_ms: isPassthrough ? 185.0 : 18.4,
    tokens_used: isPassthrough ? 450 : 0,
    tokens_saved: isPassthrough ? 0 : 450,
    cost_usd: isPassthrough ? 0.0025 : 0.0,
    cost_saved_usd: isPassthrough ? 0.0 : 0.0025
  };
  
  renderResponse(mockResp, mockResp.latency_ms);
}

async function fetchMetrics() {
  try {
    const res = await fetch(`${API_BASE}/metrics`);
    const m = await res.json();
    
    document.getElementById("mTotalReq").innerText = m.total_requests || 0;
    document.getElementById("mCacheHit").innerText = ((m.cache_hit_rate || 0) * 100).toFixed(1) + "%";
    document.getElementById("mTokensSaved").innerText = (m.total_tokens_saved || 0).toLocaleString();
    document.getElementById("mCostSaved").innerText = "$" + (m.total_cost_saved_usd || 0).toFixed(3);
  } catch (e) {
    // Keep UI responsive if server offline
  }
}

async function fetchArtifacts() {
  try {
    const res = await fetch(`${API_BASE}/artifacts`);
    const list = await res.json();
    renderArtifactsTable(list);
  } catch (e) {
    renderArtifactsTable([
      { id: "art-inv-01", task_type: "extraction", original_prompt: "Extract invoice number, total amount, and date", execution_count: 42, avg_execution_time_ms: 18.2 },
      { id: "art-csv-02", task_type: "transformation", original_prompt: "Transform item array to normalized prices", execution_count: 19, avg_execution_time_ms: 12.5 }
    ]);
  }
}

function renderArtifactsTable(artifacts) {
  const tbody = document.getElementById("artifactsBody");
  if (!artifacts || artifacts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No compiled artifacts yet. Run a request to compile one!</td></tr>`;
    return;
  }
  
  tbody.innerHTML = artifacts.map(a => `
    <tr>
      <td><code style="color: var(--accent-cyan);">${a.id.substring(0, 8)}</code></td>
      <td><span class="task-tag">${a.task_type}</span></td>
      <td style="max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${a.original_prompt}</td>
      <td><b>${a.execution_count}</b> execs</td>
      <td><span style="color: var(--accent-emerald); font-weight: 600;">${(a.avg_execution_time_ms || 15).toFixed(1)} ms</span></td>
    </tr>
  `).join('');
}

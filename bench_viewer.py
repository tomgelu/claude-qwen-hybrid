#!/usr/bin/env python3
"""
bench_viewer.py — local HTTP dashboard for benchmark_results.jsonl

Usage:
    python3 bench_viewer.py          # serves on http://localhost:8080
    python3 bench_viewer.py 9000     # custom port
"""

import json
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
RESULTS_FILE = Path(__file__).parent / "benchmark_results.jsonl"

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Benchmark Viewer</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0f0f13; color: #e2e2e8; min-height: 100vh; }
  h1 { font-size: 1.3rem; font-weight: 600; color: #a78bfa; }
  h2 { font-size: 1rem; font-weight: 600; color: #7dd3fc; margin-bottom: .75rem; }
  header { padding: 1.2rem 2rem; border-bottom: 1px solid #1e1e2e; display: flex; align-items: center; gap: 1rem; }
  header span { font-size: .8rem; color: #6b7280; }
  main { padding: 1.5rem 2rem; max-width: 1200px; }

  .cards { display: flex; gap: 1rem; margin-bottom: 1.8rem; flex-wrap: wrap; }
  .card { background: #16161f; border: 1px solid #1e1e2e; border-radius: 8px; padding: 1rem 1.4rem; min-width: 160px; }
  .card .val { font-size: 1.6rem; font-weight: 700; color: #a78bfa; }
  .card .lbl { font-size: .75rem; color: #6b7280; margin-top: .2rem; }

  section { background: #16161f; border: 1px solid #1e1e2e; border-radius: 8px; padding: 1.2rem 1.4rem; margin-bottom: 1.5rem; }

  table { width: 100%; border-collapse: collapse; font-size: .82rem; }
  th { text-align: left; color: #6b7280; font-weight: 500; padding: .4rem .7rem; border-bottom: 1px solid #1e1e2e; }
  td { padding: .4rem .7rem; border-bottom: 1px solid #12121a; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #1e1e2e; }
  .mono { font-family: monospace; }
  .badge { display: inline-block; padding: .15rem .5rem; border-radius: 4px; font-size: .72rem; font-weight: 600; }
  .badge.cloud { background: #1e3a5f; color: #7dd3fc; }
  .badge.local { background: #1a3a1a; color: #86efac; }
  .badge.pipeline { background: #3a1a3a; color: #d8b4fe; }
  .rtk-on  { color: #86efac; }
  .rtk-off { color: #f87171; }
  .delta-pos { color: #86efac; }
  .delta-neg { color: #f87171; }
  .delta-neu { color: #6b7280; }

  .charts { display: flex; gap: 1.2rem; flex-wrap: wrap; }
  .chart-wrap { flex: 1; min-width: 280px; background: #12121a; border-radius: 6px; padding: 1rem; }
  .chart-wrap h3 { font-size: .82rem; color: #6b7280; margin-bottom: .6rem; font-weight: 500; }

  .run-label { font-size: .72rem; color: #6b7280; font-family: monospace; }
  .empty { color: #4b5563; font-size: .85rem; padding: 1rem 0; }
</style>
</head>
<body>
<header>
  <h1>Benchmark Viewer</h1>
  <span id="last-updated"></span>
  <span style="flex:1"></span>
  <button onclick="load()" style="background:#1e1e2e;border:1px solid #2e2e3e;color:#e2e2e8;padding:.35rem .8rem;border-radius:6px;cursor:pointer;font-size:.8rem;">Refresh</button>
</header>
<main>
  <div class="cards" id="cards"></div>
  <section id="rtk-section">
    <h2>RTK Pipeline Comparison</h2>
    <div class="charts" id="rtk-charts"></div>
    <div style="margin-top:1.2rem">
      <table id="rtk-table"><thead><tr>
        <th>Run</th><th>Model</th><th>RTK</th>
        <th>Qwen in</th><th>Qwen out</th><th>Tool bytes</th><th>Time</th>
      </tr></thead><tbody id="rtk-body"></tbody></table>
    </div>
    <div id="rtk-savings" style="margin-top:1rem"></div>
  </section>
  <section>
    <h2>Chat Prompts</h2>
    <table><thead><tr>
      <th>Run</th><th>Prompt</th><th>Model</th><th>Type</th>
      <th>In</th><th>Out</th><th>Cache-R</th><th>Cost</th><th>ms</th>
    </tr></thead><tbody id="chat-body"></tbody></table>
  </section>
</main>
<script>
let charts = [];

function fmt(n) { return n == null ? '—' : Number(n).toLocaleString(); }
function fmtMs(s) { return s == null ? '—' : Math.round(s * 1000).toLocaleString() + ' ms'; }
function fmtCost(c) { return c ? '$' + Number(c).toFixed(4) : '—'; }
function delta(a, b) {
  if (a == null || b == null || a === 0) return '';
  const d = b - a, pct = d / a * 100;
  const cls = d < 0 ? 'delta-pos' : d > 0 ? 'delta-neg' : 'delta-neu';
  const sign = d < 0 ? '▼' : d > 0 ? '▲' : '';
  return `<span class="${cls}">${sign}${Math.abs(pct).toFixed(1)}%</span>`;
}

async function load() {
  const res = await fetch('/data');
  const rows = await res.json();
  document.getElementById('last-updated').textContent =
    'Last refreshed: ' + new Date().toLocaleTimeString();
  render(rows);
}

function render(rows) {
  const pipeline = rows.filter(r => r.model_type === 'pipeline' && !r.error);
  const chat = rows.filter(r => r.model_type !== 'pipeline');

  // Cards
  const runs = [...new Set(rows.map(r => r.run_id))];
  const models = [...new Set(rows.map(r => r.model))];
  document.getElementById('cards').innerHTML = [
    { val: runs.length, lbl: 'Total runs' },
    { val: models.length, lbl: 'Models' },
    { val: pipeline.length / 2 | 0, lbl: 'RTK pairs' },
    { val: chat.filter(r => !r.error).length, lbl: 'Chat samples' },
  ].map(c => `<div class="card"><div class="val">${c.val}</div><div class="lbl">${c.lbl}</div></div>`).join('');

  renderRtk(pipeline);
  renderChat(chat);
}

function renderRtk(rows) {
  // Pair by run_id
  const pairs = {};
  for (const r of rows) {
    pairs[r.run_id] = pairs[r.run_id] || {};
    pairs[r.run_id][r.use_rtk ? 'on' : 'off'] = r;
  }
  const pairList = Object.entries(pairs).filter(([, p]) => p.on && p.off);

  // Table
  const tbody = document.getElementById('rtk-body');
  tbody.innerHTML = '';
  for (const r of rows) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="run-label">${r.run_id}</td>
      <td class="mono" style="font-size:.78rem">${r.model}</td>
      <td>${r.use_rtk ? '<span class="rtk-on">✓ on</span>' : '<span class="rtk-off">✗ off</span>'}</td>
      <td>${fmt(r.input_tokens)}</td>
      <td>${fmt(r.output_tokens)}</td>
      <td>${fmt(r.tool_bytes)}</td>
      <td>${Math.round(r.latency_s)}s</td>`;
    tbody.appendChild(tr);
  }
  if (!rows.length) tbody.innerHTML = '<tr><td colspan="7" class="empty">No pipeline runs yet — run python3 benchmark.py</td></tr>';

  // Savings table
  const sDiv = document.getElementById('rtk-savings');
  if (pairList.length) {
    const savingsRows = pairList.map(([rid, p]) => {
      const inD  = p.off.input_tokens  - p.on.input_tokens;
      const outD = p.off.output_tokens - p.on.output_tokens;
      const tbD  = (p.off.tool_bytes || 0) - (p.on.tool_bytes || 0);
      return `<tr>
        <td class="run-label">${rid}</td>
        <td>${delta(p.off.input_tokens,  p.on.input_tokens)  || fmt(inD)}</td>
        <td>${delta(p.off.output_tokens, p.on.output_tokens) || fmt(outD)}</td>
        <td>${delta(p.off.tool_bytes,    p.on.tool_bytes)    || fmt(tbD)}</td>
      </tr>`;
    }).join('');
    sDiv.innerHTML = `<h3 style="font-size:.82rem;color:#6b7280;margin-bottom:.5rem">Savings (no-RTK → RTK)</h3>
      <table><thead><tr><th>Run</th><th>Qwen input Δ</th><th>Qwen output Δ</th><th>Tool bytes Δ</th></tr></thead>
      <tbody>${savingsRows}</tbody></table>`;
  } else {
    sDiv.innerHTML = '';
  }

  // Charts — destroy old
  charts.forEach(c => c.destroy());
  charts = [];
  const chartsDiv = document.getElementById('rtk-charts');
  chartsDiv.innerHTML = '';

  if (!pairList.length) return;

  const metrics = [
    { key: 'input_tokens',  label: 'Qwen Input Tokens' },
    { key: 'output_tokens', label: 'Qwen Output Tokens' },
    { key: 'tool_bytes',    label: 'Tool Response Bytes' },
  ];

  for (const m of metrics) {
    const wrap = document.createElement('div');
    wrap.className = 'chart-wrap';
    wrap.innerHTML = `<h3>${m.label}</h3><canvas></canvas>`;
    chartsDiv.appendChild(wrap);
    const canvas = wrap.querySelector('canvas');

    const labels = pairList.map(([rid]) => rid.replace(/^(\d{4})(\d{2})(\d{2})_/, '$1-$2-$3 '));
    const offData = pairList.map(([, p]) => p.off[m.key] || 0);
    const onData  = pairList.map(([, p]) => p.on[m.key]  || 0);

    charts.push(new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: 'No RTK', data: offData, backgroundColor: 'rgba(248,113,113,.7)', borderRadius: 4 },
          { label: 'RTK on', data: onData,  backgroundColor: 'rgba(134,239,172,.7)', borderRadius: 4 },
        ]
      },
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: '#9ca3af', font: { size: 11 } } } },
        scales: {
          x: { ticks: { color: '#6b7280', font: { size: 10 } }, grid: { color: '#1e1e2e' } },
          y: { ticks: { color: '#6b7280', font: { size: 10 } }, grid: { color: '#1e1e2e' } },
        }
      }
    }));
  }
}

function renderChat(rows) {
  const tbody = document.getElementById('chat-body');
  tbody.innerHTML = '';
  const sorted = [...rows].sort((a, b) => b.run_id.localeCompare(a.run_id));
  for (const r of sorted) {
    const tr = document.createElement('tr');
    if (r.error) {
      tr.innerHTML = `<td class="run-label">${r.run_id}</td><td>${r.prompt_id}</td>
        <td class="mono" style="font-size:.78rem">${r.model}</td>
        <td><span class="badge ${r.model_type}">${r.model_type}</span></td>
        <td colspan="5" style="color:#f87171">ERROR: ${r.error}</td>`;
    } else {
      tr.innerHTML = `
        <td class="run-label">${r.run_id}</td>
        <td>${r.prompt_id}</td>
        <td class="mono" style="font-size:.78rem">${r.model}</td>
        <td><span class="badge ${r.model_type}">${r.model_type}</span></td>
        <td>${fmt(r.input_tokens)}</td>
        <td>${fmt(r.output_tokens)}</td>
        <td>${fmt(r.cache_read)}</td>
        <td>${fmtCost(r.cost_usd)}</td>
        <td>${fmtMs(r.latency_s)}</td>`;
    }
    tbody.appendChild(tr);
  }
  if (!rows.length) tbody.innerHTML = '<tr><td colspan="9" class="empty">No chat prompt runs yet.</td></tr>';
}

load();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress request logs

    def do_GET(self):
        if self.path == "/data":
            rows = []
            if RESULTS_FILE.exists():
                for line in RESULTS_FILE.read_text().splitlines():
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            body = json.dumps(rows).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        elif self.path in ("/", "/index.html"):
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    host = "0.0.0.0" if os.environ.get("DOCKER", "") else "127.0.0.1"
    HTTPServer.allow_reuse_address = True
    server = HTTPServer((host, PORT), Handler)
    if host == "127.0.0.1":
        print(f"Benchmark viewer → http://localhost:{PORT}")
    print(f"Benchmark viewer → http://localhost:{PORT}")
    print(f"  (listening on {host}:{PORT})")
    print("Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

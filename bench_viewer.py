#!/usr/bin/env python3
"""
bench_viewer.py — local HTTP dashboard for benchmark_results.db

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
DB_FILE = Path(__file__).parent / "benchmark_results.db"

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
  <section id="bench-section">
    <h2>Bench Runs (A/B/C Quality)</h2>
    <div class="cards" id="bench-cards"></div>
    <div class="charts" id="bench-charts"></div>
    <div style="margin-top:1.2rem">
      <table id="bench-table">
        <thead><tr>
          <th>Metric</th>
          <th id="bench-col-a">A</th>
          <th id="bench-col-b">B</th>
          <th id="bench-col-c" style="display:none">C</th>
        </tr></thead>
        <tbody id="bench-body"></tbody>
      </table>
    </div>
    <div style="display:flex;align-items:center;gap:.75rem;margin:.75rem 0 .5rem">
      <button id="compare-btn" disabled onclick="runComparison()"
        style="background:#1e1e2e;border:1px solid #2e2e3e;color:#e2e2e8;padding:.35rem .9rem;border-radius:6px;cursor:pointer;font-size:.8rem;opacity:.5"
      >Compare selected</button>
      <span id="compare-hint" style="font-size:.78rem;color:#6b7280">Select 2+ runs to compare</span>
    </div>
    <div id="bench-compare" style="display:none;margin-bottom:1.2rem">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.6rem">
        <h2 style="font-size:.9rem;color:#6b7280;margin:0">Run Comparison</h2>
        <button onclick="clearComparison()"
          style="background:#1e1e2e;border:1px solid #2e2e3e;color:#9ca3af;padding:.25rem .7rem;border-radius:6px;cursor:pointer;font-size:.75rem"
        >Clear</button>
      </div>
      <table id="compare-table" style="width:100%;border-collapse:collapse;font-size:.82rem">
        <thead><tr id="compare-head"></tr></thead>
        <tbody id="compare-body"></tbody>
      </table>
    </div>
    <div style="margin-top:1.5rem">
      <h2 style="font-size:.9rem;color:#6b7280;margin-bottom:.6rem">Run History</h2>
      <table>
        <thead><tr>
          <th style="width:2rem"><input type="checkbox" id="check-all" onchange="toggleAllChecks(this)" title="Select all"></th>
          <th>Run ID</th><th>Task</th><th>A tests</th><th>B tests</th><th>C tests</th><th>RTK saving</th>
        </tr></thead>
        <tbody id="bench-history"></tbody>
      </table>
    </div>
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
let benchGroups = {};

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

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

function qCell(val, base) {
  const num = fmt(val);
  if (!base || val === base) return num;
  const d = val - base, pct = d / base * 100;
  const cls = d < 0 ? 'delta-pos' : 'delta-neg';
  return `${num} <span class="${cls}">${d < 0 ? '▼' : '▲'}${Math.abs(pct).toFixed(1)}%</span>`;
}

function qQual(val, base, higherIsBetter) {
  const num = fmt(val);
  if (!base || val === base) return num;
  const d = val - base;
  const improved = higherIsBetter ? d > 0 : d < 0;
  const cls = improved ? 'delta-pos' : 'delta-neg';
  return `${num} <span class="${cls}">${d > 0 ? '▲' : '▼'}${Math.abs(d)}</span>`;
}

const ROWS = [
  ['Token Efficiency', null, null],
  ['Qwen input tokens',    'qwen_in',         'token'],
  ['Qwen output tokens',   'qwen_out',        'token'],
  ['Tool resp bytes',      'tool_bytes',      'token'],
  ['Claude input tokens',  'claude_in',       'token'],
  ['Claude output tokens', 'claude_out',      'token'],
  ['Output Quality', null, null],
  ['Steps completed',      'steps_completed', 'qual-high'],
  ['Tests passed',         'tests_passed',    'qual-high'],
  ['Tests failed',         'tests_failed',    'qual-low'],
  ['Run Info', null, null],
  ['Wall time (s)',         'wall_time_s',     'token'],
];

async function load() {
  const res = await fetch('/data');
  const rows = await res.json();
  document.getElementById('last-updated').textContent =
    'Last refreshed: ' + new Date().toLocaleTimeString();
  render(rows);
}

function render(rows) {
  const pipeline  = rows.filter(r => r.model_type === 'pipeline' && !r.error);
  const chat      = rows.filter(r => r.model_type !== 'pipeline' && r.model_type !== 'bench_run');
  const benchRuns = rows.filter(r => r.model_type === 'bench_run');

  // Cards
  const runs   = [...new Set(rows.map(r => r.run_id))];
  const models = [...new Set(rows.map(r => r.model))];
  document.getElementById('cards').innerHTML = [
    { val: runs.length,                        lbl: 'Total runs' },
    { val: models.length,                      lbl: 'Models' },
    { val: pipeline.length / 2 | 0,           lbl: 'RTK pairs' },
    { val: chat.filter(r => !r.error).length,  lbl: 'Chat samples' },
  ].map(c => `<div class="card"><div class="val">${c.val}</div><div class="lbl">${c.lbl}</div></div>`).join('');

  renderRtk(pipeline);
  renderBenchRuns(benchRuns);
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

function renderBenchRuns(rows) {
  // Group rows by run_id — each group is one A/B or A/B/C comparison set
  benchGroups = {};
  for (const r of rows) {
    if (!benchGroups[r.run_id]) benchGroups[r.run_id] = [];
    benchGroups[r.run_id].push(r);
  }
  const sortedIds = Object.keys(benchGroups).sort().reverse();

  if (!sortedIds.length) {
    document.getElementById('bench-cards').innerHTML =
      '<p class="empty">No bench runs yet — run: python3 bench.py "your task"</p>';
    return;
  }

  // Summary cards from most recent group
  const latest = benchGroups[sortedIds[0]];
  const a = latest.find(r => r.label.startsWith('A')) || {};
  const b = latest.find(r => r.label.startsWith('B')) || {};
  const c = latest.find(r => r.label.startsWith('C'));

  const rtkSaving = a.qwen_in && b.qwen_in
    ? Math.round((a.qwen_in - b.qwen_in) / a.qwen_in * 100) + '%'
    : '—';
  const bestTests = Math.max(a.tests_passed || 0, b.tests_passed || 0, c ? (c.tests_passed || 0) : 0);
  const phasesCost = c ? fmt(c.claude_in) + ' tokens' : '—';

  document.getElementById('bench-cards').innerHTML = [
    { val: sortedIds.length,  lbl: 'Bench run sets' },
    { val: rtkSaving,         lbl: 'RTK token saving (latest)' },
    { val: bestTests + '/' + (a.tests_passed != null ? (a.tests_passed + a.tests_failed) : '?'), lbl: 'Best test score' },
    { val: phasesCost,        lbl: 'Phases Claude cost' },
  ].map(card => `<div class="card"><div class="val">${card.val}</div><div class="lbl">${card.lbl}</div></div>`).join('');

  // Show/hide C column
  const hasC = !!c;
  document.getElementById('bench-col-c').style.display = hasC ? '' : 'none';
  if (a.label) document.getElementById('bench-col-a').textContent = a.label;
  if (b.label) document.getElementById('bench-col-b').textContent = b.label;
  if (c)       document.getElementById('bench-col-c').textContent = c.label;

  const tbody = document.getElementById('bench-body');
  tbody.innerHTML = '';
  for (const [label, key, type] of ROWS) {
    if (!key) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td colspan="4" style="background:#12121a;color:#6b7280;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;padding:.3rem .7rem">${label}</td>`;
      tbody.appendChild(tr);
      continue;
    }
    const tr = document.createElement('tr');
    const aVal = a[key] ?? 0, bVal = b[key] ?? 0, cVal = c ? (c[key] ?? 0) : null;
    let bCell, cCell;
    if (type === 'token') {
      bCell = qCell(bVal, aVal);
      cCell = cVal != null ? qCell(cVal, aVal) : '—';
    } else if (type === 'qual-high') {
      bCell = qQual(bVal, aVal, true);
      cCell = cVal != null ? qQual(cVal, aVal, true) : '—';
    } else {
      bCell = qQual(bVal, aVal, false);
      cCell = cVal != null ? qQual(cVal, aVal, false) : '—';
    }
    tr.innerHTML = `
      <td style="padding:.4rem .7rem">${label}</td>
      <td style="text-align:right;padding:.4rem .7rem;font-family:monospace">${fmt(aVal)}</td>
      <td style="text-align:right;padding:.4rem .7rem;font-family:monospace">${bCell}</td>
      <td style="text-align:right;padding:.4rem .7rem;font-family:monospace;display:${hasC ? '' : 'none'}">${cCell}</td>`;
    tbody.appendChild(tr);
  }

  // Charts
  charts.forEach(ch => ch.destroy()); charts = [];
  const chartsDiv = document.getElementById('bench-charts');
  chartsDiv.innerHTML = '';

  const chartDefs = [
    { key: 'qwen_in',      label: 'Qwen Input Tokens',  colors: ['rgba(248,113,113,.7)', 'rgba(134,239,172,.7)', 'rgba(167,139,250,.7)'] },
    { key: 'tests_passed', label: 'Tests Passed',        colors: ['rgba(248,113,113,.7)', 'rgba(134,239,172,.7)', 'rgba(167,139,250,.7)'] },
  ];

  for (const def of chartDefs) {
    const wrap = document.createElement('div');
    wrap.className = 'chart-wrap';
    wrap.innerHTML = `<h3>${def.label}</h3><canvas></canvas>`;
    chartsDiv.appendChild(wrap);
    const labels = sortedIds.map(id => id.replace(/^(\d{4})(\d{2})(\d{2})_/, '$1-$2-$3 '));
    const datasets = ['A', 'B', 'C'].map((letter, i) => ({
      label: letter,
      data: sortedIds.map(id => {
        const run = benchGroups[id].find(r => r.label.startsWith(letter));
        return run ? (run[def.key] || 0) : 0;
      }),
      backgroundColor: def.colors[i],
      borderRadius: 4,
    })).filter((_, i) => i < 2 || hasC);
    charts.push(new Chart(wrap.querySelector('canvas'), {
      type: 'bar',
      data: { labels, datasets },
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

  // History table
  const histBody = document.getElementById('bench-history');
  histBody.innerHTML = '';
  for (const rid of sortedIds) {
    const grp = benchGroups[rid];
    const ra = grp.find(r => r.label.startsWith('A')) || {};
    const rb = grp.find(r => r.label.startsWith('B')) || {};
    const rc = grp.find(r => r.label.startsWith('C'));
    const saving = ra.qwen_in && rb.qwen_in
      ? '<span class="delta-pos">▼' + Math.round((ra.qwen_in - rb.qwen_in) / ra.qwen_in * 100) + '%</span>'
      : '—';
    const raw = ra.task || rb.task || '';
    const taskSnip = raw.length > 50 ? raw.slice(0, 50) + '…' : raw;
    const testCell = (t) => t == null ? '—'
      : t.tests_failed === 0
        ? `<span class="delta-pos">${t.tests_passed}/${t.tests_passed + t.tests_failed} ✓</span>`
        : `<span class="delta-neg">${t.tests_passed}/${t.tests_passed + t.tests_failed} ✗</span>`;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="text-align:center"><input type="checkbox" class="run-check" data-run-id="${esc(rid)}" onchange="onRunCheckChange()"></td>
      <td class="run-label">${rid}</td>
      <td style="font-size:.75rem;color:#9ca3af">${taskSnip}</td>
      <td>${testCell(ra)}</td>
      <td>${testCell(rb)}</td>
      <td>${testCell(rc)}</td>
      <td>${saving}</td>`;
    histBody.appendChild(tr);
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

function onRunCheckChange() {
  const checked = [...document.querySelectorAll('.run-check:checked')];
  const runIds = [...new Set(checked.map(c => c.dataset.runId))];
  const btn = document.getElementById('compare-btn');
  const hint = document.getElementById('compare-hint');
  const enough = runIds.length >= 2;
  btn.disabled = !enough;
  btn.style.opacity = enough ? '1' : '.5';
  btn.style.cursor = enough ? 'pointer' : 'default';
  btn.textContent = enough ? `Compare ${runIds.length} runs` : 'Compare selected';
  hint.textContent = enough ? '' : runIds.length === 1 ? 'Select 1 more run' : 'Select 2+ runs to compare';
}

function toggleAllChecks(masterCb) {
  document.querySelectorAll('.run-check').forEach(cb => { cb.checked = masterCb.checked; });
  onRunCheckChange();
}

function clearComparison() {
  document.querySelectorAll('.run-check').forEach(cb => { cb.checked = false; });
  const master = document.getElementById('check-all');
  if (master) master.checked = false;
  document.getElementById('compare-btn').disabled = true;
  document.getElementById('compare-btn').style.opacity = '.5';
  document.getElementById('compare-btn').style.cursor = 'default';
  document.getElementById('compare-btn').textContent = 'Compare selected';
  document.getElementById('compare-hint').textContent = 'Select 2+ runs to compare';
  document.getElementById('bench-compare').style.display = 'none';
}

function runComparison() {
  const checked = [...document.querySelectorAll('.run-check:checked')];
  const runIds = [...new Set(checked.map(c => c.dataset.runId))];
  if (runIds.length < 2) return;
  if (Object.keys(benchGroups).length === 0) return;

  const panel = document.getElementById('bench-compare');
  panel.style.display = '';

  const runData = runIds.map(rid => {
    const grp = benchGroups[rid] || [];
    return grp.find(r => r.label && r.label.startsWith('A')) || grp[0] || {};
  });

  const headRow = document.getElementById('compare-head');
  headRow.innerHTML = '<th style="text-align:left;padding:.4rem .7rem;color:#6b7280;font-weight:500">Metric</th>' +
    runIds.map((rid, i) => {
      const rd = runData[i];
      const task = (rd.task || '').slice(0, 40);
      const isBase = i === 0 ? ' <span style="color:#a78bfa;font-size:.68rem">baseline</span>' : '';
      return `<th style="text-align:right;padding:.4rem .7rem;color:#6b7280;font-weight:500">` +
             `<span style="font-family:monospace;font-size:.75rem">${esc(rid)}</span>${isBase}<br>` +
             `<span style="color:#4b5563;font-size:.68rem">${esc(task)}</span></th>`;
    }).join('');

  const tbody = document.getElementById('compare-body');
  tbody.innerHTML = '';
  const baseline = runData[0];

  for (const [label, key, type] of ROWS) {
    if (!key) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td colspan="${runIds.length + 1}" style="background:#12121a;color:#6b7280;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;padding:.3rem .7rem">${label}</td>`;
      tbody.appendChild(tr);
      continue;
    }
    const tr = document.createElement('tr');
    const baseVal = baseline[key] ?? 0;
    const cells = runData.map((rd, i) => {
      const val = rd[key] ?? 0;
      let cell;
      if (i === 0) {
        cell = fmt(val);
      } else if (type === 'token') {
        cell = qCell(val, baseVal);
      } else if (type === 'qual-high') {
        cell = qQual(val, baseVal, true);
      } else {
        cell = qQual(val, baseVal, false);
      }
      return `<td style="text-align:right;padding:.4rem .7rem;font-family:monospace;border-bottom:1px solid #12121a">${cell}</td>`;
    }).join('');
    tr.innerHTML = `<td style="padding:.4rem .7rem;border-bottom:1px solid #12121a">${label}</td>${cells}`;
    tbody.appendChild(tr);
  }
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
            if DB_FILE.exists():
                import sqlite3 as _sq
                conn = None
                try:
                    conn = _sq.connect(str(DB_FILE))
                    conn.row_factory = _sq.Row
                    for r in conn.execute(
                        "SELECT *, 'bench_run' AS model_type FROM bench_runs ORDER BY created_at"
                    ):
                        rows.append(dict(r))
                except _sq.OperationalError:
                    pass   # table doesn't exist yet
                finally:
                    if conn:
                        conn.close()
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

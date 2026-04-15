const CRITERIA = [
  { label: "Nausée / Vomissements",    max: 7 },
  { label: "Tremblements",             max: 7 },
  { label: "Sueurs paroxystiques",     max: 7 },
  { label: "Anxiété",                  max: 7 },
  { label: "Agitation",               max: 7 },
  { label: "Troubles tactiles",        max: 7 },
  { label: "Troubles auditifs",        max: 7 },
  { label: "Troubles visuels",         max: 7 },
  { label: "Céphalées",               max: 7 },
  { label: "Orientation / Conscience", max: 4 },
];

// Current score for each criterion (index matches CRITERIA)
const scores = new Array(CRITERIA.length).fill(0);

function getSeverity(total) {
  if (total <= 7)  return { label: "Sevrage léger",  cls: "badge-leger" };
  if (total <= 15) return { label: "Sevrage modéré", cls: "badge-modere" };
  return                  { label: "Sevrage sévère", cls: "badge-severe" };
}

function updateSummary() {
  const total = scores.reduce((a, b) => a + b, 0);
  document.getElementById("total-display").textContent = total;
  const { label, cls } = getSeverity(total);
  const badge = document.getElementById("severity-badge");
  badge.textContent = label;
  badge.className = "badge " + cls;
}

function buildCriteria() {
  const container = document.getElementById("criteria-list");
  CRITERIA.forEach((criterion, i) => {
    const row = document.createElement("div");
    row.className = "criterion-row";

    const labelEl = document.createElement("div");
    labelEl.className = "criterion-label";
    labelEl.textContent = (i + 1) + ". " + criterion.label;
    row.appendChild(labelEl);

    const btnGroup = document.createElement("div");
    btnGroup.className = "btn-group";

    for (let v = 0; v <= criterion.max; v++) {
      const btn = document.createElement("button");
      btn.className = "score-btn" + (v === 0 ? " selected" : "");
      btn.textContent = v;
      btn.setAttribute("aria-label", criterion.label + ": " + v);
      btn.addEventListener("click", () => {
        scores[i] = v;
        btnGroup.querySelectorAll(".score-btn").forEach((b, idx) => {
          b.classList.toggle("selected", idx === v);
        });
        updateSummary();
      });
      btnGroup.appendChild(btn);
    }

    row.appendChild(btnGroup);
    container.appendChild(row);
  });
}

function resetForm() {
  scores.fill(0);
  document.querySelectorAll(".btn-group").forEach(group => {
    group.querySelectorAll(".score-btn").forEach((btn, idx) => {
      btn.classList.toggle("selected", idx === 0);
    });
  });
  updateSummary();
}

function showError() {
  const banner = document.getElementById("error-banner");
  banner.classList.remove("hidden");
  setTimeout(() => banner.classList.add("hidden"), 5000);
}

function prependHistoryRow(row) {
  const tbody = document.getElementById("history-body");
  document.getElementById("history-empty").classList.add("hidden");
  const tr = document.createElement("tr");
  const sev = getSeverity(row.total);
  tr.innerHTML =
    "<td>" + row.timestamp + "</td>" +
    "<td>" + row.total + "</td>" +
    "<td><span class=\"badge " + sev.cls + "\">" + row.severity + "</span></td>";
  tbody.prepend(tr);
}

async function saveAssessment() {
  const total = scores.reduce((a, b) => a + b, 0);
  const { label: severity } = getSeverity(total);
  try {
    const res = await fetch("/api/assessments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scores: [...scores], total, severity }),
    });
    if (!res.ok) throw new Error("Server error");
    const now = new Date();
    const timestamp = now.toLocaleString("fr-FR");
    prependHistoryRow({ timestamp, total, severity });
    resetForm();
  } catch (_) {
    showError();
  }
}

async function loadHistory() {
  try {
    const res = await fetch("/api/assessments");
    if (!res.ok) return;
    const rows = await res.json();
    const tbody = document.getElementById("history-body");
    if (rows.length === 0) {
      document.getElementById("history-empty").classList.remove("hidden");
      return;
    }
    rows.forEach(row => {
      const sev = getSeverity(row.total);
      const tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + row.timestamp + "</td>" +
        "<td>" + row.total + "</td>" +
        "<td><span class=\"badge " + sev.cls + "\">" + row.severity + "</span></td>";
      tbody.appendChild(tr);
    });
  } catch (_) {
    // History load failure is non-fatal
  }
}

document.getElementById("history-toggle").addEventListener("click", () => {
  const panel = document.getElementById("history-panel");
  const arrow = document.getElementById("toggle-arrow");
  const isHidden = panel.classList.toggle("hidden");
  arrow.innerHTML = isHidden ? "&#9660;" : "&#9650;";
});

document.getElementById("save-btn").addEventListener("click", saveAssessment);

buildCriteria();
updateSummary();
loadHistory();

const analyticsEl = document.getElementById("analytics");
const rubricListEl = document.getElementById("rubricList");
const titleEl = document.getElementById("rubricTitle");
const criteriaEl = document.getElementById("rubricCriteria");
const msgEl = document.getElementById("msg");
const createBtn = document.getElementById("createRubricBtn");
console.log("admin_rubrics.js loaded");

function escapeHtml(str) {
  return str
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadAnalytics() {
  analyticsEl.innerHTML = "<li>Loading...</li>";
  const res = await fetch("/api/admin/analytics");
  if (!res.ok) {
    analyticsEl.innerHTML = "<li>Failed to load analytics</li>";
    return;
  }
  const a = await res.json();
  analyticsEl.innerHTML = `
    <li><strong>Total users:</strong> ${a.users_count}</li>
    <li><strong>Total submissions:</strong> ${a.submissions_count}</li>
    <li><strong>Top rubric:</strong> ${a.top_rubric ? escapeHtml(a.top_rubric.title) + " (" + a.top_rubric.count + ")" : "—"}</li>
  `;
}

async function loadRubrics() {
  rubricListEl.innerHTML = "<li>Loading...</li>";
  const res = await fetch("/api/admin/rubrics");
  if (!res.ok) {
    rubricListEl.innerHTML = "<li>Failed to load rubrics</li>";
    return;
  }
  const data = await res.json();
  rubricListEl.innerHTML = "";
  data.rubrics.forEach(r => {
    const li = document.createElement("li");
    li.textContent = `${r.id} — ${r.title}`;
    rubricListEl.appendChild(li);
  });
}

function parseCriteriaLines(raw) {
  const lines = raw.split("\n").map(x => x.trim()).filter(Boolean);
  return lines.map(line => {
    const parts = line.split("|").map(x => x.trim());
    return { name: parts[0] || "", description: parts.slice(1).join(" | ") || "" };
  });
}

async function createRubric() {
  msgEl.textContent = "Creating...";
  createBtn.disabled = true;

  const title = titleEl.value.trim();
  const criteria = parseCriteriaLines(criteriaEl.value);

  const res = await fetch("/api/admin/rubrics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, criteria })
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    msgEl.textContent = data.detail || "Failed to create rubric";
    createBtn.disabled = false;
    return;
  }

  msgEl.textContent = "Rubric created successfully.";
  titleEl.value = "";
  criteriaEl.value = "";

  await loadRubrics();
  await loadAnalytics();

  createBtn.disabled = false;
}

createBtn.addEventListener("click", createRubric);

loadAnalytics();
loadRubrics();

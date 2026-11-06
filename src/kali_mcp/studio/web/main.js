// Playbook Studio bootstrap (Phase 5). Minimal static SPA; API client targets /api/*.
const API = "/api";

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

function render(html) {
  document.getElementById("view").innerHTML = html;
}

async function viewPlaybooks() {
  try {
    const data = await api("/playbooks");
    const items = (data.playbooks || data || []).map(
      (p) => `<li>${p.playbook_id || p.id || p.name}</li>`
    );
    render(`<h2>Playbooks</h2><ul>${items.join("")}</ul>`);
  } catch (e) {
    render(`<p>Error: ${e.message}</p>`);
  }
}

window.addEventListener("hashchange", route);
function route() {
  const hash = location.hash || "#/playbooks";
  if (hash.startsWith("#/playbooks")) viewPlaybooks();
  else render("<p>Select a section.</p>");
}
route();

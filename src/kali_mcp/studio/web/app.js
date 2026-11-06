const API = window.API || "/api";

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = body?.error?.message || body?.error || res.statusText;
    throw new Error(`API ${res.status}: ${msg}`);
  }
  return body?.data ?? body;
}

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return [...document.querySelectorAll(sel)]; }

function toast(msg) {
  const el = $("#toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove("show"), 2600);
}

let selectedId = null;
let playbooks = [];

function renderList() {
  const el = $("#playbookList");
  if (!playbooks.length) {
    el.innerHTML = "<p class=\"empty\">No playbooks yet.</p>";
    return;
  }
  el.innerHTML = playbooks
    .map(
      (p) =>
        `<button class="playbook-item${p.playbook_id === selectedId ? " active" : ""}" data-id="${p.playbook_id}">${p.name || p.playbook_id}</button>`
    )
    .join("");
  el.querySelectorAll(".playbook-item").forEach((btn) => {
    btn.addEventListener("click", () => selectPlaybook(btn.dataset.id));
  });
}

async function loadPlaybooks() {
  try {
    const data = await api("/playbooks");
    playbooks = data.playbooks || data || [];
    renderList();
    if (playbooks.length && !selectedId) selectPlaybook(playbooks[0].playbook_id);
  } catch (e) {
    $("#playbookList").innerHTML = `<p class="error">${e.message}</p>`;
  }
}

async function selectPlaybook(id) {
  selectedId = id;
  renderList();
  $("#editorTitle").textContent = id;
  $("#result").textContent = "";
  try {
    const data = await api(`/playbooks/${encodeURIComponent(id)}/definition`);
    const def = data.definition || data;
    $("#dslCode").value = JSON.stringify(def, null, 2);
  } catch (e) {
    // Fall back to playbook metadata.
    try {
      const pb = await api(`/playbooks/${encodeURIComponent(id)}`);
      $("#dslCode").value = JSON.stringify(pb, null, 2);
    } catch (e2) {
      $("#dslCode").value = "";
      toast(e2.message);
    }
  }
}

async function validateCurrent() {
  if (!selectedId) return;
  let definition;
  try {
    definition = JSON.parse($("#dslCode").value || "{}");
  } catch (e) {
    toast("Invalid JSON");
    return;
  }
  try {
    const res = await api(`/playbooks/${encodeURIComponent(selectedId)}/validate-definition`, {
      method: "POST",
      body: JSON.stringify({ definition }),
    });
    $("#result").textContent = JSON.stringify(res, null, 2);
    toast(res.valid ? "Validation passed" : "Validation failed");
  } catch (e) {
    toast(e.message);
  }
}

async function saveCurrent() {
  if (!selectedId) return;
  let definition;
  try {
    definition = JSON.parse($("#dslCode").value || "{}");
  } catch (e) {
    toast("Invalid JSON");
    return;
  }
  try {
    await api(`/playbooks/${encodeURIComponent(selectedId)}/definition`, {
      method: "PUT",
      body: JSON.stringify({ definition }),
    });
    toast("Saved");
  } catch (e) {
    toast(e.message);
  }
}

async function publishCurrent() {
  const version = prompt("Version string (e.g. 1.0.0):");
  if (!version) return;
  let definition;
  try {
    definition = JSON.parse($("#dslCode").value || "{}");
  } catch (e) {
    toast("Invalid JSON");
    return;
  }
  try {
    await api(`/playbooks/${encodeURIComponent(selectedId)}/publish`, {
      method: "POST",
      body: JSON.stringify({ version, definition }),
    });
    toast(`Published ${version}`);
  } catch (e) {
    toast(e.message);
  }
}

function bindEvents() {
  $("#refreshBtn")?.addEventListener("click", loadPlaybooks);
  $("#validateBtn")?.addEventListener("click", validateCurrent);
  $("#saveBtn")?.addEventListener("click", saveCurrent);
  $("#publishBtn")?.addEventListener("click", publishCurrent);
  $("#newPlaybookBtn")?.addEventListener("click", async () => {
    const id = prompt("New playbook id:");
    const name = prompt("Name:");
    if (!id || !name) return;
    try {
      await api("/playbooks", {
        method: "POST",
        body: JSON.stringify({ playbook_id: id, name }),
      });
      await loadPlaybooks();
      selectPlaybook(id);
    } catch (e) {
      toast(e.message);
    }
  });
}

bindEvents();
loadPlaybooks();

// Playbook Studio bootstrap. Loads chrome partials, then the routed app.
const API = "/api";

async function loadPartials() {
  const nodes = document.querySelectorAll("[data-partial]");
  await Promise.all(
    [...nodes].map(async (node) => {
      const url = node.getAttribute("data-partial");
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`${res.status}`);
        node.innerHTML = await res.text();
      } catch (err) {
        node.innerHTML = `<p class="error">Failed to load ${url}: ${err.message}</p>`;
      }
    })
  );
}

window.API = API;
window.loadPartials = loadPartials;

await loadPartials();
await import("./app.js");

/* ============================================================
   Kali-MCP Studio — Visual Workflow Editor (app.js)
   Modern canvas-based node editor with DSL round-trip
   ============================================================ */

// ── Configuration ───────────────────────────────────────────
const API_BASE = '';
const NODE_CATEGORIES = {
  input: { label: 'Input', icon: '🔌', nodes: [
    { id: 'agent-input', name: 'Agent Input', type: 'input', desc: 'Value supplied by AI agent at invocation', produces: '{{inputs.X}}' },
    { id: 'operator-input', name: 'Operator Input', type: 'input', desc: 'Value configured by human operator', produces: '{{inputs.X}} (operator)' },
    { id: 'static-value', name: 'Static Value', type: 'input', desc: 'Fixed literal value', produces: 'constant' },
    { id: 'secret-ref', name: 'Secret Reference', type: 'input', desc: 'Opaque secret (redacted in UI)', produces: 'secret_ref' },
  ]},
  tools: { label: 'Tools', icon: '⚡', nodes: [] }, // populated from API
  control: { label: 'Control Flow', icon: '🔀', nodes: [
    { id: 'condition', name: 'Condition', type: 'control', desc: 'when expression (structured only)', produces: 'when field' },
    { id: 'parallel-branch', name: 'Parallel Branch', type: 'control', desc: 'Concurrent sub-graph', produces: 'parallel: true' },
    { id: 'foreach', name: 'For Each', type: 'control', desc: 'Iterate over array', produces: 'foreach field' },
    { id: 'checkpoint', name: 'Checkpoint', type: 'control', desc: 'Persist state, enable resume', produces: 'checkpoint: true' },
  ]},
  data: { label: 'Data', icon: '📊', nodes: [
    { id: 'normalize', name: 'Normalize', type: 'data', desc: 'Canonicalize tool output' },
    { id: 'filter', name: 'Filter', type: 'data', desc: 'Select subset of findings/assets' },
    { id: 'deduplicate', name: 'Deduplicate', type: 'data', desc: 'Merge duplicate observations' },
    { id: 'correlate', name: 'Correlate', type: 'data', desc: 'Cross-tool finding correlation' },
  ]},
  output: { label: 'Output', icon: '📤', nodes: [
    { id: 'asset-persist', name: 'Asset Persistence', type: 'output', desc: 'Write to assets table' },
    { id: 'finding-persist', name: 'Finding Persistence', type: 'data', desc: 'Write to findings table' },
    { id: 'evidence-persist', name: 'Evidence Persistence', type: 'output', desc: 'Write to evidence artifacts' },
    { id: 'report-gen', name: 'Report Generation', type: 'output', desc: 'report_generate tool' },
  ]},
};

// ── State ───────────────────────────────────────────────────
const state = {
  nodes: [],        // { id, x, y, type, kind, tool, config, args, position }
  edges: [],        // { source, target, type: 'execution'|'data' }
  selectedNode: null,
  dragging: null,
  dragOffset: { x: 0, y: 0 },
  pan: { x: 0, y: 0 },
  scale: 1,
  isPanning: false,
  lastMouse: { x: 0, y: 0 },
  playingbookId: null,
  definitionVersion: null,
  tools: [],
  undoStack: [],
  redoStack: [],
  maxUndo: 50,
};

// ── DOM refs ────────────────────────────────────────────────
const canvasViewport = document.getElementById('canvas-viewport');
const canvas = document.getElementById('editor-canvas');
const ctx = canvas.getContext('2d');
const svg = document.getElementById('canvas-svg');
const emptyState = document.getElementById('canvas-empty');
const playbookSelect = document.getElementById('playbook-select');
const nodeLists = {
  input: document.getElementById('nodes-input'),
  tools: document.getElementById('nodes-tools'),
  control: document.getElementById('nodes-control'),
  data: document.getElementById('nodes-data'),
  output: document.getElementById('nodes-output'),
};

// ── Init ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);
  setupCanvasInteractions();
  setupNodeLibrary();
  setupConfigPanel();
  setupDSLModal();
  setupPlaybookActions();
  setupPlaybookSelect();

  // Load playbooks and tools
  await loadPlaybooks();
  await loadTools();

  // Start render loop
  requestAnimationFrame(render);
});

// ── Resize ──────────────────────────────────────────────────
function resizeCanvas() {
  const rect = canvasViewport.getBoundingClientRect();
  canvas.width = rect.width * 2;  // high-DPI
  canvas.height = rect.height * 2;
  ctx.scale(2, 2);
  render();
}

// ── Node Library ────────────────────────────────────────────
function setupNodeLibrary() {
  // Input nodes
  renderCategory('input', NODE_CATEGORIES.input.nodes);
  renderCategory('control', NODE_CATEGORIES.control.nodes);
  renderCategory('data', NODE_CATEGORIES.data.nodes);
  renderCategory('output', NODE_CATEGORIES.output.nodes);

  // Search filter
  document.getElementById('node-search').addEventListener('input', (e) => {
    const term = e.target.value.toLowerCase();
    document.querySelectorAll('.node-card').forEach(card => {
      const text = card.textContent.toLowerCase();
      card.style.display = text.includes(term) ? 'flex' : 'none';
    });
  });

  // Make category headers collapsible
  document.querySelectorAll('.cat-header').forEach(h => {
    h.addEventListener('click', () => {
      const list = h.nextElementSibling;
      list.style.display = list.style.display === 'none' ? 'flex' : 'none';
    });
  });
}

function renderCategory(catKey, nodes) {
  const list = nodeLists[catKey];
  if (!list) return;
  list.innerHTML = '';
  nodes.forEach(node => {
    const card = document.createElement('div');
    card.className = 'node-card';
    card.draggable = true;
    card.dataset.nodeType = node.type;
    card.dataset.nodeKind = node.kind;
    card.dataset.nodeTool = node.tool || '';
    card.innerHTML = `
      <div class="node-icon ${node.type}">${nodeIcon(node.type)}</div>
      <div class="node-card-info">
        <div class="node-card-name">${escapeHtml(node.name)}</div>
        <div class="node-card-desc">${escapeHtml(node.desc)}</div>
      </div>
    `;
    card.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('application/x-node-type', node.type);
      e.dataTransfer.setData('application/x-node-kind', node.kind);
      e.dataTransfer.setData('application/x-node-tool', node.tool || '');
      e.dataTransfer.setData('application/x-node-name', node.name);
      e.dataTransfer.effectAllowed = 'copy';
      setTimeout(() => card.classList.add('dragging'), 0);
    });
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
    list.appendChild(card);
  });
}

function nodeIcon(type) {
  const icons = { input: '🔌', tool: '⚡', control: '🔀', data: '📊', output: '📤' };
  return icons[type] || '●';
}

async function loadTools() {
  try {
    const resp = await fetch(`${API_BASE}/api/tools`);
    const data = await resp.json();
    state.tools = data.tools || [];
    renderToolNodes(state.tools);
  } catch (e) {
    console.warn('Failed to load tools:', e);
  }
}

function renderToolNodes(tools) {
  const list = nodeLists.tools;
  list.innerHTML = '';
  tools.forEach(t => {
    const card = document.createElement('div');
    card.className = 'node-card';
    card.draggable = true;
    card.dataset.nodeType = 'tool';
    card.dataset.nodeKind = 'tool';
    card.dataset.nodeTool = t.tool_id || t.name;
    card.innerHTML = `
      <div class="node-icon tool">⚡</div>
      <div class="node-card-info">
        <div class="node-card-name">${escapeHtml(t.name || t.tool_id)}</div>
        <div class="node-card-desc">${escapeHtml(t.description || 'Native tool')}</div>
      </div>
    `;
    card.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('application/x-node-type', 'tool');
      e.dataTransfer.setData('application/x-node-kind', 'tool');
      e.dataTransfer.setData('application/x-node-tool', t.tool_id || t.name);
      e.dataTransfer.setData('application/x-node-name', t.name || t.tool_id);
      e.dataTransfer.effectAllowed = 'copy';
      setTimeout(() => card.classList.add('dragging'), 0);
    });
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
    list.appendChild(card);
  });
}

// ── Canvas Interactions ─────────────────────────────────────
function setupCanvasInteractions() {
  // Viewport pan
  canvasViewport.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    const target = e.target;
    if (target.tagName === 'CANVAS' || target === canvasViewport || target.id === 'canvas-grid' || target.id === 'canvas-overlay') {
      state.isPanning = true;
      state.lastMouse = { x: e.clientX, y: e.clientY };
      canvasViewport.style.cursor = 'grabbing';
    }
  });
  window.addEventListener('mousemove', (e) => {
    if (state.isPanning) {
      const dx = e.clientX - state.lastMouse.x;
      const dy = e.clientY - state.lastMouse.y;
      state.pan.x += dx / state.scale;
      state.pan.y += dy / state.scale;
      state.lastMouse = { x: e.clientX, y: e.clientY };
      render();
    }
    if (state.dragging) {
      const rect = canvasViewport.getBoundingClientRect();
      const mx = (e.clientX - rect.left) / state.scale - state.pan.x;
      const my = (e.clientY - rect.top) / state.scale - state.pan.y;
      state.dragging.x = mx - state.dragOffset.x;
      state.dragging.y = my - state.dragOffset.y;
      render();
    }
  });
  window.addEventListener('mouseup', (e) => {
    if (e.button === 0) {
      state.isPanning = false;
      canvasViewport.style.cursor = 'grab';
      if (state.dragging) {
        pushUndo();
        state.dragging = null;
      }
    }
  });

  // Drop from library
  canvasViewport.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });
  canvasViewport.addEventListener('drop', (e) => {
    e.preventDefault();
    const type = e.dataTransfer.getData('application/x-node-type');
    const kind = e.dataTransfer.getData('application/x-node-kind');
    const tool = e.dataTransfer.getData('application/x-node-tool');
    const name = e.dataTransfer.getData('application/x-node-name');
    const rect = canvasViewport.getBoundingClientRect();
    const x = (e.clientX - rect.left) / state.scale - state.pan.x;
    const y = (e.clientY - rect.top) / state.scale - state.pan.y;
    addNode({ type, kind, tool: tool || undefined, x, y, name });
    pushUndo();
    render();
  });

  // Wheel zoom
  canvasViewport.addEventListener('wheel', (e) => {
    e.preventDefault();
    const zoomSpeed = 0.001;
    const delta = -e.deltaY * zoomSpeed;
    const newScale = Math.min(Math.max(state.scale + delta, 0.5), 2);
    const rect = canvasViewport.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / state.scale - state.pan.x;
    const my = (e.clientY - rect.top) / state.scale - state.pan.y;
    state.scale = newScale;
    state.pan.x = (e.clientX - rect.left) / state.scale - mx;
    state.pan.y = (e.clientY - rect.top) / state.scale - my;
    render();
  }, { passive: false });

  // Node drag on canvas
  canvasViewport.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    const rect = canvasViewport.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / state.scale - state.pan.x;
    const my = (e.clientY - rect.top) / state.scale - state.pan.y;
    // Check if clicking on a node
    const node = getNodeAt(mx, my);
    if (node) {
      state.dragging = node;
      state.dragOffset = { x: mx - node.x, y: my - node.y };
      selectNode(node.id);
      e.stopPropagation();
    } else {
      selectNode(null);
    }
  });
}

// ── Node Management ─────────────────────────────────────────
function addNode({ type, kind, tool, x, y, name }) {
  const node = {
    id: `node_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    type,
    kind,
    tool: tool || null,
    name: name || type,
    x, y,
    config: {},
    args: {},
    depends_on: [],
    when: null,
    parallel: false,
    checkpoint: false,
    retry: 0,
    on_failure: 'abort',
    budget: {},
  };
  state.nodes.push(node);
  updateEmptyState();
  return node;
}

function deleteNode(id) {
  state.nodes = state.nodes.filter(n => n.id !== id);
  state.edges = state.edges.filter(e => e.source !== id && e.target !== id);
  if (state.selectedNode?.id === id) selectNode(null);
  updateEmptyState();
}

function getNodeAt(x, y) {
  const nodeSize = { w: 160, h: 70 };
  for (let i = state.nodes.length - 1; i >= 0; i--) {
    const n = state.nodes[i];
    if (x >= n.x - nodeSize.w/2 && x <= n.x + nodeSize.w/2 &&
        y >= n.y - nodeSize.h/2 && y <= n.y + nodeSize.h/2) {
      return n;
    }
  }
  return null;
}

function selectNode(id) {
  if (state.selectedNode?.id === id) return;
  state.selectedNode = state.nodes.find(n => n.id === id) || null;
  render();
  updateConfigPanel();
}

function pushUndo() {
  state.undoStack.push(JSON.stringify({ nodes: state.nodes, edges: state.edges }));
  if (state.undoStack.length > state.maxUndo) state.undoStack.shift();
  state.redoStack = [];
}

// ── Render ──────────────────────────────────────────────────
function render() {
  const rect = canvasViewport.getBoundingClientRect();
  const width = rect.width;
  const height = rect.height;

  // Clear
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.scale(0.5, 0.5); // undo the high-DPI scale for logical coords
  ctx.translate(state.pan.x, state.pan.y);
  ctx.scale(state.scale, state.scale);

  // Draw edges first (behind nodes)
  state.edges.forEach(edge => {
    const s = state.nodes.find(n => n.id === edge.source);
    const t = state.nodes.find(n => n.id === edge.target);
    if (!s || !t) return;
    drawEdge(s.x, s.y, t.x, t.y, edge.type);
  });

  // Draw nodes
  state.nodes.forEach(node => {
    drawNode(node, node.id === state.selectedNode?.id);
  });

  ctx.restore();

  // Update SVG for edges (crisp lines)
  renderEdgesSVG();

  updateEmptyState();
  updateStatusBar();
}

function renderEdgesSVG() {
  svg.innerHTML = '';
  state.edges.forEach(edge => {
    const s = state.nodes.find(n => n.id === edge.source);
    const t = state.nodes.find(n => n.id === edge.target);
    if (!s || !t) return;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', s.x);
    line.setAttribute('y1', s.y + 35);
    line.setAttribute('x2', t.x);
    line.setAttribute('y2', t.y - 35);
    line.setAttribute('stroke', edge.type === 'execution' ? varCss('--edge-active') : varCss('--edge'));
    line.setAttribute('stroke-width', '2');
    line.setAttribute('stroke-linecap', 'round');
    line.setAttribute('marker-end', 'url(#arrow)');
    svg.appendChild(line);
  });
  // Ensure arrow marker exists
  if (!svg.querySelector('#arrow')) {
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
    marker.setAttribute('id', 'arrow');
    marker.setAttribute('markerWidth', '10');
    marker.setAttribute('markerHeight', '10');
    marker.setAttribute('refX', '8');
    marker.setAttribute('refY', '3');
    marker.setAttribute('orient', 'auto');
    marker.innerHTML = '<path d="M0,0 L0,6 L9,3 z" fill="#6366f1" />';
    defs.appendChild(marker);
    svg.insertBefore(defs, svg.firstChild);
  }
}

function varCss(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function drawEdge(x1, y1, x2, y2, type) {
  ctx.beginPath();
  ctx.moveTo(x1, y1 + 35);
  ctx.lineTo(x2, y2 - 35);
  ctx.strokeStyle = type === 'execution' ? varCss('--edge-active') : varCss('--edge');
  ctx.lineWidth = 2;
  ctx.stroke();
}

function drawNode(node, selected) {
  const w = 170;
  const h = 74;
  const x = node.x - w/2;
  const y = node.y - h/2;

  // Shadow
  ctx.save();
  ctx.shadowColor = 'rgba(0,0,0,0.3)';
  ctx.shadowBlur = 12;
  ctx.shadowOffsetY = 6;

  // Background
  const gradient = ctx.createLinearGradient(x, y, x, y + h);
  gradient.addColorStop(0, selected ? 'rgba(99, 102, 241, 0.2)' : 'rgba(255,255,255,0.03)');
  gradient.addColorStop(1, 'rgba(255,255,255,0.02)');
  ctx.fillStyle = gradient;
  ctx.strokeStyle = selected ? varCss('--accent') : varCss('--border');
  ctx.lineWidth = selected ? 2 : 1;
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, 10);
  ctx.fill();
  ctx.stroke();

  // Left type indicator
  const typeColor = getNodeColor(node.kind);
  ctx.fillStyle = typeColor;
  ctx.beginPath();
  ctx.roundRect(x + 8, y + 8, 6, h - 16, 3);
  ctx.fill();

  // Title
  ctx.fillStyle = varCss('--text');
  ctx.font = '600 13px Inter, sans-serif';
  ctx.fillText(escapeHtml(node.name || node.type), x + 24, y + 20);

  // Type / tool subtitle
  ctx.fillStyle = varCss('--text-muted');
  ctx.font = '11px JetBrains Mono, monospace';
  ctx.fillText(node.tool || node.kind, x + 24, y + 38);

  // Output port (right side)
  ctx.fillStyle = typeColor;
  ctx.beginPath();
  ctx.arc(x + w - 8, y + h/2, 5, 0, Math.PI * 2);
  ctx.fill();

  // Input port (left side)
  ctx.beginPath();
  ctx.arc(x + 8, y + h/2, 4, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(255,255,255,0.1)';
  ctx.strokeStyle = typeColor;
  ctx.lineWidth = 1;
  ctx.fill();
  ctx.stroke();

  ctx.restore();
}

function getNodeColor(kind) {
  const colors = {
    input: varCss('--node-input'),
    tool: varCss('--node-tool'),
    module: varCss('--node-module'),
    control: varCss('--node-control'),
    data: varCss('--node-data'),
    output: varCss('--node-output'),
  };
  return colors[kind] || varCss('--text-muted');
}

// ── Config Panel ────────────────────────────────────────────
function setupConfigPanel() {
  const form = document.getElementById('config-form');
  const empty = document.getElementById('config-empty');

  // Tool select change
  document.getElementById('config-tool').addEventListener('change', (e) => {
    if (!state.selectedNode) return;
    state.selectedNode.tool = e.target.value || null;
    pushUndo();
    render();
  });

  // Input fields
  const fields = [
    { id: 'config-description', prop: 'name', type: 'text' },
    { id: 'config-when', prop: 'when', type: 'text' },
    { id: 'config-retry', prop: 'retry', type: 'number' },
    { id: 'config-budget-timeout', prop: 'budget.timeout', type: 'number' },
    { id: 'config-pos-x', prop: 'x', type: 'number' },
    { id: 'config-pos-y', prop: 'y', type: 'number' },
  ];
  fields.forEach(f => {
    const el = document.getElementById(f.id);
    el.addEventListener('change', () => {
      if (!state.selectedNode) return;
      let val = el.value;
      if (f.type === 'number') val = parseFloat(val) || 0;
      if (f.prop.includes('.')) {
        const [p1, p2] = f.prop.split('.');
        state.selectedNode[p1] = state.selectedNode[p1] || {};
        state.selectedNode[p1][p2] = val;
      } else {
        state.selectedNode[f.prop] = val;
      }
      pushUndo();
      render();
    });
  });

  // Checkboxes
  ['config-parallel', 'config-checkpoint'].forEach(id => {
    document.getElementById(id).addEventListener('change', (e) => {
      if (!state.selectedNode) return;
      state.selectedNode[id === 'config-parallel' ? 'parallel' : 'checkpoint'] = e.target.checked;
      pushUndo();
      render();
    });
  });

  // On failure
  document.getElementById('config-on-failure').addEventListener('change', (e) => {
    if (!state.selectedNode) return;
    state.selectedNode.on_failure = e.target.value;
    pushUndo();
    render();
  });

  // Delete selected
  document.getElementById('btn-delete-selected').addEventListener('click', () => {
    if (!state.selectedNode) return;
    deleteNode(state.selectedNode.id);
    pushUndo();
    render();
  });
}

function updateConfigPanel() {
  const empty = document.getElementById('config-empty');
  const form = document.getElementById('config-form');
  const title = document.getElementById('config-panel-title');
  const deleteBtn = document.getElementById('btn-delete-selected');

  if (!state.selectedNode) {
    empty.classList.remove('hidden');
    form.classList.add('hidden');
    deleteBtn.style.display = 'none';
    title.textContent = 'Node Configuration';
    return;
  }

  empty.classList.add('hidden');
  form.classList.remove('hidden');
  deleteBtn.style.display = 'flex';
  title.textContent = `Node: ${escapeHtml(state.selectedNode.name || state.selectedNode.type)}`;

  document.getElementById('config-node-id').value = state.selectedNode.id;
  document.getElementById('config-node-id-field').value = state.selectedNode.id;
  document.getElementById('config-node-type').value = state.selectedNode.kind;
  document.getElementById('config-tool').value = state.selectedNode.tool || '';
  document.getElementById('config-description').value = state.selectedNode.name || '';
  document.getElementById('config-when').value = state.selectedNode.when || '';
  document.getElementById('config-parallel').checked = state.selectedNode.parallel || false;
  document.getElementById('config-checkpoint').checked = state.selectedNode.checkpoint || false;
  document.getElementById('config-retry').value = state.selectedNode.retry || 0;
  document.getElementById('config-on-failure').value = state.selectedNode.on_failure || 'abort';
  document.getElementById('config-budget-timeout').value = state.selectedNode.budget?.timeout || '';
  document.getElementById('config-pos-x').value = Math.round(state.selectedNode.x);
  document.getElementById('config-pos-y').value = Math.round(state.selectedNode.y);

  renderDependsOnChips();
  renderArgsList();
}

function renderDependsOnChips() {
  const container = document.getElementById('config-depends-on');
  container.innerHTML = '';
  if (!state.selectedNode) return;
  (state.selectedNode.depends_on || []).forEach(depId => {
    const depNode = state.nodes.find(n => n.id === depId);
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.textContent = depNode?.name || depId;
    chip.innerHTML += '<button class="chip-remove">×</button>';
    chip.querySelector('.chip-remove').addEventListener('click', (e) => {
      e.stopPropagation();
      state.selectedNode.depends_on = state.selectedNode.depends_on.filter(d => d !== depId);
      // Remove edge
      state.edges = state.edges.filter(e => !(e.source === depId && e.target === state.selectedNode.id));
      pushUndo();
      renderDependsOnChips();
      render();
    });
    container.appendChild(chip);
  });
}

function renderArgsList() {
  const container = document.getElementById('config-args');
  container.innerHTML = '';
  if (!state.selectedNode) return;
  Object.entries(state.selectedNode.args || {}).forEach(([key, val]) => {
    const row = document.createElement('div');
    row.className = 'arg-row';
    row.innerHTML = `
      <input type="text" placeholder="arg name" value="${escapeHtml(key)}" />
      <input type="text" placeholder="value" value="${escapeHtml(typeof val === 'string' ? val : JSON.stringify(val))}" />
      <button class="btn-remove-arg">×</button>
    `;
    row.querySelector('button').addEventListener('click', () => {
      delete state.selectedNode.args[key];
      pushUndo();
      renderArgsList();
      render();
    });
    row.querySelectorAll('input').forEach((inp, idx) => {
      inp.addEventListener('change', () => {
        if (idx === 0) {
          const oldKey = key;
          const newKey = inp.value || oldKey;
          if (newKey !== oldKey) {
            state.selectedNode.args[newKey] = state.selectedNode.args[oldKey];
            delete state.selectedNode.args[oldKey];
          }
        } else {
          state.selectedNode.args[inp.previousElementSibling.value] = inp.value;
        }
        pushUndo();
      });
    });
    container.appendChild(row);
  });

  // Add arg button
  const btn = document.getElementById('btn-add-arg');
  btn.onclick = () => {
    if (!state.selectedNode) return;
    state.selectedNode.args = state.selectedNode.args || {};
    state.selectedNode.args[`arg_${Date.now()}`] = '';
    pushUndo();
    renderArgsList();
  };
}

// ── DSL Round-trip ──────────────────────────────────────────
function canvasToDSL() {
  const nodes = state.nodes.map(n => ({
    id: n.id,
    type: n.type === 'module' ? 'module' : 'tool',
    tool: n.tool,
    depends_on: n.depends_on || [],
    when: n.when || undefined,
    parallel: n.parallel || false,
    foreach: n.foreach || undefined,
    retry: n.retry || 0,
    on_failure: n.on_failure || 'abort',
    checkpoint: n.checkpoint || false,
    budget: n.budget || {},
    args: n.args || {},
  }));
  const edges = state.edges.filter(e => e.type === 'execution');
  // Map edges to depends_on (already in nodes, but ensure consistency)
  edges.forEach(e => {
    const node = nodes.find(n => n.id === e.target);
    if (node && !node.depends_on.includes(e.source)) {
      node.depends_on.push(e.source);
    }
  });
  return {
    id: state.playbookId || 'pb_visual',
    name: state.playbookName || 'Visual Playbook',
    version: '1.0.0',
    inputs: {},
    execution: { max_parallel: 4, timeout: 900, resume: true },
    steps: nodes,
    outputs: {},
  };
}

function dslToCanvas(dsl) {
  state.nodes = (dsl.steps || []).map((s, i) => ({
    id: s.id,
    type: s.type === 'module' ? 'module' : 'tool',
    kind: s.type === 'module' ? 'module' : 'tool',
    tool: s.tool,
    x: 200 + (i % 3) * 260,
    y: 150 + Math.floor(i / 3) * 140,
    depends_on: s.depends_on || [],
    when: s.when || null,
    parallel: s.parallel || false,
    foreach: s.foreach || null,
    retry: s.retry || 0,
    on_failure: s.on_failure || 'abort',
    checkpoint: s.checkpoint || false,
    budget: s.budget || {},
    args: s.args || {},
    name: s.id,
  }));
  state.edges = [];
  state.nodes.forEach(n => {
    (n.depends_on || []).forEach(dep => {
      state.edges.push({ source: dep, target: n.id, type: 'execution' });
    });
  });
  state.playbookId = dsl.id;
  state.playbookName = dsl.name;
  render();
}

// ── DSL Modal ───────────────────────────────────────────────
function setupDSLModal() {
  const modal = document.getElementById('dsl-modal');
  const output = document.getElementById('dsl-output');
  const btnOpen = document.getElementById('btn-toggle-dsl');
  const btnClose = document.getElementById('btn-close-dsl');
  const btnApply = document.getElementById('btn-apply-dsl');
  const btnDiscard = document.getElementById('btn-discard-dsl');

  btnOpen.addEventListener('click', () => {
    output.value = JSON.stringify(canvasToDSL(), null, 2);
    modal.classList.remove('hidden');
  });
  btnClose.addEventListener('click', () => modal.classList.add('hidden'));
  btnDiscard.addEventListener('click', () => modal.classList.add('hidden'));

  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      if (tab.dataset.tab === 'canonical') {
        output.value = JSON.stringify(canvasToDSL(), null, 2);
      } else {
        output.value = JSON.stringify(canvasToDSL(), null, 2); // DSL would go here
      }
    });
  });

  btnApply.addEventListener('click', () => {
    try {
      const parsed = JSON.parse(output.value);
      dslToCanvas(parsed);
      pushUndo();
      modal.classList.add('hidden');
      showToast('DSL applied successfully', 'success');
    } catch (e) {
      showToast('Invalid JSON: ' + e.message, 'error');
    }
  });
}

// ── Playbook Actions ────────────────────────────────────────
function setupPlaybookActions() {
  document.getElementById('btn-save-playbook').addEventListener('click', async () => {
    if (!state.playbookId) {
      // Create new
      const name = prompt('Playbook name:') || 'Visual Playbook';
      try {
        const resp = await fetch(`${API_BASE}/api/playbooks`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ playbook_id: `pb_${Date.now()}`, name, status: 'draft' }),
        });
        const data = await resp.json();
        state.playbookId = data.playbook_id;
        updatePlaybookSelect();
      } catch (e) {
        showToast('Failed to create playbook', 'error');
      }
      return;
    }
    // Update existing
    try {
      await fetch(`${API_BASE}/api/playbooks/${state.playbookId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'draft' }),
      });
      showToast('Saved', 'success');
    } catch (e) {
      showToast('Failed to save', 'error');
    }
  });

  document.getElementById('btn-publish-playbook').addEventListener('click', async () => {
    if (!state.playbookId) return;
    const dsl = canvasToDSL();
    try {
      // Validate first
      const valResp = await fetch(`${API_BASE}/api/playbooks/${state.playbookId}/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ definition: dsl, for_publish: true }),
      });
      const val = await valResp.json();
      if (!val.valid) {
        showToast('Validation failed — fix errors before publishing', 'error');
        return;
      }
      // Publish
      const pubResp = await fetch(`${API_BASE}/api/playbooks/${state.playbookId}/publish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: '1.0.0', definition: dsl }),
      });
      const pub = await pubResp.json();
      showToast('Published v' + pub.version, 'success');
      await loadPlaybooks();
    } catch (e) {
      showToast('Failed to publish', 'error');
    }
  });

  document.getElementById('btn-validate').addEventListener('click', async () => {
    if (!state.playbookId) {
      showToast('Save playbook first', 'error');
      return;
    }
    const dsl = canvasToDSL();
    try {
      const resp = await fetch(`${API_BASE}/api/playbooks/${state.playbookId}/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ definition: dsl }),
      });
      const val = await resp.json();
      const el = document.getElementById('status-validation');
      el.querySelector('.pill-dot').style.background = val.valid ? varCss('--success') : varCss('--error');
      el.querySelector('span:last-child').textContent = `Validation: ${val.valid ? 'passed' : 'failed' (val.findings?.length || 0) errors}`;
      showToast(val.valid ? 'Validation passed' : 'Validation failed', val.valid ? 'success' : 'error');
    } catch (e) {
      showToast('Validation error', 'error');
    }
  });

  document.getElementById('btn-preview').addEventListener('click', async () => {
    if (!state.playbookId) {
      showToast('Save playbook first', 'error');
      return;
    }
    const dsl = canvasToDSL();
    try {
      const resp = await fetch(`${API_BASE}/api/playbooks/${state.playbookId}/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ definition: dsl }),
      });
      const result = await resp.json();
      showToast(result.ok ? 'Preview ran' : 'Preview failed', result.ok ? 'success' : 'error');
    } catch (e) {
      showToast('Preview error', 'error');
    }
  });

  document.getElementById('btn-clear-canvas').addEventListener('click', () => {
    if (confirm('Clear all nodes?')) {
      state.nodes = [];
      state.edges = [];
      state.selectedNode = null;
      pushUndo();
      render();
      updateConfigPanel();
    }
  });

  document.getElementById('btn-undo').addEventListener('click', () => {
    if (state.undoStack.length === 0) return;
    state.redoStack.push(JSON.stringify({ nodes: state.nodes, edges: state.edges }));
    const prev = JSON.parse(state.undoStack.pop());
    state.nodes = prev.nodes;
    state.edges = prev.edges;
    state.selectedNode = null;
    render();
    updateConfigPanel();
  });

  document.getElementById('btn-redo').addEventListener('click', () => {
    if (state.redoStack.length === 0) return;
    state.undoStack.push(JSON.stringify({ nodes: state.nodes, edges: state.edges }));
    const next = JSON.parse(state.redoStack.pop());
    state.nodes = next.nodes;
    state.edges = next.edges;
    state.selectedNode = null;
    render();
    updateConfigPanel();
  });

  document.getElementById('btn-auto-layout').addEventListener('click', () => {
    // Simple auto-layout: wave-based
    const byId = new Map(state.nodes.map(n => [n.id, n]));
    const waves = [];
    const assigned = new Set();
    let remaining = [...state.nodes];
    while (remaining.length > 0) {
      const wave = remaining.filter(n => (n.depends_on || []).every(d => assigned.has(d)));
      if (wave.length === 0) break;
      wave.forEach(n => assigned.add(n.id));
      waves.push(wave);
      remaining = remaining.filter(n => !assigned.has(n.id));
    }
    const waveX = 300;
    const waveY = 160;
    waves.forEach((wave, wi) => {
      wave.forEach((n, ni) => {
        n.x = 150 + wi * waveX;
        n.y = 80 + ni * waveY;
      });
    });
    pushUndo();
    render();
  });

  document.getElementById('btn-zoom-fit').addEventListener('click', () => {
    state.scale = 1;
    state.pan = { x: 0, y: 0 };
    render();
  });
}

function setupPlaybookSelect() {
  playbookSelect.addEventListener('change', async (e) => {
    const id = e.target.value;
    if (!id) return;
    state.playbookId = id;
    try {
      const resp = await fetch(`${API_BASE}/api/playbooks/${id}`);
      const pb = await resp.json();
      // Find latest version
      const verResp = await fetch(`${API_BASE}/api/playbooks/${id}/versions`);
      const versions = await verResp.json();
      if (versions.versions && versions.versions.length > 0) {
        const latest = versions.versions[versions.versions.length - 1];
        let def = latest.definition;
        if (typeof def === 'string') def = JSON.parse(def);
        dslToCanvas(def);
        state.playbookName = pb.name;
      }
      updateStatusBar();
    } catch (e) {
      showToast('Failed to load playbook', 'error');
    }
  });
}

async function loadPlaybooks() {
  try {
    const resp = await fetch(`${API_BASE}/api/playbooks`);
    const data = await resp.json();
    const playbooks = data.playbooks || [];
    playbookSelect.innerHTML = '<option value="">Create new playbook</option>';
    playbooks.forEach(pb => {
      const opt = document.createElement('option');
      opt.value = pb.playbook_id;
      opt.textContent = pb.name || pb.playbook_id;
      playbookSelect.appendChild(opt);
    });
    document.getElementById('btn-save-playbook').disabled = false;
    document.getElementById('btn-publish-playbook').disabled = false;
  } catch (e) {
    console.warn('Failed to load playbooks:', e);
  }
}

function updatePlaybookSelect() {
  // Re-fetch
  loadPlaybooks();
}

// ── UI Helpers ──────────────────────────────────────────────
function updateEmptyState() {
  if (state.nodes.length === 0) {
    emptyState.classList.remove('hidden');
  } else {
    emptyState.classList.add('hidden');
  }
}

function updateStatusBar() {
  document.getElementById('status-node-count').querySelector('span:last-child').textContent = `Nodes: ${state.nodes.length}`;
  document.getElementById('status-canvas').querySelector('span:last-child').textContent = `Canvas: ${state.nodes.length} nodes`;
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

function escapeHtml(text) {
  if (text == null) return '';
  return String(text).replace(/[&<>"']/g, m => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[m]));
}
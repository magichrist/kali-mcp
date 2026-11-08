# Plan 1 — Migration Checklist (Internal)

Source of truth: existing `src/kali_mcp/studio/web/` (app.js, main.js, index.html, style.css,
partials/sidebar.html, partials/topbar.html) + `src/kali_mcp/studio/api.py` + `docs/webUI.md`.

**Phase 1 — Existing Frontend Audit (read-only). No files in `studio/web/` were modified.**

## Files audited
- [x] `studio/web/app.js` (~3k lines) — full SPA: API client, router, all pages, graph editor, undo/redo, auto-layout
- [x] `studio/web/main.js` — bootstrap + partial loading
- [x] `studio/web/index.html` — shell + mount point
- [x] `studio/web/style.css` — design system (CSS variables, colors, spacing, breakpoints, components)
- [x] `studio/web/partials/sidebar.html` — navigation items, routes, auth badge markup
- [x] `studio/web/partials/topbar.html` — breadcrumb + top-actions structure
- [x] `studio/web/assets/` — empty (no static assets)
- [x] `src/kali_mcp/studio/api.py` — backend route contracts

## Hash routes mapped (12)
- [x] `#/overview` → Overview dashboard (KPIs from /api/overview)
- [x] `#/playbooks` → Playbook library (list, search, status/category filter, sort, create, import)
- [x] `#/playbooks/:id` → Playbook editor (Graph + DSL views)
- [x] `#/executions` → Execution list (5s auto-refresh, status filter)
- [x] `#/executions/:id` → Execution detail (steps, artifacts, cancel, resume)
- [x] `#/tools` → Tool registry (list, search, visibility toggle)
- [x] `#/connections` → MCP connections (list, test, discover, delete, add)
- [x] `#/connections/:id` → Connection detail (imported tools, discover)
- [x] `#/agents` → Agent profiles (list, create)
- [x] `#/agents/:id` → Agent detail (tool grants, playbook assignments, delete)
- [x] `#/findings` → Findings (severity/target/tool filters)
- [x] `#/settings` → Server config (read-only), clear stored token

## API endpoints used by frontend (from api.py)
- [x] GET/POST /api/playbooks
- [x] GET/DELETE /api/playbooks/{id}
- [x] PUT+GET /api/playbooks/{id}/definition
- [x] POST /api/playbooks/{id}/publish (body {definition, version})
- [x] POST /api/playbooks/{id}/validate-definition (body {definition})
- [x] GET /api/playbooks/{id}/versions
- [x] POST /api/playbooks/{id}/rollback (body {version_id})
- [x] GET /api/playbooks/{id}/export
- [x] POST /api/playbooks/import (body {package})
- [x] GET /api/server
- [x] GET /api/overview
- [x] GET/POST /api/connections
- [x] GET/DELETE /api/connections/{id}
- [x] POST /api/connections/{id}/test
- [x] POST /api/connections/{id}/discover
- [x] GET /api/tools
- [x] PUT /api/tools/{id}/visibility (body {visibility})
- [x] GET /api/findings (query target, severity, tool)
- [x] GET/POST /api/agents
- [x] GET/DELETE /api/agents/{id}
- [x] PUT/DELETE /api/agents/{id}/tools/{tool_id}
- [x] PUT/DELETE /api/agents/{id}/playbooks/{playbook_id}
- [x] GET/POST /api/executions
- [x] GET /api/executions/{id}
- [x] POST /api/executions/{id}/cancel
- [x] POST /api/executions/{id}/resume

## Auth behavior documented
- [x] Token key: localStorage `kmcp_token`
- [x] Every /api/* request: Authorization: Bearer <token>
- [x] 401 → promptForToken() shows #tokenModal, queues retries, saveTokenAndRetry() saves + reloads
- [x] Token never in URLs, query strings, logs, or error messages

## Graph data representation (DSL) documented
- [x] Step fields: id, type, tool, command, depends_on, inputs, args, filter, when, checkpoint, execution {timeout, max_parallel}
- [x] Step types: tool, shell, scope_check, finding_correlation, assessment_report, custom
- [x] rawDsl is source of truth; graphDef ⇄ rawDsl sync (loadGraphFromDSL / captureGraphToDSL / switchBuilderView)
- [x] colorJson() syntax highlighting for DSL / outputs
- [x] Undo/redo: JSON snapshots, max 40, historyStack/futureStack
- [x] Auto-layout: cycle-safe longest-path layering (graphLayout), nodePos by depth, applyZoom/zoom pan
- [x] Canvas: zoom/pan/fit-to-screen, pinch-zoom, drag pan, per-playbook localStorage canvas state
- [x] Inspector tabs: General/Inputs/Outputs/Advanced; schema-driven tool args; input mapping (run/upstream/literal)

## Bugs / notes identified in vanilla implementation
- [x] `api()` returns `body?.data ?? body` — some endpoints return the row directly (not wrapped in `data`), handled by fallback
- [x] `validate-definition` reuses `put_definition` handler (POST) — frontend posts to same path with body {definition}
- [x] Publish has an `/approval-request` fallback path (not in api.py mount list) — backend-dependent, preserved as-is
- [x] Run-status polling every 1s (runStatusTimer) — must be cleaned up on route change / unmount
- [x] Execution list auto-refresh every 5s (execTimer) — must be cleaned up on route change

## Phase 1 DONE ✅
- All existing files read and understood
- All API endpoints and payloads documented
- All routes and behaviors mapped
- No files modified during this audit (read-only)

---

## Phase 2 — Vue Foundation (in progress)
- [ ] WebUI/package.json, tsconfig.json (strict), vite.config.ts
- [ ] Vite: root=WebUI, outDir=../src/kali_mcp/studio/web, emptyOutDir=true, /api proxy → 127.0.0.1:8399
- [ ] Install: vue, vue-router@4, pinia, @vue-flow/core@1.x, vitest, @vue/test-utils, jsdom, playwright, typescript, @vitejs/plugin-vue
- [ ] WebUI/index.html, src/main.ts, src/App.vue, src/router/index.ts (hash history + 12 routes, lazy pages)
- [ ] src/stores/auth.ts + API client + 5 API modules + TokenModal
- [ ] npm install succeeds; `vite` dev starts; `vite build` outputs to studio/web/
- [ ] `vue-tsc --noEmit` passes; Vitest + Playwright configured and runnable

## Phase 3 — API & Authentication (in progress)
- [ ] Centralized fetch client with Bearer injection, 401→token modal+retry, error normalization
- [ ] Auth store (kmcp_token, modal visibility, clear token)
- [ ] API modules: playbooks, executions, tools, connections, agents
- [ ] TS interfaces for all request/response types
- [ ] Token modal component; no token leakage
- [ ] Tests: 401→modal, error normalization, network failure

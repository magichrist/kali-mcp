/* Vue Router 4 — hash history to preserve existing Studio URLs
   (#/playbooks, #/playbooks/:id, #/executions/:id, ...) without requiring
   backend deep-route rewrites.
*/

import { createWebHashHistory, createRouter, type RouteRecordRaw } from "vue-router";

const routes: RouteRecordRaw[] = [
  {
    path: "/",
    redirect: "/overview",
  },
  {
    path: "/overview",
    name: "overview",
    component: () => import("@/pages/OverviewPage.vue"),
    meta: { title: "Overview", crumb: "Overview" },
  },
  {
    path: "/playbooks",
    name: "playbooks",
    component: () => import("@/pages/PlaybooksPage.vue"),
    meta: { title: "Playbook Studio", crumb: "Playbook Studio" },
  },
  {
    path: "/playbooks/:id",
    name: "playbook-editor",
    component: () => import("@/pages/PlaybooksPage.vue"),
    meta: { title: "Playbook Studio", crumb: "Playbooks" },
  },
  {
    path: "/executions",
    name: "executions",
    component: () => import("@/pages/ExecutionsPage.vue"),
    meta: { title: "Executions", crumb: "Executions" },
  },
  {
    path: "/executions/:id",
    name: "execution-detail",
    component: () => import("@/pages/ExecutionDetailPage.vue"),
    meta: { title: "Execution Detail", crumb: "Executions" },
  },
  {
    path: "/tools",
    name: "tools",
    component: () => import("@/pages/ToolsPage.vue"),
    meta: { title: "Tool Registry", crumb: "Tool Registry" },
  },
  {
    path: "/connections",
    name: "connections",
    component: () => import("@/pages/ConnectionsPage.vue"),
    meta: { title: "MCP Connections", crumb: "MCP Connections" },
  },
  {
    path: "/connections/:id",
    name: "connection-detail",
    component: () => import("@/pages/ConnectionDetailPage.vue"),
    meta: { title: "Connection Detail", crumb: "MCP Connections" },
  },
  {
    path: "/agents",
    name: "agents",
    component: () => import("@/pages/AgentsPage.vue"),
    meta: { title: "Agents", crumb: "Agents" },
  },
  {
    path: "/agents/:id",
    name: "agent-detail",
    component: () => import("@/pages/AgentDetailPage.vue"),
    meta: { title: "Agent Detail", crumb: "Agents" },
  },
  {
    path: "/findings",
    name: "findings",
    component: () => import("@/pages/FindingsPage.vue"),
    meta: { title: "Findings", crumb: "Findings" },
  },
  {
    path: "/settings",
    name: "settings",
    component: () => import("@/pages/SettingsPage.vue"),
    meta: { title: "Settings", crumb: "Settings" },
  },
  {
    path: "/:pathMatch(.*)*",
    name: "not-found",
    component: () => import("@/pages/NotFoundPage.vue"),
    meta: { title: "Not Found", crumb: "Not Found" },
  },
];

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    if (savedPosition) {
      return savedPosition;
    }
    return { top: 0 };
  },
});

export default router;

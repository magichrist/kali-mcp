/* Maps an arbitrary status/severity string to a BaseBadge variant. */

export function badgeVariant(v: string | null | undefined): "ok" | "failed" | "warn" | "default" | "accent" {
  const map: Record<string, "ok" | "failed" | "warn" | "default" | "accent"> = {
    ok: "ok",
    completed: "ok",
    healthy: "ok",
    failed: "failed",
    error: "failed",
    warn: "warn",
    warning: "warn",
    running: "warn",
    default: "default",
    accent: "accent",
  };
  return v ? (map[v] ?? "default") : "default";
}

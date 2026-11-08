/* Vitest + jsdom setup for the Playbook Studio frontend. */
import "@testing-library/jest-dom";
import { vi } from "vitest";

// Browser globals jsdom doesn't provide by default.
Object.assign(window, {
  matchMedia: vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() })),
});

if (typeof ResizeObserver === "undefined") {
  // @ts-expect-error test shim
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}

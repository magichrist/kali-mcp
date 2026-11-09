import { setActivePinia, createPinia } from "pinia";
import { vi } from "vitest";

// Active Pinia so module-level Pinia store usage (e.g. src/stores/auth.ts
// calls useAuthStore() at module scope) works during tests.
setActivePinia(createPinia());

// vitest/jsdom does not expose localStorage unless --localstorage-file is set.
// Provide an in-memory Storage polyfill so the auth store and API client can
// read/write the "kmcp_token" key exactly as they would in a browser.
const createLocalStorage = (): Storage => {
  const store: Record<string, string> = {};
  return {
    get length(): number {
      return Object.keys(store).length;
    },
    clear(): void {
      Object.keys(store).forEach((key) => {
        delete store[key];
      });
    },
    getItem(key: string): string | null {
      return Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null;
    },
    key(index: number): string | null {
      return Object.keys(store)[index] ?? null;
    },
    removeItem(key: string): void {
      delete store[key];
    },
    setItem(key: string, value: string): void {
      store[key] = String(value);
    },
  } as Storage;
};

Object.defineProperty(globalThis, "localStorage", {
  value: createLocalStorage(),
  writable: true,
  configurable: true,
});

// Silence console noise in tests unless explicitly asserted.
vi.spyOn(console, "log").mockImplementation(() => {});
vi.spyOn(console, "error").mockImplementation(() => {});
vi.spyOn(console, "warn").mockImplementation(() => {});

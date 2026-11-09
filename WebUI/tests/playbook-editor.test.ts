import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import { usePlaybookEditorStore } from "@/stores/playbook-editor";
import type { Execution } from "@/types/api";

function okResponse(execution: Execution): Response {
  return new Response(JSON.stringify({ execution }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

const baseExecution: Execution = {
  execution_id: "exec-1",
  playbook_id: "pb-1",
  status: "running",
  steps: [
    { step_id: "step_a", status: "running", outputs: { stdout: "hi" }, tool_id: "tool-1" },
    { step_id: "step_b", status: "pending" },
  ],
  artifacts: [],
};

describe("playbook editor live execution polling", () => {
  const timers: Array<() => unknown> = [];
  let intervalId = 0;
  const origFetch = globalThis.fetch;
  const fetchMock = vi.fn();

  async function flush(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
  }

  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.removeItem("kmcp_token");
    timers.length = 0;
    intervalId = 0;
    fetchMock.mockReset();
    vi.spyOn(window, "setInterval").mockImplementation((cb: unknown) => {
      const id = ++intervalId;
      timers.push(cb as () => unknown);
      return id;
    });
    vi.spyOn(window, "clearInterval").mockImplementation(() => {});
    globalThis.fetch = fetchMock as any;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.fetch = origFetch;
  });

  it("starts polling immediately, updates per-node status/results, and stops on terminal state", async () => {
    const store = usePlaybookEditorStore();
    fetchMock.mockResolvedValueOnce(okResponse({ ...baseExecution, status: "running" }));
    fetchMock.mockResolvedValueOnce(
      okResponse({ ...baseExecution, status: "completed", steps: [{ ...baseExecution.steps![0], status: "completed" }] }),
    );

    await store.startPolling("exec-1");

    expect(store.pollingActive).toBe(true);
    expect(store.pollingExecutionId).toBe("exec-1");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/executions/exec-1", expect.anything());
    expect(store.runStatus).toEqual({ step_a: "running", step_b: "pending" });
    expect(store.stepResults.step_a).toMatchObject({ outputs: { stdout: "hi" }, tool_id: "tool-1" });

    // First 1s tick fires the second poll; the execution is now terminal.
    await (timers[0] as () => unknown)();
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(store.runStatus.step_a).toBe("completed");
    expect(store.pollingActive).toBe(false);
    expect(store.pollingExecutionId).toBeNull();
    expect(window.clearInterval).toHaveBeenCalled();
  });

  it("keeps polling while the execution is non-terminal", async () => {
    const store = usePlaybookEditorStore();
    fetchMock.mockResolvedValue(okResponse(baseExecution));

    await store.startPolling("exec-1");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(store.pollingActive).toBe(true);

    await (timers[0] as () => unknown)();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await (timers[0] as () => unknown)();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(store.pollingActive).toBe(true);

    store.stopPolling();
    expect(window.clearInterval).toHaveBeenCalled();
    expect(store.pollingActive).toBe(false);
  });

  it("survives API failures without crashing and keeps the last known state", async () => {
    const store = usePlaybookEditorStore();
    fetchMock.mockResolvedValueOnce(okResponse(baseExecution));
    fetchMock.mockRejectedValueOnce(new TypeError("network down"));
    fetchMock.mockResolvedValueOnce(
      okResponse({ ...baseExecution, status: "completed", steps: [{ ...baseExecution.steps![0], status: "completed" }] }),
    );

    await store.startPolling("exec-1");
    expect(store.pollingActive).toBe(true);
    expect(store.runStatus.step_a).toBe("running");

    // First tick fails -> error swallowed, state unchanged, polling continues.
    await (timers[0] as () => unknown)();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(store.runStatus.step_a).toBe("running");
    expect(store.pollingActive).toBe(true);

    // Second tick reaches terminal state -> polling stops.
    await (timers[0] as () => unknown)();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(store.pollingActive).toBe(false);
    expect(store.runStatus.step_a).toBe("completed");
  });

  it("never runs overlapping poll requests", async () => {
    const store = usePlaybookEditorStore();
    let release!: () => void;
    const held = new Promise<Response>((resolve) => {
      release = () => resolve(okResponse(baseExecution));
    });
    fetchMock.mockResolvedValueOnce(okResponse(baseExecution)); // immediate poll
    fetchMock.mockImplementation(() => held); // every tick blocks until released

    await store.startPolling("exec-1");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(store.pollingActive).toBe(true);

    // Tick 1 starts a poll that stays in flight.
    void (timers[0] as () => unknown)();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // Tick 2 while tick 1 is still in flight must not issue another request.
    void (timers[0] as () => unknown)();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    release();
    await flush();

    // Once tick 1 completes (non-terminal), tick 3 polls again.
    void (timers[0] as () => unknown)();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(3);

    store.stopPolling();
    expect(store.pollingActive).toBe(false);
  });

  it("stopPolling is safe when idle and startPolling replaces any previous poll", async () => {
    const store = usePlaybookEditorStore();
    store.stopPolling(); // no-op when nothing is polling
    expect(store.pollingActive).toBe(false);

    fetchMock.mockResolvedValue(okResponse(baseExecution));
    await store.startPolling("exec-1");
    expect(store.pollingExecutionId).toBe("exec-1");

    await store.startPolling("exec-2"); // switches execution, old timer cleared
    expect(store.pollingExecutionId).toBe("exec-2");
    expect(store.pollingActive).toBe(true);

    store.stopPolling();
    expect(store.pollingActive).toBe(false);
    expect(store.pollingExecutionId).toBeNull();
  });
});

export interface HistorySnapshot { definition: unknown; graphPos: unknown; selectedNodeId: string | null; inspectTab: string; view: string; runStatus: unknown; stepResults: unknown; }
export function useGraphHistory(options: { maxDepth?: number } = {}) {
  const maxDepth = options.maxDepth ?? 40;
  const stack: HistorySnapshot[] = []; const future: HistorySnapshot[] = [];
  function push(snapshot: HistorySnapshot): void { stack.push(snapshot); if (stack.length > maxDepth) stack.shift(); future.length = 0; }
  function canUndo(): boolean { return stack.length > 0; }
  function canRedo(): boolean { return future.length > 0; }
  function undo(current: HistorySnapshot): { previous: HistorySnapshot } | null { if (!stack.length) return null; future.push(current); return { previous: stack.pop()! }; }
  function redo(current: HistorySnapshot): { next: HistorySnapshot } | null { if (!future.length) return null; stack.push(current); return { next: future.pop()! }; }
  function clear(): void { stack.length = 0; future.length = 0; }
  function depth(): number { return stack.length; }
  return { push, canUndo, canRedo, undo, redo, clear, depth, maxDepth };
}
export type HistoryApi = ReturnType<typeof useGraphHistory>;

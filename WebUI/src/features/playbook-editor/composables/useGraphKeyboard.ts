export interface KeyboardHandlers { onUndo?: () => void; onRedo?: () => void; onDelete?: () => void; onEscape?: () => void; isEditing?: () => boolean; }
export function useGraphKeyboard(handlers: KeyboardHandlers) {
  let listener: ((e: KeyboardEvent) => void) | null = null;
  function start(): void {
    if (listener) return;
    listener = (e) => {
      const isCmdOrCtrl = e.ctrlKey || e.metaKey;
      const isEditing = handlers.isEditing ? handlers.isEditing() : false;
      if (e.key === "z" && isCmdOrCtrl && !e.altKey && !isEditing) { if (e.shiftKey) handlers.onRedo?.(); else handlers.onUndo?.(); e.preventDefault(); return; }
      if ((e.key === "Delete" || e.key === "Backspace") && !isEditing) { handlers.onDelete?.(); e.preventDefault(); return; }
      if (e.key === "Escape") handlers.onEscape?.();
    };
    document.addEventListener("keydown", listener);
  }
  function stop(): void { if (listener) { document.removeEventListener("keydown", listener); listener = null; } }
  return { start, stop };
}

export type ListNavigationKey = "ArrowDown" | "ArrowUp" | "Home" | "End";

export function nextListSelectionId<T>(
  items: readonly T[],
  selectedId: string,
  key: string,
  getId: (item: T) => string
): string {
  if (!isListNavigationKey(key) || !items.length) return selectedId;
  const currentIndex = Math.max(0, items.findIndex((item) => getId(item) === selectedId));
  if (key === "Home") return getId(items[0]);
  if (key === "End") return getId(items[items.length - 1]);
  if (key === "ArrowDown") return getId(items[Math.min(items.length - 1, currentIndex + 1)]);
  return getId(items[Math.max(0, currentIndex - 1)]);
}

export function isEditableKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return ["BUTTON", "INPUT", "SELECT", "TEXTAREA", "A"].includes(target.tagName);
}

function isListNavigationKey(key: string): key is ListNavigationKey {
  return key === "ArrowDown" || key === "ArrowUp" || key === "Home" || key === "End";
}

export type ListNavigationKey = "ArrowDown" | "ArrowUp" | "Home" | "End";

export function nextListSelectionId<T>(
  items: readonly T[],
  selectedId: string,
  key: string,
  getId: (item: T) => string
): string {
  if (!isListNavigationKey(key) || !items.length) return selectedId;
  const foundIndex = items.findIndex((item) => getId(item) === selectedId);
  if (foundIndex < 0) return getId(items[0]);
  const currentIndex = foundIndex;
  if (key === "Home") return getId(items[0]);
  if (key === "End") return getId(items[items.length - 1]);
  if (key === "ArrowDown") return getId(items[Math.min(items.length - 1, currentIndex + 1)]);
  return getId(items[Math.max(0, currentIndex - 1)]);
}

export function isEditableKeyboardTarget(target: EventTarget | null): boolean {
  if (!target || typeof target !== "object") return false;
  const element = target as { tagName?: string; type?: string; isContentEditable?: boolean };
  if (element.isContentEditable) return true;
  const tagName = String(element.tagName || "").toUpperCase();
  if (tagName === "TEXTAREA" || tagName === "SELECT") return true;
  if (tagName !== "INPUT") return false;
  const inputType = String(element.type || "text").toLowerCase();
  return !["button", "checkbox", "radio", "reset", "submit"].includes(inputType);
}

function isListNavigationKey(key: string): key is ListNavigationKey {
  return key === "ArrowDown" || key === "ArrowUp" || key === "Home" || key === "End";
}

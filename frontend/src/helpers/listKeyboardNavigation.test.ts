import { describe, expect, it } from "vitest";
import { isEditableKeyboardTarget, nextListSelectionId } from "./listKeyboardNavigation";

describe("nextListSelectionId", () => {
  const items = [{ id: "a" }, { id: "b" }, { id: "c" }];

  it("moves selection with arrow keys and clamps at list edges", () => {
    const getId = (item: { id: string }) => item.id;

    expect(nextListSelectionId(items, "a", "ArrowDown", getId)).toBe("b");
    expect(nextListSelectionId(items, "c", "ArrowDown", getId)).toBe("c");
    expect(nextListSelectionId(items, "c", "ArrowUp", getId)).toBe("b");
    expect(nextListSelectionId(items, "a", "ArrowUp", getId)).toBe("a");
  });

  it("supports home and end for fast list movement", () => {
    const getId = (item: { id: string }) => item.id;

    expect(nextListSelectionId(items, "b", "Home", getId)).toBe("a");
    expect(nextListSelectionId(items, "b", "End", getId)).toBe("c");
  });

  it("starts from the first item when current selection is not in the visible list", () => {
    expect(nextListSelectionId(items, "missing", "ArrowDown", (item) => item.id)).toBe("a");
  });

  it("does not reserve arrow navigation for row buttons and checkboxes", () => {
    expect(isEditableKeyboardTarget({ tagName: "BUTTON" } as unknown as EventTarget)).toBe(false);
    expect(isEditableKeyboardTarget({ tagName: "INPUT", type: "checkbox" } as unknown as EventTarget)).toBe(false);
    expect(isEditableKeyboardTarget({ tagName: "A" } as unknown as EventTarget)).toBe(false);
  });

  it("keeps arrow navigation inside text editing controls", () => {
    expect(isEditableKeyboardTarget({ tagName: "INPUT", type: "text" } as unknown as EventTarget)).toBe(true);
    expect(isEditableKeyboardTarget({ tagName: "INPUT", type: "search" } as unknown as EventTarget)).toBe(true);
    expect(isEditableKeyboardTarget({ tagName: "SELECT" } as unknown as EventTarget)).toBe(true);
    expect(isEditableKeyboardTarget({ tagName: "TEXTAREA" } as unknown as EventTarget)).toBe(true);
    expect(isEditableKeyboardTarget({ tagName: "DIV", isContentEditable: true } as unknown as EventTarget)).toBe(true);
  });
});

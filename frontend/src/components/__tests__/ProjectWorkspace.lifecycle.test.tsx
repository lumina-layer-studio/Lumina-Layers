import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
const native = vi.hoisted(() => ({ setDirty: vi.fn().mockResolvedValue(true), ready: vi.fn().mockResolvedValue(true),
  closeAnswer: vi.fn().mockResolvedValue(true), onClose: vi.fn(), onOpen: vi.fn(() => () => {}) }));
vi.mock("../../project/files", async original => ({ ...await original<typeof import("../../project/files")>(), nativeProjects: native }));
vi.mock("../../project/controller", async original => ({ ...await original<typeof import("../../project/controller")>(), startProjectTracking: () => () => {} }));
import ProjectWorkspace from "../projects/ProjectWorkspace";
import { useProjectSessionStore } from "../../stores/projectSessionStore";
import { useProjectUi } from "../../project/controller";
import { translations } from "../../i18n/translations";

let close: (id: string) => void;
beforeEach(() => {
  vi.clearAllMocks();
  native.onClose.mockImplementation(listener => { close = listener; return () => {}; });
  useProjectSessionStore.getState().reset();
  useProjectSessionStore.setState({ dirty: true });
  useProjectUi.setState({ centerOpen: false });
});

it("keeps one unsaved-changes decision when another native close arrives", async () => {
  render(<ProjectWorkspace />);
  await act(async () => close("first"));
  await act(async () => close("second"));
  expect(native.closeAnswer).toHaveBeenCalledWith("second", false);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: translations.project_cancel.zh })));
  expect(native.closeAnswer).toHaveBeenCalledWith("first", false);
});

it("protects unsaved desktop edits from a full page reload", () => {
  render(<ProjectWorkspace />);
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
});

it("still protects edits when development reload storage is unavailable", async () => {
  useProjectUi.setState({ entry: null });
  await act(async () => { render(<ProjectWorkspace />); });
  const storage = vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
    throw new DOMException("Storage unavailable", "SecurityError");
  });
  try {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  } finally { storage.mockRestore(); }
});

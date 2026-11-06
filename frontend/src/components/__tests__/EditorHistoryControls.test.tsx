import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ProjectWorkspace from "../projects/ProjectWorkspace";
import { converterDocumentHistory, DEFAULT_STATE, useConverterStore } from "../../stores/converter";
import { useWidgetStore } from "../../stores/widgetStore";
import { useProjectSessionStore } from "../../stores/projectSessionStore";

const desktop = vi.hoisted(() => ({ api: { platform: undefined as string | undefined } }));
vi.mock("../../integrations/electron", async original => ({
  ...await original<typeof import("../../integrations/electron")>(),
  electronAPI: desktop.api,
}));
vi.mock("../../project/controller", async (original) => ({
  ...await original<typeof import("../../project/controller")>(),
  startProjectTracking: () => () => {},
}));

beforeEach(() => {
  desktop.api.platform = undefined;
  useConverterStore.setState({ ...DEFAULT_STATE, sessionId: "editor", historyCanUndo: true, historyCanRedo: true });
  converterDocumentHistory.reset();
  converterDocumentHistory.store.setState({ canUndo: true, canRedo: true });
  useWidgetStore.setState({ activeTab: "converter" });
  useProjectSessionStore.getState().reset();
});
afterEach(() => vi.restoreAllMocks());

it("uses the existing editor history from buttons, keyboard and native menu", async () => {
  const undo = vi.spyOn(converterDocumentHistory, "undo").mockResolvedValue();
  const redo = vi.spyOn(converterDocumentHistory, "redo").mockResolvedValue();
  render(<ProjectWorkspace />);
  fireEvent.click(screen.getByRole("button", { name: "撤销" }));
  fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
  fireEvent.keyDown(document.body, { key: "z", metaKey: true, shiftKey: true });
  const native = new CustomEvent("lumina-editor-history", { detail: "redo", cancelable: true });
  await act(async () => { window.dispatchEvent(native); });
  expect(undo).toHaveBeenCalledTimes(2);
  expect(redo).toHaveBeenCalledTimes(2);
  expect(native.defaultPrevented).toBe(true);
});

it("leaves text undo alone and blocks artwork history during dialogs and unfinished edits", () => {
  const undo = vi.spyOn(converterDocumentHistory, "undo").mockResolvedValue();
  render(<><ProjectWorkspace /><input aria-label="name" /><div contentEditable data-testid="editable" /></>);
  for (const input of [screen.getByRole("textbox"), screen.getByTestId("editable")]) {
    input.focus();
    fireEvent.keyDown(input, { key: "z", ctrlKey: true });
    const native = new CustomEvent("lumina-editor-history", { detail: "undo", cancelable: true });
    window.dispatchEvent(native);
    expect(native.defaultPrevented).toBe(false);
  }
  (document.activeElement as HTMLElement).blur();
  const dialog = document.createElement("dialog");
  dialog.setAttribute("open", ""); document.body.append(dialog);
  fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
  dialog.remove();
  act(() => useConverterStore.setState({ contentCommitStatus: "unknown" }));
  expect(screen.getByRole("button", { name: "撤销" })).toBeDisabled();
  fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
  expect(undo).not.toHaveBeenCalled();
});

it("never undoes a hidden converter while another workspace is active", () => {
  const undo = vi.spyOn(converterDocumentHistory, "undo").mockResolvedValue();
  useWidgetStore.setState({ activeTab: "workshop" });
  render(<ProjectWorkspace />);
  fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
  expect(screen.queryByRole("button", { name: "撤销" })).not.toBeInTheDocument();
  expect(undo).not.toHaveBeenCalled();
});

it.each(["win32", "linux"])("routes Ctrl shortcuts once on %s and keeps text undo native", platform => {
  desktop.api.platform = platform;
  const undo = vi.spyOn(converterDocumentHistory, "undo").mockResolvedValue();
  const redo = vi.spyOn(converterDocumentHistory, "redo").mockResolvedValue();
  render(<><ProjectWorkspace /><input aria-label="filename" /></>);
  fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
  fireEvent.keyDown(document.body, { key: "z", ctrlKey: true, shiftKey: true });
  fireEvent.keyDown(document.body, { key: "y", ctrlKey: true });
  expect(undo).toHaveBeenCalledTimes(1);
  expect(redo).toHaveBeenCalledTimes(2);
  const input = screen.getByRole("textbox", { name: "filename" });
  input.focus();
  fireEvent.keyDown(input, { key: "z", ctrlKey: true });
  fireEvent.keyDown(input, { key: "y", ctrlKey: true });
  expect(undo).toHaveBeenCalledTimes(1);
  expect(redo).toHaveBeenCalledTimes(2);
});

it("uses the native macOS menu without repeating its keyboard event", () => {
  desktop.api.platform = "darwin";
  const undo = vi.spyOn(converterDocumentHistory, "undo").mockResolvedValue();
  render(<ProjectWorkspace />);
  fireEvent.keyDown(document.body, { key: "z", metaKey: true });
  expect(undo).not.toHaveBeenCalled();
  window.dispatchEvent(new CustomEvent("lumina-editor-history", { detail: "undo", cancelable: true }));
  expect(undo).toHaveBeenCalledTimes(1);
});

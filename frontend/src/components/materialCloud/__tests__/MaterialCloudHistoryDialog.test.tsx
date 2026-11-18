import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import MaterialCloudHistoryDialog from "../MaterialCloudHistoryDialog";
import type { MaterialSyncInstalledEntry } from "../../../api/types";
import { I18nProvider } from "../../../i18n/context";

const entry: MaterialSyncInstalledEntry = {
  material_id: "material-id", revision_id: "hash-current", content_hash: "sha256:secret", channel: "official", source: "package",
  local_directory: "Brand/PLA", display_brand: "Brand", display_name: "PLA Blue", local_exists: true, material_file_exists: true,
  installed_at: "2026-10-20T08:00:00Z", available_revisions: ["hash-old", "hash-current", "hash-newer"],
  revision_history: [
    { revision_id: "hash-old", installed_at: "2026-09-01T08:00:00Z" },
    { revision_id: "hash-newer", installed_at: "2026-10-01T08:00:00Z" },
    { revision_id: "hash-current", installed_at: "2026-10-20T08:00:00Z" },
  ],
};
function show(entries = [entry]) {
  const onRollback = vi.fn(); const onClose = vi.fn();
  render(<I18nProvider><MaterialCloudHistoryDialog entries={entries} pendingRollback={null} error={null} success={null} onDismissSuccess={vi.fn()} onRollback={onRollback} onClose={onClose} /></I18nProvider>);
  return { onRollback, onClose };
}
describe("local material history dialog", () => {
  it("orders by date, hides hashes and restores only the selected revision", () => {
    const { onRollback } = show();
    const dialog = screen.getByRole("dialog");
    expect(dialog).not.toHaveTextContent(/hash-|sha256/);
    const dates = within(dialog).getAllByRole("radio");
    expect(dates[0].closest("label")).toHaveTextContent(/10.*01/);
    expect(dates[1].closest("label")).toHaveTextContent(/09.*01/);
    const restore = screen.getByRole("button", { name: /恢复所选版本|Restore selected/ });
    expect(restore).toBeDisabled();
    fireEvent.click(dates[0]); fireEvent.click(restore);
    expect(onRollback).toHaveBeenCalledWith(entry, "hash-newer");
  });
  it("shows unknown dates without falling back to hashes", () => {
    show([{ ...entry, revision_history: undefined, installed_at: null }]);
    expect(screen.getByRole("dialog")).toHaveTextContent(/日期未知|Date unknown/);
    expect(screen.getByRole("dialog")).not.toHaveTextContent("hash-old");
  });
  it("shows an empty state and closes with Escape", async () => {
    const { onClose } = show([]);
    expect(screen.getByRole("dialog")).toHaveTextContent(/暂无|No local history/);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });
});

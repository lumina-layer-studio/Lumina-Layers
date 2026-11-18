import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import CloudLibraryPreview from "../CloudLibraryPreview";

afterEach(() => { vi.restoreAllMocks(); });

describe("cloud library detail focus", () => {
  it("toggles the current card, retains content during exit, and cancels exit when another card opens", async () => {
    render(<CloudLibraryPreview resetKey="all" toolbar={null} items={[
      { key: "first", name: "First LUT", subtitle: "Brand", thumbnail: { kind: "luts" }, detail: <p>First details</p> },
      { key: "second", name: "Second LUT", subtitle: "Brand", thumbnail: { kind: "luts" }, detail: <p>Second details</p> },
    ]} />);
    const first = screen.getByRole("button", { name: /First LUT/ });
    const second = screen.getByRole("button", { name: /Second LUT/ });
    fireEvent.click(first);
    fireEvent.click(first);
    const exiting = screen.getByText("First details").closest("aside")!;
    expect(exiting).toHaveAttribute("inert");
    expect(first).toHaveAttribute("aria-expanded", "false");
    expect(first).toHaveFocus();
    fireEvent.click(second);
    await waitFor(() => expect(screen.getByRole("complementary")).not.toHaveAttribute("inert"));
    expect(screen.getByText("Second details")).toBeInTheDocument();
    expect(screen.queryByText("First details")).not.toBeInTheDocument();
    fireEvent.click(second.closest("article")!);
    await waitFor(() => expect(document.querySelector("aside")).toBeNull());
    expect(second).toHaveFocus();
  });

  it("opens from card padding, restores keyboard focus and keeps all actions independent", () => {
    const download = vi.fn();
    const favorite = vi.fn();
    render(<CloudLibraryPreview resetKey="all" toolbar={null}
      items={[{ key: "lut", name: "Test LUT", subtitle: "Brand", thumbnail: { kind: "luts" },
        detail: <p>Details</p>, activity: <button onClick={favorite}>Favorite</button>,
        action: <button onClick={download}>Download</button> }]} />);
    const trigger = screen.getByRole("button", { name: /Test LUT/ });
    fireEvent.click(screen.getByRole("button", { name: "Favorite" }));
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(favorite).toHaveBeenCalledOnce();
    expect(download).toHaveBeenCalledOnce();
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("article"));
    expect(screen.getByText("Details")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("complementary"), { key: "Escape" });
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(screen.getByText("Details")).toBeInTheDocument();
    expect(screen.getByRole("article").querySelector("button button")).toBeNull();
  });

  it("does not open details when a disabled action is clicked", () => {
    render(<CloudLibraryPreview resetKey="all" toolbar={null}
      items={[{ key: "lut", name: "Test LUT", subtitle: "Brand", thumbnail: { kind: "luts" },
        detail: <p>Details</p>, action: <button disabled>Downloading</button> }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Downloading" }));
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it.each([
    [1280, 900, true], [640, 900, false], [1280, 500, false],
  ])("opens details at %i × %i with preventScroll=%s", (width, height, preventScroll) => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(width);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(height);
    const focus = vi.spyOn(HTMLButtonElement.prototype, "focus");
    render(<CloudLibraryPreview
      resetKey="all" toolbar={null}
      items={[{ key: "lut", name: "Selected LUT", subtitle: "Brand", state: "Installed", thumbnail: { kind: "luts", mode: "4-Color (RYBW)" },
        detail: <p>Details</p> }]}
    />);
    fireEvent.click(screen.getByRole("button", { name: /Selected LUT/ }));
    expect(screen.getByText("Details")).toBeInTheDocument();
    expect(focus).toHaveBeenLastCalledWith({ preventScroll });
  });
});

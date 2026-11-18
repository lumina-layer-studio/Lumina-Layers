import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import CalibrationThumbnail from "../CalibrationThumbnail";
import { LibraryIdentity } from "../LibraryDetails";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function pointer(target: Element, type: string, x: number, y: number, pointerType = "mouse") {
  const event = new MouseEvent(type, { clientX: x, clientY: y });
  Object.defineProperty(event, "pointerType", { value: pointerType });
  fireEvent(target, event);
}

function animationFrames() {
  let id = 0;
  const queued = new Map<number, FrameRequestCallback>();
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    queued.set(++id, callback);
    return id;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation((key) => { queued.delete(key); });
  return { queued, draw() {
    const callbacks = [...queued.values()];
    queued.clear();
    callbacks.forEach((callback) => callback(16));
  } };
}

describe("calibration card interaction", () => {
  const pageColor = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4qGsEAAMzAUGNjL54AAAAAElFTkSuQmCC";
  const secondColor = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGOQS3kNAAIRAW7+16uUAAAAAElFTkSuQmCC";
  const lookup = (family: "five" | "eight" | "full", counts: number[]) => ({
    lut_board_preview: { family, set_size: counts.length, pages: counts.map((count, i) => ({
      number: i + 1, rows: Math.ceil(Math.sqrt(count)), cols: Math.ceil(Math.sqrt(count)), padding: family === "five" && i === 0 ? 4 : 1, count, png: i ? secondColor : pageColor,
    })) },
  });
  const graphic = (img: HTMLImageElement) => new DOMParser().parseFromString(decodeURIComponent(img.src.split(",")[1]), "image/svg+xml");

  it("shows two stacked square faces in a list, and switches real five- and eight-color pages only in details", () => {
    vi.useFakeTimers();
    const display = lookup("five", [1024, 1444]);
    const { container, rerender } = render(<button>Select LUT<CalibrationThumbnail kind="luts" resourceKey="five" display={display} /></button>);
    const listFace = graphic(container.querySelector("img")!);
    expect([...listFace.querySelectorAll("image")].map((e) => e.getAttribute("href"))).toEqual([
      "data:image/png;base64," + secondColor, "data:image/png;base64," + pageColor,
    ]);
    expect(screen.queryByRole("group", { name: "切换校准板" })).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    rerender(<LibraryIdentity name="Aliz PETG" subtitle="Aliz" thumbnail={{ kind: "luts", resourceKey: "five", display }} />);
    const first = screen.getByRole("img", { name: "基础板" });
    const headingColumn = screen.getByRole("heading", { name: "Aliz PETG" }).parentElement!;
    expect(screen.queryByRole("group", { name: "切换校准板" })).toBeNull();
    expect(headingColumn).toContainElement(screen.getByText("基础板 · 1,024 条配方"));
    expect(headingColumn).not.toContainElement(first);
    expect(screen.getByRole("button", { name: "基础板，点击查看扩展板" })).toContainElement(first);
    const artwork = graphic(first as HTMLImageElement);
    const surface = artwork.documentElement.querySelector("svg")!;
    expect(surface.getAttribute("viewBox")).toBe("0 0 40 40");
    expect(surface.querySelector("image")?.getAttribute("x")).toBe("4");
    // Four physical registration patches; no additional row of channel colors.
    const cornerColors = (svg: Element) => [...svg.querySelectorAll("rect")].map((rect) => rect.getAttribute("fill")).filter((fill) => fill?.startsWith("#"));
    expect(cornerColors(surface)).toEqual(["#ffffff", "#dc143c", "#0064f0", "#ffe600"]);
    fireEvent.click(screen.getByRole("button", { name: "基础板，点击查看扩展板" }));
    const second = screen.getByRole("img", { name: "扩展板" }) as HTMLImageElement;
    expect(screen.getAllByRole("img")).toHaveLength(1);
    expect(first).toHaveAttribute("aria-hidden", "true");
    expect(graphic(second).querySelector("image")?.getAttribute("href")).toBe("data:image/png;base64," + secondColor);
    expect(screen.getByText("扩展板 · 1,444 条配方")).toBeInTheDocument();
    const extension = graphic(second).documentElement.querySelector("svg")!;
    expect(extension.getAttribute("viewBox")).toBe("0 0 40 40");
    expect(extension.querySelector("image")?.getAttribute("x")).toBe("1");
    expect(cornerColors(extension)).toEqual(["#0064f0", "#dc143c", "#141414", "#ffe600"]);
    // Repeated clicks during the exchange do not restart it or skip a board.
    const switchBoard = screen.getByRole("button", { name: "扩展板，点击查看基础板" });
    fireEvent.click(switchBoard);
    fireEvent.click(switchBoard);
    expect(screen.getByRole("img", { name: "扩展板" })).toBe(second);
    act(() => vi.advanceTimersByTime(360));
    fireEvent.click(switchBoard);
    expect(screen.getByRole("img", { name: "基础板" })).toBe(first);
    // Selecting a different resource during animation resets to its first board.
    rerender(<CalibrationThumbnail kind="luts" size="lg" resourceKey="eight" display={lookup("eight", [1369, 1369])} />);
    expect(screen.getByRole("img", { name: "A 板" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "A 板，点击查看B 板" }));
    expect(screen.getByRole("img", { name: "B 板" })).toBeInTheDocument();
    expect(screen.getByText("B 板 · 1,369 条配方")).toBeInTheDocument();
  });

  it("switches the preview with Enter and Space while retaining focus", async () => {
    const user = userEvent.setup();
    render(<CalibrationThumbnail kind="luts" size="lg" display={lookup("eight", [1369, 1369])} />);
    const target = screen.getByRole("button", { name: "A 板，点击查看B 板" });
    await user.tab();
    expect(target).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("img", { name: "B 板" })).toBeInTheDocument();
    await waitFor(() => expect(target.querySelector(".is-swapping")).toBeNull());
    await user.keyboard(" ");
    expect(screen.getByRole("img", { name: "A 板" })).toBeInTheDocument();
    expect(target).toHaveFocus();
  });

  it("switches with touch and clears pending work on unmount", () => {
    vi.useFakeTimers();
    const { unmount } = render(<CalibrationThumbnail kind="luts" size="lg" display={lookup("eight", [1369, 1369])} />);
    const target = screen.getByRole("button", { name: "A 板，点击查看B 板" });
    pointer(target.parentElement!, "pointerenter", 60, 40, "touch");
    fireEvent.click(target);
    expect(screen.getByRole("img", { name: "B 板" })).toBeInTheDocument();
    expect(target.querySelector(".is-tilting")).toBeNull();
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("shows unavailable artwork as status text instead of a white board", () => {
    render(<LibraryIdentity name="Unmeasured" subtitle="" thumbnail={{ kind: "luts", display: { palette_rgb: [[255, 0, 0], [0, 0, 255]] } }} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByRole("heading").parentElement).toContainElement(screen.getByText("暂无色板数据"));
  });

  it("browses a full set without rendering every board and keeps an individual page file separate", () => {
    const display = lookup("full", [...Array(23).fill(1369), 1281]);
    const { rerender } = render(<CalibrationThumbnail kind="luts" resourceKey="all" size="lg" display={display} />);
    expect(screen.getByRole("button", { name: "上一张校准板" })).toBeDisabled();
    const next = screen.getByRole("button", { name: "下一张校准板" });
    for (let i = 1; i < 24; i++) fireEvent.click(next);
    expect(next).toBeDisabled();
    expect(screen.getByText("1,281 条配方")).toBeInTheDocument();
    const lastPage = display.lut_board_preview.pages[23];
    rerender(<CalibrationThumbnail kind="luts" resourceKey="one" size="lg" display={{
      lut_board_preview: { ...display.lut_board_preview, pages: [lastPage] },
    }} />);
    expect(screen.getByRole("img", { name: "第 24 / 24 张" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "切换校准板" })).toBeNull();
  });

  it("keeps distinct measured colors in flat, rotated print order and leaves missing samples empty", () => {
    render(<CalibrationThumbnail kind="materials" size="lg" display={{
      preview_swatches: { black: ["#303030", "#881414"], white: ["#fafafa", "#ff4400"] },
    }} />);
    const image = screen.getByRole("img", { name: /实测/ }) as HTMLImageElement;
    const doc = new DOMParser().parseFromString(decodeURIComponent(image.src.split(",")[1]), "image/svg+xml");
    const boards = [...doc.querySelectorAll("g")];
    expect(boards).toHaveLength(2);
    for (const [side, board] of boards.entries()) {
      const cells = board.querySelectorAll("path");
      expect(cells).toHaveLength(18);
      expect(cells[0].getAttribute("d")).toBe("M23 1h10v10h-10Z");
      expect(cells[17].getAttribute("d")).toBe("M1 56h10v10h-10Z");
      expect(cells[0].getAttribute("fill")).toBe(side ? "#fafafa" : "#303030");
      expect(cells[17].getAttribute("fill")).toBe(side ? "#ff4400" : "#881414");
      expect(board.querySelectorAll('[fill="none"]')).toHaveLength(16);
    }
  });

  it.each(["materials", "luts"] as const)("tilts the %s card toward the pointer, coalesces movement, and cancels work on exit", (kind) => {
    const { queued, draw } = animationFrames();
    render(<><button>First<CalibrationThumbnail kind={kind} rgb={[239, 10, 30]} display={lookup("eight", [1369, 1369])} /></button>
      <button>Second<CalibrationThumbnail kind={kind} rgb={[40, 80, 200]} display={lookup("five", [1024, 1444])} /></button></>);
    const [first, second] = screen.getAllByRole("button");
    vi.spyOn(first, "getBoundingClientRect").mockReturnValue(new DOMRect(10, 20, 200, 100));
    const image = first.querySelector("img")!;
    const plane = image.parentElement!;
    // The thumbnail sits left of the much wider resource button's center.
    vi.spyOn(plane.parentElement!, "getBoundingClientRect").mockReturnValue(new DOMRect(20, 30, 56, 56));
    expect(queued.size).toBe(0);
    pointer(first, "pointerenter", 20, 58);
    draw();
    expect(plane.style.transform).toContain("rotateX(0.00deg) rotateY(30.00deg)");
    pointer(first, "pointermove", 76, 58);
    draw();
    expect(plane.style.transform).toContain("rotateX(0.00deg) rotateY(-30.00deg)");
    pointer(first, "pointermove", 48, 58);
    draw();
    expect(plane.style.transform).toContain("rotateX(0.00deg) rotateY(0.00deg)");
    pointer(first, "pointermove", 40, 40);
    pointer(first, "pointermove", 76, 30);
    expect(queued.size).toBe(1);
    draw();
    // At the upper-right corner, negative X/Y rotations lift that corner toward the viewer.
    expect(plane.style.transform).toContain("rotateX(-20.00deg) rotateY(-30.00deg)");
    expect(queued.size).toBe(0);
    expect(first.querySelector("img")).toBe(image);
    expect(second.querySelector(".is-tilting")).toBeNull();
    pointer(first, "pointermove", 20, 86);
    draw();
    expect(plane.style.transform).toContain("rotateX(20.00deg) rotateY(30.00deg)");
    pointer(first, "pointermove", 48, 58);
    pointer(first, "pointerleave", 0, 0);
    expect(queued.size).toBe(0);
    expect(plane.style.transform).toBe("");
    expect(first.querySelector(".calibration-edge-frame")).toBeNull();
  });

  it("allows touch selection and releases active work on window blur or unmount", () => {
    const { queued } = animationFrames();
    const select = vi.fn();
    const { unmount } = render(<button onClick={select}>Select<CalibrationThumbnail kind="luts" display={lookup("eight", [1369, 1369])} /></button>);
    const target = screen.getByRole("button");
    pointer(target, "pointerenter", 60, 40, "touch");
    pointer(target, "pointermove", 70, 50, "touch");
    fireEvent.click(target);
    expect(select).toHaveBeenCalledOnce();
    expect(queued.size).toBe(0);
    expect(target.querySelector(".is-tilting")).toBeNull();
    pointer(target, "pointerenter", 75, 50);
    act(() => { window.dispatchEvent(new Event("blur")); });
    expect(queued.size).toBe(0);
    expect(target.querySelector(".is-tilting")).toBeNull();
    pointer(target, "pointerenter", 75, 50);
    expect(queued.size).toBe(1);
    unmount();
    expect(queued.size).toBe(0);
  });
});

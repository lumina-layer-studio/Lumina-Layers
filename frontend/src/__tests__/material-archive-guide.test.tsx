import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MaterialArchiveGuide from "../components/ui/MaterialArchiveGuide";
import { useSettingsStore } from "../stores/settingsStore";
import { dismissMaterialGuide } from "../stores/materialGuideStore";

describe("material archive migration guide", () => {
  beforeEach(() => {
    localStorage.removeItem("lumina.material-archive-guide.dismissed.v1");
    useSettingsStore.setState({ language: "zh" });
  });
  it("explains calibration only on request and lets the user start finding profiles", () => {
    const onFind = vi.fn();
    render(<MaterialArchiveGuide onFind={onFind} />);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查找我的耗材" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "试试耗材档案配色" }));
    expect(screen.queryByText(/梯度卡用于建立单种耗材/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "了解梯度卡" }));
    expect(screen.getByText(/日常转换直接勾选档案/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "查找我的耗材" }));
    expect(onFind).toHaveBeenCalledOnce();
  });
  it("removes the converter hint after dismissal and keeps manual help in the library", async () => {
    const page = render(<MaterialArchiveGuide />);
    fireEvent.click(screen.getByRole("button", { name: "关闭引导，不再提示" }));
    expect(page.container).toBeEmptyDOMElement();
    page.unmount();
    const reopenedPage = render(<MaterialArchiveGuide />);
    expect(reopenedPage.container).toBeEmptyDOMElement();
    reopenedPage.unmount();
    render(<MaterialArchiveGuide compact />);
    expect(screen.queryByRole("button", { name: "查找我的耗材" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "了解耗材档案" }));
    expect(screen.getByRole("button", { name: "查找我的耗材" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "关闭引导，不再提示" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "了解耗材档案" })).toBeVisible());
  });
  it("does not prompt again after the user has opened the explanation", () => {
    const page = render(<MaterialArchiveGuide />);
    fireEvent.click(screen.getByRole("button", { name: "试试耗材档案配色" }));
    page.unmount();
    const revisit = render(<MaterialArchiveGuide />);
    expect(revisit.container).toBeEmptyDOMElement();
  });
  it("does not prompt after a completed trial", () => {
    dismissMaterialGuide();
    const page = render(<MaterialArchiveGuide />);
    expect(page.container).toBeEmptyDOMElement();
  });
});

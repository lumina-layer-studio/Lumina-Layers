import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import AdvancedSettings from "../components/sections/AdvancedSettings";
import { useConverterStore } from "../stores/converter";

beforeEach(() => {
  useConverterStore.setState({
    enable_cleanup: true,
    separate_backing: false,
    hue_enable: false,
    use_lut_constrained: false,
    auto_dynamic_range: false,
    high_precision_3d_preview: false,
    chroma_gate: 15,
    quantize_colors_unlocked: false,
    source_version: "legacy",
    materialDynamicLayerCountEnabled: false,
  } as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AdvancedSettings — LUT-Constrained K-Means toggle", () => {
  it("renders the precise color matching checkbox", () => {
    render(<AdvancedSettings />);
    expect(
      screen.getByRole("switch", { name: /高精度颜色匹配/ }),
    ).toBeInTheDocument();
  });

  it("defaults to unchecked", () => {
    render(<AdvancedSettings />);
    const checkbox = screen.getByRole("switch", {
      name: /高精度颜色匹配/,
    });
    expect(checkbox).not.toBeChecked();
    expect(useConverterStore.getState().use_lut_constrained).toBe(false);
  });

  it("toggles store state on click", () => {
    render(<AdvancedSettings />);
    const checkbox = screen.getByRole("switch", {
      name: /高精度颜色匹配/,
    });

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().use_lut_constrained).toBe(true);

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().use_lut_constrained).toBe(false);
  });

  it("disables hue protection checkbox when precise matching is on", () => {
    useConverterStore.setState({ use_lut_constrained: true } as never);
    render(<AdvancedSettings />);

    const hueCheckbox = screen.getByRole("switch", {
      name: /色相保护/,
    });
    expect(hueCheckbox).toBeDisabled();
    expect(hueCheckbox).not.toBeChecked();
  });

  it("renders the auto dynamic range checkbox", () => {
    render(<AdvancedSettings />);
    const checkbox = screen.getByRole("switch", {
      name: /自动动态范围/,
    });
    expect(checkbox).toBeInTheDocument();
    expect(checkbox).not.toBeChecked();
    expect(useConverterStore.getState().auto_dynamic_range).toBe(false);
  });

  it("toggles auto dynamic range store state on click", () => {
    render(<AdvancedSettings />);
    const checkbox = screen.getByRole("switch", {
      name: /自动动态范围/,
    });

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().auto_dynamic_range).toBe(true);

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().auto_dynamic_range).toBe(false);
  });

  it("toggles high-precision 3D preview store state on click", () => {
    render(<AdvancedSettings />);
    const checkbox = screen.getByRole("switch", {
      name: /3D高精度颜色预览/,
    });

    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().high_precision_3d_preview).toBe(true);

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().high_precision_3d_preview).toBe(false);
  });

  it("hides chroma gate slider when precise matching is enabled", () => {
    useConverterStore.setState({
      use_lut_constrained: true,
      hue_enable: true,
    } as never);
    render(<AdvancedSettings />);

    expect(
      screen.queryByRole("slider", { name: /暗色彩度门槛/ }),
    ).not.toBeInTheDocument();
  });

  it("disables hue and hides chroma while exact dynamic material matching owns scoring", () => {
    useConverterStore.setState({
      source_version: "material",
      materialDynamicLayerCountEnabled: true,
      hue_enable: true,
      use_lut_constrained: false,
    } as never);

    render(<AdvancedSettings />);

    const hueCheckbox = screen.getByRole("switch", { name: /色相保护/ });
    expect(hueCheckbox).toBeDisabled();
    expect(hueCheckbox).not.toBeChecked();
    expect(
      screen.queryByRole("slider", { name: /暗色彩度门槛/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "动态叠层模式下，色相保护和暗色彩度修正不可用。",
    );
  });

  it("restores hue availability outside material mode without resurrecting it on return", () => {
    useConverterStore.setState({
      source_version: "legacy",
      materialDynamicLayerCountEnabled: true,
      hue_enable: false,
    } as never);

    render(<AdvancedSettings />);

    const hueCheckbox = screen.getByRole("switch", { name: /色相保护/ });
    expect(hueCheckbox).toBeEnabled();
    fireEvent.click(hueCheckbox);
    expect(useConverterStore.getState().hue_enable).toBe(true);

    act(() => {
      useConverterStore.getState().setSourceVersion("material");
    });

    expect(hueCheckbox).toBeDisabled();
    expect(hueCheckbox).not.toBeChecked();
    expect(useConverterStore.getState().hue_enable).toBe(false);
  });
});

describe("AdvancedSettings — 30-layer unlock warning", () => {
  const unlockSwitch = () => screen.getByRole("switch", { name: "解锁 30 层叠色" });

  it("asks before unlocking and unlocks only on confirm", () => {
    useConverterStore.setState({ materialLayersUnlocked: false });
    render(<AdvancedSettings />);

    fireEvent.click(unlockSwitch());
    expect(screen.getByTestId("material-layer-unlock-dialog")).toBeInTheDocument();
    expect(screen.getByText(/高保真和像素模式的模型固定按 0\.08 mm/)).toBeInTheDocument();
    expect(useConverterStore.getState().materialLayersUnlocked).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "解锁" }));
    expect(useConverterStore.getState().materialLayersUnlocked).toBe(true);
    expect(screen.queryByTestId("material-layer-unlock-dialog")).not.toBeInTheDocument();
  });

  it("stays locked when the warning is cancelled", () => {
    useConverterStore.setState({ materialLayersUnlocked: false });
    render(<AdvancedSettings />);

    fireEvent.click(unlockSwitch());
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(useConverterStore.getState().materialLayersUnlocked).toBe(false);

    fireEvent.click(unlockSwitch());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(useConverterStore.getState().materialLayersUnlocked).toBe(false);
    expect(screen.queryByTestId("material-layer-unlock-dialog")).not.toBeInTheDocument();
  });

  it("locks again without asking", () => {
    useConverterStore.setState({ materialLayersUnlocked: true });
    render(<AdvancedSettings />);

    fireEvent.click(unlockSwitch());
    expect(screen.queryByTestId("material-layer-unlock-dialog")).not.toBeInTheDocument();
    expect(useConverterStore.getState().materialLayersUnlocked).toBe(false);
  });
});

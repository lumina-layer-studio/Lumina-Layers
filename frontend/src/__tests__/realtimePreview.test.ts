import { describe, it, expect, beforeEach } from "vitest";
import { computeThicknessScale } from "../utils/scaleUtils";
import { useConverterStore } from "../stores/converterStore";

// ========== computeThicknessScale 单元测试 ==========

describe("computeThicknessScale", () => {
  it("当前厚度为预览厚度两倍 → 返回 2.0", () => {
    expect(computeThicknessScale(2.4, 1.2)).toBeCloseTo(2.0, 10);
  });

  it("当前厚度为预览厚度一半 → 返回 0.5", () => {
    expect(computeThicknessScale(0.6, 1.2)).toBeCloseTo(0.5, 10);
  });

  it("当前厚度等于预览厚度 → 返回 1.0", () => {
    expect(computeThicknessScale(1.2, 1.2)).toBeCloseTo(1.0, 10);
  });

  it("previewThickness 为 null → 返回 1.0", () => {
    expect(computeThicknessScale(1.2, null)).toBe(1.0);
  });

  it("previewThickness 为 0 → 返回 1.0", () => {
    expect(computeThicknessScale(1.2, 0)).toBe(1.0);
  });

  it("previewThickness 为负数 → 返回 1.0", () => {
    expect(computeThicknessScale(1.2, -1.0)).toBe(1.0);
  });
});

// ========== converterStore preview_spacer_thick 单元测试 ==========

describe("converterStore preview_spacer_thick", () => {
  beforeEach(() => {
    useConverterStore.setState({
      preview_spacer_thick: null,
      spacer_thick: 1.2,
    });
  });

  it("初始值为 null", () => {
    const state = useConverterStore.getState();
    expect(state.preview_spacer_thick).toBeNull();
  });

  it("setSpacerThick 不影响 preview_spacer_thick", () => {
    useConverterStore.getState().setSpacerThick(2.0);
    const state = useConverterStore.getState();
    expect(state.preview_spacer_thick).toBeNull();
    expect(state.spacer_thick).toBeCloseTo(2.0, 5);
  });
});

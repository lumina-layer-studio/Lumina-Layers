import { beforeEach, describe, expect, it } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

import KeychainLoopSettings from "../components/sections/KeychainLoopSettings";
import { useConverterStore } from "../stores/converter";
import { buildGenerateParams } from "../stores/converter/requests";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";

describe("KeychainLoopSettings", () => {
  beforeEach(() => {
    useConverterStore.setState({
      add_loop: false,
      largeFormatEnabled: false,
      puzzleEnabled: false,
      enable_fridge_magnet: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      loop_angle: 0,
      loop_offset_x: 0,
      loop_offset_y: 0,
    } as never);
  });

  it("disables the loop toggle while fridge magnet mode is enabled", () => {
    useConverterStore.setState({
      enable_fridge_magnet: true,
    } as never);

    render(<KeychainLoopSettings />);

    expect(
      screen.getByRole("switch", { name: "添加挂件环" }),
    ).toBeDisabled();
  });

  it("turns off an active ring when Large Format is enabled", () => {
    render(<KeychainLoopSettings />);
    const ringSwitch = screen.getByRole("switch", { name: "添加挂件环" });
    fireEvent.click(ringSwitch);
    expect(ringSwitch).toBeChecked();

    act(() => useConverterStore.getState().setLargeFormatEnabled(true));
    expect(useConverterStore.getState()).toMatchObject({ largeFormatEnabled: true, add_loop: false });
    expect(ringSwitch).toBeDisabled();
    expect(ringSwitch).not.toBeChecked();
    expect(screen.getByText("大画幅分块模式下不支持挂件环。")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "Y 偏移 value" })).not.toBeInTheDocument();

    act(() => useConverterStore.getState().setAddLoop(true));
    expect(useConverterStore.getState().add_loop).toBe(false);
    act(() => useConverterStore.getState().setLargeFormatEnabled(false));
    expect(ringSwitch).toBeEnabled();
    expect(ringSwitch).not.toBeChecked();
    fireEvent.click(ringSwitch);
    expect(ringSwitch).toBeChecked();
  });

  it("restores an older document with Large Format active and the ring turned off", () => {
    const state = useConverterStore.getState();
    state.commitProjectRestore({ ...state, largeFormatEnabled: true, add_loop: true, loop_offset_y: -4 });
    expect(useConverterStore.getState()).toMatchObject({
      largeFormatEnabled: true, add_loop: false, loop_offset_y: -4,
    });
  });

  it("excludes a ring from a tiled request even if a stale state still contains both flags", () => {
    const state = { ...useConverterStore.getState(), add_loop: true };
    const source = { source_kind: "legacy_single", lut_name: "test-lut" } as const;
    const ordinary = buildGenerateParams(state, DEFAULT_SETTINGS, source, undefined, undefined);
    const tiled = buildGenerateParams({ ...state, largeFormatEnabled: true }, DEFAULT_SETTINGS, source, undefined, undefined);
    expect(ordinary.add_loop).toBe(true);
    expect(tiled.add_loop).toBe(false);
  });
});

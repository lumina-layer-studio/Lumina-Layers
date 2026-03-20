import { describe, expect, it } from "vitest";
import { resolveWorkspaceMode } from "../hooks/useWorkspaceMode";

describe("resolveWorkspaceMode", () => {
  it("treats 1080p desktops as compact workspaces for denser control layouts", () => {
    expect(resolveWorkspaceMode({ width: 1920, height: 1080, dpr: 1 })).toBe("compact");
  });

  it("treats 4K at high scaling as compact because the effective viewport is reduced", () => {
    expect(resolveWorkspaceMode({ width: 1536, height: 864, dpr: 2.5 })).toBe("compact");
  });

  it("treats regular 1440p desktops as standard", () => {
    expect(resolveWorkspaceMode({ width: 2560, height: 1440, dpr: 1 })).toBe("standard");
  });

  it("treats ultrawide desktops as wide", () => {
    expect(resolveWorkspaceMode({ width: 3440, height: 1440, dpr: 1 })).toBe("wide");
  });
});

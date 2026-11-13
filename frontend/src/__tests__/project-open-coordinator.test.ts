import { describe, expect, it } from "vitest";
import { createOpenRequestCoordinator } from "../project/openRequestCoordinator";

describe("project open request coordinator", () => {
  it("atomically claims one native request across event and promise delivery", () => {
    const coordinator = createOpenRequestCoordinator();

    expect(coordinator.claim("request-1")).toBe(true);
    expect(coordinator.claim("request-1")).toBe(false);
    expect(coordinator.claim("request-1")).toBe(false);
  });

  it("does not deduplicate browser opens without a native request id", () => {
    const coordinator = createOpenRequestCoordinator();

    expect(coordinator.claim(null)).toBe(true);
    expect(coordinator.claim(null)).toBe(true);
  });
});

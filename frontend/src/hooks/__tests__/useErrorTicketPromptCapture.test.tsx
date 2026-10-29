import { beforeEach, describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";

import {
  describeThrownValue,
  useErrorTicketPromptCapture,
} from "../useErrorTicketPromptCapture";
import { useErrorTicketPromptStore } from "../../stores/errorTicketPromptStore";
import { markSceneErrorHandled } from "../../utils/handledSceneErrors";

function dispatchRejection(reason: unknown) {
  const event = new Event("unhandledrejection") as Event & { reason: unknown };
  event.reason = reason;
  window.dispatchEvent(event);
}

describe("useErrorTicketPromptCapture", () => {
  beforeEach(() => {
    useErrorTicketPromptStore.getState()._resetForTests();
  });

  it("forwards uncaught errors to the prompt store", () => {
    renderHook(() => useErrorTicketPromptCapture(true));

    window.dispatchEvent(
      new ErrorEvent("error", { error: new TypeError("boom"), message: "boom" }),
    );

    expect(useErrorTicketPromptStore.getState().pending).toMatchObject({
      kind: "client",
      message: "boom",
    });
  });

  it("forwards unhandled promise rejections", () => {
    renderHook(() => useErrorTicketPromptCapture(true));

    dispatchRejection(new Error("async failure"));

    expect(useErrorTicketPromptStore.getState().pending?.message).toBe("async failure");
  });

  it("does not offer a duplicate ticket for a recovered scene error", () => {
    renderHook(() => useErrorTicketPromptCapture(true));
    const error = new Error("Environment unavailable");
    markSceneErrorHandled(error);
    window.dispatchEvent(new ErrorEvent("error", { error }));
    expect(useErrorTicketPromptStore.getState().pending).toBeNull();

    // Identical text from a different, uncaught failure must still be reported.
    window.dispatchEvent(new ErrorEvent("error", { error: new Error(error.message) }));
    expect(useErrorTicketPromptStore.getState().pending?.message).toBe(error.message);
  });

  it("does not listen when disabled or after unmount", () => {
    const { rerender, unmount } = renderHook(
      ({ enabled }) => useErrorTicketPromptCapture(enabled),
      { initialProps: { enabled: false } },
    );
    dispatchRejection(new Error("ignored while disabled"));
    expect(useErrorTicketPromptStore.getState().pending).toBeNull();

    rerender({ enabled: true });
    unmount();
    dispatchRejection(new Error("ignored after unmount"));
    expect(useErrorTicketPromptStore.getState().pending).toBeNull();
  });
});

describe("describeThrownValue", () => {
  it("handles errors, strings, and unknown values", () => {
    expect(describeThrownValue(new Error("e"))).toBe("e");
    expect(describeThrownValue("plain")).toBe("plain");
    expect(describeThrownValue({ code: 1 }, "fallback")).toBe("fallback");
  });
});

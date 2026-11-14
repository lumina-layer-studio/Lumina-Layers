// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const postMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  default: {
    post: postMock,
  },
}));

import { beaconCloseSession, isSessionCloseRequested } from "../api/session";

const originalSendBeaconDescriptor = Object.getOwnPropertyDescriptor(
  navigator,
  "sendBeacon",
);

function setSendBeacon(sendBeacon: Navigator["sendBeacon"] | undefined): void {
  Object.defineProperty(navigator, "sendBeacon", {
    configurable: true,
    value: sendBeacon,
  });
}

function restoreSendBeacon(): void {
  if (originalSendBeaconDescriptor) {
    Object.defineProperty(
      navigator,
      "sendBeacon",
      originalSendBeaconDescriptor,
    );
    return;
  }

  delete (navigator as Partial<Navigator>).sendBeacon;
}

describe("session API beacon close", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    postMock.mockResolvedValue({ data: {} });
  });

  afterEach(() => {
    restoreSendBeacon();
  });

  it("falls back to session close when sendBeacon cannot queue the request", async () => {
    const sendBeaconMock = vi.fn(() => false);
    setSendBeacon(sendBeaconMock);

    beaconCloseSession("session-beacon-false", ["download-1", "preview-1"]);
    await Promise.resolve();

    expect(sendBeaconMock).toHaveBeenCalledOnce();
    expect(postMock).toHaveBeenCalledOnce();
    expect(postMock).toHaveBeenCalledWith(
      "/session/close",
      {
        session_id: "session-beacon-false",
        keep_file_ids: ["download-1", "preview-1"],
      },
      { timeout: 3_600_000, suppressErrorTicket: true },
    );
    expect(isSessionCloseRequested("session-beacon-false")).toBe(true);
  });
});

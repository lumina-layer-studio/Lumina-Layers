import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  afterEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  WorkshopFrame,
  type WorkshopFrameModule,
} from "../workshop/runtime/WorkshopFrame";
import {
  WORKSHOP_RUNTIME_CSP,
  canRunWorkshopInBrowser,
  desktopModuleUrl,
  isWorkshopApiCompatible,
} from "../workshop/runtime/health";
import type { WorkshopMessagePort } from "../workshop/runtime/rpcHost";
import { useWorkshopProjectRuntime } from "../project/workshopRuntime";

class FakeHostPort implements WorkshopMessagePort {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onmessageerror: ((event: MessageEvent) => void) | null = null;
  readonly postMessage = vi.fn();
  readonly start = vi.fn();
  readonly close = vi.fn();
}

function installedFixture(
  overrides: Partial<WorkshopFrameModule> = {},
): WorkshopFrameModule {
  return {
    moduleId: "fixture.hello",
    moduleVersion: "1.0.0",
    displayName: "Fixture Hello",
    source: "fixture",
    official: false,
    enabled: true,
    runtimeUrl:
      "/api/workshop/v1/modules/fixture.hello/1.0.0/runtime",
    browserRuntimeHtml:
      "<html><head></head><body><script>globalThis.fixture=true</script></body></html>",
    workshopApi: {
      min: "1.0.0",
      maxExclusive: "2.0.0",
    },
    permissions: [],
    candidate: false,
    previousVersion: null,
    consecutiveStartFailures: 0,
    ...overrides,
  };
}

function postReady(
  source: MessageEventSource | null,
  overrides: Partial<{
    moduleId: string;
    moduleVersion: string;
    apiVersion: string;
    events: string[];
    features: string[];
    projectSnapshotProtocol: number;
  }> = {},
): void {
  const event = new MessageEvent("message", {
    data: {
      type: "lumina.workshop.ready",
      moduleId: "fixture.hello",
      moduleVersion: "1.0.0",
      apiVersion: "1.0.0",
      ...overrides,
    },
  });
  Object.defineProperty(event, "source", { value: source });
  window.dispatchEvent(event);
}

function rpcRequest(
  method:
    | "image.pick"
    | "status.progress"
    | "lifecycle.ready"
    | "colorLibrary.read"
    | "backend.list",
  payload: unknown,
  requestId: string,
) {
  return {
    protocol: "lumina-workshop-rpc",
    version: 1,
    kind: "request",
    requestId,
    method,
    payload,
  };
}

function channelFixture() {
  const port1 = new FakeHostPort();
  const port2 = {
    close: vi.fn(),
  } as unknown as MessagePort;
  return {
    port1,
    port2,
    createChannel: vi.fn(() => ({ port1, port2 })),
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("WorkshopFrame", () => {
  it("keeps project snapshots and backend tasks connected in the same frame", async () => {
    const channel = channelFixture();
    const listTasks = vi.fn().mockResolvedValue([]);
    const view = render(
      <WorkshopFrame
        module={installedFixture({
          hasBackend: true,
          permissions: ["project.storage"],
          projectSnapshotProtocol: 1,
          projectSnapshotSchemas: ["editor/v1"],
        })}
        handlers={{ "backend.list": listTasks }}
        createChannel={channel.createChannel}
      />,
    );
    const iframe = screen.getByTitle("Fixture Hello") as HTMLIFrameElement;
    fireEvent.load(iframe);
    act(() => {
      postReady(iframe.contentWindow, {
        apiVersion: "1.1.0",
        features: ["backend.tasks"],
        projectSnapshotProtocol: 1,
      });
    });
    await waitFor(() => expect(channel.port1.start).toHaveBeenCalledTimes(1));
    act(() => {
      channel.port1.onmessage?.(new MessageEvent("message", {
        data: rpcRequest("lifecycle.ready", {}, "ready"),
      }));
    });
    await waitFor(() => expect(useWorkshopProjectRuntime.getState().current).not.toBeNull());
    act(() => {
      channel.port1.onmessage?.(new MessageEvent("message", {
        data: rpcRequest("backend.list", {}, "backend-list"),
      }));
    });
    await waitFor(() => expect(channel.port1.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ requestId: "backend-list", ok: true, result: [] }),
    ));
    expect(listTasks).toHaveBeenCalledTimes(1);

    const project = useWorkshopProjectRuntime.getState().current!;
    const capture = project.capture();
    const captureRequest = channel.port1.postMessage.mock.calls.at(-1)![0] as { requestId: string };
    channel.port1.onmessage?.(new MessageEvent("message", {
      data: {
        protocol: "lumina-workshop-project", version: 1, kind: "response",
        requestId: captureRequest.requestId, ok: true,
        result: { schemaVersion: "editor/v1", state: { cells: [1, 2] } },
      },
    }));
    await expect(capture).resolves.toEqual({ schemaVersion: "editor/v1", state: { cells: [1, 2] } });
    view.unmount();
    expect(useWorkshopProjectRuntime.getState().current).toBeNull();
  });

  it.each([
    ["official Registry", "registry", true, "browser", true],
    ["official seed", "seed", true, "browser", true],
    ["community Registry", "registry", false, "browser", false],
    ["official GitHub", "github", true, "browser", false],
    ["official local", "local", true, "browser", false],
    ["desktop community", "registry", false, "desktop-secure", true],
    ["fixture", "fixture", false, "browser", true],
    [
      "unsafe local",
      "local",
      false,
      "browser-unsafe-development",
      true,
    ],
  ] as const)("enforces the browser trust matrix for %s", (
    _label,
    source,
    official,
    mode,
    expected,
  ) => {
    expect(canRunWorkshopInBrowser(source, official, mode)).toBe(
      expected,
    );
  });

  it("pushes live UI state only to capable modules without reloading their frame", async () => {
    const capableChannel = channelFixture();
    const initialState = {
      locale: "zh-CN" as const,
      theme: "dark" as const,
      tokens: { "--lumina-surface": "#111827" },
    };
    const nextState = {
      locale: "en-US" as const,
      theme: "light" as const,
      tokens: { "--lumina-surface": "#ffffff" },
    };
    const view = render(
      <WorkshopFrame
        module={installedFixture()}
        uiState={initialState}
        createChannel={capableChannel.createChannel}
      />,
    );
    const iframe = screen.getByTitle("Fixture Hello");
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow, {
        events: ["ui.stateChanged"],
      });
    });
    await waitFor(() =>
      expect(capableChannel.port1.start).toHaveBeenCalledTimes(1),
    );
    capableChannel.port1.postMessage.mockClear();

    view.rerender(
      <WorkshopFrame
        module={installedFixture()}
        uiState={nextState}
        createChannel={capableChannel.createChannel}
      />,
    );

    await waitFor(() =>
      expect(capableChannel.port1.postMessage).toHaveBeenCalledWith({
        protocol: "lumina-workshop-rpc",
        version: 1,
        kind: "event",
        event: "ui.stateChanged",
        payload: nextState,
      }),
    );
    expect(screen.getByTitle("Fixture Hello")).toBe(iframe);
    expect(capableChannel.createChannel).toHaveBeenCalledTimes(1);
    expect(capableChannel.port1.close).not.toHaveBeenCalled();
  });

  it("does not push UI state events to legacy modules", async () => {
    const channel = channelFixture();
    const module = installedFixture();
    const view = render(
      <WorkshopFrame
        module={module}
        uiState={{ locale: "zh-CN", theme: "dark", tokens: {} }}
        createChannel={channel.createChannel}
      />,
    );
    const iframe = screen.getByTitle("Fixture Hello");
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow);
    });
    await waitFor(() =>
      expect(channel.port1.start).toHaveBeenCalledTimes(1),
    );
    channel.port1.postMessage.mockClear();

    view.rerender(
      <WorkshopFrame
        module={module}
        uiState={{ locale: "en-US", theme: "light", tokens: {} }}
        createChannel={channel.createChannel}
      />,
    );

    await act(async () => Promise.resolve());
    expect(channel.port1.postMessage).not.toHaveBeenCalled();
    expect(screen.getByTitle("Fixture Hello")).toBe(iframe);
  });

  it("fills the host without a fixed iframe height or framed chrome", async () => {
    render(<WorkshopFrame module={installedFixture()} />);

    const iframe = await screen.findByTitle("Fixture Hello");
    const runtimeShell = iframe.parentElement as HTMLElement;
    expect(runtimeShell).toHaveClass(
      "relative",
      "h-full",
      "min-h-0",
      "overflow-hidden",
    );
    expect(iframe).toHaveClass(
      "h-full",
      "min-h-0",
      "w-full",
      "flex-1",
      "border-0",
      "rounded-none",
    );
    expect(iframe).not.toHaveClass("min-h-[560px]", "rounded-lg");
  });

  it("accepts ready only from the current iframe window and matching identity", async () => {
    const channel = channelFixture();
    window.localStorage.setItem("outside-frame", "kept");
    const setItem = vi.spyOn(
      Storage.prototype,
      "setItem",
    );

    render(
      <WorkshopFrame
        module={installedFixture()}
        createChannel={channel.createChannel}
      />,
    );
    const iframe = screen.getByTitle("Fixture Hello");
    expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
    expect(iframe.getAttribute("sandbox")).not.toContain(
      "allow-same-origin",
    );
    expect(iframe).toHaveAttribute("referrerpolicy", "no-referrer");
    const srcDoc = iframe.getAttribute("srcdoc") ?? "";
    expect(srcDoc.indexOf(WORKSHOP_RUNTIME_CSP)).toBeGreaterThanOrEqual(
      0,
    );
    expect(srcDoc.indexOf(WORKSHOP_RUNTIME_CSP)).toBeLessThan(
      srcDoc.indexOf("<script>"),
    );

    fireEvent.load(iframe);
    const childWindow = (
      iframe as HTMLIFrameElement
    ).contentWindow;
    expect(childWindow).not.toBeNull();
    const connectPort = vi.spyOn(childWindow!, "postMessage");

    act(() => {
      postReady(window, {
        moduleId: "fixture.hello",
        moduleVersion: "1.0.0",
      });
      postReady(childWindow, {
        moduleId: "other.module",
        moduleVersion: "1.0.0",
      });
      postReady(childWindow, {
        moduleId: "fixture.hello",
        moduleVersion: "9.0.0",
      });
      postReady(childWindow, {
        apiVersion: "2.0.0",
      });
    });
    expect(connectPort).not.toHaveBeenCalled();

    act(() => {
      postReady(childWindow);
    });
    await waitFor(() =>
      expect(connectPort).toHaveBeenCalledTimes(1),
    );
    act(() => {
      postReady(childWindow);
    });
    expect(channel.createChannel).toHaveBeenCalledTimes(1);
    expect(setItem).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("outside-frame")).toBe("kept");
  });

  it("terminates a frame that misses the ten second handshake", async () => {
    vi.useFakeTimers();
    const onStartFailure = vi.fn();
    render(
      <WorkshopFrame
        module={installedFixture()}
        onStartFailure={onStartFailure}
      />,
    );
    fireEvent.load(screen.getByTitle("Fixture Hello"));

    await act(async () => {
      vi.advanceTimersByTime(10_001);
    });

    expect(screen.getByText("模块启动超时")).toBeInTheDocument();
    expect(screen.queryByTitle("Fixture Hello")).not.toBeInTheDocument();
    expect(onStartFailure).toHaveBeenCalledWith(
      expect.objectContaining({
        moduleId: "fixture.hello",
        moduleVersion: "1.0.0",
        reason: "handshake-timeout",
      }),
    );
  });

  it("connects a runtime whose single ready message precedes the frame load event", async () => {
    vi.useFakeTimers();
    const channel = channelFixture();
    const onStartFailure = vi.fn();
    render(
      <WorkshopFrame
        module={installedFixture()}
        createChannel={channel.createChannel}
        onStartFailure={onStartFailure}
      />,
    );
    const iframe = screen.getByTitle(
      "Fixture Hello",
    ) as HTMLIFrameElement;
    const connectPort = vi.spyOn(iframe.contentWindow!, "postMessage");

    act(() => {
      postReady(iframe.contentWindow);
    });
    expect(connectPort).toHaveBeenCalledTimes(1);
    expect(connectPort).toHaveBeenCalledWith(
      expect.objectContaining({ type: "lumina.workshop.connect" }),
      "*",
      [channel.port2],
    );

    fireEvent.load(iframe);
    act(() => {
      postReady(iframe.contentWindow);
    });
    await act(async () => {
      vi.advanceTimersByTime(10_001);
    });

    expect(channel.createChannel).toHaveBeenCalledTimes(1);
    expect(connectPort).toHaveBeenCalledTimes(1);
    expect(onStartFailure).not.toHaveBeenCalled();
    expect(screen.queryByText("模块启动超时")).not.toBeInTheDocument();
    expect(screen.getByTitle("Fixture Hello")).toBe(iframe);
  });

  it("still connects when the frame load event precedes ready", () => {
    vi.useFakeTimers();
    const channel = channelFixture();
    const onStartFailure = vi.fn();
    render(
      <WorkshopFrame
        module={installedFixture()}
        createChannel={channel.createChannel}
        onStartFailure={onStartFailure}
      />,
    );
    const iframe = screen.getByTitle(
      "Fixture Hello",
    ) as HTMLIFrameElement;
    const connectPort = vi.spyOn(iframe.contentWindow!, "postMessage");

    fireEvent.load(iframe);
    act(() => {
      vi.advanceTimersByTime(9_000);
      postReady(iframe.contentWindow);
    });
    act(() => {
      vi.advanceTimersByTime(2_000);
    });

    expect(connectPort).toHaveBeenCalledTimes(1);
    expect(onStartFailure).not.toHaveBeenCalled();
  });

  it("rejects early ready messages from other windows or mismatched identities", async () => {
    vi.useFakeTimers();
    const channel = channelFixture();
    const onStartFailure = vi.fn();
    const outsider = document.createElement("iframe");
    document.body.appendChild(outsider);
    render(
      <WorkshopFrame
        module={installedFixture()}
        createChannel={channel.createChannel}
        onStartFailure={onStartFailure}
      />,
    );
    const iframe = screen.getByTitle(
      "Fixture Hello",
    ) as HTMLIFrameElement;
    const connectPort = vi.spyOn(iframe.contentWindow!, "postMessage");

    act(() => {
      postReady(window);
      postReady(outsider.contentWindow);
      postReady(null);
      postReady(iframe.contentWindow, { moduleId: "other.module" });
      postReady(iframe.contentWindow, { moduleVersion: "9.0.0" });
      postReady(iframe.contentWindow, { apiVersion: "2.0.0" });
    });
    fireEvent.load(iframe);
    await act(async () => {
      vi.advanceTimersByTime(10_001);
    });

    expect(channel.createChannel).not.toHaveBeenCalled();
    expect(connectPort).not.toHaveBeenCalled();
    expect(onStartFailure).toHaveBeenCalledWith(
      expect.objectContaining({ reason: "handshake-timeout" }),
    );
    outsider.remove();
  });

  it("ignores ready from a replaced frame and accepts only the current one", () => {
    const channel = channelFixture();
    const view = render(
      <WorkshopFrame
        module={installedFixture()}
        createChannel={channel.createChannel}
      />,
    );
    const staleWindow = (
      screen.getByTitle("Fixture Hello") as HTMLIFrameElement
    ).contentWindow;
    view.rerender(
      <WorkshopFrame
        module={installedFixture({ moduleVersion: "1.0.1" })}
        createChannel={channel.createChannel}
      />,
    );
    const current = screen.getByTitle(
      "Fixture Hello",
    ) as HTMLIFrameElement;
    expect(current.contentWindow === staleWindow).toBe(false);
    const connectPort = vi.spyOn(current.contentWindow!, "postMessage");

    act(() => {
      postReady(staleWindow, { moduleVersion: "1.0.1" });
    });
    expect(channel.createChannel).not.toHaveBeenCalled();

    act(() => {
      postReady(current.contentWindow, { moduleVersion: "1.0.1" });
    });
    expect(connectPort).toHaveBeenCalledTimes(1);
  });

  it("closes an early connection on unmount without a later timeout", async () => {
    vi.useFakeTimers();
    const channel = channelFixture();
    const onStartFailure = vi.fn();
    const view = render(
      <WorkshopFrame
        module={installedFixture()}
        createChannel={channel.createChannel}
        onStartFailure={onStartFailure}
      />,
    );
    const iframe = screen.getByTitle(
      "Fixture Hello",
    ) as HTMLIFrameElement;
    act(() => {
      postReady(iframe.contentWindow);
      postReady(iframe.contentWindow);
    });
    expect(channel.createChannel).toHaveBeenCalledTimes(1);
    expect(channel.port1.start).toHaveBeenCalledTimes(1);

    view.unmount();
    await act(async () => {
      vi.advanceTimersByTime(10_001);
    });

    expect(channel.port1.close).toHaveBeenCalledTimes(1);
    expect(channel.port1.onmessage).toBeNull();
    expect(onStartFailure).not.toHaveBeenCalled();
  });

  it("keeps one active port and closes it on unmount", async () => {
    const channel = channelFixture();
    const view = render(
      <WorkshopFrame
        module={installedFixture()}
        createChannel={channel.createChannel}
      />,
    );
    const iframe = screen.getByTitle("Fixture Hello");
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow);
    });
    await waitFor(() =>
      expect(channel.port1.start).toHaveBeenCalledTimes(1),
    );

    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow);
    });
    expect(channel.createChannel).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(channel.port1.close).toHaveBeenCalledTimes(1);
    expect(channel.port1.onmessage).toBeNull();
  });

  it("keeps the active port across semantically identical module props", async () => {
    const channel = channelFixture();
    const imagePick = vi.fn().mockResolvedValue(null);
    const handlers = {
      "image.pick": imagePick,
    };
    const initialPrepareCandidate = vi.fn();
    const moduleOverrides: Partial<WorkshopFrameModule> = {
      permissions: ["image.pick"],
    };
    const view = render(
      <WorkshopFrame
        module={installedFixture(moduleOverrides)}
        handlers={handlers}
        createChannel={channel.createChannel}
        prepareCandidate={initialPrepareCandidate}
        disableVersion={vi.fn()}
        onStartFailure={vi.fn()}
      />,
    );
    const iframe = screen.getByTitle("Fixture Hello");
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow);
    });
    await waitFor(() =>
      expect(channel.port1.start).toHaveBeenCalledTimes(1),
    );

    view.rerender(
      <WorkshopFrame
        module={installedFixture(moduleOverrides)}
        handlers={handlers}
        createChannel={channel.createChannel}
        prepareCandidate={vi.fn()}
        disableVersion={vi.fn()}
        onStartFailure={vi.fn()}
      />,
    );

    expect(channel.port1.close).not.toHaveBeenCalled();
    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest("image.pick", {}, "pick-after-rerender"),
        }),
      );
    });
    await waitFor(() => expect(imagePick).toHaveBeenCalledTimes(1));
  });

  it("snapshots a candidate, renders progress, and activates only after lifecycle.ready", async () => {
    const channel = channelFixture();
    const order: string[] = [];
    const prepareCandidate = vi.fn(async () => {
      order.push("snapshot");
    });
    const activateCandidate = vi.fn(async () => {
      order.push("activate");
    });
    render(
      <WorkshopFrame
        module={installedFixture({
          moduleVersion: "1.1.0",
          candidate: true,
        })}
        createChannel={channel.createChannel}
        prepareCandidate={prepareCandidate}
        activateCandidate={activateCandidate}
      />,
    );

    expect(
      screen.queryByTitle("Fixture Hello"),
    ).not.toBeInTheDocument();
    const iframe = await screen.findByTitle("Fixture Hello");
    expect(prepareCandidate).toHaveBeenCalledTimes(1);
    expect(order).toEqual(["snapshot"]);
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow, {
        moduleVersion: "1.1.0",
      });
    });
    await waitFor(() =>
      expect(channel.port1.start).toHaveBeenCalledTimes(1),
    );
    expect(activateCandidate).not.toHaveBeenCalled();

    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest(
            "status.progress",
            {
              phase: "analyze",
              completed: 1,
              total: 4,
            },
            "progress-1",
          ),
        }),
      );
    });
    expect(await screen.findByText("1 / 4")).toBeInTheDocument();

    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest("lifecycle.ready", {}, "ready-1"),
        }),
      );
    });
    await waitFor(() =>
      expect(activateCandidate).toHaveBeenCalledWith(
        "fixture.hello",
        "1.1.0",
      ),
    );
    expect(order).toEqual(["snapshot", "activate"]);
    expect(screen.queryByText("1 / 4")).not.toBeInTheDocument();
    expect(screen.queryByText("运行中")).not.toBeInTheDocument();
    expect(iframe).toBeInTheDocument();
  });

  it("keeps the active port when a candidate becomes the installed version", async () => {
    const channel = channelFixture();
    const activateCandidate = vi.fn().mockResolvedValue(undefined);
    const progress = vi.fn().mockResolvedValue(undefined);
    const candidateModule = installedFixture({
      moduleVersion: "1.1.0",
      candidate: true,
    });
    const view = render(
      <WorkshopFrame
        module={candidateModule}
        handlers={{ "status.progress": progress }}
        createChannel={channel.createChannel}
        prepareCandidate={vi.fn().mockResolvedValue(undefined)}
        activateCandidate={activateCandidate}
      />,
    );

    const iframe = await screen.findByTitle("Fixture Hello");
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow, {
        moduleVersion: "1.1.0",
      });
    });
    await waitFor(() =>
      expect(channel.port1.start).toHaveBeenCalledTimes(1),
    );

    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest("lifecycle.ready", {}, "ready-1"),
        }),
      );
    });
    await waitFor(() =>
      expect(activateCandidate).toHaveBeenCalledWith(
        "fixture.hello",
        "1.1.0",
      ),
    );

    view.rerender(
      <WorkshopFrame
        module={{ ...candidateModule, candidate: false }}
        handlers={{ "status.progress": progress }}
        createChannel={channel.createChannel}
        prepareCandidate={vi.fn()}
        activateCandidate={activateCandidate}
      />,
    );

    expect(channel.port1.close).not.toHaveBeenCalled();
    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest(
            "status.progress",
            {
              phase: "autosave",
              completed: 1,
              total: 1,
            },
            "progress-after-activation",
          ),
        }),
      );
    });
    await waitFor(() => expect(progress).toHaveBeenCalledTimes(1));
  });

  it("does not repeat candidate activation when the installed runtime restarts", async () => {
    const firstChannel = channelFixture();
    const secondChannel = channelFixture();
    const createChannel = vi
      .fn()
      .mockReturnValueOnce({
        port1: firstChannel.port1,
        port2: firstChannel.port2,
      })
      .mockReturnValueOnce({
        port1: secondChannel.port1,
        port2: secondChannel.port2,
      });
    const prepareCandidate = vi.fn().mockResolvedValue(undefined);
    const activateCandidate = vi.fn().mockResolvedValue(undefined);
    const candidateModule = installedFixture({
      moduleVersion: "1.1.0",
      candidate: true,
    });
    const view = render(
      <WorkshopFrame
        module={candidateModule}
        createChannel={createChannel}
        prepareCandidate={prepareCandidate}
        activateCandidate={activateCandidate}
      />,
    );

    const candidateFrame = await screen.findByTitle("Fixture Hello");
    fireEvent.load(candidateFrame);
    act(() => {
      postReady((candidateFrame as HTMLIFrameElement).contentWindow, {
        moduleVersion: "1.1.0",
      });
    });
    await waitFor(() =>
      expect(firstChannel.port1.start).toHaveBeenCalledTimes(1),
    );
    act(() => {
      firstChannel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest("lifecycle.ready", {}, "ready-candidate"),
        }),
      );
    });
    await waitFor(() =>
      expect(activateCandidate).toHaveBeenCalledTimes(1),
    );

    view.rerender(
      <WorkshopFrame
        module={{
          ...candidateModule,
          candidate: false,
          browserRuntimeHtml:
            "<html><head></head><body>installed restart</body></html>",
        }}
        createChannel={createChannel}
        prepareCandidate={prepareCandidate}
        activateCandidate={activateCandidate}
      />,
    );

    const installedFrame = await screen.findByTitle("Fixture Hello");
    await waitFor(() =>
      expect(installedFrame.getAttribute("srcdoc")).toContain(
        "installed restart",
      ),
    );
    expect(prepareCandidate).toHaveBeenCalledTimes(1);
    fireEvent.load(installedFrame);
    act(() => {
      postReady((installedFrame as HTMLIFrameElement).contentWindow, {
        moduleVersion: "1.1.0",
      });
    });
    await waitFor(() =>
      expect(secondChannel.port1.start).toHaveBeenCalledTimes(1),
    );
    act(() => {
      secondChannel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest("lifecycle.ready", {}, "ready-installed"),
        }),
      );
    });
    await waitFor(() =>
      expect(
        screen.queryByText("正在等待模块就绪"),
      ).not.toBeInTheDocument(),
    );
    expect(installedFrame).toBeInTheDocument();
    expect(activateCandidate).toHaveBeenCalledTimes(1);
  });

  it("disables a version after its third consecutive startup failure", async () => {
    vi.useFakeTimers();
    const disableVersion = vi.fn();
    render(
      <WorkshopFrame
        module={installedFixture({
          consecutiveStartFailures: 2,
        })}
        disableVersion={disableVersion}
      />,
    );
    fireEvent.load(screen.getByTitle("Fixture Hello"));

    await act(async () => {
      vi.advanceTimersByTime(10_001);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(disableVersion).toHaveBeenCalledWith(
      "fixture.hello",
      "1.0.0",
    );
  });

  it("loads an official Registry runtime as same-origin srcDoc", async () => {
    const fetchRuntime = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        "<html><head></head><body><script>globalThis.registry=true</script></body></html>",
        {
          status: 200,
          headers: { "content-type": "text/html; charset=utf-8" },
        },
      ),
    );
    render(
      <WorkshopFrame
        module={installedFixture({
          source: "registry",
          official: true,
          browserRuntimeHtml: null,
        })}
      />,
    );

    const iframe = await screen.findByTitle("Fixture Hello");
    expect(fetchRuntime).toHaveBeenCalledWith(
      "/api/workshop/v1/modules/fixture.hello/1.0.0/runtime",
      {
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
      },
    );
    expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
    expect(iframe.getAttribute("sandbox")).not.toContain(
      "allow-same-origin",
    );
    expect(iframe).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(iframe).not.toHaveAttribute("src");
    const srcDoc = iframe.getAttribute("srcdoc") ?? "";
    expect(srcDoc).toContain("globalThis.registry=true");
    expect(srcDoc).toContain("default-src 'none'");
    expect(srcDoc).toContain("connect-src 'none'");
    expect(srcDoc).toContain("frame-src 'none'");
    expect(srcDoc).toContain("form-action 'none'");
    expect(srcDoc.indexOf(WORKSHOP_RUNTIME_CSP)).toBeGreaterThanOrEqual(
      0,
    );
    expect(srcDoc.indexOf(WORKSHOP_RUNTIME_CSP)).toBeLessThan(
      srcDoc.indexOf("<script>"),
    );
  });

  it.each([
    ["community Registry", "registry", false],
    ["official GitHub", "github", true],
    ["official local", "local", true],
  ] as const)("requires the secure desktop runtime for %s packages", (
    _label,
    source,
    official,
  ) => {
    const loadBrowserRuntime = vi.fn();
    render(
      <WorkshopFrame
        module={installedFixture({
          source,
          official,
          browserRuntimeHtml: null,
        })}
        loadBrowserRuntime={loadBrowserRuntime}
      />,
    );

    expect(
      screen.getByText("此模块需要 Lumina 桌面版才能运行"),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveClass("m-3", "mt-16");
    expect(loadBrowserRuntime).not.toHaveBeenCalled();
    expect(screen.queryByTitle("Fixture Hello")).not.toBeInTheDocument();
  });

  it("keeps official seed modules runnable in browser mode", () => {
    render(
      <WorkshopFrame
        module={installedFixture({
          source: "seed",
          official: true,
        })}
      />,
    );

    expect(screen.getByTitle("Fixture Hello")).toHaveAttribute(
      "sandbox",
      "allow-scripts",
    );
  });

  it("uses the custom scheme for community packages in secure desktop mode", () => {
    render(
      <WorkshopFrame
        module={installedFixture({
          source: "registry",
          official: false,
          browserRuntimeHtml: null,
        })}
        runtimeMode="desktop-secure"
      />,
    );

    expect(screen.getByTitle("Fixture Hello")).toHaveAttribute(
      "src",
      "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
    );
  });

  it("replaces real host data with synthetic handlers in unsafe browser development", async () => {
    const channel = channelFixture();
    const realRead = vi.fn().mockResolvedValue({
      id: "real-library",
    });
    const syntheticRead = vi.fn().mockResolvedValue({
      id: "synthetic-library",
    });
    render(
      <WorkshopFrame
        module={installedFixture({
          source: "local",
          permissions: ["color-library.read"],
        })}
        runtimeMode="browser-unsafe-development"
        handlers={{ "colorLibrary.read": realRead }}
        syntheticHandlers={{
          "colorLibrary.read": syntheticRead,
        }}
        createChannel={channel.createChannel}
      />,
    );
    const iframe = screen.getByTitle("Fixture Hello");
    fireEvent.load(iframe);
    act(() => {
      postReady((iframe as HTMLIFrameElement).contentWindow);
    });
    await waitFor(() =>
      expect(channel.port1.start).toHaveBeenCalledTimes(1),
    );

    act(() => {
      channel.port1.onmessage?.(
        new MessageEvent("message", {
          data: rpcRequest(
            "colorLibrary.read",
            {},
            "library-1",
          ),
        }),
      );
    });
    await waitFor(() =>
      expect(syntheticRead).toHaveBeenCalledTimes(1),
    );
    expect(realRead).not.toHaveBeenCalled();
  });
});

describe("Workshop runtime helpers", () => {
  it("builds one encoded custom-scheme desktop URL", () => {
    expect(
      desktopModuleUrl("fixture.hello", "1.0.0"),
    ).toBe(
      "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
    );
    expect(
      desktopModuleUrl("fixture.hello", "1.0.0+desktop.1"),
    ).toBe(
      "lumina-workshop://fixture.hello/1.0.0+desktop.1/ui/index.html",
    );
  });

  it("accepts only host API versions inside the manifest range", () => {
    expect(
      isWorkshopApiCompatible({
        min: "1.0.0",
        maxExclusive: "2.0.0",
      }),
    ).toBe(true);
    // The host implements Workshop API 1.1.0 (module backends).
    expect(
      isWorkshopApiCompatible({
        min: "1.1.0",
        maxExclusive: "2.0.0",
      }),
    ).toBe(true);
    expect(
      isWorkshopApiCompatible({
        min: "1.2.0",
        maxExclusive: "2.0.0",
      }),
    ).toBe(false);
    expect(
      isWorkshopApiCompatible({
        min: "0.9.0",
        maxExclusive: "1.0.0",
      }),
    ).toBe(false);
  });
});

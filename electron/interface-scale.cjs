"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { randomBytes } = require("node:crypto");
const { isTrustedMainFrameSender } = require("./generated-file-directory.cjs");

const STATE_VERSION = 1;
// Product decision: the OS must not decide how this app is laid out. Every page
// is laid out in the same 1536×864 room (what a 1920×1080 screen at 125% system
// scaling gives other apps), so panels, header and toolbars keep the same share
// of the window on any screen. resolveZoomFactor() converts the display size —
// which already carries the system scaling — into page zoom, cancelling both the
// resolution and the system scaling. Only the user's own preference changes the
// layout; plain percent/100 would hand that decision back to the OS.
const REFERENCE = { width: 1536, height: 864 };
const DEFAULT_PREFERENCE = "100";
// Interface first; each step scales the 100% layout room.
const SCALE_STEPS = Object.freeze(["80", "90", "100", "110", "125", "150", "175"]);
const PREFERENCES = new Set(SCALE_STEPS);
const DEFAULT_WINDOW_SIZE = { width: 1440, height: 900 };
// Smallest page, in CSS pixels, at which the workspace panels and the 3D
// toolbar still sit side by side without covering each other.
const MIN_PAGE_SIZE = { width: 960, height: 620 };
const MAX_WINDOWED_SHARE = 0.9;
const MOVE_SETTLE_MS = 200;
const DISPLAY_EVENTS = ["display-metrics-changed", "display-added", "display-removed"];

function isInterfaceScalePreference(value) {
  return typeof value === "string" && PREFERENCES.has(value);
}

/**
 * Page zoom that lays the page out on the shared reference room.
 * The room is exact: a panel that is 23% of the window stays 23% of the
 * window on every screen, whatever its resolution or system scaling.
 * Display metrics are read only here, and only so they can be cancelled out.
 */
function referenceZoomFactor(displaySize) {
  const width = Number(displaySize?.width);
  const height = Number(displaySize?.height);
  if (!(width > 0 && height > 0)) return 1;
  return Math.min(width / REFERENCE.width, height / REFERENCE.height);
}

/**
 * Page zoom for a preference on a display of the given logical size.
 * 100% is the reference room; other steps are multiples of it.
 * The display is an argument only so it can be cancelled: the preference is
 * the one setting that is allowed to change the layout.
 */
function resolveZoomFactor(preference, displaySize) {
  const percent = isInterfaceScalePreference(preference)
    ? Number(preference)
    : Number(DEFAULT_PREFERENCE);
  const factor = referenceZoomFactor(displaySize) * percent / 100;
  return Math.round(factor * 1000) / 1000;
}

/**
 * Caps the zoom so the minimum page still fits the work area. Without this a
 * high step on a small display would need a window larger than the screen.
 */
function fitZoomFactorToWorkArea(zoomFactor, workArea) {
  const width = Number(workArea?.width);
  const height = Number(workArea?.height);
  if (!(width > 0 && height > 0)) return zoomFactor;
  const largest = Math.min(width / MIN_PAGE_SIZE.width, height / MIN_PAGE_SIZE.height);
  if (zoomFactor <= largest) return zoomFactor;
  return Math.floor(largest * 1000) / 1000;
}

/** Window size that keeps the page at least MIN_PAGE_SIZE at this zoom. */
function resolveMinimumWindowSize(zoomFactor) {
  return {
    width: Math.ceil(MIN_PAGE_SIZE.width * zoomFactor),
    height: Math.ceil(MIN_PAGE_SIZE.height * zoomFactor),
  };
}

/**
 * Bounds that grow an existing window to the minimum size, or null when it is
 * already large enough. On restoration, also fit an OS-enlarged window's position.
 * A raised minimum does not resize an open window on every platform, so the
 * window is grown explicitly. It grows from its
 * top-left corner and moves back inside the work area if that would overflow.
 */
function resolveGrownWindowBounds(bounds, minimum, workArea, fitPosition = false) {
  if (!fitPosition && bounds.width >= minimum.width && bounds.height >= minimum.height) return null;
  const width = Math.max(bounds.width, minimum.width);
  const height = Math.max(bounds.height, minimum.height);
  const area = workArea ?? { x: bounds.x, y: bounds.y, width, height };
  const x = Math.max(area.x, Math.min(bounds.x, area.x + area.width - width));
  const y = Math.max(area.y, Math.min(bounds.y, area.y + area.height - height));
  if (x === bounds.x && y === bounds.y && width === bounds.width && height === bounds.height) return null;
  return { x, y, width, height };
}

/** Next preference for a zoom shortcut; stays put at either end. */
function stepInterfaceScalePreference(preference, direction) {
  if (direction === "reset") return DEFAULT_PREFERENCE;
  const index = SCALE_STEPS.indexOf(isInterfaceScalePreference(preference) ? preference : DEFAULT_PREFERENCE);
  const next = Math.min(SCALE_STEPS.length - 1, Math.max(0, index + (direction === "in" ? 1 : -1)));
  return SCALE_STEPS[next];
}

/**
 * Maps Ctrl (Command on macOS) with +, - or 0 to a zoom direction. Alt is
 * excluded because AltGr arrives as Ctrl+Alt on Windows keyboard layouts.
 */
function interfaceScaleShortcut(input, platform) {
  if (input?.type !== "keyDown" || input.alt) return null;
  if (!(platform === "darwin" ? input.meta : input.control)) return null;
  if (input.key === "+" || input.key === "=") return "in";
  if (input.key === "-" || input.key === "_") return "out";
  if (input.key === "0" || input.code === "Digit0") return "reset";
  return null;
}

function readInterfaceScalePreference(stateFile) {
  try {
    const parsed = JSON.parse(fs.readFileSync(stateFile, "utf8"));
    if (parsed?.schemaVersion === STATE_VERSION && isInterfaceScalePreference(parsed.preference)) {
      return parsed.preference;
    }
  } catch (_) { /* Missing or unreadable state falls back to 100%. */ }
  return DEFAULT_PREFERENCE;
}

function writeInterfaceScalePreference(stateFile, preference) {
  const temporary = `${stateFile}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`;
  try {
    fs.mkdirSync(path.dirname(stateFile), { recursive: true });
    fs.writeFileSync(temporary, `${JSON.stringify({ schemaVersion: STATE_VERSION, preference })}\n`, { flag: "wx" });
    fs.renameSync(temporary, stateFile);
  } finally {
    try { fs.unlinkSync(temporary); } catch (_) { /* Already renamed into place. */ }
  }
}

/**
 * The historical 1440×900 default scaled by the zoom. Windows that would take
 * more than 90% of the work area start maximized; the centered bounds are
 * what un-maximizing restores.
 */
function resolveInitialWindowPlacement(workArea, zoomFactor) {
  const wantedWidth = Math.round(DEFAULT_WINDOW_SIZE.width * zoomFactor);
  const wantedHeight = Math.round(DEFAULT_WINDOW_SIZE.height * zoomFactor);
  const maxWidth = Math.floor(workArea.width * MAX_WINDOWED_SHARE);
  const maxHeight = Math.floor(workArea.height * MAX_WINDOWED_SHARE);
  const width = Math.min(wantedWidth, maxWidth);
  const height = Math.min(wantedHeight, maxHeight);
  return {
    maximize: wantedWidth > maxWidth || wantedHeight > maxHeight,
    bounds: {
      x: workArea.x + Math.round((workArea.width - width) / 2),
      y: workArea.y + Math.round((workArea.height - height) / 2),
      width,
      height,
    },
  };
}

/**
 * Owns the saved preference and keeps the main window's page zoom in line
 * with it and with the display the window is on.
 */
function createInterfaceScaleController({
  screen,
  stateFile,
  platform = process.platform,
  log = () => {},
  logError = () => {},
}) {
  let preference = readInterfaceScalePreference(stateFile);
  let window = null;
  let settleTimer = null;

  const isLive = () => Boolean(window && !window.isDestroyed());
  const currentDisplay = () => (isLive()
    ? screen.getDisplayMatching(window.getBounds())
    : screen.getPrimaryDisplay());

  const effectiveZoomFactor = display =>
    fitZoomFactorToWorkArea(resolveZoomFactor(preference, display.size), display.workArea);

  function apply(fitPosition = false) {
    if (!isLive()) return;
    const display = currentDisplay();
    const factor = effectiveZoomFactor(display);
    const minimum = resolveMinimumWindowSize(factor);
    window.setMinimumSize(minimum.width, minimum.height);
    // Maximized, minimized and full-screen windows take their size from the OS.
    if (!window.isMaximized() && !window.isMinimized() && !window.isFullScreen()) {
      const grown = resolveGrownWindowBounds(window.getBounds(), minimum, display.workArea, fitPosition);
      if (grown) window.setBounds(grown);
    }
    if (Math.abs(window.webContents.getZoomFactor() - factor) < 0.001) return;
    window.webContents.setZoomFactor(factor);
    log(`Interface scale ${preference}: zoom ${factor} on a ${display.size.width}x${display.size.height} display`);
  }

  function choose(next) {
    if (!isInterfaceScalePreference(next)) return false;
    if (next !== preference) {
      preference = next;
      try {
        writeInterfaceScalePreference(stateFile, next);
      } catch (error) {
        logError(`Interface scale not saved: ${error.code || error.message}`);
      }
    }
    apply();
    if (isLive()) window.webContents.send("interface-scale-changed", { preference });
    return true;
  }

  function attach(target) {
    window = target;
    const reapply = () => apply();
    const reapplyAfterMove = () => {
      clearTimeout(settleTimer);
      settleTimer = setTimeout(reapply, MOVE_SETTLE_MS);
    };
    for (const name of DISPLAY_EVENTS) screen.on(name, reapply);
    target.on("move", reapplyAfterMove);
    // macOS can enlarge restored bounds to the minimum without moving them on screen.
    target.on("unmaximize", () => apply(true));
    // setZoomFactor is ignored until the first navigation commits.
    target.webContents.on("did-navigate", reapply);
    target.webContents.on("before-input-event", (event, input) => {
      const direction = interfaceScaleShortcut(input, platform);
      if (!direction) return;
      event.preventDefault();
      choose(stepInterfaceScalePreference(preference, direction));
    });
    target.once("closed", () => {
      clearTimeout(settleTimer);
      for (const name of DISPLAY_EVENTS) screen.off(name, reapply);
      window = null;
    });
  }

  function initialPlacement() {
    const display = screen.getPrimaryDisplay();
    const zoomFactor = effectiveZoomFactor(display);
    return {
      zoomFactor,
      minimumSize: resolveMinimumWindowSize(zoomFactor),
      ...resolveInitialWindowPlacement(display.workArea, zoomFactor),
    };
  }

  return { attach, choose, initialPlacement, preference: () => preference };
}

function getInterfaceScale({ event, window, trustedUrl, controller }) {
  if (!controller) return { status: "error", code: "unavailable" };
  if (!isTrustedMainFrameSender(event, window, trustedUrl)) return { status: "error", code: "denied" };
  return { status: "ok", preference: controller.preference() };
}

function setInterfaceScale({ event, window, trustedUrl, controller, preference }) {
  if (!controller) return { status: "error", code: "unavailable" };
  if (!isTrustedMainFrameSender(event, window, trustedUrl)) return { status: "error", code: "denied" };
  return controller.choose(preference)
    ? { status: "ok", preference: controller.preference() }
    : { status: "error", code: "invalid" };
}

module.exports = {
  MIN_PAGE_SIZE,
  SCALE_STEPS,
  createInterfaceScaleController,
  fitZoomFactorToWorkArea,
  getInterfaceScale,
  interfaceScaleShortcut,
  isInterfaceScalePreference,
  readInterfaceScalePreference,
  resolveGrownWindowBounds,
  resolveInitialWindowPlacement,
  resolveMinimumWindowSize,
  resolveZoomFactor,
  setInterfaceScale,
  stepInterfaceScalePreference,
  writeInterfaceScalePreference,
};

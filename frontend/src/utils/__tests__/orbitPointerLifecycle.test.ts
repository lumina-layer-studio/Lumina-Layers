import { createRequire } from "node:module";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

// Exercise the same dependency instance that Drei uses, without a WebGL renderer.
const requireDrei = createRequire(createRequire(import.meta.url).resolve("@react-three/drei"));
const { OrbitControls } = requireDrei("three-stdlib");
const { PerspectiveCamera } = requireDrei("three");

describe("preview orbit pointer lifecycle", () => {
  let element: HTMLDivElement;
  let controls: InstanceType<typeof OrbitControls>;
  let camera: InstanceType<typeof PerspectiveCamera>;
  let errors: unknown[];
  const captureError = (event: ErrorEvent) => {
    errors.push(event.error);
    event.preventDefault();
  };
  const pointer = (type: string, pointerId: number, pointerType: string, x: number) => {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.assign(event, { pointerId, pointerType, pageX: x, pageY: 100, clientX: x, clientY: 100, button: 0 });
    element.dispatchEvent(event);
  };
  beforeEach(() => {
    errors = [];
    window.addEventListener("error", captureError);
    element = document.createElement("div");
    document.body.appendChild(element);
    element.setPointerCapture = () => {};
    element.hasPointerCapture = () => false;
    element.releasePointerCapture = () => {};
    Object.defineProperties(element, {
      clientHeight: { value: 500 },
      clientWidth: { value: 500 },
    });
    camera = new PerspectiveCamera(50, 1, 0.1, 100);
    camera.position.set(0, 0, 10);
    controls = new OrbitControls(camera, element);
  });
  afterEach(() => {
    controls.dispose();
    element.remove();
    window.removeEventListener("error", captureError);
  });

  it("does not count a mouse drag as the second finger of a pinch", () => {
    pointer("pointerdown", 1, "mouse", 100);
    pointer("pointerdown", 2, "touch", 200);
    pointer("pointermove", 2, "touch", 220);
    expect(errors).toEqual([]);
    expect(camera.position.length()).toBeCloseTo(10);
    pointer("pointerup", 2, "touch", 220);
    const before = camera.position.clone();
    pointer("pointermove", 1, "mouse", 130);
    expect(camera.position.equals(before)).toBe(false);
  });

  it("ignores duplicate pointerdown and keeps a single finger usable", () => {
    pointer("pointerdown", 1, "touch", 100);
    pointer("pointerdown", 1, "touch", 100);
    pointer("pointermove", 1, "touch", 140);
    expect(errors).toEqual([]);
    expect(camera.position.toArray().every(Number.isFinite)).toBe(true);
    expect(camera.position.length()).toBeCloseTo(10);
    expect(camera.position.x).not.toBe(0);
  });

  it("ignores document pointer moves and releases from outside this gesture", () => {
    pointer("pointerdown", 1, "touch", 100);
    const before = camera.position.clone();
    pointer("pointermove", 99, "touch", 300);
    expect(camera.position.equals(before)).toBe(true);
    pointer("pointerup", 99, "touch", 300);
    pointer("pointermove", 1, "touch", 140);
    expect(camera.position.equals(before)).toBe(false);
  });

  it("pinches normally and continues rotating with the remaining finger", () => {
    pointer("pointerdown", 1, "touch", 100);
    pointer("pointerdown", 2, "touch", 200);
    pointer("pointermove", 2, "touch", 250);
    expect(errors).toEqual([]);
    expect(camera.position.length()).toBeLessThan(10);
    pointer("pointerup", 2, "touch", 250);
    const before = camera.position.clone();
    pointer("pointermove", 1, "touch", 140);
    expect(camera.position.equals(before)).toBe(false);
  });

  it("starts a clean gesture after cancellation or reconnecting", () => {
    pointer("pointerdown", 1, "mouse", 100);
    controls.dispose();
    controls.connect(element);
    pointer("pointerdown", 2, "touch", 200);
    pointer("pointermove", 2, "touch", 220);
    expect(errors).toEqual([]);
    expect(camera.position.length()).toBeCloseTo(10);
    pointer("pointercancel", 2, "touch", 220);
    pointer("pointerdown", 3, "touch", 100);
    const before = camera.position.clone();
    pointer("pointermove", 3, "touch", 130);
    expect(camera.position.equals(before)).toBe(false);
  });
});

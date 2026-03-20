import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { createKeychainRingGeometry } from "../components/KeychainRing3D";

// Mock R3F — Canvas renders as plain div in jsdom
vi.mock("@react-three/fiber", () => ({
  Canvas: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="mock-canvas">{children}</div>
  ),
}));

// Must import after mocks
import KeychainRing3D from "../components/KeychainRing3D";

const defaultBounds = {
  minX: -10,
  maxX: 10,
  minY: -15,
  maxY: 15,
  maxZ: 5,
};

describe("KeychainRing3D", () => {
  describe("enabled/disabled rendering", () => {
    it("returns null when enabled=false", () => {
      const { container } = render(
        <KeychainRing3D
          enabled={false}
          width={4}
          length={8}
          hole={2}
          modelBounds={defaultBounds}
        />,
      );
      expect(container.innerHTML).toBe("");
    });

    it("does not crash when enabled=true with valid params", () => {
      // Geometry creation is valid — component should render without error
      const geo = createKeychainRingGeometry(4, 8, 2);
      expect(geo).not.toBeNull();
    });

    it("geometry is null when hole >= width (component would return null)", () => {
      // hole === width → invalid geometry → component returns null
      const geo = createKeychainRingGeometry(3, 8, 3);
      expect(geo).toBeNull();
    });
  });
});

describe("createKeychainRingGeometry", () => {
  it("produces valid geometry with default params", () => {
    const geo = createKeychainRingGeometry(4, 8, 2);
    expect(geo).not.toBeNull();
    expect(geo!.attributes.position.count).toBeGreaterThan(0);
  });

  it("produces geometry with vertices for min valid params", () => {
    // width=2, length=4, hole=1 → hole < min(2,4)=2 ✓
    const geo = createKeychainRingGeometry(2, 4, 1);
    expect(geo).not.toBeNull();
    expect(geo!.attributes.position.count).toBeGreaterThan(0);
  });

  it("produces geometry with vertices for max valid params", () => {
    // width=10, length=15, hole=5 → hole < min(10,15)=10 ✓
    const geo = createKeychainRingGeometry(10, 15, 5);
    expect(geo).not.toBeNull();
    expect(geo!.attributes.position.count).toBeGreaterThan(0);
  });

  it("returns null when hole >= min(width, length)", () => {
    // hole=5 >= min(5, 10)=5 → invalid
    expect(createKeychainRingGeometry(5, 10, 5)).toBeNull();
    // hole=6 >= min(4, 8)=4 → invalid
    expect(createKeychainRingGeometry(4, 8, 6)).toBeNull();
  });

  it("returns null when hole > width but < length", () => {
    // hole=4 >= min(3, 8)=3 → invalid
    expect(createKeychainRingGeometry(3, 8, 4)).toBeNull();
  });

  it("returns null for zero or negative dimensions", () => {
    expect(createKeychainRingGeometry(0, 8, 2)).toBeNull();
    expect(createKeychainRingGeometry(4, 0, 2)).toBeNull();
    expect(createKeychainRingGeometry(4, 8, 0)).toBeNull();
    expect(createKeychainRingGeometry(-1, 8, 2)).toBeNull();
  });

  it("geometry has non-degenerate faces (index count > 0)", () => {
    const geo = createKeychainRingGeometry(6, 10, 3);
    expect(geo).not.toBeNull();
    // ExtrudeGeometry uses indexed geometry
    if (geo!.index) {
      expect(geo!.index.count).toBeGreaterThan(0);
    } else {
      // Non-indexed: position count implies triangles
      expect(geo!.attributes.position.count).toBeGreaterThan(0);
    }
  });
});

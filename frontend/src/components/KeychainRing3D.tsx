/**
 * KeychainRing3D — 3D keychain ring preview component using Three.js ExtrudeGeometry.
 * KeychainRing3D — 使用 Three.js ExtrudeGeometry 的 3D 钥匙扣环预览组件。
 *
 * Renders a rectangle with a circular hole cut out, extruded to match spacer thickness.
 * 渲染一个带圆形孔洞的矩形，拉伸厚度与 spacer 一致。
 */

import { useMemo } from "react";
import * as THREE from "three";

/** Default extrusion depth matching spacer_thick (mm). (默认拉伸深度，匹配 spacer_thick) */
const EXTRUDE_DEPTH = 1.2;

/** Small offset above model top (mm). (模型顶部上方的小偏移量) */
const TOP_OFFSET = 0.1;

/** Number of segments for the circular hole. (圆形孔洞的分段数) */
const HOLE_SEGMENTS = 32;

export interface KeychainRing3DProps {
  enabled: boolean;
  width: number; // mm, 2-10
  length: number; // mm, 4-15
  hole: number; // mm, 1-5
  modelBounds: {
    minX: number;
    maxX: number;
    minY: number;
    maxY: number;
    maxZ: number;
  };
}

/**
 * Create keychain ring geometry: a rectangle with a circular hole extruded to depth.
 * 创建钥匙扣环几何体：带圆形孔洞的矩形拉伸体。
 *
 * @param width - Ring width in mm. (环宽度，毫米)
 * @param length - Ring length in mm. (环长度，毫米)
 * @param hole - Hole diameter in mm. (孔洞直径，毫米)
 * @returns ExtrudeGeometry or null if params invalid. (ExtrudeGeometry 或参数无效时返回 null)
 */
export function createKeychainRingGeometry(
  width: number,
  length: number,
  hole: number,
): THREE.ExtrudeGeometry | null {
  // Hole diameter must be less than min(width, length) for valid geometry
  if (hole >= Math.min(width, length)) {
    return null;
  }
  if (width <= 0 || length <= 0 || hole <= 0) {
    return null;
  }

  const halfW = width / 2;
  const halfL = length / 2;
  const holeRadius = hole / 2;

  // Outer rectangle shape
  const shape = new THREE.Shape();
  shape.moveTo(-halfW, -halfL);
  shape.lineTo(halfW, -halfL);
  shape.lineTo(halfW, halfL);
  shape.lineTo(-halfW, halfL);
  shape.closePath();

  // Circular hole in the upper portion of the rectangle
  // Center the hole at (0, halfL - holeRadius - margin) so it sits in the upper area
  const holeCenterY = halfL - holeRadius - Math.max(0.5, (length - hole) * 0.15);
  const holePath = new THREE.Path();
  holePath.absarc(0, holeCenterY, holeRadius, 0, Math.PI * 2, false);
  shape.holes.push(holePath);

  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: EXTRUDE_DEPTH,
    bevelEnabled: false,
    curveSegments: HOLE_SEGMENTS,
  });

  return geometry;
}

function KeychainRing3D({
  enabled,
  width,
  length,
  hole,
  modelBounds,
}: KeychainRing3DProps) {
  // Memoize geometry — only regenerate when width/length/hole change (Req 7.2)
  const geometry = useMemo(
    () => createKeychainRingGeometry(width, length, hole),
    [width, length, hole],
  );

  if (!enabled || !geometry) {
    return null;
  }

  // Position at model top center:
  // X = centered horizontally, Y = top of model + offset, Z = centered in thickness
  const posX = (modelBounds.minX + modelBounds.maxX) / 2;
  const posY = modelBounds.maxY + TOP_OFFSET;
  const posZ = 0;

  return (
    <mesh geometry={geometry} position={[posX, posY, posZ]}>
      <meshStandardMaterial
        color="#888888"
        opacity={0.6}
        transparent={true}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

export default KeychainRing3D;

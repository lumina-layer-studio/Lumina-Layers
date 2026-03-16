import { useMemo, useEffect, useRef, useCallback } from "react";
import { useThree, useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { useConverterStore } from "../stores/converterStore";

// ========== Exported pure utility functions (testable without Three.js) ==========

/**
 * Extract hex color string from a mesh name with "color_" prefix.
 * 从带有 "color_" 前缀的网格名称中提取 hex 颜色字符串。
 *
 * @param meshName - The mesh name, e.g. "color_ff0000". (网格名称)
 * @returns The hex string without prefix, e.g. "ff0000". (不含前缀的 hex 字符串)
 */
export function extractHexFromMeshName(meshName: string): string {
  return meshName.slice(6);
}

/**
 * Compute the next selected color after a click toggle.
 * 计算点击切换后的下一个选中颜色。
 *
 * @param currentSelected - Currently selected hex or null. (当前选中的 hex 或 null)
 * @param clickedHex - The hex that was clicked. (被点击的 hex)
 * @returns null if toggling off (same color), otherwise the clicked hex. (取消选中返回 null，否则返回被点击的 hex)
 */
export function toggleColorSelection(
  currentSelected: string | null,
  clickedHex: string,
): string | null {
  return currentSelected === clickedHex ? null : clickedHex;
}

// ========== Component ==========

export interface InteractiveModelViewerProps {
  url: string;
  colorRemapMap: Record<string, string>;
  colorHeightMap: Record<string, number>;
  selectedColor: string | null;
  baseHeight: number;
  enableRelief: boolean;
  onColorClick: (hex: string | null) => void;
  scaleX?: number;  // X 方向缩放比例，默认 1.0
  scaleY?: number;  // Y 方向缩放比例，默认 1.0
  spacerThick?: number;    // 底板厚度 (mm)，默认 1.2
  structureMode?: string;  // "Double-sided" | "Single-sided"
}

/** Color layer thickness in mm (5 layers × 0.08mm). */
const COLOR_LAYER_HEIGHT = 0.4;

function InteractiveModelViewer({
  url,
  colorRemapMap,
  colorHeightMap,
  selectedColor,
  baseHeight,
  enableRelief,
  onColorClick,
  scaleX = 1,
  scaleY = 1,
  spacerThick = 1.2,
  structureMode = "Double-sided",
}: InteractiveModelViewerProps) {
  const { scene } = useGLTF(url);
  const groupRef = useRef<THREE.Group>(null);

  // Clone scene once per URL load, apply rotation/centering,
  // and clone each color mesh's material to avoid shared-material mutations.
  // Also separate color_ meshes from non-color children for individual JSX rendering.
  const { nonColorObject, colorMeshes, modelBounds, sceneCenter } = useMemo(() => {
    const clone = scene.clone(true);

    // Remove any baked-in bed mesh
    const toRemove: THREE.Object3D[] = [];
    clone.traverse((child) => {
      if (child.name.toLowerCase() === "bed") {
        toRemove.push(child);
      }
    });
    toRemove.forEach((obj) => obj.removeFromParent());

    // Convert all mesh materials to pure diffuse (no specular reflections).
    // Trimesh-exported GLB uses MeshStandardMaterial which reflects the HDR
    // environment map, causing unwanted glare on the color surfaces.
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        const mats = Array.isArray(child.material)
          ? child.material
          : [child.material];
        for (const mat of mats) {
          if (mat instanceof THREE.MeshStandardMaterial) {
            mat.roughness = 1.0;
            mat.metalness = 0.0;
          }
        }
      }
    });

    // Trimesh exports Z-up with image in XY plane.
    // We want the image to face the camera (stand upright in XY),
    // with thickness along +Z (toward camera).
    // No rotation needed — keep the Trimesh coordinate system as-is,
    // since Three.js XY plane is the screen plane.
    clone.updateMatrixWorld(true);

    // Compute bounding box
    const box = new THREE.Box3().setFromObject(clone);

    // Center on X and Y (model centered on bed), but place bottom at Z=0
    // so the model sits on top of the bed platform (Z = -0.1).
    const center = new THREE.Vector3();
    box.getCenter(center);
    clone.position.set(-center.x, -center.y, -box.min.z);
    clone.updateMatrixWorld(true);

    // Separate color_ meshes from the rest
    const colorMeshList: THREE.Mesh[] = [];
    const colorMeshParents: { mesh: THREE.Mesh; parent: THREE.Object3D }[] = [];

    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.name.startsWith("color_")) {
        // Clone material so mutations don't affect the GLTF cache
        if (child.material) {
          const cloned = (child.material as THREE.Material).clone();
          // Ensure pure diffuse (no specular reflections)
          if (cloned instanceof THREE.MeshStandardMaterial) {
            cloned.roughness = 1.0;
            cloned.metalness = 0.0;
          }
          child.material = cloned;
        }
        colorMeshList.push(child);
        if (child.parent) {
          colorMeshParents.push({ mesh: child, parent: child.parent });
        }
      }
    });

    // Bake the parent's centering offset into each color mesh's geometry
    // so they remain centered after detachment from the clone tree.
    for (const mesh of colorMeshList) {
      mesh.geometry.applyMatrix4(mesh.matrixWorld);
      mesh.position.set(0, 0, 0);
      mesh.rotation.set(0, 0, 0);
      mesh.scale.set(1, 1, 1);
      mesh.updateMatrixWorld(true);
    }

    // Detach color meshes from the clone tree so they can be rendered as individual JSX
    for (const { mesh, parent } of colorMeshParents) {
      parent.remove(mesh);
    }

    // Compute model bounding box from all meshes after centering
    const boundsBox = new THREE.Box3();
    // Add bounds from the remaining non-color scene
    boundsBox.expandByObject(clone);
    // Add bounds from each color mesh (geometry already in centered world space)
    for (const mesh of colorMeshList) {
      mesh.geometry.computeBoundingBox();
      if (mesh.geometry.boundingBox) {
        boundsBox.union(mesh.geometry.boundingBox);
      }
    }

    const bounds = boundsBox.isEmpty()
      ? null
      : {
          minX: boundsBox.min.x,
          maxX: boundsBox.max.x,
          minY: boundsBox.min.y,
          maxY: boundsBox.max.y,
          maxZ: boundsBox.max.z, // thickness direction (toward camera)
        };

    return { nonColorObject: clone, colorMeshes: colorMeshList, modelBounds: bounds, sceneCenter: center };
  }, [scene]);

  // Expose model bounds to store for KeychainRing3D positioning
  useEffect(() => {
    useConverterStore.getState().setModelBounds(modelBounds);
  }, [modelBounds]);

  // ---- White backing plate mesh ----
  const isDoubleSided = structureMode === "Double-sided";
  const backingMesh = useMemo(() => {
    if (!modelBounds) return null;
    const w = modelBounds.maxX - modelBounds.minX;
    const h = modelBounds.maxY - modelBounds.minY;
    if (w <= 0 || h <= 0) return null;

    const geo = new THREE.BoxGeometry(w, h, spacerThick);
    const mat = new THREE.MeshStandardMaterial({
      color: 0xf5f5f5,
      roughness: 0.85,
      metalness: 0.0,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = "__backing_plate";

    const cx = (modelBounds.minX + modelBounds.maxX) / 2;
    const cy = (modelBounds.minY + modelBounds.maxY) / 2;

    if (isDoubleSided) {
      // Double-sided: backing plate sits with its top face at the color layer base
      // Color layers go upward from spacerThick, backing occupies [0, spacerThick]
      mesh.position.set(cx, cy, spacerThick / 2);
    } else {
      // Single-sided: backing at bottom, colors on top
      mesh.position.set(cx, cy, spacerThick / 2);
    }
    return mesh;
  }, [modelBounds, spacerThick, isDoubleSided]);

  // Camera is managed by BedPlatform's default view — skip auto-fit here
  // so the viewport stays stable when a preview model loads.

  // Double-sided mirror meshes: pre-create clones that share the same material
  // so color remap mutations apply to both sides automatically.
  const mirrorMeshes = useMemo(() => {
    if (!isDoubleSided) return [];
    return colorMeshes.map((mesh) => {
      const mirror = mesh.clone(true);
      // Share the same material instance so color remap applies to both
      mirror.material = mesh.material;
      mirror.name = `mirror_${mesh.name}`;
      return mirror;
    });
  }, [colorMeshes, isDoubleSided]);

  // Raycaster for manual hit-testing on click (avoids per-mesh R3F pointer events).
  const raycasterRef = useRef(new THREE.Raycaster());
  const pointerRef = useRef(new THREE.Vector2());

  // Store Three.js context for manual raycasting
  const threeCtx = useThree();

  // Flag to suppress onPointerMissed when a color mesh was clicked via native event.
  // We store this on the converterStore so Scene3D can read it.
  const colorHitRef = useRef(false);

  const handlePointerDown = useCallback(
    (event: PointerEvent) => {
      if (event.button !== 0) return; // Only left click
      colorHitRef.current = false;

      const canvas = threeCtx.gl.domElement;
      const rect = canvas.getBoundingClientRect();
      pointerRef.current.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointerRef.current.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycasterRef.current.setFromCamera(pointerRef.current, threeCtx.camera);
      const intersects = raycasterRef.current.intersectObjects(colorMeshes, false);

      if (intersects.length > 0) {
        const hitMesh = intersects[0].object as THREE.Mesh;
        if (hitMesh.name.startsWith("color_")) {
          colorHitRef.current = true;
          const hex = extractHexFromMeshName(hitMesh.name);
          const result = toggleColorSelection(selectedColor, hex);
          onColorClick(result);
        }
      }
    },
    [threeCtx.gl, threeCtx.camera, colorMeshes, selectedColor, onColorClick],
  );

  // Expose colorHitRef check so Scene3D's onPointerMissed can query it
  useEffect(() => {
    (window as unknown as Record<string, unknown>).__luminaColorHitRef = colorHitRef;
    return () => {
      delete (window as unknown as Record<string, unknown>).__luminaColorHitRef;
    };
  }, []);

  // Attach/detach native pointer event for color mesh click detection
  useEffect(() => {
    const canvas = threeCtx.gl.domElement;
    canvas.addEventListener("pointerdown", handlePointerDown);
    return () => canvas.removeEventListener("pointerdown", handlePointerDown);
  }, [threeCtx.gl, handlePointerDown]);

  // Edge outline LineSegments for selected color regions.
  const outlineObjsRef = useRef<THREE.LineSegments[]>([]);
  // Normalized arc-length ratios per outline, for flowing RGB animation.
  // Each entry is an array of [h0, h1] pairs (one per line segment).
  const outlineArcRef = useRef<Array<Array<[number, number]>>>([]);
  const outlineGroupRef = useRef<THREE.Group>(new THREE.Group());
  outlineGroupRef.current.name = "__outlineGroup";

  // Imperative Three.js mutations: color remap, contour-based outline, relief scaling.
  // Colors stay fully visible — contour lines from backend OpenCV mark the selected region.
  const colorContours = useConverterStore((s) => s.colorContours);

  useEffect(() => {
    // Clear previous outlines
    const outlineGroup = outlineGroupRef.current;
    for (const obj of outlineObjsRef.current) {
      outlineGroup.remove(obj);
      obj.geometry.dispose();
      (obj.material as THREE.Material).dispose();
    }
    outlineObjsRef.current = [];
    outlineArcRef.current = [];

    if (groupRef.current && !groupRef.current.children.includes(outlineGroup)) {
      groupRef.current.add(outlineGroup);
    }

    for (const mesh of colorMeshes) {
      const origHex = extractHexFromMeshName(mesh.name);
      const mat = mesh.material as THREE.MeshStandardMaterial;

      // Color replacement — always apply
      const remappedHex = colorRemapMap[origHex] || origHex;
      mat.color.set(`#${remappedHex}`);

      // Keep all meshes fully opaque and unchanged
      mat.emissive.set(0x000000);
      mat.opacity = 1.0;
      mat.transparent = false;

      // Compute Z scale: map the GLB's native color height to the target height
      // GLB color meshes span [0, nativeH] where nativeH ≈ 2.0mm (25 layers × 0.08)
      mesh.geometry.computeBoundingBox();
      const nativeH = mesh.geometry.boundingBox
        ? mesh.geometry.boundingBox.max.z - mesh.geometry.boundingBox.min.z
        : 1;

      if (enableRelief && baseHeight > 0) {
        // Relief mode: each color gets its own height from colorHeightMap
        const heightMm = colorHeightMap[origHex] ?? COLOR_LAYER_HEIGHT;
        mesh.scale.z = nativeH > 0 ? heightMm / nativeH : 1;
      } else {
        // Normal mode: scale to COLOR_LAYER_HEIGHT (0.4mm)
        mesh.scale.z = nativeH > 0 ? COLOR_LAYER_HEIGHT / nativeH : 1;
      }

      // Position color layer on top of the backing plate
      mesh.position.z = spacerThick;
    }

    // Update mirror meshes for double-sided mode
    for (const mirror of mirrorMeshes) {
      const origName = mirror.name.replace("mirror_", "");
      const origMesh = colorMeshes.find((m) => m.name === origName);
      if (origMesh) {
        mirror.scale.z = -origMesh.scale.z; // flip Z direction
        mirror.position.z = 0; // grow downward from bottom of backing plate
      }
    }

    // Draw contour outline for selected color using backend-computed contours.
    // Contours are in raw world coords (mm, origin at bottom-left of image).
    // The GLB model is centered by subtracting sceneCenter, so apply same offset.
    if (selectedColor && colorContours[selectedColor] && modelBounds) {
      const polygons = colorContours[selectedColor];
      // Outline sits on top of the color layer (which is on top of the backing plate)
      const colorTopZ = spacerThick + COLOR_LAYER_HEIGHT + 0.1;
      const topZ = enableRelief
        ? spacerThick + (colorHeightMap[selectedColor] ?? COLOR_LAYER_HEIGHT) + 0.1
        : colorTopZ;
      const offsetX = -sceneCenter.x;
      const offsetY = -sceneCenter.y;

      for (const polygon of polygons) {
        if (polygon.length < 3) continue;
        const verts: number[] = [];
        // Compute cumulative arc length for rainbow hue mapping
        const cumLen: number[] = [0];
        for (let i = 0; i < polygon.length; i++) {
          const [x0, y0] = polygon[i];
          const [x1, y1] = polygon[(i + 1) % polygon.length];
          const dx = x1 - x0;
          const dy = y1 - y0;
          cumLen.push(cumLen[cumLen.length - 1] + Math.sqrt(dx * dx + dy * dy));
        }
        const totalLen = cumLen[cumLen.length - 1] || 1;

        // Store normalized arc-length ratios for animation
        const arcPairs: Array<[number, number]> = [];
        for (let i = 0; i < polygon.length; i++) {
          const [x0, y0] = polygon[i];
          const [x1, y1] = polygon[(i + 1) % polygon.length];
          verts.push(
            x0 + offsetX, y0 + offsetY, topZ,
            x1 + offsetX, y1 + offsetY, topZ,
          );
          arcPairs.push([cumLen[i] / totalLen, cumLen[i + 1] / totalLen]);
        }

        // Initialize color buffer (will be updated each frame by useFrame)
        const colorArr = new Float32Array(arcPairs.length * 6);
        const lineGeo = new THREE.BufferGeometry();
        lineGeo.setAttribute(
          "position",
          new THREE.Float32BufferAttribute(verts, 3),
        );
        lineGeo.setAttribute(
          "color",
          new THREE.BufferAttribute(colorArr, 3),
        );
        const lineMat = new THREE.LineBasicMaterial({
          vertexColors: true,
          linewidth: 2,
          depthTest: false,
        });
        const line = new THREE.LineSegments(lineGeo, lineMat);
        line.renderOrder = 999;
        outlineGroup.add(line);
        outlineObjsRef.current.push(line);
        outlineArcRef.current.push(arcPairs);
      }
    }
  }, [colorMeshes, mirrorMeshes, colorRemapMap, colorHeightMap, selectedColor, enableRelief, baseHeight, colorContours, modelBounds, sceneCenter, spacerThick, isDoubleSided]);

  // Flowing RGB animation: shift hue offset each frame for a "light strip" effect.
  const tmpColorAnim = useRef(new THREE.Color());
  useFrame(() => {
    const lines = outlineObjsRef.current;
    const arcs = outlineArcRef.current;
    if (lines.length === 0) return;

    // Advance hue offset over time (~0.3 full cycles per second)
    const time = performance.now() * 0.0003;

    const c = tmpColorAnim.current;
    for (let li = 0; li < lines.length; li++) {
      const colorAttr = lines[li].geometry.getAttribute("color") as THREE.BufferAttribute;
      const arr = colorAttr.array as Float32Array;
      const pairs = arcs[li];
      if (!pairs) continue;

      for (let si = 0; si < pairs.length; si++) {
        const [t0, t1] = pairs[si];
        const idx = si * 6;
        // Start vertex
        c.setHSL((t0 + time) % 1.0, 1.0, 0.55);
        arr[idx] = c.r; arr[idx + 1] = c.g; arr[idx + 2] = c.b;
        // End vertex
        c.setHSL((t1 + time) % 1.0, 1.0, 0.55);
        arr[idx + 3] = c.r; arr[idx + 4] = c.g; arr[idx + 5] = c.b;
      }
      colorAttr.needsUpdate = true;
    }
  });

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      for (const obj of outlineObjsRef.current) {
        obj.geometry.dispose();
        (obj.material as THREE.Material).dispose();
      }
      outlineObjsRef.current = [];
    };
  }, []);

  // Double-sided mirror meshes are defined above (before useEffect).

  return (
    <group ref={groupRef} scale={[scaleX, scaleY, 1]}>
      <primitive object={nonColorObject} />
      {/* White backing plate */}
      {backingMesh && <primitive object={backingMesh} />}
      {/* Color layers (positioned on top of backing plate via position.z in useEffect) */}
      {colorMeshes.map((mesh) => (
        <primitive key={mesh.uuid} object={mesh} />
      ))}
      {/* Double-sided: mirror color layers below the backing plate */}
      {mirrorMeshes.map((mesh) => (
        <primitive key={mesh.uuid} object={mesh} />
      ))}
    </group>
  );
}

export default InteractiveModelViewer;

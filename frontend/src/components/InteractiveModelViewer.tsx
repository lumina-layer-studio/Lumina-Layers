import { useMemo, useEffect, useRef, useCallback } from "react";
import { useThree } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { computeFitDistance } from "./ModelViewer";
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
}

function InteractiveModelViewer({
  url,
  colorRemapMap,
  colorHeightMap,
  selectedColor,
  baseHeight,
  enableRelief,
  onColorClick,
}: InteractiveModelViewerProps) {
  const { scene } = useGLTF(url);
  const { camera, controls } = useThree();
  const groupRef = useRef<THREE.Group>(null);

  // Clone scene once per URL load, apply rotation/centering,
  // and clone each color mesh's material to avoid shared-material mutations.
  // Also separate color_ meshes from non-color children for individual JSX rendering.
  const { nonColorObject, colorMeshes, modelBounds } = useMemo(() => {
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

    // Center on X and Y (model centered on bed), center Z (thickness)
    const center = new THREE.Vector3();
    box.getCenter(center);
    clone.position.set(-center.x, -center.y, -center.z);
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

    return { nonColorObject: clone, colorMeshes: colorMeshList, modelBounds: bounds };
  }, [scene]);

  // Expose model bounds to store for KeychainRing3D positioning
  useEffect(() => {
    useConverterStore.getState().setModelBounds(modelBounds);
  }, [modelBounds]);

  // Auto-fit camera to model after load
  useEffect(() => {
    const wrapper = new THREE.Group();
    // Add non-color scene
    const cloneForFit = nonColorObject.clone(true);
    wrapper.add(cloneForFit);
    // Add color meshes for bounding calculation
    for (const mesh of colorMeshes) {
      wrapper.add(mesh.clone());
    }
    wrapper.updateMatrixWorld(true);

    const box = new THREE.Box3().setFromObject(wrapper);
    const sphere = new THREE.Sphere();
    box.getBoundingSphere(sphere);

    const perspCam = camera as THREE.PerspectiveCamera;
    const dist = computeFitDistance(sphere.radius, perspCam.fov);

    // Model is already centered at origin — camera looks straight at (0,0,0) from +Z
    camera.position.set(0, 0, dist);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();

    if (controls) {
      const oc = controls as unknown as {
        target: THREE.Vector3;
        maxDistance: number;
        minDistance: number;
        update: () => void;
      };
      oc.target.set(0, 0, 0);
      oc.maxDistance = dist * 5;
      oc.minDistance = dist * 0.1;
      oc.update();
    }

    wrapper.clear();
  }, [nonColorObject, colorMeshes, camera, controls]);

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

  // Imperative Three.js mutations: color remap, highlight, and relief scaling.
  // Runs on every prop change without triggering React re-renders of the Canvas.
  useEffect(() => {
    for (const mesh of colorMeshes) {
      const origHex = extractHexFromMeshName(mesh.name);
      const mat = mesh.material as THREE.MeshStandardMaterial;

      // Color replacement
      const remappedHex = colorRemapMap[origHex] || origHex;
      mat.color.set(`#${remappedHex}`);

      // Highlight selected color mesh
      const isSelected = selectedColor === origHex;
      mat.emissive.set(isSelected ? 0x333333 : 0x000000);
      mat.opacity = selectedColor && !isSelected ? 0.4 : 1.0;
      mat.transparent = selectedColor !== null && !isSelected;

      // Height scaling (relief mode only)
      if (enableRelief && baseHeight > 0) {
        const heightMm = colorHeightMap[origHex] ?? baseHeight;
        mesh.scale.z = heightMm / baseHeight;
      } else {
        mesh.scale.z = 1.0;
      }
    }
  }, [colorMeshes, colorRemapMap, colorHeightMap, selectedColor, enableRelief, baseHeight]);

  return (
    <group ref={groupRef}>
      <primitive object={nonColorObject} />
      {colorMeshes.map((mesh) => (
        <primitive key={mesh.uuid} object={mesh} />
      ))}
    </group>
  );
}

export default InteractiveModelViewer;

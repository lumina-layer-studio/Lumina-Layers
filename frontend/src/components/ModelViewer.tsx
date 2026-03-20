import { useMemo, useEffect } from "react";
import { useThree } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";

/**
 * Compute the offset needed to center a bounding box at the origin.
 * Pure function, independently testable.
 */
export function computeCenterOffset(
  min: [number, number, number],
  max: [number, number, number],
): [number, number, number] {
  return [
    -(min[0] + max[0]) / 2,
    -(min[1] + max[1]) / 2,
    -(min[2] + max[2]) / 2,
  ];
}

/**
 * Compute camera distance so the model fits in view.
 * Returns the distance from the origin along the camera's forward axis.
 */
export function computeFitDistance(
  boundingSphereRadius: number,
  fovDeg: number,
): number {
  const halfFovRad = (fovDeg * Math.PI) / 360;
  return (boundingSphereRadius / Math.sin(halfFovRad)) * 1.2;
}

interface ModelViewerProps {
  url: string;
}

function ModelViewer({ url }: ModelViewerProps) {
  const { scene } = useGLTF(url);
  const { camera, controls } = useThree();

  const preparedScene = useMemo(() => {
    const clone = scene.clone(true);

    // Remove any baked-in bed mesh from old GLB files
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
    // We replace them with MeshLambertMaterial for a completely matte finish.
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        const mats = Array.isArray(child.material)
          ? child.material
          : [child.material];
        const newMats = mats.map((mat) => {
          if (mat instanceof THREE.MeshStandardMaterial) {
            return new THREE.MeshLambertMaterial({ color: mat.color });
          }
          return mat;
        });
        child.material = Array.isArray(child.material) ? newMats : newMats[0];
      }
    });

    // Trimesh exports Z-up with image in XY plane.
    // Keep as-is: image faces camera in XY, thickness along +Z.
    clone.updateMatrixWorld(true);

    // Compute bounding box
    const box = new THREE.Box3().setFromObject(clone);

    // Center on X and Y (model centered on bed), place bottom at Z=0
    // so the model sits on top of the bed platform.
    const center = new THREE.Vector3();
    box.getCenter(center);
    clone.position.set(-center.x, -center.y, -box.min.z);

    return clone;
  }, [scene]);

  // Auto-fit camera to model after load
  useEffect(() => {
    // Need a wrapper to get correct world bounds after position offset
    const wrapper = new THREE.Group();
    wrapper.add(preparedScene.clone(true));
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
  }, [preparedScene, camera, controls]);

  return <primitive object={preparedScene} />;
}

export default ModelViewer;

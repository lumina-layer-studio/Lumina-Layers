import { useMemo, useEffect } from "react";
import { useThree } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";
import {
  cloneObjectTreeWithOwnedResources,
  disposeMaterial,
  disposeObjectTree,
} from "../utils/threeDisposal";
import {
  debugThreeLog,
  getLatestResourceTiming,
  summarizeObjectTree,
} from "../utils/threeDebug";
import { postClientLog } from "../utils/clientLog";
import { createMatteMaterialFromStandard } from "../utils/threeMatteMaterial";
import { useGltfCacheLifecycle } from "./useGltfCacheLifecycle";
import { configureGltfTransport } from "../utils/gltfTransport";

type LuminaWindow = Window & { __luminaGenerateStart?: number };

function _getGenerateStartTime(): number | null {
  return (window as LuminaWindow).__luminaGenerateStart ?? null;
}

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
  position?: [number, number, number];
  autoFitCamera?: boolean;
}

const DEFAULT_MODEL_POSITION: [number, number, number] = [0, 0, 0];

function ModelViewer({
  url,
  position = DEFAULT_MODEL_POSITION,
  autoFitCamera = true,
}: ModelViewerProps) {
  const { scene } = useGLTF(url, true, true, configureGltfTransport);
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls);
  useGltfCacheLifecycle(url, useGLTF.clear);

  useEffect(() => {
    debugThreeLog("ModelViewer.lifecycle", {
      event: "mount",
      url,
    });
    return () => {
      debugThreeLog("ModelViewer.lifecycle", {
        event: "unmount",
        url,
      });
    };
  }, [url]);

  useEffect(() => {
    console.timeLog('[LUMINA] generate', 'GLB loaded (useGLTF resolved)');
    const resourceTiming = getLatestResourceTiming(url);
    const sourceScene = summarizeObjectTree(scene);
    postClientLog('generate: GLB loaded (useGLTF resolved)', {
      startTime: _getGenerateStartTime(),
      scope: 'generate-viewer',
      phase: 'gltf-loaded',
      dedupeMs: 250,
      details: {
        url,
        resource_timing: resourceTiming,
        source_scene: sourceScene,
      },
    });
    debugThreeLog("ModelViewer.gltf", {
      url,
      resource_timing: resourceTiming,
      source_scene: sourceScene,
    });
  }, [scene, url]);

  const { preparedScene, buildSummary } = useMemo(() => {
    const buildStart = performance.now();
    const clone = cloneObjectTreeWithOwnedResources(scene);

    // Remove any baked-in bed mesh from old GLB files
    const toRemove: THREE.Object3D[] = [];
    clone.traverse((child) => {
      if (child.name.toLowerCase() === "bed") {
        toRemove.push(child);
      }
    });
    toRemove.forEach((obj) => obj.removeFromParent());

    // Convert all mesh materials to unlit (no lighting, no specular).
    // Trimesh-exported GLB uses MeshStandardMaterial which reflects the HDR
    // environment map, causing unwanted glare on the color surfaces.
    // We replace them with MeshBasicMaterial so chip colours equal the source
    // hex exactly and stay decoupled from scene lighting.
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        const previousMaterial = child.material;
        const mats = Array.isArray(previousMaterial)
          ? previousMaterial
          : [previousMaterial];
        const replacedMaterials: THREE.Material[] = [];
        const newMats = mats.map((mat: THREE.Material) => {
          if (mat instanceof THREE.MeshStandardMaterial) {
            replacedMaterials.push(mat);
            return createMatteMaterialFromStandard(mat);
          }
          return mat;
        });
        if (replacedMaterials.length > 0) {
          for (const material of replacedMaterials) {
            disposeMaterial(material);
          }
          child.material = Array.isArray(previousMaterial) ? newMats : newMats[0];
        }
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
    clone.position.set(
      position[0] - center.x,
      position[1] - center.y,
      position[2] - box.min.z,
    );

    const summary = {
      url,
      build_ms: +(performance.now() - buildStart).toFixed(2),
      source_scene: summarizeObjectTree(scene),
      prepared_scene: summarizeObjectTree(clone),
      center: {
        x: +center.x.toFixed(3),
        y: +center.y.toFixed(3),
        z: +center.z.toFixed(3),
      },
      min_z: +box.min.z.toFixed(3),
    };

    debugThreeLog("ModelViewer.build", summary);

    return {
      preparedScene: clone,
      buildSummary: summary,
    };
  }, [position, scene, url]);

  useEffect(() => {
    console.timeLog('[LUMINA] generate', 'GLB scene processed (useMemo done)');
    postClientLog('generate: GLB scene processed (useMemo done)', {
      startTime: _getGenerateStartTime(),
      scope: 'generate-viewer',
      phase: 'scene-processed',
      dedupeMs: 250,
      details: buildSummary,
    });
  }, [buildSummary]);

  useEffect(() => {
    return () => {
      debugThreeLog("ModelViewer.dispose", {
        url,
        prepared_scene: summarizeObjectTree(preparedScene),
      });
      disposeObjectTree(preparedScene);
    };
  }, [preparedScene, url]);

  // Auto-fit camera to model after load
  useEffect(() => {
    if (!autoFitCamera) {
      return;
    }
    preparedScene.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(preparedScene);
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

    console.timeLog('[LUMINA] generate', 'camera fitted (model fully visible)');
    console.timeEnd('[LUMINA] generate');
    postClientLog('generate: camera fitted (model fully visible)', {
      startTime: _getGenerateStartTime(),
      scope: 'generate-viewer',
      phase: 'camera-fitted',
      dedupeMs: 250,
      details: {
        url,
        camera_distance: +dist.toFixed(3),
        bounding_sphere_radius: +sphere.radius.toFixed(3),
      },
    });
  }, [autoFitCamera, preparedScene, camera, controls, url]);

  return <primitive object={preparedScene} />;
}

export default ModelViewer;

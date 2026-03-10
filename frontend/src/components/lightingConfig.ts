/** Lighting configuration for the 3D preview scene.
 *  3D 预览场景的光照配置。
 */
export const LIGHTING_CONFIG = {
  /** Environment map settings (环境贴图设置) */
  environment: {
    /** Path to self-hosted HDR file (自托管 HDR 文件路径) */
    hdrFile: "/hdr/studio_small_09_1k.hdr",
    /** Environment map intensity for PBR materials (环境光强度) */
    intensity: 0.8,
  },
  /** Key directional light for directional shading (主方向光源) */
  keyLight: {
    /** Position [x, y, z] in scene units — front-right-top for vertical XY-plane model (位置：竖直 XY 平面模型的右上前方) */
    position: [150, 200, 500] as [number, number, number],
    /** Light intensity (光照强度) */
    intensity: 0.5,
    /** Light color hex (光照颜色) */
    color: "#ffffff",
  },
} as const;

/** Type for the lighting configuration object.
 *  光照配置对象的类型。
 */
export type LightingConfig = typeof LIGHTING_CONFIG;

/**
 * Scale factor utilities for real-time 3D model resizing.
 * 实时 3D 模型缩放比例计算工具。
 */

export interface ScaleFactor {
  scaleX: number;
  scaleY: number;
}

/**
 * Compute scale factors based on current dimensions vs preview dimensions.
 * 根据当前尺寸与预览时原始尺寸计算缩放比例。
 *
 * Args:
 *   currentWidth (number): Current target width in mm. (当前目标宽度，单位 mm)
 *   currentHeight (number): Current target height in mm. (当前目标高度，单位 mm)
 *   previewWidth (number | null): Width used when preview was generated. (生成预览时的宽度)
 *   previewHeight (number | null): Height used when preview was generated. (生成预览时的高度)
 *
 * Returns:
 *   ScaleFactor: X and Y scale ratios. (X 和 Y 方向的缩放比例)
 */
export function computeScaleFactor(
  currentWidth: number,
  currentHeight: number,
  previewWidth: number | null,
  previewHeight: number | null,
): ScaleFactor {
  if (!previewWidth || !previewHeight || previewWidth <= 0 || previewHeight <= 0) {
    return { scaleX: 1, scaleY: 1 };
  }
  const rawScaleX = currentWidth / previewWidth;
  const rawScaleY = currentHeight / previewHeight;
  // Use uniform scale (min of both axes) to preserve aspect ratio
  const uniform = Math.min(rawScaleX, rawScaleY);
  return {
    scaleX: uniform,
    scaleY: uniform,
  };
}

/**
 * Compute Z-axis scale factor for thickness preview.
 * 计算厚度预览的 Z 轴缩放比例。
 *
 * A pure function that returns the ratio of current thickness to the
 * thickness used when the preview was generated. Returns 1.0 as a safe
 * default when the preview thickness is missing or invalid.
 * 纯函数，返回当前厚度与生成预览时厚度的比值。当预览厚度缺失或无效时返回 1.0。
 *
 * @param currentThickness - Current spacer_thick value in mm. (当前 spacer_thick 值，单位 mm)
 * @param previewThickness - Thickness used when preview was generated, may be null. (生成预览时的厚度，可能为 null)
 * @returns Z-axis scale ratio. (Z 轴缩放比例)
 */
export function computeThicknessScale(
  currentThickness: number,
  previewThickness: number | null,
): number {
  if (!previewThickness || previewThickness <= 0) {
    return 1.0;
  }
  return currentThickness / previewThickness;
}

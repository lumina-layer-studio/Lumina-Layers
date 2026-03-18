/**
 * Card-mode layout utilities for LUT color grid.
 * LUT 颜色网格色卡模式布局工具函数。
 */

// (Removed unused STANDARD_TOTALS)

/** 8-color LUT total requiring split display. */
const EIGHT_COLOR_TOTAL = 2738;

/**
 * Compute grid column counts for card-mode layout.
 * 计算色卡模式方阵的列数。
 *
 * For the 8-color LUT (2738 colors), splits into two halves with
 * independent column counts. For all others, returns a single column count.
 * 8 色 LUT（2738 色）分两半各自计算列数，其余返回单一列数。
 *
 * @param total - Total number of LUT colors. (LUT 颜色总数)
 * @returns Column config: single `cols` or split `colsA`/`colsB`. (列数配置)
 */
export function computeCardDimensions(
  total: number,
): { cols: number } | { colsA: number; colsB: number } {
  if (total === EIGHT_COLOR_TOTAL) {
    const half = Math.floor(total / 2);
    return {
      colsA: Math.ceil(Math.sqrt(half)),
      colsB: Math.ceil(Math.sqrt(total - half)),
    };
  }
  return { cols: Math.ceil(Math.sqrt(total)) };
}

/**
 * Check whether card mode is available for a given LUT.
 * 判断指定 LUT 是否支持色卡模式。
 *
 * Card mode is available for standard (non-merged) LUTs.
 * 标准（非合并）LUT 支持色卡模式，合并 LUT 禁用。
 *
 * @param colorMode - The LUT's color mode string. (LUT 颜色模式)
 * @returns Whether card mode can be used. (是否可使用色卡模式)
 */
export function isCardModeAvailable(colorMode: string): boolean {
  return colorMode !== "" && colorMode.toLowerCase() !== "merged";
}

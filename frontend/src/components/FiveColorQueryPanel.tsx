import { useEffect, useMemo } from "react";
import { useFiveColorStore } from "../stores/fiveColorStore";
import { useConverterStore } from "../stores/converterStore";
import Dropdown from "./ui/Dropdown";
import { useI18n } from "../i18n/context";
import FiveColorCanvas from "./FiveColorCanvas";

export default function FiveColorQueryPanel() {
  const { t } = useI18n();
  const {
    lutName, baseColors, selectedIndices, queryResult,
    isLoading, error,
    loadBaseColors, addSelection, removeLastSelection,
    clearSelection, reverseSelection, submitQuery, clearError,
  } = useFiveColorStore();

  const lutList = useConverterStore((s) => s.lutList);
  const fetchLutList = useConverterStore((s) => s.fetchLutList);

  useEffect(() => {
    if (lutList.length === 0) void fetchLutList();
  }, []);

  const handleLutChange = (name: string) => {
    if (name) { clearError(); void loadBaseColors(name); }
  };

  const hasSelection = selectedIndices.length > 0;
  const isFull = selectedIndices.length === 5;

  // 为 Canvas 组件准备 slices 数据
  const canvasSlices = useMemo(
    () => selectedIndices.map((idx) => {
      const c = baseColors.find((b) => b.index === idx);
      return c ? { hex: c.hex, name: c.name } : { hex: "#666", name: "?" };
    }),
    [selectedIndices, baseColors],
  );

  return (
    <div className="flex h-full bg-gray-950 text-white">
      {/* ===== 左侧：颜色选择网格 ===== */}
      <div className="w-72 shrink-0 border-r border-gray-800 flex flex-col">
        <div className="p-4 border-b border-gray-800">
          <Dropdown
            label={t("five_color_lut_label")}
            value={lutName}
            options={lutList.map((n) => ({ label: n, value: n }))}
            onChange={handleLutChange}
            placeholder={t("five_color_lut_placeholder")}
          />
        </div>

        <div className="flex-1 overflow-y-auto p-3">
          {baseColors.length > 0 ? (
            <div className="grid grid-cols-3 gap-1.5">
              {baseColors.map((color) => {
                const isSelected = selectedIndices.includes(color.index);
                const selOrder = selectedIndices.indexOf(color.index);
                return (
                  <button
                    key={color.index}
                    onClick={() => addSelection(color.index)}
                    disabled={isFull && !isSelected}
                    className={`relative group flex flex-col items-center gap-0.5 rounded-lg p-1.5 transition-all
                      ${isSelected
                        ? "ring-2 ring-blue-500 bg-blue-500/10"
                        : "hover:bg-gray-800 border border-transparent hover:border-gray-600"}
                      ${isFull && !isSelected ? "opacity-30 cursor-not-allowed" : "cursor-pointer"}`}
                    aria-label={t("five_color_select_color").replace("{name}", color.name).replace("{hex}", color.hex)}
                  >
                    <div
                      className="w-10 h-10 rounded-md shadow-md transition-transform group-hover:scale-110"
                      style={{ backgroundColor: color.hex }}
                    />
                    {isSelected && (
                      <span className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-blue-500 text-white text-xs flex items-center justify-center font-bold">
                        {selOrder + 1}
                      </span>
                    )}
                    <span className="text-[10px] text-gray-400 truncate w-full text-center leading-tight">
                      {color.name}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : lutName ? (
            <p className="text-sm text-gray-500 text-center py-8">{t("five_color_no_base_colors")}</p>
          ) : (
            <p className="text-sm text-gray-500 text-center py-8">{t("five_color_select_lut_first")}</p>
          )}
        </div>
      </div>

      {/* ===== 中间：Canvas 3D 薄片动画 ===== */}
      <div className="flex-1 flex flex-col items-center justify-center relative bg-gradient-to-b from-gray-900 to-gray-950">
        <div className="w-full h-full max-w-lg max-h-96">
          <FiveColorCanvas
            slices={canvasSlices}
            resultHex={queryResult?.found ? queryResult.result_hex : null}
            isLoading={isLoading}
          />
        </div>

        {/* 底部提示 */}
        {!isFull && baseColors.length > 0 && (
          <p className="absolute bottom-6 text-sm text-gray-500">
            {t("five_color_select_lut_first").includes("LUT")
              ? `已选 ${selectedIndices.length}/5 种颜色，请继续选择`
              : `${selectedIndices.length}/5 selected`}
          </p>
        )}
      </div>

      {/* ===== 右侧：操作按钮 + 结果 ===== */}
      <div className="w-56 shrink-0 border-l border-gray-800 flex flex-col p-4 gap-3">
        <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">操作</h3>

        <button
          onClick={() => void submitQuery()}
          disabled={!isFull || isLoading}
          className="w-full py-2.5 rounded-lg text-sm font-medium transition-all
            bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isLoading ? "查询中..." : t("five_color_query")}
        </button>

        <button
          onClick={removeLastSelection}
          disabled={!hasSelection}
          className="w-full py-2 rounded-lg text-sm font-medium transition-all
            bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {t("five_color_undo")}
        </button>

        <button
          onClick={reverseSelection}
          disabled={!isFull}
          className="w-full py-2 rounded-lg text-sm font-medium transition-all
            bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {t("five_color_reverse")}
        </button>

        <button
          onClick={clearSelection}
          disabled={!hasSelection}
          className="w-full py-2 rounded-lg text-sm font-medium transition-all
            bg-gray-800 hover:bg-gray-700 text-red-400 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {t("five_color_clear")}
        </button>

        {/* 错误 */}
        {error && (
          <div className="rounded-lg bg-red-900/30 border border-red-800 p-2.5 text-xs text-red-300 flex items-start gap-2">
            <span className="flex-1">{error}</span>
            <button onClick={clearError} className="text-red-400 hover:text-red-200 shrink-0">✕</button>
          </div>
        )}

        {/* 结果 */}
        {queryResult && queryResult.found && (
          <div className="mt-auto flex flex-col gap-2 rounded-lg border border-gray-700 bg-gray-800/50 p-3">
            <div
              className="w-full h-16 rounded-lg shadow-lg"
              style={{ backgroundColor: queryResult.result_hex ?? undefined }}
            />
            <p className="text-sm text-gray-200 font-mono">{queryResult.result_hex}</p>
            <p className="text-xs text-gray-400">
              RGB: {queryResult.result_rgb?.join(", ")}
            </p>
            <p className="text-xs text-gray-500">
              {t("five_color_result_row")}: {queryResult.row_index}
            </p>
          </div>
        )}

        {queryResult && !queryResult.found && (
          <div className="mt-auto rounded-lg border border-yellow-800 bg-yellow-900/20 p-3">
            <p className="text-sm text-yellow-400">{t("five_color_not_found")}</p>
          </div>
        )}
      </div>
    </div>
  );
}

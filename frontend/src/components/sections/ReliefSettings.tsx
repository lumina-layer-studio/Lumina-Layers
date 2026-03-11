import { useCallback } from "react";
import { useShallow } from "zustand/react/shallow";
import { useConverterStore } from "../../stores/converterStore";
import type { AutoHeightMode } from "../../api/types";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";
import Dropdown from "../ui/Dropdown";
import ImageUpload from "../ui/ImageUpload";

const AUTO_HEIGHT_OPTIONS: { label: string; value: AutoHeightMode }[] = [
  { label: "深色凸起", value: "darker-higher" },
  { label: "浅色凸起", value: "lighter-higher" },
  { label: "根据高度图", value: "use-heightmap" },
];

export default function ReliefSettings() {
  // State fields grouped with useShallow
  const {
    enable_relief,
    heightmap_max_height,
    autoHeightMode,
    heightmapFile,
    heightmapThumbnailUrl,
  } = useConverterStore(useShallow((s) => ({
    enable_relief: s.enable_relief,
    heightmap_max_height: s.heightmap_max_height,
    autoHeightMode: s.autoHeightMode,
    heightmapFile: s.heightmapFile,
    heightmapThumbnailUrl: s.heightmapThumbnailUrl,
  })));

  // Actions extracted individually (stable references)
  const setEnableRelief = useConverterStore((s) => s.setEnableRelief);
  const setHeightmapMaxHeight = useConverterStore((s) => s.setHeightmapMaxHeight);
  const setAutoHeightMode = useConverterStore((s) => s.setAutoHeightMode);
  const applyAutoHeight = useConverterStore((s) => s.applyAutoHeight);
  const setHeightmapFile = useConverterStore((s) => s.setHeightmapFile);
  const uploadHeightmap = useConverterStore((s) => s.uploadHeightmap);

  const handleModeChange = useCallback(
    (value: string) => {
      const mode = value as AutoHeightMode;
      setAutoHeightMode(mode);
      if (mode !== "use-heightmap") {
        applyAutoHeight(mode);
      }
    },
    [setAutoHeightMode, applyAutoHeight],
  );

  const handleHeightmapSelect = useCallback(
    (file: File) => {
      setHeightmapFile(file);
      // 设置文件后自动触发上传
      // 需要在下一个 tick 执行，因为 setHeightmapFile 是异步更新 state
      setTimeout(() => {
        uploadHeightmap();
      }, 0);
    },
    [setHeightmapFile, uploadHeightmap],
  );

  return (
    <div className="flex flex-col gap-4">
        <Checkbox
          label="启用浮雕"
          checked={enable_relief}
          onChange={setEnableRelief}
        />

        {enable_relief && (
          <>
            <Slider
              label="最大高度"
              value={heightmap_max_height}
              min={0.08}
              max={15.0}
              step={0.1}
              unit="mm"
              onChange={setHeightmapMaxHeight}
            />

            <Dropdown
              label="自动高度模式"
              value={autoHeightMode}
              options={AUTO_HEIGHT_OPTIONS}
              onChange={handleModeChange}
            />

            {autoHeightMode === "use-heightmap" && (
              <div className="flex flex-col gap-2">
                <label className="text-sm text-gray-300">高度图</label>
                <ImageUpload
                  onFileSelect={handleHeightmapSelect}
                  accept="image/png,image/jpeg,image/bmp,image/tiff"
                  preview={heightmapThumbnailUrl ?? undefined}
                />
                {heightmapFile && !heightmapThumbnailUrl && (
                  <span className="text-xs text-gray-400">
                    已选择: {heightmapFile.name}
                  </span>
                )}
              </div>
            )}
          </>
        )}
    </div>
  );
}

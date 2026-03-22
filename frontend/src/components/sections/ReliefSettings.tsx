import { useCallback } from "react";
import { useShallow } from "zustand/react/shallow";
import { useConverterStore } from "../../stores/converterStore";
import type { AutoHeightMode } from "../../api/types";
import { ModelingMode } from "../../api/types";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";
import Dropdown from "../ui/Dropdown";
import ImageUpload from "../ui/ImageUpload";
import { useI18n } from "../../i18n/context";
import { workstationFieldLabelClass } from "../ui/panelPrimitives";

export default function ReliefSettings() {
  const { t } = useI18n();

  const AUTO_HEIGHT_OPTIONS: { label: string; value: AutoHeightMode }[] = [
    { label: t("relief_darker_higher"), value: "darker-higher" },
    { label: t("relief_lighter_higher"), value: "lighter-higher" },
    { label: t("relief_use_heightmap"), value: "use-heightmap" },
  ];

  const {
    enable_relief,
    heightmap_max_height,
    autoHeightMode,
    heightmapFile,
    heightmapThumbnailUrl,
    modeling_mode,
  } = useConverterStore(useShallow((s) => ({
    enable_relief: s.enable_relief,
    heightmap_max_height: s.heightmap_max_height,
    autoHeightMode: s.autoHeightMode,
    heightmapFile: s.heightmapFile,
    heightmapThumbnailUrl: s.heightmapThumbnailUrl,
    modeling_mode: s.modeling_mode,
  })));

  const isVector = modeling_mode === ModelingMode.VECTOR;

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
          label={t("relief_enable")}
          checked={isVector ? false : enable_relief}
          onChange={setEnableRelief}
          disabled={isVector}
        />
        {isVector && (
          <p className="text-[clamp(0.6rem,0.8vw,0.7rem)] text-slate-400 dark:text-slate-500">
            {t("relief_vector_unsupported")}
          </p>
        )}

        {enable_relief && !isVector && (
          <>
            <Slider
              label={t("relief_max_height")}
              value={heightmap_max_height}
              min={0.08}
              max={15.0}
              step={0.04}
              unit="mm"
              onChange={setHeightmapMaxHeight}
            />

            <Dropdown
              label={t("relief_auto_height_mode")}
              value={autoHeightMode}
              options={AUTO_HEIGHT_OPTIONS}
              onChange={handleModeChange}
            />

            {autoHeightMode === "use-heightmap" && (
              <div className="flex flex-col gap-2">
                <label className={workstationFieldLabelClass}>{t("relief_heightmap_label")}</label>
                <ImageUpload
                  onFileSelect={handleHeightmapSelect}
                  accept="image/png,image/jpeg,image/bmp,image/tiff"
                  preview={heightmapThumbnailUrl ?? undefined}
                />
                {heightmapFile && !heightmapThumbnailUrl && (
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {t("relief_file_selected")}: {heightmapFile.name}
                  </span>
                )}
              </div>
            )}
          </>
        )}
    </div>
  );
}

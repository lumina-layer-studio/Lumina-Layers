import {
  isDynamicMaterialActive,
  useConverterStore,
} from "../../stores/converter";
import { useI18n } from "../../i18n/context";
import Slider from "../ui/Slider";
import Checkbox from "../ui/Checkbox";
import Dropdown from "../ui/Dropdown";
import { StatusBanner } from "../ui/panelPrimitives";
import { StructureMode, ColorMode, type BackingOutput } from "../../api/types";
import { WIKI_DOCS } from "../../utils/wikiDocs";
import { useState } from "react";
import MaterialLayerUnlockDialog from "./MaterialLayerUnlockDialog";

export default function AdvancedSettings() {
  const { t } = useI18n();
  // Turning the 30-layer switch on asks first; turning it off does not.
  // 打开 30 层开关前先确认；关闭时不弹出。
  const [confirmUnlockOpen, setConfirmUnlockOpen] = useState(false);
  const enable_cleanup = useConverterStore((s) => s.enable_cleanup);
  const separate_backing = useConverterStore((s) => s.separate_backing);
  const backingOutput = useConverterStore((s) => s.backingOutput);
  const setBackingOutput = useConverterStore((s) => s.setBackingOutput);
  const canSeparateProjects = useConverterStore((s) => s.structure_mode === StructureMode.SINGLE_SIDED
    && !s.enable_relief && s.color_mode !== ColorMode.FIVE_COLOR_EXT
    && !s.batchMode && !s.puzzleEnabled && !s.largeFormatEnabled && !s.modelSurfaceEnabled);
  const hue_enable = useConverterStore((s) => s.hue_enable);
  const use_lut_constrained = useConverterStore((s) => s.use_lut_constrained);
  const auto_dynamic_range = useConverterStore((s) => s.auto_dynamic_range);
  const high_precision_3d_preview = useConverterStore((s) => s.high_precision_3d_preview);
  const chroma_gate = useConverterStore((s) => s.chroma_gate);
  const quantize_colors_unlocked = useConverterStore((s) => s.quantize_colors_unlocked);
  const dynamicMaterialLayerCountActive = useConverterStore((s) =>
    isDynamicMaterialActive(s),
  );
  const setEnableCleanup = useConverterStore((s) => s.setEnableCleanup);
  const setSeparateBacking = useConverterStore((s) => s.setSeparateBacking);
  const setHueEnable = useConverterStore((s) => s.setHueEnable);
  const setUseLutConstrained = useConverterStore((s) => s.setUseLutConstrained);
  const setAutoDynamicRange = useConverterStore((s) => s.setAutoDynamicRange);
  const setHighPrecision3dPreview = useConverterStore((s) => s.setHighPrecision3dPreview);
  const setChromaGate = useConverterStore((s) => s.setChromaGate);
  const setQuantizeColorsUnlocked = useConverterStore((s) => s.setQuantizeColorsUnlocked);
  const materialLayersUnlocked = useConverterStore((s) => s.materialLayersUnlocked);
  const setMaterialLayersUnlocked = useConverterStore((s) => s.setMaterialLayersUnlocked);

  return (
    <div className="flex flex-col gap-4">
      <Checkbox
        label={t("adv_isolated_pixel_cleanup")}
        tooltip={t("adv_isolated_pixel_cleanup_hint")}
        wikiPath={WIKI_DOCS.isolatedPixelCleanup}
        checked={enable_cleanup}
        onChange={setEnableCleanup}
      />
      <Checkbox
        label={t("adv_separate_backing")}
        tooltip={t("adv_separate_backing_hint")}
        wikiPath={WIKI_DOCS.separateBacking}
        checked={separate_backing}
        onChange={setSeparateBacking}
      />
      {separate_backing && (canSeparateProjects ? <>
        <Dropdown
          label={t("adv_backing_output")}
          value={backingOutput}
          options={[
            { value: "same_project", label: t("adv_backing_output_same") },
            { value: "separate_project", label: t("adv_backing_output_separate") },
          ]}
          onChange={(value) => setBackingOutput(value as BackingOutput)}
        />
        {backingOutput === "separate_project" && <StatusBanner>{t("adv_backing_output_hint")}</StatusBanner>}
      </> : <StatusBanner action={backingOutput === "separate_project" ?
        <button type="button" className="underline" onClick={() => setBackingOutput("same_project")}>{t("adv_backing_output_same")}</button>
        : undefined}>{t("adv_backing_output_unavailable")}</StatusBanner>)}
      <Checkbox
        label={t("adv_precise_color_matching")}
        tooltip={t("adv_precise_color_matching_hint")}
        wikiPath={WIKI_DOCS.preciseColorMatching}
        checked={use_lut_constrained}
        onChange={setUseLutConstrained}
      />
      <Checkbox
        label={t("adv_auto_dynamic_range")}
        tooltip={t("adv_auto_dynamic_range_hint")}
        wikiPath={WIKI_DOCS.autoDynamicRange}
        checked={auto_dynamic_range}
        onChange={setAutoDynamicRange}
      />
      <Checkbox
        label={t("adv_high_precision_3d_preview")}
        tooltip={t("adv_high_precision_3d_preview_hint")}
        wikiPath={WIKI_DOCS.highPrecision3dPreview}
        checked={high_precision_3d_preview}
        onChange={setHighPrecision3dPreview}
      />
      <Checkbox
        label={t("adv_hue_protection")}
        wikiPath={WIKI_DOCS.hueProtection}
        tooltip={t("adv_hue_protection_hint")}
        disabled={use_lut_constrained || dynamicMaterialLayerCountActive}
        checked={
          hue_enable &&
          !use_lut_constrained &&
          !dynamicMaterialLayerCountActive
        }
        onChange={setHueEnable}
      />
      {(dynamicMaterialLayerCountActive || use_lut_constrained) && (
        <p role="status" className="text-xs leading-5 text-slate-500 dark:text-slate-400">
          {t(
            dynamicMaterialLayerCountActive
              ? "adv_hue_protection_dynamic_status"
              : "adv_hue_protection_disabled_status",
          )}
        </p>
      )}
      {hue_enable && !use_lut_constrained && !dynamicMaterialLayerCountActive && (
        <Slider label={t("adv_chroma_gate")} tooltip={t("adv_chroma_gate_hint")} wikiPath={WIKI_DOCS.darkChromaGate} value={chroma_gate} min={0} max={50} step={1} onChange={setChromaGate} />
      )}
      <Checkbox
        label={t("adv_unlock_quantize")}
        tooltip={t("adv_unlock_quantize_hint")}
        wikiPath={WIKI_DOCS.unlockQuantizeCeiling}
        checked={quantize_colors_unlocked}
        onChange={setQuantizeColorsUnlocked}
      />
      <Checkbox
        label={t("adv_unlock_material_layers")}
        tooltip={t("adv_unlock_material_layers_hint")}
        checked={materialLayersUnlocked}
        onChange={(checked) => {
          if (checked) setConfirmUnlockOpen(true);
          else setMaterialLayersUnlocked(false);
        }}
      />
      <MaterialLayerUnlockDialog
        open={confirmUnlockOpen}
        onConfirm={() => {
          setConfirmUnlockOpen(false);
          setMaterialLayersUnlocked(true);
        }}
        onCancel={() => setConfirmUnlockOpen(false)}
      />
    </div>
  );
}

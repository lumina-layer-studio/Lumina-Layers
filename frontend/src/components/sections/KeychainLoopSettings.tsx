import { useConverterStore } from "../../stores/converter";
import { useI18n } from "../../i18n/context";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";
import { WIKI_DOCS } from "../../utils/wikiDocs";

export default function KeychainLoopSettings() {
  const { t } = useI18n();
  const add_loop = useConverterStore((s) => s.add_loop);
  const puzzleEnabled = useConverterStore((s) => s.puzzleEnabled);
  const largeFormatEnabled = useConverterStore((s) => s.largeFormatEnabled);
  const enableFridgeMagnet = useConverterStore((s) => s.enable_fridge_magnet);
  const loop_width = useConverterStore((s) => s.loop_width);
  const loop_length = useConverterStore((s) => s.loop_length);
  const loop_hole = useConverterStore((s) => s.loop_hole);
  const loop_angle = useConverterStore((s) => s.loop_angle);
  const loop_offset_x = useConverterStore((s) => s.loop_offset_x);
  const loop_offset_y = useConverterStore((s) => s.loop_offset_y);
  const setAddLoop = useConverterStore((s) => s.setAddLoop);
  const setLoopWidth = useConverterStore((s) => s.setLoopWidth);
  const setLoopLength = useConverterStore((s) => s.setLoopLength);
  const setLoopHole = useConverterStore((s) => s.setLoopHole);
  const setLoopAngle = useConverterStore((s) => s.setLoopAngle);
  const setLoopOffsetX = useConverterStore((s) => s.setLoopOffsetX);
  const setLoopOffsetY = useConverterStore((s) => s.setLoopOffsetY);
  const loopDisabled = puzzleEnabled || largeFormatEnabled || enableFridgeMagnet;
  const loopEnabled = add_loop && !loopDisabled;

  return (
    <div className="flex flex-col gap-4">
      <Checkbox
        label={t("loop_enable")}
        checked={loopEnabled}
        onChange={setAddLoop}
        disabled={loopDisabled}
        tooltip={t("loop_enable_hint")}
        wikiPath={WIKI_DOCS.keychainLoop}
      />
      {puzzleEnabled && !add_loop && (
        <p className="-mt-2 px-1 text-xs text-slate-500 dark:text-slate-400">
          {t("puzzle_loop_disabled_hint")}
        </p>
      )}
      {enableFridgeMagnet && !add_loop && (
        <p className="-mt-2 px-1 text-xs text-slate-500 dark:text-slate-400">
          {t("fridge_magnet_loop_disabled_status")}
        </p>
      )}
      {largeFormatEnabled && (
        <p className="-mt-2 px-1 text-xs text-slate-500 dark:text-slate-400">
          {t("large_format_loop_disabled_hint")}
        </p>
      )}
      {loopEnabled && (
        <>
          <Slider label={t("loop_width")} tooltip={t("loop_width_hint")} wikiPath={WIKI_DOCS.keychainLoop} value={loop_width} min={2} max={10} step={0.5} unit="mm" onChange={setLoopWidth} />
          <Slider label={t("loop_length")} tooltip={t("loop_length_hint")} wikiPath={WIKI_DOCS.keychainLoop} value={loop_length} min={4} max={15} step={0.5} unit="mm" onChange={setLoopLength} />
          <Slider label={t("loop_hole_diameter")} tooltip={t("loop_hole_diameter_hint")} wikiPath={WIKI_DOCS.keychainLoop} value={loop_hole} min={1} max={5} step={0.25} unit="mm" onChange={setLoopHole} />

          <Slider label={t("loop_angle")} tooltip={t("loop_angle_hint")} wikiPath={WIKI_DOCS.keychainLoop} value={loop_angle} min={-180} max={180} step={1} unit="°" onChange={setLoopAngle} />
          <Slider label={t("loop_offset_x")} tooltip={t("loop_offset_x_hint")} wikiPath={WIKI_DOCS.keychainLoop} value={loop_offset_x} min={-200} max={200} step={0.5} unit="mm" onChange={setLoopOffsetX} />
          <Slider label={t("loop_offset_y")} tooltip={t("loop_offset_y_hint")} wikiPath={WIKI_DOCS.keychainLoop} value={loop_offset_y} min={-200} max={200} step={0.5} unit="mm" onChange={setLoopOffsetY} />
        </>
      )}
    </div>
  );
}

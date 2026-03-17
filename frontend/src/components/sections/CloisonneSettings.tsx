import { useConverterStore } from "../../stores/converterStore";
import { useI18n } from "../../i18n/context";
import { ModelingMode } from "../../api/types";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";

export default function CloisonneSettings() {
  const { t } = useI18n();
  const enable_cloisonne = useConverterStore((s) => s.enable_cloisonne);
  const wire_width_mm = useConverterStore((s) => s.wire_width_mm);
  const wire_height_mm = useConverterStore((s) => s.wire_height_mm);
  const modeling_mode = useConverterStore((s) => s.modeling_mode);
  const setEnableCloisonne = useConverterStore((s) => s.setEnableCloisonne);
  const setWireWidthMm = useConverterStore((s) => s.setWireWidthMm);
  const setWireHeightMm = useConverterStore((s) => s.setWireHeightMm);

  const isVector = modeling_mode === ModelingMode.VECTOR;

  return (
    <div className="flex flex-col gap-4">
      {/* 🚧 施工中标记 / Work-in-progress banner */}
      <div className="flex items-center gap-2 rounded-md bg-amber-50 dark:bg-amber-900/30 border border-amber-300 dark:border-amber-700 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
        <span>🚧</span>
        <span>{t("cloisonne_wip")}</span>
      </div>
      <Checkbox
        label={t("cloisonne_enable")}
        checked={enable_cloisonne}
        onChange={setEnableCloisonne}
        disabled={isVector}
      />
      {enable_cloisonne && (
        <>
          <Slider label={t("cloisonne_wire_width")} value={wire_width_mm} min={0.2} max={1.2} step={0.1} unit="mm" onChange={setWireWidthMm} />
          <Slider label={t("cloisonne_wire_height")} value={wire_height_mm} min={0.04} max={1.0} step={0.04} unit="mm" onChange={setWireHeightMm} />
        </>
      )}
    </div>
  );
}

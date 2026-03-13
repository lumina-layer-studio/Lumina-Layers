import { useConverterStore } from "../../stores/converterStore";
import { useI18n } from "../../i18n/context";
import { ModelingMode } from "../../api/types";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";

export default function OutlineSettings() {
  const { t } = useI18n();
  const enable_outline = useConverterStore((s) => s.enable_outline);
  const outline_width = useConverterStore((s) => s.outline_width);
  const modeling_mode = useConverterStore((s) => s.modeling_mode);
  const setEnableOutline = useConverterStore((s) => s.setEnableOutline);
  const setOutlineWidth = useConverterStore((s) => s.setOutlineWidth);

  const isVector = modeling_mode === ModelingMode.VECTOR;

  return (
    <div className="flex flex-col gap-4">
      <Checkbox
        label={t("outline_enable")}
        checked={enable_outline}
        onChange={setEnableOutline}
        disabled={isVector}
      />
      {enable_outline && (
        <Slider
          label={t("outline_width")}
          value={outline_width}
          min={0.5}
          max={10.0}
          step={0.5}
          unit="mm"
          onChange={setOutlineWidth}
        />
      )}
    </div>
  );
}

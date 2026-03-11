import { useConverterStore } from "../../stores/converterStore";
import { ModelingMode } from "../../api/types";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";

export default function OutlineSettings() {
  const enable_outline = useConverterStore((s) => s.enable_outline);
  const outline_width = useConverterStore((s) => s.outline_width);
  const modeling_mode = useConverterStore((s) => s.modeling_mode);
  const setEnableOutline = useConverterStore((s) => s.setEnableOutline);
  const setOutlineWidth = useConverterStore((s) => s.setOutlineWidth);

  const isVector = modeling_mode === ModelingMode.VECTOR;

  return (
    <div className="flex flex-col gap-4">
      <Checkbox
        label="启用描边"
          checked={enable_outline}
          onChange={setEnableOutline}
          disabled={isVector}
        />

        {enable_outline && (
          <Slider
            label="描边宽度"
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

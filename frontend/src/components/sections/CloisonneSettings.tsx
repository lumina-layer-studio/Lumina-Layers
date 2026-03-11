import { useConverterStore } from "../../stores/converterStore";
import { ModelingMode } from "../../api/types";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";

export default function CloisonneSettings() {
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
      <Checkbox
        label="启用掐丝珐琅"
          checked={enable_cloisonne}
          onChange={setEnableCloisonne}
          disabled={isVector}
        />

        {enable_cloisonne && (
          <>
            <Slider
              label="金属丝宽度"
              value={wire_width_mm}
              min={0.2}
              max={1.2}
              step={0.1}
              unit="mm"
              onChange={setWireWidthMm}
            />

            <Slider
              label="金属丝高度"
              value={wire_height_mm}
              min={0.04}
              max={1.0}
              step={0.04}
              unit="mm"
              onChange={setWireHeightMm}
            />
          </>
        )}
    </div>
  );
}

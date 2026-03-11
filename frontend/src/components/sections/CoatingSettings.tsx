import { useConverterStore } from "../../stores/converterStore";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";

export default function CoatingSettings() {
  const enable_coating = useConverterStore((s) => s.enable_coating);
  const coating_height_mm = useConverterStore((s) => s.coating_height_mm);
  const setEnableCoating = useConverterStore((s) => s.setEnableCoating);
  const setCoatingHeightMm = useConverterStore((s) => s.setCoatingHeightMm);

  return (
    <div className="flex flex-col gap-4">
      <Checkbox
        label="启用涂层"
          checked={enable_coating}
          onChange={setEnableCoating}
        />

        {enable_coating && (
          <Slider
            label="涂层高度"
            value={coating_height_mm}
            min={0.04}
            max={0.12}
            step={0.04}
            unit="mm"
            onChange={setCoatingHeightMm}
          />
        )}
    </div>
  );
}

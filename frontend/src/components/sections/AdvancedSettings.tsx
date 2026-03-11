import { useConverterStore } from "../../stores/converterStore";
import Slider from "../ui/Slider";
import Checkbox from "../ui/Checkbox";

export default function AdvancedSettings() {
  const quantize_colors = useConverterStore((s) => s.quantize_colors);
  const bg_tol = useConverterStore((s) => s.bg_tol);
  const auto_bg = useConverterStore((s) => s.auto_bg);
  const enable_cleanup = useConverterStore((s) => s.enable_cleanup);
  const separate_backing = useConverterStore((s) => s.separate_backing);
  const setQuantizeColors = useConverterStore((s) => s.setQuantizeColors);
  const setBgTol = useConverterStore((s) => s.setBgTol);
  const setAutoBg = useConverterStore((s) => s.setAutoBg);
  const setEnableCleanup = useConverterStore((s) => s.setEnableCleanup);
  const setSeparateBacking = useConverterStore((s) => s.setSeparateBacking);

  return (
    <div className="flex flex-col gap-4">
      <Slider
          label="量化颜色数"
          value={quantize_colors}
          min={8}
          max={256}
          step={8}
          onChange={setQuantizeColors}
        />

        <Slider
          label="背景容差"
          value={bg_tol}
          min={0}
          max={150}
          step={1}
          onChange={setBgTol}
        />

        <Checkbox
          label="自动背景"
          checked={auto_bg}
          onChange={setAutoBg}
        />

        <Checkbox
          label="启用清理"
          checked={enable_cleanup}
          onChange={setEnableCleanup}
        />

        <Checkbox
          label="分离底板"
          checked={separate_backing}
          onChange={setSeparateBacking}
        />
    </div>
  );
}

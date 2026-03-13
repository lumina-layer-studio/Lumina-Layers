import { useConverterStore } from "../../stores/converterStore";
import { useI18n } from "../../i18n/context";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";

export default function KeychainLoopSettings() {
  const { t } = useI18n();
  const add_loop = useConverterStore((s) => s.add_loop);
  const loop_width = useConverterStore((s) => s.loop_width);
  const loop_length = useConverterStore((s) => s.loop_length);
  const loop_hole = useConverterStore((s) => s.loop_hole);
  const setAddLoop = useConverterStore((s) => s.setAddLoop);
  const setLoopWidth = useConverterStore((s) => s.setLoopWidth);
  const setLoopLength = useConverterStore((s) => s.setLoopLength);
  const setLoopHole = useConverterStore((s) => s.setLoopHole);

  return (
    <div className="flex flex-col gap-4">
      <Checkbox label={t("loop_enable")} checked={add_loop} onChange={setAddLoop} />
      {add_loop && (
        <>
          <Slider label={t("loop_width")} value={loop_width} min={2} max={10} step={0.5} unit="mm" onChange={setLoopWidth} />
          <Slider label={t("loop_length")} value={loop_length} min={4} max={15} step={0.5} unit="mm" onChange={setLoopLength} />
          <Slider label={t("loop_hole_diameter")} value={loop_hole} min={1} max={5} step={0.25} unit="mm" onChange={setLoopHole} />
        </>
      )}
    </div>
  );
}

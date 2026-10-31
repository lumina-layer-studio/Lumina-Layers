import { useConverterStore } from "../../stores/converter";
import { useI18n } from "../../i18n/context";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";
import { WIKI_DOCS } from "../../utils/wikiDocs";

export default function CoatingSettings() {
  const { t } = useI18n();
  const enable_coating = useConverterStore((s) => s.enable_coating);
  const coating_height_mm = useConverterStore((s) => s.coating_height_mm);
  const setEnableCoating = useConverterStore((s) => s.setEnableCoating);
  const setCoatingHeightMm = useConverterStore((s) => s.setCoatingHeightMm);

  return (
    <div className="flex flex-col gap-4" data-tutorial="coating-settings">
      <Checkbox
        label={t("coating_enable")}
        checked={enable_coating}
        onChange={setEnableCoating}
        tooltip={t("coating_enable_hint")}
        wikiPath={WIKI_DOCS.transparentCoating}
      />
      {enable_coating && (
        <Slider
          label={t("coating_height")}
          tooltip={t("coating_height_hint")}
          wikiPath={WIKI_DOCS.transparentCoating}
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

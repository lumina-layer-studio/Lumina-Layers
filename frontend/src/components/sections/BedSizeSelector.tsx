import { useConverterStore } from "../../stores/converterStore";
import { useI18n } from "../../i18n/context";
import Dropdown from "../ui/Dropdown";

export default function BedSizeSelector() {
  const { t } = useI18n();
  const { bed_label, bedSizes, bedSizesLoading, setBedLabel } =
    useConverterStore();

  const options = bedSizes.map((bed) => ({
    label: bed.label,
    value: bed.label,
  }));

  return (
    <Dropdown
      label={t("bed_size_label")}
      value={bed_label}
      options={options}
      onChange={setBedLabel}
      disabled={bedSizesLoading}
      placeholder={bedSizesLoading ? t("bed_size_loading") : t("bed_size_placeholder")}
    />
  );
}

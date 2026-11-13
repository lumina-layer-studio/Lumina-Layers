import { useConverterStore } from "../../stores/converter";
import { useState } from "react";
import ProjectDeviceDialog from "../projects/ProjectDeviceDialog";
import { useI18n } from "../../i18n/context";
import HelpDot from "../ui/HelpDot";

export default function BedSizeSelector() {
  const { t } = useI18n();
  const bed_label = useConverterStore((s) => s.bed_label);
  const bedSizes = useConverterStore((s) => s.bedSizes);
  const [editing, setEditing] = useState(false);
  const selectedBed = bedSizes.find((bed) => bed.label === bed_label);
  const dimensions = selectedBed
    ? `${selectedBed.width_mm}×${selectedBed.height_mm} ${t('common_unit_mm')}`
    : null;
  const bedSummary =
    dimensions && selectedBed?.printer_id
      ? `${bed_label} · ${dimensions}`
      : bed_label;

  return (
    <><div className="flex items-center justify-between gap-3">
      <span className="flex shrink-0 items-center gap-1.5 text-[clamp(0.65rem,0.85vw,0.75rem)] font-medium text-slate-500 dark:text-slate-400">
        {t("bed_size_label")}
        <HelpDot
          title={t("bed_size_label")}
          description={t("bed_size_hint")}
          ariaLabel={t("bed_size_hint_aria")}
          placement="left"
        />
      </span>
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate text-[clamp(0.65rem,0.85vw,0.75rem)] tabular-nums text-slate-700 dark:text-slate-200">
          {bedSummary}
        </span>
        <button
          type="button"
          onClick={() => setEditing(true)}
          aria-label={t("project_device_settings")}
          className="action-control shrink-0 rounded-lg px-2 py-1 text-[clamp(0.65rem,0.85vw,0.75rem)] font-medium"
        >
          {t("bed_size_change")}
        </button>
      </span>
    </div>{editing && <ProjectDeviceDialog onClose={() => setEditing(false)} />}</>
  );
}

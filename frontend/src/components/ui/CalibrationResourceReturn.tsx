import type { ResourceKind } from "../../api/resources";
import { useI18n } from "../../i18n/context";
import { returnFromResourceCalibration, useResourceCalibrationStore } from "../../stores/converter/resourceSelection";
import Button from "./Button";
import { StatusBanner } from "./panelPrimitives";

/** Only a calibration started from a converter picker has a task to return to. */
export default function CalibrationResourceReturn({ family, resource }: { family: ResourceKind; resource: string | null | undefined }) {
  const { t } = useI18n();
  const { context, returning, error } = useResourceCalibrationStore();
  if (!resource || context?.family !== family || context.phase !== "calibrating") return null;
  return <div className="flex flex-col gap-2">
    <p className="text-sm text-slate-500 dark:text-slate-400">{t("resources_calibration_return_hint")}</p>
    <Button label={t(family === "materials" ? "material_guide_add_to_palette" : "resources_use_for_task")} variant="primary" loading={returning}
      onClick={() => void returnFromResourceCalibration(family, resource)} />
    {error && <StatusBanner tone="error">{error}</StatusBanner>}
  </div>;
}

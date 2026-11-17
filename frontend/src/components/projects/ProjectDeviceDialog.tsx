import { useEffect, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { getPrinters, getSlicers } from "../../api/system";
import { apiErrorToVisibleMessage } from "../../api/client";
import type { PrinterInfo, SlicerOption } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { useConverterStore } from "../../stores/converter";
import { captureProjectSettings, resolveProjectDeviceSettings, type ProjectConverterSettings } from "../../stores/converter/project";
import { useSettingsStore, type NozzleSize } from "../../stores/settingsStore";
import { useProjectSessionStore } from "../../stores/projectSessionStore";
import { setWorkflowRuntime, useWorkflowRuntime, workflowRuntime } from "../../project/workflowRuntime";
import { invalidateGeneratedArtifacts } from "../../stores/generatedArtifactInvalidation";
import { filterCompatiblePrinters } from "../../utils/settingsOptionIds";
import MachineSelectionDialog from "../settings/MachineSelectionDialog";
import BuildPlateSelector from "../settings/BuildPlateSelector";
import Button from "../ui/Button";
import { StatusBanner } from "../ui/panelPrimitives";

export default function ProjectDeviceDialog({ kind = "converter", onClose }: { kind?: string; onClose: () => void }) {
  const { t } = useI18n();
  const defaults = useSettingsStore(useShallow(captureProjectSettings));
  const converterSettings = useConverterStore((state) => state.projectSettings);
  const workflowSettings = useWorkflowRuntime((state) => state.workflows[kind]?.settings);
  const settings = (kind === "converter" ? converterSettings : workflowSettings) ?? defaults;
  const status = useProjectSessionStore((state) => state.status);
  const converterBusy = useConverterStore((state) => state.isLoading || state.isGenerating || state.historyBusy || state.replacePreviewLoading || state.contentCommitStatus === "pending" || state.contentCommitStatus === "unknown");
  const busy = status === "saving" || status === "opening" || (kind === "converter" && converterBusy);
  const [printers, setPrinters] = useState<PrinterInfo[]>([]);
  const [slicers, setSlicers] = useState<SlicerOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    void Promise.all([getPrinters(), getSlicers()]).then(([machines, software]) => {
      if (!cancelled) { setPrinters(machines); setSlicers(software); }
    }).catch((cause: unknown) => {
      if (!cancelled) setError(apiErrorToVisibleMessage(cause));
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [attempt]);
  const apply = (changes: Partial<ProjectConverterSettings>) => {
    if (busy || loading) return;
    const next = resolveProjectDeviceSettings(settings, changes, printers);
    if (kind === "converter") useConverterStore.getState().setProjectSettings(next);
    else {
      invalidateGeneratedArtifacts({ preservePreviews: true });
      setWorkflowRuntime(kind, { contextId: null, lutFiles: {}, ...workflowRuntime(kind), settings: next });
    }
  };
  const profile = printers.find((printer) => printer.id === settings.printerModel)?.device_profiles?.find((item) => item.device_profile_id === settings.deviceProfileId);
  return <MachineSelectionDialog open description={t("project_device_detail")} printers={filterCompatiblePrinters(printers, settings.slicerSoftware)} slicers={slicers} printersLoading={loading || busy} slicersLoading={loading || busy} printerModel={settings.printerModel} slicerSoftware={settings.slicerSoftware} nozzleSize={settings.nozzleSize}
    onPrinterChange={(printerModel) => apply({ printerModel })}
    onSlicerChange={(slicerSoftware) => apply({ slicerSoftware })}
    onPrinterNozzleChange={(printer, nozzleSize) => apply({ printerModel: printer.id, nozzleSize: nozzleSize as NozzleSize })}
    onClose={onClose} footer={<>
      {error && <StatusBanner tone="error">{error}<Button label={t("project_retry")} size="sm" onClick={() => setAttempt((value) => value + 1)} /></StatusBanner>}
      {busy ? <StatusBanner tone="info">{t("project_device_wait")}</StatusBanner> : <BuildPlateSelector label={t("settings.build_plate")} hint={t("settings.build_plate_hint")} plates={profile?.build_plates ?? []} selectedId={settings.buildPlateId} onSelect={(buildPlateId) => apply({ buildPlateId })} />}
    </>} />;
}

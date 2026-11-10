import { useEffect } from "react";
import { useConverterStore, converterDocumentHistory } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import { captureConversionParameters, presetMatchesCurrent } from "../stores/conversionPreferences";

export function bindConversionPreferences(): () => void {
  let adjustingImageSize = false;
  let edited = false;
  const restore = () => {
    const current = useConverterStore.getState();
    const last = useSettingsStore.getState().conversionPreferences.last;
    if (!last || current.conversionParameterContext !== "defaults" || current.imageFile) return;
    if (presetMatchesCurrent(last, captureConversionParameters(current))) return;
    converterDocumentHistory.amendCurrent(() => current.restoreConversionDefaults());
  };
  restore();
  const stopConverter = useConverterStore.subscribe((current, previous) => {
    if (current.conversionParameterContext === "restoring" && previous.conversionParameterContext === "defaults") {
      const settings = useSettingsStore.getState();
      if (!settings.conversionPreferences.last) settings.setConversionPreferences({
        ...settings.conversionPreferences, last: captureConversionParameters(previous),
      });
    }
    if (adjustingImageSize || current.conversionParameterContext !== "defaults") return;
    if (current.imageFile && !current.workshopSource && current.aspectRatio && current.aspectRatio !== previous.aspectRatio) {
      adjustingImageSize = true;
      try {
        // The image loader restores the remembered long edge. Anchor that
        // edge so rounding the short edge cannot grow the saved size.
        if (current.aspectRatio < 1) current.setTargetHeightMm(current.target_height_mm);
        else current.setTargetWidthMm(current.target_width_mm);
      } finally { adjustingImageSize = false; }
    }
    const parameters = captureConversionParameters(useConverterStore.getState());
    if (JSON.stringify(parameters) === JSON.stringify(captureConversionParameters(previous))) return;
    edited = true;
    const settings = useSettingsStore.getState();
    settings.setConversionPreferences({ ...settings.conversionPreferences, last: parameters });
  });
  const stopSettings = useSettingsStore.subscribe((current, previous) => {
    if (!edited && JSON.stringify(current.conversionPreferences.last) !== JSON.stringify(previous.conversionPreferences.last)) restore();
  });
  return () => { stopConverter(); stopSettings(); };
}

export function useConversionPreferences(): void {
  useEffect(bindConversionPreferences, []);
}

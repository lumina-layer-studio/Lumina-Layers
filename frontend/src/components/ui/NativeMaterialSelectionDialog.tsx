import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ExportMaterialSelection } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { useConverterStore } from "../../stores/converter";
import { resolveConverterSettings } from "../../stores/converter/project";
import {
  externalSpoolMaterial,
  scopedNativeFilamentProfiles,
  selectableExternalSpoolMaterials,
  supportsExternalSpool,
} from "../../stores/converter/nativeMaterialSelection";
import { useSettingsStore } from "../../stores/settingsStore";
import Button from "./Button";
import CloseButton from "./CloseButton";
import Dropdown from "./Dropdown";

function MaterialSelectionContent({ selection, isEditing }: {
  selection: ExportMaterialSelection;
  isEditing: boolean;
}) {
  const { t } = useI18n();
  const cancelLabel = t(isEditing ? "native_material_edit_cancel" : "native_material_cancel");
  const templateManaged = selection.ready && selection.materials.length === 0;
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const applySelection = useConverterStore((state) => state.applyNativeMaterialSelection);
  const refreshSelection = useConverterStore((state) => state.refreshNativeMaterialSelection);
  const cancelSelection = useConverterStore((state) => state.cancelNativeMaterialSelection);
  const isChecking = useConverterStore((state) => state.nativeMaterialSelectionLoading);
  const selectionError = useConverterStore((state) => state.nativeMaterialSelectionError);
  const projectSettings = useConverterStore((state) => state.projectSettings);
  const hasExternalSpool = useSettingsStore((defaults) => supportsExternalSpool(projectSettings ?? defaults));
  const spoolMaterials = selectableExternalSpoolMaterials(selection);
  const [savedSpool] = useState(() => externalSpoolMaterial(useConverterStore.getState(), useSettingsStore.getState()));
  const [spool, setSpool] = useState(() =>
    savedSpool && spoolMaterials.includes(savedSpool) ? savedSpool : "",
  );
  const [plateId, setPlateId] = useState(() =>
    selection.build_plates.find((plate) => plate.build_plate_uid === selection.build_plate_uid)?.id ?? "",
  );
  const [profiles, setProfiles] = useState<Record<string, string>>(() => {
    const state = useConverterStore.getState();
    const saved = scopedNativeFilamentProfiles(state, resolveConverterSettings(state, useSettingsStore.getState()));
    return Object.fromEntries(selection.materials.map((material) => [
      material.name,
      material.profiles.some((profile) => profile.available && profile.name === saved?.[material.name])
        ? saved![material.name]
        : "",
    ]));
  });
  const plate = selection.build_plates.find((row) => row.id === plateId);
  const plateUid = plate?.build_plate_uid ?? selection.build_plate_uid;
  const compatiblePlates = selection.build_plates.filter((row) => row.compatible);
  const canApply = !isChecking && !selectionError && selection.ready &&
    Boolean(plate?.compatible) && plateUid === selection.build_plate_uid;

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelSelection();
      } else if (event.key === "Tab" && dialogRef.current) {
        const controls = dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), [tabindex="0"]',
        );
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, [cancelSelection]);

  function changePlate(nextId: string): void {
    const nextPlate = selection.build_plates.find((row) => row.id === nextId);
    if (!nextPlate) return;
    setPlateId(nextId);
    void refreshSelection(profiles, nextId);
  }

  function changeProfile(materialName: string, profileName: string): void {
    const nextProfiles = { ...profiles, [materialName]: profileName };
    setProfiles(nextProfiles);
    void refreshSelection(nextProfiles, plateId);
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4 backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
      onClick={cancelSelection}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={isChecking}
        tabIndex={-1}
        className="panel-card flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl text-slate-800 outline-none dark:text-slate-100"
        style={{ background: "var(--surface-panel-strong)" }}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 px-5 py-4">
          <div>
            <h2 id={titleId} className="text-base font-semibold">
              {t(isEditing ? "native_material_edit_title" : "native_material_dialog_title")}
            </h2>
            <p id={descriptionId} className="mt-1 text-sm leading-6 text-[var(--surface-text-muted)]">
              {t(isEditing ? "native_material_edit_description" : "native_material_dialog_description")}
            </p>
          </div>
          <CloseButton label={t("native_material_close")} onClick={cancelSelection} />
        </header>
        <div className="panel-divider min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-y-contain border-t px-5 py-4">
          {isChecking && (
            <p className="status-banner text-sm" data-tone="info" role="status">
              {t("native_material_rechecking")}
            </p>
          )}
          {selectionError && (
            <div className="status-banner space-y-2 text-sm" data-tone="error" role="alert">
              <p>{t(selectionError)}</p>
              <Button
                label={t("native_material_recheck")}
                size="sm"
                variant="secondary"
                onClick={() => void refreshSelection(profiles, plateId)}
              />
            </div>
          )}
          {!isChecking && !selectionError && selection.issues
            .filter((issue) => issue.material_index === null)
            .map((issue) => (
              <p key={issue.code} className="status-banner text-sm" data-tone="warning" role="status">
                {t(issue.code)}
              </p>
            ))}
          {templateManaged ? (
            <p className="status-banner text-sm" data-tone="info" role="status">
              {t("native_material_template_managed")}
            </p>
          ) : (
            <Dropdown
              label={t("native_material_build_plate")}
              value={plateId}
              onChange={changePlate}
              options={compatiblePlates.map((row) => ({ value: row.id, label: row.name }))}
              placeholder={plate?.name ?? t("native_material_choose_plate")}
              disabled={compatiblePlates.length === 0}
            />
          )}
          {!templateManaged && !isChecking && !selectionError && compatiblePlates.length === 0 && (
            <p className="status-banner text-sm" data-tone="warning" role="status">
              {t("native_material_no_compatible_plate")}
            </p>
          )}
          {hasExternalSpool && !templateManaged && (
            <div className="space-y-2">
              <Dropdown
                label={t("native_material_external_spool")}
                tooltip={t("native_material_external_spool_help")}
                value={spool}
                onChange={setSpool}
                options={[
                  { value: "", label: t("native_material_automatic_option") },
                  ...spoolMaterials.map((name) => ({ value: name, label: name })),
                ]}
              />
              {savedSpool && !spoolMaterials.includes(savedSpool) && (
                <p className="status-banner text-sm" data-tone="warning" role="status">
                  {t("native_material_external_spool_missing").replace("{material}", savedSpool)}
                </p>
              )}
              {spoolMaterials.length < selection.materials.length && (
                <p className="status-banner text-sm" data-tone="warning" role="status">
                  {t("native_material_external_spool_duplicate")}
                </p>
              )}
            </div>
          )}
          {selection.materials.map((material, index) => {
            const candidates = material.profiles.filter((profile) => profile.available);
            const chosen = profiles[material.name] ?? "";
            const automatic = !chosen && !isChecking && !selectionError ? material.selected_profile_name : null;
            const reportedIssue = selection.issues.find((issue) => issue.material_index === index);
            const issueCode = !isChecking && !selectionError ? reportedIssue?.code : null;
            const message = issueCode ? t(issueCode)
              .replace("{material}", material.name)
              .replace("{type}", material.material_type)
              .replace("{plate}", plate?.name ?? "") : null;
            return (
              <section key={`${index}:${material.name}`} className="panel-divider space-y-2 border-t pt-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="break-words text-sm font-semibold">{material.name}</h3>
                  <span className="text-xs text-[var(--surface-text-muted)]">{material.material_type}</span>
                </div>
                <Dropdown
                  label={t("native_material_profile")}
                  value={chosen}
                  onChange={(name) => changeProfile(material.name, name)}
                  options={[
                    {
                      value: "",
                      label: automatic
                        ? t("native_material_automatic").replace("{profile}", automatic)
                        : t("native_material_automatic_option"),
                    },
                    ...candidates.map((profile) => ({ value: profile.name, label: profile.name })),
                  ]}
                  disabled={candidates.length === 0}
                />
                {message && (
                  <p className="status-banner text-sm" data-tone="warning" role="status">{message}</p>
                )}
              </section>
            );
          })}
        </div>
        <footer className="panel-divider flex justify-end gap-2 border-t px-5 py-4">
          <Button label={cancelLabel} variant="secondary" onClick={cancelSelection} />
          {!templateManaged && (
            <Button
              label={t(isEditing ? "native_material_edit_save" : "native_material_apply")}
              disabled={!canApply}
              onClick={() => void applySelection(profiles, plateId, spool || undefined)}
              variant="primary"
            />
          )}
        </footer>
      </div>
    </div>,
    document.body,
  );
}

export default function NativeMaterialSelectionDialog() {
  const selection = useConverterStore((state) => state.nativeMaterialSelection);
  const action = useConverterStore((state) => state.nativeMaterialSelectionAction);
  return selection ? <MaterialSelectionContent selection={selection} isEditing={action === "edit"} /> : null;
}

import { describe, it, expect, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";
import type { SettingsState } from "../stores/settingsStore";

// ========== Constants ==========

const VALID_PRINTER_IDS = [
  "bambu-a1-mini",
  "bambu-a1",
  "bambu-p1p",
  "bambu-p1s",
  "bambu-x1c",
  "bambu-x1e",
  "bambu-h2d",
  "bambu-h2d-pro",
  "bambu-h2s",
  "bambu-p2s",
  "bambu-h2c",
] as const;

// ========== Helpers ==========

function resetStore() {
  useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  localStorage.clear();
}

// ========== Generators ==========

const arbPrinterId = fc.constantFrom(...VALID_PRINTER_IDS);

// ========== P5: Printer Model Selection Round-Trip ==========

// **Validates: Requirements 2.1**
describe("P5: Printer Model Selection Persistence Round-Trip", () => {
  beforeEach(() => {
    resetStore();
  });

  it("setPrinterModel writes to store state correctly for any valid printer ID", () => {
    fc.assert(
      fc.property(arbPrinterId, (printerId) => {
        localStorage.clear();
        useSettingsStore.setState({ ...DEFAULT_SETTINGS });

        useSettingsStore.getState().setPrinterModel(printerId);

        const storeValue = useSettingsStore.getState().printerModel;
        expect(storeValue).toBe(printerId);
      }),
      { numRuns: 100 }
    );
  });

  it("printerModel persists to localStorage and can be restored (round-trip)", () => {
    fc.assert(
      fc.property(arbPrinterId, (printerId) => {
        localStorage.clear();
        useSettingsStore.setState({ ...DEFAULT_SETTINGS });

        useSettingsStore.getState().setPrinterModel(printerId);

        const raw = localStorage.getItem("lumina-settings");
        expect(raw).not.toBeNull();

        const parsed = JSON.parse(raw!);
        const persisted: SettingsState = parsed.state;

        expect(persisted.printerModel).toBe(printerId);
      }),
      { numRuns: 100 }
    );
  });

  it("sequential printerModel changes always reflect the last written value", () => {
    fc.assert(
      fc.property(
        fc.array(arbPrinterId, { minLength: 1, maxLength: 20 }),
        (printerIds) => {
          localStorage.clear();
          useSettingsStore.setState({ ...DEFAULT_SETTINGS });

          for (const pid of printerIds) {
            useSettingsStore.getState().setPrinterModel(pid);
          }

          const lastId = printerIds[printerIds.length - 1];

          expect(useSettingsStore.getState().printerModel).toBe(lastId);

          const raw = localStorage.getItem("lumina-settings");
          expect(raw).not.toBeNull();
          const persisted: SettingsState = JSON.parse(raw!).state;
          expect(persisted.printerModel).toBe(lastId);
        }
      ),
      { numRuns: 100 }
    );
  });

  it("default printerModel is 'bambu-h2d' (backward compatibility)", () => {
    expect(DEFAULT_SETTINGS.printerModel).toBe("bambu-h2d");

    localStorage.clear();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    expect(useSettingsStore.getState().printerModel).toBe("bambu-h2d");
  });
});

import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import apiClient from "../api/client";
import { ColorMode, ModelingMode } from "../api/types";
import { fetchSimilarRecipes, getEditorSelection } from "../api/converter";
import { closeSession } from "../api/session";
import { createConverterProjectAdapter } from "../project/adapters/converterAdapter";
import { ProjectAdapterRegistry } from "../project/adapters/registry";
import { parseProject, serializeProject } from "../project/archive";
import { createProjectSnapshot } from "../project/identity";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

// Opt-in production API test: start an isolated api_server.py, then run with
// LUMINA_PROJECT_TEST_API=http://127.0.0.1:<port>/api. No API calls are mocked.
describe.skipIf(!process.env.LUMINA_PROJECT_TEST_API)("edited project resize roundtrip against a live backend", () => {
  it("saves new dimensions without another preview, reopens edits, then saves and opens again", async () => {
    const baseURL = apiClient.defaults.baseURL;
    apiClient.defaults.baseURL = process.env.LUMINA_PROJECT_TEST_API;
    const sessions = new Set<string>();
    const adapter = createConverterProjectAdapter();
    const registry = new ProjectAdapterRegistry([adapter]);
    async function save() {
      const captured = await adapter.capture();
      return serializeProject(createProjectSnapshot({
        name: "Resize edited SVG", workflowKinds: ["converter"],
        documents: [captured.document], assets: captured.assets,
      }));
    }
    try {
      useSettingsStore.setState({ ...DEFAULT_SETTINGS });
      const image = await readFile(resolve("../tests/fixtures/svg_vector/dynamic_material_lifecycle.svg"));
      useConverterStore.setState({
        ...DEFAULT_STATE, imageFile: new File([new Uint8Array(image)], "dynamic_material_lifecycle.svg", { type: "image/svg+xml" }),
        source_version: "legacy", lut_name: "bambulab - bambulab_pla_basic_cmyw",
        lut_names: ["bambulab - bambulab_pla_basic_cmyw"], color_mode: ColorMode.FOUR_COLOR_CMYW,
        modeling_mode: ModelingMode.VECTOR, target_width_mm: 62,
      });
      await useConverterStore.getState().submitPreview();
      const initial = useConverterStore.getState();
      expect(initial.error).toBeNull();
      expect(initial.sessionId).toBeTruthy();
      const sid = initial.sessionId!;
      sessions.add(sid);
      await initial.applySelectionMutation({ operation: "same-color-toggle", colorHex: "#c47e96" });
      expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBeGreaterThan(0);
      const recipes = await fetchSimilarRecipes({ session_id: sid, target_color: "#c47e96", limit: 12 });
      const nearby = recipes.items.find((item) => item.hex.toLowerCase() === "#c58096");
      expect(nearby).toBeDefined();
      expect(await useConverterStore.getState().replaceSharedSelectionColor(nearby!.hex)).toBe(true);
      const edited = await getEditorSelection(sid);
      expect(edited.selected_color_hexes.map((hex) => hex.toLowerCase())).toContain(nearby!.hex.toLowerCase());
      useConverterStore.getState().setTargetWidthMm(64);
      expect(useConverterStore.getState().sessionId).toBe(sid);
      expect(useConverterStore.getState().preview_width_mm).toBe(62);
      const archive = await save();
      if (process.env.LUMINA_PROJECT_TEST_OUTPUT) await writeFile(process.env.LUMINA_PROJECT_TEST_OUTPUT, archive);
      await closeSession(sid);
      sessions.delete(sid);
      useConverterStore.setState({ ...DEFAULT_STATE, lutList: [], lutListFull: [] });
      for (const bytes of [archive, null]) {
        const project = await parseProject(bytes ?? await save());
        await registry.restore(project, { projectId: project.project.projectId, revisionId: project.project.revisionId, runtimeEpoch: 1 });
        const restored = useConverterStore.getState();
        sessions.add(restored.sessionId!);
        expect(restored.target_width_mm).toBe(64);
        expect(restored.preview_width_mm).toBe(64);
        expect(restored.previewPixelWidth).toBe(640);
        expect(restored.regionReplacementCount).toBeGreaterThan(0);
        const selected = await getEditorSelection(restored.sessionId!);
        expect(selected.selected_pixel_count).toBeGreaterThan(0);
        expect(selected.selected_color_hexes.map((hex) => hex.toLowerCase())).toEqual([nearby!.hex.toLowerCase()]);
      }
    } finally {
      const active = useConverterStore.getState().sessionId;
      if (active) sessions.add(active);
      useConverterStore.setState({ ...DEFAULT_STATE });
      await Promise.all([...sessions].map((sid) => closeSession(sid)));
      apiClient.defaults.baseURL = baseURL;
    }
  }, 180_000);
});

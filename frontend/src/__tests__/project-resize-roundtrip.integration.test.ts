import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import apiClient from "../api/client";
import { ColorMode, ModelingMode } from "../api/types";
import { convertGenerate, fetchSimilarRecipes, getEditorSelection } from "../api/converter";
import { closeSession } from "../api/session";
import { createConverterProjectAdapter } from "../project/adapters/converterAdapter";
import { ProjectAdapterRegistry } from "../project/adapters/registry";
import { parseProject, serializeProject } from "../project/archive";
import { createProjectSnapshot } from "../project/identity";
import { converterDocumentHistory, DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { buildGenerateParams } from "../stores/converter/requests";
import { buildConversionSourceParams } from "../stores/converter/sources";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

// Opt-in production API test: start an isolated api_server.py, then run with
// LUMINA_PROJECT_TEST_API=http://127.0.0.1:<port>/api. No API calls are mocked.
describe.skipIf(!process.env.LUMINA_PROJECT_TEST_API)("edited project resize roundtrip against a live backend", () => {
  it.each(["region", "single-pixel-recipe", "hifi-region"])("preserves %s edits through resize, save, reopen and preview", async (edit) => {
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
      useSettingsStore.setState({ ...DEFAULT_SETTINGS, svgPixelsPerMm: edit === "hifi-region" ? 18.1 : 10 });
      const fixture = edit === "single-pixel-recipe" ? "single_pixel_edit.svg" : "dynamic_material_lifecycle.svg";
      const image = await readFile(resolve("../tests/fixtures/svg_vector", fixture));
      useConverterStore.setState({
        ...DEFAULT_STATE, imageFile: new File([new Uint8Array(image)], fixture, { type: "image/svg+xml" }),
        source_version: "legacy", lut_name: "bambulab - bambulab_pla_basic_cmyw",
        lut_names: ["bambulab - bambulab_pla_basic_cmyw"], color_mode: ColorMode.FOUR_COLOR_CMYW,
        modeling_mode: edit === "hifi-region" ? ModelingMode.HIGH_FIDELITY : ModelingMode.VECTOR, target_width_mm: 62,
      });
      await useConverterStore.getState().submitPreview();
      const initial = useConverterStore.getState();
      expect(initial.error).toBeNull();
      expect(initial.sessionId).toBeTruthy();
      const sid = initial.sessionId!;
      const editorPixelWidth = initial.previewPixelWidth;
      sessions.add(sid);
      const smallest = [...initial.palette].sort((a, b) => a.pixel_count - b.pixel_count)[0];
      await initial.applySelectionMutation({ operation: "same-color-toggle", colorHex:
        edit === "region" ? "#c47e96" : `#${smallest.matched_hex}` });
      expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBeGreaterThan(0);
      const recipes = await fetchSimilarRecipes({ session_id: sid, target_color: "#c47e96", limit: 12 });
      const nearby = recipes.items.find((item) => item.hex.toLowerCase() === "#c58096");
      expect(nearby).toBeDefined();
      if (edit !== "single-pixel-recipe") {
        expect(await useConverterStore.getState().replaceSharedSelectionColor(nearby!.hex)).toBe(true);
      } else {
        const selection = useConverterStore.getState().selectionDocument!;
        expect(selection.selected_pixel_count).toBe(1);
        await useConverterStore.getState().applyCustomRecipeOverride(
          [`__editor_selection__:${selection.selection_revision}`], [1, 0, 1, 0, 1],
        );
        expect(useConverterStore.getState().error).toBeNull();
        expect(useConverterStore.getState().recipe_overrides).toHaveLength(1);
      }
      const edited = await getEditorSelection(sid);
      const printWidth = edit === "single-pixel-recipe" ? 31 : 64;
      useConverterStore.getState().setTargetWidthMm(printWidth);
      expect(useConverterStore.getState().sessionId).toBe(sid);
      expect(useConverterStore.getState().preview_width_mm).toBe(62);
      const archive = await save();
      if (process.env.LUMINA_PROJECT_TEST_OUTPUT) await writeFile(`${process.env.LUMINA_PROJECT_TEST_OUTPUT}-${edit}.lum`, archive);
      await closeSession(sid);
      sessions.delete(sid);
      useConverterStore.setState({ ...DEFAULT_STATE, lutList: [], lutListFull: [] });
      for (const bytes of [archive, null]) {
        const project = await parseProject(bytes ?? await save());
        await registry.restore(project, { projectId: project.project.projectId, revisionId: project.project.revisionId, runtimeEpoch: 1 });
        const restored = useConverterStore.getState();
        sessions.add(restored.sessionId!);
        expect(restored.target_width_mm).toBe(printWidth);
        expect(restored.preview_width_mm).toBe(62);
        expect(restored.previewPixelWidth).toBe(editorPixelWidth);
        const selected = await getEditorSelection(restored.sessionId!);
        expect(selected.selected_pixel_count).toBe(edited.selected_pixel_count);
        expect(selected.selected_color_hexes).toEqual(edited.selected_color_hexes);
        if (edit === "single-pixel-recipe") expect(restored.recipe_overrides[0].recipe).toEqual([1, 0, 1, 0, 1]);
      }
      let generated: { sessionId: string; url: string } | null = null;
      if (edit === "single-pixel-recipe" && process.env.LUMINA_PROJECT_TEST_GENERATE) {
        const state = useConverterStore.getState();
        const params = buildGenerateParams(state, useSettingsStore.getState(), buildConversionSourceParams(state)!, undefined, undefined);
        expect(params.target_width_mm).toBe(31);
        const result = await convertGenerate(state.sessionId!, params);
        expect(result.status).toBe("ok");
        generated = { sessionId: state.sessionId!, url: result.download_url };
      }
      // The refresh button must preserve the same editing basis as project open.
      useConverterStore.getState().setTargetWidthMm(93);
      await useConverterStore.getState().submitPreview();
      const refreshed = useConverterStore.getState();
      sessions.add(refreshed.sessionId!);
      expect(refreshed.error).toBeNull();
      expect(refreshed.target_width_mm).toBe(93);
      expect(refreshed.preview_width_mm).toBe(62);
      expect(refreshed.previewPixelWidth).toBe(editorPixelWidth);
      const selected = await getEditorSelection(refreshed.sessionId!);
      expect(selected.selected_pixel_count).toBe(edited.selected_pixel_count);
      expect(selected.selected_color_hexes).toEqual(edited.selected_color_hexes);
      const expanded = await parseProject(await save());
      await registry.restore(expanded, { projectId: expanded.project.projectId, revisionId: expanded.project.revisionId, runtimeEpoch: 2 });
      const reopened = useConverterStore.getState();
      sessions.add(reopened.sessionId!);
      expect(reopened.target_width_mm).toBe(93);
      expect(reopened.previewPixelWidth).toBe(editorPixelWidth);
      expect((await getEditorSelection(reopened.sessionId!)).selected_pixel_count).toBe(edited.selected_pixel_count);
      await reopened.applySelectionMutation({ operation: "clear" });
      expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBe(0);
      await converterDocumentHistory.undo();
      expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBe(edited.selected_pixel_count);
      await converterDocumentHistory.redo();
      expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBe(0);
      if (generated) {
        await closeSession(generated.sessionId);
        sessions.delete(generated.sessionId);
        const download = await apiClient.get(new URL(generated.url, apiClient.defaults.baseURL).href, { responseType: "arraybuffer" });
        expect(download.status).toBe(200);
        if (process.env.LUMINA_PROJECT_TEST_OUTPUT) await writeFile(`${process.env.LUMINA_PROJECT_TEST_OUTPUT}-31mm.3mf`, new Uint8Array(download.data));
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

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProjectWorkspace from "../projects/ProjectWorkspace";
import { translations } from "../../i18n/translations";
import { DEFAULT_STATE, useConverterStore } from "../../stores/converter";
import { useProjectSessionStore } from "../../stores/projectSessionStore";
import { useWidgetStore } from "../../stores/widgetStore";
import { saveCurrentProject, useProjectUi } from "../../project/controller";
import { exportShareCard } from "../../recipe/importFlow";

vi.mock("../../project/controller", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../project/controller")>(),
  startProjectTracking: () => () => {},
  saveCurrentProject: vi.fn().mockResolvedValue(true),
}));
vi.mock("../../recipe/importFlow", () => ({
  exportShareCard: vi.fn(),
  MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR: "Model surface recipes are not supported",
}));

function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: translations.project_export.zh }));
}
async function share() {
  openMenu();
  await act(async () => fireEvent.click(screen.getByRole("menuitem", { name: translations.recipe_export_btn.zh })));
}

describe("ProjectWorkspace sharing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(exportShareCard).mockResolvedValue("canceled");
    useConverterStore.setState({
      ...DEFAULT_STATE,
      imageFile: new File(["art"], "art.png", { type: "image/png" }),
      sessionId: "share-session",
      previewImageUrl: "/api/files/preview.png",
    });
    useWidgetStore.setState({ activeTab: "converter" });
    useProjectSessionStore.getState().reset();
    useProjectSessionStore.setState({ dirty: true, activeProjectId: "artwork", revisionId: "draft" });
    useProjectUi.setState({ name: "Artwork", centerOpen: false, notice: null, recoveryError: null });
  });

  it("exports a share card from the project menu without marking the project saved", async () => {
    vi.mocked(exportShareCard).mockResolvedValue("saved");
    render(<ProjectWorkspace />);
    await share();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(translations.file_save_saved.zh);
    expect(useProjectSessionStore.getState()).toMatchObject({ dirty: true, activeProjectId: "artwork", revisionId: "draft", savedRevisionId: null });
    expect(saveCurrentProject).not.toHaveBeenCalled();
    expect(exportShareCard).toHaveBeenCalledOnce();
  });

  it("keeps cancellation silent and reports browser downloads as downloads", async () => {
    render(<ProjectWorkspace />);
    await share();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    vi.mocked(exportShareCard).mockResolvedValue("download-started");
    await share();
    expect(screen.getByRole("status")).toHaveTextContent(translations.file_save_download_started.zh);
  });

  it("blocks duplicate exports and project writes while a share card is being captured", async () => {
    let complete!: (outcome: "saved") => void;
    vi.mocked(exportShareCard).mockReturnValue(new Promise(resolve => { complete = resolve; }));
    render(<ProjectWorkspace />);
    await share();
    expect(screen.getByRole("button", { name: translations.project_save.zh })).toBeDisabled();
    openMenu();
    expect(screen.getByRole("menuitem", { name: translations.recipe_export_btn.zh })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: translations.project_more.zh }));
    expect(screen.getByRole("menuitem", { name: translations.project_save_as.zh })).toBeDisabled();
    await act(async () => complete("saved"));
    await waitFor(() => expect(screen.getByRole("button", { name: translations.project_save.zh })).toBeEnabled());
    expect(exportShareCard).toHaveBeenCalledOnce();
  });

  it.each([
    [{ imageFile: null }, "recipe_export_error_no_image"],
    [{ previewImageUrl: null }, "recipe_export_error_no_preview"],
    [{ modelSurfaceEnabled: true }, "recipe_export_model_surface_unavailable"],
    [{ replacePreviewLoading: true }, "recipe_export_wait_edits"],
    [{ contentCommitStatus: "unknown" as const }, "recipe_export_wait_edits"],
  ])("explains why sharing is unavailable for %j", (state, reason) => {
    useConverterStore.setState(state);
    render(<ProjectWorkspace />);
    openMenu();
    const item = screen.getByRole("menuitem", { name: translations.recipe_export_btn.zh });
    expect(item).toBeDisabled();
    expect(item).toHaveAccessibleDescription(translations[reason].zh);
    fireEvent.click(item);
    expect(exportShareCard).not.toHaveBeenCalled();
  });

  it.each(["workshop", "vectorizer"] as const)("does not export another workspace's converter image from %s", (activeTab) => {
    useWidgetStore.setState({ activeTab });
    render(<ProjectWorkspace />);
    openMenu();
    expect(screen.queryByRole("menuitem", { name: translations.recipe_export_btn.zh })).not.toBeInTheDocument();
  });

  it("does not offer a single-image share card for batch conversion", () => {
    useConverterStore.setState({ batchMode: true });
    render(<ProjectWorkspace />);
    openMenu();
    expect(screen.queryByRole("menuitem", { name: translations.recipe_export_btn.zh })).not.toBeInTheDocument();
  });

  it.each([
    ["Request failed with status code 500", "服务器发生内部错误"],
    ["Failed to create cover PNG blob", translations.recipe_export_error_unknown.zh],
    ["Failed to load preview image for cover", translations.recipe_export_error_preview_load.zh],
    ["file_save_failed", translations.file_save_failed.zh],
  ])("shows a readable export error for %s", async (message, expected) => {
    vi.mocked(exportShareCard).mockRejectedValue(new Error(message));
    render(<ProjectWorkspace />);
    await share();
    expect(screen.getByRole("alert")).toHaveTextContent(expected);
    expect(screen.queryByText(message, { exact: true })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: translations.common_close.zh }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: translations.project_save.zh })).toBeEnabled();
  });
});

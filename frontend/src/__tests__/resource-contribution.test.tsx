import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import * as api from "../api/contributions";
import { ContributionDialog } from "../components/ResourceContribution";
import { useCommunityStore } from "../stores/communityStore";
import { prepareFeedbackImage } from "../utils/feedbackImages";

vi.mock("../api/contributions", () => ({
  getContributionConnection: vi.fn(), startContributionConnection: vi.fn(), disconnectContribution: vi.fn(),
  prepareContribution: vi.fn(), submitContribution: vi.fn(), fetchContributionHistory: vi.fn(),
  checkOriginalSource: vi.fn(),
  getContributionQueue: vi.fn().mockResolvedValue({ enabled: false, account_id: null, items: [] }),
  prepareQueuedContribution: vi.fn(),
  prepareContributionRevision: vi.fn(), changeContributionReview: vi.fn(),
}));
vi.mock("../utils/feedbackImages", async () => ({
  ...(await vi.importActual("../utils/feedbackImages")),
  prepareFeedbackImage: vi.fn(),
}));
vi.mock("../api/extractor", () => ({ listGradientCardMaterials: vi.fn().mockResolvedValue({ materials: [] }), installExtractedLut: vi.fn() }));
vi.mock("../i18n/context", () => ({ useI18n: () => ({ lang: "zh", t: translate }) }));
const translate = (key: string) => key;

function chooseOrigin(option = "contribution_origin_original") {
  fireEvent.click(screen.getByRole("combobox", { name: "contribution_origin" }));
  fireEvent.click(screen.getByRole("option", { name: option }));
}

const EXPECTED_MATERIAL_PRINT_IMAGES = [
  { role: "white_card", data: "cHJpbnQtcGhvdG8=" },
  { role: "black_card", data: "cHJpbnQtcGhvdG8=" },
  { role: "finished_print", data: "cHJpbnQtcGhvdG8=" },
];

const EXPECTED_LUT_PRINT_IMAGES = [
  { role: "calibration_board", data: "cHJpbnQtcGhvdG8=" },
  { role: "finished_print", data: "cHJpbnQtcGhvdG8=" },
];

async function attachSlotPhoto(role: api.PrintImageRole, name = `${role}.jpg`, expectedAlt?: string) {
  const file = new File(["photo"], name, { type: "image/jpeg" });
  fireEvent.change(screen.getByTestId(`contribution-print-photo-input-${role}`), {
    target: { files: [file] },
  });
  await screen.findByAltText(expectedAlt ?? new RegExp(`contribution_print_slot_${role}`));
}

async function attachPrintPhoto(kind: "materials" | "luts" = "materials") {
  if (kind === "materials") {
    await attachSlotPhoto("white_card");
    await attachSlotPhoto("black_card");
    await attachSlotPhoto("finished_print", "finished.jpg", "contribution_print_slot_finished_print 1");
    return;
  }
  await attachSlotPhoto("calibration_board", "board.jpg", "contribution_print_slot_calibration_board 1");
  await attachSlotPhoto("finished_print", "finished.jpg", "contribution_print_slot_finished_print 1");
}

beforeEach(() => {
  useCommunityStore.setState({ connection: null, error: "", connectionError: "" });
  vi.clearAllMocks();
  vi.mocked(api.getContributionConnection).mockResolvedValue({ state: "connected", subject: "maker", display_name: "Maker", web_url: "http://localhost:8018" });
  vi.mocked(api.prepareContribution).mockResolvedValue({
    kind: "materials", key: "Brand/Red", fingerprint: "a".repeat(64), bytes: 100,
    display: { material_name: "Red", brand: "Brand", material_type: "PLA" }, compatibility: {},
  });
  vi.mocked(api.submitContribution).mockResolvedValue({ kind: "materials", status: "pending" });
  vi.mocked(api.checkOriginalSource).mockResolvedValue({ eligible: false });
  vi.mocked(prepareFeedbackImage).mockResolvedValue("cHJpbnQtcGhvdG8=");
});

it("withdraws a pending review only after confirmation and reloads the account history", async () => {
  const pending = { kind: "luts" as const, lut_id: "lut_one", revision_id: "rev_one", status: "pending", display: { name: "Owned LUT" } };
  vi.mocked(api.fetchContributionHistory).mockResolvedValueOnce([pending]).mockResolvedValue([{ ...pending, status: "withdrawn" }]);
  vi.mocked(api.changeContributionReview).mockResolvedValue({ ...pending, status: "withdrawn" });
  render(<ContributionDialog kind="materials" onClose={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "contribution_withdraw" }));
  expect(api.changeContributionReview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "contribution_withdraw_confirm" }));
  await screen.findByText(/contribution_lut · withdrawn/);
  expect(api.changeContributionReview).toHaveBeenCalledWith({ kind: "luts", resource_id: "lut_one", revision_id: "rev_one" }, "maker", "withdraw");
  expect(screen.getByRole("button", { name: "contribution_resubmit" })).toBeEnabled();
});

it("edits an owned revision using its server snapshot and submits the same resource identity", async () => {
  const revision = { kind: "materials" as const, resource_id: "mat_owned", revision_id: "rev_one" };
  vi.mocked(api.prepareContributionRevision).mockResolvedValue({
    kind: "materials", key: "revision:mat_owned:rev_one", fingerprint: "c".repeat(64), bytes: 100,
    display: { material_name: "Owned red", brand: "Brand", material_type: "PLA", attribution: { relationship: "original" } }, compatibility: {},
  });
  render(<ContributionDialog kind="materials" resourceKey="revision:mat_owned:rev_one" revision={revision} onClose={vi.fn()} />);
  await screen.findByDisplayValue("Owned red");
  expect(api.prepareContributionRevision).toHaveBeenCalledWith(revision, "maker");
  expect(api.prepareContribution).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("resources_color_name"), { target: { value: "Corrected red" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "contribution_submit" }));
  await waitFor(() => expect(api.submitContribution).toHaveBeenCalledWith(expect.objectContaining({ revision,
    fingerprint: "c".repeat(64), product: expect.objectContaining({ color_name: "Corrected red" }) })));
});

it("requires explicit permission and submits the selected resource with product details", async () => {
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={vi.fn()} />);
  await screen.findByDisplayValue("Red");
  const submit = screen.getByRole("button", { name: "contribution_submit" });
  expect(submit).toBeDisabled();
  fireEvent.change(screen.getByLabelText("resources_series"), { target: { value: "Basic" } });
  chooseOrigin();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(submit).toBeDisabled();
  await attachSlotPhoto("white_card");
  await attachSlotPhoto("black_card");
  expect(submit).toBeDisabled();
  await attachSlotPhoto("finished_print", "finished.jpg", "contribution_print_slot_finished_print 1");
  expect(submit).toBeEnabled();
  fireEvent.click(submit);
  await waitFor(() => expect(api.submitContribution).toHaveBeenCalledWith(expect.objectContaining({
    kind: "materials", key: "Brand/Red", consent: true, account_id: "maker",
    product: expect.objectContaining({ brand: "Brand", material_type: "PLA", series: "Basic" }),
    attribution: { relationship: "original" },
    print_images: EXPECTED_MATERIAL_PRINT_IMAGES,
  })));
  await waitFor(() => expect(screen.getByText(/contribution_received/)).toBeVisible());
});

it("submits optional regional names and several purchase links without flattening them", async () => {
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={vi.fn()} />);
  await screen.findByDisplayValue("Red");
  fireEvent.click(screen.getByText("contribution_regional_names"));
  fireEvent.change(screen.getByLabelText("contribution_name_cn"), { target: { value: "中国商品名" } });
  fireEvent.change(screen.getByLabelText("contribution_name_intl"), { target: { value: "International name" } });
  fireEvent.click(screen.getByText("contribution_product_link"));
  fireEvent.change(screen.getByLabelText("resources_product_page"), { target: { value: "https://shop.test/cn" } });
  fireEvent.click(screen.getByRole("button", { name: "contribution_add_link" }));
  fireEvent.change(screen.getAllByLabelText(/resources_product_page/)[1], { target: { value: "https://shop.test/global" } });
  chooseOrigin();
  await attachPrintPhoto();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "contribution_submit" }));
  await waitFor(() => expect(api.submitContribution).toHaveBeenCalledWith(expect.objectContaining({
    product: expect.objectContaining({ market_names: { CN: "中国商品名", INTL: "International name" },
      purchase_url: "https://shop.test/cn", purchase_links: [{ url: "https://shop.test/global", market: "ALL" }] }),
    print_images: EXPECTED_MATERIAL_PRINT_IMAGES,
  })));
});

it("prefills structured LUT products by channel instead of metadata array order", async () => {
  vi.mocked(api.prepareContribution).mockResolvedValue({
    kind: "luts", key: "BW", fingerprint: "b".repeat(64), bytes: 96, compatibility: {},
    display: { name: "BW", filaments: [{ slot: 0, color_name: "White" }, { slot: 1, color_name: "Black" }] },
  });
  render(<ContributionDialog kind="luts" resourceKey="BW" onClose={vi.fn()} initialDisplay={{
    brand: "Brand", material_type: "PLA",
    filaments: [{ slot: 1, series: "Matte", color_name: "Black", color_code: "10102" },
      { slot: 0, series: "Basic", color_name: "White", color_code: "10100",
        purchase_links: [{ url: "https://example.com/white", market: "INTL" }] }],
  }} />);
  await screen.findByDisplayValue("10100");
  chooseOrigin();
  await attachSlotPhoto("calibration_board", "board.jpg", "contribution_print_slot_calibration_board 1");
  expect(screen.getByRole("button", { name: "contribution_submit" })).toBeDisabled();
  await attachSlotPhoto("finished_print", "finished.jpg", "contribution_print_slot_finished_print 1");
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "contribution_submit" }));
  await waitFor(() => expect(api.submitContribution).toHaveBeenCalledWith(expect.objectContaining({
    filaments: [
      expect.objectContaining({ color_name: "White", series: "Basic", color_code: "10100", purchase_url: "https://example.com/white", market: "INTL" }),
      expect.objectContaining({ color_name: "Black", series: "Matte", color_code: "10102" }),
    ],
    print_images: EXPECTED_LUT_PRINT_IMAGES,
  })));
});

it("connects the existing account without submitting or losing entered fields", async () => {
  vi.mocked(api.getContributionConnection).mockResolvedValue({ state: "disconnected", web_url: "http://localhost:8018" });
  vi.mocked(api.startContributionConnection).mockResolvedValue({
    state: "pending", code: "ABCDEFGH23", connect_url: "http://localhost:8018/#/studio-connect?code=ABCDEFGH23", web_url: "http://localhost:8018",
  });
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={vi.fn()} />);
  await screen.findByDisplayValue("Red");
  fireEvent.change(screen.getByLabelText("resources_series"), { target: { value: "Basic" } });
  fireEvent.click(screen.getByRole("button", { name: "contribution_connect" }));
  await waitFor(() => expect(screen.getByText("ABCDEFGH23")).toBeVisible());
  expect(screen.getByRole("link", { name: "contribution_browser" })).toHaveAttribute("href", "http://localhost:8018/#/studio-connect?code=ABCDEFGH23");
  expect(screen.getByDisplayValue("Basic")).toBeVisible();
  expect(api.submitContribution).not.toHaveBeenCalled();
});

it("retains the form after a failed submission and allows a retry", async () => {
  vi.mocked(api.submitContribution).mockRejectedValueOnce(new Error("offline"));
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={vi.fn()} />);
  await screen.findByDisplayValue("Red");
  chooseOrigin();
  await attachPrintPhoto();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "contribution_submit" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "contribution_submit" })).toBeEnabled());
  expect(screen.getByDisplayValue("Red")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "contribution_submit" }));
  await screen.findByText(/contribution_received/);
  expect(api.submitContribution).toHaveBeenCalledTimes(2);
});

it("shows material and LUT submissions from the same account history", async () => {
  vi.mocked(api.fetchContributionHistory).mockResolvedValue([
    { kind: "materials", submission_id: "a", status: "needs_changes", display: { material_name: "Red" }, latest_decision: { comment: "Please add a color code" } },
    { kind: "luts", lut_id: "b", status: "approved", display: { name: "Palette" } },
  ]);
  render(<ContributionDialog kind="materials" onClose={vi.fn()} />);
  await waitFor(() => expect(screen.getByText("Red")).toBeVisible());
  expect(screen.getByText("Palette")).toBeVisible();
  expect(screen.getByText("Please add a color code")).toBeVisible();
});

it("can retry a failed preparation without showing an editable incomplete form", async () => {
  vi.mocked(api.prepareContribution).mockRejectedValueOnce({ response: { status: 422 } });
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={vi.fn()} />);
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "contribution_submit" })).toBeDisabled();
  expect(screen.queryByLabelText("contribution_name *")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "contribution_retry_prepare" }));
  await screen.findByDisplayValue("Red");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(api.prepareContribution).toHaveBeenCalledTimes(2);
});

it("keeps the approval account and all close actions locked while submitting", async () => {
  let resolve!: (value: api.ContributionReceipt) => void;
  vi.mocked(api.submitContribution).mockReturnValue(new Promise(done => { resolve = done; }));
  const close = vi.fn();
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={close} />);
  await screen.findByDisplayValue("Red");
  chooseOrigin();
  await attachPrintPhoto();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "contribution_submit" }));
  expect(screen.getByRole("button", { name: "contribution_disconnect" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "common_close" })).toBeDisabled();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(close).not.toHaveBeenCalled();
  resolve({ kind: "materials", status: "pending" });
  await screen.findByText(/contribution_received/);
  expect(screen.getByRole("button", { name: "common_close" })).toBeEnabled();
});

it("requires an origin choice and confirms permission again when that choice changes", async () => {
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={vi.fn()} />);
  await screen.findByDisplayValue("Red");
  expect(screen.getByRole("link", { name: "resources_data_license" })).toHaveAttribute("href", "/data-license.html");
  expect(screen.queryByRole("link", { name: "resources_lumina_license" })).toBeNull();
  await waitFor(() => expect(screen.getByText("resources_license_unspecified")).toBeVisible());
  await attachPrintPhoto();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button", { name: "contribution_submit" })).toBeDisabled();
  chooseOrigin();
  expect(screen.getByRole("link", { name: "resources_lumina_license" })).toHaveAttribute("href", "/data-license.html");
  expect(screen.getByRole("checkbox", { name: "contribution_original_consent" })).not.toBeChecked();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button", { name: "contribution_submit" })).toBeEnabled();
  chooseOrigin("contribution_origin_adapted");
  expect(screen.getByRole("checkbox", { name: "contribution_consent" })).not.toBeChecked();
  expect(screen.queryByRole("link", { name: "resources_lumina_license" })).toBeNull();
  expect(screen.getByText("resources_license_unspecified")).toBeVisible();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByRole("button", { name: "contribution_submit" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("contribution_original_author *"), { target: { value: "Jane" } });
  fireEvent.change(screen.getByLabelText("contribution_source_url *"), { target: { value: "https://example.org/source" } });
  fireEvent.change(screen.getByLabelText(/contribution_rights_basis/), { target: { value: "CC-BY-4.0" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "contribution_submit" }));
  await waitFor(() => expect(api.submitContribution).toHaveBeenCalledWith(expect.objectContaining({
    attribution: { relationship: "adapted", original_author: "Jane", source_url: "https://example.org/source", rights_basis: "CC-BY-4.0" },
    print_images: EXPECTED_MATERIAL_PRINT_IMAGES,
  })));
});

it.each([undefined, "CC-BY-4.0", "LicenseRef-Lumina-Data-1.0"])("shows the actual installed license %s separately from contribution terms", async (license) => {
  const prepared = await vi.mocked(api.prepareContribution)("materials", "Brand/Red");
  vi.mocked(api.prepareContribution).mockResolvedValue({
    ...prepared, display: { ...prepared.display, license },
    origin: { reference: { kind: "materials", resource_id: "mat_source", revision_id: "rev_source", content_hash: "sha256:" + "a".repeat(64) },
      modified: false, original_author: "Original maker", rights_basis: license || "", license },
  });
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={vi.fn()} />);
  await waitFor(() => expect(screen.getByDisplayValue("Original maker")).toBeVisible());
  expect(screen.getByRole("link", { name: "resources_data_license" })).toHaveAttribute("href", "/data-license.html");
  if (!license) {
    expect(screen.getByText("resources_license_unspecified")).toBeVisible();
    expect(screen.queryByRole("link", { name: "resources_lumina_license" })).toBeNull();
  } else {
    expect(screen.getByRole("link", { name: license === "CC-BY-4.0" ? license : "resources_lumina_license" }))
      .toHaveAttribute("href", license === "CC-BY-4.0" ? "https://creativecommons.org/licenses/by/4.0/" : "/data-license.html");
  }
});

it("keeps existing original-work terms without asking for a new Lumina grant", async () => {
  const prepared = await vi.mocked(api.prepareContribution)("materials", "Brand/Red");
  vi.mocked(api.prepareContribution).mockResolvedValue({ ...prepared, display: { ...prepared.display, license: "CC-BY-4.0" } });
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={vi.fn()} />);
  await screen.findByDisplayValue("Red");
  chooseOrigin();
  expect(screen.getByRole("checkbox", { name: "contribution_consent" })).not.toBeChecked();
  expect(screen.queryByRole("checkbox", { name: "contribution_original_consent" })).toBeNull();
  expect(screen.getByRole("link", { name: "CC-BY-4.0" })).toHaveAttribute("href", "https://creativecommons.org/licenses/by/4.0/");
});

it("retains public origins without offering an original-work declaration", async () => {
  const prepared = await vi.mocked(api.prepareContribution)("materials", "Brand/Red");
  vi.mocked(api.prepareContribution).mockResolvedValue({
    ...prepared, origin: { reference: { kind: "materials", resource_id: "mat_original", revision_id: "rev_1", content_hash: "sha256:" + "a".repeat(64) },
      original_author: "Jane", rights_basis: "CC-BY-4.0", modified: false },
  });
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={vi.fn()} />);
  await screen.findByDisplayValue("Jane");
  fireEvent.click(screen.getByText("contribution_origin_linked"));
  await waitFor(() => expect(screen.getByText(/mat_original.*rev_1/)).toBeVisible());
  fireEvent.click(screen.getByRole("combobox", { name: "contribution_origin" }));
  expect(screen.queryByRole("option", { name: "contribution_origin_original" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("option", { name: "contribution_origin_redistributed" }));
  await attachPrintPhoto();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "contribution_submit" }));
  await waitFor(() => expect(api.submitContribution).toHaveBeenCalledWith(expect.objectContaining({
    attribution: expect.objectContaining({ relationship: "redistributed", original_author: "Jane" }),
    print_images: EXPECTED_MATERIAL_PRINT_IMAGES,
  })));
});

it("lets the account owner choose their original public source and submit an update", async () => {
  const prepared = await api.prepareContribution("materials", "Brand/Red");
  const reference = {
    kind: "materials" as const, resource_id: "mat_original", revision_id: "rev_1",
    content_hash: "sha256:" + "a".repeat(64),
  };
  vi.mocked(api.prepareContribution).mockResolvedValue({
    ...prepared, origin: { reference, original_author: "Maker", rights_basis: "CC-BY-4.0", modified: false },
  });
  vi.mocked(api.checkOriginalSource).mockResolvedValue({ eligible: true });
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={vi.fn()} />);
  const source = await screen.findByRole("combobox", { name: "contribution_origin" });
  fireEvent.click(source);
  fireEvent.click(await screen.findByRole("option", { name: "contribution_origin_original" }));
  expect(api.checkOriginalSource).toHaveBeenCalledWith(reference, "maker");
  expect(screen.getByText("contribution_origin_update_original")).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: /contribution_original_author/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "contribution_submit" }));
  await waitFor(() => expect(api.submitContribution).toHaveBeenCalledWith(expect.objectContaining({
    attribution: { relationship: "original" },
    account_id: "maker",
  })));
});

it("disables submit when any required slot photo is removed and clears photos on account switch", async () => {
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" onClose={vi.fn()} />);
  await screen.findByDisplayValue("Red");
  chooseOrigin();
  fireEvent.click(screen.getByRole("checkbox"));
  const submit = screen.getByRole("button", { name: "contribution_submit" });
  expect(submit).toBeDisabled();
  await attachPrintPhoto("materials");
  expect(submit).toBeEnabled();
  fireEvent.click(
    screen.getByRole("button", {
      name: "contribution_print_photos_remove · contribution_print_slot_finished_print",
    }),
  );
  expect(screen.queryByAltText("contribution_print_slot_finished_print 1")).not.toBeInTheDocument();
  expect(submit).toBeDisabled();
  await attachSlotPhoto("finished_print", "second.jpg", "contribution_print_slot_finished_print 1");
  expect(submit).toBeEnabled();
  act(() => {
    useCommunityStore.setState({
      connection: { state: "connected", subject: "second_maker", display_name: "Second", web_url: "http://localhost:8018" },
    });
  });
  await waitFor(() => expect(screen.queryByAltText("contribution_print_slot_white_card")).not.toBeInTheDocument());
});

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import * as api from "../api/community";
import type { ResourceReport } from "../api/community";
import ResourceFeedback, { FeedbackDialog } from "../components/ResourceFeedback";
import ResourceReportHistory from "../components/ResourceReportHistory";
import { useCommunityStore } from "../stores/communityStore";
import { prepareFeedbackImage } from "../utils/feedbackImages";

vi.mock("../api/community", async () => ({
  ...await vi.importActual("../api/community"),
  fetchResourceContributor: vi.fn(), fetchMyResourceReports: vi.fn(), submitResourceReport: vi.fn(), fetchResourceReportHistory: vi.fn(), fetchResourceReportImage: vi.fn(),
}));
vi.mock("../utils/feedbackImages", async () => ({ ...await vi.importActual("../utils/feedbackImages"), prepareFeedbackImage: vi.fn() }));
vi.mock("../components/CommunityAccount", () => ({ CommunityConnection: () => <div>Account connection</div> }));
vi.mock("../i18n/context", () => ({ useI18n: () => ({ lang: "zh", t: translate }) }));
const translate = (key: string) => key;

const resource = { resource_id: "mat_red", revision_id: "revision_one", content_hash: "sha256:" + "a".repeat(64) };
const connection = { state: "connected" as const, subject: "maker", display_name: "Maker", email_verified: true, web_url: "https://example.test" };
const receipt: ResourceReport = { ...resource, report_id: "report_one", kind: "materials", category: "attribution",
  message: "Please check the original source.", evidence_url: "", status: "open", decision: "", created_at: "2026-11-16T00:00:00Z", decided_at: null };

beforeEach(() => {
  vi.clearAllMocks();
  useCommunityStore.setState({ connection, error: "", connectionError: "" });
  vi.mocked(api.fetchResourceContributor).mockResolvedValue({ contributor: { id: "public_id", display_name: "Contributor" } });
  vi.mocked(api.fetchMyResourceReports).mockResolvedValue({ subject: "maker", items: [] });
  vi.mocked(api.submitResourceReport).mockResolvedValue({ subject: "maker", item: receipt });
  vi.mocked(api.fetchResourceReportHistory).mockResolvedValue({ subject: "maker", items: [], has_more: false });
  vi.mocked(prepareFeedbackImage).mockResolvedValue("c2NyZWVuc2hvdA==");
  vi.mocked(api.fetchResourceReportImage).mockResolvedValue({ subject: "maker", data_url: "data:image/jpeg;base64,c2NyZWVuc2hvdA==" });
});

it("loads contributor information only after the detail action is opened", async () => {
  render(<ResourceFeedback kind="materials" resource={resource} />);
  expect(api.fetchResourceContributor).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "resource_feedback_open" }));
  await waitFor(() => expect(screen.getByText("Contributor")).toBeVisible());
  expect(api.fetchResourceContributor).toHaveBeenCalledWith("materials", resource);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByRole("dialog")).toHaveAccessibleName("resource_feedback_title");
});

it("keeps optional links and screenshots out of the ordinary text-only form", async () => {
  render(<FeedbackDialog kind="materials" resource={resource} onClose={vi.fn()} />);
  await screen.findByText("Contributor");
  await waitFor(() => expect(screen.getByRole("dialog")).toBeVisible());
  const link = screen.getByLabelText("resource_feedback_evidence");
  expect(link).not.toBeVisible();
  fireEvent.change(screen.getByLabelText("resource_feedback_message"), { target: { value: receipt.message } });
  expect(screen.getByRole("button", { name: "resource_feedback_submit" })).toBeEnabled();
  fireEvent.click(screen.getByText("resource_feedback_supplements"));
  await waitFor(() => expect(link).toBeVisible());
  expect(screen.getByRole("button", { name: "resource_feedback_add_image" })).toBeVisible();
});

it("pastes a screenshot, preserves it for a retry and removes it on an account change", async () => {
  vi.mocked(api.submitResourceReport).mockRejectedValue(new Error("Offline"));
  render(<FeedbackDialog kind="materials" resource={resource} onClose={vi.fn()} />);
  await screen.findByText("Contributor");
  const input = screen.getByLabelText("resource_feedback_message");
  fireEvent.change(input, { target: { value: receipt.message } });
  const file = new File(["screenshot"], "clipboard.png", { type: "image/png" });
  fireEvent.paste(input, { clipboardData: { files: [file] } });
  await waitFor(() => expect(screen.getByAltText("resource_feedback_image_number")).toBeVisible());
  expect(prepareFeedbackImage).toHaveBeenCalledWith(file);
  fireEvent.click(screen.getByRole("button", { name: "resource_feedback_submit" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "resource_feedback_submit" })).toBeEnabled());
  expect(vi.mocked(api.submitResourceReport).mock.calls[0][2].images).toEqual(["c2NyZWVuc2hvdA=="]);
  fireEvent.click(screen.getByRole("button", { name: "resource_feedback_submit" }));
  await waitFor(() => expect(api.submitResourceReport).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.submitResourceReport).mock.calls[0]).toEqual(vi.mocked(api.submitResourceReport).mock.calls[1]);
  vi.mocked(api.fetchMyResourceReports).mockResolvedValue({ subject: "second", items: [] });
  act(() => useCommunityStore.setState({ connection: { ...connection, subject: "second" } }));
  await waitFor(() => expect(screen.queryByAltText("resource_feedback_image_number")).not.toBeInTheDocument());
  expect(input).toHaveValue("");
});

it("ignores a screenshot that finishes processing after its account changed", async () => {
  let finish!: (value: string) => void;
  vi.mocked(prepareFeedbackImage).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  render(<FeedbackDialog kind="materials" resource={resource} onClose={vi.fn()} />);
  await screen.findByText("Contributor");
  fireEvent.paste(screen.getByLabelText("resource_feedback_message"), { clipboardData: { files: [new File(["x"], "a.png", { type: "image/png" })] } });
  vi.mocked(api.fetchMyResourceReports).mockResolvedValue({ subject: "second", items: [] });
  act(() => useCommunityStore.setState({ connection: { ...connection, subject: "second" } }));
  await act(async () => finish("c2NyZWVuc2hvdA=="));
  expect(screen.queryByAltText("resource_feedback_image_number")).not.toBeInTheDocument();
});

it.each(["file", "drop"] as const)("accepts screenshots through %s and allows removal", async source => {
  render(<FeedbackDialog kind="materials" resource={resource} onClose={vi.fn()} />);
  await screen.findByText("Contributor");
  const file = new File(["screenshot"], "chosen.png", { type: "image/png" });
  if (source === "file") {
    fireEvent.click(screen.getByText("resource_feedback_supplements"));
    fireEvent.change(screen.getByLabelText("resource_feedback_add_image"), { target: { files: [file] } });
  } else {
    fireEvent.drop(screen.getByLabelText("resource_feedback_message"), { dataTransfer: { files: [file] } });
  }
  await waitFor(() => expect(screen.getByAltText("resource_feedback_image_number")).toBeVisible());
  fireEvent.click(screen.getByRole("button", { name: "resource_feedback_remove_image" }));
  expect(screen.queryByAltText("resource_feedback_image_number")).not.toBeInTheDocument();
});

it("rejects too many screenshots without sending or silently dropping any", async () => {
  render(<FeedbackDialog kind="materials" resource={resource} onClose={vi.fn()} />);
  await screen.findByText("Contributor");
  const file = new File(["x"], "chosen.png", { type: "image/png" });
  fireEvent.paste(screen.getByLabelText("resource_feedback_message"), { clipboardData: { files: [file, file, file, file] } });
  expect(screen.getByText("resource_feedback_image_limit")).toBeVisible();
  expect(prepareFeedbackImage).not.toHaveBeenCalled();
  expect(api.submitResourceReport).not.toHaveBeenCalled();
});

it("keeps the screenshot and offers text-only submission when the server rejects its size", async () => {
  vi.mocked(api.submitResourceReport).mockRejectedValue({ isAxiosError: true, response: { status: 413, data: { detail: "Screenshot storage is full." } } });
  render(<FeedbackDialog kind="materials" resource={resource} onClose={vi.fn()} />);
  await screen.findByText("Contributor");
  fireEvent.change(screen.getByLabelText("resource_feedback_message"), { target: { value: receipt.message } });
  fireEvent.paste(screen.getByLabelText("resource_feedback_message"), { clipboardData: { files: [new File(["x"], "a.png", { type: "image/png" })] } });
  await waitFor(() => expect(screen.getByAltText("resource_feedback_image_number")).toBeVisible());
  fireEvent.click(screen.getByRole("button", { name: "resource_feedback_submit" }));
  await screen.findByText("resource_feedback_image_upload_failed");
  expect(screen.getByAltText("resource_feedback_image_number")).toBeVisible();
  expect(screen.getByLabelText("resource_feedback_message")).toHaveValue(receipt.message);
});

it("loads saved screenshots only when expanded and does not expose them to a different account", async () => {
  vi.mocked(api.fetchMyResourceReports).mockResolvedValue({ subject: "maker", items: [{ ...receipt,
    images: [{ image_id: "b".repeat(32), width: 10, height: 10, bytes: 50 }] }] });
  render(<FeedbackDialog kind="materials" resource={resource} onClose={vi.fn()} />);
  await screen.findByText("resource_feedback_status_open");
  expect(api.fetchResourceReportImage).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("resource_feedback_details"));
  await waitFor(() => expect(screen.getByAltText("resource_feedback_image_number")).toBeVisible());
  expect(api.fetchResourceReportImage).toHaveBeenCalledWith(receipt.report_id, "b".repeat(32), "maker");
  vi.mocked(api.fetchMyResourceReports).mockResolvedValue({ subject: "second", items: [] });
  act(() => useCommunityStore.setState({ connection: { ...connection, subject: "second" } }));
  await waitFor(() => expect(screen.queryByAltText("resource_feedback_image_number")).not.toBeInTheDocument());
});

it("allows anonymous contributor lookup while keeping report submission behind a verified account", async () => {
  useCommunityStore.setState({ connection: { state: "disconnected", web_url: "https://example.test" } });
  render(<FeedbackDialog kind="luts" resource={resource} onClose={vi.fn()} />);
  await waitFor(() => expect(screen.getByText("Contributor")).toBeVisible());
  expect(screen.queryByRole("button", { name: "resource_feedback_submit" })).not.toBeInTheDocument();
  expect(screen.getByText("Account connection")).toBeVisible();
  expect(api.fetchMyResourceReports).not.toHaveBeenCalled();
});

it("submits the exact revision and account and retains the request ID for a network retry", async () => {
  vi.mocked(api.submitResourceReport).mockRejectedValueOnce(new Error("Network unavailable"));
  render(<FeedbackDialog kind="materials" resource={resource} onClose={vi.fn()} />);
  await screen.findByText("Contributor");
  fireEvent.change(screen.getByLabelText("resource_feedback_message"), { target: { value: receipt.message } });
  fireEvent.click(screen.getByRole("button", { name: "resource_feedback_submit" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "resource_feedback_submit" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "resource_feedback_submit" }));
  await waitFor(() => expect(screen.getByText("resource_feedback_status_open")).toBeVisible());
  expect(api.submitResourceReport).toHaveBeenCalledTimes(2);
  const first = vi.mocked(api.submitResourceReport).mock.calls[0];
  const retry = vi.mocked(api.submitResourceReport).mock.calls[1];
  expect(first).toEqual(retry);
  expect(first[0]).toBe("materials"); expect(first[1]).toEqual(resource);
  expect(first[2]).toMatchObject({ account_id: "maker", category: "attribution", message: receipt.message });
  expect(first[2].request_id).toMatch(/^[a-f0-9]{32}$/);
  expect(screen.queryByRole("button", { name: "resource_feedback_submit" })).not.toBeInTheDocument();
});

it("discards a late private response when the connected account changes", async () => {
  let finish!: (value: { subject: string; items: ResourceReport[] }) => void;
  vi.mocked(api.fetchMyResourceReports).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  render(<FeedbackDialog kind="materials" resource={resource} onClose={vi.fn()} />);
  await screen.findByText("Contributor");
  vi.mocked(api.fetchMyResourceReports).mockResolvedValue({ subject: "second", items: [] });
  act(() => useCommunityStore.setState({ connection: { ...connection, subject: "second" } }));
  await act(async () => finish({ subject: "maker", items: [receipt] }));
  expect(screen.queryByText(receipt.message)).not.toBeInTheDocument();
  expect(screen.queryByText("resource_feedback_status_open")).not.toBeInTheDocument();
});

it("keeps author attribution without showing contact links from an older server", async () => {
  const legacyContributor = { id: "public_id", display_name: "Contributor", contact_url: "https://example.test/contact" };
  vi.mocked(api.fetchResourceContributor).mockResolvedValue({ contributor: legacyContributor });
  render(<FeedbackDialog kind="materials" resource={resource} onClose={vi.fn()} />);
  await waitFor(() => expect(screen.getByText("Contributor")).toBeVisible());
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.queryByText("resource_feedback_no_contact")).not.toBeInTheDocument();
  expect(screen.getByLabelText("resource_feedback_message")).toBeVisible();
});

it("keeps feedback about removed resources reachable through private history and clears it on account changes", async () => {
  vi.mocked(api.fetchResourceReportHistory).mockResolvedValue({ subject: "maker", items: [{ ...receipt, resource_id: "removed_resource", status: "resolved", decision: "Corrected the source." }], has_more: false });
  render(<ResourceReportHistory />);
  expect(api.fetchResourceReportHistory).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("resource_feedback_receipts"));
  await waitFor(() => expect(screen.getByText("Corrected the source.")).toBeVisible());
  fireEvent.click(screen.getByText("resource_feedback_target"));
  expect(screen.getByText(/removed_resource/)).toBeVisible();
  vi.mocked(api.fetchResourceReportHistory).mockResolvedValue({ subject: "second", items: [], has_more: false });
  act(() => useCommunityStore.setState({ connection: { ...connection, subject: "second" } }));
  await waitFor(() => expect(screen.queryByText("Corrected the source.")).not.toBeInTheDocument());
});

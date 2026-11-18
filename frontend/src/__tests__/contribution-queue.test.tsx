import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ContributionQueue from "../components/ContributionQueue";
import { ContributionDialog } from "../components/ResourceContribution";
import { useCommunityStore } from "../stores/communityStore";
import * as api from "../api/contributions";

const translate = (key: string) => key;
vi.mock("../i18n/context", () => ({ useI18n: () => ({ lang: "zh", t: translate }) }));
vi.mock("../components/CommunityAccount", () => ({ CommunityConnection: () => null }));
vi.mock("../api/extractor", () => ({ listGradientCardMaterials: vi.fn().mockResolvedValue({ materials: [] }) }));
vi.mock("../api/contributions", () => ({
  getContributionQueue: vi.fn(), configureAutomaticContributions: vi.fn(), actOnContributionQueue: vi.fn(),
  prepareQueuedContribution: vi.fn(), prepareContribution: vi.fn(), submitContribution: vi.fn(),
  fetchContributionHistory: vi.fn().mockResolvedValue([]),
}));

beforeEach(() => {
  vi.clearAllMocks();
  useCommunityStore.setState({ connection: { state: "connected", subject: "maker", email_verified: true, web_url: "" } });
  vi.mocked(api.getContributionQueue).mockResolvedValue({ enabled: false, account_id: null, items: [] });
  vi.mocked(api.configureAutomaticContributions).mockResolvedValue({ enabled: true, account_id: "maker", items: [] });
});

it("requires explicit consent before enabling future submissions", async () => {
  render(<ContributionQueue onReview={vi.fn()} />);
  fireEvent.click(await screen.findByText(/contribution_auto_title/));
  const enable = screen.getByRole("button", { name: "contribution_auto_enable" });
  expect(enable).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  await waitFor(() => expect(enable).toBeEnabled());
  fireEvent.click(enable);
  await waitFor(() => expect(api.configureAutomaticContributions).toHaveBeenCalledWith("maker", true, true));
  expect(await screen.findByRole("button", { name: "contribution_auto_disable" })).toBeEnabled();
});

it("unverified accounts can browse the queue but cannot enable uploads", async () => {
  useCommunityStore.setState({ connection: { state: "connected", subject: "maker", email_verified: false, web_url: "" } });
  render(<ContributionQueue onReview={vi.fn()} />);
  fireEvent.click(await screen.findByText(/contribution_auto_title/));
  expect(screen.getByRole("checkbox")).toBeDisabled();
  expect(screen.getByRole("button", { name: "contribution_auto_enable" })).toBeDisabled();
  expect(screen.getByText("contribution_auto_verify")).toBeVisible();
});

it("keeps incomplete items out of retry and original account items out of a new account", async () => {
  vi.mocked(api.getContributionQueue).mockResolvedValue({ enabled: false, account_id: "maker", items: [
    { id: "a", account: "maker", kind: "materials", resource_key: "red", name: "Red", state: "needs_review", reviewed: 0, reason: "details" },
    { id: "b", account: "other", kind: "luts", resource_key: "board", name: "Board", state: "paused", reviewed: 1, reason: "" },
  ] });
  const review = vi.fn();
  render(<ContributionQueue onReview={review} />);
  expect(await screen.findByText("Red")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "contribution_queue_review" }));
  expect(review).toHaveBeenCalledWith(expect.objectContaining({ id: "a" }));
  expect(screen.getByRole("button", { name: "contribution_queue_retry" })).toBeDisabled();
  expect(screen.getAllByRole("button", { name: "contribution_queue_cancel" })).toHaveLength(2);
});

it("reviews frozen data using the queue ID instead of rereading a changed resource", async () => {
  vi.mocked(api.prepareQueuedContribution).mockResolvedValue({
    kind: "materials", key: "Brand/Red", fingerprint: "a".repeat(64), bytes: 100, compatibility: {},
    display: { material_name: "Frozen Red", brand: "Brand", material_type: "PLA", attribution: { relationship: "original" } },
  });
  vi.mocked(api.submitContribution).mockResolvedValue({ kind: "materials", status: "queued" });
  render(<ContributionDialog kind="materials" resourceKey="Brand/Red" queueId={"b".repeat(32)} onClose={vi.fn()} />);
  await screen.findByDisplayValue("Frozen Red");
  expect(api.prepareContribution).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "contribution_submit" }));
  await waitFor(() => expect(api.submitContribution).toHaveBeenCalledWith(expect.objectContaining({
    queue_id: "b".repeat(32), fingerprint: "a".repeat(64), name: "Frozen Red",
  })));
  await waitFor(() => expect(screen.getByText(/contribution_queue_confirmed/)).toBeVisible());
});

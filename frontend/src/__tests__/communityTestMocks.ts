import { beforeEach, vi } from "vitest";
import { useCommunityStore } from "../stores/communityStore";
import * as accounts from "../api/contributions";
import * as community from "../api/community";

vi.mock("../api/contributions", () => ({
  getContributionConnection: vi.fn().mockResolvedValue({ state: "disconnected", web_url: "http://localhost:8018" }),
  startContributionConnection: vi.fn(),
  disconnectContribution: vi.fn(),
}));
vi.mock("../api/community", () => ({
  fetchResourceStats: vi.fn().mockResolvedValue({ items: [], subject: null }),
  fetchMyResourceActivity: vi.fn().mockResolvedValue({ items: [], subject: "maker" }),
  setResourceActivity: vi.fn(),
  fetchLocalResourceReferences: vi.fn().mockResolvedValue({}),
}));
beforeEach(() => {
  vi.mocked(accounts.getContributionConnection).mockResolvedValue({ state: "disconnected", web_url: "http://localhost:8018" });
  vi.mocked(community.fetchResourceStats).mockResolvedValue({ items: [], subject: null });
  vi.mocked(community.fetchMyResourceActivity).mockResolvedValue({ items: [], subject: "maker" });
  vi.mocked(community.fetchLocalResourceReferences).mockResolvedValue({});
  useCommunityStore.setState({
    connection: null, stats: {}, mine: { materials: {}, luts: {} }, mineLoaded: { materials: false, luts: false },
    references: { materials: {}, luts: {} }, pending: {}, error: "", connectionError: "", epoch: useCommunityStore.getState().epoch + 1,
  });
});

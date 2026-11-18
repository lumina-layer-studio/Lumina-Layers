import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import "./communityTestMocks";
import * as api from "../api/community";
import * as accounts from "../api/contributions";
import { useCommunityStore } from "../stores/communityStore";
import { CommunityFilter, ResourceActivityActions } from "../components/ui/ResourceActivity";
import CommunityAccountSetting from "../components/CommunityAccount";
import type { ResourceStats } from "../api/community";

const ref = { resource_id: "same-resource", revision_id: "rev1", content_hash: "abc" };
const stats: ResourceStats = { resource_id: ref.resource_id, likes: 12, saves: 7, downloads: 30,
  liked: false, saved: false, downloaded: false, revisions: [ref] };
const connected = { state: "connected" as const, subject: "maker", display_name: "Maker", web_url: "http://localhost:8018" };
beforeEach(() => {
  vi.mocked(api.fetchResourceStats).mockResolvedValue({ items: [stats], subject: null });
  vi.mocked(api.fetchMyResourceActivity).mockResolvedValue({ items: [], subject: "maker" });
  vi.mocked(accounts.getContributionConnection).mockResolvedValue({ state: "disconnected", web_url: "http://localhost:8018" });
});

it("shows real aggregate counts while signed out and opens the shared account dialog without writing", async () => {
  await useCommunityStore.getState().loadStats("materials", [ref.resource_id]);
  render(<ResourceActivityActions kind="materials" resource={ref} />);
  expect(screen.getByText("12")).toBeVisible();
  expect(screen.getByText("7")).toBeVisible();
  expect(screen.getByText("30")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "收藏到账号" }));
  await waitFor(() => expect(screen.getByRole("dialog", { name: "社区账号" })).toBeVisible());
  expect(api.setResourceActivity).not.toHaveBeenCalled();
});

it("identifies public snapshot counts and keeps genuine zero distinct from missing data", async () => {
  vi.mocked(api.fetchResourceStats).mockResolvedValue({
    subject: null, items: [{ ...stats, likes: 0, stats_source: "snapshot", snapshot_at: "2026-11-16T00:00:00Z" }],
  });
  await useCommunityStore.getState().loadStats("materials", [ref.resource_id]);
  render(<ResourceActivityActions kind="materials" resource={ref} />);
  expect(screen.getByText("0")).toBeVisible();
  expect(screen.getByRole("button", { name: "点赞" }).title).toContain("统计时间");
  expect(screen.getByRole("button", { name: "点赞" })).toHaveAttribute("aria-pressed", "false");
});

it("shares an account favorite between a card and a converter control and supports undo", async () => {
  useCommunityStore.getState().acceptConnection(connected);
  vi.mocked(api.fetchResourceStats).mockResolvedValue({ items: [stats], subject: "maker" });
  await useCommunityStore.getState().loadStats("materials", [ref.resource_id]);
  vi.mocked(api.setResourceActivity).mockImplementation(async (_kind, _ref, action, enabled) =>
    ({ item: { ...stats, [action]: enabled, saves: enabled ? 8 : 7 }, subject: "maker" }));
  render(<><ResourceActivityActions kind="materials" resource={ref} />
    <ResourceActivityActions kind="materials" resource={ref} favoriteOnly /></>);
  fireEvent.click(screen.getAllByRole("button", { name: "收藏到账号" })[0]);
  await waitFor(() => expect(screen.getAllByRole("button", { name: "取消账号收藏" })).toHaveLength(2));
  fireEvent.click(screen.getAllByRole("button", { name: "取消账号收藏" })[1]);
  await waitFor(() => expect(screen.getAllByRole("button", { name: "收藏到账号" })).toHaveLength(2));
  expect(api.setResourceActivity).toHaveBeenLastCalledWith("materials", ref, "saved", false, "maker");
});

it("clears personal state on account changes and ignores the old account's late response", async () => {
  useCommunityStore.getState().acceptConnection(connected);
  let resolve!: (value: { items: ResourceStats[]; subject: string }) => void;
  vi.mocked(api.fetchResourceStats).mockReturnValue(new Promise((done) => { resolve = done; }));
  const loading = useCommunityStore.getState().loadStats("luts", [ref.resource_id]);
  useCommunityStore.getState().acceptConnection({ ...connected, subject: "other" });
  resolve({ items: [{ ...stats, saved: true }], subject: "maker" });
  await loading;
  expect(useCommunityStore.getState().stats).toEqual({});
  expect(useCommunityStore.getState().mine.luts).toEqual({});
});

it("does not let an older statistics response undo a successful favorite", async () => {
  useCommunityStore.getState().acceptConnection(connected);
  let resolve!: (value: { items: ResourceStats[]; subject: string }) => void;
  vi.mocked(api.fetchResourceStats).mockReturnValue(new Promise((done) => { resolve = done; }));
  const loading = useCommunityStore.getState().loadStats("luts", [ref.resource_id]);
  vi.mocked(api.setResourceActivity).mockResolvedValue({ item: { ...stats, saved: true, saves: 8 }, subject: "maker" });
  await useCommunityStore.getState().toggle("luts", ref, "saved");
  resolve({ items: [stats], subject: "maker" });
  await loading;
  expect(useCommunityStore.getState().stats["luts:same-resource"].value?.saved).toBe(true);
});

it("uses a bounded memory cache and represents unknown resources without invented zeroes", async () => {
  vi.mocked(api.fetchResourceStats).mockClear().mockResolvedValue({ items: [], subject: null });
  await useCommunityStore.getState().loadStats("luts", [ref.resource_id]);
  await useCommunityStore.getState().loadStats("luts", [ref.resource_id]);
  expect(api.fetchResourceStats).toHaveBeenCalledTimes(1);
  render(<ResourceActivityActions kind="luts" resource={ref} />);
  expect(screen.getAllByText("—")).toHaveLength(3);
});

it("does not show stats for a custom registry resource with a colliding ID", async () => {
  useCommunityStore.getState().acceptConnection(connected);
  vi.mocked(api.fetchResourceStats).mockResolvedValue({ items: [stats], subject: "maker" });
  useCommunityStore.setState({ mine: { materials: {}, luts: { [ref.resource_id]: { ...stats, saved: true } } } });
  await useCommunityStore.getState().loadStats("luts", [ref.resource_id]);
  render(<ResourceActivityActions kind="luts" resource={{ ...ref, content_hash: "different" }} />);
  expect(screen.getAllByText("—")).toHaveLength(3);
  expect(screen.getByRole("button", { name: "收藏到账号" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "收藏到账号" })).toHaveAttribute("aria-pressed", "false");
});

it("waits for existing account favorites before deciding whether to save or unsave", async () => {
  useCommunityStore.getState().acceptConnection(connected);
  vi.mocked(api.fetchMyResourceActivity).mockResolvedValue({ items: [{ ...stats, saved: true }], subject: "maker" });
  vi.mocked(api.setResourceActivity).mockResolvedValue({ item: stats, subject: "maker" });
  await useCommunityStore.getState().toggle("luts", ref, "saved");
  expect(api.setResourceActivity).toHaveBeenLastCalledWith("luts", ref, "saved", false, "maker");
});
it("keeps settings to one account row and disconnects the same shared connection", async () => {
  vi.mocked(accounts.getContributionConnection).mockResolvedValue(connected);
  vi.mocked(accounts.disconnectContribution).mockResolvedValue({ state: "disconnected", web_url: connected.web_url });
  render(<CommunityAccountSetting />);
  await screen.findByText("Maker");
  fireEvent.click(screen.getByRole("button", { name: "管理连接" }));
  fireEvent.click(screen.getByRole("button", { name: "断开连接" }));
  await waitFor(() => expect(useCommunityStore.getState().connection?.state).toBe("disconnected"));
});

it("never persists community credentials or personal favorites in localStorage", async () => {
  const write = vi.spyOn(Storage.prototype, "setItem");
  useCommunityStore.getState().acceptConnection(connected);
  vi.mocked(api.setResourceActivity).mockResolvedValue({ item: { ...stats, saved: true }, subject: "maker" });
  await act(() => useCommunityStore.getState().toggle("luts", ref, "saved"));
  expect(write).not.toHaveBeenCalled();
  write.mockRestore();
});

it("selects a personal scope by keyboard and closes the custom menu without changing scope on Escape", () => {
  useCommunityStore.getState().acceptConnection(connected);
  const onChange = vi.fn();
  render(<CommunityFilter value="all" onChange={onChange} />);
  const trigger = screen.getByRole("combobox", { name: "账号资源筛选" });
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  expect(screen.getByRole("option", { name: "全部资源" })).toHaveAttribute("aria-selected", "true");
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.keyDown(trigger, { key: "Enter" });
  expect(onChange).toHaveBeenCalledWith("saved");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  onChange.mockClear();
  fireEvent.click(trigger);
  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(onChange).not.toHaveBeenCalled();
});

it("waits for login before applying a personal scope and forgets a cancelled request", async () => {
  const onChange = vi.fn();
  render(<CommunityFilter value="all" onChange={onChange} />);
  const trigger = screen.getByRole("combobox", { name: "账号资源筛选" });
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("option", { name: "我的收藏" }));
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("dialog", { name: "社区账号" })).toBeVisible());
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "关闭" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(trigger).toHaveFocus();
  await act(() => useCommunityStore.getState().acceptConnection(connected));
  expect(onChange).not.toHaveBeenCalled();
});

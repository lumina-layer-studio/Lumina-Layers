import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import "./communityTestMocks";
import * as api from "../api/contributions";
import { CommunityAccountDialog, CommunityConnection } from "../components/CommunityAccount";
import { useCommunityStore } from "../stores/communityStore";

const web_url = "http://localhost:8018";
const pending = { state: "pending" as const, web_url, code: "ABCDEFGH23", connect_url: `${web_url}/#/studio-connect?code=ABCDEFGH23` };
const connected = { state: "connected" as const, web_url, subject: "maker", display_name: "Maker" };
beforeEach(() => vi.clearAllMocks());

it("replaces the start action with approval and can explicitly restart a pending connection", async () => {
  vi.mocked(api.getContributionConnection).mockResolvedValue(pending);
  vi.mocked(api.disconnectContribution).mockResolvedValue({ state: "disconnected", web_url });
  vi.mocked(api.startContributionConnection).mockResolvedValue({ ...pending, code: "NEWCODE123" });
  render(<CommunityAccountDialog onClose={vi.fn()} />);
  await screen.findByText(pending.code);
  expect(screen.queryByRole("button", { name: "连接社区账号" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "打开耗材库" })).toHaveAttribute("href", pending.connect_url);
  expect(screen.getByRole("button", { name: "检查连接" })).not.toHaveAttribute("aria-pressed");
  fireEvent.click(screen.getByRole("button", { name: "重新连接" }));
  await screen.findByText("NEWCODE123");
  expect(api.disconnectContribution).toHaveBeenCalledOnce();
  expect(api.startContributionConnection).toHaveBeenCalledOnce();
});

it("uses one start request during loading and updates the same dialog after approval", async () => {
  let finish!: (value: typeof pending) => void;
  vi.mocked(api.startContributionConnection).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  render(<CommunityAccountDialog onClose={vi.fn()} />);
  const start = await screen.findByRole("button", { name: "连接社区账号" });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  expect(start).toBeDisabled();
  fireEvent.click(start);
  expect(api.startContributionConnection).toHaveBeenCalledOnce();
  await act(async () => finish(pending));
  vi.mocked(api.getContributionConnection).mockResolvedValue(connected);
  fireEvent.click(screen.getByRole("button", { name: "检查连接" }));
  await screen.findByText("Maker");
  expect(screen.queryByText(pending.code)).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "打开耗材库" })).not.toBeInTheDocument();
  expect(screen.getByText("已连接社区账号")).toBeInTheDocument();
});

it("recovers failed connection checks without displaying unrelated catalog errors", async () => {
  useCommunityStore.setState({ error: "catalog request failed" });
  vi.mocked(api.getContributionConnection).mockRejectedValueOnce(new Error("connection offline"));
  render(<CommunityAccountDialog onClose={vi.fn()} />);
  await screen.findByRole("alert");
  expect(screen.queryByText("catalog request failed")).not.toBeInTheDocument();
  vi.mocked(api.getContributionConnection).mockResolvedValue({ state: "disconnected", web_url });
  fireEvent.click(screen.getByRole("button", { name: "检查连接" }));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  expect(screen.getByRole("button", { name: "连接社区账号" })).toBeEnabled();
  expect(useCommunityStore.getState().error).toBe("");
});

it("does not allow the submitting form to disconnect its attribution account", async () => {
  vi.mocked(api.getContributionConnection).mockResolvedValue(connected);
  render(<CommunityConnection disabled />);
  await screen.findByText("Maker");
  const disconnect = screen.getByRole("button", { name: "断开连接" });
  expect(disconnect).toBeDisabled();
  fireEvent.click(disconnect);
  expect(api.disconnectContribution).not.toHaveBeenCalled();
});

it("distinguishes remembered desktop accounts from temporary browser connections", async () => {
  vi.mocked(api.getContributionConnection).mockResolvedValue({ ...connected, persistent: true });
  render(<CommunityAccountDialog onClose={vi.fn()} />);
  await screen.findByText("Maker");
  await waitFor(() => expect(screen.getByRole("dialog")).toBeVisible());
  expect(screen.getByText("已记住账号，下次自动登录。")).not.toBeVisible();
  fireEvent.click(screen.getByText("登录信息"));
  await waitFor(() => expect(screen.getByText("已记住账号，下次自动登录。")).toBeVisible());
  expect(screen.getByRole("link", { name: "管理邮箱与设备" })).toHaveAttribute("href", web_url + "/#/account");
  act(() => useCommunityStore.getState().acceptConnection({ ...connected, persistent: false }));
  expect(screen.getByText("重启软件后需要重新登录。")).toBeVisible();
  expect(screen.queryByText("已记住账号，下次自动登录。")).not.toBeInTheDocument();
});

it("guides a connected but unverified account to verification and rechecks without reconnecting", async () => {
  vi.mocked(api.getContributionConnection).mockResolvedValue({ ...connected, email_verified: false });
  render(<CommunityConnection requireVerifiedEmail />);
  await screen.findByText("Maker");
  expect(screen.getByRole("link", { name: "验证邮箱" })).toHaveAttribute("href", web_url + "/#/account");
  vi.mocked(api.getContributionConnection).mockResolvedValue({ ...connected, email_verified: true });
  fireEvent.click(screen.getByRole("button", { name: "刷新验证状态" }));
  await screen.findByRole("link", { name: "管理邮箱与设备" });
  expect(screen.queryByRole("button", { name: "刷新验证状态" })).not.toBeInTheDocument();
  expect(api.disconnectContribution).not.toHaveBeenCalled();
  expect(api.startContributionConnection).not.toHaveBeenCalled();
});

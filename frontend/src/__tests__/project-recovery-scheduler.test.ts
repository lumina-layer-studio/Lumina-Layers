import { afterEach, expect, it, vi } from "vitest";
import { createRecoveryScheduler } from "../project/recoveryScheduler";

afterEach(() => vi.useRealTimers());

it("recovers after a busy interval without requiring another edit", async () => {
  vi.useFakeTimers();
  let ready = false;
  const save = vi.fn().mockResolvedValue(undefined);
  const scheduler = createRecoveryScheduler({ needed: () => true, ready: () => ready, save, onError: vi.fn() });
  scheduler.request();
  await vi.advanceTimersByTimeAsync(5000);
  expect(save).not.toHaveBeenCalled();
  ready = true;
  await vi.advanceTimersByTimeAsync(2000);
  expect(save).toHaveBeenCalledOnce();
  scheduler.stop();
});

it("retries a failed write and serializes edits received during recovery", async () => {
  vi.useFakeTimers();
  let finish!: () => void;
  const save = vi.fn().mockRejectedValueOnce(new Error("disk busy"))
    .mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }))
    .mockResolvedValue(undefined);
  const onError = vi.fn();
  const scheduler = createRecoveryScheduler({ needed: () => true, ready: () => true, save, onError });
  scheduler.request();
  await vi.advanceTimersByTimeAsync(7000);
  expect(save).toHaveBeenCalledTimes(2);
  scheduler.request();
  await vi.advanceTimersByTimeAsync(20_000);
  expect(save).toHaveBeenCalledTimes(2);
  finish();
  await scheduler.settled();
  await vi.advanceTimersByTimeAsync(5000);
  expect(save).toHaveBeenCalledTimes(3);
  expect(onError).toHaveBeenCalledOnce();
  scheduler.stop();
});

it("stops when the project becomes clean or tracking is disposed", async () => {
  vi.useFakeTimers();
  let dirty = true;
  const save = vi.fn().mockResolvedValue(undefined);
  const scheduler = createRecoveryScheduler({ needed: () => dirty, ready: () => true, save, onError: vi.fn() });
  scheduler.request(); dirty = false;
  await vi.advanceTimersByTimeAsync(10_000);
  dirty = true; scheduler.request(); scheduler.stop();
  await vi.advanceTimersByTimeAsync(10_000);
  expect(save).not.toHaveBeenCalled();
});

it("does not starve recovery during continuous edits", async () => {
  vi.useFakeTimers();
  const save = vi.fn().mockResolvedValue(undefined);
  const scheduler = createRecoveryScheduler({ needed: () => true, ready: () => true, save, onError: vi.fn() });
  for (let index = 0; index < 8; index++) { scheduler.request(); await vi.advanceTimersByTimeAsync(4000); }
  expect(save).toHaveBeenCalledOnce();
  scheduler.stop();
});
